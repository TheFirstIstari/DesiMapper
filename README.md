# DesiMapper

**3D visualization of the DESI DR1 galaxy survey — ~40 million galaxies mapped across 14 billion years of cosmic time.**

DesiMapper is a high-performance data pipeline and dual-output visualization toolkit built around the [Dark Energy Spectroscopic Instrument (DESI) Data Release 1](https://data.desi.lbl.gov/public/dr1/). It produces:

1. **A cinematic 3D animation** — a fly-through of the DESI survey volume rendered in Blender, exported as a YouTube-ready MP4
2. **An interactive web viewer** — a real-time Three.js/WebGL point cloud hosted publicly, rendering ~500k galaxies at 60fps

---

## What is DESI?

DESI is a spectroscopic survey instrument on the Nicholas U. Mayall 4-meter Telescope at Kitt Peak National Observatory. DR1 contains spectra for over 40 million celestial objects observed across one third of the sky. This project uses the **Large Scale Structure (LSS) clustering catalogs** — the clustering-ready galaxy positions for four tracer types:

| Tracer | Colour | Redshift Range | Physics |
|--------|--------|----------------|---------|
| BGS — Bright Galaxy Survey | Orange | z = 0.01–0.6 | Nearby universe |
| LRG — Luminous Red Galaxies | Red | z = 0.4–1.1 | Massive ellipticals |
| ELG — Emission Line Galaxies | Teal | z = 0.8–1.6 | Star-forming galaxies |
| QSO — Quasars | Blue-violet | z = 0.8–2.1 | Active galactic nuclei |

---

## Quick Start

### Prerequisites

- [mise](https://mise.jdx.dev/) — manages Python 3.12 and Node 20 environments
- Python packages: `astropy`, `numpy`, `pyarrow`, `httpx`, `tqdm`, `polars`, `rich`
- [Blender 4.x](https://www.blender.org/) — for the animation render (optional)
- `ffmpeg` — for video encoding (optional)

```bash
# Install mise then:
mise install
mise run install
```

### Run the Full Pipeline

```bash
# Download DESI catalogs, process, and export for web
mise run pipeline

# Or step by step:
mise run fetch        # Download ~150 MB of FITS catalogs
mise run process      # Convert to Parquet (RA/Dec/z → XYZ Mpc)
mise run export-web   # Downsample to 500k points → binary for browser
```

### Web Viewer (Development)

```bash
mise run web-dev
# → http://localhost:5173
```

### Deploy to Production

The web viewer is hosted on a Fedora MiniPC behind a residential ISP (no port-forward).
An Azure VM acts as the public-facing reverse proxy, forwarding traffic via Tailscale:

```
Browser → Azure VM (public IP) → Tailscale mesh → Fedora MiniPC (100.82.166.71)
```

```bash
# Set your Azure VM public IP first:
export AZURE_HOST="root@<YOUR_AZURE_VM_IP>"

mise run deploy
# Builds → pushes via rsync through Azure jump host → configures nginx on both machines
```

### Render the Animation (8K 60fps)

The render script auto-detects the best available GPU backend (OptiX → CUDA → Metal → CPU). No configuration needed — just run it.

**macOS (Metal / Apple Silicon):**
```bash
# Quick test at 1080p
blender --background --python animation/render.py -- \
  --resolution 1920x1080 --samples 32 --max-points 200000

# Full 8K production render (batched, manages disk space automatically)
bash scripts/batch_render.sh

# Encode frames → YouTube-ready H.265 MP4
bash scripts/encode_video.sh
```

**Windows (NVIDIA GPU — OptiX/NVENC):**
```bat
REM Quick test at 1080p
"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe" --background --python animation\render.py -- ^
  --resolution 1920x1080 --samples 32 --max-points 200000

REM Full 8K production render (batched, manages disk space automatically)
scripts\batch_render_windows.bat

REM Encode frames → YouTube-ready H.265 MP4 (NVENC GPU encoding)
scripts\encode_video_windows.bat
```

See [WINDOWS_RENDER.md](WINDOWS_RENDER.md) for full Windows setup instructions.

---

## Project Structure

```
DesiMapper/
├── pipeline/           # Python data pipeline
│   ├── fetch.py        # Async streaming FITS download
│   ├── process.py      # FITS → Parquet (RA/Dec/z → XYZ Mpc)
│   ├── reduce.py       # Downsample → compact binary for web
│   └── requirements.txt
├── animation/          # Blender 3D render scripts
│   ├── render.py       # Main render orchestrator
│   ├── scene.py        # Scene construction (mesh, materials, geo nodes)
│   └── camera_path.py  # Cinematic camera keyframes
├── web/                # Interactive Three.js viewer
│   ├── src/
│   │   ├── main.ts             # App entry point
│   │   ├── GalaxyRenderer.ts   # WebGL point cloud (shader material)
│   │   ├── CameraController.ts # Orbit + inertia camera
│   │   └── DataLoader.ts       # Streaming binary loader
│   ├── index.html
│   └── vite.config.ts
├── scripts/
│   ├── run_pipeline.sh         # Full pipeline runner
│   ├── deploy.sh               # Deploy to Fedora MiniPC
│   ├── encode_video.sh         # ffmpeg MP4 encoder
│   └── nginx-desimapper.conf   # Production nginx config
├── .mise.toml          # Environment + task definitions
├── Spec.md             # Full project specification
└── README.md
```

---

## Architecture

```
DESI DR1 FITS catalogs
       │  (HTTP, ~150 MB)
       ▼
  pipeline/fetch.py        ← async streaming download
       │
       ▼
  pipeline/process.py      ← RA/Dec/z → XYZ (Planck 2018 ΛCDM)
       │                      astropy FlatLambdaCDM, Parquet/zstd
       ▼
  pipeline/reduce.py       ─────────────────┐
       │                                    │
       ▼                                    ▼
  animation/render.py              web/public/data/galaxies.bin
  (Blender, ~500k pts)             (~500k pts, custom binary)
       │                                    │
       ▼                                    ▼
  renders/*.mp4                    web/src/main.ts (Three.js)
  (YouTube)                        (Nginx → Fedora MiniPC)
```

### Coordinate System

Redshift → comoving Cartesian XYZ using flat ΛCDM (H₀ = 67.4 km/s/Mpc, Ω_m = 0.315):

```
d_c = comoving_distance(z)   [Mpc]
x = d_c · cos(dec) · cos(ra)
y = d_c · cos(dec) · sin(ra)
z = d_c · sin(dec)
```

### Web Binary Format

Custom compact format for fast `ArrayBuffer` loading — no JSON parsing overhead:

```
Header  (16 bytes): magic | version | n_points | flags
Per point (16 bytes): x f32 | y f32 | z f32 | tracer u8 | pad u8 | z_encoded u16
```

500k galaxies → ~8 MB binary file, loads in ~1s on a 100 Mbit/s connection.

---

## Data Source

**DESI DR1 LSS Clustering Catalogs**
```
https://data.desi.lbl.gov/public/dr1/vac/dr1/lss/guadalupe/v1.0/LSScats/clustering/
```

Files used (`*_clustering.dat.fits` — galaxy data only, not randoms):
- `BGS_BRIGHT_{N,S}_clustering.dat.fits`
- `LRG_{N,S}_clustering.dat.fits`
- `ELG_LOPnotqso_{N,S}_clustering.dat.fits`
- `QSO_{N,S}_clustering.dat.fits`

Total download: ~150 MB (vs 279 TB full release).

---

## Infrastructure

| Machine | Role | Notes |
|---------|------|-------|
| MacBook (macOS) | Development, pipeline | Metal GPU → Blender Cycles (backup renderer) |
| Windows PC (7800X3D + RTX 3090) | **Primary animation renderer** | OptiX → Blender Cycles, NVENC encoding |
| Raspberry Pi (`100.68.179.53`) | FITS archive + pipeline storage | 1 TB, `/projects` |
| Fedora MiniPC (`100.82.166.71`) | Static web server (nginx) | AMD 7940HS, Tailscale only |
| Azure VM | Public reverse proxy (nginx) | Forwards HTTP → MiniPC via Tailscale |

**Network topology** (ISP blocks port-forwarding → Azure bridges the gap):
```
Browser → Azure VM :80 ──[Tailscale]──► Fedora MiniPC :80
```

---

## Acknowledgements

Data from the Dark Energy Spectroscopic Instrument (DESI):

> DESI Collaboration et al. (2025), "Data Release 1 of the Dark Energy Spectroscopic Instrument", arXiv:2503.14745

> Moon et al. (2023), MNRAS 525, 5406

See [DESI Data License](https://data.desi.lbl.gov/public/dr1/LICENSE.md) for terms of use.

---

## License

MIT — see [LICENSE](LICENSE) for details. DESI data is subject to its own license terms.

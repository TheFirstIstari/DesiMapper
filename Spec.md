# DesiMapper — Project Specification

## Overview

DesiMapper is a high-performance data pipeline and visualization toolkit for the **DESI (Dark Energy Spectroscopic Instrument) Data Release 1** galaxy survey. It extracts galaxy position data (RA, Dec, redshift) from the DESI LSS catalogs, converts them to 3D Cartesian coordinates, and produces:

1. **A cinematic 3D animation** — a fly-through of the DESI survey volume, exportable as a YouTube-ready video
2. **A real-time interactive web visualizer** — a publicly hosted Three.js/WebGL viewer hosted on a Fedora MiniPC, rendering a reduced model of the full dataset

---

## Dataset

**Source:** [DESI DR1 LSS Catalogs](https://data.desi.lbl.gov/public/dr1/vac/dr1/lss/guadalupe/v1.0/LSScats/clustering/)

**Total dataset size:** ~279 TB (full spectroscopic release)  
**Selected subset (clustering `.dat.fits` files):** ~150–400 MB total — covering all tracer types

### Target Catalogs

| Tracer | Files | Redshift Range | Count (approx) |
|--------|-------|----------------|----------------|
| BGS_BRIGHT (N+S) | `BGS_BRIGHT_N_clustering.dat.fits`, `BGS_BRIGHT_S_clustering.dat.fits` | z = 0.01–0.6 | ~300k |
| LRG (N+S) | `LRG_N_clustering.dat.fits`, `LRG_S_clustering.dat.fits` | z = 0.4–1.1 | ~600k |
| ELG (N+S) | `ELG_LOPnotqso_N_clustering.dat.fits`, `ELG_LOPnotqso_S_clustering.dat.fits` | z = 0.8–1.6 | ~800k |
| QSO (N+S) | `QSO_N_clustering.dat.fits`, `QSO_S_clustering.dat.fits` | z = 0.8–2.1 | ~400k |

**Base URL:** `https://data.desi.lbl.gov/public/dr1/vac/dr1/lss/guadalupe/v1.0/LSScats/clustering/`

### Key Data Columns

- `RA` — Right Ascension (degrees)
- `DEC` — Declination (degrees)  
- `Z` — Spectroscopic redshift
- `WEIGHT` — Combined completeness weight for clustering

---

## Architecture

```
DesiMapper/
├── pipeline/               # Python data pipeline
│   ├── fetch.py            # Streaming download of FITS catalogs
│   ├── process.py          # FITS → Cartesian XYZ conversion
│   ├── export.py           # Export to Parquet + binary formats
│   └── reduce.py           # Downsampling for web viewer
├── animation/              # Blender/Manim-based 3D renderer
│   ├── render.py           # Orchestrates the animation render
│   ├── scene.py            # Blender Python scene definition
│   └── camera_path.py      # Keyframe camera trajectory
├── web/                    # Interactive web viewer
│   ├── src/
│   │   ├── main.ts         # Three.js entry point
│   │   ├── GalaxyRenderer.ts # Point cloud renderer
│   │   ├── CameraController.ts # Orbit + fly controls
│   │   └── DataLoader.ts   # Streaming binary data loader
│   ├── public/
│   │   └── data/           # Pre-processed reduced galaxy data
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── scripts/
│   ├── deploy.sh           # Deploy to Fedora MiniPC
│   └── run_pipeline.sh     # Full pipeline runner
├── data/
│   ├── raw/                # Downloaded FITS files (gitignored)
│   └── processed/          # Parquet + binary outputs (gitignored)
├── docs/
│   └── architecture.md
├── .mise.toml              # mise environment config
├── .gitignore
├── README.md
└── Spec.md
```

---

## Technology Choices

### Pipeline — Python 3.12

**Why Python:** Dominant language for astronomy/FITS processing with mature ecosystem.

| Library | Purpose |
|---------|---------|
| `astropy` | FITS file reading (industry standard) |
| `numpy` | Vectorised coordinate transforms |
| `pyarrow` / `polars` | Fast Parquet export |
| `httpx` + `asyncio` | Async streaming download (avoids loading 1GB+ into RAM) |
| `tqdm` | Progress bars |
| `astropy.cosmology` | Redshift → comoving distance conversion (FlatLambdaCDM) |

### Web Viewer — TypeScript + Three.js + Vite

**Why Three.js:** Mature WebGL library, excellent point cloud support via `THREE.Points`, runs on any browser with no install.

**Why Vite:** Instant HMR, native ESM, tree-shaking — ideal for a self-hosted minipc.

| Library | Purpose |
|---------|---------|
| `three` | 3D rendering engine |
| `@tweenjs/tween.js` | Smooth camera animations |
| Custom binary format | Fast load of 2M+ galaxy positions |

### Animation — Blender Python API (bpy)

**Why Blender:** Free, scriptable, GPU-accelerated Cycles renderer, professional-quality output.

The animation script:
1. Loads pre-processed galaxy XYZ data
2. Creates a particle system / point cloud
3. Defines a cinematic camera path (DESI footprint fly-through)
4. Renders at 1920×1080 @ 30fps to PNG sequence
5. `ffmpeg` encodes final MP4 for YouTube

---

## Coordinate Transform

Redshift → 3D Cartesian using flat ΛCDM cosmology (Planck 2018: H₀=67.4, Ωm=0.315):

```python
from astropy.cosmology import FlatLambdaCDM
import numpy as np

cosmo = FlatLambdaCDM(H0=67.4, Om0=0.315)

def to_cartesian(ra_deg, dec_deg, z):
    d_c = cosmo.comoving_distance(z).value  # Mpc
    ra  = np.radians(ra_deg)
    dec = np.radians(dec_deg)
    x = d_c * np.cos(dec) * np.cos(ra)
    y = d_c * np.cos(dec) * np.sin(ra)
    z_cart = d_c * np.sin(dec)
    return x, y, z_cart
```

---

## Web Viewer Data Format

A custom compact binary format for fast browser loading:

```
Header (16 bytes):
  uint32: magic = 0x44455349  ("DESI")
  uint32: version = 1
  uint32: n_points
  uint32: flags (bitmask: tracer type, etc.)

Body (n_points × 16 bytes):
  float32: x (Mpc)
  float32: y (Mpc)
  float32: z (Mpc)
  uint8:   tracer_type (0=BGS, 1=LRG, 2=ELG, 3=QSO)
  uint8:   reserved
  uint16:  z_encoded (z * 10000, for colour mapping)
```

Target: ≤ 500k points for web (downsampled from ~2M), file size ≤ 32 MB.

---

## Animation Sequence (YouTube Video)

**Duration:** ~6.5 minutes  
**Resolution:** 7680×4320 (8K UHD) @ 60fps  
**Render machine:** MacBook (macOS, Metal GPU via Blender Cycles)  
**Output format:** OpenEXR 16-bit → H.265 MP4 via VideoToolbox hardware encoder

| Segment | Duration | Description |
|---------|----------|-------------|
| 0:00 | 10s | Title card: "The Universe as Seen by DESI" |
| 0:10 | 20s | Earth → Milky Way → Local Group zoom-out |
| 0:30 | 30s | Full survey volume appears, galaxy types colour-coded |
| 1:00 | 60s | Slow fly-through of BGS (nearby universe) |
| 2:00 | 45s | Camera pushes to LRG / ELG shells (z~1) |
| 2:45 | 30s | QSO shell at z~2 revealed |
| 3:15 | 30s | Wide shot of full 3D survey, rotate 360° |
| 3:45 | 15s | Data credits & outro |

**Colour coding:**
- BGS (z < 0.6): warm orange
- LRG (0.4 < z < 1.1): red
- ELG (0.8 < z < 1.6): cyan/teal
- QSO (z > 0.8): white/blue

---

## Infrastructure

### Development Machine (macOS)
- Pipeline processing, web development, animation scripting
- **Animation rendering** at 8K 60fps using Blender Metal GPU backend

### Raspberry Pi (root@100.68.179.53, /projects, 1TB)
- Archive storage for raw FITS files and processed Parquet data
- Run data pipeline for heavy downloads

### Fedora MiniPC (root@100.82.166.71, AMD 7940HS)
- **Static web server** — serves the Vite-built Three.js app
- Connected to the internet only via Tailscale mesh (no public port-forward on local ISP)
- Nginx serves files locally on port 80

### Azure VM (public internet access)
- **Public-facing reverse proxy** — has a static public IP
- Nginx proxies inbound HTTP → Fedora MiniPC via Tailscale IP (100.82.166.71)
- This bridges the ISP port-forward limitation

```
Browser → Azure VM (public IP :80) → [Tailscale] → Fedora MiniPC (100.82.166.71:80)
```

---

## Performance Targets

| Metric | Target |
|--------|--------|
| Download time (all 8 clustering catalogs) | < 5 min on 100 Mbit/s |
| Pipeline processing time (2M galaxies → binary) | < 30 sec |
| Web viewer initial load | < 3 sec on 100 Mbit/s |
| Web viewer frame rate | 60fps on modern GPU, 30fps on iGPU |
| Animation render time | ~24–48h on MacBook (Metal GPU, 8K 128 samples) |

---

## Development Phases

### Phase 1 — Data Pipeline (Days 1–2)
- [ ] `mise` environment setup
- [ ] Async FITS download with progress
- [ ] RA/Dec/z → XYZ transform
- [ ] Parquet export + binary web format export
- [ ] Data validation & summary stats

### Phase 2 — Web Viewer (Days 2–4)
- [ ] Vite + Three.js scaffolding
- [ ] Binary data loader (streaming ArrayBuffer)
- [ ] Point cloud renderer with colour-by-tracer
- [ ] Orbit + fly camera controls
- [ ] Redshift slider UI
- [ ] Nginx deploy to Fedora MiniPC

### Phase 3 — Animation (Days 4–7)
- [ ] Blender scene setup (headless)
- [ ] Camera path keyframes
- [ ] Render PNG sequence
- [ ] ffmpeg encode MP4
- [ ] Title cards & colour grading

### Phase 4 — Polish
- [ ] README with screenshots/demo GIF
- [ ] GitHub repo cleanup
- [ ] YouTube upload instructions

---

## Acknowledgements

Data from the Dark Energy Spectroscopic Instrument (DESI) DR1 release.  
DESI Collaboration et al. (2025), arXiv:2503.14745.

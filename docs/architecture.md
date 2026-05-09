# DesiMapper — Architecture Notes

## Data Flow

```
DESI DR1 (HTTPS)
    │
    │  ~150 MB of *_clustering.dat.fits files
    │  (RA, Dec, Z, WEIGHT columns)
    ▼
pipeline/fetch.py
    │  httpx async streaming, max 3 concurrent
    │  saves to data/raw/*.dat.fits
    ▼
pipeline/process.py
    │  astropy FITS reader (memmap=True, zero-copy)
    │  quality cut: 0.001 < z < 5.0
    │  FlatLambdaCDM(H0=67.4, Om0=0.315) comoving distance
    │  RA/Dec/z → x/y/z_cart (float32 Mpc)
    │  saves per-tracer Parquet (zstd) + combined
    ▼
pipeline/reduce.py
    │  stratified weighted sampling (seed=42)
    │  500k total points across 4 tracers
    │  writes custom binary + metadata.json
    ▼
web/public/data/galaxies.bin   animation/all_galaxies.parquet
         │                              │
         ▼                              ▼
    Three.js viewer              Blender scene
    (browser, 60fps)             (headless render)
```

## Technology Rationale

### Python for Pipeline

The DESI community uses Python exclusively (`astropy`, `fitsio`, `numpy`).
Using the same ecosystem means we can borrow from published DESI notebooks directly.

`httpx` is chosen over `requests` for native async support — critical for
concurrent downloads without threading overhead.

`polars` is used where available for fast Parquet I/O, falling back to `pyarrow`
in Blender's embedded Python which may not have polars.

### TypeScript + Three.js for Web

Three.js is the de facto WebGL abstraction for scientific visualization.
Its `THREE.Points` + custom `ShaderMaterial` is the most efficient approach
for 500k+ point clouds — GPU-side size and colour computation means
the CPU only needs to update dirty attributes.

Additive blending (`THREE.AdditiveBlending`) makes galaxy clusters naturally
appear brighter — physically appropriate as overlapping faint objects sum.

### Blender for Animation

Blender's Geometry Nodes (4.x) handles vertex-to-point conversion efficiently.
The headless `--background` mode allows rendering on the MiniPC without a display.
Cycles renderer with GPU acceleration on the 7940HS integrated GPU should render
the full animation overnight.

## Binary Format Design

The custom 16-byte-per-point format is designed for:
1. **No parsing overhead** — direct `Float32Array` / `Uint8Array` views into the ArrayBuffer
2. **Alignment** — all fields naturally aligned (no padding needed for float32)
3. **Compactness** — 16 bytes vs ~40 bytes for JSON equivalent

A future v2 could use GPU-uploadable formats (e.g. interleaved VBO), but the
current format is already loaded directly into Three.js `BufferAttribute`s.

## Coordinate Scale

DESI's BGS extends to ~1700 Mpc comoving, QSO to ~6500 Mpc.
Scene units = Mpc. Camera distances of ~4000 Mpc give a good full-survey view.

For Blender: scale factor 0.001 maps Mpc → Blender units, so the survey
spans ~0–6.5 BU — comfortable for Blender's default clip distances.

## Performance Notes

- `memmap=True` in astropy means FITS files are not fully loaded into RAM;
  only accessed columns are paged in. Critical for machines with <8 GB RAM.
- The web binary shuffle (random permutation) ensures depth-sorted rendering
  doesn't introduce systematic bias when opacity < 1.
- Three.js `depthWrite: false` + additive blending eliminates z-fighting for
  overlapping transparent points.

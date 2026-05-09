# DesiMapper — Windows Render Guide (NVIDIA GPU)

Step-by-step setup for rendering the 8K 60fps animation on a Windows PC with an NVIDIA GPU (tested target: Ryzen 7800X3D + RTX 3090).

---

## Prerequisites

| Software | Download |
|----------|----------|
| **Blender 4.3+ or 5.x** | https://www.blender.org/download/ |
| **Python 3.12** | https://www.python.org/downloads/ |
| **Git** | https://git-scm.com/download/win |
| **ffmpeg** | `winget install ffmpeg` or https://ffmpeg.org/download.html |
| **NVIDIA drivers** | 531+ (CUDA 12.x) — update via GeForce Experience or https://nvidia.com/drivers |

Verify your driver version:
```
nvidia-smi
```
You should see `CUDA Version: 12.x` in the top-right corner. If not, update your drivers.

---

## 1. Clone the Repository

Open **Command Prompt** or **PowerShell** (not WSL — use native Windows):

```bat
cd C:\
git clone https://github.com/TheFirstIstari/DesiMapper.git
cd DesiMapper
```

---

## 2. Set Up Python Environment

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r pipeline\requirements.txt
```

> **Note:** If `python` is not found, use `py -3.12` instead. Make sure Python was added to PATH during install (tick the checkbox in the installer).

---

## 3. Run the Data Pipeline

This downloads ~150 MB of FITS catalogs from DESI and processes them into the Parquet file that Blender reads.

```bat
python pipeline\fetch.py
python pipeline\process.py
```

Output: `data\processed\all_galaxies.parquet` (~150 MB, 1.4M galaxies)

> **Already have the parquet file?** Copy it to `data\processed\all_galaxies.parquet` and skip this step.

---

## 4. Verify Blender Can See Your GPU

Open a Command Prompt, find your Blender path, and run a quick GPU detection check:

```bat
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --python animation\render.py -- --parquet data\processed\all_galaxies.parquet --output renders\test\ --resolution 1920x1080 --samples 32 --max-points 100000 --start-frame 1 --end-frame 1
```

In the output you should see:
```
  Enabled: 'NVIDIA GeForce RTX 3090'  (CUDA)
  Backend: OPTIX
  CPU threads: 16 (FIXED)
```

If you see `No GPU backend available — falling back to CPU`, your drivers may need updating or CUDA is not installed.

> **OptiX vs CUDA:** The render script auto-selects OptiX over CUDA when available. OptiX uses NVIDIA's RT cores and is significantly faster. Both will produce identical output.

---

## 5. Full 8K Production Render

### Option A — Automated batch render (recommended)

The batch render script renders in 600-frame chunks (10s each), encodes each chunk to MP4 via NVENC, then deletes the PNG frames before the next chunk. Peak disk usage is ~9 GB at a time.

```bat
cd C:\DesiMapper
scripts\batch_render_windows.bat
```

Options:
```bat
scripts\batch_render_windows.bat 600         REM default: 600 frames per chunk
scripts\batch_render_windows.bat 600 resume  REM skip already-encoded chunks (resume after crash)
```

Final output: `renders\desimapper_8k_60fps.mp4`

### Option B — Manual render + encode

Render all frames at once (requires ~340 GB free disk space for 8K PNGs):

```bat
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --python animation\render.py -- ^
    --parquet data\processed\all_galaxies.parquet ^
    --output renders\frames ^
    --resolution 7680x4320 ^
    --fps 60 ^
    --samples 128 ^
    --max-points 1400000
```

Then encode:
```bat
scripts\encode_video_windows.bat
```

---

## 6. Estimated Performance

The RTX 3090 (24 GB VRAM, 10,496 CUDA cores) is significantly faster than the M4 MacBook:

| Setting | MacBook M4 (Metal) | RTX 3090 (OptiX) |
|---------|--------------------|------------------|
| 1080p 128spp | ~0.95s/frame | ~0.2–0.4s/frame (est.) |
| 8K 128spp | ~15–20s/frame (est.) | ~3–6s/frame (est.) |
| 8K total (23,400 frames) | ~100h | ~20–40h (est.) |

> These estimates are based on the M4 benchmark and typical 3090 vs M4 GPU throughput ratios. Run a 10-frame test at 8K to get your actual number:

```bat
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --background --python animation\render.py -- ^
    --parquet data\processed\all_galaxies.parquet ^
    --output renders\test_8k ^
    --resolution 7680x4320 ^
    --samples 128 ^
    --max-points 1400000 ^
    --start-frame 100 ^
    --end-frame 109
```

---

## 7. Denoising on NVIDIA (Optional Quality Boost)

Unlike on macOS where OIDN denoising was slow and caused stalls, **OptiX denoising on NVIDIA is fast** (GPU-native, uses RT cores). If you want to try it, simply omit `--no-denoising` (it's already the default):

The render script defaults to `use_denoising=True` unless you pass `--no-denoising`. On a 3090 with OptiX, the denoiser adds minimal overhead and can reduce graininess in sparse regions.

Benchmark both with a 10-frame test and decide based on quality vs. speed.

---

## 8. Troubleshooting

### Blender not found
Edit `scripts\batch_render_windows.bat` and update the `BLENDER` variable to your actual Blender install path:
```bat
set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
```

### ffmpeg not on PATH
After installing ffmpeg, either:
- Re-open Command Prompt (PATH refresh)
- Add ffmpeg's `bin\` folder to System Environment Variables → PATH

### Out of VRAM
If Blender crashes with a CUDA out-of-memory error, reduce `--max-points`:
```bat
--max-points 1000000   REM try 1M instead of 1.4M
```
The 3090 has 24 GB VRAM so this should not be needed for 1.4M points.

### OptiX not detected
Ensure your NVIDIA driver is 531 or newer. Check with `nvidia-smi`. Update via GeForce Experience or https://nvidia.com/drivers.

### Chunk resume after crash
If the render crashes mid-chunk, delete any partial `.png` files and the `.mp4` for that chunk, then re-run with `resume`:
```bat
del renders\frames\frame_*.png
scripts\batch_render_windows.bat 600 resume
```

---

## 9. After Rendering

Transfer the final `renders\desimapper_8k_60fps.mp4` to wherever you plan to upload from. The file will be roughly 40–80 GB depending on scene complexity.

YouTube upload checklist:
- Upload via [YouTube Studio](https://studio.youtube.com)
- Set as **Unlisted** first — verify quality at 8K before publishing
- YouTube takes 30–60 minutes to process 8K after upload
- Title suggestion: `The Universe as Seen by DESI — 40 Million Galaxies in 3D (8K 60fps)`

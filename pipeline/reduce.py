"""
reduce.py — Export the full galaxy catalog for the web viewer.

No downsampling is applied.  Every galaxy that passed quality cuts in
process.py is written to the binary.  At 16 bytes/point the ~1.4M-row
combined catalog produces a ~22 MB file.

BGS galaxies carry a per-galaxy g-r colour byte derived from dereddened
DESI fluxes.  The byte encodes g-r on a 0–255 scale covering [-0.5, 2.5]
mag (blue star-forming → red passive).  Non-BGS tracers get 128 (neutral).

Output: custom 16-byte-per-point binary (v2) + metadata.json for the Three.js viewer.
"""

import json
import os
import struct
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from rich.console import Console
from rich.table import Table

console = Console()

PROCESSED_DIR = Path(os.environ.get("DESI_PROCESSED_DIR", "data/processed"))
WEB_DATA_DIR  = Path("web/public/data")

MAGIC   = 0x44452349  # "DESI"
VERSION = 4

# Cap on random (density-field) points written to the web binary. Randoms are
# ~100× the galaxy count; we keep a bounded slice so the committed binary stays
# feasible to serve from Render's static CDN (galaxies + cap ≈ 75 MB at 17 B/pt).
MAX_RANDOM_POINTS = 3_000_000

# g-r colour byte encoding: maps the physical range [GR_MIN, GR_MAX] mag
# linearly onto [0, 255].  Values outside the range are clamped.
# 0   = very blue (star-forming)   g-r ≈ -0.5
# 128 = neutral / non-BGS tracer   g-r ≈  1.0
# 255 = very red (passive)         g-r ≈  2.5
GR_MIN = -0.5
GR_MAX =  2.5


def _gr_to_byte(flux_g: np.ndarray, flux_r: np.ndarray) -> np.ndarray:
    """Compute g-r colour and encode to uint8.

    flux_g, flux_r: dereddened fluxes in nanomaggies (may contain NaN for
    non-BGS rows, in which case 128 (neutral) is returned).
    """
    # AB magnitude: m = 22.5 - 2.5*log10(flux)  [flux in nanomaggies]
    safe_g = np.clip(flux_g, 1e-5, None)
    safe_r = np.clip(flux_r, 1e-5, None)
    g_mag = 22.5 - 2.5 * np.log10(safe_g)
    r_mag = 22.5 - 2.5 * np.log10(safe_r)
    gr = g_mag - r_mag

    # Replace NaN / non-finite with neutral
    bad = ~np.isfinite(gr) | np.isnan(flux_g) | np.isnan(flux_r)
    gr[bad] = (GR_MIN + GR_MAX) / 2.0  # → byte 128

    # Linear map [GR_MIN, GR_MAX] → [0, 255]
    t = (gr - GR_MIN) / (GR_MAX - GR_MIN)
    return np.clip(np.round(t * 255), 0, 255).astype(np.uint8)


# ─── Binary writer ────────────────────────────────────────────────────────────

def write_binary_fast(x, y, z_cart, z_red, tracer, color_byte, kind, out_path: Path) -> None:
    """Vectorised write — header + struct-of-arrays, 4-byte field alignment.

    Binary format v4 — 17 bytes per point (little-endian), laid out as separate
    field blocks so the viewer can wrap each field with a zero-copy typed-array
    view (no per-point parse loop). No intra-block padding needed (f32 4-aligned,
    u8 1-align, u16 at 16+14n always even):
      Header (16): magic, version, n_points, flags
      x[]          float32  [16,        4n]
      y[]          float32  [16+4n,     4n]
      z_cart[]     float32  [16+8n,     4n]
      tracer[]     uint8    [16+12n,    n]
      color_byte[] uint8    [16+13n,    n]
      z_encoded[]  uint16   [16+14n,    2n]
      kind[]       uint8    [16+16n,    n]   (0=galaxy, 1=random)
    Total on wire: 16 + 17n bytes.
    """
    n = len(x)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    z_encoded = np.clip(z_red * 10000, 0, 65535).astype(np.uint16)

    body = (
        x.astype("<f4").tobytes()
        + y.astype("<f4").tobytes()
        + z_cart.astype("<f4").tobytes()
        + tracer.astype("<u1").tobytes()
        + color_byte.astype("<u1").tobytes()
        + z_encoded.astype("<u2").tobytes()
        + kind.astype("<u1").tobytes()
    )

    with open(out_path, "wb") as f:
        f.write(struct.pack("<IIII", MAGIC, VERSION, n, 0))
        f.write(body)

    size_mb = out_path.stat().st_size / 1e6
    console.print(f"  Wrote {n:,} points → {out_path.name} ({size_mb:.1f} MB)")


# ─── Main export ─────────────────────────────────────────────────────────────

def export_web() -> None:
    console.rule("[bold cyan]DESI DR1 — Full Catalog Web Export")

    combined_path = PROCESSED_DIR / "all_galaxies.parquet"
    if not combined_path.exists():
        console.print(f"[red]Combined catalog not found: {combined_path}[/]")
        console.print("Run [bold]mise run process[/] first.")
        raise SystemExit(1)

    console.print(f"Loading {combined_path}…")
    table = pq.read_table(combined_path)
    n_gal = len(table)
    console.print(f"  Total galaxies: {n_gal:,}")

    # Galaxies
    gx = np.array(table["x"], dtype=np.float32)
    gy = np.array(table["y"], dtype=np.float32)
    gz = np.array(table["z_cart"], dtype=np.float32)
    gzr = np.array(table["z"], dtype=np.float32)
    gt = np.array(table["tracer"], dtype=np.uint8)
    gflux_g = np.array(table["flux_g"], dtype=np.float32)
    gflux_r = np.array(table["flux_r"], dtype=np.float32)
    g_color = _gr_to_byte(gflux_g, gflux_r)
    g_kind = np.zeros(n_gal, dtype=np.uint8)

    # Randoms (density-field layer) — optional, subsampled to a hard cap so the
    # binary stays feasible to serve.
    rx = ry = rz = rzr = rt = r_color = r_kind = None
    n_rand = 0
    rand_path = PROCESSED_DIR / "all_randoms.parquet"
    if rand_path.exists():
        rtable = pq.read_table(rand_path)
        n_rand = len(rtable)
        # ponytail: subsample first (cheap) so downstream arrays stay small
        if n_rand > MAX_RANDOM_POINTS:
            keep = np.random.default_rng(7).choice(n_rand, MAX_RANDOM_POINTS, replace=False)
            rtable = rtable.take(keep)
            n_rand = MAX_RANDOM_POINTS
        rx = np.array(rtable["x"], dtype=np.float32)
        ry = np.array(rtable["y"], dtype=np.float32)
        rz = np.array(rtable["z_cart"], dtype=np.float32)
        rzr = np.array(rtable["z"], dtype=np.float32)
        rt = np.array(rtable["tracer"], dtype=np.uint8)
        # Randoms carry no meaningful per-galaxy colour → neutral
        r_color = np.full(n_rand, 128, dtype=np.uint8)
        r_kind = np.ones(n_rand, dtype=np.uint8)
        console.print(f"  Randoms (density): {n_rand:,}")
    else:
        console.print("  [dim]No randoms (all_randoms.parquet) — galaxies only. Run 'mise run process' with randoms enabled.[/]")

    # Concatenate galaxy + random blocks
    x = np.concatenate([gx, rx]) if rx is not None else gx
    y = np.concatenate([gy, ry]) if ry is not None else gy
    z_cart = np.concatenate([gz, rz]) if rz is not None else gz
    z_red = np.concatenate([gzr, rzr]) if rzr is not None else gzr
    tracer = np.concatenate([gt, rt]) if rt is not None else gt
    color_byte = np.concatenate([g_color, r_color]) if r_color is not None else g_color
    kind = np.concatenate([g_kind, r_kind]) if r_kind is not None else g_kind
    n_total = len(x)

    # Per-tracer stats (galaxies only)
    tracer_names = {0: "BGS", 1: "LRG", 2: "ELG", 3: "QSO"}
    stats = Table(title="Full Catalog Export")
    stats.add_column("Tracer", style="cyan")
    stats.add_column("Count", justify="right", style="green")
    stats.add_column("z range", justify="right")
    stats.add_column("g-r range", justify="right", style="dim")

    for tid, name in tracer_names.items():
        mask = gt == tid
        if not mask.any():
            continue
        z_t = gzr[mask]
        cb_t = g_color[mask]
        if tid == 0:
            gr_lo = GR_MIN + (cb_t.min() / 255.0) * (GR_MAX - GR_MIN)
            gr_hi = GR_MIN + (cb_t.max() / 255.0) * (GR_MAX - GR_MIN)
            gr_str = f"{gr_lo:.2f}–{gr_hi:.2f}"
        else:
            gr_str = "N/A"
        stats.add_row(name, f"{mask.sum():,}", f"{z_t.min():.3f}–{z_t.max():.3f}", gr_str)

    console.print(stats)

    # Shuffle so additive-blending draw order has no systematic depth bias
    perm = np.random.default_rng(42).permutation(n_total)

    write_binary_fast(
        x[perm], y[perm], z_cart[perm], z_red[perm],
        tracer[perm], color_byte[perm], kind[perm],
        WEB_DATA_DIR / f"galaxies.v{VERSION}.bin",
    )

    metadata = {
        "version": VERSION,
        "n_points": n_total,
        "n_galaxies": n_gal,
        "n_randoms": n_rand,
        "tracers": {
            "0": {"name": "BGS", "color": "#FF8C00", "z_range": [0.01, 0.6]},
            "1": {"name": "LRG", "color": "#CC2200", "z_range": [0.4, 1.1]},
            "2": {"name": "ELG", "color": "#00CED1", "z_range": [0.8, 1.6]},
            "3": {"name": "QSO", "color": "#8888FF", "z_range": [0.8, 2.1]},
        },
        "bounds": {
            "x": [float(x.min()), float(x.max())],
            "y": [float(y.min()), float(y.max())],
            "z": [float(z_cart.min()), float(z_cart.max())],
        },
        "cosmology": {"H0": 67.4, "Om0": 0.315, "model": "FlatLambdaCDM"},
        "data_release": "DESI DR1 guadalupe/v1.0",
        "sampling": "galaxies: full catalog; randoms: subsampled density layer",
        "color_encoding": {
            "field": "color_byte (byte offset 13 per record)",
            "description": "g-r colour from dereddened DESI fluxes (BGS only; 128=neutral for other tracers and randoms)",
            "gr_min": GR_MIN,
            "gr_max": GR_MAX,
            "byte_0": "blue/star-forming (g-r=-0.5)",
            "byte_128": "neutral",
            "byte_255": "red/passive (g-r=2.5)",
        },
    }

    meta_path = WEB_DATA_DIR / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    console.print(f"  Wrote metadata → {meta_path}")
    console.print(f"\n[bold green]✓ Web export complete: {n_gal:,} galaxies + {n_rand:,} randoms = {n_total:,} points[/]")


if __name__ == "__main__":
    export_web()

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

MAGIC   = 0x44455349  # "DESI"
VERSION = 3

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

def write_binary_fast(x, y, z_cart, z_red, tracer, color_byte, out_path: Path) -> None:
    """Vectorised write — header + struct-of-arrays, 4-byte field alignment.

    Binary format v3 — 16 bytes per point (little-endian), laid out as separate
    field blocks so the viewer can wrap each field with a zero-copy typed-array
    view (no per-point parse loop). No intra-block padding is needed: f32 blocks
    are 4-aligned by construction, u8 needs only 1-align, and the u16 block lands
    at 16+14n (always even), so every view is correctly aligned for ANY n:
      Header (16): magic, version, n_points, flags
      x[]          float32  [16,        4n]
      y[]          float32  [16+4n,     4n]
      z_cart[]     float32  [16+8n,     4n]
      tracer[]     uint8    [16+12n,    n]
      color_byte[] uint8    [16+13n,    n]
      z_encoded[]  uint16   [16+14n,    2n]
    Total on wire: 16 + 16n bytes.
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
    n_total = len(table)
    console.print(f"  Total galaxies: {n_total:,}")

    # `clustering` catalogs lowercase flux cols (flux_g); `full` uppercases (FLUX_G).
    # Resolve case-insensitively so both work.
    def _col(name: str) -> str:
        lname = name.lower()
        for c in table.column_names:
            if c.lower() == lname:
                return c
        raise KeyError(f"column {name} not found (have {table.column_names})")

    x      = np.array(table["x"],      dtype=np.float32)
    y      = np.array(table["y"],      dtype=np.float32)
    z_cart = np.array(table["z_cart"], dtype=np.float32)
    z_red  = np.array(table["z"],      dtype=np.float32)
    tracer = np.array(table["tracer"], dtype=np.uint8)
    flux_g = np.array(table[_col("flux_g")], dtype=np.float32)
    flux_r = np.array(table[_col("flux_r")], dtype=np.float32)

    color_byte = _gr_to_byte(flux_g, flux_r)

    # Per-tracer stats
    tracer_names = {0: "BGS", 1: "LRG", 2: "ELG", 3: "QSO"}
    stats = Table(title="Full Catalog Export")
    stats.add_column("Tracer",  style="cyan")
    stats.add_column("Count",   justify="right", style="green")
    stats.add_column("z range", justify="right")
    stats.add_column("g-r range", justify="right", style="dim")

    for tid, name in tracer_names.items():
        mask = tracer == tid
        if not mask.any():
            continue
        z_t  = z_red[mask]
        cb_t = color_byte[mask]
        if tid == 0:
            gr_lo = GR_MIN + (cb_t.min() / 255.0) * (GR_MAX - GR_MIN)
            gr_hi = GR_MIN + (cb_t.max() / 255.0) * (GR_MAX - GR_MIN)
            gr_str = f"{gr_lo:.2f}–{gr_hi:.2f}"
        else:
            gr_str = "N/A"
        stats.add_row(name, f"{mask.sum():,}", f"{z_t.min():.3f}–{z_t.max():.3f}", gr_str)

    console.print(stats)

    # Shuffle so additive-blending draw order has no systematic depth bias
    rng = np.random.default_rng(42)
    perm = rng.permutation(n_total)

    write_binary_fast(
        x[perm], y[perm], z_cart[perm], z_red[perm],
        tracer[perm], color_byte[perm],
        WEB_DATA_DIR / f"galaxies.v{VERSION}.bin",
    )

    metadata = {
        "version":    VERSION,
        "n_points":   n_total,
        "tracers": {
            "0": {"name": "BGS", "color": "#FF8C00", "z_range": [0.01,  0.6]},
            "1": {"name": "LRG", "color": "#CC2200", "z_range": [0.4,   1.1]},
            "2": {"name": "ELG", "color": "#00CED1", "z_range": [0.8,   1.6]},
            "3": {"name": "QSO", "color": "#8888FF", "z_range": [0.8,   2.1]},
        },
        "bounds": {
            "x": [float(x.min()), float(x.max())],
            "y": [float(y.min()), float(y.max())],
            "z": [float(z_cart.min()), float(z_cart.max())],
        },
        "cosmology":    {"H0": 67.4, "Om0": 0.315, "model": "FlatLambdaCDM"},
        "data_release": "DESI DR1 guadalupe/v1.0",
        "sampling":     "DESI DR1 guadalupe `full` sample — complete observed catalog (all galaxies, not the cosmology clustering subset)",
        "color_encoding": {
            "field": "color_byte (byte offset 13 per record)",
            "description": "g-r colour from dereddened DESI fluxes (BGS only; 128=neutral for other tracers)",
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
    console.print(f"\n[bold green]✓ Web export complete: {n_total:,} galaxies[/]")


if __name__ == "__main__":
    export_web()

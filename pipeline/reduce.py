"""
reduce.py — Downsample galaxy catalog for web viewer export.

Reads the combined Parquet catalog, applies stratified random sampling
per tracer type to produce a reduced dataset that loads fast in the browser.
Outputs a compact binary file and a JSON metadata file.
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
WEB_DATA_DIR = Path("web/public/data")

# Target point count per tracer for web viewer (keep total ~500k)
TARGET_PER_TRACER = {
    0: 100_000,  # BGS
    1: 150_000,  # LRG
    2: 150_000,  # ELG
    3: 100_000,  # QSO
}

MAGIC = 0x44455349  # "DESI"
VERSION = 1


def sample_tracer(table, tracer_id: int, n_target: int) -> tuple:
    """Weighted random sample from a tracer's rows."""
    mask = np.array(table["tracer"]) == tracer_id
    idx = np.where(mask)[0]

    if len(idx) == 0:
        return np.array([]), np.array([]), np.array([]), np.array([]), np.array([])

    n_sample = min(n_target, len(idx))

    # Use weights for stratified sampling
    weights = np.array(table["weight"])[idx].astype(np.float64)
    weights = np.clip(weights, 0, None)
    total_w = weights.sum()
    if total_w > 0:
        probs = weights / total_w
    else:
        probs = np.ones(len(idx)) / len(idx)

    chosen = np.random.choice(idx, size=n_sample, replace=False, p=probs)

    x = np.array(table["x"])[chosen].astype(np.float32)
    y = np.array(table["y"])[chosen].astype(np.float32)
    z_cart = np.array(table["z_cart"])[chosen].astype(np.float32)
    z_red = np.array(table["z"])[chosen].astype(np.float32)
    tracer = np.full(n_sample, tracer_id, dtype=np.uint8)

    return x, y, z_cart, z_red, tracer


def write_binary(x, y, z_cart, z_red, tracer, out_path: Path) -> None:
    """
    Write compact binary format for fast ArrayBuffer loading in Three.js.

    Header (16 bytes):
      uint32: magic
      uint32: version
      uint32: n_points
      uint32: flags

    Body per point (16 bytes):
      float32: x
      float32: y
      float32: z_cart
      uint8: tracer_type
      uint8: reserved
      uint16: z_encoded (z * 10000, clamped to uint16 max)
    """
    n = len(x)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "wb") as f:
        # Header
        f.write(struct.pack("<IIII", MAGIC, VERSION, n, 0))

        # Body — pack each record
        z_encoded = np.clip(z_red * 10000, 0, 65535).astype(np.uint16)

        for i in range(n):
            f.write(struct.pack("<fffBBH", x[i], y[i], z_cart[i], tracer[i], 0, z_encoded[i]))

    console.print(f"  Wrote {n:,} points → {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


def write_binary_fast(x, y, z_cart, z_red, tracer, out_path: Path) -> None:
    """Vectorised binary write — much faster than per-row loop."""
    n = len(x)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    z_encoded = np.clip(z_red * 10000, 0, 65535).astype(np.uint16)
    reserved = np.zeros(n, dtype=np.uint8)

    # Interleave fields into structured array
    dtype = np.dtype([
        ("x", "<f4"),
        ("y", "<f4"),
        ("z_cart", "<f4"),
        ("tracer", "u1"),
        ("reserved", "u1"),
        ("z_encoded", "<u2"),
    ])
    records = np.empty(n, dtype=dtype)
    records["x"] = x
    records["y"] = y
    records["z_cart"] = z_cart
    records["tracer"] = tracer
    records["reserved"] = reserved
    records["z_encoded"] = z_encoded

    with open(out_path, "wb") as f:
        # Header
        f.write(struct.pack("<IIII", MAGIC, VERSION, n, 0))
        f.write(records.tobytes())

    size_mb = out_path.stat().st_size / 1e6
    console.print(f"  Wrote {n:,} points → {out_path.name} ({size_mb:.1f} MB)")


def export_web() -> None:
    console.rule("[bold cyan]DESI DR1 — Web Data Export")

    combined_path = PROCESSED_DIR / "all_galaxies.parquet"
    if not combined_path.exists():
        console.print(f"[red]Combined catalog not found: {combined_path}[/]")
        console.print("Run [bold]mise run process[/] first.")
        raise SystemExit(1)

    console.print(f"Loading {combined_path}…")
    table = pq.read_table(combined_path)
    console.print(f"  Total galaxies: {len(table):,}")

    np.random.seed(42)  # Reproducible sampling

    all_x, all_y, all_z_cart, all_z_red, all_tracer = [], [], [], [], []
    stats_table = Table(title="Web Export Sample")
    stats_table.add_column("Tracer", style="cyan")
    stats_table.add_column("Available", justify="right")
    stats_table.add_column("Sampled", justify="right", style="green")

    tracer_names = {0: "BGS", 1: "LRG", 2: "ELG", 3: "QSO"}

    for tracer_id, n_target in TARGET_PER_TRACER.items():
        x, y, z_c, z_r, t = sample_tracer(table, tracer_id, n_target)
        if len(x) == 0:
            continue

        n_avail = int((np.array(table["tracer"]) == tracer_id).sum())
        stats_table.add_row(
            tracer_names[tracer_id],
            f"{n_avail:,}",
            f"{len(x):,}",
        )

        all_x.append(x)
        all_y.append(y)
        all_z_cart.append(z_c)
        all_z_red.append(z_r)
        all_tracer.append(t)

    x_all = np.concatenate(all_x)
    y_all = np.concatenate(all_y)
    z_cart_all = np.concatenate(all_z_cart)
    z_red_all = np.concatenate(all_z_red)
    tracer_all = np.concatenate(all_tracer)

    console.print(stats_table)

    # Shuffle so point cloud doesn't render back-to-front sorted
    perm = np.random.permutation(len(x_all))
    write_binary_fast(
        x_all[perm], y_all[perm], z_cart_all[perm], z_red_all[perm], tracer_all[perm],
        WEB_DATA_DIR / "galaxies.bin",
    )

    # Write metadata JSON for the web app
    metadata = {
        "version": VERSION,
        "n_points": int(len(x_all)),
        "tracers": {
            "0": {"name": "BGS", "color": "#FF8C00", "z_range": [0.01, 0.6]},
            "1": {"name": "LRG", "color": "#CC2200", "z_range": [0.4, 1.1]},
            "2": {"name": "ELG", "color": "#00CED1", "z_range": [0.8, 1.6]},
            "3": {"name": "QSO", "color": "#8888FF", "z_range": [0.8, 2.1]},
        },
        "bounds": {
            "x": [float(x_all.min()), float(x_all.max())],
            "y": [float(y_all.min()), float(y_all.max())],
            "z": [float(z_cart_all.min()), float(z_cart_all.max())],
        },
        "cosmology": {"H0": 67.4, "Om0": 0.315, "model": "FlatLambdaCDM"},
        "data_release": "DESI DR1 guadalupe/v1.0",
    }

    meta_path = WEB_DATA_DIR / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    console.print(f"  Wrote metadata → {meta_path}")

    console.print(f"\n[bold green]✓ Web export complete: {len(x_all):,} galaxies[/]")


if __name__ == "__main__":
    export_web()

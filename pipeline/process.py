"""
process.py — Convert DESI FITS catalogs to XYZ Cartesian coordinates.

Reads RA, Dec, Z from clustering .dat.fits files, converts to comoving
Cartesian coordinates (Mpc) using Planck 2018 flat ΛCDM cosmology,
and writes Parquet files for further processing.
"""

import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from astropy.cosmology import FlatLambdaCDM
from astropy.io import fits
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()

# Planck 2018 cosmology (DESI DR1 fiducial)
COSMO = FlatLambdaCDM(H0=67.4, Om0=0.315)

DATA_DIR = Path(os.environ.get("DESI_DATA_DIR", "data/raw"))
PROCESSED_DIR = Path(os.environ.get("DESI_PROCESSED_DIR", "data/processed"))

# Map filename prefix → tracer type integer (for colour coding)
TRACER_MAP = {
    "BGS_BRIGHT-21.5": 0,
    "BGS_BRIGHT": 0,
    "LRG": 1,
    "ELG_LOPnotqso": 2,
    "QSO": 3,
}

TRACER_NAMES = {0: "BGS", 1: "LRG", 2: "ELG", 3: "QSO"}


def get_tracer_id(filename: str) -> int:
    """Derive tracer integer from filename."""
    for prefix, tid in TRACER_MAP.items():
        if filename.startswith(prefix):
            return tid
    return 0


def radec_z_to_xyz(ra_deg: np.ndarray, dec_deg: np.ndarray, z: np.ndarray) -> tuple:
    """
    Convert RA, Dec, redshift to comoving Cartesian XYZ (Mpc).

    Uses FlatLambdaCDM comoving distance. Vectorised over numpy arrays.
    """
    d_c = COSMO.comoving_distance(z).value  # Mpc

    ra_rad = np.radians(ra_deg)
    dec_rad = np.radians(dec_deg)

    x = d_c * np.cos(dec_rad) * np.cos(ra_rad)
    y = d_c * np.cos(dec_rad) * np.sin(ra_rad)
    z_cart = d_c * np.sin(dec_rad)

    return x.astype(np.float32), y.astype(np.float32), z_cart.astype(np.float32)


def process_fits(fits_path: Path, tracer_id: int) -> pa.Table:
    """Read a FITS catalog and return a PyArrow table with XYZ + metadata."""
    with fits.open(fits_path, memmap=True) as hdul:
        data = hdul["LSS"].data
        ra = np.asarray(data["RA"], dtype=np.float64)
        dec = np.asarray(data["DEC"], dtype=np.float64)
        z = np.asarray(data["Z"], dtype=np.float64)
        weight = np.asarray(data["WEIGHT"], dtype=np.float32)

    # Quality cuts: valid redshifts only
    mask = (z > 0.001) & (z < 5.0) & np.isfinite(ra) & np.isfinite(dec)
    ra, dec, z, weight = ra[mask], dec[mask], z[mask], weight[mask]

    x, y, z_cart = radec_z_to_xyz(ra, dec, z)

    table = pa.table(
        {
            "ra": pa.array(ra.astype(np.float32)),
            "dec": pa.array(dec.astype(np.float32)),
            "z": pa.array(z.astype(np.float32)),
            "x": pa.array(x),
            "y": pa.array(y),
            "z_cart": pa.array(z_cart),
            "weight": pa.array(weight),
            "tracer": pa.array(np.full(len(ra), tracer_id, dtype=np.uint8)),
        }
    )

    return table


def process_all() -> None:
    console.rule("[bold cyan]DESI DR1 — FITS → Parquet Processing")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    fits_files = sorted(DATA_DIR.glob("*_clustering.dat.fits"))
    if not fits_files:
        console.print(f"[red]No .dat.fits files found in {DATA_DIR}/[/]")
        console.print("Run [bold]mise run fetch[/] first.")
        raise SystemExit(1)

    stats_table = Table(title="Processing Summary")
    stats_table.add_column("Catalog", style="cyan")
    stats_table.add_column("Tracer", style="magenta")
    stats_table.add_column("Galaxies", justify="right", style="green")
    stats_table.add_column("z range", justify="right")
    stats_table.add_column("Output", style="dim")

    all_tables = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        for fits_path in fits_files:
            task = progress.add_task(f"Processing {fits_path.name}…", total=None)

            tracer_id = get_tracer_id(fits_path.name)
            table = process_fits(fits_path, tracer_id)

            out_path = PROCESSED_DIR / fits_path.with_suffix(".parquet").name
            pq.write_table(table, out_path, compression="zstd")

            z_arr = table["z"].to_pylist()
            z_min = min(z_arr)
            z_max = max(z_arr)

            stats_table.add_row(
                fits_path.name.replace("_clustering.dat.fits", ""),
                TRACER_NAMES[tracer_id],
                f"{len(table):,}",
                f"{z_min:.3f}–{z_max:.3f}",
                out_path.name,
            )

            all_tables.append(table)
            progress.remove_task(task)

    # Write combined catalog
    combined = pa.concat_tables(all_tables)
    combined_path = PROCESSED_DIR / "all_galaxies.parquet"
    pq.write_table(combined, combined_path, compression="zstd")

    console.print(stats_table)
    console.print(f"\n[bold green]✓ Combined catalog: {len(combined):,} galaxies → {combined_path}[/]")


if __name__ == "__main__":
    process_all()

"""
process.py — Convert DESI FITS catalogs to XYZ Cartesian coordinates.

Reads RA, Dec, Z from clustering .dat.fits files, converts to comoving
Cartesian coordinates (Mpc) using Planck 2018 flat ΛCDM cosmology,
and writes Parquet files for further processing.

BGS catalogs additionally export flux_g_dered and flux_r_dered (dereddened
fluxes in nanomaggies) so that g-r colour can be computed downstream.
ELG/LRG/QSO clustering catalogs do not carry flux columns; they get NaN.
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

# Random (density-field) catalogs — huge; only a bounded subset is processed so
# the parquet + web binary stay feasible. Each random file is ~200 MB / ~1.8M rows.
RANDOM_FILES = [
    "BGS_BRIGHT_N_0_clustering.ran.fits",
    "BGS_BRIGHT_S_0_clustering.ran.fits",
    "LRG_N_0_clustering.ran.fits",
    "LRG_S_0_clustering.ran.fits",
    "ELG_LOPnotqso_N_0_clustering.ran.fits",
    "ELG_LOPnotqso_S_0_clustering.ran.fits",
    "QSO_N_0_clustering.ran.fits",
    "QSO_S_0_clustering.ran.fits",
]
# Subsample each random file to this many rows before combining (keeps the
# density layer bounded). 8 files × ~225k ≈ 1.8M randoms.
RANDOM_SAMPLE_PER_FILE = 225_000

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
    """Read a FITS catalog and return a PyArrow table with XYZ + metadata.

    For BGS catalogs (tracer_id == 0) flux_g_dered and flux_r_dered are
    preserved so that g-r colour can be computed in reduce.py.  All other
    tracers receive NaN for those columns (they carry no flux data).
    """
    with fits.open(fits_path, memmap=True) as hdul:
        data = hdul["LSS"].data
        ra = np.asarray(data["RA"], dtype=np.float64)
        dec = np.asarray(data["DEC"], dtype=np.float64)
        z = np.asarray(data["Z"], dtype=np.float64)
        weight = np.asarray(data["WEIGHT"], dtype=np.float32)

        # Flux columns are only present in BGS files
        col_names = [c.name.lower() for c in hdul["LSS"].columns]
        if "flux_g_dered" in col_names and "flux_r_dered" in col_names:
            flux_g = np.asarray(data["flux_g_dered"], dtype=np.float32)
            flux_r = np.asarray(data["flux_r_dered"], dtype=np.float32)
        else:
            flux_g = np.full(len(ra), np.nan, dtype=np.float32)
            flux_r = np.full(len(ra), np.nan, dtype=np.float32)

    # Quality cuts: valid redshifts only
    mask = (z > 0.001) & (z < 5.0) & np.isfinite(ra) & np.isfinite(dec)
    ra, dec, z, weight = ra[mask], dec[mask], z[mask], weight[mask]
    flux_g, flux_r = flux_g[mask], flux_r[mask]

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
            "flux_g": pa.array(flux_g),
            "flux_r": pa.array(flux_r),
        }
    )

    return table


def process_randoms() -> None:
    """Process a bounded subset of random catalogs into all_randoms.parquet.

    Randoms are the unclustered density-field sample (~100× galaxies). We pull a
    fixed small set of files and subsample each, so the result stays feasible to
    ship. kind=1 tags them for the web viewer's separate random layer.
    """
    random_paths = [DATA_DIR / f for f in RANDOM_FILES if (DATA_DIR / f).exists()]
    if not random_paths:
        console.print("[dim]No random catalogs found — skipping density layer. Run 'mise run fetch-randoms' first.[/]")
        return

    rng = np.random.default_rng(11)
    parts = []
    for fits_path in random_paths:
        task_tid = get_tracer_id(fits_path.name.replace("_clustering.ran", "_clustering"))
        table = process_fits(fits_path, task_tid)
        n = len(table)
        if n > RANDOM_SAMPLE_PER_FILE:
            idx = rng.choice(n, RANDOM_SAMPLE_PER_FILE, replace=False)
            table = table.take(idx)
        # tag as random (kind=1)
        table = table.append_column("kind", pa.array(np.ones(len(table), dtype=np.uint8)))
        parts.append(table)
        console.print(f"  random {fits_path.name}: {len(table):,}")

    combined = pa.concat_tables(parts)
    out_path = PROCESSED_DIR / "all_randoms.parquet"
    pq.write_table(combined, out_path, compression="zstd")
    console.print(f"[bold green]✓ Random density layer: {len(combined):,} → {out_path}[/]")


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

    # Randoms (density layer) — optional, bounded
    process_randoms()

    console.print(stats_table)
    console.print(f"\n[bold green]✓ Combined catalog: {len(combined):,} galaxies → {combined_path}[/]")


if __name__ == "__main__":
    process_all()

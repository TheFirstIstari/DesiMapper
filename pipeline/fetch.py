"""
fetch.py — Async streaming download of DESI LSS clustering catalogs.

Downloads only the small *.dat.fits galaxy data files (not the large random catalogs).
Uses HTTP range requests + async I/O to maximise throughput.
"""

import asyncio
import os
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console()

BASE_URL = os.environ.get(
    "DESI_BASE_URL",
    "https://data.desi.lbl.gov/public/dr1/vac/dr1/lss/guadalupe/v1.0/LSScats/clustering",
)

DATA_DIR = Path(os.environ.get("DESI_DATA_DIR", "data/raw"))

# Only the galaxy data catalogs — NOT the large random files (*.ran.fits)
CATALOGS = [
    "BGS_BRIGHT_N_clustering.dat.fits",
    "BGS_BRIGHT_S_clustering.dat.fits",
    "BGS_BRIGHT-21.5_N_clustering.dat.fits",
    "BGS_BRIGHT-21.5_S_clustering.dat.fits",
    "LRG_N_clustering.dat.fits",
    "LRG_S_clustering.dat.fits",
    "ELG_LOPnotqso_N_clustering.dat.fits",
    "ELG_LOPnotqso_S_clustering.dat.fits",
    "QSO_N_clustering.dat.fits",
    "QSO_S_clustering.dat.fits",
]

# Max concurrent downloads — be respectful to the DESI server
MAX_CONCURRENT = 3


async def download_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    progress: Progress,
    task_id: TaskID,
) -> None:
    """Stream a single file to disk with progress tracking."""
    if dest.exists():
        console.print(f"[green]✓ Already downloaded:[/] {dest.name}")
        progress.update(task_id, visible=False)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")

    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            progress.update(task_id, total=total)

            with open(tmp, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)
                    progress.advance(task_id, len(chunk))

        tmp.rename(dest)
        progress.update(task_id, description=f"[green]✓ {dest.name}")
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        progress.update(task_id, description=f"[red]✗ {dest.name}: {exc}")
        raise


async def fetch_all() -> None:
    console.rule("[bold cyan]DESI DR1 — Catalog Download")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    progress = Progress(
        TextColumn("[bold blue]{task.description}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.0f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def bounded_download(client, url, dest, progress, task_id):
        async with semaphore:
            await download_file(client, url, dest, progress, task_id)

    timeout = httpx.Timeout(30.0, read=None)
    limits = httpx.Limits(max_connections=MAX_CONCURRENT, max_keepalive_connections=MAX_CONCURRENT)

    with progress:
        async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True) as client:
            tasks = []
            for catalog in CATALOGS:
                url = f"{BASE_URL}/{catalog}"
                dest = DATA_DIR / catalog
                task_id = progress.add_task(f"[cyan]{catalog}", total=None)
                tasks.append(bounded_download(client, url, dest, progress, task_id))

            results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        console.print(f"\n[red]✗ {len(errors)} download(s) failed.[/]")
        for e in errors:
            console.print(f"  [red]{e}[/]")
        raise SystemExit(1)

    console.print(f"\n[bold green]✓ All {len(CATALOGS)} catalogs downloaded to {DATA_DIR}/[/]")


def main():
    asyncio.run(fetch_all())


if __name__ == "__main__":
    main()

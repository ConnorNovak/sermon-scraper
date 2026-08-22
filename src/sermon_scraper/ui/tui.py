"""Terminal User Interface for the sermon-scraper, built with rich and plac."""

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

import pandas as pd
import plac  # type: ignore [import-untyped]
import requests
from rich.console import Console
from rich.table import Table
from tqdm import tqdm

from ..constants import DEFAULT_CSV
from ..utilities import retrieve_resource, retrieve_resource_length_in_bytes, slugify
from .cli import csv_file_annotation
from .dialog import (
    get_directory,
    get_report_file_dialog,
    load_csv_file_dialog,
)

SPEAKER_KEY = "preachers"
SERIES_KEY = "series"
AUDIO_SIZE_MB_KEY = "audio-size-mb"
VIDEO_SIZE_MB_KEY = "video-size-mb"
NOTES_SIZE_MB_KEY = "notes-size-mb"
NOTES_KEY = "notes"
AUDIO_KEY = "audio"
VIDEO_KEY = "video"
SERMON_ID_KEY = "sermon_id"
DATE_KEY = "date"
AUDIO_SOURCE_KEY = "audio-source"
SOURCE_MODE = "source"
S3_SOURCE = "s3.amazonaws.com"
RACKCDN_SOURCE = "rackcdn"

tqdm.pandas()

_console = Console(highlight=False)
_logger = logging.getLogger(__name__)


def calculate_resource_sizes(
    df: pd.DataFrame,
    url_column_name: str,
    max_worker_count: int,
    new_column_name: str,
    overwrite: bool = False,
    session: requests.Session | None = None,
) -> None:
    """Calculate the sizes of resources in MB for a given URL column in a DataFrame.

    :note: Modifies the DataFrame in place by adding a new column with the calculated sizes.

    :param df: The DataFrame containing the URLs.
    :param url_column_name: The name of the column containing the URLs.
    :param max_worker_count: The maximum number of worker threads to use for downloading.
    :param new_column_name: The name of the new column to store the sizes in MB.
    :param overwrite: If True, will overwrite the new column if it already exists. If False, will raise an error if the new column already exists.
    """
    if new_column_name in df.columns and not overwrite:
        raise ValueError(
            f"Column '{new_column_name}' already exists in the DataFrame. Set 'overwrite=True' to overwrite it."
        )
    with ThreadPoolExecutor(max_workers=max_worker_count) as executor:
        df[new_column_name] = list(
            tqdm(
                executor.map(
                    lambda url: (
                        retrieve_resource_length_in_bytes(url, session) / (1024 * 1024)
                        if pd.notnull(url)
                        else 0
                    ),
                    df[url_column_name],
                ),
                total=len(df[url_column_name]),
            )
        )


def classify_audio_source(url: str | None) -> str | None:
    """Classify an audio URL by hosting source.

    :param url: The audio URL to classify.
    :return: One of ``S3_SOURCE``, ``RACKCDN_SOURCE``, or ``"Unknown"`` if the host matches
        neither. ``None`` if url is null/missing.
    """
    if pd.isnull(url):
        return None
    netloc = urlparse(str(url)).netloc
    if S3_SOURCE in netloc:
        return S3_SOURCE
    if RACKCDN_SOURCE in netloc:
        return RACKCDN_SOURCE
    return "Unknown"


def _get_git_info() -> tuple[str, bool]:
    """Return (short commit hash, is_dirty) for the sermon-scraper repo.

    :return: ("unknown", False) if git is unavailable or this isn't a git checkout (e.g.
        installed from a built wheel).
    """
    repo_dir = Path(__file__).resolve().parent
    try:
        commit_hash = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return commit_hash, bool(status.strip())
    except subprocess.CalledProcessError, FileNotFoundError:
        return "unknown", False


def generate_report(
    report_title: str,
    df: pd.DataFrame,
    filesize_units: str = "GB",
) -> str:
    """Generate a report from the sermon data.

    Displays the following:
    - git hash of the sermon-scraper generation tool + dirty flag
    - date of generation
    - Section 1: Overview
        - total count of sermons
        - total size of audio resources in `filesize_units`

    - Section 2: Speakers
        - # of unique speakers
         - For each speaker:
            - # of sermons
            - date range
            - total size of resources in `filesize_units`
            - unique series titles

    - Section 3: Series
        - # of unique series
         - For each series:
            - # of sermons
            - date range
            - total size of resources in `filesize_units`
            - unique speakers

    :param report_title: The title of the report.
    :param df: The DataFrame to generate the report from.
    :param filesize_units: The units to display file sizes in. Can be ["KB", "MB", "GB"]. Defaults
        to "GB".

    :return: a string blob of the report, as rich-styled HTML (feed straight into e.g.
        ``weasyprint.HTML(string=blob).write_pdf(path)`` to get a PDF).
    """
    console = Console(record=True, width=100, highlight=False)

    size_columns = [
        c for c in (NOTES_SIZE_MB_KEY, AUDIO_SIZE_MB_KEY, VIDEO_SIZE_MB_KEY) if c in df.columns
    ]

    def total_size_mb(sub_df: pd.DataFrame) -> float:
        if not size_columns:
            return 0.0
        return float(sub_df[size_columns].sum(numeric_only=True).to_numpy().sum())

    def date_range(sub_df: pd.DataFrame) -> str:
        if "date" not in sub_df.columns:
            return "Unknown"
        dates = pd.to_datetime(sub_df[DATE_KEY], errors="coerce").dropna()
        if dates.empty:
            return "Unknown"
        lo, hi = dates.min(), dates.max()
        if lo == hi:
            return lo.strftime("%Y-%m-%d")
        return f"{lo.strftime('%Y-%m-%d')} to {hi.strftime('%Y-%m-%d')}"

    def sources(sub_df: pd.DataFrame) -> str:
        if AUDIO_SOURCE_KEY not in sub_df.columns:
            return "-"
        found = sorted(sub_df[AUDIO_SOURCE_KEY].dropna().unique())
        return ", ".join(found) if found else "-"

    table_style = dict(
        title_style="blue",
        header_style="white",
        border_style="blue",
        row_styles=["white", "dim"],
        show_lines=True,
    )

    valid_units = ("KB", "MB", "GB")
    if filesize_units not in valid_units:
        raise ValueError(f"filesize_units must be one of {valid_units}, got {filesize_units!r}")
    mb_per_unit = {"KB": 1 / 1024, "MB": 1, "GB": 1024}[filesize_units]

    def convert_size(value_mb: float) -> float:
        return value_mb / mb_per_unit

    console.rule(f"[bold blue]{report_title}[/bold blue]")
    git_hash, is_dirty = _get_git_info()
    console.print(f"[dim]Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]")
    console.print(f"[dim]sermon-scraper commit: {git_hash}{' (dirty)' if is_dirty else ''}[/dim]")
    console.print()

    missing_column_hints = [
        (AUDIO_SIZE_MB_KEY, f"calculate {AUDIO_KEY}"),
        (VIDEO_SIZE_MB_KEY, f"calculate {VIDEO_KEY}"),
        (NOTES_SIZE_MB_KEY, f"calculate {NOTES_KEY}"),
        (AUDIO_SOURCE_KEY, f"calculate {SOURCE_MODE}"),
    ]
    missing = [(col, cmd) for col, cmd in missing_column_hints if col not in df.columns]
    if missing:
        console.print(
            "[yellow]Warning:[/yellow] some report data will be incomplete. Run these first:"
        )
        for col, cmd in missing:
            console.print(f"  - '{col}' missing → run '[bold]{cmd}[/bold]'")
        console.print()

    # --- Section 1: Overview ---
    console.rule("[bold]Section 1: Overview[/bold]")
    overview = Table(show_header=False, **{**table_style, "row_styles": ["white"]})
    overview.add_column("metric", justify="left")
    overview.add_column("value", justify="right")
    overview.add_row("Total sermons", str(len(df)))
    if AUDIO_SIZE_MB_KEY in df.columns:
        total_audio_mb = float(df[AUDIO_SIZE_MB_KEY].sum())
        overview.add_row(
            f"Total audio size ({filesize_units})", f"{convert_size(total_audio_mb):,.1f}"
        )
    console.print(overview)
    console.print()

    # --- Section 2: Speakers ---
    if SPEAKER_KEY in df.columns:
        console.rule("[bold]Section 2: Speakers[/bold]")
        console.print(f"Unique speakers: {df[SPEAKER_KEY].nunique()}")
        console.print()
        speaker_table = Table(**table_style)
        speaker_table.add_column("Speaker", justify="left")
        speaker_table.add_column("# Sermons", justify="right")
        speaker_table.add_column("Date Range", justify="left")
        speaker_table.add_column(f"Size ({filesize_units})", justify="right")
        speaker_table.add_column("Series", justify="left")
        speaker_table.add_column("Source", justify="left")
        for speaker in sorted(df[SPEAKER_KEY].dropna().unique()):
            sub = df[df[SPEAKER_KEY] == speaker]
            series_titles = (
                sorted(sub[SERIES_KEY].dropna().unique()) if SERIES_KEY in sub.columns else []
            )
            speaker_table.add_row(
                str(speaker),
                str(len(sub)),
                date_range(sub),
                f"{convert_size(total_size_mb(sub)):,.1f}",
                ", ".join(series_titles) if series_titles else "-",
                sources(sub),
            )
        console.print(speaker_table)
        console.print()
    else:
        console.print("[dim]No 'speaker' column found in the CSV file. Skipping Section 2.[/dim]")
        console.print()

    # --- Section 3: Series ---
    if SERIES_KEY in df.columns:
        console.rule("[bold]Section 3: Series[/bold]")
        console.print(f"Unique series: {df['series'].nunique()}")
        console.print()
        series_table = Table(**table_style)
        series_table.add_column("Series", justify="left")
        series_table.add_column("# Sermons", justify="right")
        series_table.add_column("Date Range", justify="left")
        series_table.add_column(f"Size ({filesize_units})", justify="right")
        series_table.add_column("Speakers", justify="left")
        series_table.add_column("Source", justify="left")
        for series in sorted(df[SERIES_KEY].dropna().unique()):
            sub = df[df[SERIES_KEY] == series]
            speakers = (
                sorted(sub[SPEAKER_KEY].dropna().unique()) if SPEAKER_KEY in sub.columns else []
            )
            series_table.add_row(
                str(series),
                str(len(sub)),
                date_range(sub),
                f"{convert_size(total_size_mb(sub)):,.1f}",
                ", ".join(speakers) if speakers else "-",
                sources(sub),
            )
        console.print(series_table)
    if SERIES_KEY not in df.columns:
        console.print("[dim]No 'series' column found in the CSV file. Skipping Section 3.[/dim]")
        console.print()

    return console.export_html(inline_styles=True)


def download_resources(
    resources: Sequence[tuple[str, str]],
    destination_dir: Path,
    max_worker_count: int,
    overwrite: bool = False,
    session: requests.Session | None = None,
) -> None:
    """Calculate the sizes of resources in MB for a given URL column in a DataFrame.

    :note: Modifies the DataFrame in place by adding a new column with the calculated sizes.

    :param resources: A sequence of tuples containing the resource URL and the filename to save it as.
    :param max_worker_count: The maximum number of worker threads to use for downloading.
    :param overwrite: If True, will overwrite the new column if it already exists. If False, will raise an error if the new column already exists.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_worker_count) as executor:
        futures = [
            executor.submit(
                retrieve_resource,
                resource[0],
                destination_dir / (resource[1] + resource[0][-4:]),
                session=session,
            )
            for resource in resources
            if pd.notnull(resource[0])
        ]
        for future in tqdm(as_completed(futures), total=len(futures)):
            future.result()  # surfaces any exception instead of swallowing it


class TUI:
    """sermon-scraper interactive tool."""

    commands = ["calculate", "download", "load", "report", "show", "quit"]

    def __init__(self, max_retry_count: int = 3, max_worker_count: int = 16) -> None:
        """Initialize the TUI."""
        self._df: pd.DataFrame | None = None
        self._max_retry_count = max_retry_count
        self._max_worker_count = max_worker_count
        self.should_exit = False

        # Requests session w/ multiple workers to speed up resource downloads.
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=max_worker_count, pool_maxsize=max_worker_count
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    @plac.annotations(
        series=plac.Annotation(
            help="Series to download",
        ),
        destination_dir=plac.Annotation(
            help="Directory to download the series to. If None, will prompt for a directory.",
            kind="option",
            type=Path,
        ),
    )
    def download(self, series: str, destination_dir: Path | None = None) -> None:
        """Download all resources for a given series."""
        if self._df is None:
            _console.print("[red]Error:[/red] No CSV file loaded. Please load a CSV file first.")
            return

        if series not in self._df[SERIES_KEY].unique():
            _console.print(f"[red]Error:[/red] Series '{series}' not found in the database.")
            return

        if destination_dir is None:
            destination_dir = get_directory()
        if destination_dir is None:
            _console.print("[red]Error:[/red] No destination directory selected.")
            return

        sub_df = self._df[self._df[SERIES_KEY] == series]
        for row in sub_df.iterrows():
            # Write sub_df to CSV
            sub_df.to_csv(destination_dir / f"{series}.csv", index=False)

            # Download audio
            resources = [
                (sub_df[AUDIO_KEY].iloc[i], slugify(str(sub_df[SERMON_ID_KEY].iloc[i])))
                for i in range(len(sub_df))
            ]
            download_resources(
                resources, destination_dir, self._max_worker_count, session=self._session
            )

    @plac.annotations(
        key=plac.Annotation(
            help="List unique instances in the database for a given key (e.g., 'speaker', 'series', 'topic').",
        ),
    )
    def show(self, key: str | None = None) -> None:
        """List unique instances underneath a given key.

        :param key: key to list instances for - will be slugified. If None given, prints a list of
            available keys.
        """
        if key is not None:
            slug = slugify(key)
            if slug not in self._df.columns:
                _console.print(f"[red]Error:[/red] Key '{key}' not found in the database.")
                key = None  # Reset key to None to show available keys below.
            else:
                table = Table(
                    title=f"Unique '{key}' Entries",
                    title_style="blue",
                    header_style="white",
                    border_style="blue",
                    row_styles=["white"],
                )
                table.add_column("count", justify="center")
                table.add_column(key)
                total = 0
                for value in self._df[slug].dropna().sort_values().unique():
                    count = (self._df[slug] == value).sum()
                    total += count
                    table.add_row(*[str(count), str(value)])

                table.add_row(*[str(total), "Total"])
                _console.print(table)

        if key is None:
            table = Table(
                title="Available Keys",
                title_style="blue",
                header_style="blue",
                border_style="blue",
                row_styles=["white"],
            )
            table.add_column("key", justify="left")
            for col in sorted(list(self._df.columns)):
                table.add_row(col)
            _console.print(table)
        return

    @plac.annotations(
        csv_file=csv_file_annotation,
    )
    def load(self, csv_file: Path | str) -> None:
        """Load a CSV file into the TUI.

        :param csv_file: Path to the CSV file to load. If "None", unloads the csv file.
        """
        if csv_file is None:
            _console.print(
                "[blue]Please provide a CSV file path to load, or 'None' to unload the current CSV file.[/blue]"
            )
            return

        if csv_file == "None":
            if self._df is not None:
                _logger.debug("Unloading CSV file.")
            del self._df  # free the memory!
            self._df = None
            return

        if not csv_file.exists():
            _console.print(f"[red]Error:[/red] CSV file not found: {csv_file}")
            return

        try:
            df = pd.read_csv(csv_file)
            _console.print(f"[green]Loaded CSV file:[/green] {csv_file}")
        except Exception as e:
            _console.print(f"[red]Error loading CSV file:[/red] {e}")

        # Only update internal state after the loading works successfully.
        self._csv_file = csv_file
        self._df = pd.DataFrame()
        for col in df.columns:
            slug = slugify(col)
            _logger.debug("Ingesting '%s' as '%s'", col, slug)
            self._df[slug] = df[col]

    @plac.annotations(
        mode=plac.Annotation(
            help="The mode of resources to calculate sizes for. Can be 'notes', 'audio', 'video', or "
            "'source' (divides audio by hosting source).",
            choices=[NOTES_KEY, AUDIO_KEY, VIDEO_KEY, SOURCE_MODE],
        ),
        overwrite=plac.Annotation(
            help="If True, will overwrite the size column if it already exists. If False, will raise an error if the size column already exists.",
            type=bool,
            kind="flag",
        ),
    )
    def calculate(self, mode: str, overwrite: bool = False) -> None:
        """Calculate the sizes of resources in MB for a given mode, or classify audio by source.

        :param mode: The mode of resources to calculate sizes for. Can be 'notes', 'audio', 'video',
            or 'source'.
        """
        if self._df is None:
            _console.print("[red]Error:[/red] No CSV file loaded. Please load a CSV file first.")
            return

        modes = (NOTES_KEY, AUDIO_KEY, VIDEO_KEY, SOURCE_MODE)
        if mode not in modes:
            _console.print(f"[red]Error:[/red] Invalid mode '{mode}'. Please choose from {modes}.")
            return

        if mode == SOURCE_MODE:
            if AUDIO_SOURCE_KEY in self._df.columns and not overwrite:
                _console.print(
                    f"[red]Error:[/red] Column '{AUDIO_SOURCE_KEY}' already exists. "
                    "Set 'overwrite=True' to overwrite it."
                )
                return
            if AUDIO_KEY not in self._df.columns:
                _console.print(f"[red]Error:[/red] '{AUDIO_KEY}' column not found in the CSV file.")
                return

            self._df[AUDIO_SOURCE_KEY] = self._df[AUDIO_KEY].apply(classify_audio_source)
            _console.print(
                f"[green]Classified audio sources and stored in column '{AUDIO_SOURCE_KEY}'.[/green]"
            )
            return

        if mode not in self._df.columns:
            _console.print(f"[red]Error:[/red] '{mode}' column not found in the CSV file.")
            return

        new_column_name = f"{mode}-size-mb"
        calculate_resource_sizes(
            df=self._df,
            url_column_name=mode,
            max_worker_count=self._max_worker_count,
            new_column_name=new_column_name,
            overwrite=overwrite,
            session=self._session,
        )
        _console.print(
            f"[green]Calculated sizes for '{mode}' resources and stored in column '{new_column_name}'.[/green]"
        )

    @plac.annotations(
        csv_file=csv_file_annotation,
    )
    def save(self, csv_file: Path | str) -> None:
        """Save the current DataFrame to a CSV file.

        :param csv_file: Path to the CSV file to save. If "None", will not save.
        """
        if self._df is None:
            _console.print("[red]Error:[/red] No CSV file loaded. Please load a CSV file first.")
            return

        if csv_file == "None":
            _console.print("[blue]No CSV file specified. Not saving.[/blue]")
            return

        try:
            self._df.to_csv(csv_file, index=False)
            _console.print(f"[green]Saved DataFrame to CSV file:[/green] {csv_file}")
        except Exception as e:
            _console.print(f"[red]Error saving DataFrame to CSV file:[/red] {e}")

    @plac.annotations(
        report_title=plac.Annotation(
            help="Title for the report.",
        ),
        output_file=plac.Annotation(
            help="Path to write the report HTML to. If None, will prompt for a file to save to.",
            kind="option",
            type=Path,
        ),
    )
    def report(self, report_title: str, output_file: Path | None = None) -> None:
        """Generate a report on the loaded sermon data and write it out as HTML.

        :param report_title: Title for the report.
        :param output_file: Path to write the report HTML to. If None, will prompt for a file to
            save to.
        """
        if self._df is None:
            _console.print("[red]Error:[/red] No CSV file loaded. Please load a CSV file first.")
            return

        if output_file is None:
            output_file = get_report_file_dialog()
        if output_file is None:
            _console.print("[red]Error:[/red] No output file selected.")
            return

        html = generate_report(report_title, self._df)
        output_file.write_text(html)
        _console.print(f"[green]Report written to:[/green] {output_file}")
        _console.print(
            f"[dim]Convert to PDF, e.g.: weasyprint {output_file} {output_file.with_suffix('.pdf')}[/dim]"
        )

    def quit(self) -> None:
        """Save the current data to the DEFAULT_CSV and exit the TUI."""
        self.save(DEFAULT_CSV)
        self.load(None)
        self.should_exit = True


@plac.annotations(
    csv_file=csv_file_annotation,
)
def main(csv_file: Path | None = None) -> None:
    """Run the sermon-scraper TUI."""
    tui = TUI()

    # Optionally load file
    if csv_file is None:
        csv_file = load_csv_file_dialog()
    if csv_file is not None:
        tui.load(csv_file)

    with plac.Interpreter(tui) as i:
        i.interact(prompt="sermon-scraper> ")


if __name__ == "__main__":
    plac.call(main)

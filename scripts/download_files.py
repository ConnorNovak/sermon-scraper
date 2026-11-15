"""Script to download all of the files specified in a given .csv.

This script copies the target .csv into the target directory, then downloads all of the files
into that directory. Files targeted are all of the links in the "audio" column.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd
import plac  # type: ignore [import-untyped]
import requests

from sermon_scraper.rate_limit import KeyedRateLimiter
from sermon_scraper.retrieve import retrieve_resource

_logger = logging.getLogger(__name__)


def clean_df_ekklesia(df: pd.DataFrame) -> None:
    """Perform the following cleaning operations in-place on the given dataframe.

    - Lowercase all column names
    - Rename "preachers" to "speaker"
    - Rename "sermon id" to "sermon_id"
    - Convert "date" column to datetime
    - Add a "source" column with the value "ekklesia"
    - Sort the dataframe by the "date" column

    :param df: The dataframe to clean.
    """
    df.columns = df.columns.str.lower()
    df.rename(
        inplace=True,
        columns={
            "preachers": "speaker",
            "sermon id": "sermon_id",
        },
    )
    df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce", utc=True)
    df["source"] = "ekklesia"

    df.sort_values(by="date")


@plac.annotations(
    csv_path=plac.Annotation(
        "Path to the .csv file containing the links to download",
        type=Path,
    ),
    target_dir=plac.Annotation(
        "Path to the directory where the files will be downloaded",
        type=Path,
    ),
    source=plac.Annotation(
        "Source of the .csv file, either 'ekklesia' or 'subsplash'",
        choices=["ekklesia", "subsplash"],
    ),
    no_cache=plac.Annotation(
        "If set, will not use cached files and will re-download all files",
        type=bool,
    ),
)
def main(
    csv_path: Path,
    target_dir: Path,
    source: Literal["ekklesia", "subsplash"],
    no_cache: bool = False,
) -> None:
    """Download all of the files specified by a given .csv file assumed to be downloaded from
    Ekklesia or Subsplash.
    """
    # Set up logger
    _handler = logging.FileHandler(target_dir / "download.log", mode="a", encoding="utf-8")
    _formatter = logging.Formatter("%(message)s")  # Raw message, as we'll just log json
    _handler.setFormatter(_formatter)
    _handler.setLevel(logging.INFO)
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)

    # Read and clean the .csv file
    df = pd.read_csv(csv_path)
    match source:
        case "ekklesia":
            clean_df_ekklesia(df)
        case "subsplash":
            raise NotImplementedError("Subsplash source is not yet implemented.")

    df.to_csv(
        target_dir / f"{csv_path.name}_clean.csv", index=False
    )  # Copy the .csv to the target directory

    session: requests.Session | None = None
    for _, row in df.iterrows():
        audio_url = str(row["audio"])
        file_path = target_dir / Path(audio_url).name
        log_data = {"url": audio_url, "file_path": file_path}
        download = True
        if file_path.exists():
            if no_cache:
                log_data["action"] = "re-downloading"
            else:
                log_data["action"] = "skipping"
                download = False
        else:
            log_data["action"] = "downloading"

        log_data["error"] = None
        log_data["success"] = None
        log_data["datetime_begin"] = None
        log_data["datetime_end"] = None
        print(f"{log_data['action']} {audio_url}")
        if download:
            if session is None:
                session = requests.Session()

            # This line is a bit aggregious, but it hardcore ensures parent directory exists.
            file_path.parent.mkdir(parents=True, exist_ok=True)
            log_data["datetime_begin"] = datetime.now().isoformat()
            try:
                retrieve_resource(
                    url=audio_url,
                    destination=file_path,
                    session=session,
                    rate_limiter=KeyedRateLimiter(),
                    enable_tqdm=True,
                )
                log_data["error"] = None
                log_data["success"] = True
            except Exception as err:
                file_path.unlink(missing_ok=True)  # Remove the file if it was partially downloaded
                log_data["error"] = str(err)
                log_data["success"] = False

            log_data["datetime_end"] = datetime.now().isoformat()
            _logger.info(log_data)


if __name__ == "__main__":
    plac.call(main)

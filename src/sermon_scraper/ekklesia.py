"""Ekklesia-specific tools."""

import pandas as pd


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

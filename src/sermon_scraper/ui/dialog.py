"""Tkinter dialogs."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from ..constants import DEFAULT_CSV


def load_csv_file_dialog() -> Path | None:
    """Open a file dialog to select a CSV file.

    :return: The selected CSV file path, or None if no file was selected.
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    csv_file_path = filedialog.askopenfilename(
        initialdir=DEFAULT_CSV.parent,
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
    )
    return Path(csv_file_path) if csv_file_path else None


def get_report_file_dialog() -> Path | None:
    """Open a file dialog to select where to save the report HTML.

    :return: The selected file path, or None if no file was selected.
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    file_path = filedialog.asksaveasfilename(
        initialdir=DEFAULT_CSV.parent,
        defaultextension=".html",
        filetypes=[("HTML files", "*.html"), ("All files", "*.*")],
    )
    return Path(file_path) if file_path else None


def get_directory() -> Path | None:
    """Open a file dialog to select a directory.

    :return: The selected directory path, or None if no directory was selected.
    """
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    dir_path = filedialog.askdirectory(
        initialdir=DEFAULT_CSV.parent,
    )
    return Path(dir_path) if dir_path else None

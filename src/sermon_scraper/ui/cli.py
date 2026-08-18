import sys
from pathlib import Path

import plac  # type: ignore [import-untyped]

output_dir_annotation = plac.Annotation(
    help="directory to write series/episodes into",
    kind="option",
    type=Path,
)

csv_file_annotation = plac.Annotation(
    help="Path to the CSV file to load.",
    type=Path,
    kind="option",
)


def prompt_choice(choices: list[str]) -> int:
    """Prompt the user to choose from a list of choices, returning the index of the selected choice.

    :param choices: A list of strings representing the choices.
    :return: The index of the selected choice in the choices list.
    :raises SystemExit: If the user chooses to quit by entering 'q'.
    """
    while True:
        buf = len(str(len(choices)))
        for i, choice in enumerate(choices):
            print(f"{i + 1:{buf}}) {choice}")
        selection = input("Select entry by number [1-N|q]: ")
        if selection.lower() == "q":
            raise sys.exit("User chose to quit.")
        try:
            index = int(selection) - 1
            if 0 <= index < len(choices):
                return index
            else:
                print(f"Invalid choice. Please enter a number between 1 and {len(choices)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")


def prompt_yes_no(question: str) -> bool:
    """Prompt the user with a yes/no question and return True for yes, False for no.

    :param question: The question to ask the user.
    :return: True if the user answered yes, False if the user answered no.
    """
    while True:
        answer = input(f"{question} [y|n|q]: ").strip().lower()
        if answer == "q":
            raise SystemExit("User chose to quit.")
        if answer in ("y", "yes"):
            return True
        elif answer in ("n", "no"):
            return False
        else:
            print("Invalid input. Please enter 'y' or 'n'.")

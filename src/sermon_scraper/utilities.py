import re


def slugify(text: str) -> str:
    """Convert a string into a slug suitable for filenames or URLs."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)

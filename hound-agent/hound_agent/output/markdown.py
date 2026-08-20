"""Safe rendering helpers for untrusted text in generated Markdown."""
from __future__ import annotations


def escape_text(value: object) -> str:
    text = str(value or "")
    for char in ("\\", "`", "*", "_", "{", "}", "[", "]", "<", ">", "#", "|", "!"):
        text = text.replace(char, "\\" + char)
    return text.replace("\r", "").replace("\n", "  \n")


def escape_code(value: object) -> str:
    return str(value or "").replace("`", "'").replace("\r", " ").replace("\n", " ")

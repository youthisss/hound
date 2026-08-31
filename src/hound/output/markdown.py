"""Safe rendering helpers for untrusted text in generated Markdown."""
from __future__ import annotations


def sanitize_text(value: object) -> str:
    """Strip terminal control bytes while preserving readable whitespace."""
    return "".join(
        char for char in str(value or "")
        if char in {"\n", "\t"} or (ord(char) >= 32 and not 127 <= ord(char) <= 159)
    )


def escape_text(value: object) -> str:
    text = sanitize_text(value)
    for char in ("\\", "`", "*", "_", "{", "}", "[", "]", "<", ">", "#", "|", "!"):
        text = text.replace(char, "\\" + char)
    return text.replace("\r", "").replace("\n", "  \n")


def escape_code(value: object) -> str:
    return sanitize_text(value).replace("`", "'").replace("\r", " ").replace("\n", " ")

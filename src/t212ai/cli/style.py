"""Small terminal rendering helpers for the brokerai CLI."""

from __future__ import annotations

import os
import shutil
import sys
import textwrap


_BANNER_LINES = (
    " _______  ___   ___  _______  _______  ___ ",
    "|       ||   | |   ||       ||   _   ||   |",
    "|_     _||   |_|   ||    ___||  |_|  ||   |",
    "  |   |  |      _  ||   |___ |       ||   |",
    "  |   |  |     |_  ||    ___||       ||   |",
    "  |   |  |    _  | ||   |___ |   _   ||   |",
    "  |___|  |___| |___||_______||__| |__||___|",
)


class Tone:
    TITLE = "title"
    ACCENT = "accent"
    MUTED = "muted"
    WARNING = "warning"


_ANSI = {
    Tone.TITLE: "\033[1;38;5;231m",
    Tone.ACCENT: "\033[38;5;208m",
    Tone.MUTED: "\033[38;5;245m",
    Tone.WARNING: "\033[38;5;203m",
}
_RESET = "\033[0m"


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR_FORCE"):
        return True
    stream = getattr(sys, "stdout", None)
    return bool(getattr(stream, "isatty", lambda: False)())


def paint(text: str, tone: str) -> str:
    if not _supports_color():
        return text
    return f"{_ANSI.get(tone, '')}{text}{_RESET}"


def render_banner(label: str = "T212AI") -> str:
    if label.strip().upper() != "T212AI":
        return paint(label, Tone.TITLE)
    return "\n".join(paint(line, Tone.TITLE) for line in _BANNER_LINES)


def render_box(text: str, *, title: str | None = None, width: int | None = None) -> str:
    terminal_width = shutil.get_terminal_size((88, 24)).columns
    box_width = max(44, min(width or terminal_width - 2, 96))
    inner_width = box_width - 4
    lines: list[str] = []
    if title:
        heading = f"[ {title} ]"
        lines.append("+" + heading + "-" * max(0, box_width - len(heading) - 2) + "+")
    else:
        lines.append("+" + "-" * (box_width - 2) + "+")
    for paragraph in str(text).splitlines() or [""]:
        if not paragraph:
            lines.append("| " + " " * inner_width + " |")
            continue
        for wrapped in textwrap.wrap(paragraph, width=inner_width) or [""]:
            lines.append(f"| {wrapped:<{inner_width}} |")
    lines.append("+" + "-" * (box_width - 2) + "+")
    return "\n".join(lines)


def render_step_intro(title: str, description: str) -> str:
    heading = paint(f"> {title}", Tone.ACCENT)
    return f"{heading}\n{render_box(description, title=title)}"

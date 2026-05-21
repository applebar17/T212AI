"""Terminal IO helpers for the interactive CLI."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, TextIO


@dataclass(slots=True)
class TerminalIO:
    input_fn: Callable[[str], str] = input
    output: TextIO | None = None

    def __post_init__(self) -> None:
        if self.output is None:
            self.output = sys.stdout

    def write(self, text: str = "") -> None:
        print(text, file=self.output)

    def prompt(self, label: str, *, default: str | None = None) -> str:
        suffix = f" [{default}]" if default not in {None, ""} else ""
        value = self.input_fn(f"{label}{suffix}: ").strip()
        if value:
            return value
        return default or ""

    def confirm(self, label: str, *, default: bool = True) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            raw = self.input_fn(f"{label} [{suffix}]: ").strip().lower()
            if not raw:
                return default
            if raw in {"y", "yes"}:
                return True
            if raw in {"n", "no"}:
                return False
            self.write("Please answer yes or no.")

    def choose(
        self,
        label: str,
        *,
        options: tuple[tuple[str, str], ...],
        default: str,
    ) -> str:
        self.write(label)
        index_by_value = {value: idx for idx, (value, _) in enumerate(options, start=1)}
        for index, (value, description) in enumerate(options, start=1):
            marker = " (default)" if value == default else ""
            self.write(f"  {index}. {description}{marker}")
        default_index = index_by_value.get(default, 1)
        while True:
            raw = self.prompt("Select option", default=str(default_index)).strip().lower()
            if raw.isdigit():
                selected_index = int(raw)
                if 1 <= selected_index <= len(options):
                    return options[selected_index - 1][0]
            for value, description in options:
                if raw in {value.lower(), description.lower()}:
                    return value
            self.write("Please choose one of the listed options.")

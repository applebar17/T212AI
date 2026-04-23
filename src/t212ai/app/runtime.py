from __future__ import annotations

from dataclasses import dataclass

from .config import AppSettings, get_app_settings


@dataclass(slots=True)
class AppRuntime:
    settings: AppSettings


def build_runtime() -> AppRuntime:
    return AppRuntime(settings=get_app_settings())


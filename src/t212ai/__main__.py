from __future__ import annotations

from .app.config import get_app_settings


def main() -> None:
    settings = get_app_settings()
    print(f"T212AI baseline runtime. trading212_environment={settings.trading212_environment}")


if __name__ == "__main__":
    main()


from __future__ import annotations

from t212ai.telegram import TelegramBotService


def main() -> None:
    TelegramBotService.from_settings().run_polling()


if __name__ == "__main__":
    main()

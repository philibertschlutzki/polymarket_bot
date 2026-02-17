import json
import logging
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Dict


class TelegramErrorLogHandler(logging.Handler):
    def __init__(self, bot_token: str, chat_id: str):
        super().__init__()
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.setLevel(logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = self.format(record)
            threading.Thread(target=self._send_to_telegram, args=(log_entry,)).start()
        except Exception:
            self.handleError(record)

    def _send_to_telegram(self, message: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": f"🚨 *CRITICAL ERROR* 🚨\n\n`{message}`", "parse_mode": "Markdown"}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            # Prevent recursive logging if Telegram fails
            pass


def setup_logging(config: Dict[str, Any]) -> None:
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logging.basicConfig(
        level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", handlers=[logging.StreamHandler()]
    )

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if bot_token and chat_id:
        telegram_handler = TelegramErrorLogHandler(bot_token, chat_id)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(message)s")
        telegram_handler.setFormatter(formatter)
        logging.getLogger().addHandler(telegram_handler)
        logging.info("Telegram Error Logging Enabled.")
    else:
        logging.warning("Telegram credentials not found. Error logging disabled.")

import asyncio
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.session: aiohttp.ClientSession | None = None

        if not self.bot_token or not self.chat_id:
            logger.warning("Telegram credentials not found. Notifications disabled.")
        else:
            try:
                # Attempt to create session if loop exists
                self.session = aiohttp.ClientSession()
            except Exception:
                self.session = None

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def _send(self, text: str) -> None:
        if not self.bot_token or not self.chat_id:
            return

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}

        try:
            async with self.session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to send Telegram message: {error_text}")
                else:
                    logger.debug(f"Telegram message sent: {text[:50]}...")
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")

    def send_message(self, text: str) -> None:
        """
        Send a message to Telegram asynchronously (Fire-and-Forget).
        """
        if not self.bot_token or not self.chat_id:
            return

        # Fire-and-forget task
        asyncio.create_task(self._send(text))

    def send_trade_update(self, action: str, symbol: str, price: float, quantity: float, reason: str = "") -> None:
        """
        Send a formatted trade update.
        """
        text = (
            f"🚨 *Trade Update* 🚨\n\n"
            f"**Action:** {action.upper()}\n"
            f"**Symbol:** `{symbol}`\n"
            f"**Price:** ${price:.4f}\n"
            f"**Quantity:** {quantity}\n"
        )
        if reason:
            text += f"**Reason:** {reason}\n"

        self.send_message(text)

    def send_scanner_update(self, count: int, top_markets: list[str]) -> None:
        """
        Send scanner results.
        """
        markets_list = "\n".join([f"- {m}" for m in top_markets[:5]])
        text = f"🔍 *Scanner Update* 🔍\n\n" f"Found {count} new opportunities.\n" f"**Top Markets:**\n{markets_list}"
        self.send_message(text)

    def send_analysis_update(self, question: str, result: dict[str, Any]) -> None:
        """
        Send analysis result.
        """
        action = result.get("action", "UNKNOWN").upper()
        target = result.get("target_outcome", "UNKNOWN")
        confidence = result.get("confidence", 0.0)
        reasoning = result.get("reasoning", "No reasoning provided.")

        text = (
            f"🧠 *Gemini Analysis* 🧠\n\n"
            f"**Question:** {question}\n"
            f"**Decision:** {action} on {target}\n"
            f"**Confidence:** {confidence:.2f}\n"
            f"**Reasoning:** {reasoning}"
        )
        self.send_message(text)

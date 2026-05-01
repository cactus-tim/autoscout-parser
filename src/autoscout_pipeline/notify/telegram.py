"""Telegram notifier for scored AutoScout24 listings.

Sends HTML-formatted messages via the Bot API when a listing's score
meets or exceeds the configured threshold.  All user-supplied text is
passed through html.escape() before interpolation to prevent accidental
HTML injection in the message body.

Network errors are logged as warnings and silently swallowed so a single
Telegram failure never aborts the pipeline run.
"""

import asyncio
import html
import logging

import httpx

from autoscout_pipeline.models import ScoredListing

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Score-gated notifier that posts listings to a Telegram chat.

    Args:
        token:     Telegram Bot API token (obtained from @BotFather).
        chat_id:   Target chat or channel ID (string or numeric string).
        threshold: Minimum score.score value required to trigger a send.
                   Listings with score strictly below this value are skipped.
        timeout:   httpx request timeout in seconds.
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        threshold: int = 8,
        timeout: float = 10.0,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._threshold = threshold
        self._timeout = timeout

    def _format(self, s: ScoredListing) -> str:
        """Render a ScoredListing as an HTML Telegram message.

        All interpolated values from the listing and score objects are
        html.escape()-d.  The URL is also quote-escaped in the href attribute
        so that characters like '"' and '&' do not break the anchor tag.
        """
        listing = s.listing
        score = s.score
        return (
            f"<b>Score {score.score}/10</b> — "
            f"{html.escape(listing.brand)} {html.escape(listing.model)} {listing.year}\n"
            f'<a href="{html.escape(listing.url, quote=True)}">'
            f"{html.escape(listing.url)}</a>\n"
            f"{listing.mileage_km} km · €{listing.price_eur} · "
            f"{html.escape(listing.location or '')}\n"
            f"<i>{html.escape(score.reasoning)}</i>"
        )

    async def send(self, scored: ScoredListing) -> bool:
        """Send a single listing to Telegram if it meets the score threshold.

        Returns:
            True  — message was sent successfully.
            False — score below threshold (silent skip) or network error
                    (warning logged, error swallowed).
        """
        if scored.score.score < self._threshold:
            return False

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": self._format(scored),
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("telegram send failed: %s", exc)
            return False

    async def send_batch(self, scored_list: list[ScoredListing]) -> int:
        """Send all listings that pass the threshold, one after another.

        A 0.5-second delay is inserted *between* consecutive sends to
        respect Telegram's per-chat rate limit (1 message/second).
        The delay is added before each send except the first, so N sends
        produce exactly N-1 sleeps.

        Returns:
            Number of messages successfully sent.
        """
        sent = 0
        for s in scored_list:
            if sent > 0:
                await asyncio.sleep(0.5)
            if await self.send(s):
                sent += 1
        return sent

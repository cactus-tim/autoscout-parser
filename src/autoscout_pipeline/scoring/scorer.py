"""LLM-backed listing scorer using instructor + AsyncOpenAI.

Mode.TOOLS is the only verified-working mode for gpt-4.1-nano.
The following modes are FORBIDDEN and return "Unsupported model":
    - Mode.TOOLS_STRICT
    - Mode.JSON_SCHEMA
    - Mode.RESPONSES_TOOLS
    - Mode.RESPONSES_TOOLS_WITH_INBUILT_TOOLS
"""

import logging
from pathlib import Path

import instructor
from instructor import Mode
from openai import AsyncOpenAI

from autoscout_pipeline.models import Listing, ListingScore
from autoscout_pipeline.scoring.prompt import build_system_prompt, load_brief, render_listing

logger = logging.getLogger(__name__)


class LLMScorer:
    """Score a single Listing by calling an OpenAI chat completion via instructor."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4.1-nano",
        brief_path: Path = Path("brief.md"),
    ) -> None:
        self._client = instructor.from_openai(
            AsyncOpenAI(api_key=api_key),
            mode=Mode.TOOLS,
        )
        # Exposed for test pinning — never change to a different mode.
        self._mode = Mode.TOOLS
        self._model = model
        self._brief_path = brief_path

    async def score(self, listing: Listing) -> ListingScore:
        """Return a ListingScore for *listing*, or a sentinel score=1 on failure."""
        system = build_system_prompt(load_brief(self._brief_path))
        user = render_listing(listing)
        try:
            return await self._client.chat.completions.create(
                model=self._model,
                response_model=ListingScore,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=600,
            )
        except Exception as e:
            logger.warning("scoring failed for %s: %s", listing.listing_id, e)
            return ListingScore(
                score=1,
                reasoning=f"LLM scoring failed: {e}",
                pros=[],
                cons=[],
            )

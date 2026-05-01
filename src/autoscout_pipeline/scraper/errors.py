"""Custom exceptions for the AutoScout24 scraper module."""


class NextDataMissingError(Exception):
    """Raised when the __NEXT_DATA__ script tag is absent from the fetched HTML.

    AutoScout24 uses Next.js SSR; the ``<script id="__NEXT_DATA__">`` tag must
    be present after hydration. When it is missing it usually means:
    - Akamai served a bot-challenge page instead of the real content.
    - The page hydration did not complete (networkidle fired too early).
    - The site changed its Next.js rendering strategy.

    The raw HTML is saved to a /tmp dump path (included in the exception message)
    for offline debugging.
    """


class EmptyResultsError(Exception):
    """Raised when the first search results page returns an empty listing array.

    Possible causes:
    - The URL bucket codes for ``kmfrom``/``kmto``/``priceto`` are wrong.
    - Akamai returned a CAPTCHA or empty page silently.
    - No listings match the criteria on autoscout24.com at this time.
    """

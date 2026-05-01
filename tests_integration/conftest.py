"""Integration test configuration for live Google Sheets tests.

All tests in this directory are skipped unless:
  - INTEGRATION_TESTS=1 is set in the environment
  - INTEGRATION_SHEET_ID is set to a real spreadsheet ID
  - creds.json is present in the working directory (service-account credentials)

Run with:
    INTEGRATION_TESTS=1 INTEGRATION_SHEET_ID=<id> uv run pytest tests_integration/ -v
"""

import os
from pathlib import Path

import pytest

from autoscout_pipeline.sheets.client import SheetsClient
from autoscout_pipeline.sheets.schema import LISTINGS_TAB, PRICE_HISTORY_TAB, RUNS_TAB

pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRATION_TESTS") != "1" or not os.environ.get("INTEGRATION_SHEET_ID"),
    reason=(
        "Live integration tests skipped: set INTEGRATION_TESTS=1 + INTEGRATION_SHEET_ID"
        " + creds.json to run"
    ),
)

_EXPECTED_TABS = [LISTINGS_TAB, PRICE_HISTORY_TAB, RUNS_TAB]


def _delete_tab_if_exists(spreadsheet, title: str) -> None:
    """Delete a worksheet by title if it exists; silently skip if not found."""
    try:
        ws = spreadsheet.worksheet(title)
        spreadsheet.del_worksheet(ws)
    except Exception:
        pass


@pytest.fixture(scope="session")
def live_client():
    """Session-scoped SheetsClient connected to the real integration spreadsheet.

    Pre-clean: deletes the three expected tabs (listings, price_history, runs)
    if they exist so each session starts from a blank slate.

    Post-clean (teardown): deletes those same tabs, leaving the spreadsheet
    itself intact.  Teardown runs even if tests fail.

    Skips immediately if the required environment variables are not set,
    which mirrors the module-level pytestmark skip condition.
    """
    if os.environ.get("INTEGRATION_TESTS") != "1" or not os.environ.get("INTEGRATION_SHEET_ID"):
        pytest.skip(
            "Live integration tests skipped: set INTEGRATION_TESTS=1 + INTEGRATION_SHEET_ID"
            " + creds.json to run"
        )

    sheet_id = os.environ["INTEGRATION_SHEET_ID"]
    creds_path = Path("creds.json")

    client = SheetsClient(creds_path=creds_path, sheet_id=sheet_id)
    spreadsheet = client._spreadsheet

    # --- Pre-clean: start each session with no leftover tabs ---
    for tab in _EXPECTED_TABS:
        _delete_tab_if_exists(spreadsheet, tab)

    yield client

    # --- Post-clean: remove test tabs after session finishes ---
    for tab in _EXPECTED_TABS:
        _delete_tab_if_exists(spreadsheet, tab)

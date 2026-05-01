"""Shared pytest fixtures for the autoscout_pipeline test suite."""

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Treat 'no tests collected' (exit code 5) as success.

    This allows ``uv run pytest -q`` to exit 0 before any test modules are
    written (Phase 1 bootstrap).  Once real tests exist the hook is a no-op.
    """
    if exitstatus == 5:
        session.exitstatus = 0

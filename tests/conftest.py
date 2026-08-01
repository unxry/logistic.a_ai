"""Shared pytest guardrails for mutable UI globals."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.ui.theme import tokens


@pytest.fixture(autouse=True)
def _restore_design_tokens() -> Iterator[None]:
    """Keep Light tokens as the baseline between tests.

    Stage 10.4 adds live theme switching; tokens are intentionally mutable at
    runtime, so tests that flip Light/Dark must not leak global theme state into
    unrelated design-system assertions.
    """
    tokens.apply_theme("light")
    yield
    tokens.apply_theme("light")

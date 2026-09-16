"""Configurable location for external research artifacts."""

import os
from pathlib import Path


def results_root() -> Path:
    """Use BARNETTE_RESULTS_ROOT, or the local ignored results directory."""
    return Path(os.environ.get("BARNETTE_RESULTS_ROOT") or "results").expanduser()

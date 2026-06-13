import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
import categorize.main as main_module


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset module-level cache and stop event before/after every test."""
    main_module._cached_rules = []
    main_module._cached_aliases = []
    main_module._cache_expires_at = 0.0
    main_module._stop.clear()
    yield
    main_module._stop.clear()

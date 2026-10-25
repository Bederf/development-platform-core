"""Human-run smoke check for the dormant Humanizer scaffold."""

from pathlib import Path

import pytest

from humanizer_scaffold import HumanizerDisabled, require_enabled


def test_scaffold_is_disabled_by_default():
    with pytest.raises(HumanizerDisabled):
        require_enabled(Path(__file__).parents[1])

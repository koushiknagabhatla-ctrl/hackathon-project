"""Runtime data-integrity configuration.

One gate, one place. Every caller that could put non-observed data in front of
a user routes through here.

The rule this file exists to enforce:

    The system never presents fabricated, simulated, placeholder or stale
    information as real-world information. If verified data cannot be
    obtained, it says so. It never fills the gap.
"""

from __future__ import annotations

import os


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


# Default FALSE. Simulated world data only loads when this is explicitly on,
# and when it is on the UI labels the whole environment as SIMULATION.
MOCK_MODE: bool = _flag("MOCK_MODE", "false")

# Contacting a human being is irreversible. Even with MOCK_MODE on, outbound
# notification stays off unless separately and deliberately enabled.
ALLOW_OUTBOUND_NOTIFICATIONS: bool = _flag("ALLOW_OUTBOUND_NOTIFICATIONS", "false")


class FabricationError(RuntimeError):
    """Raised when code attempts to persist invented data on the real path.

    This is deliberately an exception and not a warning. A silent fallback from
    real data to fake data is the exact failure this system must not have.
    """


def require_mock_mode(what: str) -> None:
    """Guard the entry to any simulated-data path."""
    if not MOCK_MODE:
        raise FabricationError(
            f"refusing to load simulated data ({what}) while MOCK_MODE is off. "
            "Set MOCK_MODE=true to run a clearly-labelled demonstration "
            "environment, or configure a real source."
        )


def environment_banner() -> dict[str, object]:
    """What the UI renders so a viewer always knows which world they are in."""
    return {
        "mock_mode": MOCK_MODE,
        "label": "SIMULATION — DEMONSTRATION DATA" if MOCK_MODE else "LIVE",
        "outbound_notifications_enabled": ALLOW_OUTBOUND_NOTIFICATIONS,
        "notice": (
            "All world data in this environment is fabricated for demonstration "
            "and must not be treated as observation."
            if MOCK_MODE
            else "Only verified data from configured sources is shown. Gaps are "
            "reported as unavailable rather than filled."
        ),
    }

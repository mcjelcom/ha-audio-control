"""Data models for serial/network audio devices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ZoneState:
    """Parsed state of a single zone."""

    power: bool = False
    # Whether `power` has been reported by the device (or set by a command). It
    # starts False because the default `power=False` is a placeholder, not a
    # reading: checks that refuse an action on an OFF zone must not fire before
    # the first status poll has told us the zone is really off.
    power_known: bool = False
    source: int = 1
    volume: int = 0
    mute: bool = False
    bass: int = 0
    treble: int = 0
    balance: int = 0
    group: bool = False

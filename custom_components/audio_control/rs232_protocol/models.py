"""Data models for serial/network audio devices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ZoneState:
    """Parsed state of a single zone."""

    power: bool = False
    source: int = 1
    volume: int = 0
    mute: bool = False
    bass: int = 0
    treble: int = 0
    balance: int = 0
    group: bool = False

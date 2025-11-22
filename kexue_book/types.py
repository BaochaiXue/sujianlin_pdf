from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Post:
    """Metadata for a Scientific Spaces article."""

    title: str
    url: str
    date: date

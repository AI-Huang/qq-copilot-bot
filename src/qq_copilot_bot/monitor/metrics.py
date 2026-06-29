#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Metric data structures shared by every message-count dashboard renderer.

The collector produces a :class:`Snapshot` (raw counts at a point in time) and
derives a :class:`Stats` (totals + rates + breakdowns). ``Stats.to_dict()`` is
the single serialization contract consumed by both the TUI and web dashboards,
and by the web JSON API.
"""

from dataclasses import asdict, dataclass, field
from typing import Dict


@dataclass
class Snapshot:
    """Raw counts sampled from chat_messages at one instant."""

    ts: float  # epoch seconds
    total: int
    total_user: int       # role = 'user'
    total_assistant: int  # role = 'assistant'
    total_private: int    # message_type = 'private'
    total_group: int      # message_type = 'group'
    # top session_id -> count (e.g. "group:12345" -> 400)
    per_session: Dict[str, int] = field(default_factory=dict)


@dataclass
class Stats:
    """Derived metrics ready for rendering. Serializable via :meth:`to_dict`."""

    ts: float
    total: int
    delta: int          # rows added since the previous snapshot
    interval_s: float   # seconds between the last two snapshots
    elapsed_s: float    # seconds since the collector started
    started_total: int  # row count when the collector started

    rate_instant: float   # messages/min over the last interval
    rate_avg: float       # messages/min over the rolling window
    rate_ema: float       # exponentially smoothed messages/min

    rate_instant_s: float  # messages/sec over the last interval
    rate_avg_s: float      # messages/sec over the rolling window
    rate_ema_s: float      # exponentially smoothed messages/sec

    total_user: int
    total_assistant: int
    total_private: int
    total_group: int

    per_session: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

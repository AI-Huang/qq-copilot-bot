#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Renderer-agnostic message-count collector (the dashboard base).

Polls the MySQL ``chat_messages`` table on demand, keeps a bounded rolling
history of snapshots, and derives speed metrics. Both the terminal and web
dashboards build on this single class so the statistics logic lives in exactly
one place.

Typical use (a renderer owns the cadence, e.g. every 5 s)::

    from qq_copilot_bot.monitor import MessageStatsCollector

    collector = MessageStatsCollector()
    while True:
        collector.poll()
        stats = collector.stats()
        render(stats.to_dict())
        time.sleep(5)
"""

import time
from collections import deque

from sqlalchemy import create_engine, text

from settings import mysql_settings

from .metrics import Snapshot, Stats


class MessageStatsCollector:
    """Sample the ``chat_messages`` table and compute message-rate statistics.

    Args:
        window: number of recent snapshots used for the rolling average rate.
            With a 5 s cadence, ``window=12`` averages over ~1 minute.
        ema_alpha: smoothing factor (0–1) for the EMA rate; higher reacts faster.
        track_sessions: also collect a per-session breakdown each poll.
    """

    def __init__(
        self,
        *,
        window: int = 12,
        ema_alpha: float = 0.3,
        track_sessions: bool = True,
    ) -> None:
        self._engine = create_engine(mysql_settings.url, pool_pre_ping=True)
        self.history: deque[Snapshot] = deque(maxlen=max(2, window))
        self.ema_alpha = ema_alpha
        self.track_sessions = track_sessions

        self._start_ts: float | None = None
        self._start_total: int | None = None
        self._ema: float | None = None

    # -- sampling -------------------------------------------------------------

    def poll(self) -> Snapshot:
        """Query the DB once and append a fresh snapshot to the history."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) AS total, "
                    "SUM(role = 'user') AS total_user, "
                    "SUM(role = 'assistant') AS total_assistant, "
                    "SUM(message_type = 'private') AS total_private, "
                    "SUM(message_type = 'group') AS total_group "
                    "FROM chat_messages"
                )
            ).fetchone()

            per_session: dict[str, int] = {}
            if self.track_sessions:
                rows = conn.execute(
                    text(
                        "SELECT session_id, COUNT(*) AS n "
                        "FROM chat_messages "
                        "GROUP BY session_id "
                        "ORDER BY n DESC "
                        "LIMIT 20"
                    )
                ).fetchall()
                for r in rows:
                    per_session[r[0]] = int(r[1])

        snapshot = Snapshot(
            ts=time.time(),
            total=int(row[0] or 0),
            total_user=int(row[1] or 0),
            total_assistant=int(row[2] or 0),
            total_private=int(row[3] or 0),
            total_group=int(row[4] or 0),
            per_session=per_session,
        )

        if self._start_ts is None:
            self._start_ts = snapshot.ts
            self._start_total = snapshot.total

        self.history.append(snapshot)
        self._update_ema()
        return snapshot

    def _update_ema(self) -> None:
        if len(self.history) < 2:
            return
        prev, last = self.history[-2], self.history[-1]
        dt = max(1e-9, last.ts - prev.ts)
        instant = (last.total - prev.total) / dt * 60.0
        if self._ema is None:
            self._ema = instant
        else:
            self._ema = self.ema_alpha * instant + (1 - self.ema_alpha) * self._ema

    # -- derivation -----------------------------------------------------------

    def stats(self) -> Stats:
        """Compute derived metrics from the current history. Call poll() first."""
        if not self.history:
            raise RuntimeError("call poll() before stats()")

        last = self.history[-1]
        prev = self.history[-2] if len(self.history) >= 2 else last
        oldest = self.history[0]

        interval_s = max(0.0, last.ts - prev.ts)
        delta = last.total - prev.total
        rate_instant = (delta / interval_s * 60.0) if interval_s > 0 else 0.0

        window_s = max(0.0, last.ts - oldest.ts)
        rate_avg = (
            (last.total - oldest.total) / window_s * 60.0 if window_s > 0 else 0.0
        )

        elapsed_s = max(0.0, last.ts - (self._start_ts or last.ts))

        return Stats(
            ts=last.ts,
            total=last.total,
            delta=delta,
            interval_s=interval_s,
            elapsed_s=elapsed_s,
            started_total=self._start_total or 0,
            rate_instant=round(rate_instant, 2),
            rate_avg=round(rate_avg, 2),
            rate_ema=round(self._ema or 0.0, 2),
            rate_instant_s=round(rate_instant / 60.0, 4),
            rate_avg_s=round(rate_avg / 60.0, 4),
            rate_ema_s=round((self._ema or 0.0) / 60.0, 4),
            total_user=last.total_user,
            total_assistant=last.total_assistant,
            total_private=last.total_private,
            total_group=last.total_group,
            per_session=dict(last.per_session),
        )

    # -- historical seed ------------------------------------------------------

    def load_message_history(
        self,
        bucket_seconds: int = 60,
    ) -> list[dict]:
        """Reconstruct the message-rate curve from ``chat_messages.created_at``.

        Buckets all stored messages by time and returns a list of
        ``{t, instant, avg, ema, total}`` dicts (oldest first) that can seed
        the web chart so the timeline always reaches back to the first message.
        Returns an empty list if the table is unreadable.
        """
        try:
            from sqlalchemy import text as _text

            sql = _text(
                "SELECT FLOOR(UNIX_TIMESTAMP(created_at) / :bs) * :bs AS t, "
                "COUNT(*) AS n "
                "FROM chat_messages "
                "GROUP BY t "
                "ORDER BY t ASC"
            )
            with self._engine.connect() as conn:
                rows = conn.execute(sql, {"bs": bucket_seconds}).fetchall()

            result: list[dict] = []
            cumulative = 0
            ema: float | None = None
            alpha = 0.3
            for row in rows:
                t = float(row[0])
                n = int(row[1])
                cumulative += n
                instant = n / bucket_seconds * 60.0  # msgs/min
                if ema is None:
                    ema = instant
                else:
                    ema = alpha * instant + (1 - alpha) * ema
                result.append(
                    {
                        "t": t,
                        "instant": round(instant, 2),
                        "avg": round(instant, 2),
                        "ema": round(ema, 2),
                        "total": cumulative,
                    }
                )
            return result
        except Exception:  # history is best-effort
            return []

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        self._engine.dispose()

    def __enter__(self) -> "MessageStatsCollector":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> None:
        self.close()

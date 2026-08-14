"""Counters worth watching in production, in Prometheus text format.

Deliberately few. The ones here answer questions an operator of *this* system
would actually ask, rather than filling a dashboard:

- **Is it abstaining more than it used to?** That is the earliest signal that a
  corpus has gone stale or a filing has changed shape, and it appears long
  before anyone notices a wrong answer.
- **Is the routing mix shifting?** A drop in ledger-routed questions means the
  structured path is reaching fewer of them, which usually means labels are
  missing rather than that users changed the subject.
- **How long does each route take?** They differ by orders of magnitude, so one
  pooled latency figure would hide both.

No dependency: the exposition format is a few lines of text, and pulling in a
client library to emit it would be more code than writing it.
"""

from __future__ import annotations

import threading
from collections import Counter


class Metrics:
    """Process-local counters. Reset when the process restarts, as they should."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.answers: Counter[str] = Counter()
        self.routes: Counter[str] = Counter()
        self.latency_sum: Counter[str] = Counter()
        self.latency_count: Counter[str] = Counter()
        self.replays: Counter[str] = Counter()

    def record_answer(self, route: str, status: str, latency_ms: float) -> None:
        with self._lock:
            self.answers[status] += 1
            self.routes[route] += 1
            # Sum and count rather than a histogram: with two routes and a
            # single process, an average per route plus the p95 already reported
            # on each response is enough, and a histogram would be furniture.
            self.latency_sum[route] += int(latency_ms * 1000)
            self.latency_count[route] += 1

    def record_replay(self, outcome: str) -> None:
        with self._lock:
            self.replays[outcome] += 1

    def render(self, documents: int, snapshot_id: str) -> str:
        """Prometheus text exposition."""
        lines: list[str] = [
            "# HELP disclosure_rag_documents Documents currently indexed.",
            "# TYPE disclosure_rag_documents gauge",
            f"disclosure_rag_documents {documents}",
            "# HELP disclosure_rag_corpus_info The corpus snapshot answers are produced against.",
            "# TYPE disclosure_rag_corpus_info gauge",
            f'disclosure_rag_corpus_info{{snapshot_id="{snapshot_id}"}} 1',
            "# HELP disclosure_rag_answers_total Answers by status.",
            "# TYPE disclosure_rag_answers_total counter",
        ]
        with self._lock:
            for status, count in sorted(self.answers.items()):
                lines.append(f'disclosure_rag_answers_total{{status="{status}"}} {count}')
            lines += [
                "# HELP disclosure_rag_route_total Answers by route.",
                "# TYPE disclosure_rag_route_total counter",
            ]
            for route, count in sorted(self.routes.items()):
                lines.append(f'disclosure_rag_route_total{{route="{route}"}} {count}')
            lines += [
                "# HELP disclosure_rag_latency_microseconds_sum Answer latency by route.",
                "# TYPE disclosure_rag_latency_microseconds_sum counter",
            ]
            for route, total in sorted(self.latency_sum.items()):
                lines.append(f'disclosure_rag_latency_microseconds_sum{{route="{route}"}} {total}')
            for route, count in sorted(self.latency_count.items()):
                lines.append(f'disclosure_rag_latency_count{{route="{route}"}} {count}')
            if self.replays:
                lines += [
                    "# HELP disclosure_rag_replays_total Audit replays by outcome.",
                    "# TYPE disclosure_rag_replays_total counter",
                ]
                for outcome, count in sorted(self.replays.items()):
                    lines.append(f'disclosure_rag_replays_total{{outcome="{outcome}"}} {count}')
        return "\n".join(lines) + "\n"

"""gary status-report — prints the 5 pilot rubric metrics.

Run ad-hoc or wire into the evening template. Adopts the rubric verbatim from
the Perplexity stress-test brief (2026-05-23):

  1. TTL hit rate
  2. State-transition compliance
  3. Blocked decay rate (items in blocked >48h)
  4. Snooze attempts
  5. Time-to-resolution after escalation
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import parse as urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402


WINDOW_DAYS = 7  # pilot window
LOOP_TAG = "loop"


def _all_loop_items() -> list[dict]:
    return json.loads(db._req(f"/gary_todos?tag=eq.{LOOP_TAG}&select=*&limit=1000"))


def report() -> dict:
    items = _all_loop_items()
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(days=WINDOW_DAYS)

    # Metric 1: TTL hit rate — items with due_at in window, were they escalated?
    # We approximate "escalated" by status in (blocked, killed, shipped) after due_at
    due_in_window = [
        r for r in items
        if r.get("due_at")
        and datetime.fromisoformat(r["due_at"].replace("Z","+00:00")) >= window_start
        and datetime.fromisoformat(r["due_at"].replace("Z","+00:00")) <= now_utc
    ]
    escalated = [r for r in due_in_window if r.get("status") in ("blocked", "killed", "shipped")]
    ttl_hit = (len(escalated) / len(due_in_window) * 100) if due_in_window else None

    # Metric 2: state-transition compliance — items that hit a terminal state
    # via the start→ship/block/kill path (we proxy: terminal-status items have
    # last_update suggesting a transition note).
    terminal = [r for r in items if r.get("status") in ("shipped", "killed", "blocked", "cancelled")]
    compliant = [r for r in terminal if r.get("last_update")]
    compliance = (len(compliant) / len(terminal) * 100) if terminal else None

    # Metric 3: blocked decay — items in blocked >48h
    blocked_48h = 0
    for r in items:
        if r.get("status") == "blocked" and r.get("blocked_at"):
            ba = datetime.fromisoformat(r["blocked_at"].replace("Z","+00:00"))
            if (now_utc - ba) > timedelta(hours=48):
                blocked_48h += 1

    # Metric 4: snooze attempts — items with snooze_count > 0
    snoozed_once = sum(1 for r in items if (r.get("snooze_count") or 0) >= 1)
    snoozed_twice = sum(1 for r in items if (r.get("snooze_count") or 0) >= 2)

    # Metric 5: time-to-resolution after escalation
    # Items that went blocked → terminal: compute median time
    # Without a full audit-log join we approximate using updated_at - blocked_at
    # for items currently terminal that have a blocked_at.
    resolution_hours = []
    for r in items:
        if r.get("status") in ("shipped", "killed") and r.get("blocked_at") and r.get("updated_at"):
            ba = datetime.fromisoformat(r["blocked_at"].replace("Z","+00:00"))
            ua = datetime.fromisoformat(r["updated_at"].replace("Z","+00:00"))
            resolution_hours.append((ua - ba).total_seconds() / 3600)
    if resolution_hours:
        resolution_hours.sort()
        median_h = resolution_hours[len(resolution_hours)//2]
    else:
        median_h = None

    return {
        "ttl_hit_rate_pct": ttl_hit,
        "state_compliance_pct": compliance,
        "blocked_decay_count": blocked_48h,
        "snooze_attempts": {"once": snoozed_once, "twice_or_more": snoozed_twice},
        "median_resolution_hours": median_h,
        "total_loop_items": len(items),
        "by_status": {
            s: sum(1 for r in items if r.get("status") == s)
            for s in ("open", "in_progress", "blocked", "shipped", "killed", "cancelled")
        },
        "window_days": WINDOW_DAYS,
    }


def format_report(r: dict) -> str:
    def pct(v, t=None):
        if v is None:
            return "n/a"
        return f"{v:.0f}%" + (f" ({t})" if t else "")

    pass_fail = {
        "ttl": "✓ pass" if (r["ttl_hit_rate_pct"] or 0) >= 80 else (
            "✗ fail" if (r["ttl_hit_rate_pct"] or 100) < 50 else "↻ watch"
        ),
        "compliance": "✓ pass" if (r["state_compliance_pct"] or 0) >= 90 else (
            "✗ fail" if (r["state_compliance_pct"] or 100) < 70 else "↻ watch"
        ),
        "decay": "✓ pass" if r["blocked_decay_count"] == 0 else (
            "✗ fail" if r["blocked_decay_count"] > 2 else "↻ watch"
        ),
        "snooze": "✓ pass" if r["snooze_attempts"]["twice_or_more"] == 0 else "✗ fail",
        "resolution": "✓ pass" if (r["median_resolution_hours"] or 99) < 4 else (
            "✗ fail" if (r["median_resolution_hours"] or 0) > 24 else "↻ watch"
        ),
    }

    mr = r["median_resolution_hours"]
    mr_str = f"{mr:.1f}h" if mr is not None else "n/a"
    once = r["snooze_attempts"]["once"]
    twice = r["snooze_attempts"]["twice_or_more"]
    return "\n".join([
        "📊 LOOP PILOT — status report",
        f"({r['window_days']}-day window, {r['total_loop_items']} #loop items)",
        "",
        f"1. TTL hit rate:           {pct(r['ttl_hit_rate_pct'])}    {pass_fail['ttl']}",
        f"2. State compliance:       {pct(r['state_compliance_pct'])}    {pass_fail['compliance']}",
        f"3. Blocked decay (>48h):   {r['blocked_decay_count']} item(s)    {pass_fail['decay']}",
        f"4. Snooze attempts:        once={once}, 2x+={twice}    {pass_fail['snooze']}",
        f"5. Median resolution:      {mr_str}    {pass_fail['resolution']}",
        "",
        "Status counts: " + ", ".join(f"{s}={n}" for s, n in r["by_status"].items() if n),
    ])


if __name__ == "__main__":
    out_json = "--json" in sys.argv
    r = report()
    if out_json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(format_report(r))

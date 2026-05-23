"""Workloft Loop board — single source of truth for Loop status formatting.

Used by:
  - STATE.md mirror (block between <!-- LOOP:BEGIN --> markers)
  - 08:00 BST morning cron (Telegram morning template)
  - 22:00 BST evening cron (Telegram evening template)
  - SessionStart hook (additional context for new Bob sessions)
  - TTL escalator cron (identifies stale items needing ASK)

Loop items live in gary_todos with tag='loop'. Stages: research / ship / publish.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import parse as urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

BST = timezone(timedelta(hours=1))
LOOP_TAG = "loop"
STALE_GRACE_HOURS = 0  # an item is escalated as soon as due_at passes


# ---------------------------------------------------------------------------
# Queries

def fetch_loop_items(status: str = "open") -> list[dict]:
    """All Loop items at the given status, ordered by stage then due_at."""
    q = [
        "select=*",
        f"status=eq.{status}",
        f"tag=eq.{LOOP_TAG}",
        "order=due_at.asc.nullslast,created_at.asc",
    ]
    rows = json.loads(db._req("/gary_todos?" + "&".join(q)))
    return rows


def fetch_shipped_today() -> list[dict]:
    """Items marked shipped (or done) between 00:00 BST today and now."""
    now_bst = datetime.now(BST)
    start_bst = now_bst.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_bst.astimezone(timezone.utc).isoformat()
    q = [
        "select=*",
        f"tag=eq.{LOOP_TAG}",
        f"completed_at=gte.{urlparse.quote(start_utc)}",
        "order=completed_at.desc",
    ]
    rows = json.loads(db._req("/gary_todos?" + "&".join(q)))
    return [r for r in rows if r.get("status") in ("shipped", "done")]


def fetch_killed_today() -> list[dict]:
    """Items killed (status=killed) since 00:00 BST today."""
    now_bst = datetime.now(BST)
    start_bst = now_bst.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_bst.astimezone(timezone.utc).isoformat()
    q = [
        "select=*",
        f"tag=eq.{LOOP_TAG}",
        "status=eq.killed",
        f"updated_at=gte.{urlparse.quote(start_utc)}",
        "order=updated_at.desc",
    ]
    return json.loads(db._req("/gary_todos?" + "&".join(q)))


def fetch_overdue() -> list[dict]:
    """Open Loop items whose due_at has passed."""
    now_utc = datetime.now(timezone.utc).isoformat()
    q = [
        "select=*",
        f"tag=eq.{LOOP_TAG}",
        "status=in.(open,in_progress)",
        f"due_at=lt.{urlparse.quote(now_utc)}",
        "order=due_at.asc",
    ]
    return json.loads(db._req("/gary_todos?" + "&".join(q)))


def fetch_blocked() -> list[dict]:
    """Open ASKs — items waiting on Alfred."""
    q = [
        "select=*",
        f"tag=eq.{LOOP_TAG}",
        "status=eq.blocked",
        "order=updated_at.asc",
    ]
    return json.loads(db._req("/gary_todos?" + "&".join(q)))


# ---------------------------------------------------------------------------
# Formatting helpers

def _short(uuid_str: str) -> str:
    return uuid_str[:8] if uuid_str else "?"


def _fmt_due(iso: str | None) -> str:
    if not iso:
        return "no due"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BST)
    now_bst = datetime.now(BST)
    if dt < now_bst:
        delta = now_bst - dt
        if delta.total_seconds() < 3600:
            return f"OVERDUE {int(delta.total_seconds()/60)}m"
        if delta.days == 0:
            return f"OVERDUE {int(delta.total_seconds()/3600)}h"
        return f"OVERDUE {delta.days}d"
    if dt.date() == now_bst.date():
        return f"today {dt.strftime('%H:%M')}"
    if dt.date() == (now_bst + timedelta(days=1)).date():
        return f"tomorrow {dt.strftime('%H:%M')}"
    return dt.strftime("%a %d %b")


def _stage_emoji(stage: str | None) -> str:
    return {"research": "🔬", "ship": "🛠", "publish": "📣"}.get(stage or "", "·")


def _line(r: dict) -> str:
    stage = (r.get("stage") or "").ljust(8)
    return (
        f"  {_stage_emoji(r.get('stage'))} `{_short(r['id'])}` "
        f"[{stage}] {r.get('title','')} — {_fmt_due(r.get('due_at'))}"
    )


# ---------------------------------------------------------------------------
# Public templates

def board_markdown() -> str:
    """Compact Loop board for STATE.md + session-start context."""
    items = fetch_loop_items("open") + fetch_loop_items("in_progress")
    blocked = fetch_blocked()
    overdue = fetch_overdue()

    by_stage = {"research": [], "ship": [], "publish": []}
    for r in items:
        by_stage.setdefault(r.get("stage") or "research", []).append(r)

    now = datetime.now(BST).strftime("%a %d %b %H:%M %Z")
    out = [f"## Workloft Loop board — refreshed {now}", ""]

    for stage in ("research", "ship", "publish"):
        rows = by_stage.get(stage, [])
        emoji = _stage_emoji(stage)
        out.append(f"### {emoji} {stage.title()} ({len(rows)})")
        if rows:
            for r in rows:
                out.append(_line(r))
        else:
            out.append("  _(empty)_")
        out.append("")

    if overdue:
        out.append(f"### 🚨 Overdue — Bob escalates ({len(overdue)})")
        for r in overdue:
            out.append(_line(r))
        out.append("")

    if blocked:
        out.append(f"### ⏸ Blocked — Alfred owes a call ({len(blocked)})")
        for r in blocked:
            out.append(_line(r))
            if r.get("default_action"):
                out.append(f"      default: {r['default_action']}")
        out.append("")

    return "\n".join(out)


def morning_template() -> str:
    """08:00 BST template — what Bob is shipping, what Alfred owes."""
    items = fetch_loop_items("open") + fetch_loop_items("in_progress")
    blocked = fetch_blocked()
    overdue = fetch_overdue()

    now_bst = datetime.now(BST)
    today_end = now_bst.replace(hour=23, minute=59, second=59)

    shipping_today = [
        r for r in items
        if r.get("due_at")
        and datetime.fromisoformat(r["due_at"].replace("Z","+00:00")) <= today_end.astimezone(timezone.utc)
        and r.get("owner") == "bob"
    ]

    by_stage = {"research": 0, "ship": 0, "publish": 0}
    for r in items:
        by_stage[r.get("stage") or "research"] = by_stage.get(r.get("stage") or "research", 0) + 1

    out = [f"🌅 WORKLOFT LOOP — morning ({now_bst.strftime('%a %d %b')})", ""]

    out.append("SHIPPING TODAY (Bob owns)")
    if shipping_today:
        for r in shipping_today:
            out.append(f"  {_stage_emoji(r.get('stage'))} {r.get('title','')} — due {_fmt_due(r.get('due_at'))}")
    else:
        out.append("  _(nothing committed)_")
    out.append("")

    out.append("DECISIONS YOU OWE (blocking Bob)")
    if blocked:
        for r in blocked:
            out.append(f"  ⏸ {r.get('title','')}")
            if r.get("default_action"):
                out.append(f"     default if no reply by 22:00: {r['default_action']}")
    else:
        out.append("  _(none)_")
    out.append("")

    if overdue:
        out.append(f"STALE ({len(overdue)} past due — Bob will escalate today)")
        for r in overdue[:5]:
            out.append(f"  {r.get('title','')} — {_fmt_due(r.get('due_at'))}")
        out.append("")

    out.append(
        f"LOOP STATUS  🔬 Research: {by_stage['research']}  "
        f"🛠 Ship: {by_stage['ship']}  📣 Publish: {by_stage['publish']}"
    )
    return "\n".join(out)


def _status_report_block() -> str:
    """Pilot rubric metrics appended to the evening template."""
    try:
        import status_report as sr
        return "\n" + sr.format_report(sr.report())
    except Exception as e:
        return f"\n(status report unavailable: {e})"


def evening_template() -> str:
    """22:00 BST template — what shipped, what slipped, queued for tomorrow."""
    now_bst = datetime.now(BST)
    today_end = now_bst.replace(hour=23, minute=59, second=59)
    tomorrow_end = today_end + timedelta(days=1)

    shipped = fetch_shipped_today()
    killed = fetch_killed_today()
    blocked = fetch_blocked()
    items_open = fetch_loop_items("open") + fetch_loop_items("in_progress")

    slipped = [
        r for r in items_open
        if r.get("due_at")
        and datetime.fromisoformat(r["due_at"].replace("Z","+00:00")) <= today_end.astimezone(timezone.utc)
    ]
    queued_tomorrow = [
        r for r in items_open
        if r.get("due_at")
        and today_end.astimezone(timezone.utc).isoformat() < r["due_at"]
        and datetime.fromisoformat(r["due_at"].replace("Z","+00:00")) <= tomorrow_end.astimezone(timezone.utc)
    ]

    out = [f"🌆 WORKLOFT LOOP — evening ({now_bst.strftime('%a %d %b')})", ""]

    out.append("SHIPPED TODAY")
    if shipped:
        for r in shipped:
            out.append(f"  ✓ {_stage_emoji(r.get('stage'))} {r.get('title','')}")
    else:
        out.append("  _(nothing today)_")
    out.append("")

    out.append("SLIPPED (was due today, not done)")
    if slipped:
        for r in slipped:
            note = r.get("next_step") or r.get("last_update") or "no note"
            out.append(f"  ✗ {r.get('title','')} — {note[:80]}")
    else:
        out.append("  _(clean)_")
    out.append("")

    out.append("QUEUED FOR TOMORROW")
    if queued_tomorrow:
        for r in queued_tomorrow:
            out.append(f"  {_stage_emoji(r.get('stage'))} {r.get('title','')} [{r.get('stage','')}]")
    else:
        out.append("  _(empty)_")
    out.append("")

    if killed:
        out.append(f"ARCHIVED TODAY ({len(killed)})")
        for r in killed:
            out.append(f"  🗑 {r.get('title','')}")
        out.append("")

    if blocked:
        out.append("OPEN DECISIONS OUTSTANDING (no reply received)")
        for r in blocked:
            out.append(f"  ⏸ {r.get('title','')}")
            if r.get("default_action"):
                out.append(f"     default fires at 08:00 tomorrow: {r['default_action']}")
        out.append("")

    out.append(_status_report_block())
    return "\n".join(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "board"
    if cmd == "board":
        print(board_markdown())
    elif cmd == "morning":
        print(morning_template())
    elif cmd == "evening":
        print(evening_template())
    elif cmd == "overdue":
        for r in fetch_overdue():
            print(_line(r))
    else:
        print(f"Unknown command: {cmd}. Use board / morning / evening / overdue", file=sys.stderr)
        sys.exit(2)

"""TTL escalator — runs hourly, finds overdue Loop items, escalates each.

For each overdue Loop item:
  1. Post a Telegram ASK to Alfred with [A] execute / [B] kill / [C] extend
  2. Flip the item to status='blocked' so it stops appearing as overdue
     (until Alfred responds and Bob transitions it explicitly)
  3. Write an audit-log entry

Alfred replies in plain Telegram. Bob handles the response in regular sessions.
No webhook callback in v1; the human is in the loop, not the escalator script.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib import request as urlrequest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
import loop_board  # noqa: E402

ALFRED_CHAT_ID = "6129334589"


def _load_token() -> str | None:
    for path in [
        "/home/workloft/.claude/channels/telegram/.env",
        "/home/workloft/larry-tier-routing/.env.tier-keys",
    ]:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except FileNotFoundError:
            continue
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def _send(text: str) -> dict:
    token = _load_token()
    if not token:
        raise RuntimeError("No TELEGRAM_BOT_TOKEN found")
    data = json.dumps({
        "chat_id": ALFRED_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()
    req = urlrequest.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _audit(**kwargs):
    try:
        if "/home/workloft/audit" not in sys.path:
            sys.path.insert(0, "/home/workloft/audit")
        import logger as _l  # noqa
        _l.log(**kwargs)
    except Exception:
        pass


def escalate_one(item: dict) -> None:
    short = item["id"][:8]
    title = item.get("title", "")
    due = loop_board._fmt_due(item.get("due_at"))
    stage = item.get("stage") or "?"
    default = item.get("default_action") or "(none set)"
    next_step = item.get("next_step") or "(none)"

    # CIBA-style explicit expiry: 72h from now, written into the row + message.
    from datetime import datetime, timezone, timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
    expires_display = (datetime.now(timezone.utc) + timedelta(hours=72)).astimezone(
        timezone(timedelta(hours=1))
    ).strftime("%a %d %b %H:%M %Z")

    msg = (
        f"🚨 *LOOP TTL HIT* — `{short}` ({stage})\n\n"
        f"*{title}*\n"
        f"Due: {due}\n"
        f"Next step on file: {next_step[:200]}\n"
        f"Default action if you don't reply: {default}\n"
        f"⏱ Default fires: {expires_display} (in 72h)\n\n"
        f"Reply with:\n"
        f"`[A] {short}` — Bob ships it today (Bob takes ownership)\n"
        f"`[B] {short}` — kill it (status=killed, archived)\n"
        f"`[C] {short} <days>` — extend TTL by N days\n"
        f"`[T] {short} @<owner>` — transfer ownership (alfred|bob)"
    )

    try:
        _send(msg)
        # Flip to blocked + stamp blocked_at + write explicit expiry
        db._req(
            f"/gary_todos?id=eq.{item['id']}",
            method="PATCH",
            body={
                "status": "blocked",
                "blocked_at": datetime.now(timezone.utc).isoformat(),
                "escalation_expires_at": expires_at,
            },
            prefer="return=minimal",
        )
        _audit(
            agent="gary",
            action="ttl_escalate",
            tool="gary.escalator",
            category="external",
            arguments={"short_id": short, "title": title[:120], "stage": stage,
                       "expires_at": expires_at},
            actor="bob-session",
            session_id="gary.escalator",
        )
        print(f"escalated: {short} {title[:80]} (expires {expires_display})")
    except Exception as e:
        print(f"FAILED to escalate {short}: {e}", file=sys.stderr)


def escalate_blocked_24h(item: dict) -> None:
    """Louder reminder for items blocked >24h but <72h."""
    short = item["id"][:8]
    title = item.get("title", "")
    default = item.get("default_action") or "(none set)"
    expires = item.get("escalation_expires_at")

    msg = (
        f"⏰ *BLOCKED 24h+* — `{short}`\n\n"
        f"*{title}*\n"
        f"Default fires: {expires[:16] if expires else '?'} UTC\n"
        f"Default action: {default}\n\n"
        f"Reply `[A]` / `[B]` / `[C] <days>` to override the default."
    )

    try:
        _send(msg)
        _audit(
            agent="gary", action="blocked_24h_reminder", tool="gary.escalator",
            category="external",
            arguments={"short_id": short, "title": title[:120]},
            actor="bob-session", session_id="gary.escalator",
        )
        print(f"reminded (24h): {short}")
    except Exception as e:
        print(f"FAILED reminder {short}: {e}", file=sys.stderr)


def fire_default_action(item: dict) -> None:
    """Item's escalation_expires_at passed with no reply. Fire the default."""
    short = item["id"][:8]
    title = item.get("title", "")
    default = (item.get("default_action") or "").strip()
    from datetime import datetime, timezone, timedelta

    if default == "kill" or default.startswith("archive if not shipped"):
        db._req(
            f"/gary_todos?id=eq.{item['id']}",
            method="PATCH",
            body={"status": "killed"},
            prefer="return=minimal",
        )
        action_desc = "killed (default expired)"
    elif default.startswith("extend-"):
        # extend-3d means push due_at by 3 days, reset to open
        days = 3
        try:
            days = int(default.split("-", 1)[1].rstrip("d"))
        except Exception:
            pass
        new_due = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        db._req(
            f"/gary_todos?id=eq.{item['id']}",
            method="PATCH",
            body={
                "status": "open",
                "due_at": new_due,
                "blocked_at": None,
                "escalation_expires_at": None,
            },
            prefer="return=minimal",
        )
        action_desc = f"extended {days}d (default expired)"
    elif default == "transfer-to-alfred":
        db._req(
            f"/gary_todos?id=eq.{item['id']}",
            method="PATCH",
            body={"owner": "alfred", "status": "open"},
            prefer="return=minimal",
        )
        action_desc = "transferred to alfred (default expired)"
    else:
        # Unknown default. Fail safe to kill rather than leave in limbo.
        db._req(
            f"/gary_todos?id=eq.{item['id']}",
            method="PATCH",
            body={"status": "killed"},
            prefer="return=minimal",
        )
        action_desc = f"killed (unknown default {default!r}, failed safe)"

    msg = (
        f"⏰ *DEFAULT FIRED* — `{short}`\n"
        f"*{title}*\n"
        f"Action: {action_desc}"
    )
    try:
        _send(msg)
    except Exception:
        pass

    _audit(
        agent="gary", action="default_fired", tool="gary.escalator",
        category="external",
        arguments={"short_id": short, "default": default, "result": action_desc},
        actor="bob-session", session_id="gary.escalator",
    )
    print(f"default fired: {short} {action_desc}")


def fetch_blocked_24h() -> list[dict]:
    """Blocked items 24-72h old (between first reminder + auto-fire)."""
    from datetime import datetime, timezone, timedelta
    from urllib import parse as urlparse
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_72h = (now - timedelta(hours=72)).isoformat()
    import json as _json
    q = (
        "/gary_todos?"
        "select=*"
        "&tag=eq.loop"
        "&status=eq.blocked"
        f"&blocked_at=lte.{urlparse.quote(cutoff_24h)}"
        f"&blocked_at=gt.{urlparse.quote(cutoff_72h)}"
    )
    return _json.loads(db._req(q))


def fetch_blocked_expired() -> list[dict]:
    """Blocked items whose escalation_expires_at has passed → fire default."""
    from datetime import datetime, timezone
    from urllib import parse as urlparse
    import json as _json
    now = datetime.now(timezone.utc).isoformat()
    q = (
        "/gary_todos?"
        "select=*"
        "&tag=eq.loop"
        "&status=eq.blocked"
        f"&escalation_expires_at=lt.{urlparse.quote(now)}"
    )
    return _json.loads(db._req(q))


def main() -> int:
    # Stage 1: new overdue items → escalate to blocked
    overdue = loop_board.fetch_overdue()
    if overdue:
        print(f"Overdue Loop items: {len(overdue)}")
        for item in overdue:
            escalate_one(item)

    # Stages 2 + 3 depend on the v2 schema columns. Skip gracefully if not yet migrated.
    try:
        blocked_24h = fetch_blocked_24h()
        if blocked_24h:
            print(f"Blocked 24h+ items: {len(blocked_24h)}")
            for item in blocked_24h:
                escalate_blocked_24h(item)

        expired = fetch_blocked_expired()
        if expired:
            print(f"Defaults to fire: {len(expired)}")
            for item in expired:
                fire_default_action(item)
    except RuntimeError as e:
        if "does not exist" in str(e):
            print(f"v2 schema not migrated yet, skipping blocked-TTL stages: {e}",
                  file=sys.stderr)
        else:
            raise

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Dead-man watchdog for Loop crons.

Self-hosted equivalent of Healthchecks.io. Each Loop cron writes a heartbeat
file on success. This script runs hourly, checks each expected heartbeat
against the grace window, and pings Telegram if a heartbeat is missing.

Cron schedule:
    Each cron appends `&& /home/workloft/gary/cron_heartbeat.sh <name>`
    This script runs at *:25 hourly, after the escalator at *:17.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Import telegram sender from sibling
sys.path.insert(0, "/home/workloft/gary")
try:
    from escalator import _send
except Exception:
    _send = None

HEARTBEAT_DIR = Path("/var/lib/larry-bob/heartbeats")

# Expected cadence (seconds). A heartbeat older than this triggers an alert.
EXPECTED = {
    # name              max_age_seconds   description
    "loop-state":       (15 * 60 + 300,    "STATE.md LOOP refresh (15-min)"),
    "loop-escalator":   (60 * 60 + 300,    "Hourly TTL escalator"),
    # morning + evening are daily; we check ~25h cadence with a 5-min grace
    "loop-morning":     (25 * 60 * 60,     "08:00 BST morning template"),
    "loop-evening":     (25 * 60 * 60,     "22:00 BST evening template"),
}

ALERT_STATE_DIR = Path("/var/lib/larry-bob/heartbeats/state")
ALERT_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _last_alert_state(name: str) -> str:
    p = ALERT_STATE_DIR / f"{name}.state"
    if p.exists():
        return p.read_text().strip()
    return "ok"


def _save_alert_state(name: str, state: str) -> None:
    (ALERT_STATE_DIR / f"{name}.state").write_text(state)


def check_one(name: str, max_age: int, desc: str) -> str:
    """Return 'ok' or 'missing'."""
    hb_file = HEARTBEAT_DIR / name
    if not hb_file.exists():
        # If we've never seen this heartbeat, give it 2x grace before alerting.
        # Avoids alerts on the first run before any cron has fired.
        startup_grace = max_age * 2
        startup_ref = HEARTBEAT_DIR / ".startup"
        if not startup_ref.exists():
            HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
            startup_ref.write_text(str(int(time.time())))
            return "ok"
        try:
            startup_ts = int(startup_ref.read_text().strip())
        except Exception:
            return "ok"
        if time.time() - startup_ts < startup_grace:
            return "ok"
        return "missing"
    try:
        last = int(hb_file.read_text().strip())
    except Exception:
        return "missing"
    age = time.time() - last
    return "ok" if age < max_age else "missing"


def main() -> int:
    transitions = []
    for name, (max_age, desc) in EXPECTED.items():
        new = check_one(name, max_age, desc)
        old = _last_alert_state(name)
        if new != old:
            transitions.append((name, desc, old, new))
            _save_alert_state(name, new)

    # Edge-triggered: only alert on transitions, not every tick.
    for name, desc, old, new in transitions:
        if new == "missing":
            msg = (
                f"🚨 *CRON DEADMAN*\n\n"
                f"Loop cron `{name}` has missed its heartbeat window.\n"
                f"Job: {desc}\n"
                f"Last heartbeat too old (or never fired).\n\n"
                f"Investigate: `tail /var/lib/larry-bob/bridge-logs/{name}.log`"
            )
        else:
            msg = (
                f"✓ *CRON RECOVERED*\n\n"
                f"Loop cron `{name}` is heartbeating again.\n"
                f"({desc})"
            )
        if _send:
            try:
                _send(msg)
            except Exception as e:
                print(f"deadman: failed to send for {name}: {e}", file=sys.stderr)
        print(f"{name}: {old} -> {new}")

    if not transitions:
        print("all crons heartbeating")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Send the Loop morning or evening template to Alfred on Telegram.

Usage:
    python3 loop_digest.py morning
    python3 loop_digest.py evening
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loop_board  # noqa: E402
from escalator import _send, _audit  # noqa: E402


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if mode == "morning":
        text = loop_board.morning_template()
    elif mode == "evening":
        text = loop_board.evening_template()
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        return 2

    try:
        _send(text)
        _audit(
            agent="gary",
            action=f"loop_digest_{mode}",
            tool="gary.loop_digest",
            category="external",
            arguments={"mode": mode, "chars": len(text)},
            actor="bob-session",
            session_id="gary.loop_digest",
        )
        print(f"sent {mode} digest ({len(text)} chars)")
        return 0
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

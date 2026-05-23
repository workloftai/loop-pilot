#!/usr/bin/env python3
"""Stop hook — enforces the three-terminal-state contract on Loop items.

Fires when the Claude Code session is about to stop. Queries Gary for any
#loop items in 'in_progress' status owned by bob. If any are found, exit 2
with a model-visible message listing them, forcing the model to transition
each before the session can end.

Exit codes:
  0 — clean, session can stop
  2 — blocking, message sent back to model (Claude must resolve before stop)
  >2 — script error (do not block; we'd rather miss enforcement than hang sessions)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Wrap everything in a top-level try so a Gary DB outage never wedges the session.
try:
    sys.path.insert(0, "/home/workloft/gary")
    import db  # noqa: E402

    q = (
        "/gary_todos?"
        "select=id,title,stage,due_at,owner,status"
        "&tag=eq.loop"
        "&status=eq.in_progress"
        "&owner=eq.bob"
    )
    rows = json.loads(db._req(q))

    if not rows:
        sys.exit(0)

    short = [f"  - {r['id'][:8]} [{r.get('stage','?')}] {r.get('title','')[:80]}" for r in rows]
    msg = (
        f"Loop contract violation: {len(rows)} #loop item(s) still in_progress.\n"
        f"Before stopping this session, transition each to shipped, blocked, or killed:\n"
        + "\n".join(short)
        + "\n\nCLI:\n"
          "  gary ship <id>                       — shipped (terminal success)\n"
          "  gary block <id> --reason \"…\"        — waiting on Alfred (terminal-ish)\n"
          "  gary kill  <id> --reason \"…\"        — killed (terminal failure)\n\n"
          "If you genuinely worked on none of these, demote them with:\n"
          "  gary update <id> --next-step \"deferred: <reason>\"\n"
          "and then explicitly `gary block`."
    )

    print(msg, file=sys.stderr)
    sys.exit(2)

except SystemExit:
    raise
except Exception as e:
    # Fail open: we'd rather miss an enforcement check than break Stop entirely.
    print(f"loop_stop_audit: soft-error: {e}", file=sys.stderr)
    sys.exit(0)

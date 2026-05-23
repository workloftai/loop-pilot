# loop-pilot

A todo system the agent cannot cheat.

This repo is the open-source mirror of the watertight Workloft Loop pilot. We
spent a day building enforcement around our agent stack's todo list because
items were rotting (164 open, many overdue two weeks) and nothing forced
resolution. The result is a small set of pieces that together make sure every
item ends in `shipped` or `killed`. No third state.

Full write-up: [workloft.ai/ships/watertight-todos-2026-05-23.html](https://workloft.ai/ships/watertight-todos-2026-05-23.html)

## The pieces

### 1. Claude Code Stop hook (`hooks/loop_stop_audit.py`)

The biggest one. Before the agent can end a session, this hook queries the
todo table for items in `in_progress` status owned by the agent. If any
exist, the hook exits with code 2 and a model-visible message listing each.
Exit code 2 is the Claude Code convention for "do not stop yet". The model
must transition each item to shipped, blocked, or killed before it can close
out. **Enforcement at the harness layer, not the prompt layer.**

Register in `~/.claude/settings.json`:

```json
"hooks": {
  "Stop": [{
    "hooks": [{
      "type": "command",
      "command": "/path/to/hooks/loop_stop_audit.py",
      "timeout": 5
    }]
  }]
}
```

### 2. Three-stage TTL escalator (`gary/escalator.py`)

Hourly cron. For each Loop item:

- **Open past due** → Telegram ask with options + 72h expiry + flip to blocked
- **Blocked aged 24h+** → louder Telegram reminder
- **Blocked past expiry** → auto-fire `default_action` (constrained to `kill`,
  `extend-3d`, or `transfer-to-alfred`)

The escalator can resolve any item without a human.

### 3. Hardened snooze (in your CLI)

Snooze requires a `--reason` and caps at one attempt per item. A second
snooze auto-flips the item to blocked instead of indefinitely deferring.

Snooze was the original rot vector. It is closed now.

### 4. Self-hosted dead-man (`gary/cron_deadman.py` + `cron_heartbeat.sh`)

Each cron writes a heartbeat file on success. A watchdog (also cron) checks
heartbeat ages against expected cadences and fires an edge-triggered
Telegram alert if any cron misses its window. Recovery messages too.

No Healthchecks.io, no signup, no external dependency.

### 5. Twice-daily templates (`gary/loop_board.py`, `gary/loop_digest.py`)

08:00 BST morning: shipping today, decisions owed, stale items.
22:00 BST evening: shipped, slipped, queued, archived, plus the pilot
evaluation report inline (`gary/status_report.py`).

### 6. Pilot evaluation rubric (`gary/status_report.py`)

Five metrics with pass/fail thresholds. Run `gary status-report` (or
`python3 gary/status_report.py`) for the current scoreboard.

## Schema

Two migrations in `migrations/`. Together they add:

- `owner` text (bob | alfred)
- `stage` text (research | ship | publish)
- `snooze_count` int with a hard cap of 1
- `default_action` text constrained to {kill, extend-3d, transfer-to-alfred}
- `stage_entered_at` timestamptz (TTL anchor that resists gaming via
  `updated_at` touches)
- `blocked_at` + `escalation_expires_at` timestamps for the blocked-state
  lifecycle
- Status enum extended to {open, in_progress, blocked, shipped, done,
  cancelled, killed}

## What this is and is not

This is the small viable version of "the agent cannot leave work in a state
nobody is tracking". It runs in production at [Workloft](https://workloft.ai)
on a one-person stack.

It is not a framework. It is not a SaaS. It is a small set of scripts you can
read, fork, and adapt. The interesting move is the Stop hook, not the schema.

## Status

Day 1 of a 7-day pilot. Caught its first contract violation 30 minutes after
going live. Day-7 decision gate: pass means generalise to other Gary tags;
fail means redesign before generalising. Full pilot rubric in the Ship
article.

## License

MIT. Use, fork, learn from, contribute back if you find a hole.


### 7. Posts ledger (`gary/post_log.py`)

A small Supabase-backed ledger of every public post (LinkedIn, X, future channels). One row per posted artefact: channel, slug, posted_url, posted_at, ship_ref (link to the article being promoted), hero_path, hashtags, char count, source. CLI:

```bash
workloft-post log --channel linkedin --slug X --url https://... --ship-ref https://...
workloft-post list [--channel X]
workloft-post show <id-prefix>
workloft-post stats
```

The point: Maggie-style JSON queues hold intent. A posts ledger holds outcome. Different jobs. Without a separate record of what actually went out, the agent stack cannot tell scheduled-but-never-posted from genuinely-shipped.

Migration: `migrations/2026-05-23-workloft-posts.sql`.

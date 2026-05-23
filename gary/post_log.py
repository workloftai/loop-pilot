#!/usr/bin/env python3
"""workloft-post — small CLI for logging public posts (LI / X / future).

Usage:
    workloft-post log --channel linkedin --slug watertight-todos-2026-05-23 \
                      --url https://www.linkedin.com/posts/... \
                      --ship-ref https://workloft.ai/ships/watertight-todos-2026-05-23.html

    workloft-post list [--channel linkedin] [--limit 20]
    workloft-post show <id-prefix>
    workloft-post stats               # counts per channel + last 30d
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402


def _audit(**kwargs):
    try:
        if "/home/workloft/audit" not in sys.path:
            sys.path.insert(0, "/home/workloft/audit")
        import logger as _l  # noqa
        _l.log(**kwargs)
    except Exception:
        pass


def cmd_log(args) -> int:
    row = {
        "channel": args.channel,
        "slug": args.slug,
        "title": args.title,
        "body": args.body,
        "posted_url": args.url,
        "posted_at": args.posted_at or datetime.now(timezone.utc).isoformat(),
        "ship_ref": args.ship_ref,
        "hero_path": args.hero_path,
        "hashtags": [h.strip().lstrip("#") for h in (args.hashtags or "").split(",") if h.strip()],
        "chars": args.chars,
        "source": args.source,
        "notes": args.notes,
    }
    row = {k: v for k, v in row.items() if v not in (None, "", [])}
    raw = db._req("/workloft_posts?select=*",
                   method="POST", body=[row], prefer="return=representation")
    inserted = json.loads(raw)[0]
    sid = inserted["id"][:8]
    print(f"✓ {sid} [{inserted['channel']}] {inserted['slug']} — {inserted['posted_url']}")
    _audit(agent="workloft-post", action="log_post", tool="post_log.cli",
           category="write",
           arguments={"channel": args.channel, "slug": args.slug, "url": args.url},
           response={"short_id": sid},
           actor="bob-session", session_id="post-log")
    return 0


def cmd_list(args) -> int:
    q = ["select=id,channel,slug,posted_url,posted_at,title",
         f"limit={args.limit}",
         "order=posted_at.desc"]
    if args.channel:
        q.append(f"channel=eq.{args.channel}")
    rows = json.loads(db._req("/workloft_posts?" + "&".join(q)))
    if not rows:
        print("(no posts)")
        return 0
    print(f"{len(rows)} post(s):")
    for r in rows:
        sid = r["id"][:8]
        ts = r["posted_at"][:10]
        chan = r["channel"]
        title = (r.get("title") or r.get("slug") or "")[:80]
        print(f"  {sid} {ts} [{chan:8s}] {title}")
        print(f"           {r.get('posted_url','')}")
    return 0


def cmd_show(args) -> int:
    rows = json.loads(db._req(f"/workloft_posts?id=like.{args.id}%25&select=*&limit=1"))
    if not rows:
        print("(not found)", file=sys.stderr)
        return 1
    print(json.dumps(rows[0], indent=2, default=str))
    return 0


def cmd_stats(args) -> int:
    rows = json.loads(db._req("/workloft_posts?select=channel,posted_at&limit=1000"))
    by_chan: dict[str, int] = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    last_30: dict[str, int] = {}
    for r in rows:
        c = r["channel"]
        by_chan[c] = by_chan.get(c, 0) + 1
        try:
            ts = datetime.fromisoformat(r["posted_at"].replace("Z", "+00:00"))
            if ts >= cutoff:
                last_30[c] = last_30.get(c, 0) + 1
        except Exception:
            pass
    print(f"Total: {len(rows)} posts")
    print()
    print(f"{'channel':12s} {'all-time':>10s} {'last 30d':>10s}")
    for c in sorted(set(list(by_chan.keys()) + list(last_30.keys()))):
        print(f"  {c:10s} {by_chan.get(c,0):>10d} {last_30.get(c,0):>10d}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workloft-post", description="Log + query Workloft posts")
    sub = p.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("log", help="log a posted artefact")
    l.add_argument("--channel", required=True,
                   choices=["linkedin", "x", "mastodon", "bluesky", "youtube", "other"])
    l.add_argument("--slug", required=True, help="e.g. watertight-todos-2026-05-23")
    l.add_argument("--url", required=True, help="The public URL of the posted artefact")
    l.add_argument("--posted-at", dest="posted_at",
                   help="ISO timestamp; defaults to now()")
    l.add_argument("--title")
    l.add_argument("--body")
    l.add_argument("--ship-ref", dest="ship_ref", help="URL of the related Ship article or Labs Note")
    l.add_argument("--hero-path", dest="hero_path", help="Path to the hero image used")
    l.add_argument("--hashtags", help="Comma-separated, with or without #")
    l.add_argument("--chars", type=int)
    l.add_argument("--source", default="alfred-paste",
                   choices=["alfred-paste", "maggie-auto", "backfill", "other"])
    l.add_argument("--notes")
    l.set_defaults(fn=cmd_log)

    ls = sub.add_parser("list", help="list recent posts")
    ls.add_argument("--channel")
    ls.add_argument("--limit", type=int, default=20)
    ls.set_defaults(fn=cmd_list)

    sh = sub.add_parser("show", help="show a single post by short id")
    sh.add_argument("id", help="short id prefix")
    sh.set_defaults(fn=cmd_show)

    st = sub.add_parser("stats", help="counts per channel + last 30d")
    st.set_defaults(fn=cmd_stats)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

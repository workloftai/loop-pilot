-- Workloft posts ledger — canonical record of every public post (LI, X, future)
-- Maggie's JSON queues stay as the draft/scheduler tracker; this table is the
-- shipped-record of truth. One row per posted artefact. Append-mostly.

BEGIN;

CREATE TABLE IF NOT EXISTS workloft_posts (
  id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  channel         text         NOT NULL,
  slug            text         NOT NULL,
  title           text,
  body            text,
  posted_url      text         NOT NULL,
  posted_at       timestamptz  NOT NULL,
  ship_ref        text,
  hero_path       text,
  hashtags        text[],
  chars           int,
  source          text         DEFAULT 'alfred-paste',
  impressions     int,
  engagement      int,
  notes           text,
  created_at      timestamptz  NOT NULL DEFAULT now(),
  updated_at      timestamptz  NOT NULL DEFAULT now()
);

ALTER TABLE workloft_posts DROP CONSTRAINT IF EXISTS workloft_posts_channel_check;
ALTER TABLE workloft_posts ADD CONSTRAINT workloft_posts_channel_check
  CHECK (channel IN ('linkedin', 'x', 'mastodon', 'bluesky', 'youtube', 'other'));

ALTER TABLE workloft_posts DROP CONSTRAINT IF EXISTS workloft_posts_source_check;
ALTER TABLE workloft_posts ADD CONSTRAINT workloft_posts_source_check
  CHECK (source IN ('alfred-paste', 'maggie-auto', 'backfill', 'other'));

CREATE INDEX IF NOT EXISTS workloft_posts_channel_idx     ON workloft_posts (channel, posted_at DESC);
CREATE INDEX IF NOT EXISTS workloft_posts_slug_idx        ON workloft_posts (slug);
CREATE INDEX IF NOT EXISTS workloft_posts_posted_at_idx   ON workloft_posts (posted_at DESC);

COMMIT;

-- Sanity: SELECT count(*) FROM workloft_posts; -- expect 0 on first run.

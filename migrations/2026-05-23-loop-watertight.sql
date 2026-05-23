-- Gary schema migration for the Watertight Loop Pilot (2026-05-23)
--
-- Adds the columns needed to enforce: every item has an owner, every item
-- ends in one of three terminal states, snooze is capped, asks carry a
-- default action.
--
-- Run via Supabase SQL editor on project elvsximyeztwopjkubeo (eu-west-2).
-- Idempotent: uses IF NOT EXISTS where possible.

BEGIN;

-- 1. New columns ----------------------------------------------------------
ALTER TABLE gary_todos
  ADD COLUMN IF NOT EXISTS owner          text,
  ADD COLUMN IF NOT EXISTS stage          text,
  ADD COLUMN IF NOT EXISTS snooze_count   integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS default_action text;

-- 2. Owner constraint (bob | alfred), nullable for legacy rows ------------
ALTER TABLE gary_todos
  DROP CONSTRAINT IF EXISTS gary_todos_owner_check;
ALTER TABLE gary_todos
  ADD CONSTRAINT gary_todos_owner_check
  CHECK (owner IS NULL OR owner IN ('bob', 'alfred'));

-- 3. Stage constraint (research | ship | publish), nullable for non-Loop --
ALTER TABLE gary_todos
  DROP CONSTRAINT IF EXISTS gary_todos_stage_check;
ALTER TABLE gary_todos
  ADD CONSTRAINT gary_todos_stage_check
  CHECK (stage IS NULL OR stage IN ('research', 'ship', 'publish'));

-- 4. Snooze cap (max 1) ---------------------------------------------------
ALTER TABLE gary_todos
  DROP CONSTRAINT IF EXISTS gary_todos_snooze_count_check;
ALTER TABLE gary_todos
  ADD CONSTRAINT gary_todos_snooze_count_check
  CHECK (snooze_count >= 0 AND snooze_count <= 1);

-- 5. Status: expand allowed values ---------------------------------------
-- Existing live values: 'open', 'done', 'cancelled'.
-- New values added by this migration:
--   'in_progress'           — Bob is actively working on it
--   'blocked'               — Bob is waiting on Alfred (an ASK is open)
--   'killed'                — explicitly killed (distinct from 'cancelled')
ALTER TABLE gary_todos
  DROP CONSTRAINT IF EXISTS gary_todos_status_check;
ALTER TABLE gary_todos
  ADD CONSTRAINT gary_todos_status_check
  CHECK (status IN ('open', 'in_progress', 'blocked', 'shipped', 'done', 'cancelled', 'killed'));

-- 6. Source: align with audit-log feedback memory ------------------------
-- Memory `e652d317` flagged that 'maggie/larry/ruby/otto/bob-jobs/hitl' get
-- rejected. Fix now while we're touching constraints.
ALTER TABLE gary_todos
  DROP CONSTRAINT IF EXISTS gary_todos_source_check;
ALTER TABLE gary_todos
  ADD CONSTRAINT gary_todos_source_check
  CHECK (source IN (
    'bob-session', 'alfred', 'plaud', 'josh', 'walt', 'gmail',
    'maggie', 'larry', 'ruby', 'otto', 'bob-jobs', 'hitl', 'other'
  ));

-- 7. Index for the morning/evening cron queries --------------------------
CREATE INDEX IF NOT EXISTS gary_todos_loop_idx
  ON gary_todos (tag, status, stage, due_at)
  WHERE tag = 'loop';

COMMIT;

-- Sanity checks (run separately after commit):
-- SELECT COUNT(*) FROM gary_todos WHERE status = 'open';   -- expect 0
-- SELECT COUNT(*) FROM gary_todos;                          -- expect ~existing total
-- \d+ gary_todos                                            -- inspect new columns

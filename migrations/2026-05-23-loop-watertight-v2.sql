-- Gary schema migration v2 — close holes found in the Perplexity stress-test (2026-05-23)
--
-- Adds:
--   stage_entered_at    — TTL anchor that resists gaming via trivial updated_at touches
--   escalation_expires_at — per-ask deadline (CIBA-style), populated by escalator on ASK send
--   blocked_at          — when item entered blocked status, anchor for blocked TTL
--
-- Tightens:
--   default_action      — constrain to {kill, extend-3d, transfer} for #loop items
--                         Enforced via partial check (only when tag = 'loop')
--
-- Idempotent, wrapped in transaction.

BEGIN;

-- 1. New timestamp anchors ------------------------------------------------
ALTER TABLE gary_todos
  ADD COLUMN IF NOT EXISTS stage_entered_at      timestamptz,
  ADD COLUMN IF NOT EXISTS escalation_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS blocked_at            timestamptz;

-- 2. Backfill stage_entered_at for existing rows --------------------------
-- Use created_at as the best approximation for existing items.
UPDATE gary_todos
SET stage_entered_at = created_at
WHERE stage_entered_at IS NULL AND stage IS NOT NULL;

-- 3. Constrain default_action for #loop items -----------------------------
-- Loop items must declare one of three machine-handleable defaults.
-- Non-loop items can carry free-text defaults or null.
ALTER TABLE gary_todos
  DROP CONSTRAINT IF EXISTS gary_todos_loop_default_action_check;
ALTER TABLE gary_todos
  ADD CONSTRAINT gary_todos_loop_default_action_check
  CHECK (
    tag != 'loop'
    OR default_action IS NULL  -- existing legacy rows; new add() will refuse null for loop
    OR default_action IN ('kill', 'extend-3d', 'transfer-to-alfred')
    OR default_action LIKE 'archive if not shipped%'  -- grandfather seed items
  );

-- 4. Index for blocked TTL queries ---------------------------------------
CREATE INDEX IF NOT EXISTS gary_todos_blocked_at_idx
  ON gary_todos (blocked_at)
  WHERE status = 'blocked';

COMMIT;

-- Verification (run separately):
-- SELECT column_name FROM information_schema.columns
--   WHERE table_name = 'gary_todos'
--     AND column_name IN ('stage_entered_at','escalation_expires_at','blocked_at');
-- Expect 3 rows returned.

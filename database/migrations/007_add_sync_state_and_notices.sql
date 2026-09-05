-- Faz 6: Sync state, sync runs, official notices

-- Extend official_source_state with new columns (add if not exists via ALTER)
ALTER TABLE official_source_state ADD COLUMN last_attempt_at TEXT;
ALTER TABLE official_source_state ADD COLUMN last_success_at TEXT;
ALTER TABLE official_source_state ADD COLUMN last_changed_at TEXT;
ALTER TABLE official_source_state ADD COLUMN last_error TEXT;

-- Backfill new columns from existing data where possible
UPDATE official_source_state SET last_attempt_at = COALESCE(last_checked_at, last_successful_sync_at) WHERE last_attempt_at IS NULL;
UPDATE official_source_state SET last_success_at = last_successful_sync_at WHERE last_success_at IS NULL;

-- Sync runs audit
CREATE TABLE IF NOT EXISTS official_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('GIB', 'SGK')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'SYNCED', 'UNCHANGED', 'UPDATED', 'FAILED', 'NEEDS_REVIEW', 'NOT_AVAILABLE', 'NEEDS_DATA')),
    http_status INTEGER,
    raw_hash TEXT,
    normalized_hash TEXT,
    items_seen INTEGER,
    items_added INTEGER DEFAULT 0,
    items_changed INTEGER DEFAULT 0,
    items_missing INTEGER DEFAULT 0,
    items_unchanged INTEGER DEFAULT 0,
    error_message TEXT,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_runs_source ON official_sync_runs(source_code, started_at DESC);

-- Official notices (SGK)
CREATE TABLE IF NOT EXISTS official_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL, -- SGK, GIB
    source_notice_key TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    source_url TEXT NOT NULL,
    raw_hash TEXT,
    body_hash TEXT,
    classification TEXT, -- e.g., SGK_4A_PREMIUM_PAYMENT, MUHSGK_INSURANCE_SECTION, etc.
    scope_kind TEXT CHECK (scope_kind IN ('NATIONAL_GLOBAL', 'NATIONAL_OBLIGATION_SPECIFIC', 'REGIONAL', 'CONDITIONAL', 'UNRESOLVED')),
    scope_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('DETECTED', 'AUTO_APPLIED', 'NO_RELEVANT_CHANGE', 'NEEDS_REVIEW', 'IGNORED', 'SUPERSEDED')) DEFAULT 'DETECTED',
    acquired_at TEXT NOT NULL,
    processed_at TEXT,
    raw_snapshot_path TEXT,
    details_json TEXT,
    UNIQUE(provider, source_notice_key)
);
CREATE INDEX IF NOT EXISTS idx_notices_provider ON official_notices(provider, status, published_at DESC);

-- For MISSING handling: track how many consecutive syncs an event has been missing
ALTER TABLE official_calendar_events ADD COLUMN missing_since TEXT;
ALTER TABLE official_calendar_events ADD COLUMN withdrawn_at TEXT;
ALTER TABLE official_calendar_events ADD COLUMN is_withdrawn INTEGER NOT NULL DEFAULT 0 CHECK (is_withdrawn IN (0,1));

-- Update view to exclude withdrawn events (existing view definition will be recreated if needed)
-- We will recreate the view to filter withdrawn
DROP VIEW IF EXISTS v_active_official_company_events;
CREATE VIEW v_active_official_company_events AS
SELECT
    co.company_id,
    c.name AS company_name,
    ot.code AS obligation_code,
    ot.name AS obligation_name,
    oce.id AS official_event_id,
    oce.title,
    oce.period_key,
    oce.period_label,
    oce.effective_due_date AS due_date,
    oce.due_time,
    oce.source_kind,
    oce.source_url
FROM company_obligations co
JOIN companies c
  ON c.id = co.company_id AND c.is_active = 1
JOIN obligation_types ot
  ON ot.id = co.obligation_type_id AND ot.is_active = 1
JOIN official_calendar_events oce
  ON oce.obligation_type_id = co.obligation_type_id AND oce.is_active = 1 AND oce.is_withdrawn = 0
LEFT JOIN completion_records cr
  ON cr.source_kind = 'OFFICIAL'
 AND cr.source_id = oce.id
 AND cr.company_id = co.company_id
WHERE co.is_active = 1
  AND cr.id IS NULL;

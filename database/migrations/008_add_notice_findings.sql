-- Faz 6.1: Notice findings for mixed outcomes (e.g., 20 May has 2 findings)
CREATE TABLE IF NOT EXISTS official_notice_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id INTEGER NOT NULL,
    finding_kind TEXT NOT NULL, -- e.g., SGK_4A_PREMIUM_PAYMENT, MUHSGK_INSURANCE_SECTION
    obligation_code TEXT,
    old_due_date TEXT,
    new_due_date TEXT,
    scope_kind TEXT CHECK (scope_kind IN ('NATIONAL_GLOBAL', 'NATIONAL_OBLIGATION_SPECIFIC', 'REGIONAL', 'CONDITIONAL', 'UNRESOLVED')),
    status TEXT NOT NULL CHECK (status IN ('AUTO_APPLIED', 'NEEDS_REVIEW', 'NO_MATCH', 'IGNORED')) DEFAULT 'NEEDS_REVIEW',
    matched_event_id INTEGER,
    revision_id INTEGER,
    reason TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (notice_id) REFERENCES official_notices(id) ON DELETE CASCADE,
    FOREIGN KEY (matched_event_id) REFERENCES official_calendar_events(id) ON DELETE SET NULL,
    FOREIGN KEY (revision_id) REFERENCES official_calendar_revisions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_notice ON official_notice_findings(notice_id, status);
CREATE INDEX IF NOT EXISTS idx_findings_obligation ON official_notice_findings(obligation_code, status);

-- Add canonical hashes to official_source_state for GIB (to fix hash churn)
ALTER TABLE official_source_state ADD COLUMN raw_canonical_hash TEXT;
ALTER TABLE official_source_state ADD COLUMN normalized_hash TEXT;

-- For GIB, store both transport hash and canonical content hash
-- Existing last_content_hash will be treated as normalized_hash for backward compat

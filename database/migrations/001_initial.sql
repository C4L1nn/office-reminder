PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    tax_number TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_tax_number
    ON companies(tax_number)
    WHERE tax_number IS NOT NULL AND tax_number <> '';

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    plate TEXT NOT NULL,
    make TEXT,
    model TEXT,
    model_year INTEGER,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicles_plate
    ON vehicles(plate COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS obligation_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('GIB', 'SGK', 'SYSTEM')),
    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('SEEDED', 'RULE_ENGINE', 'EVENT_DRIVEN')),
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_obligations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    obligation_type_id INTEGER NOT NULL,
    enabled_from TEXT,
    enabled_until TEXT,
    settings_json TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (obligation_type_id) REFERENCES obligation_types(id) ON DELETE RESTRICT,
    UNIQUE(company_id, obligation_type_id)
);

CREATE TABLE IF NOT EXISTS official_calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    obligation_type_id INTEGER NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('GIB', 'SGK')),
    source_event_key TEXT NOT NULL,
    title TEXT NOT NULL,
    period_key TEXT,
    period_label TEXT,
    year INTEGER NOT NULL,
    normal_due_date TEXT NOT NULL,
    effective_due_date TEXT NOT NULL,
    due_time TEXT,
    source_url TEXT NOT NULL,
    source_published_at TEXT,
    source_checked_at TEXT,
    provenance_json TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (obligation_type_id) REFERENCES obligation_types(id) ON DELETE RESTRICT,
    UNIQUE(source_kind, source_event_key)
);

CREATE INDEX IF NOT EXISTS idx_official_calendar_due_date
    ON official_calendar_events(effective_due_date);

CREATE INDEX IF NOT EXISTS idx_official_calendar_obligation
    ON official_calendar_events(obligation_type_id, effective_due_date);

CREATE TABLE IF NOT EXISTS official_calendar_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    official_event_id INTEGER NOT NULL,
    old_due_date TEXT NOT NULL,
    new_due_date TEXT NOT NULL,
    reason TEXT,
    source_url TEXT NOT NULL,
    source_published_at TEXT,
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_reference_json TEXT,
    FOREIGN KEY (official_event_id) REFERENCES official_calendar_events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_official_revisions_event
    ON official_calendar_revisions(official_event_id, detected_at);

CREATE TABLE IF NOT EXISTS manual_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    vehicle_id INTEGER,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'GENERAL',
    due_date TEXT NOT NULL,
    due_time TEXT,
    notes TEXT,
    recurrence_kind TEXT NOT NULL DEFAULT 'NONE'
        CHECK (recurrence_kind IN ('NONE', 'MONTHLY', 'QUARTERLY', 'SEMIANNUAL', 'YEARLY', 'CUSTOM')),
    recurrence_interval INTEGER,
    recurrence_json TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'COMPLETED', 'CANCELLED')),
    parent_reminder_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL,
    FOREIGN KEY (parent_reminder_id) REFERENCES manual_reminders(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_manual_reminders_due_date
    ON manual_reminders(status, due_date);

CREATE INDEX IF NOT EXISTS idx_manual_reminders_company
    ON manual_reminders(company_id, status, due_date);

CREATE TABLE IF NOT EXISTS notification_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('OFFICIAL', 'MANUAL')),
    source_id INTEGER NOT NULL,
    offset_days INTEGER NOT NULL,
    notify_time TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_kind, source_id, offset_days)
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('OFFICIAL', 'MANUAL')),
    source_id INTEGER NOT NULL,
    company_id INTEGER,
    notification_key TEXT NOT NULL,
    due_date_snapshot TEXT NOT NULL,
    delivered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivery_channel TEXT NOT NULL DEFAULT 'WINDOWS',
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_delivery_general_unique
    ON notification_deliveries(source_kind, source_id, notification_key)
    WHERE company_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_delivery_company_unique
    ON notification_deliveries(source_kind, source_id, company_id, notification_key)
    WHERE company_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notification_deliveries_source
    ON notification_deliveries(source_kind, source_id, company_id);

CREATE TABLE IF NOT EXISTS completion_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('OFFICIAL', 'MANUAL')),
    source_id INTEGER NOT NULL,
    company_id INTEGER,
    completion_status TEXT NOT NULL DEFAULT 'COMPLETED'
        CHECK (completion_status IN ('COMPLETED', 'PAID', 'FILED', 'CANCELLED')),
    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    amount REAL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_completion_general_unique
    ON completion_records(source_kind, source_id)
    WHERE company_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_completion_company_unique
    ON completion_records(source_kind, source_id, company_id)
    WHERE company_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('OFFICIAL', 'MANUAL', 'COMPLETION', 'VEHICLE', 'COMPANY')),
    source_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    mime_type TEXT,
    sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_kind, source_id, relative_path)
);

CREATE TABLE IF NOT EXISTS official_source_state (
    source_code TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('GIB', 'SGK')),
    last_seed_version TEXT,
    last_successful_sync_at TEXT,
    last_checked_at TEXT,
    last_content_hash TEXT,
    status TEXT NOT NULL DEFAULT 'NEVER_SYNCED',
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIEW IF NOT EXISTS v_active_official_company_events AS
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
  ON oce.obligation_type_id = co.obligation_type_id AND oce.is_active = 1
LEFT JOIN completion_records cr
  ON cr.source_kind = 'OFFICIAL'
 AND cr.source_id = oce.id
 AND cr.company_id = co.company_id
WHERE co.is_active = 1
  AND cr.id IS NULL;

CREATE VIEW IF NOT EXISTS v_open_manual_reminders AS
SELECT
    mr.id AS manual_reminder_id,
    mr.company_id,
    c.name AS company_name,
    mr.vehicle_id,
    v.plate,
    mr.title,
    mr.category,
    mr.due_date,
    mr.due_time,
    mr.notes,
    mr.recurrence_kind
FROM manual_reminders mr
LEFT JOIN companies c ON c.id = mr.company_id
LEFT JOIN vehicles v ON v.id = mr.vehicle_id
LEFT JOIN completion_records cr
  ON cr.source_kind = 'MANUAL'
 AND cr.source_id = mr.id
 AND cr.company_id IS mr.company_id
WHERE mr.status = 'OPEN'
  AND cr.id IS NULL;

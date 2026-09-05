-- Uygulama içi bildirim kutusu.
--
-- Windows "Rahatsız Etmeyin / Odak Yardımı" açıkken sistem bildirimi hiç
-- görünmeden yutulabiliyor ve bildirim tamamen kayboluyordu. Artık iki kanal var:
--
--   IN_APP  → garantili kanal. Her bildirim buraya yazılır, okunana kadar
--             kenar çubuğunda ve tepsi simgesinde sayaç olarak durur.
--   WINDOWS → en iyi çaba. Gösterilemezse bir sonraki turda tekrar denenir.
--
-- Bu yüzden teslim defteri artık kanal bazlıdır: aynı bildirim IN_APP'te bir kez
-- yazılırken WINDOWS tarafında yeniden denenebilir.

CREATE TABLE IF NOT EXISTS app_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('DUE', 'OVERDUE', 'OFFICIAL_REVISION')),
    severity TEXT NOT NULL DEFAULT 'INFO' CHECK (severity IN ('INFO', 'WARNING', 'DANGER')),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('OFFICIAL', 'MANUAL')),
    source_id INTEGER NOT NULL,
    company_id INTEGER,
    due_date TEXT,
    notification_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- Aynı bildirim kutuya iki kez düşmez.
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_notifications_general_unique
    ON app_notifications(source_kind, source_id, notification_key)
    WHERE company_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_notifications_company_unique
    ON app_notifications(source_kind, source_id, company_id, notification_key)
    WHERE company_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_app_notifications_unread
    ON app_notifications(read_at, created_at DESC);

-- Teslim defterini kanal bazlı hâle getir: eski indeksler kanalı hesaba katmıyordu,
-- bu yüzden IN_APP'e yazmak WINDOWS'un tekrar denenmesini engellerdi.
DROP INDEX IF EXISTS idx_notification_delivery_general_unique;
DROP INDEX IF EXISTS idx_notification_delivery_company_unique;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_delivery_general_unique
    ON notification_deliveries(source_kind, source_id, notification_key, delivery_channel)
    WHERE company_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_delivery_company_unique
    ON notification_deliveries(source_kind, source_id, company_id, notification_key, delivery_channel)
    WHERE company_id IS NOT NULL;

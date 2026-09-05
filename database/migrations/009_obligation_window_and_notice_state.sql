-- RC: (1) yükümlülük geçerlilik penceresi, (2) SGK duyuru sync state, (3) bildirim sonucu izleme.

-- 1) İki ayrı pencere gerekiyor ve ikisi de 001'de var olan kolonlarla ifade edilebiliyor:
--
--    enabled_from / enabled_until  → şirketin yükümlülüğe tabi olduğu takvim aralığı.
--       Varsayılan olarak yükümlülüğün eklendiği yılın 1 Ocak'ı; böylece Eylül'de eklenen
--       bir şirket için o yılın 12 aylık KDV takvimi eksiksiz görünür.
--
--    created_at                    → yükümlülüğün programda takip edilmeye başlandığı an.
--       Geciken hesabı bunu taban alır; aksi hâlde bugün eklenen bir şirket, yılbaşından
--       bugüne kadarki bütün resmî tarihleri anında "geciken" olarak gösterirdi.
--
--    View her ikisini de dışarı verir; pencereyi uygular, geciken filtresini service katmanına bırakır.
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
    oce.source_url,
    oce.eligibility_tags,
    co.enabled_from,
    co.enabled_until,
    substr(co.created_at, 1, 10) AS obligation_tracked_from
FROM company_obligations co
JOIN companies c
  ON c.id = co.company_id AND c.is_active = 1
JOIN obligation_types ot
  ON ot.id = co.obligation_type_id AND ot.is_active = 1
JOIN official_calendar_events oce
  ON oce.obligation_type_id = co.obligation_type_id
 AND oce.is_active = 1
 AND oce.is_withdrawn = 0
LEFT JOIN completion_records cr
  ON cr.source_kind = 'OFFICIAL'
 AND cr.source_id = oce.id
 AND cr.company_id = co.company_id
WHERE co.is_active = 1
  AND cr.id IS NULL
  AND (co.enabled_from IS NULL OR oce.effective_due_date >= co.enabled_from)
  AND (co.enabled_until IS NULL OR oce.effective_due_date <= co.enabled_until);

-- Mevcut kayıtlarda enabled_from boşsa, eklendiği yılın başına damgala.
UPDATE company_obligations
SET enabled_from = COALESCE(enabled_from, substr(created_at, 1, 4) || '-01-01')
WHERE enabled_from IS NULL;

-- 2) SGK duyuru (online) sync durumu, SGK kural takviminden ayrı bir source olarak izlenir.
--    Settings ekranı SGK_4A_<yıl> satırını online duyuru durumu sanmamalıdır.
INSERT OR IGNORE INTO official_source_state (source_code, source_kind, status)
VALUES ('SGK_NOTICES', 'SGK', 'NEVER_SYNCED');

-- 3) Bildirimin gerçekten gösterilip gösterilmediğini ayırt edebilmek için.
--    Başarısız bildirim "delivered" sayılmaz; bu kolon audit içindir.
ALTER TABLE notification_deliveries ADD COLUMN delivery_status TEXT NOT NULL DEFAULT 'SHOWN';

CREATE INDEX IF NOT EXISTS idx_company_obligations_active
    ON company_obligations(company_id, is_active);

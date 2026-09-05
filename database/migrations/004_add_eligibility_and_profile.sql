-- Faz 3.5 + Faz 4: Eligibility/profile ve SGK tatil desteği

-- official_calendar_events için eligibility ve SGK rule metadata
ALTER TABLE official_calendar_events ADD COLUMN subject_kind TEXT;
ALTER TABLE official_calendar_events ADD COLUMN taxpayer_kind TEXT;
ALTER TABLE official_calendar_events ADD COLUMN filing_kind TEXT;
ALTER TABLE official_calendar_events ADD COLUMN upload_preference TEXT;
ALTER TABLE official_calendar_events ADD COLUMN eligibility_tags TEXT; -- JSON array
ALTER TABLE official_calendar_events ADD COLUMN rule_code TEXT;
ALTER TABLE official_calendar_events ADD COLUMN rule_version TEXT;

-- company_obligations settings_json zaten var, dokümantasyon için yorum:
-- e-Defter profile: {"taxpayer_kind": "GELIR"|"DIGER", "upload_preference": "MONTHLY"|"TEMPORARY_PERIOD"}
-- Genel eligibility için ileride tag bazlı filtre kullanılabilir.

-- SGK ve GIB event ayrımı için view güncellemesi gerekmez, service katmanı halledecek.
-- Ancak holiday-aware SGK için resmi tatiller tablosu

CREATE TABLE IF NOT EXISTS holidays_tr (
    holiday_date TEXT PRIMARY KEY, -- YYYY-MM-DD
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('NATIONAL', 'RELIGIOUS', 'HALF_DAY')),
    is_full_day INTEGER NOT NULL DEFAULT 1 CHECK (is_full_day IN (0,1))
);

-- 2026 Türkiye resmi tatilleri (tam gün ve yarım günler)
INSERT OR IGNORE INTO holidays_tr (holiday_date, name, kind, is_full_day) VALUES
('2026-01-01', 'Yılbaşı', 'NATIONAL', 1),
('2026-03-19', 'Ramazan Bayramı Arifesi', 'RELIGIOUS', 0),
('2026-03-20', 'Ramazan Bayramı 1. Gün', 'RELIGIOUS', 1),
('2026-03-21', 'Ramazan Bayramı 2. Gün', 'RELIGIOUS', 1),
('2026-03-22', 'Ramazan Bayramı 3. Gün', 'RELIGIOUS', 1),
('2026-04-23', 'Ulusal Egemenlik ve Çocuk Bayramı', 'NATIONAL', 1),
('2026-05-01', 'Emek ve Dayanışma Günü', 'NATIONAL', 1),
('2026-05-19', 'Atatürk''ü Anma, Gençlik ve Spor Bayramı', 'NATIONAL', 1),
('2026-05-26', 'Kurban Bayramı Arifesi', 'RELIGIOUS', 0),
('2026-05-27', 'Kurban Bayramı 1. Gün', 'RELIGIOUS', 1),
('2026-05-28', 'Kurban Bayramı 2. Gün', 'RELIGIOUS', 1),
('2026-05-29', 'Kurban Bayramı 3. Gün', 'RELIGIOUS', 1),
('2026-05-30', 'Kurban Bayramı 4. Gün', 'RELIGIOUS', 1),
('2026-07-15', 'Demokrasi ve Milli Birlik Günü', 'NATIONAL', 1),
('2026-08-30', 'Zafer Bayramı', 'NATIONAL', 1),
('2026-10-28', 'Cumhuriyet Bayramı Arifesi', 'NATIONAL', 0),
('2026-10-29', 'Cumhuriyet Bayramı', 'NATIONAL', 1);

-- For testing, also add a known holiday for SGK due date testing: 2026-02-28 is not holiday, but we will test 2026-03-20 etc.
-- No additional indexes needed for now.

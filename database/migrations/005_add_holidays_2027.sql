-- 2027 Türkiye resmi tatilleri (SGK vade adjustment için gereklidir, özellikle Aralık 2026 dönemi vadesi 2027-01-31)
INSERT OR IGNORE INTO holidays_tr (holiday_date, name, kind, is_full_day) VALUES
('2027-01-01', 'Yılbaşı', 'NATIONAL', 1),
('2027-03-08', 'Ramazan Bayramı Arifesi', 'RELIGIOUS', 0),
('2027-03-09', 'Ramazan Bayramı 1. Gün', 'RELIGIOUS', 1),
('2027-03-10', 'Ramazan Bayramı 2. Gün', 'RELIGIOUS', 1),
('2027-03-11', 'Ramazan Bayramı 3. Gün', 'RELIGIOUS', 1),
('2027-04-23', 'Ulusal Egemenlik ve Çocuk Bayramı', 'NATIONAL', 1),
('2027-05-01', 'Emek ve Dayanışma Günü', 'NATIONAL', 1),
('2027-05-16', 'Kurban Bayramı Arifesi', 'RELIGIOUS', 0),
('2027-05-17', 'Kurban Bayramı 1. Gün', 'RELIGIOUS', 1),
('2027-05-18', 'Kurban Bayramı 2. Gün', 'RELIGIOUS', 1),
('2027-05-19', 'Kurban Bayramı 3. Gün', 'RELIGIOUS', 1),
('2027-05-19', 'Atatürk''ü Anma, Gençlik ve Spor Bayramı', 'NATIONAL', 1),
('2027-05-20', 'Kurban Bayramı 4. Gün', 'RELIGIOUS', 1),
('2027-07-15', 'Demokrasi ve Milli Birlik Günü', 'NATIONAL', 1),
('2027-08-30', 'Zafer Bayramı', 'NATIONAL', 1),
('2027-10-28', 'Cumhuriyet Bayramı Arifesi', 'NATIONAL', 0),
('2027-10-29', 'Cumhuriyet Bayramı', 'NATIONAL', 1);
-- Note: 2027-05-19 appears twice (Kurban 3 and 19 Mayıs) - is_full_day=1 for both, but dedup via INSERT OR IGNORE will keep first

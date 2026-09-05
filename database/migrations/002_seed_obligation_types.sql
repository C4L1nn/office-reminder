INSERT OR IGNORE INTO obligation_types
(code, name, category, source_kind, schedule_kind, description)
VALUES
('GIB_KDV', 'Katma Değer Vergisi', 'TAX', 'GIB', 'SEEDED', 'GİB resmî vergi takviminden gelir.'),
('GIB_MUHSGK', 'Muhtasar ve Prim Hizmet Beyannamesi', 'TAX', 'GIB', 'SEEDED', 'GİB resmî vergi takviminden gelir.'),
('GIB_DAMGA', 'Damga Vergisi', 'TAX', 'GIB', 'SEEDED', 'GİB resmî vergi takviminden gelir.'),
('GIB_GECICI_KURUMLAR', 'Kurum Geçici Vergisi', 'TAX', 'GIB', 'SEEDED', 'GİB resmî vergi takviminden gelir.'),
('GIB_KURUMLAR', 'Kurumlar Vergisi', 'TAX', 'GIB', 'SEEDED', 'GİB resmî vergi takviminden gelir.'),
('GIB_EDEFTER', 'e-Defter / Berat', 'E_LEDGER', 'GIB', 'SEEDED', 'GİB resmî takviminden gelir.'),
('GIB_MTV', 'Motorlu Taşıtlar Vergisi', 'TAX', 'GIB', 'SEEDED', 'GİB resmî takviminden gelir.'),
('SGK_4A_PREMIUM', 'SGK 4/a İşveren Prim Ödemesi', 'SGK', 'SGK', 'RULE_ENGINE', 'Standart vadeler SGK kural motoru tarafından oluşturulur.'),
('SGK_WORK_ACCIDENT', 'İş Kazası Bildirimi', 'SGK', 'SGK', 'EVENT_DRIVEN', 'Olay tarihine göre iş günü kuralıyla hesaplanır.');

INSERT OR IGNORE INTO app_settings(key, value) VALUES
('notifications.enabled', 'true'),
('notifications.default_offsets', '[14,7,3,1,0]'),
('notifications.check_interval_minutes', '15'),
('startup.enabled', 'false'),
('startup.background', 'true'),
('backup.enabled', 'true'),
('backup.retention_days', '30');

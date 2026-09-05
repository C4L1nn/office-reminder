# FINAL_AUDIT.md — Office Reminder Release Candidate Audit

Tarih: 2026-09-03 · Sürüm: 1.0.0
Kapsam: Tüm depo (app, database, services, ui, tests, build)
Yapı: **Bölüm 1** başlangıç denetimi (bulunan sorunlar), **Bölüm 2** yapılan
düzeltmeler ve doğrulamaları.
Yöntem: Kaynak kod okuması + gerçek SQLite davranışı + gerçek pytest çalıştırması + gerçek UI screenshot incelemesi.
Önceki ajan raporları source-of-truth kabul **edilmemiştir**.

Başlangıç durumu:
- `pytest -q` → 80 passed (fakat aşağıda P0-2'de açıklandığı gibi bazı testler yanlış davranışı doğruluyordu)
- Runtime DB: 500 `official_calendar_events` (476 GİB seed + 24 SGK rule), 5 `official_notices` (hepsi UNKNOWN/NEEDS_REVIEW), 0 `official_calendar_revisions`, 0 `official_sync_runs`
- Python 3.11.9 ortamı, `pyproject.toml` ise `requires-python = ">=3.12"` diyor

---

## Şiddet tanımları

| Seviye | Anlam |
|---|---|
| **P0** | Veri kaybı / yanlış resmî tarih / temel özellik hiç çalışmıyor |
| **P1** | Ana özellik bozuk veya yanıltıcı |
| **P2** | UX / mimari / güvenilirlik |
| **P3** | Polish |

---

## P0 — Bloklayıcı

### P0-1. Şirket yükümlülük profili ilk kayıtta sessizce kayboluyor
**Dosya:** `ui/dialogs/company_obligations_dialog.py:178-197`, `services/company_service.py:99-159`

`CompanyObligationsDialog._on_accept()` KDV varyantlarını ve SGK ücret dönemini kaydetmeye çalışır. Ancak `company_obligations` satırı henüz **yoktur**: satır ancak dialog kapandıktan sonra `CompaniesPage._open_obligations()` içinde `set_company_obligations()` çağrıldığında oluşur.

`set_kdv_profile()` / `set_sgk_wage_period()` satırı bulamayınca `False` döner; dönüş değeri kontrol edilmez ve tüm blok `except Exception: pass` ile sarılıdır.

Sonuç: Bir şirkete **ilk kez** `GIB_KDV + KDV_STANDARD_MONTHLY` veya `SGK_4A_PREMIUM + MONTHLY_1_END` seçildiğinde profil DB'ye hiç yazılmaz. `EligibilityService` profil bulamadığı için `needs_profile` döner ve şirketin **hiçbir KDV/SGK resmî eventi dashboard'da görünmez.** Kullanıcı seçim yaptığını sanır.

**Sıra sorunu (race/order) doğrulandı.**

**Düzeltme:** Tek atomik service transaction — `CompanyService.save_obligation_profile()` — obligation set + KDV profili + SGK ücret dönemi tek `database.session()` içinde yazılır. UI yalnızca veriyi toplar.

---

### P0-2. SGK production notice işleme tamamen fixture ID'sine bağlı — gerçek duyuru asla revision üretemez
**Dosya:** `services/sgk_notice_service.py:448-470`

Tüm iş mantığı şu iki dala bağlı:

```python
if source_key == "SGK_20260331_BORC_UZATMA": ...
elif source_key == "SGK_20260520_MUHSGK_NISAN": ...
```

Gerçek crawler (`_fetch_real_sgk_list`) ise URL slug'ından anahtar üretir:
`SGK_KURUMA_OLAN_BORCLARIN_SON_ODEME_TARIHININ_UZATILMASINA_DAIR_...`

Bu anahtarlar hiçbir zaman fixture ID'leriyle eşleşmez. Dolayısıyla production yolunda:
- **Gövdeden tarih çıkarımı hiç yoktur.** Kodun hiçbir yerinde "31.03.2026 → 07.04.2026" gibi bir tarih çifti metinden parse edilmiyor.
- `classify_sgk_notice()` yalnızca sınıflandırma döner, tarih döndürmez.
- Bu yüzden gerçek bir SGK uzatma duyurusu geldiğinde `official_calendar_revisions` **asla** yazılmaz.

Runtime DB bunu doğruluyor: 5 gerçek duyuru çekilmiş, hepsi `classification=UNKNOWN`, `scope_kind=UNRESOLVED`, `status=NEEDS_REVIEW`, `official_calendar_revisions` = 0.

Ayrıca `tests/test_faz6_new.py:75-100` "production parser" testi, crawler'ı **fixture anahtarlarını döndürecek şekilde mock'layarak** bu boşluğu gizliyor. Test yeşil, sistem çalışmıyor.

**Düzeltme:** Gerçek bir production analiz katmanı (`services/sgk_notice_analyzer.py`):
- Türkçe tarih çıkarımı (`31.03.2026`, `31/03/2026`, `31 Mart 2026`)
- Uzatma yönü tespiti (eski → yeni)
- Semantik sınıflandırma: ödeme (`SGK_4A_PREMIUM_PAYMENT`) vs. sigorta bildirimi (`MUHSGK_INSURANCE_SECTION`) vs. alakasız (SUT/ilaç → `NO_RELEVANT_CHANGE`)
- Bulunan her tarih çifti bir **finding**; olay eşleşmesi `effective_due_date`/`normal_due_date` üzerinden
- Fixture ID hiçbir production business rule'un anahtarı değil (fixture'lar yalnızca snapshot gövdesi sağlar)

---

### P0-3. SGK pagination — yalnızca son sayfa parse ediliyor
**Dosya:** `services/sgk_notice_service.py:168-183`

```python
for page in pages_to_fetch:
    url = ...
    with urllib.request.urlopen(req, ...) as resp:
        html = resp.read()...      # her turda html üzerine yazılır

# ↓ girinti seviyesi 'for base_url' — döngü DIŞINDA
pattern = r'...'
matches = re.findall(pattern, html, re.DOTALL)
```

Parse bloğu sayfa döngüsünün dışındadır. 3 sayfa çekilse bile yalnızca **sonuncusu** parse edilir; ilk sayfalardaki (yani en yeni) duyurular tamamen kaybolur.

Ek olarak `continue` / `break` mantığı `matches` ve `alt_matches` değişkenlerini döngü dışında referans ediyor — `UnboundLocalError` riski.

**Düzeltme:** Her sayfa kendi iterasyonunda `fetch → validate → parse → dedup → watermark` olarak işlenir.

---

## P1 — Ana özellik bozuk

### P1-1. Resmî tarih değişikliği bildirimi hiç gösterilmiyor
**Dosya:** `services/official_update_service.py:156-172`

```python
# Send notification via adapter (if available)
# For now, just record delivery to avoid flood, actual show will be via NotificationService
conn.execute("INSERT OR IGNORE INTO notification_deliveries ...")
try:
    from services.notification_adapter import NotificationPayload
    pass          # ← hiçbir şey yapmıyor
except Exception:
    pass
```

`notification_deliveries` satırı yazılıyor ama Windows bildirimi **hiç** gösterilmiyor. Üstelik satır yazıldığı için dedup devreye girer ve bildirim bir daha asla gösterilemez. `_notify_sgk_changes()` gövdesi tamamen `pass`.

**Düzeltme:** `OfficialUpdateService` bir `NotificationAdapter` alır; bildirim gösterilir; **yalnızca başarılıysa** delivery yazılır.

### P1-2. Başarısız bildirim "delivered" olarak işaretleniyor
**Dosya:** `services/notification_service.py:80-92`, `161-183`

`_show()` `None` döner; dönüş değeri kontrol edilmez; `_mark_delivered()` koşulsuz çağrılır. Adapter hata verse bile kayıt "gönderildi" olur ve bir daha denenmez.

**Düzeltme:** `_show()` / `_show_overdue()` `bool` döner; `_mark_delivered()` yalnızca `True` durumunda.

### P1-3. 30 günden büyük custom notification offset'leri hiç tetiklenmiyor
**Dosya:** `services/notification_service.py:58-62`

```python
max_offset = max(DEFAULT_NOTIFICATION_OFFSETS)      # = 14
upcoming = ...list_due(horizon_days=max(30, max_offset))   # = 30
```

UI 0–365 gün kabul ediyor (`ui/dialogs/reminder_dialog.py:213`), repository 0–365 doğruluyor, ama motor sabit 30 günlük ufuk kullanıyor. "90 gün önce hatırlat" kuralı **asla** ateşlenmez.

**Düzeltme:** Ufuk, aktif `notification_rules` içindeki gerçek maksimum offset'ten hesaplanır.

### P1-4. `notify_time` DB ve UI'da var, hiç uygulanmıyor
`notification_rules.notify_time` yazılıyor ama `check_and_notify` saat kontrolü yapmıyor. Yanıltıcı alan.

**Düzeltme:** `notify_time` gerçekten uygulanır (o saatten önce bildirim gönderilmez).

### P1-5. SGK duyuru sync durumu ayrı source olarak takip edilmiyor
**Dosya:** `services/sgk_notice_service.py:604-646`, `ui/pages/settings_page.py:309`

`SgkNoticeService.sync()` ne `official_sync_runs` ne de `official_source_state` yazıyor. Sonuç:
- `OfficialUpdateService.should_sync("SGK_NOTICES")` her seferinde `True` → 6 saatlik throttle çalışmıyor, her tetiklemede tam crawl.
- Settings ekranı `WHERE source_code LIKE 'SGK_%'` sorgusuyla **SGK_4A_2026 kural takvimi** satırını buluyor ve onu online duyuru sync durumu sanıyor. "SGK: SYNCED" yazıyor ama online kontrol hiç yapılmamış olabilir.

**Düzeltme:** `SGK_NOTICES` ayrı source_code olarak `official_source_state` + `official_sync_runs` içine yazılır (last_attempt/last_success/last_error/status). Settings tam bu satırı okur.

### P1-6. Araç ilişkilendirme UI'da yok (yarım özellik)
**Dosya:** `ui/dialogs/reminder_dialog.py`

Backend tamamen hazır: `manual_reminders.vehicle_id` kolonu, FK, `ReminderRepository.create_manual(vehicle_id=...)`, `ManualReminderRecord.plate`. Ancak `ReminderDialog` içinde araç seçici **yok**; `get_data()` `vehicle_id` döndürmüyor; `DueItem` plaka taşımıyor; tablolarda plaka gösterilmiyor.

Araç Muayenesi / Trafik Sigortası / Kasko akışı "Şirket → Araç → Plaka" olarak kurulamıyor.

**Düzeltme:** Dialog'a şirkete bağlı araç seçici; `DueItem`'a `vehicle_id`/`plate`; tablo ve bildirim metinlerinde plaka.

### P1-7. Yeni şirket anında onlarca "geciken" resmî yükümlülük gösteriyor
**Doğrulama:** Ekran görüntüsü — bugün oluşturulan `TEST LTD.` için dashboard **"Geciken: 27"**.

`list_overdue()` alt sınır uygulamıyor; şirkete yükümlülük atandığı anda yılbaşından bugüne kadarki tüm GİB/SGK eventleri "gecikmiş" sayılıyor. `company_obligations.enabled_from` kolonu mevcut ama hiçbir yerde set edilmiyor veya sorgulanmıyor.

Muhasebe personeli açısından bu ekranı kullanılamaz hâle getiriyor.

**Düzeltme:** `enabled_from` şirket yükümlülüğü etkinleştirildiğinde set edilir; resmî event projeksiyonu `due_date >= enabled_from` filtresi uygular.

### P1-8. UI katmanı doğrudan SQL çalıştırıyor
**Dosya:** `ui/pages/settings_page.py:180-188, 268-299, 301-319`

`SettingsPage` kendi `Database` nesnesini kuruyor ve `app_settings`, `official_calendar_revisions`, `official_notices`, `official_source_state` üzerinde ham SQL çalıştırıyor. `AGENTS.md` ve `PLAN.md` bunu açıkça yasaklıyor.

Ayrıca `dashboard_page.py:135`, `reminders_page.py:153`, `reminder_dialog.py:81`, `quick_add_dialog.py:300` UI'dan doğrudan `CompanyRepository` kullanıyor (repository katmanına doğrudan erişim).

**Düzeltme:** `SettingsService` + `OfficialStatusService`; UI yalnızca service çağırır.

### P1-9. Manuel sync UI thread'ini bloke edebiliyor
**Dosya:** `app/application.py:238-259`, `ui/pages/settings_page.py:253-263`

`trigger_manual_sync()` `future.result(timeout=60)` ile 60 saniyeye kadar bloke ediyor. Settings'ten normalde bir `threading.Thread` içinden çağrılıyor ama fallback dalı (`_sync_callback` yoksa) `svc.sync_all()`'u doğrudan UI thread'inde çalıştırıyor → uygulama donar.

Ayrıca `services/sync_worker.py` `QThreadPool` ile doğru altyapıyı sağlıyor ama manuel yolda kullanılmıyor.

---

## P2 — UX / mimari / güvenilirlik

### P2-1. UI profesyonel ürün seviyesinde değil (kabul edilmedi)
Ekran görüntüleriyle doğrulandı:
- `resources/styles/dark.qss` **hiçbir zaman yüklenmiyor** (kod tabanında `setStyleSheet` ile qss dosyası okunmuyor).
- Bunun yerine ~20 yerde inline, **açık tema için yazılmış** renkler hardcoded: `#f3f4f6`, `#f9fafb`, `#374151`, `#6b7280`, `#555`, `#888`.
- Sistem teması koyu olduğu için: KPI kartları beyaz zemin + beyaz yazı (okunmuyor), ipucu metinleri koyu gri zemin üstüne koyu gri (okunmuyor), Ayarlar sayfasında etiketlerin yarısı görünmez.
- Boş tablo → ekranın %70'i anlamsız siyah alan, empty state yok.
- `QTabWidget` üst sekme barı, stok `QGroupBox`, tam genişlik butonlar, buton hiyerarşisi yok.
- Emoji/unicode ikon dahi yok, hiç ikon yok.
- Tek bir design token katmanı yok.

### P2-2. Sessizce yutulan istisnalar
`except Exception: pass` / `except Exception: ...` toplam **60+** yerde. Kritik olanlar:
- `company_obligations_dialog.py:195` → P0-1'in görünmez olmasının nedeni
- `sgk_notice_service.py` detay/PDF/liste fetch — tümü sessiz
- `app/paths.py:88` modül seviyesinde `try/except` ile yol sabitleri

### P2-3. Migration atomik değil
**Dosya:** `database/migrations.py:34-39`

`sqlite3.executescript()` çağrılmadan önce bekleyen transaction'ı **commit eder** ve script'i autocommit modunda çalıştırır. Bir migration ortasında hata olursa önceki ifadeler kalıcı olur, ama `applied_migrations` satırı yazılmaz → sonraki açılışta aynı migration tekrar çalışır ve `ALTER TABLE ... ADD COLUMN` "duplicate column" ile patlar (004 ve 007 `IF NOT EXISTS` desteklemiyor).

### P2-4. SGK duyuru başlıkları HTML entity olarak kaydediliyor
Runtime DB:
`'Bedeli &#xD6;denecek &#x130;la&#xE7;lar Listesinde Yap&#x131;lan D&#xFC;zenlemeler...'`

`_fetch_real_sgk_list` başlığı `html.unescape()` yapmıyor (import ediliyor ama kullanılmıyor) ve 120 karakterde kelime ortasından kesiyor.

### P2-5. `classify_sgk_notice` bölgesel tespiti güvenilmez
`regional_keywords` listesinde `"ankara"`, `"istanbul"`, `"adana"` var. Ulusal bir duyuru gövdesinde kurum adresi geçerse "REGIONAL" damgası yiyebilir. Aynı zamanda `"mücbir sebep"` gibi gerçek sinyaller diğer koşullara takılıp kaçabilir.

### P2-6. `official_notices.status` alanında `NO_RELEVANT_CHANGE` hiç kullanılmıyor
Şema destekliyor ama kod her alakasız duyuruyu (ilaç listesi, SUT tebliği) `NEEDS_REVIEW` yapıyor → Settings'te "5 incelenmeli" gibi sürekli yanlış alarm.

### P2-7. `list_due(include_overdue=True)` alt sınırsız
`start=None` olduğunda geçmişteki tüm eventler dahil ediliyor; `Hatırlatmalar → Tümü` görünümü yıllar öncesini de çekebilir.

### P2-8. Ölü / yarım kod
- `services/official_update_service.py:174-176` `_notify_sgk_changes` gövdesi `pass`
- `services/reminder_service.py:376-379` `if include_overdue:` bloğu yalnızca yorum + `pass`
- `database/repositories/reminders.py:391-403` 13 satırlık kararsız yorum bloğu, `update_with_company_clear()` fiilen kullanılmıyor
- `ui/dialogs/company_obligations_dialog.py:157-161` boş `for` döngüsü + `pass`
- `app/application.py:115-121` "test" amaçlı log satırı production kodunda
- `services/gib_sync_service.py:290` fonksiyon içinde `import hashlib, json` (zaten üstte var)
- `ui/pages/settings_page.py:3` kullanılmayan `subprocess` importu

### P2-9. Paket / ortam tutarsızlığı
- `pyproject.toml` `requires-python = ">=3.12"`, çalışan ortam **3.11.9**
- `requirements.txt` içinde `pytest` (dev bağımlılığı) production listesinde
- `office_reminder.spec` `icon=None`, `resources/icon.ico` yok, ikon/tema kaynakları bundle'lanmıyor
- Depoda `build_test/`, `dist_test/`, `OfficeReminder.zip`, `.pytest_cache/`, `data/` commit'lenmiş; `.gitignore` yok

### P2-10. Runtime dizin yapısı kafa karıştırıcı
`get_runtime_root()` dev modda `<proje>/data`, `get_data_dir()` ise `<proje>/data/data` → `data/data/office_reminder.db`. Ayrıca kökte eski şemalı `data/office_reminder.db` (migration 007/008 uygulanmamış) duruyor.

### P2-11. Tray "Çıkış" tam kapanmayabilir
`_quit_app()` `qt_app.quit()` çağırıyor ama `main_window` gizliyken `setQuitOnLastWindowClosed(False)` olduğu için event loop'un temiz kapandığını garanti eden bir yol yok; `SingleInstanceGuard` unlock ediliyor ama tray ikonu explicit `hide()` edilmiyor (Windows'ta hayalet ikon).

### P2-12. Backup retention gün değil dosya sayısı
`_apply_retention()` `files[self.retention_days:]` ile **son 30 dosyayı** tutuyor, "son 30 gün"ü değil. `force=True` ile aynı gün birden çok yedek alınırsa pencere daralır.

---

## P3 — Polish

- Dashboard'da `Kategori` kolonu resmî eventler için hep `-` (official item'lara kategori set edilmiyor)
- `ReminderDialog` "Özel (ay)" tekrar seçeneği yalnızca ay destekliyor, `interval_days` backend'de var
- `_show_today` tray aksiyonu `dp.view_combo` gibi UI iç yapısına `hasattr` ile erişiyor
- Bildirim metni "TEST LTD. ŞTİ.\n14 gün kaldı • 17.09.2026" — insan diline uzak
- Tarih formatı her yerde `%d.%m.%Y`, uzun format ("16 Eylül 2026") hiç kullanılmıyor
- `README.md` çalıştırma dokümantasyonu `data/office_reminder.db` diyor, gerçek yol farklı

---

## Doğrulanan / sorun bulunmayan alanlar

| Konu | Sonuç |
|---|---|
| `main.py` var ve `office_reminder.spec` ile uyumlu | ✅ (önceki teslimatta eksikmiş, şimdi mevcut) |
| GİB 2026 seed: 476 raw / 476 normalized / 0 üretilmiş tarih | ✅ `unmapped_count=0`, `generated_count=0` |
| GİB lineage: `source_event_key = GIB_<gerçek id>`, provenance zorunlu | ✅ seed ve runtime sync aynı anahtar şemasını kullanıyor |
| `normal_due_date` immutable, `effective_due_date` revision ile değişiyor | ✅ |
| SGK 4/a `MONTHLY_1_END` = takip eden ayın son günü | ✅ `following_month_end()` doğru |
| SGK 4/a `MONTHLY_15_14` = period-end ayını takip eden ayın 14'ü | ✅ hesap doğru |
| SGK tatil verisi yoksa fail-closed (üretmez, `NEEDS_DATA` yazar) | ✅ |
| SGK motoru `GIB_MUHSGK` üretmiyor (çift guard) | ✅ |
| GİB "current year 0 item" şüpheli cevabı fail-closed | ✅ `gib_sync_service.py:275` |
| Dosya ekleri BLOB olarak saklanmıyor | ✅ |
| Backup SQLite backup API kullanıyor + integrity_check | ✅ |
| Single instance `QLockFile` | ✅ |
| Notification dedup unique index'leri (company NULL/NOT NULL ayrımı) | ✅ |

---


## Bölüm 2 — Çözümler

Aşağıdaki her satır, yukarıdaki bulguya karşılık gelen düzeltmeyi ve onu koruyan
doğrulamayı gösterir.

### P0

| # | Düzeltme | Doğrulama |
|---|---|---|
| **P0-1** | `CompanyObligationRepository.replace_profile()` — yükümlülük seti + KDV varyantları + SGK ücret dönemi **tek transaction** içinde yazılıyor. Servis girişi `CompanyService.save_obligation_profile()`. Diyalog artık yalnızca veri topluyor (`get_selection()`); yazmayı çağıran yapıyor. `profile_gaps()` eksik profili UI'da "Profil tamamlanmalı" rozetiyle görünür kılıyor. | `test_first_time_kdv_profile_survives_and_projects_twelve_events`, `test_kdv_without_variant_shows_nothing_and_is_reported_as_a_gap`, walkthrough 3–5 |
| **P0-2** | Yeni üretim hattı: `services/sgk_notice_parser.py` (gerçek markup), `services/sgk_notice_analyzer.py` (Türkçe tarih çıkarımı, uzatma yönü, semantik sınıflandırma, kapsam tespiti), `services/document_text.py` (QtPdf ile ek metni). `sgk_notice_service.py` baştan yazıldı; **hiçbir dal `source_notice_key`'e bakmıyor.** Alakasız duyuru `NO_RELEVANT_CHANGE`, bölgesel duyuru `NEEDS_REVIEW`. | `tests/test_sgk_production_pipeline.py` (15 test, gerçek snapshot'lar), canlı çalıştırma: 10 duyuru / 2 otomatik uygulama |
| **P0-3** | `discover_notices()` her sayfayı kendi turunda `fetch → validate → parse → dedup → watermark` olarak işliyor; site 0 tabanlı olduğu için ilk sayfa `?page=0`. Slug anahtarı kısaltma çakışmasına karşı digest ile korunuyor. | `test_every_page_is_parsed_not_only_the_last`, `test_real_list_page_parses_every_card` (10/10 kart) |

### P1

| # | Düzeltme | Doğrulama |
|---|---|---|
| **P1-1** | `OfficialUpdateService.announce_revisions()` gerçek `NotificationService` üzerinden "Resmî tarih değişti · 31 Mart → 7 Nisan · Kaynak: SGK" gösteriyor; yalnızca o yükümlülüğe tabi şirketlere, şirket başına bir kez. | `test_official_revision_is_actually_announced`, walkthrough 24 |
| **P1-2** | Adapter `bool` döndürüyor; `_mark_delivered` yalnızca `True` iken çağrılıyor. `notification_deliveries.delivery_status` eklendi. | `test_failed_notification_is_not_recorded_as_delivered`, `test_revision_announcement_is_not_recorded_when_it_cannot_be_shown` |
| **P1-3** | `NotificationService.notification_horizon_days()` ufku `notification_rules` içindeki en büyük aktif offset'ten hesaplıyor. | `test_ninety_day_offset_actually_fires` |
| **P1-4** | `notify_time` diyalogda girilebiliyor, kurala yazılıyor, `check_and_notify` o saatten önce göndermiyor. | `test_notify_time_defers_until_the_requested_hour` |
| **P1-5** | `SGK_NOTICES` ayrı source_code; her çalıştırma `official_sync_runs`'a, sonuç `official_source_state`'e yazılıyor. Ekranlar bu satırı okuyor, SGK 4/a kural takvimini değil. | `test_pipeline_is_idempotent_and_records_sync_state`, `test_failed_sync_records_error_state` |
| **P1-6** | `ReminderDialog`'a şirkete bağlı araç seçici eklendi; `DueItem` plaka taşıyor; repository `KEEP` sentinel'i ile araç bağlantısı temizlenebiliyor; başka şirketin aracı reddediliyor. Araçlar ekranı araca bağlı hatırlatmaları ve hızlı şablonları gösteriyor. | `test_vehicle_link_round_trips_through_the_service`, `test_vehicle_from_another_company_is_rejected`, walkthrough 6–9 |
| **P1-7** | `enabled_from` (görünürlük penceresi, varsayılan yılbaşı) ile `company_obligations.created_at` (gecikme tabanı) ayrıldı; migration 009 view'ı buna göre kurdu. | `test_new_company_does_not_inherit_a_backlog_of_overdue_dates` |
| **P1-8** | `SettingsService` eklendi; `OfficialUpdateService`'e `status_summary` / `list_revisions` / `list_pending_reviews` okumaları eklendi. UI'da SQL ve doğrudan repository erişimi kalmadı. | `grep -riE "execute\(|sqlite3|SELECT " ui/` → eşleşme yok |
| **P1-9** | Resmî kontrol `QThreadPool` üzerinde çalışıyor; UI yalnızca "Kontrol ediliyor…" durumunu gösteriyor, başarısızlık modal değil durum satırı. | Uygulama kodu + canlı çalıştırma |

### P2 / P3

| Konu | Düzeltme |
|---|---|
| P2-1 UI | Sol gezinme rayı + `QStackedWidget`; `ui/theme.py` tek token katmanı (açık + koyu palet); `ui/icons.py` kendi SVG ikon seti; `ui/widgets.py` (Card, StatCard, Badge, EmptyState, TableStack); `ui/shell.py` (Sidebar, PageHeader, Page, FilterBar); `ui/dialogs/base.py` bölümlü form, sabit alt bar, alan içi doğrulama. Inline renk kalmadı. |
| P2-2 istisnalar | Kalan `except` blokları ya dar tipli, ya loglu, ya da neden sessiz olduğu yorumlu. |
| P2-3 migration | Her migration + `applied_migrations` satırı tek `BEGIN/COMMIT` içinde; hata hâlinde rollback, `MigrationError` ile anlaşılır mesaj. |
| P2-4 entity | Başlık ve gövde `html.unescape` ediliyor, kelime ortasından kesilmiyor. |
| P2-5 kapsam | `detect_scope()` önce ulusal ibareye bakıyor; şehir adı tek başına bölgesel damgası vermiyor. |
| P2-6 gürültü | Alakasız duyurular `NO_RELEVANT_CHANGE`; "inceleme bekliyor" sayacı gerçek. |
| P2-7 alt sınır | `list_due(include_overdue=True)` ve `list_overdue()` artık `DEFAULT_OVERDUE_LOOKBACK_DAYS` ile sınırlı. |
| P2-8 ölü kod | `_notify_sgk_changes`, `update_with_company_clear`, boş döngüler, `models/`, `app/constants.py`, yüklenmeyen `dark.qss` kaldırıldı. |
| P2-9 paket | `requires-python >= 3.11`, sürüm 1.0.0, `.gitignore`, spec'te ikon + QtSvg/QtPdf + gereksiz Qt modülleri hariç. |
| P2-10 yollar | Ayarlar ekranı gerçek yolları gösteriyor; `--selftest` bunları raporluyor. |
| P2-11 çıkış | `quit()` tray ikonunu gizliyor, kilidi bırakıyor, pencere durumunu kaydediyor. |
| P2-12 yedek | Saklama ayardan geliyor, silinemeyen dosya loglanıyor, her yedek `integrity_check` ile doğrulanıyor. |
| P3 | Resmî satırlarda dönem etiketi; insan diline yakın bildirim metni; uzun tarih biçimi (`16 Eylül 2026`); plaka başlıkta tekrar etmiyor; boş durumlar; tooltip'ler; "Tekrar" kolonu kategori hücresine katlandı. |

### Denetim sırasında ek olarak bulunanlar

Bunlar ilk listede yoktu; gerçek sayfalar incelenirken ortaya çıktı.

| Bulgu | Düzeltme |
|---|---|
| **SGK detay parser'ı gerçek sayfayla hiç eşleşmiyordu.** `announcement-content` sınıfı detay sayfasında yok; gövde hiçbir zaman okunamıyordu. Runtime DB'deki 5 duyurunun hepsinin gövdesi boştu. | Parser gerçek markup'a göre yazıldı (`announcement-detail-title/date`, `<hr class="border-gray-300">` sonrası gövde, `/Download/DownloadFile` ekleri) ve gerçek snapshot'larla test edildi. |
| **31.03.2026 duyurusunun gövdesi boş; metin yalnızca PDF ekinde.** Ek okunmadan bu duyuru asla uygulanamazdı. | `services/document_text.py` — QtPdf ile metin çıkarımı (yeni bağımlılık yok; `Qt6Pdf` zaten paketleniyor). Metin okunamazsa `NEEDS_REVIEW`. |
| **Sayfalama parametresi 1 tabanlı kullanılıyordu**, yani gerçekte ikinci sayfadan başlanıyordu. | 0 tabanlı; ilk sayfa `?page=0`. |
| **`main.py` Qt'ye kendi bayraklarını geçiriyordu.** | Bayraklar `sys.argv`'den ayıklanıyor; `--selftest` ve `--version` eklendi. |
| **Paketlenmiş build'in doğrulanabilir yolu yoktu.** | `app/selftest.py`; rapor konsola ve `%LOCALAPPDATA%\OfficeReminder\selftest.txt` dosyasına yazılıyor. |
| **Uygulama ikonu yoktu** (`icon=None`, `resources/icon.ico` mevcut değil). | `ui/icons.app_icon()` ile üretilen vektör ikon; `tools/make_icon.py` bunu `resources/icon.ico`'ya yazıyor; pencere, tepsi ve exe aynı görseli kullanıyor. |

---

## Doğrulama özeti

| Kontrol | Sonuç |
|---|---|
| `pytest -q` | **136 passed** |
| Sıfırdan migration (001→010) | 10 uygulandı; ikinci çalıştırma no-op |
| `PRAGMA integrity_check` | ok |
| `PRAGMA foreign_key_check` | 0 ihlal |
| GİB seed | 476 raw / 476 normalized / **0 üretilmiş tarih** |
| Canlı GİB sync | `UNCHANGED`, 476 item — paket takvimi canlı kaynakla birebir |
| Canlı SGK sync | 10 duyuru; 2 otomatik uygulandı; **`GIB_MUHSGK` revision = 0** |
| Kabul senaryosu (25 adım) | **25/25** |
| PyInstaller temiz build | başarılı, 121 MB, runtime verisi paketlenmedi |
| Paketli `--selftest` | EXIT=0 |
| Paketli GUI `--background` | "Startup complete"; yalnızca `%LOCALAPPDATA%` altına yazdı |
| UI 1280×720 / 1920×1080 / %125 / %150 | Yatay taşma ve kırpma yok |

---

## Bilinen sınırlamalar

1. **Tatil verisi 2026–2028'i kapsıyor; SGK üretimi 2027'de biter.**
   Bir dönemin vadesi ertesi yılın ocak/şubat ayına düşebildiği için
   `generate_and_import(year)` hem `year` hem `year + 1` tatillerini ister ve
   biri yoksa **o yılın tamamını** üretmez (yalnız aralık dönemini değil).
   Tatil tablosu 2028'de bittiğinden üretilebilen son yıl **2027**'dir; 2028
   çağrısı 0 kayıt döndürür ve `SGK_4A_2029` satırına `NEEDS_DATA` yazar —
   tarih uydurulmaz. Uygulamada asıl son tarih bu: 2028 takvimi Aralık
   2027'de üretilmeye çalışılacağı için **2029 resmî tatilleri o tarihten
   önce bir migration ile eklenmelidir.** Sınır `tests/test_sgk_calendar.py
   ::test_sgk_generation_stops_where_the_holiday_data_stops` ile sabitlendi.
   Not: 2029 şubatında Ramazan Bayramı'nın 14 Şubat vadesini etkileme
   ihtimali var; tarihler Diyanet'in resmî ilanından alınmalı, hesapla
   türetilmemelidir.
2. **Paketle gelen GİB takvimi 2026 yılınadır.** Diğer yıllar yalnızca çevrimiçi
   sync ile gelir; internet yoksa o yıl için resmî tarih üretilmez — tahmin
   yapılmaz.
3. **SGK duyuruları yalnızca "Sigorta Primleri Genel Müdürlüğü" listesinden**
   taranır. Başka bir birimin yayımladığı süre uzatımı görülmez.
4. **PDF metni yalnızca metin katmanı olan dosyalardan** okunur; taranmış
   (görüntü) PDF için OCR yoktur, duyuru `NEEDS_REVIEW` olur.
5. **Yedekten geri yükleme elle yapılır** (`RELEASE_CHECKLIST.md` → Geri alma).
   Uygulama içinde "restore" ekranı yoktur.
6. **Dosya eki eklendi (1.1).** Manuel hatırlatmaya PDF/görsel/Office belgesi
   iliştirilir; kopya çalışma klasörüne alınır, çalıştırılabilir dosya
   reddedilir, üst sınır 25 MB. Karar ve gerekçe: `PLAN.md` § 8.

7. **Aylık takvim ekranı eklendi (1.1).** Altı haftalık ızgara, günlük yük ve
   resmî tatil işaretleri; `PLAN.md` § 7.
8. **Bildirim iki kanaldan gider.** Uygulama içi kutu garantilidir; Windows
   bildirimi Qt tepsi balonudur (10/11'de gerçek sistem bildirimi olarak
   görünür) ve `windows-toasts` kuruluysa native toast kullanılır — zorunlu
   bağımlılık değildir. "Rahatsız Etmeyin" açıkken sistem bildirimi
   görünmeyebilir; bildirim kutuda ve tepsi rozetinde durmaya devam eder.
9. **Kod imzalama yapılmamıştır**; ilk çalıştırmada SmartScreen uyarısı çıkabilir.
11. **Dosya ekleri yedeğe dahil değildir.** Yedekleme yalnız `office_reminder.db`
    dosyasını kopyalar ve doğrular; ekler `%LOCALAPPDATA%\OfficeReminder    attachments\` altında durur. Veritabanı geri yüklendiğinde ek satırları
    geri gelir ama dosyalar o klasörden silinmişse "eksik dosya" olarak
    görünür. Ekleri de korumak için o klasörün ayrıca yedeklenmesi gerekir.

10. **Manuel tekrar "aynı gün, ay kısaysa kırpılır" mantığıyla ilerler.**
    31 Ocak vadeli aylık bir hatırlatma tamamlandığında sonraki vade 28 Şubat
    olur ve zincir 28'inden devam eder (ay sonuna geri dönmez). Davranış
    belirlenimseldir ve yalnızca kullanıcının kendi eklediği hatırlatmaları
    etkiler; GİB/SGK resmî tarihleri bu yoldan geçmez.

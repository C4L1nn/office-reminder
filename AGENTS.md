# AGENTS.md

Bu depo Python + PySide6 tabanlı Windows Office Reminder uygulamasıdır.

## Önce oku

1. `PLAN.md` — ürün kararları
2. `FINAL_AUDIT.md` — en son teknik denetim ve neyin neden böyle yapıldığı
3. `database/migrations/001_initial.sql` — şemanın temeli
4. `app/application.py` — her şeyin birbirine bağlandığı yer

## Mimari

```
UI → Service → Repository → SQLite
```

- UI katmanında **SQL yok** ve repository'lere doğrudan erişim yok. Her ekran
  bir service ile konuşur (`SettingsService`, `CompanyService`,
  `ReminderService`, `OfficialUpdateService`).
- Sunum biçimlendirmesi (tarih, kategori, "3 gün kaldı") `services/formatting.py`
  içindedir; bildirim metni ile tablo hücresi aynı kaynaktan beslenir.
- Renkler, boşluklar ve tipografi yalnızca `ui/theme.py` içindedir. Widget'lar
  objectName / dynamic property kullanır, inline `setStyleSheet` yazmaz.

## Değişmez kurallar

- Vergi ve standart SGK tarihleri kullanıcıya elle girdirilmez.
- Resmî kayıtlar `official_calendar_events` içinde globaldir; şirket bazlı
  tamamlama `completion_records` içindedir.
- `normal_due_date` değişmez; resmî uzatma yalnızca `effective_due_date`'i
  değiştirir ve `official_calendar_revisions` içine yazılır.
- GİB/SGK verisi provenance olmadan DB'ye yazılmaz.
- Dosya ekleri SQLite BLOB olarak saklanmaz.
- Her schema değişikliği **yeni** bir migration dosyasıdır; yayımlanmış
  migration düzenlenmez.
- Bildirim iki kanaldan gider ve teslim defteri **kanal bazlıdır**:
  `IN_APP` garantili kanaldır (uygulama içi kutu — işletim sistemi susturamaz),
  `WINDOWS` en iyi çabadır. Bir kanal, gerçekten teslim ettiğini bildirmeden
  o kanal için `notification_deliveries` satırı yazılmaz; böylece bastırılmış
  bir toast kutuyu ikizlemeden yeniden denenir.
- Uygulama internet yokken mevcut SQLite verisiyle tam çalışır; başarısız
  resmî kontrol modal değil, durum satırıdır.
- Resmî kaynak işleme **fail-closed**'dır: şüpheli veri otomatik uygulanmaz,
  `NEEDS_REVIEW` olur.

## Resmî kaynak işlemenin kuralı

`services/sgk_notice_analyzer.py` duyurunun **metnine** bakar. Hiçbir iş kuralı
bir duyuru kimliğine (`source_notice_key`) bağlanmaz — fixture ID'si üzerinden
karar veren kod kabul edilmez. Testler `tests/fixtures/sgk/` altındaki gerçek
sayfa snapshot'larıyla çalışır.

`GIB_MUHSGK` tarihleri GİB kaynaklıdır. Bir SGK duyurusunda "Sigorta
Bildirimleri" geçmesi bu event'i **değiştirmez**; bulgu `NEEDS_REVIEW` olarak
kaydedilir.

## Kod stili

- Python 3.11+
- type hints, `pathlib`, gerektiğinde `dataclass`
- küçük, test edilebilir service fonksiyonları
- SQL yalnızca repository katmanında
- UI'da blocking network işlemi yok (`services/sync_worker.py` kullanılır)
- `except Exception: pass` yazma. Ya dar bir istisna yakala, ya logla, ya da
  neden sessiz kalmanın doğru olduğunu bir yorumla açıkla.

## Test

```bash
pytest -q
```

Yeni iş kuralı için test zorunlu. Beklenen minimum kapsam:

- migration idempotence + `integrity_check` / `foreign_key_check`
- repository CRUD
- tarih ve bildirim hesapları (offset, notify_time, tekrar)
- deduplication (bildirim ve revision), kanal bazlı teslim
- official / manual ayrımı ve eligibility
- SGK production parser'ı gerçek snapshot'lar üzerinde

## Sürüm

`app/version.py` tek kaynaktır; `pyproject.toml` ile senkron tutulur.

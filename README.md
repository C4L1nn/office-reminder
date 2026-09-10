# Office Reminder

Windows ofis kullanımı için yerel, internetsiz de çalışan PySide6 + SQLite
yükümlülük ve hatırlatma uygulaması.

Şirketlerin **KDV / SGK / diğer resmî yükümlülük** tarihleri GİB ve SGK resmî
kaynaklarından gelir — personel bu tarihleri elle girmez. Araç muayenesi,
sigorta, kasko, kira, sözleşme gibi şirkete özgü tarihler kullanıcı tarafından
eklenir. Uygulama sistem tepsisinde yaşar, Windows bildirimi gönderir ve
verisini günlük yedekler.

İsteğe bağlı **mini sayaç**, en acil işi diğer pencerelerin üstünde duran
küçük bir kartta gösterir: tıklayınca ana pencere açılır, sürükleyerek
taşınır. Varsayılan olarak kapalıdır; Ayarlar ekranından veya tepsi
menüsünden açılır.

## Hızlı başlangıç

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

İlk açılışta veritabanı oluşturulur, migration'lar uygulanır, paketle gelen
GİB 2026 takvimi (476 gerçek kayıt) yüklenir ve SGK 4/a vadeleri kural
motoruyla üretilir.

### Çalıştırma seçenekleri

| Komut | Ne yapar |
|---|---|
| `python main.py` | Normal başlatır |
| `python main.py --background` | Pencereyi açmadan tepside başlatır (Windows açılışı için) |
| `python main.py --selftest` | Depolama ve paketlenmiş kaynakları doğrular, çıkar (0 = sağlam) |
| `python main.py --version` | Sürümü yazar |

## Veriler nerede?

Uygulama **kendi klasörüne hiçbir şey yazmaz.**

| | Paketlenmiş (.exe) | Kaynaktan çalıştırma |
|---|---|---|
| Kök | `%LOCALAPPDATA%\OfficeReminder\` | `<proje>\data\` |
| Veritabanı | `…\data\office_reminder.db` | `…\data\office_reminder.db` |
| Yedekler | `…\backups\` | `…\backups\` |
| Günlükler | `…\logs\` | `…\logs\` |
| Resmî kaynak snapshot'ları | `…\data\official_sources\` | `…\data\official_sources\` |

`OFFICE_REMINDER_DATA_DIR` ortam değişkeni bu kökü değiştirir (testler ve
taşınabilir kurulum için).

## Test

```bash
pytest -q
```

Testler ağa çıkmaz. SGK production parser'ı, `tests/fixtures/sgk/` altındaki
**gerçek sgk.gov.tr sayfa ve PDF snapshot'larına** karşı çalıştırılır.

## Paketleme

```bash
python -m PyInstaller --noconfirm --clean office_reminder.spec
```

Çıktı: `dist/OfficeReminder/OfficeReminder.exe` (onedir, windowed).
Bundle yalnızca salt-okunur kaynakları içerir: migration'lar, GİB seed takvimi
ve ikon. Çalışma zamanı verisi paketlenmez.

Build sonrası doğrulama:

```bash
dist\OfficeReminder\OfficeReminder.exe --selftest
```

Rapor hem konsola hem `%LOCALAPPDATA%\OfficeReminder\selftest.txt` dosyasına
yazılır.

## Mimari

```
UI  →  Service  →  Repository  →  SQLite
```

UI katmanı SQL bilmez ve repository'lere doğrudan erişmez; her ekran bir
service ile konuşur. Ayrıntılar için `PLAN.md` ve `AGENTS.md`.

Sürüm notları ve yayın öncesi kontrol listesi: `RELEASE_CHECKLIST.md`.
Son teknik denetim: `FINAL_AUDIT.md`.

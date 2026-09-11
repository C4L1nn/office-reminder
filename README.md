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

## Güncelleme

Uygulama günde bir kez, ayrı bir public depodaki `latest.json` dosyasına bakar
ve yeni sürüm varsa pencerenin üstünde ince bir şerit gösterir. **Kurulum her
zaman kullanıcının onayıyla başlar**; şerit "Sonra" ile kapatılırsa o sürüm
için bir daha çıkmaz, sonraki sürümde yeniden görünür. Otomatik denetim
Ayarlar'dan kapatılabilir; tepsi menüsünde "Güncellemeleri denetle" her zaman
çalışır.

Sıra, her adımı geri dönülebilir bırakacak şekilde kurulu:

```
manifest → indir → sha256 doğrula → klasörü hazırla
→ yeni yapıyı kendi kum havuzunda --selftest'ten geçir
→ veritabanını yedekle → uygulamadan çık → takas → yeniden başlat
```

- **Özet tutmazsa hiçbir şey açılmaz.** HTTPS tek başına yeterli sayılmaz.
  Paket adresi de yalnızca bilinen sunuculardan olabilir.
- **Yeni sürüm kendini sınamadan kurulmaz.** Sınama kendi geçici veri
  klasöründe koşar, çünkü selftest migration uygular ve kullanıcı henüz
  güncellemeye razı olmadan gerçek şema değiştirilmemelidir.
- **Kurulumdan önce veritabanı yedeklenir.** Migration'lar tek yönlü; geri
  dönüş yolu `.old` klasörü değil, o yedektir.
- **Eski klasör silinmez, `.old` olarak bekler** ve ancak yeni sürüm bir kez
  açıldıktan sonra kaldırılır.
- **Sonuç bir nota yazılır.** Kurulum uygulama kapalıyken koştuğu için
  başarısız bir güncelleme aksi hâlde sessiz kalırdı; not bir sonraki açılışta
  kullanıcıya gösterilir. Ayrıntısı güncelleme klasöründeki `update.log`
  dosyasında.

Kurulumu ayrı bir yardımcı program değil, **hazırlanan klasörün kendi exe'si**
yapar (`--apply-update`). O klasör hedefin dışındadır ve hedef o sırada
çalışmadığı için kilit sorunu doğmaz; böylece paketle taşınması ve ana
programla senkron tutulması gereken ikinci bir ikili olmuyor.

Tipik güncelleme **~3 MB**: paketteki 179 dosyanın yalnızca birkaçı sürümler
arasında değişir, gerisi bit bit aynı kalır ve indirilmez.

### Sürüm yayınlama

```bash
.venv/Scripts/python tools/make_release.py --dist dist/OfficeReminder --out dist/release --previous dist/OfficeReminder-1.0.0 --previous-version 1.0.0 --notes "..."
```

Tam paketi, fark paketini ve `latest.json`'ı aynı ölçümden üretir ve manifesti
uygulamanın kendi doğrulayıcısından geçirir. Üç dosya da sürüm deposuna
yüklenir; `latest.json` deponun kökünde durmalıdır.

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

**Derleme mutlaka temiz bir sanal ortamda yapılmalıdır.** PyInstaller, ortamda
ne bulursa import zincirlerinden içeri çeker; sistem Python'unda derlenen
1.0.0 paketi bu yüzden `numpy` + OpenBLAS, `PIL`'in AVIF kodeki ve pywin32'nin
MFC katmanını taşıyordu — hiçbiri bu uygulamada import edilmiyor.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean office_reminder.spec
```

Çıktı: `dist/OfficeReminder/OfficeReminder.exe` (onedir, windowed).
Bundle yalnızca salt-okunur kaynakları içerir: migration'lar, GİB seed takvimi
ve ikon. Çalışma zamanı verisi paketlenmez.

Temiz ortamda ölçülen boyutlar: klasör **109 MB**, ZIP **42,9 MB**, 179 dosya,
`OfficeReminder.exe` **3,2 MB**. Kod değişikliğinde paketin yalnızca iki
dosyası değişir (`OfficeReminder.exe` ve `_internal/base_library.zip`,
sıkıştırılmış toplam ~3 MB); geri kalan 177 dosya sürümler arasında bit bit
aynı kalır.

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

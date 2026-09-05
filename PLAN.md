# Office Reminder — Uygulama Planı

## 1. Projenin amacı

Office Reminder, ofiste Windows üzerinde sürekli arka planda çalışan yerel bir PySide6 masaüstü uygulamasıdır.

Ana hedef: Şirketlerin vergi, SGK ve özel yükümlülüklerini tek yerde takip etmek; yaklaşan veya geciken işler için Windows bildirimi üretmek; personelin vergi/SGK tarihlerini elle girmesini önlemek.

Bu bir web uygulaması değildir. İlk sürüm tek bilgisayarda, internetsiz çalışabilen SQLite tabanlı masaüstü uygulamasıdır. İnternet yalnızca resmî takvim/güncelleme kontrolü gibi görevlerde kullanılır.

## 2. Ana ürün ilkeleri

1. Kullanıcı vergi tarihlerini elle girmez.
2. Kullanıcı standart SGK ödeme tarihlerini elle girmez.
3. 2026 GİB vergi takvimi uygulama paketine seed olarak eklenir.
4. SGK standart vadeleri kural motoruyla üretilir.
5. GİB/SGK yıl içi süre uzatmaları daha sonra resmî kaynaklardan güncelleme olarak uygulanabilir.
6. Araç muayenesi, kasko, kira, sözleşme vb. şirkete özgü tarihler kullanıcı tarafından manuel girilir.
7. Kullanıcı vergi/SGK için yalnızca şirketin tabi olduğu yükümlülükleri seçer.
8. Uygulama Windows açılışında başlayabilir, sistem tepsisinde çalışır ve pencere kapatıldığında varsayılan olarak arka planda kalır.
9. Aynı bildirim tekrar tekrar gönderilmez; gönderim logu tutulur.
10. Her otomatik yükümlülüğün kaynağı ve değişiklik geçmişi korunur.

## 3. Teknoloji kararı

- Python 3.12+
- PySide6
- SQLite 3
- sqlite3 standart kütüphane; ilk sürümde ORM yok
- QSystemTrayIcon
- QTimer
- QSettings sadece UI/istemci tercihleri için; iş verisi SQLite'ta
- PyInstaller ile Windows .exe paketleme
- pytest

## 4. Veri kaynakları

### GİB

GİB takvimi "built-in official calendar" olarak ele alınır.

Geliştirme aşamasında araç/script ile resmî 2026 takvimi alınır, normalize edilir ve `resources/seed/official_calendar_2026.json` içine yazılır. Uygulama ilk veritabanı oluşturulduğunda bu seed'i SQLite'a aktarır.

Kullanıcı arayüzünde "GİB takvimini indir" gibi bir işlem olmayacaktır.

İleride `OfficialCalendarSyncService`, resmî takvimde değişiklik olup olmadığını arka planda kontrol eder. Değişen tarih eski değeri silmez; revision/override geçmişine yazılır.

### SGK

SGK iki parçaya ayrılır:

1. Standart/hesaplanabilir yükümlülükler: `SgkRuleEngine` tarafından yıl için oluşturulur.
2. Özel süre uzatımları/mücbir sebep vb.: resmî duyuru güncellemesi olarak mevcut vadenin üzerine override uygulanır.

MUHSGK gibi GİB takviminde zaten bulunan yükümlülükler GİB event kaynağından gelir; aynı yükümlülük SGK motorunda ikinci kez üretilmemelidir.

## 5. Kayıt türleri

### Official

Program tarafından üretilen veya seed edilen kayıtlar:

- GİB vergi takvimi
- SGK standart vade kayıtları
- Resmî süre uzatmaları / tarih revizyonları

Bunlar kullanıcı tarafından doğrudan tarih değiştirilerek düzenlenmez. Gerekirse override/revision mantığı kullanılır.

### Manual

Kullanıcı tarafından oluşturulur:

- Araç muayenesi
- Trafik sigortası
- Kasko
- Kira
- Sözleşme
- Ruhsat
- Abonelik
- Özel ödeme
- Personel belgesi
- Serbest hatırlatma

## 6. Şirket yükümlülük profili

Kullanıcı şirket oluştururken veya düzenlerken ilgili yükümlülükleri işaretler.

Örnek:

- KDV
- Muhtasar ve Prim Hizmet Beyannamesi
- SGK 4/a prim
- Damga Vergisi
- Kurum Geçici Vergisi
- Kurumlar Vergisi
- e-Defter
- MTV

Uygulama, `company_obligations` ile şirketi `obligation_types` tablosundaki yükümlülük tanımlarına bağlar.

Bir şirket KDV'ye tabi ise dashboard'daki KDV kayıtları `official_calendar_events` ile otomatik eşleşir. Her ay için ayrı manuel reminder oluşturulmaz.

## 7. Ana ekranlar

### Dashboard

- Bugün
- Yaklaşan
- Geciken
- Bu ay
- Resmî / Manuel etiketi
- Şirket filtresi
- "Tamamlandı" aksiyonu

### Hatırlatmalar

- Tüm yükümlülükler
- Resmî
- Manuel
- Tamamlananlar
- Gecikenler

### Şirketler

- Şirket ekleme/düzenleme
- Aktif/pasif
- Yükümlülük profili

### Araçlar

- Plaka
- Şirket
- Marka/model (opsiyonel)
- Muayene
- Trafik sigortası
- Kasko
- Notlar

### Takvim — 1.1 (karar: 2026-09-04)

Aynı kayıtların aciliyete göre değil **tarihe göre** okunuşu. Burada kayıt
oluşturulmaz veya tamamlanmaz; bir güne tıklanınca o günün kayıtları yanda
listelenir, işlem yapmak yine Hatırlatmalar ekranının işidir.

- **Izgara:** Pazartesi başlangıçlı, her zaman **altı hafta** — ay değişince
  sayfanın boyu zıplamasın diye.
- **Gün hücresi:** gün numarası, en fazla üç kayıt çipi, sonrası "+N daha".
  Dört ve üzeri kaydı olan gün ayrıca renklendirilir; asıl aranan bilgi budur.
- **Resmî tatiller** ızgarada işaretlenir. Vadenin neden kaydığını görmek
  için gereklidir; veri `holidays_tr` tablosundan gelir.
- **Ay penceresi** `ReminderService.list_month()` ile alınır; bu da mevcut
  `list_due` sorgusunun üzerine ince bir pencere olduğundan listelerle
  ayrışamaz.

### Notlar — 1.1 (karar: 2026-09-04)

Düz bir metin sayfası değil, **yapışkan not tuvali**. Ofiste masaya
yapıştırılan sarı kâğıtların karşılığı: bir yükümlülük kaydı değil, serbest
karalama alanı.

- **Sayfa (board):** birden çok tuval. Her sayfanın adı var, sekmeyle geçilir.
- **Not:** tuvalde serbestçe sürüklenir, köşesinden boyutlandırılır. Konum,
  boyut ve üst-alt sırası (z) kalıcıdır.
- **Dizme:** serbest sürüklemenin yanında "yan yana", "alt alta" ve "kaskat"
  komutları; isteğe bağlı ızgaraya yapışma.
- **Sıralama:** öne getir / arkaya gönder.
- **Biçimlendirme:** not içinde zengin metin — kalın, italik, altı çizili,
  yazı tipi, punto, metin rengi, madde işareti. Seçime uygulanır.
- **Kâğıt rengi:** paletten seçilir. Renk veritabanına **palet anahtarı**
  olarak yazılır (`yellow`, `mint`, …), hex olarak değil; açık ve koyu tema
  aynı notu kendi paletiyle çizer.
- **Bağlantı yok:** notlar şirkete veya hatırlatmaya bağlanmaz (karar:
  2026-09-04). Bağımsız kalır; gerekirse sonradan eklenir.
- **Bildirim yok:** notun vadesi yoktur, bildirim üretmez. Hatırlatma
  gerekiyorsa manuel hatırlatma kullanılır.

- **Görsel yapıştırma:** panodaki ekran görüntüsü doğrudan nota yapıştırılır.
  Görsel base64 olarak HTML'e gömülmez; çalışma klasörüne PNG olarak yazılır
  ve nota `note-image:<ad>.png` özel şemasıyla referans verilir. Böylece
  veritabanı şişmez ve saklanan işaretleme makineye özgü mutlak yol taşımaz.
  Adı özet (sha256) olduğundan aynı görsel iki kez yapıştırılsa tek dosya olur;
  hiçbir notun göstermediği görseller not/sayfa silindiğinde temizlenir.

Teknik: `QGraphicsView` + `QGraphicsScene`; her not bir `QGraphicsObject` ve
gövdesi `QGraphicsProxyWidget` içindeki `QTextEdit`. Yazma sırasında her tuşta
değil, gecikmeli (debounce) kaydedilir. **Baskıda not metni sahneden değil
belgeden çizilir**: `QGraphicsScene.render()` gömülü editörü hedef aygıta göre
yeniden yerleştirip yüksekliğinin bir kısmına kırpıyor ve uzun notlar PDF'e
eksik giriyordu.

### Dışa aktarma, toplu işlem ve arama — 1.1 (karar: 2026-09-04)

- **Liste dışa aktarma:** Hatırlatmalar ekranındaki *filtrelenmiş* satırlar
  `.xlsx` (openpyxl) ve A4 PDF (QTextDocument) olarak yazılır. Ekranda görünen
  ne ise dosyaya giren odur; "hepsini aktar" sessizce yanlış belge üretir.
- **Not dışa aktarma:** Bir tuval sayfası, **ekrandaki yerleşimiyle** PDF
  olur; sahne olduğu gibi çizilir, belge biçimine dönüştürülmez. Tuval geniş
  ise sayfa yatay olur ve tuval bir sayfaya sığacak şekilde ölçeklenir.
  Çizim sırasında **açık** kâğıt paleti zorlanır — koyu temadaki not beyaz
  kâğıda mürekkep bloğu olarak çıkardı — ve metin imleci ile kaydırma
  çubukları kapatılır, yoksa PDF'e dikey çubuk olarak basılıyorlardı.
- **Toplu tamamlama:** Tabloda çoklu seçim, onay, ardından kayıt başına mevcut
  atomik `complete()` çağrısı. Tekrarlı kayıt sonraki vadesini üretmeye devam
  eder; bir kaydın hatası diğerlerini geri almaz.
- **Genel arama (Ctrl+K):** Şirket, araç, hatırlatma ve not tek kutuda. Bir
  türün sorgusu hata verirse yalnız o tür düşer, liste boşalmaz.

### Küçük hızlandırmalar — 1.1 (karar: 2026-09-04)

Günde onlarca kez tekrarlanan hareketleri kısaltan dokunuşlar:

- **Yazarak tarih:** takvimden tıklamak yerine "yarın", "3 gün sonra",
  "ayın son günü", "15 ekim", "gelecek salı". Ayrıştırıcı emin olmadığında
  **hiçbir şey yazmaz** ve ne anladığını ekrana geri yazar; yanlış aya düşen
  sessiz bir tarih, hiç tarih olmamasından kötüdür.
- **Nottan hatırlatma:** yapışkan nota sağ tık; ilk satır başlık, kalanı not
  gövdesi, metinde geçen tarih vade olarak önerilir.
- **Panodan hatırlatma (Ctrl+Shift+V):** e-postadan kopyalanan satır aynı
  şekilde işlenir. Hiçbiri kendiliğinden kaydetmez; kullanıcı onaylar.
- **İş günü:** vade ipucunda takvim günü yanında iş günü de yazar. Araya
  bayram girdiğinde işi belirleyen sayı budur.
- **Satır kopyalama (Ctrl+C):** "Şirket · Yükümlülük · Tarih" panoya.
- **Sürükle-bırak:** dosya doğrudan manuel hatırlatma satırına ya da nota.
  Resmî GİB/SGK satırı evrak almaz; o kayıt bizim değildir.

### Ayarlar

- Windows ile başlat
- Arka planda başlat
- Bildirimler açık/kapalı
- Bildirim kontrol aralığı
- Yedekleme
- Veri klasörünü aç

## 8. Manuel hatırlatma akışı

`+ Yeni Hatırlatma`

Temel alanlar:

- Başlık
- Şirket (opsiyonel)
- Kategori
- Son tarih
- Saat (opsiyonel)
- Tekrar: yok / aylık / 3 aylık / 6 aylık / yıllık / özel
- Hatırlatma offsetleri: varsayılan 14, 7, 3, 1, 0 gün
- Not
- ~~Dosya eki~~ → **Deferred post-1.0** (aşağıya bakınız)

Kategoriye göre ileride ek alanlar açılabilir.

### Dosya eki — 1.1 (karar: 2026-09-04)

Manuel hatırlatmaya PDF, görsel, Office belgesi veya metin dosyası eklenir.

- **Kopya alınır, bağlantı tutulmaz.** Dosya çalışma klasörüne kopyalanır;
  Downloads'taki ya da USB'deki özgün dosya kaybolduğunda ek de kaybolurdu.
- **Her kayıt kendi kopyasına sahiptir** (`attachments/<tür>/<id>/`). Aynı
  belge iki kayda eklenirse iki kez saklanır; birkaç kilobayta karşılık bir
  kaydı silmenin diğerinin dosyasını alıp götürmeyeceği garantisi alınır.
- **Dosya adı özet (sha256) ile verilir**, aynı adlı iki dosya çakışmaz;
  kullanıcının tanıdığı ad satırda saklanır.
- **Sınırlar:** en fazla 25 MB, boş dosya kabul edilmez ve **çalıştırılabilir
  dosya reddedilir** — uygulama makineler arası program taşımanın yolu
  olmamalıdır.
- Hatırlatma silinince ekleri de silinir; dosyalar veritabanının dışında
  olduğundan hiçbir şey onları kendiliğinden temizlemez.
- Listede ataç simgesi, eki olan kaydı gösterir (tablo başına tek sorgu).
- **Yedekleme kapsam dışı:** yedek yalnız `.db` dosyasını kopyalar, ekler
  yedeğe girmez. Bkz. `FINAL_AUDIT.md` sınırlama 11.

## 9. Bildirim motoru

Varsayılan bildirim eşikleri:

- 14 gün önce
- 7 gün önce
- 3 gün önce
- 1 gün önce
- Son gün
- Geciktiyse günlük bir kez (ayar yapılabilir)

Aynı olay + aynı eşik için bir kez bildirim gönderilir.

`notification_deliveries` tablosunda unique constraint kullanılmalıdır.

### İki kanal (1.0)

Windows'ta "Rahatsız Etmeyin / Odak Yardımı" yaygın kullanıldığı ve sistem
bildirimini sessizce yuttuğu için bildirim iki kanaldan gider:

1. **Uygulama içi kutu (`IN_APP`) — garantili.** Her bildirim `app_notifications`
   tablosuna yazılır, okunana kadar kenar çubuğunda ve tepsi simgesinde sayaç
   olarak durur. Pencere açıkken ayrıca sağ altta kısa bir şerit gösterilir.
2. **Windows bildirimi (`WINDOWS`) — en iyi çaba.** Gösterilemezse bir sonraki
   turda yeniden denenir.

Teslim defteri kanal bazlıdır: bastırılan bir toast tekrar denenirken kutuya
ikinci kayıt düşmez.

Örnek anahtar:

`(source_kind, source_id, company_id, notification_key)`

## 10. Tamamlama modeli

Resmî takvim eventi globaldir. "KDV 28 Eylül" eventini üç şirket kullanabilir. Bu nedenle resmî eventin kendi `completed` alanı olmaz.

Tamamlama `completion_records` tablosunda şirket + kaynak event bazında tutulur.

Örnek:

- company_id = 7
- source_kind = official_calendar
- source_id = 101
- completed_at = ...
- status = paid

Bu model aynı resmî tarihin farklı şirketlerde bağımsız kapanmasını sağlar.

## 11. Veritabanı tabloları

### schema_meta
Migration sürümü.

### companies
Şirketler.

### vehicles
Şirket araçları.

### obligation_types
KDV, SGK_4A_PREMIUM vb. yükümlülük tanımları.

### company_obligations
Şirketin aktif yükümlülükleri.

### official_calendar_events
GİB/SGK tarafından belirlenen global takvim olayları.

### official_calendar_revisions
Bir resmî eventte sonradan yapılan tarih değişikliği/override geçmişi.

### manual_reminders
Kullanıcı hatırlatmaları.

### notification_rules
Reminder başına özel notification offsetleri. Kayıt yoksa varsayılan offsetler kullanılır.

### notification_deliveries
Gönderilmiş bildirimlerin deduplication logu.

### completion_records
Şirket-event veya manual reminder tamamlanma geçmişi.

### attachments
Dosya yol referansları. Dosya binary olarak DB'ye gömülmez; satır yalnız
kopyanın yerini, kullanıcının tanıdığı adı ve sha256 özetini tutar.

### official_source_state
Resmî veri kaynaklarının son kontrol/seed/sync durumu.

### app_notifications
Uygulama içi bildirim kutusu. Her bildirim buraya düşer ve okunana kadar
okunmamış sayılır; Windows bildirimi bastırılsa bile kayıt kaybolmaz.

### note_boards / notes
Yapışkan not tuvalleri ve notlar. `notes` satırı metnin yanında konum (`x`,
`y`), boyut (`width`, `height`), üst-alt sırası (`z`) ve kâğıt rengini palet
anahtarı olarak tutar. Zengin metin `content_html` alanında; `content_text`
yalnızca arama içindir. Resmî veya manuel hatırlatma değildir, vade taşımaz.

### app_settings
Uygulama ayarları. Tek kaynak burasıdır; `QSettings` yalnızca pencere
geometrisi gibi istemci tercihleri için kullanılır.

### official_sync_runs
Her resmî kaynak kontrolünün denetim kaydı (başlangıç, bitiş, durum, hata).

### official_notices / official_notice_findings
Alınan resmî duyurular ve her duyurudan çıkarılan tarih bulguları. Bir duyuru
birden çok bulgu üretebilir; bulgular ayrı ayrı uygulanır veya incelemeye
düşer.

## 12. Kaynak katmanları

Akış:

UI -> Service -> Repository -> SQLite

UI bileşenleri doğrudan SQL çalıştırmaz.

`database/connection.py`
- bağlantı açma
- foreign keys
- WAL
- row_factory

`database/repositories/*`
- SQL erişimi

`services/*`
- iş kuralları

`ui/*`
- yalnızca sunum ve kullanıcı etkileşimi

## 13. İlk MVP teslim kriteri

MVP aşağıdaki uçtan uca akışı çalıştırmalıdır:

1. Uygulama açılır.
2. SQLite otomatik oluşturulur ve migration uygulanır.
3. Seed obligation type kayıtları yüklenir.
4. Şirket eklenebilir.
5. Şirkete KDV/SGK yükümlülüğü atanabilir.
6. Manuel hatırlatma eklenebilir.
7. Dashboard yaklaşan manuel ve resmî işleri gösterebilir.
8. QSystemTrayIcon çalışır.
9. Hatırlatma kontrol servisi due kayıtları bulabilir.
10. Aynı eşik bildirimi ikinci kez gönderilmez.
11. İş tamamlandı işaretlenebilir.
12. Uygulama yeniden açıldığında kayıtlar korunur.

## 14. Geliştirme fazları

### Faz 0 — İskelet (bu paket)

- klasör yapısı
- migration sistemi
- temel schema
- PySide6 application bootstrap
- main window
- dashboard placeholder
- tray
- temel repository/service örnekleri
- test altyapısı

### Faz 1 — Manuel hatırlatmalar

- CRUD
- quick add
- recurrence
- notification rules
- completion
- dashboard query

### Faz 2 — Şirket ve yükümlülük profili

- companies CRUD
- obligation type seed
- company obligations UI
- official event -> company eşleştirme

### Faz 3 — GİB 2026 seed

- resmî 2026 takvimi geliştirme scripti ile çek
- normalize et
- kaynak bilgisi ekle
- `official_calendar_2026.json` üret
- startup seed importer
- veri doğrulama testleri

### Faz 4 — SGK rule engine

- 4/a prim standart takvimi
- tatil/iş günü handling
- duplication guard
- GİB'ten gelen MUHSGK ile çakışma engeli

### Faz 5 — Windows deneyimi

- native toast gerekiyorsa Qt tray notification yerine Windows toast adapter
- autostart
- minimize to tray
- daily backup
- PyInstaller build

### Faz 6 — Resmî güncelleme kontrolü

- GİB değişiklik kontrolü
- SGK duyuru kontrolü
- revision/override
- kullanıcıya "resmî tarih değişti" bildirimi

### Faz 7 — Release Candidate (1.0.0)

Bu faz yeni özellik eklemez; mevcut ürünü güvenilir ve kullanılabilir hâle
getirir. Ayrıntılı bulgu listesi `FINAL_AUDIT.md`, doğrulama listesi
`RELEASE_CHECKLIST.md`.

**Domain**

- Şirket yükümlülük seti ve profili (KDV varyantları, SGK ücret dönemi) tek
  atomik transaction'da yazılır. Profil artık ilk kayıtta kaybolamaz.
- SGK duyuru işleme gerçek üretim hattına taşındı: liste → detay → gövde veya
  PDF eki → semantik analiz → bulgu → revision. Hiçbir iş kuralı duyuru
  kimliğine bağlı değildir.
- Sayfalama her sayfayı kendi turunda parse eder; watermark ile durur.
- `SGK_NOTICES` ayrı bir kaynak olarak `official_source_state` ve
  `official_sync_runs` içinde izlenir.
- Bildirim yalnızca gerçekten gösterildiğinde teslim edilmiş sayılır.
- Bildirim ufku, tanımlı kurallardaki en büyük offset'ten hesaplanır;
  `notify_time` uygulanır.
- Yükümlülük penceresi: `enabled_from` görünürlüğü, `created_at` gecikme
  hesabını sınırlar. Yeni şirket geçmiş yılın tamamını "geciken" göstermez.

**Arayüz**

- Üst sekme barı yerine sol gezinme rayı ve `QStackedWidget`.
- Tek merkezî tasarım katmanı (`ui/theme.py`): renk, boşluk, tipografi
  token'ları; açık ve koyu palet; widget'larda inline renk yok.
- Kendi SVG ikon setimiz (`ui/icons.py`), emoji yok, offline çalışır.
- Şirketler ve Araçlar ekranları liste + detay düzenine geçti; yükümlülük
  profili ve araç hatırlatmaları detay panelinde görünür.
- Yeni "Resmî Güncellemeler" ekranı: kaynak durumu, inceleme bekleyen
  duyurular, uygulanan tarih değişikliklerinin geçmişi.
- Diyaloglar bölümlü form + sabit alt bar + alan içi doğrulama.
- Her liste için boş durum metni ve aksiyonu.

**Windows**

- `%LOCALAPPDATA%\OfficeReminder\` altına yazar; exe yanına hiçbir şey yazmaz.
- Resmî kontrol Qt thread'inde çalışmaz; başarısızlık modal değil durum satırıdır.
- `--selftest` ile paketlenmiş build doğrulanabilir.

## 15. Kesin tasarım kararları

- Web backend yok.
- İlk sürümde cloud DB yok.
- ORM yok.
- Vergi tarihleri personel tarafından girilmez.
- SGK standart tarihleri personel tarafından girilmez.
- Resmî event global; şirket tamamlaması ayrı tabloda.
- Dosyalar DB blob olarak saklanmaz.
- UI SQL bilmez.
- Migration olmadan schema değişikliği yapılmaz.
- Bir migration yayımlandıktan sonra değiştirilmez; yeni migration eklenir.
- Resmî kaynak verisi source/provenance bilgisi olmadan DB'ye yazılmaz.

## 16. Ajanlar için çalışma kuralı

Bir sonraki ajan işe başlamadan önce `PLAN.md`, `AGENTS.md` ve `database/migrations/001_initial.sql` dosyalarını okumalıdır.

Her değişiklikte:

1. Mevcut migration'ı değiştirmek yerine yeni migration yaz.
2. UI'da SQL sorgusu yazma.
3. Resmî kayıtları manuel kayıtlarla birleştirip source bilgisini kaybetme.
4. Bildirim deduplication kuralını bozma.
5. Uygulama internetsizken mevcut local veriyle çalışmaya devam etmeli.
6. GİB/SGK parser veya sync kodunda fail-closed davran: şüpheli veriyi otomatik overwrite etme.
7. Yeni iş kuralı için test ekle.


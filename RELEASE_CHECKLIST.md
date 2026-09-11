# RELEASE_CHECKLIST.md — Office Reminder 1.0.0

Bu liste her yayın öncesi baştan sona çalıştırılır. Her satırın karşısında
**nasıl doğrulandığı** yazılıdır; "çalışıyor gibi görünüyor" kabul edilmez.

Son çalıştırma: **2026-09-03** · Ortam: Windows 11, Python 3.11.9, PySide6 6.11.0

---

## 1. Kod ve testler

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 1.1 | Tüm testler geçiyor | `pytest -q` | ✅ **457 passed** |
| 1.2 | Testler ağa çıkmıyor | SGK/GİB testleri snapshot + enjekte edilmiş fetcher kullanır | ✅ |
| 1.3 | Derleme hatası yok | `python -m compileall app database services ui tools main.py` | ✅ |
| 1.4 | UI'da SQL yok | `grep -riE "execute\(|sqlite3|SELECT " ui/` | ✅ eşleşme yok |
| 1.5 | Sessiz `except: pass` yok | Kalanlar dar istisna veya gerekçeli yorum içeriyor | ✅ |
| 1.6 | TODO / FIXME / stub yok | Kaynak taraması | ✅ |
| 1.7 | Sürüm senkron | `app/version.py` == `pyproject.toml` | ✅ 1.1.0 |

## 2. Veritabanı

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 2.1 | Sıfırdan migration | Boş dosyaya 001→011 | ✅ 11 migration |
| 2.2 | Tekrar çalıştırma no-op | İkinci `run()` boş liste döner | ✅ |
| 2.3 | Migration atomik | Hata hâlinde rollback; `applied_migrations` ile aynı transaction | ✅ |
| 2.4 | `PRAGMA integrity_check` | selftest | ✅ ok |
| 2.5 | `PRAGMA foreign_key_check` | selftest | ✅ 0 ihlal |
| 2.6 | Yeniden başlatmada veri korunur | `test_data_survives_a_restart` | ✅ |

## 3. GİB

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 3.1 | Paketle gelen 2026 takvimi | `resources/seed/official_calendar_2026.json` | ✅ 476 event |
| 3.2 | Üretilmiş (fabricated) tarih yok | seed `generated_count` | ✅ 0 |
| 3.3 | Eşlenemeyen kayıt yok | seed `unmapped_count` | ✅ 0 |
| 3.4 | Lineage korunuyor | `source_event_key = GIB_<gerçek id>`, provenance zorunlu | ✅ |
| 3.5 | Canlı kaynakla birebir | Gerçek GİB API sync → `UNCHANGED`, 476 item | ✅ |
| 3.6 | KDV eligibility | Profil yoksa 0 event; `KDV_STANDARD_MONTHLY` → 12 event | ✅ test A |
| 3.7 | e-Defter mükellef/yükleme ayrımı | 4 ayrı obligation kodu korunuyor | ✅ |
| 3.8 | Şüpheli 0 item mevcut veriyi silmiyor | `test_gib_zero_item_current_year_fail_closed` | ✅ |
| 3.9 | `normal_due_date` değişmez | revision testleri | ✅ |

## 4. SGK

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 4.1 | 1–Ay Sonu vadesi | Ocak 2026 → 2026-02-28 | ✅ |
| 4.2 | 15–14 vadesi | Ocak 2026 → 2026-03-14 | ✅ |
| 4.3 | Tatil/hafta sonu ötelemesi | 2026-05-31 Pazar → 2026-06-01 | ✅ |
| 4.4 | Tatil verisi yoksa üretim yok | fail-closed, `NEEDS_DATA` | ✅ |
| 4.5 | Her sayfa ayrı parse ediliyor | `test_every_page_is_parsed_not_only_the_last` | ✅ |
| 4.6 | Sayfalama 0 tabanlı | Gerçek liste sayfası markup'ı | ✅ |
| 4.7 | 31.03.2026 → 07.04.2026 | Gerçek duyuru + gerçek PDF eki | ✅ AUTO_APPLIED |
| 4.8 | 20.05.2026 karma sonuç | Ödeme 05.06 AUTO_APPLIED, bildirim 03.06 NEEDS_REVIEW | ✅ |
| 4.9 | `GIB_MUHSGK` revision = 0 | Aynı test | ✅ |
| 4.10 | Bölgesel duyuru otomatik uygulanmaz | Kahramanmaraş mücbir sebep snapshot'ı | ✅ REGIONAL |
| 4.11 | Alakasız duyuru gürültü yapmaz | İlaç/SUT duyuruları | ✅ NO_RELEVANT_CHANGE |
| 4.12 | Fixture ID iş kuralı değil | Analiz yalnızca metne bakar | ✅ |
| 4.13 | `SGK_NOTICES` ayrı sync state | `official_source_state` + `official_sync_runs` | ✅ |
| 4.14 | Canlı çalıştırma | Gerçek site: 10 duyuru, 2 otomatik uygulandı | ✅ |

## 5. Hatırlatma motoru

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 5.1 | CRUD + hızlı ekle | UI + servis testleri | ✅ |
| 5.2 | Tamamla / geri al | `completion_records` | ✅ |
| 5.3 | Tekrar (aylık…yıllık, özel gün/ay) | Tamamlandığında tek bir sonraki kayıt | ✅ |
| 5.12 | Kopya tekrar kaydı DB seviyesinde de engelli | `idx_manual_reminders_parent_occurrence` unique index | ✅ |
| 5.4 | Araç ilişkisi | Oluştur / düzenle / temizle round-trip | ✅ test G |
| 5.5 | Başka şirketin aracı reddedilir | `test_vehicle_from_another_company_is_rejected` | ✅ |
| 5.6 | Yeni şirket geciken yığını almıyor | `enabled_from` + `created_at` penceresi | ✅ |
| 5.7 | Tekrar tamamlama atomik ve idempotent | complete×2 ve complete→undo→complete tek çocuk üretir | ✅ |
| 5.8 | Başarısız tamamlama iz bırakmıyor | Çocuk kayıt sonrası enjekte edilen hata → hepsi geri alınır | ✅ |
| 5.9 | Sonraki tekrar doğru bildirim saatini alıyor | `notify_time` kopyalanır, `due_time` ayrı kalır | ✅ |
| 5.10 | Araç–şirket tutarlılığı create ve update'te aynı | Ortak `resolve_links()` yardımcısı | ✅ |
| 5.11 | Belirtilmeyen bildirim ayarı korunuyor | `KEEP` sentinel; yalnız başlık düzenlemesi kuralları silmez | ✅ |

## 6. Bildirimler

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 6.1 | Başarısız Windows toast'ı "delivered" sayılmaz | `test_failed_windows_toast_is_not_recorded_as_delivered` | ✅ kanal bazlı |
| 6.1b | Bastırılan toast bildirimi kaybettirmiyor | Odak Yardımı senaryosu: kutuya düşer, rozet artar | ✅ |
| 6.1c | Bastırılan toast sonraki turda yeniden deneniyor | Kutuda ikinci kayıt oluşmaz | ✅ |
| 6.2 | Aynı eşik iki kez gönderilmez | Aynı test | ✅ |
| 6.3 | 90 günlük offset gerçekten çalışıyor | Ufuk kurallardan hesaplanır | ✅ test F |
| 6.4 | `notify_time` uygulanıyor | Saatten önce gönderilmez | ✅ |
| 6.5 | Resmî tarih değişikliği gösteriliyor | "Resmî tarih değişti · 31 Mart → 7 Nisan" | ✅ |
| 6.6 | Gösterilemeyen revision bildirimi kaydedilmez | Adapter başarısızken delivery = 0 | ✅ |
| 6.7 | Metin insan diline uygun | "ABC LTD. · 35 ABC 123 / Son tarihe 3 gün kaldı" | ✅ |
| 6.8 | Geciken spam'i sınırlı | 30 günlük pencere, günde bir kez | ✅ |
| 6.9 | Uygulama içi bildirim kutusu | Okundu / tümünü okundu, okunmamış sayacı | ✅ |
| 6.10 | Kenar çubuğu ve tepsi rozeti | Okunmamış sayısı ikon üzerinde | ✅ |
| 6.11 | Pencere açıkken uygulama içi şerit | Odak çalmaz, kendi kendine kapanır | ✅ |
| 6.12 | Vadesi geçmiş resmî değişiklik duyurulmaz | Yeni kurulumun ilk senkronu eski revizyonları "yeni" diye göstermez; revizyon kaydı ve Resmî Güncellemeler ekranı değişmez | ✅ `tests/test_notification_channels.py` |
| 6.13 | Bildirimler okunmamışlarla açılır | "Eski bildirimler" okunmuşları gösterir; boş kutu okunmuşların nerede olduğunu söyler | ✅ `tests/test_notification_channels.py` |

## 7. Windows deneyimi

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 7.1 | Tek örnek (single instance) | `QLockFile` + ikinci örnek bilgilendirilip çıkar | ✅ |
| 7.2 | Sistem tepsisi | İkon, menü, çift tıkla aç | ✅ |
| 7.3 | Kapat → tepsi | Ayara bağlı; ilk seferde bir kez açıklanır | ✅ |
| 7.4 | Gerçek çıkış | Tepsi → Çıkış; ikon gizlenir, kilit bırakılır | ✅ |
| 7.5 | `--background` | Pencere açılmaz, tepside başlar | ✅ paketli exe ile doğrulandı |
| 7.6 | Windows ile başlat | HKCU\...\Run, yönetici izni yok | ✅ |
| 7.7 | Runtime yolu | `%LOCALAPPDATA%\OfficeReminder\` | ✅ exe yanına yazmıyor |
| 7.8 | Çevrimdışı açılış | Ağ yokken dashboard ve bildirimler çalışır | ✅ test I |
| 7.9 | Mini sayaç | Varsayılan kapalı; Ayarlar ve tepsi menüsü aynı ayarı yazar | ✅ `tests/test_mini_counter.py` |
| 7.10 | Mini sayaç tazeleme | Kayıt değişince `data_changed` ile anında; zamanlayıcı beklenmez | ✅ `tests/test_mini_counter.py` |
| 7.11 | Mini sayaç konumu | `QSettings` (pencere kroması); ekran dışıysa sağ alta döner | ✅ |
| 7.12 | Başlangıç kaydını yalnızca paketli exe yazar | Kaynaktan çalışınca kutu kapalı ve sebebi yazılı; 2026-09-11'de kaynak kod Python 3.13 ile açılışa girip geliştirme veritabanını açmıştı | ✅ `tests/test_startup_service.py` |
| 7.13 | Başka programı gösteren kayıt "açık" sayılmaz | Ayarlar kaydın gösterdiği komutu yazar, işaretleyince bu exe'ye düzeltir | ✅ `tests/test_settings_autostart.py` |
| 7.14 | Ağsız açılışta senkron yeniden denenir | 2 → 5 → 15 → 30 dk, başarıya kadar; başarısız deneme "yakın zamanda senkronlandı" sayılmaz | ✅ `tests/test_sync_retry.py` |

## 7b. Güncelleme

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 7b.1 | Manifest doğrulanıyor | HTTPS dışı, tanınmayan sunucu, bozuk özet, absürt boyut, ileri schema reddedilir | ✅ `tests/test_update_service.py` |
| 7b.2 | Özet tutmazsa kurulmuyor | Aynı boyutta farklı içerik indirildi | ✅ `.part` silinir, hiçbir şey açılmaz |
| 7b.3 | Selftest kapısı | Hazırlanan yapı kendi kum havuzunda `--selftest` | ✅ gerçek veritabanına dokunmaz |
| 7b.4 | Kurulum öncesi yedek | `create_backup(force=True)` | ✅ migration'lar tek yönlü |
| 7b.5 | Eski sürüm korunuyor | `.old` klasörü yeni sürüm açılana kadar durur | ✅ `tests/test_update_swap.py` |
| 7b.6 | Her hata yolunda çalışan program kalıyor | Hazırlık yok, exe yok, süreç kapanmadı senaryoları | ✅ `tests/test_update_installer.py` |
| 7b.7 | Sonuç kullanıcıya bildiriliyor | `last_result.json` -> açılışta toast, bir kez | ✅ `tests/test_update_controller.py` |
| 7b.8 | "Sonra" bir sürüme ait | Atlanan sürüm çıkmaz, sonraki çıkar | ✅ |
| 7b.9 | Uçtan uca prova | 1.0.0 kurulu -> 1.1.0 fark paketi -> gerçek takas | ✅ 3,3 MB, kurulu sürüm 1.1.0, `.old` 1.0.0, selftest EXIT=0 |
| 7b.10 | Fark paketi boyutu | `tools/make_release.py` | ✅ tam 43,0 MB / fark **3,3 MB** |

## 8. Yedekleme

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 8.1 | SQLite backup API | `sqlite3.Connection.backup` (WAL güvenli) | ✅ |
| 8.2 | Günde bir kez otomatik | `create_backup_if_needed` | ✅ |
| 8.3 | Yedek doğrulanıyor | Oluşturulduktan sonra `integrity_check` | ✅ |
| 8.4 | Yedek gerçekten açılabiliyor | Yedek DB'den veri okundu | ✅ test J |
| 8.5 | Saklama uygulanıyor | Ayarlanan sayıda yedek kalır | ✅ |

## 9. Arayüz

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 9.1 | Tek tema/token katmanı | `ui/theme.py`; inline renk yok | ✅ |
| 9.2 | Açık ve koyu tema | İşletim sistemi şemasına göre | ✅ |
| 9.3 | İkonlar | Kendi SVG setimiz, emoji yok | ✅ |
| 9.4 | Boş durumlar | Her liste için açıklama + aksiyon | ✅ |
| 9.5 | 1280×720 | Tüm ekranlar, yatay taşma yok | ✅ screenshot |
| 9.6 | 1920×1080 | ✅ screenshot | ✅ |
| 9.7 | %125 / %150 ölçek | İkonlar keskin, kırpma yok | ✅ screenshot |
| 9.8 | Uzun içerik kaydırılıyor | Ayarlar ve Resmî Güncellemeler | ✅ |
| 9.9 | Diyaloglarda inline doğrulama | Hata alanın yanında, modal değil | ✅ |
| 9.10 | Kullanıcıya traceback gösterilmiyor | Hata metinleri sadeleştirilmiş | ✅ |
| 9.11 | Veri yoğunluğu | 38 px satır; 1440×900'de 12 kayıt + 3 grup başlığı görünür | ✅ screenshot |
| 9.12 | Tarih grupları | GECİKEN / BUGÜN / YARIN / BU HAFTA / GELECEK HAFTA / BU AY / ay adı | ✅ |
| 9.13 | Türkçe büyük harf | `upper_tr()`; "Ekim" → "EKİM", "Geciken" → "GECİKEN" | ✅ test |
| 9.14 | Tablo başlık hizası | Metin sütunları sola, tarih ve durum ortaya (`align_headers`) | ✅ screenshot |
| 9.15 | Sütun genişliği | Yalnız başlık sütunu esner; şirket/dönem sabit, başlık kırpılmıyor | ✅ screenshot |
| 9.16 | Filtre satırı | Alanlar sabit değil esnek genişlikte; %125'te üst üste binmiyor | ✅ screenshot |
| 9.17 | Boş sağ panel | Şirket ve araç detayında "Yaklaşan Tarihler" / hızlı ekle şeritleri | ✅ screenshot |
| 9.18 | Tarih seçici takvim | Hafta numarası sütunu kapalı, seçili gün accent dolgulu, hafta sonu ayrı renk | ✅ test + screenshot |
| 9.19 | Notlar tuvali | Sürükle, köşeden boyutlandır, öne/arkaya al; konum ve boyut kalıcı | ✅ test + screenshot |
| 9.20 | Not kâğıdı rengi | Palet anahtarı saklanır, hex değil; açık ve koyu tema kendi paletiyle çizer | ✅ test |
| 9.21 | Boş tuval | "Bu sayfada henüz not yok" + nasıl ekleneceği | ✅ screenshot |
| 9.22 | Liste dışa aktarma | Ekrandaki filtrelenmiş satırlar .xlsx ve A4 PDF olarak; kayıt sayısı ve tarih damgası | ✅ test + örnek dosya |
| 9.23 | Not dışa aktarma | Tuval sayfası PDF; tema koyu olsa da kâğıtlar açık paletle basılır | ✅ test |
| 9.24 | Toplu tamamlama | Çoklu seçim, onay, kayıt başına atomik tamamlama; tekrarlı kayıt sonraki vadeyi üretir | ✅ test + screenshot |
| 9.25 | Genel arama | Ctrl+K; şirket, araç, hatırlatma ve not; bir tür hata verse de diğerleri listelenir | ✅ test + screenshot |
| 9.26 | Satır–kayıt eşleşmesi | Grup başlığı satırları indeks kaydırmıyor; seçilen satır kendi kaydını döndürüyor | ✅ test |
| 9.27 | Not PDF'i yerleşimi koruyor | Tuval ekrandaki düzeniyle basılır; koyu tema olsa da açık palet, imleç ve kaydırma çubuğu basılmaz | ✅ test + PDF |
| 9.28 | Qt diyalog dilleri | Standart düğmeler "Evet / Hayır"; `qtbase_tr.qm` pakete dahil | ✅ test |
| 9.29 | SGK başlık kodlaması | Çift kodlanmış entity'ler ("&amp;#xD6;") tam çözülüyor | ✅ test |
| 9.30 | Kontrast (WCAG AA) | Her metin tonu her zeminde ≥ 4.5; iki temada da test ile sabit | ✅ test |
| 9.31 | Boş durum ölçüsü | Gövde metni ≥ 340 px genişlikte sarılıyor, cümle kesilmiyor | ✅ test |
| 9.32 | Boş liste ipucu | Kayıt yokken listede açıklama, kayıt gelince gizleniyor | ✅ test |
| 9.33 | Notlar tuvali kaydırma | Boş tahtada kaydırma çubuğu yok; tuval içeriğe göre büyüyor | ✅ test |
| 9.34 | Klavye kısayolları | Ctrl+K/N/F/E, F5, Ctrl+Shift+R, Ctrl+1…8; çakışma yok; Ayarlar'da listeleniyor | ✅ test |
| 9.35 | Engellemeyen başarı mesajı | "Kaydedildi / dışa aktarıldı" modal değil toast; uyarı ve onay modal kalır | ✅ |
| 9.36 | Yapışkan grup başlığı | Kaydırırken güncel tarih grubu üstte asılı kalır | ✅ screenshot |
| 9.37 | 30 günlük yük şeridi | Ana Sayfa'da günlük dağılım; çubuk başına tarih ve sayı tooltip'i | ✅ test + screenshot |
| 9.38 | Ekran geçişi | 130 ms açılma; efekt bitince kaldırılıyor, kalıcı opacity katmanı bırakmıyor | ✅ |
| 9.39 | Takvim ekranı | Altı haftalık ızgara, ay dışı günler soluk, yoğun gün renkli, "+N daha" | ✅ test + screenshot |
| 9.40 | Takvim ay penceresi | Ay yalnız kendi günlerini gösteriyor; komşu ay kaymıyor | ✅ test |
| 9.41 | Takvimde resmî tatil | Tatil günü işaretli ve tooltip'te adı yazıyor | ✅ test |
| 9.42 | Dosya eki | Kopya çalışma klasörüne alınıyor, özgün dosya silinse de ek duruyor | ✅ test |
| 9.43 | Ek güvenliği | Çalıştırılabilir dosya reddediliyor, 25 MB üstü ve boş dosya reddediliyor | ✅ test |
| 9.44 | Ek temizliği | Hatırlatma silinince ek satırı ve dosyası da siliniyor | ✅ test |
| 9.45 | Ek göstergesi | Listede ataç simgesi; tablo başına tek sorgu | ✅ |
| 9.46 | Ekler ve yedek | Ekler yedeğe **dahil değil**; sınırlama 11 olarak yazıldı | ⚠ bilinen sınırlama |
| 9.47 | Nota görsel yapıştırma | Pano görseli nota düşüyor, dosya olarak saklanıyor, HTML'de mutlak yol yok | ✅ test |
| 9.48 | Görsel temizliği | Not/sayfa silinince referanssız görseller siliniyor | ✅ test |
| 9.49 | Not baskısında kırpma yok | Uzun not PDF'e tam giriyor (belgeden çizim) | ✅ test (regresyon doğrulandı) |
| 9.50 | Yazarak tarih | "yarın · 3 gün sonra · ayın son günü · 15 ekim · gelecek salı"; anlaşılmayan girdi tarihe dokunmuyor | ✅ 55 test |
| 9.51 | Nottan hatırlatma | Sağ tık → ilk satır başlık, kalanı not, metindeki tarih vade olarak öneriliyor | ✅ test |
| 9.52 | İş günü sayısı | Vade tooltip'inde "24 gün · 16 iş günü"; tatiller düşülüyor | ✅ test |
| 9.53 | Satır kopyalama | Ctrl+C ve sağ tık; "Şirket · Yükümlülük · Tarih" | ✅ test |
| 9.54 | Sürükle-bırak dosya | Manuel satıra ve nota; resmî satır ve grup başlığı almıyor | ✅ test |
| 9.55 | Panodan hatırlatma | Ctrl+Shift+V; başlık, not gövdesi ve metindeki tarih | ✅ test |
| 9.56 | Takvim çipleri | Uzun şirket adı kısaltılıp üç noktayla bitiyor, ortadan kesilmiyor | ✅ test |
| 9.57 | Takvim gün sayacı | Çiplerin göstermediği kadar kayıt varsa köşede sayı; tek kayıtta rozet yok | ✅ test |
| 9.58 | Bugün / seçili ayrımı | Bugün accent dolgulu rozet, seçili gün accent çerçeve | ✅ screenshot |
| 9.59 | Çerçeve yerine derinlik | Kartlarda çerçeve yok; sayfa ile kart tonla ayrılıyor, iki temada da ayırt edilebilir | ✅ test |
| 9.60 | Dolgulu rozetler | Durum rozetleri çerçevesiz, yumuşak dolgulu | ✅ test |
| 9.61 | Kenar çubuğu | Uygulama işareti + seçili girişte accent çubuk; seçim değişince etiket kaymıyor | ✅ test |
| 9.62 | Tablo ayırıcıları | İki uçtan girintili, görünür hairline; grup başlığı satırında çizgi yok | ✅ test |
| 9.63 | Satır vurgusu | Fare satırın tamamını vurguluyor; tek hücre kutusu kalktı | ✅ |
| 9.64 | Takvim gün paneli başlıkları | Başlığın tamamı sarılarak gösteriliyor, satır metne göre uzuyor; üç nokta yok, satırlar çakışmıyor (30 Eylül'ün 44/113/156 karakterlik GİB başlıklarıyla ölçüldü) | ✅ `tests/test_calendar_page.py` |

## 10. Performans bütçeleri

Hepsi ölçülerek bulundu ve teste bağlandı (`tests/test_query_budgets.py`);
kod okuyarak görülmezler.

| # | Kontrol | Ölçüm | Durum |
|---|---|---|---|
| 10.1 | `journal_mode` bağlantı başına değil, dosya başına bir kez | bağlantı 10.16 ms → 0.28 ms | ✅ test |
| 10.2 | Tatil tablosu yıl başına bir kez okunuyor | 300 günlük hesap 984 ms → 12 ms | ✅ test |
| 10.3 | Yarım gün tatil hâlâ iş günü sayılıyor | önbellek eski anlamı koruyor | ✅ test |
| 10.4 | Uygunluk ayarları satır başına değil toplu okunuyor | pano 384 ms → 88 ms, 178 → 14 bağlantı | ✅ test |
| 10.5 | Toplu okuma tek tek okumayla aynı sonucu veriyor | eşitlik testi | ✅ test |
| 10.6 | Şirket listesi satır başına sorgu yapmıyor | 496 ms → 92 ms, 129 → 10 bağlantı | ✅ test |
| 10.7 | Hatırlatmalar yenilemesi bütçe içinde | 5003 ms → 205 ms, 1083 → 4 bağlantı | ✅ test |

## 9b. Kapsam kararları

| Konu | Karar | Gerekçe |
|---|---|---|
| Hatırlatma dosya eki | **Deferred post-1.0** | `attachments` tablosu şemada duruyor ama service/repository/UI yok ve hiçbir ekranda gösterilmiyor. Kullanıcıya çalışmayan alan sunulmuyor. Ayrıntı: `PLAN.md` § 8. |
| Takvim görünümü | Deferred post-1.0 | PLAN.md § 7'de MVP sonrasına bırakılmıştı; listeler bu sürümde yeterli. |
| Uygulama içi yedek geri yükleme | Deferred post-1.0 | Geri alma prosedürü bu belgede elle tanımlı; yedekler doğrulanıyor. |

## 10. Paketleme

| # | Kontrol | Nasıl | Sonuç |
|---|---|---|---|
| 10.0 | **Temiz sanal ortamda derleniyor** | `.venv` yalnızca `requirements.txt` + pyinstaller içerir | ✅ 15 paket |
| 10.1 | Temiz build | `rm -rf build dist && PyInstaller --clean` | ✅ |
| 10.2 | Bundle içeriği | migrations + seed + ikon | ✅ |
| 10.3 | Runtime verisi paketlenmiyor | `find dist -name "*.db"` | ✅ boş |
| 10.4 | Paketli selftest | `OfficeReminder.exe --selftest` | ✅ EXIT=0 |
| 10.5 | Paketli GUI açılıyor | `OFFICE_REMINDER_DATA_DIR` ile yalıtılmış örnek, log "Startup complete" | ✅ 12 migration + 476 GİB + 24 SGK |
| 10.6 | Boyut | onedir klasör / ZIP / dosya | ✅ 109 MB / 42,9 MB / 179 |
| 10.7 | Kullanılmayan Qt zinciri paketlenmiyor | `Qt6VirtualKeyboard` -> `Qt6Quick`/`Qt6Qml` spec'te ikili süzgeçle düşürülür | ✅ 13 MB |
| 10.8 | `opengl32sw.dll` bilinçli olarak duruyor | Uygulama GL istemiyor, ama RDP oturumunda yedeksiz kalmamak için tutuluyor | ⚠ karar: kalsın |

---

## Yayın adımları

1. `pytest -q` — tamamı yeşil olmalı, **temiz sanal ortamda** koşturun.
2. `python tools/make_icon.py` — ikon değiştiyse.
3. `rm -rf build dist && .venv/Scripts/pyinstaller --noconfirm --clean office_reminder.spec`
   Sistem Python'uyla derlemeyin: paket 40 MB şişer (bkz. 10.0).
4. `dist\OfficeReminder\OfficeReminder.exe --selftest` → `SELFTEST PASSED`
5. Temiz bir kullanıcı profilinde `--background` ile başlat, tepsi menüsünü ve
   "Bugünkü İşler"i dene.
6. `%LOCALAPPDATA%\OfficeReminder\logs\office_reminder.log` içinde `ERROR`
   satırı olmadığını doğrula.
7. `dist/OfficeReminder` klasörünü arşivle ve dağıt.

## Geri alma

Uygulama veriyi asla otomatik silmez. Bir sürüm sorunlu çıkarsa:

1. Uygulamayı kapat (tepsi → Çıkış).
2. `%LOCALAPPDATA%\OfficeReminder\backups\` içinden istenen günün `.db`
   dosyasını `…\data\office_reminder.db` üzerine kopyala.
3. Önceki `dist/OfficeReminder` klasörünü geri koy.

Migration'lar ileriye dönüktür: eski bir sürüm, yeni şemayla oluşmuş bir
veritabanını açmaya çalışırsa çalışmayabilir — bu yüzden geri alırken yedek
kullanılır.

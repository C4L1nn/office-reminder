-- Yapışkan not tuvali (PLAN.md § 7 "Notlar").
--
-- Not bir yükümlülük değildir: vadesi yoktur, bildirim üretmez ve resmî/manuel
-- hatırlatma tablolarıyla ilişkilendirilmez (karar: 2026-09-04). Bu yüzden
-- kendi tablolarında durur ve hatırlatma sorgularına hiç karışmaz.
--
-- Kâğıt rengi hex olarak değil **palet anahtarı** olarak saklanır. Renk kodu
-- yazılsaydı koyu temada okunamayan bir not, açık temada da aynı hex ile
-- çizilirdi; anahtar sayesinde her tema kendi paletiyle boyar.

CREATE TABLE IF NOT EXISTS note_boards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL,
    -- Zengin metin. content_text yalnızca arama içindir, gösterimde kullanılmaz.
    content_html TEXT NOT NULL DEFAULT '',
    content_text TEXT NOT NULL DEFAULT '',
    x REAL NOT NULL DEFAULT 0,
    y REAL NOT NULL DEFAULT 0,
    width REAL NOT NULL DEFAULT 240,
    height REAL NOT NULL DEFAULT 200,
    -- Üst-alt sırası. Büyük olan üstte çizilir.
    z INTEGER NOT NULL DEFAULT 0,
    colour TEXT NOT NULL DEFAULT 'yellow',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (board_id) REFERENCES note_boards(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notes_board ON notes(board_id, z);

-- Boyut alt sınırı: 0 genişlikte bir not ekranda kaybolur ve geri getirilemez.
-- Kontrol veritabanında durur ki UI hatası kalıcı veri bozmasın.
CREATE TRIGGER IF NOT EXISTS trg_notes_min_size_insert
BEFORE INSERT ON notes
FOR EACH ROW WHEN NEW.width < 120 OR NEW.height < 90
BEGIN
    SELECT RAISE(ABORT, 'not boyutu 120x90 altına inemez');
END;

CREATE TRIGGER IF NOT EXISTS trg_notes_min_size_update
BEFORE UPDATE ON notes
FOR EACH ROW WHEN NEW.width < 120 OR NEW.height < 90
BEGIN
    SELECT RAISE(ABORT, 'not boyutu 120x90 altına inemez');
END;

-- Her kurulumda en az bir sayfa bulunur; boş bir uygulama açılışında
-- kullanıcıya "önce sayfa oluştur" duvarı çıkmaz.
INSERT INTO note_boards (name, position)
SELECT 'Notlarım', 0
WHERE NOT EXISTS (SELECT 1 FROM note_boards);

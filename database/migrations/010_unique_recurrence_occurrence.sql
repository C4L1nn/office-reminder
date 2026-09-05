-- Tekrarlayan hatırlatmalarda "bir üst kayıt + bir vade = tek çocuk" garantisi.
--
-- complete() akışı, tamamlama kaydını yazmadan ÖNCE sonraki tekrarı oluşturuyordu.
-- Bu yüzden ikinci bir complete (ya da complete → undo → complete) aynı vade için
-- ikinci bir çocuk kayıt bırakabiliyordu. Servis tarafı artık bunu tek transaction
-- içinde ve mevcut çocuğu yeniden kullanarak yapıyor; buradaki index ise aynı
-- garantiyi veritabanı seviyesinde kalıcı kılar.

-- Önce varsa geçmişten kalan kopyaları temizle: her (parent, due_date) çifti için
-- en eski kayıt tutulur, sonradan üretilmiş kopyalar silinir.
DELETE FROM manual_reminders
WHERE parent_reminder_id IS NOT NULL
  AND id NOT IN (
      SELECT MIN(id) FROM manual_reminders
      WHERE parent_reminder_id IS NOT NULL
      GROUP BY parent_reminder_id, due_date
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_reminders_parent_occurrence
    ON manual_reminders(parent_reminder_id, due_date)
    WHERE parent_reminder_id IS NOT NULL;

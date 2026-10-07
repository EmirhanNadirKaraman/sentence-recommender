# Reels ve dil atlası kapasite kontrolü

7 Ekim 2026. Bu sürümün kapasite kontrolü **başarılı sonuç vermedi**.
Önceki optimizasyon raporunun hız/bellek sayıları bu sürüm için yeniden
doğrulanmış olarak sunulmamalıdır.

İlk staged koşuda ilk öğrenme GET'i 180.165 saniyede zaman aşımına uğradı.
Dört hesabın 72 sıcak isteğine ve kaydetme dalgasına ulaşılamadı.
Başarısız istekten sonra sonlandırılan uygulama alt sürecinde gözlenen tepe
1,630 MiB idi; bu, dört okuyucunun tamamlanmış bellek ölçümü değildir.
[İlk ham sonuç](results/four_readers_journey_2026-10-07.json).

Ölçüm aracının ebeveyn süreci bütün pg_dump çıktısını ve yeniden yazılmış
SQL'i bellekte tutuyordu. Büyük tamponlar uygulama ölçümü boyunca da
yaşıyordu; bu bellek baskısı yaratabilir ve ebeveyn belleği alt süreç
ölçümünde görünmüyordu. Araç düzeltildi:

- SQL geçici dosyaya yazılır ve her şemaya satır satır aktarılır.
- Büyük kopya tamponları uygulama ölçümü boyunca bellekte tutulmaz.
- Uzayan uygulama ölçümünde 45 saniyelik aralıklarla iş parçacığı izi çıkar.
- Başarısız alt süreç hemen başarısız kodla çıkar; büyük Python nesnelerinin
  son temizliğinde takılmaz. Ana komut da başarısız koşuyu başarısız kodla bildirir.
- Corpus salt okunur, dört state şeması geçicidir. Gerçek öğrenme kayıtları değişmez.

Bu düzeltmeden sonraki koşu da ilk GET'te 180 saniyelik sınırı aştı.
Alt süreç için gözlenen tepe 1,292 MiB; çıkış kodu 1.
[İkinci ham sonuç](results/four_readers_journey_retry_2026-10-07.json).

45/90/135/180 saniyelik izler corpus/store.py içindeki mevcut SQL okumasını
ve corpus_unit satırlarının Python nesnelerine dönüştürülmesini gösteriyordu.
İstek henüz Viewer._page/JourneyStore.snapshot aşamasına gelmemişti.
Kontrol edilen PostgreSQL oturumunda engelleyici işlem kilidi görülmedi.
Bu, ödül okumasının bu zaman aşımını başlatmadığını gösterir; yavaşlamanın
tam nedenini veya önceki koşuyla ortam eşitliğini tek başına kanıtlamaz.
Bellek baskısı gözlendi, fakat yalnızca buna dayanarak bütün gecikmeyi
ortama atfetmiyoruz.

Ödül mantığının eşzamanlı dört iş parçacığı testi günlük dinleme sınırını ve
tek ödülü doğruladı. Dokunma/tekerlek/iptal/hata testleri ve mobil/masaüstü
örnek ekran kontrolü başarılıdır; bunlar gerçek corpus kapasite testinin
yerine geçmez. Sunucuyu paylaşmadan önce temiz, kaynakları ölçülen bir
ortamda ilk corpus yüklemesi ve dört okuyucunun sıcak akışı yeniden ölçülmeli.

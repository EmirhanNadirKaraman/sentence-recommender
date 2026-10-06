# Dört kullanıcı optimizasyonu — 7 Ekim 2026

Değişiklikler codex/learning-experience-redesign branch'inde. Karşılaştırma,
[önceki incelemeyle](FOUR_READERS.md) aynı macOS/ARM64 bilgisayarı, aynı corpus
sayımı ve aynı kullanıcı durumunun dört geçici kopyası üzerinde yapıldı.
Bu ölçüm Linux VPS kapasite garantisi değildir.

## Son ölçüm

| Ölçüm | Önce | Sonra |
|---|---|---|
| Sıralı ilk öğrenme sayfası, dört hesap | 23,49 / 57,98 / 72,75 / 95,45 s | 13.70 / 2.67 / 6.01 / 4.22 s |
| 4 eşzamanlı istemci, 6 sayfa, 72 istek: toplam süre | 10,60 s | 2.050 s |
| Bu gezinmede medyan / P95 | 0,230 / 2,612 s | 0.038 / 0.459 s |
| Öğrenme sayfası, 12 istek: medyan / en uzun | 1,661 / 3,168 s | 0.163 / 0.475 s |
| İlk kelime işaretleme dalgası: video puanları tamamlanana kadar | 13,08–13,67 s | 0.066–0.073 s |
| Aynı dalgada kaydetme yanıtı | 0,110–0,197 s | 0.014–0.025 s |
| Sıralı senaryoda gözlenen uygulama ayak izi | 5.370 MiB | 2,071 MiB |
| Dört eşzamanlı ilk ziyaret | 6.065 MiB'de güvenlik kesmesi, tamamlanmadı | 3,375 MiB tepe; 4/4 başarılı, 37.04 s toplam |
| Sıkıştırılmamış katalog HTML'i | 861.279 bayt | 45,405 bayt |

Sıralı senaryoda 85 GET'in tamamı, eşzamanlı soğuk senaryoda dört GET'in tamamı
200 döndü. Dört kelime yalnızca geçici hesap kopyalarına kaydedildi.
P95 en yakın sıra yöntemiyle hesaplandı; sayfa başına örnek sayısı 12.
Karışık gezinme öğrenme, Reels, katalog, tekrar, kelime arama ve listeleri
kapsar; öğrenme ve Reels dışındaki sayfaların ilk açılışları da dahildir.
Sonuçlar tek koşu ölçümleridir; işletim sistemi önbelleği ve swap süreleri etkiler.
Önceki bellek örneklemesi dördüncü hesabın açılışında başlamıştı; yeni ölçüm
çocuk sürecin ömrünü kapsar. PostgreSQL ve işletim sistemi belleği dahil değildir.

## Uygulanan değişiklikler

- Web sunucusunda ortak CorpusPool: aynı dil, veri sürümü, kaynak ve liste
  çözümlemesi için cümleler bir kez yüklenir. Eşzamanlı yüklemeler birleştirilir;
  kullanılmayan veri zayıf referanslarla bırakılır.
- Gizlenen/düzeltilen cümleler, yasaklanan videolar ve hakem istisnaları görünüm
  anahtarındadır. Her okuyucunun bilinen kelimeleri, adayları ve öğrenme sayıları
  kendisine aittir. Büyük değişmez corpus topolojisi ve örnek indeksi paylaşılır.
- Hazır planı olmayan kaynakta bir sonraki öneri ve örnekleri saklanır.
  Öğrenme, geri alma, erteleme, kelime/gramer filtresi, cümle değerlendirmesi veya
  örnek vektör kaynakları değişince yeniden hesaplanır. Yalnızca son öneri tutulur.
  Kalıcı müfredat hazırlığı mevcut build-roadmap komutunda kalır.
- Kelime→video ve video→cümle indeksleri corpus hazırlığında bir kez oluşturulur.
  Kelime sonrası güncelleme yalnızca etkilenen videolara dokunur.
- Katalogda kartlar ve karşılaştırma tablosu 24 videoluk aynı sayfayı gösterir.
  Sayfa geçişleri aramayı, kaynağı, listeyi ve sıralamayı korur; bütün videolar
  sonraki sayfalardan erişilebilir.

## Doğrulama ve kalan sınır

İzole, geçici PostgreSQL ile ilgili corpus, liste çözümleme, roadmap, web,
okuyucu ve yeni kapasite testleri: **398 test + 54 alt test başarılı**.
Testler eşzamanlı tek yükleme, kullanıcı ilerlemesinin ayrılığı, doğrudan
cümle sayımlarıyla indeks eşitliği, düzeltme/sürüm ayrılığı, öneri önbelleğinin
geçersizleşmesi ve tüm katalog sayfalarının erişilebilirliğini doğrular.

İlk soğuk giriş hâlâ pahalıdır: tüm hesaplar aynı anda ilk kez açılırsa bu koşuda
35–37 saniye beklenir. Bellek kaynak/liste çeşitliliğiyle artabilir; dört farklı
hesabın farklı listeler üzerinde davranışı bu dört eş kopya testinden çıkmaz.
Sunucu seçildikten sonra aynı harness Linux üzerinde tekrar çalıştırılmalıdır.
Gerçek oturum/davet akışı, tarayıcı JavaScript'i, YouTube ve dış model servisleri
bu yük testinin kapsamına dahil değildir.

Ham kayıtlar: [optimizasyon sonrası](results/four_readers_optimized_2026-10-07.json)
ve [önceki sürüm](results/four_readers_2026-10-07.json).
four_readers.py komutları önceki raporda bulunur.

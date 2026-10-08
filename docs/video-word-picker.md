# Video kelime seçimi

`tools/build_video_word_picker.py`, hesabın `study_list.txt` hedeflerini uygulamanın
aynı `known_set()` hesabıyla karşılaştırır: dosyadaki bilinenler, uygulamada işaretlenen
birimler, alias'lar ve türetilebilir bileşikler dahil. Dil Almanca olmalı.

```sh
.venv/bin/python tools/build_video_word_picker.py --reader emir
```

`docs/video-selection/` içinde bağımsız HTML, bilinmeyenler TXT ve kaynak snapshot
JSON oluşur. Bunlar kişisel, üretilen dosyalardır; git ve Docker image dışında kalır.
HTML'i tarayıcıda aç veya aynı klasörü yalnızca loopback üzerinde sun:

```sh
.venv/bin/python -m http.server 8794 --bind 127.0.0.1 --directory docs/video-selection
```

`http://127.0.0.1:8794/emir-video-words.html` üzerinden Evet/Hayır değerlendir.
A Hayır, D Evet. Ok tuşları da çalışır: sağ Evet, sol Hayır, yukarı geri al;
boşluk sonra karar ver.
Arama kutusuna yazarken kısayollar çalışmaz. Aynı kelimenin kalan bilinmeyen
kullanımları gruplanır; kart kararı bütün kalan üyelerine uygulanır. Bilinen
üyeler dışa aktarılmaz. Liste sırası korunur.

Evet listesi TXT, karar yedeği JSON olarak indirilebilir. JSON yedeği aynı hesabın
aynı listesindeki kartlara geri yüklenebilir; snapshot'tan kalkmış kartlar atlanır.
Kararlar tarayıcı localStorage alanındadır; aynı origin/tarayıcıda yeniden açılınca
korunur. HTML'i file:// ile açmak farklı saklama alanı kullanabilir; başka
bilgisayara veya tarayıcıya geçmeden JSON yedekle. Otomatik kayıt engellenirse araç
uyarı verir, o oturumda seçim ve dosya indirme devam eder.

Bunlar video üretim tercihleri; bilinen kelimeler veya ilerleme değiştirilmez,
video/model çağrısı yapılmaz. Snapshot otomatik güncellenmez; yeniden üretmek
için komutu tekrar çalıştır. Güncellenen snapshot aynı origin'de aynı kalan kartların
kararlarını korur. Geri alma geçmişi yalnızca mevcut oturum içindir.

## Gerekçeli otomatik eleme

`tools/screen_video_word_picker.py` mevcut özel snapshot'ı işler; veritabanı,
bilinen kelimeler ve gerçek öğrenme ilerlemesine dokunmaz. Goethe A1 Start
Deutsch 1 ve A2 kelime listelerinin başlık sütunlarını kullanır; örnek cümlelerin
sözcüklerini seviye kanıtı saymaz. İsim/sıfat ayrımında büyük harfi korur
(`mittel` ile `Mittel` aynı değildir). Tam yazım eşleşmesi gerekir; liste
kapsamındaki bir sözcüğün bütün olası anlamlarının bu seviyede olduğu iddia edilmez.

Kaynaklar:
- https://www.goethe.de/pro/relaunch/prf/de/A1_SD1_Wortliste_02.pdf
- https://www.goethe.de/pro/relaunch/prf/mk/Goethe-Zertifikat_A2_Wortliste.pdf

Resmi PDF'leri indirip `pdftotext -bbox-layout` ile dönüştürdükten sonra:

```sh
.venv/bin/python tools/screen_video_word_picker.py \
  --a1-bbox /tmp/word-picker-levels/a1.html \
  --a2-bbox /tmp/word-picker-levels/a2.html
```

İngilizce benzerliği, açık Almanca–İngilizce anlam çiftleriyle değerlendirilir;
fuzzy mesafe veya yalnızca aynı harfler eleme sebebi değildir. Liste bilinçli
olarak ihtiyatlıdır; tüm benzer sözcükleri kapsama iddiası yoktur. Yanıltıcı
benzerlikler (Gift/gift, aktuell/actual, eventuell/eventually vb.) bu kuralla
elenmez. A1/A2 kanıtı ayrıca varsa o gerekçe geçerli olabilir.

Bir karttaki **her** bilinmeyen hedef kanıtlanmalı; aksi halde kartın tamamı
manuel değerlendirmeye kalır. Temel bir fiil, ileri edatlı/refleksif kullanımın
elenmesine neden olmaz. Eski para birimleri, kurum adları, nadir/teknik sözcükler
ayrı bir onay olmadan otomatik eleme kuralı değildir.

Otomatik Hayır başlangıç kararlarıdır. Önceden kaydedilmiş manuel Evet/Hayır
korunur. Hayır filtresinde ve “Hayır gerekçeleri” listesinde açıklamalar görünür.
TSV indirmesi mevcut kararları ve gerekçeleri içerir; JSON yedeği gerekçeleri de
saklar (eski gerekçesiz yedekler çalışır). Kartı yeniden değerlendirmek veya
“otomatik hayırları yeniden değerlendir” düğmesiyle otomatik kararları geri almak
mümkündür; bu kartlar sayfa yenilenince yeniden otomatik elenmez. Kurallar yeniden
üretilirse yalnızca hâlâ otomatik olan kararların gerekçeleri güncellenir; artık
kanıtlanmayan otomatik kararlar manuel bekleyenlere döner.

Özel klasörde `*-automatic-no.json` kanıt/sayfa/kaynak ayrıntılarını ve
`*-automatic-no.tsv` tarayıcıdaki manuel kararlar öncesindeki otomatik eleme
önerilerini saklar. Bunlar da Git ve Docker dışında kalır. Snapshot'ı sıfırdan
üretince eleme komutunu yeniden çalıştırmak gerekir.

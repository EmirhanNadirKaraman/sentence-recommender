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
Ok tuşları: sağ Evet, sol Hayır, yukarı geri al; boşluk sonra karar ver.
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

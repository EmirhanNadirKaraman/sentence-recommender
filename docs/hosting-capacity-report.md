# Sunucu kapasitesi ve performans incelemesi

Ölçüm tarihi: 7 Ekim 2026. Branch: `codex/learning-experience-redesign`.

**Tüm sayfalar açık kalacaksa önerim 16 GB RAM, en az 4 vCPU ve en az 80 GB SSD/NVMe.** Somut başlangıç seçeneği: Hetzner CX43, 8 vCPU / 16 GB / 160 GB NVMe. Almanya/Finlandiya için yayımlanan taban fiyat €15,99/ay; vergi, IPv4 ve yedekleme hariç. [Resmî özellikler](https://www.hetzner.com/cloud/cost-optimized/), [resmî fiyat tablosu](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/).

CX33, 4 vCPU / 8 GB / 80 GB ve €8,49/ay taban fiyatla daha ucuz. Normal öğrenme/video akışları için değerlendirilebilir; bütün gelişmiş araçlar, birden fazla liste ve eşzamanlı hesaplamalar açıkken güvenli varsayılan olarak seçmiyorum. Ölçülen uygulama ayak izi tek başına 5,6 GiB'ye ulaştı. PostgreSQL, işletim sistemi ve geçici hesaplamalar bunun üzerine gelir. Sunucu siparişinde stok ve güncel toplam tutarı kontrol et.

## Nasıl ölçüldü?

- MacBook Pro M1, 8 mantıksal CPU, 16 GB RAM, macOS 26.2, Python 3.12. Kiralık Linux VPS üzerinde yapılmış kapasite garantisi değildir.
- Mevcut PostgreSQL veritabanı: 500.431 corpus cümlesi, yaklaşık 4,13 GiB veritabanı boyutu. Bu sayı bütün veritabanına aittir; her sayfa bütün cümleleri kullanmaz.
- Gerçek HTTP router'ı üzerinde geçici loopback sunucusu; dört ayrı Application/Viewer önbelleği. Gerçek hesap veya öğrenme kaydı oluşturulmadı, kelime işaretlenmedi, liste kaydedilmedi, model çağrısı yapılmadı.
- Dört sentetik oturum aynı mevcut kullanıcı durumunu ve aynı `study_list` listesini okudu. Farklı diller/listeler/düzeltmeler ek belleğe neden olabilir. GET sayfaları mevcut türetilmiş önbellekleri yenileyebilir.
- İlk sayfa turu, sıcak tek kullanıcı ve dört eşzamanlı istemci ayrı kaydedildi. İlk turdaki ikinci sayfa tamamen boş bir süreçte başlamaz; önceki sayfanın önbelleklerinden yararlanabilir.
- Sıcak tek kullanıcıda sayfa başına 3, eşzamanlı turda 12 örnek vardır. Eşzamanlı tur diğer kullanıcıların bazı sayfalara ilk ziyaretini de içerir. Küçük örneklerden güvenilir P95/P99 veya uzun süreli kapasite iddiası çıkarmıyorum.
- Son ana koşu 372, gerçek video/kelime akışları ek koşusu 84 HTTP isteği: **456/456 başarılı**. İlk tanı koşusunda live-search test URL'si yanlış yazılmıştı; o 16 başarısız test isteği uygulama hatası sayılmadı. Doğru URL ile son koşuda başarı doğrulandı.
- cProfile ayrı koşuda kullanıldı. Profil süreleri ek yük taşır; yanıt süresi karşılaştırmaları profilsiz koşulardan gelir. Cumulative süreler birbirini içerir ve toplanamaz.
- RAM için RSS yanında macOS `vmmap` fiziksel ayak izi kullanıldı. RSS sıkıştırılmış belleği göstermediği için özellikle boşta görünen 600–1.000 MiB değerleriyle sunucu seçilmemeli.
- Bunlar HTML/JSON sunucu yanıtlarıdır. Tarayıcı çizimi, mobil ağ, YouTube oynatma, TTS, modelle yazı düzeltme ve dört kişinin aynı anda kelime öğrenmesi bu yeni koşunun kapsamında değildir. Önceki kelime-işaretleme testi [önceki optimizasyon raporunda](../perf/OPTIMIZATIONS.md) bulunur.

## Sayfa sonuçları

Aşağıdaki değerler son koşunun milisaniye cinsinden medyanlarıdır. İlk sütun ilk turdaki tek istektir. Dört istemci sütunu sıcak ve bazı yeni kullanıcı ziyaretlerini birlikte içerir.

| Sayfa / istek | İlk tur | Sıcak tek kullanıcı | 4 istemci medyan |
|---|---:|---:|---:|
| Öğrenme `/` | 24.563 | 159 | 332 |
| Sözlük `geben` | 3.457 | 85 | 217 |
| Reels | 174 | 35 | 136 |
| Video kütüphanesi | 17 | 18 | 43 |
| Kanallar | 70 | 50 | 63 |
| Tekrar | 253 | 152 | 424 |
| Dinleme | 82 | 38 | 122 |
| Yazma sayfası | 9 | 8 | 19 |
| Kelime kontrolü | 441 | 8 | 20 |
| Kaydedilen cümleler | 17 | 11 | 23 |
| Kelime listeleri | 12 | 14 | 26 |
| Video-cover giriş sayfası | 9 | 11 | 17 |
| Başarılar / Journey | 13 | 14 | 21 |
| Plan | 28 | 12 | 31 |
| Roadmap | 275 | 336 | 638 |
| Frontier | 41.640 | 165 | 869 |
| Blocked | 4.773 | 18 | 28 |
| Anki önizlemesi | 4.421 | 10 | 49 |
| Ayarlar | 118 | 29 | 64 |
| Canlı trigram cover araması `haus` | 2.149 | 35 | 212 |
| Sonraki Reels JSON | 40 | 23 | 80 |

`/study` ve `/watch` girişleri de test edildi; bir video seçilmemiş girişlerin maliyeti gerçek bir öğrenme oturumuyla aynı değildir. Ek koşuda gerçek video parametresi ve kelime detayı kullanıldı:

| Gerçek akış | İlk tur ms | Sıcak tek kullanıcı ms | 4 istemci medyan ms |
|---|---:|---:|---:|
| Video `Tw-UQAGy1Ds` | 1.804 | 35 | 58 |
| Bu videonun study isteği | 12 | 12 | 24 |
| `angeben` kelime detayı | 2.249 | 88 | 269 |
| Video altyazısı JSON | 14 | 12 | 21 |
| Sonraki öğrenme kartı JSON | 21.468 | 79 | 264 |

Seçilen videonun study yanıtı boş/uygun sonraki kelime bulunmayan duruma denk geldi; bu düşük süre bütün study oturumları için genellenemez. Soğuk yükler hâlâ hissedilir: ana koşuda yeni kullanıcı Frontier açılışı 49,5 saniyeye, öğrenme sayfası 11,1 saniyeye ulaştı. Medyanlar bu uçları gizlememeli.

## CPU ve RAM'i en çok kullanan yollar

1. **`Application.corpus` → `CorpusStore.load` → `Viewer.scope` / `CorpusIndex`.** Hazır plan bulunmadığında yüz binlerce cümlenin ve birim üyeliklerinin Python nesneleri olarak tutulması, çözümleme ve indeks kurma yapılır. Soğuk öğrenme açılışı 24–30 saniye; sonraki kart API'sinin soğuk açılışı 21,5 saniye. Paylaşılan corpus önbelleği zaten var; kullanıcı sayısıyla birebir dört kez veri kopyalandığını varsaymak yanlış olur. Bununla birlikte kaynak, sayım biçimi, hedef listesi ve düzeltmeler farklı önbellek anahtarları oluşturur.

2. **`Viewer.frontier` → `_frontier_corpus` / `_frontier_index`.** Varsayılan plan generated+subtitle+transcript kaynaklarını birlikte kullanıyor; yalnızca subtitle sayfasını açmakla aynı kapsam değil. Filtrelenmiş cümleler ve başka bir öğrenme indeksi tutulur. Yeni hesap için hâlâ pahalı. Ana son koşuda Frontier istekleri toplam yaklaşık 70 CPU-saniyesi kullandı; bu toplam, farklı sayıdaki soğuk/sıcak istekleri içerir ve tek istek süresi değildir.

3. **`Application.verdicts` / `SentenceOverrides.verdicts`.** Ayrı profil koşusunda 218 kez aynı değerlendirme tablosu okunup sözlük oluşturuldu. Frontier bunu gösterilen her aday için, Anki fallback'i de her kelime için tekrar yapıyordu. Bu tekrar düzeltildi; aşağıdaki sonuçlar davranışı koruyan dar değişiklik içindir.

4. **`Viewer._stranded` → `reachable` ve Blocked örnekleri.** Corpus üzerinden ulaşılabilirlik ve engelleyici kelimeler hesaplanır. İlk ana açılış yaklaşık 4,8 saniye; diğer kullanıcıların ilk ziyaretlerini içeren testte 17,3 saniyeye çıktı. Sıcak sonuç çok hızlı, fakat hesaplar/listeler değiştikçe ilk maliyet tekrar oluşabilir.

5. **`Viewer.anki_examples` → hedefli corpus okumaları / `ExampleIndex.examples` / `spread`.** Bu hesapta 70 Anki kartı kuyruktaydı. Hazır deck bulunmayan kelimeler için ayrı örnek seçimleri yapılıyor; ilk açılış pahalı, mevcut kuyruk önbelleğe alındığında hızlı. Son koşuda ilk açılış 4,4 saniye, yeni kullanıcıların açılışları 14,7 saniyeye kadar çıktı. Örnek seçimini sayfalara bölmek veya arka planda hazırlamak önerilir.

6. **`UnitSearch.__init__` ve trigram posting'leri.** Arama başına bütün corpus okunmuyor; birim frekanslarından indeks hazırlanıyor. Yaklaşık 79 bin birimlik indeksin ilk kurulması 2,1 saniye, sıcak arama 35 ms. İndeksler şu anda viewer başına tutulduğu için aynı listeyi kullanan kişilerde yeniden kurulabilir. Paylaşılacaksa anahtar corpus vintage + dil + alias/goal setini içermeli; kullanıcıya ait bilinen kelime durumları ortaklaştırılmamalı.

7. **`CorpusStore.load(holding_many=...)` ve `minimum_subset` / CBC solver.** Cover giriş sayfası hafiftir; hesaplama ayrı bir ağır işlemdir. Mevcut bilgi dondurularak en sık geçen bilinmeyen hedeflerden 20/50/100 kelimeyle gerçek, kayıt yapmayan hesaplar çalıştırıldı:

| Hedef | Getirilen aday cümle | Veriyi getirme | Cover hesabı | Çözücü CPU | Sonuç |
|---:|---:|---:|---:|---:|---|
| 20 | 10.184 | 11,10 s | 1,58 s | 0,84 s | Optimal, 7 video, 19 hedef kapsandı |
| 50 | 20.123 | 11,33 s | 4,71 s | 3,63 s | Optimal, 14 video, 49 hedef kapsandı |
| 100 | 33.105 | 11,83 s | 1,38 s | 0,77 s | Optimal, 21 video, 98 hedef kapsandı |

Hedef sayısı arttıkça solver süresi monoton artmaz; set-cover örneğinin yapısı belirler. Bu tek hedef seçimi worst-case sınırı değildir. Kodda solver için 20 saniye sınır var; **bu sınır SQL okumasını, örnek hazırlığını veya kuyruğu kapsamaz**. Dört eşzamanlı cover hesabı bu koşuda çalıştırılmadı. Cover verisini getirme sorguları yeni SQL planı incelemesinde öncelikli adaydır; bütün yabancı birimleri koruma şartı nedeniyle i+1 doğruluğunu bozacak erken filtre uygulanmamalı.

### Bellek sonucu

- Dört kişiyle odaklı video/kelime/sonraki kart testinin fiziksel ayak izi tepe değeri yaklaşık **2,0 GiB**.
- Bütün geniş sayfa turu, Frontier ve Blocked dahil: yaklaşık **5,5 GiB mevcut, 5,6 GiB tepe** uygulama ayak izi.
- İki farklı iş yükü karşılaştırılıyor; farkın tamamını tek bir sayfaya atfetmiyorum. PostgreSQL ve diğer süreçler bu rakamlara dahil değil.
- Liste/kaynak/hesap çeşitliliği ve uzun süreli kullanım ayrı stres testi gerektirir. Birden fazla uygulama worker süreci büyük önbellekleri ayrı tutar; ilk dağıtımda tek web süreci kullanmak daha uygun.

## Bu incelemede uygulanan optimizasyon

Frontier ve Anki örnek seçiminde verdict verileri aynı render içinde bir kez okunuyor. Sonraki render yine güncel veri okuyor; kalıcı, yanlış geçersizleşen bir öğrenme önbelleği eklenmedi.

- Frontier sıcak tek kullanıcı medyanı: **2.641 ms → 165 ms**, yaklaşık 16 kat iyileşme.
- Frontier dört istemci turu medyanı: **9.203 ms → 869 ms**. Bu tur bazı ilk ziyaretleri de içerir.
- Anki ilk turu: 7,17 s → 4,42 s. Ayrı koşulardaki işletim sistemi/DB cache değişimleri de etkili; bu farkın tamamını kod değişikliğine atfetmiyorum. Sıcak Anki zaten yaklaşık 10 ms idi.
- Tüm genişletilmiş web/dictionary/cover/alias kontrolleri ve iki yeni snapshot testi çalıştırıldı. Hiçbir sayfa veya öğrenme özelliği kapatılmadı.

## Öncelikli işler ve kapatma kararı

1. **Yayınlanacak kaynak/liste kombinasyonları için hazır plan üret.** Kontrolde `subtitle` için seçilen label'ın geçerli planı yoktu; `all` için hazır planın stamp'i geçerliydi. Canlı fallback'i kapatmak yerine eksik planları dağıtım öncesinde üretmek, ardından yeni veri geldiğinde arka planda güncellemek ilk iş. Örnek mevcut CLI: `python main.py build-roadmap --reader emir --source subtitle --quality --strict --goals`. Her arkadaşın kendi liste/bilgi durumu ayrıca ele alınmalı. Bu incelemede plan yeniden yazılmadı.
2. **Cover hesaplarını tek hesaplama kuyruğuna al; ilerleme/sonuç durumunu göster.** Kullanıcı başına mükerrer hesap isteğini birleştir. Giriş sayfası ve live search açık kalabilir. SQL süresi ve solver süresi ayrı izlenmeli.
3. **Frontier ve Blocked'ı normal kullanıcıların ana akışından uzak tut.** Yöneticiye özel/isteğe bağlı araç olmaları düşünülebilir. Soğuk corpus/indekslerin hiç kurulmasını önlediğinde fayda sağlar; yalnız menü linkini gizlemek yeterli değildir. Frontier sıcak tekrar artık hızlı olduğundan tümden kaldırılması şart değil. Erişim kısıtlama tercihi kullanıcı onayına bırakıldı, bu incelemede uygulanmadı.
4. **Anki önizlemesini sayfala veya lazy hazırla.** 70 kelimenin eksik örneklerini ilk render'da hesaplama. Export akışı ayrı background job olabilir.
5. **Trigram indekslerini doğru anahtarla paylaş ve listeler için toplam cache bütçesi belirle.** Owner'ın liste sayısı sınırsız; konu listeleri açıldıkça farklı corpus çözümlemeleri belleği büyütebilir. Bütün kullanıcıların toplamını kapsayan sınır önerilir.
6. **Yeni video/channel ingestion, NLP, corpus build, plan rebuild, TTS/deck export ve LLM generation işlerini web sunucusuyla aynı anda koşturma.** Bunlar bu sayfa testinde çalıştırılmadı; kod yolları ve önceki profiller ağır batch işlerine işaret ediyor. Geceleri/job worker'da veya kendi bilgisayarında hazırlayıp yeni corpus verilerini sunucuya aktarabilirsin. Arkadaşlara owner-only ingestion/replan yetkisi zaten verilmiyor.

**Reels, normal video kütüphanesi, listeler, Journey veya yazma giriş sayfasını kaldırmayı önermiyorum.** Bu sayfaların sıcak GET maliyeti düşük. Yazı gönderme/model yanıtı farklı bir işlem; sırf yazma sayfası 8 ms diye modelle düzeltmenin de hızlı olduğu söylenemez.

## Taşıma için pratik düzen

- 16 GB VPS, Ubuntu ve Docker Compose; tek uygulama süreci + PostgreSQL + Caddy/Nginx üzerinden HTTPS. GPU bu web-serving kapasitesi için gerekli değil.
- Veritabanını `pg_dump`/restore ile ve gereken `data/` dosyalarını taşı. Hesaplar, öğrenme durumu ve kayıtlı listeler veritabanındaki şemalarda; yalnız kodu göndermek yeterli değil.
- Mevcut compose dosyası yerel başlangıç içindir; eski “auth yok” yorumu güncel kodu açıklamıyor. Üretimde sırları ayrı environment/secret ile ver, DB'yi internete açma, uygulamayı reverse proxy arkasında tut.
- DB yaklaşık 4,13 GiB, `data/` yaklaşık 682 MiB; `out/` bu bilgisayarda 24 GiB. Bütün deney/export çıktılarını otomatik taşımak gerekmeyebilir; kullanılan dosyaları ayır. 160 GB disk büyüme ve geçici yedekler için rahat pay verir.
- Günlük veritabanı yedeğini sunucudan ayrı bir yere al. Yedeğin geri yüklenmesini test et.
- LLM/TTS ayrı kapasite konusudur. LLM endpoint'i yalnız bilgisayarında çalışıyorsa web'i taşıman bu bağımlılığı kaldırmaz; yazı düzeltme/üretim için bilgisayar açık kalmalı veya model endpoint'i de başka yere taşınmalı. Bu test herhangi bir dış modelin süresini/maliyetini ölçmedi.
- Taşıdıktan sonra aynı harness'i Linux'ta çalıştır: yerel M1 sürelerini VPS için SLA kabul etme. Önce tek kaynak/liste, sonra gerçekten farklı dört hesap/listenin eşzamanlı açılışı ve cover kuyruğu test edilmeli. CPU, uygulama+PostgreSQL RAM'i, disk, swap, job kuyruğu ve yanıt sürelerini izle.

Ham kayıtlar ve tekrar kullanılabilen scriptler [benchmarks/](../benchmarks/) içindedir: `web_capacity.py`, `cover_capacity.py`, `capacity-before.json`, `capacity-after.json`, `capacity-profile.json`, `capacity-active-flows.json`, `cover-calculation.json`. HTTP harness gerçek router'ı çalıştırır fakat yalnız loopback'te sentetik oturum kullanır; internete açılması için tasarlanmamıştır.

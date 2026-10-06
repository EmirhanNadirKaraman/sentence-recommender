# Dört kullanıcı için kapasite ve optimizasyon incelemesi

Bu rapor optimizasyon öncesi sürümü kaydeder. Uygulanan değişiklikler ve yeni
ölçümler [OPTIMIZATIONS.md](OPTIMIZATIONS.md) dosyasındadır.

Ölçüm: 7 Ekim 2026. Mevcut tasarım branch'i üzerinde, macOS/ARM64 geliştirici
bilgisayarında çalıştırıldı. **Öncelik soğuk başlangıç maliyeti ve kullanıcı
başına çoğalan bellektir. Mevcut sürüm için 8 GB VPS rahat kapasite olarak
önerilemez; optimizasyon yapılmadan 16 GB daha güvenli bir başlangıçtır.**
Bu, kiralık sunucuda yapılmış bir kapasite sertifikası değildir.

## Ölçülen sonuçlar

| Senaryo | Sonuç |
|---|---|
| Kullanıcıları sırayla açma, ilk öğrenme sayfası | 23,49 / 57,98 / 72,75 / 95,45 saniye |
| Ardından ilk Reels açılışı | 2,08–3,73 saniye |
| Öğrenme ve Reels önbellekleri dolduktan sonra 4 eşzamanlı istemci, 6 sayfa, 72 istek | 0 hata; 10,60 saniye toplam; medyan 0,230 s; P95 2,612 s; en uzun 3,168 s |
| Bu karışık gezinmede öğrenme sayfası, 12 istek | medyan 1,661 s; P95/en uzun 3,168 s |
| Bu karışık gezinmede Reels, 12 istek | medyan 0,338 s; P95/en uzun 1,494 s |
| Dört kişinin eşzamanlı birer kelime öğrenmesi | kaydetme yanıtı 0,110–0,197 s; video puanları güncellenene kadar 13,08–13,67 s |
| Dört kullanıcı önbelleği tutulurken gözlenen uygulama bellek ayak izi | yaklaşık 5,2 GiB (5.370 MiB); PostgreSQL ve işletim sistemi hariç |
| Dört kişinin aynı anda ilk öğrenme sayfasını açması | 6.000 MiB güvenlik sınırı aşıldı; 6.065 MiB'de test süreci durduruldu; istekler tamamlanmadı |
| Aynı kullanıcının hazır plan bulunan `src=all` öğrenme sayfası | 0,108 s; bu tek ölçüm, soğuk `subtitle` senaryosuyla aynı koşullarda bir A/B testi değildir |
| Video kataloğunun sıkıştırılmamış HTML'i | 861.279 bayt; kapalı ayrıntı tablosu da cevapta bulunuyor |

Sıralı senaryoda 85 GET yanıtının tamamı 200'dü; ayrıca dört kelime işaretleme
işlemi geçici kopyalara yapıldı. 72 istek yalnızca karışık gezinme bölümüdür.
Bu bölüm `/`, `/reels`, `/subtitles`, `/review`, `/words`, `/lists` sayfalarını
kapsar. Öğrenme ve Reels dışındaki sayfaların ilk açılışları da bu bölüme dahildir.
P95 en yakın sıra yöntemiyle hesaplandı; sayfa başına örnek sayısı yalnızca 12'dir.

## Öncelikler

### 1. Canlı öğrenme indeksine düşen yolları azaltma

`Viewer.next_step()` önce kayıtlı planı dener; kaynak/liste/sayım ayarı için
geçerli plan yoksa `_walked()` tüm cümleleri ve `CorpusIndex`'i oluşturur.
Testte `src=subtitle&list=everyday_words` bu ağır yolu kullandı; `src=all`
hazır plandan hızlı yanıt verdi. Sunucunun başlangıçta yaptığı `_warm()`
yalnızca sözlüğü hazırlar; bu indeksin hazır olduğunu garanti etmez.

İlk uygulanacak değişiklik: yayımlanan liste/kaynak kombinasyonları için
planların geçerliliğini ve varlığını kontrol etmek, eksik planları arka planda
hazırlamak. Kaynak filtresinin anlamını değiştirmeden bu yolları hızlandırmak
gerekir. Canlı yol için de sonraki adımı kullanıcı bilgisinin sürümü ve
filtrelerle anahtarlamak düşünülebilir; kelime öğrenme/geri alma/erteleme ve
veri değişikliklerinde geçersizleştirme şarttır.

Sıcak, tek kullanıcı profilinde `builder.peek()` 18.066 aday puanlaması
yapıyordu. Hazır plan veya doğru geçersizleşen sonuç önbelleği bu tekrarın
önüne geçebilir. Kazanç henüz uygulanıp ölçülmedi.

### 2. Kullanıcı başına yinelenen cümle verisini azaltma

`Door` her kullanıcı için ayrı `Application` ve `Viewers` tutar. Her `Viewer`
kaynak ve sayım biçimine göre `_corpora` ve `_scopes` tutar. `Once` aynı
kullanıcının aynı anahtarına gelen istekleri birleştirir; dört farklı
kullanıcının aynı cümleleri ayrı ayrı yüklemesini engellemez. Davet edilen
kullanıcılar, Google kayıtlarının LRU sınırına da dahil değildir.

Öneri: dil ve corpus sürümüyle anahtarlanan değişmez ham cümle/kelime verisini
paylaşmak; kullanıcıya ait bilinen kelimeleri, istisnaları ve değişen indeks
durumunu ayrı tutmak. Ardından büyük Python set/dict ağlarının yerine sayısal
kimlikler ve daha kompakt indeksler değerlendirilmelidir. **Mevcut mutable
`CorpusIndex`'i hesaplar arasında doğrudan paylaşmak doğru değildir.**

Kanıt: dört kullanıcı tutulurken yaklaşık 5,2 GiB uygulama ayak izi ve
eşzamanlı soğuk başlangıçta 6.000 MiB sınırının aşılması. Yeni mimarinin gerçek
tasarrufu ölçülmeden bir yüzde veya yeni kullanıcı kapasitesi vaat edilemez.

### 3. Kelime sonrası ilk video puanı güncellemesini hazırlama

`mark_known()` hızlı döner fakat `_settled()` güncelleme kuyruğunu bekler.
`_rescore_locked()` kelimenin geçtiği videoları bulmak için `_videos_with()`
indeksine, video gruplarına ve puanlama verilerine ihtiyaç duyar. İlk eşzamanlı
işaretleme dalgasında bu iş yaklaşık 13 saniye sürdü.

Öneri: kelime→video indeksini puanlama/corpus hazırlığı sırasında oluşturmak
ve değişmez kısmını paylaşmak; yalnızca etkilenen videoları güncellemek.
Sonraki işaretlemelerin ilk dalgadan daha hızlı olup olmadığını da ölçmek
gerekir. Bu test ikinci işaretleme dalgasını ölçmedi; 13 saniye her kelime için
sabit maliyet olarak yorumlanmamalıdır.

### 4. Video kataloğunu sayfalama veya ayrıntıları sonradan yükleme

Görsel kartlar ilk 24 videoyla sınırlı olsa da kapalı ayrıntı tablosu yaklaşık
1.500 satırı HTML'e koyuyor. Yaklaşık 841 KiB ham cevap, telefonda ağ ve DOM
maliyetini artırabilecek somut bir adaydır. Tabloyu 40–60 satırlık sayfalara
ayırmak veya açılınca yüklemek gerekir. HTTPS proxy'de sıkıştırma da eklenebilir;
sıkıştırma tarayıcıdaki DOM satır sayısını azaltmaz.

## Testin güvenliği ve kapsamı

- Ana cümle veritabanının bağlantılarında `default_transaction_read_only=on`
  zorlandı ve sorguyla doğrulandı.
- Kullanıcı şeması dört ayrı geçici şemaya kopyalandı. Dosyalar da geçici
  dizinlere kopyalandı; asıl hesaplarda kelime, kart veya plan değiştirilmedi.
- Geçici PostgreSQL yalnızca Unix socket dinledi; HTTP adaptörü yalnızca
  `127.0.0.1` üzerinde ve rastgele portta çalıştı. İş bitince kapatılıp silindi.
- Gerçek `Viewer` sayfaları bir `ThreadingHTTPServer` adaptörü üzerinden
  çalıştı. Oturum açma/davet sistemi, tarayıcı JavaScript'i, tüm API uçları,
  YouTube ve dış LLM servisleri bu testte ölçülmedi.
- Dört farklı kullanıcı verisi yerine mevcut kullanıcı durumunun dört kopyası
  kullanıldı. Dört yeni başlayan hesabın davranışı birebir temsil edilmiyor.
- macOS ciddi bellek sıkıştırma/swap etkisi gösterdi. RSS bu yüzden yanıltıcı
  derecede düşüktü; bellek yorumu SDK'deki `ri_phys_footprint` ölçümüne dayanır.
  Sıralı testte ayak izi örneklemesi dördüncü kullanıcının açılışında başladı.
  İlk üç kullanıcının tepe ayak izi ayrı ayrı ölçülmedi.
- Profil araçları zamanları etkiler. Soğuk profilin bazı kümülatif toplamları
  tutarsız olduğundan soğuk maliyet yüzdeleri raporlanmadı; sıcak profil yalnızca
  ilgili yolları ve çağrı sayılarını saptamak için kullanıldı.
- Sıralı testin tüm istekleri bittikten sonra büyük önbelleğin Python kapanış
  GC'si uzadı; yalnızca test süreci kapatıldı. Ham kayıttaki `exit_code=-15`
  buna aittir, HTTP hatasına değil. Tekrar çalıştırılan harness ölçüm tamamlanınca
  çocuk süreci GC beklemeden kapatır; PostgreSQL temizliğini üst süreç yapar.

## Tekrar çalıştırma

Yerel `initdb`, `pg_ctl`, `pg_dump`, `psql` ve projenin PostgreSQL erişimi gerekir.
Komutlar repo kökünden çalıştırılır:

```bash
.venv/bin/python perf/four_readers.py --output /tmp/four-readers-staged.jsonl
.venv/bin/python perf/four_readers.py --mode cold-parallel --output /tmp/four-readers-cold-parallel.jsonl
.venv/bin/python perf/four_readers.py --mode profile --output /tmp/four-readers-profile.jsonl
```

Varsayılan sınır 6.000 MiB uygulama ayak izidir (Linux'ta RSS). Bellek sınırında
testin durması, makinenin gerçek OOM yaşadığı anlamına gelmez. Bu kontrollü
bir kesmedir. Sunucu seçiminden sonra aynı ölçümü Linux VPS üzerinde tekrar
çalıştırmak gerekir. Ham kanıtlar `perf/results/four_readers_2026-10-07.json`
dosyasındadır. Uygulamanın üretim kodunda optimizasyon değişikliği yapılmadı.

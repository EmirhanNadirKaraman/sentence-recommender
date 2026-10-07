# Dil atlası ve tam ekran Reels

7 Ekim 2026 · codex/learning-experience-redesign

Amaç: kullanıcıya öğrenirken becerisinin geliştiğini hissettiren, bir sonraki
adımı anlaşılır ve cazip kılan bir deneyim. Dopamin ölçümü veya bağımlılık
etkisi iddiası yok; bu sürümün öğrenme ve devam oranı üzerindeki etkisi henüz
kullanıcı deneyiyle ölçülmedi.

## Araştırmadan tasarıma

| Birincil kaynak | Bulgudan çıkardığımız tasarım kararı |
|---|---|
| [Sailer & Homner, 2020 — The Gamification of Learning: a Meta-analysis](https://link.springer.com/article/10.1007/s10648-019-09498-w) | Oyunlaştırma öğrenme sonuçlarını destekleyebilir; etki bağlama bağlıdır ve motivasyon/davranış sonuçları daha az kararlıdır. Puanı gezinmeye değil öğrenme eylemlerine bağladık. |
| [Przybylski, Rigby & Ryan, 2010 — A Motivational Model of Video Game Engagement](https://selfdeterminationtheory.org/SDT/documents/2010_PrzybylskiRigbyRyan_ROGP.pdf) | Yetkinlik hissi, seçim özgürlüğü ve anlaşılır kontrol önemlidir. Mevcut i+1 yaklaşımı ve kişiselleştirilmiş video sıralaması korunuyor; kullanıcı görevlerin yolunu seçebiliyor, ödül geri bildirimi kısa ve anlaşılır. |
| [Kivetz, Urminsky & Zheng, 2006 — The Goal-Gradient Hypothesis Resurrected](https://www.columbia.edu/~rk566/Session4/Goal-Gradient_Illusionary_Goal_Progress.pdf) | Hedefe yakınlık çabayı etkileyebilir. Seviye için kalan XP ve görevler için gerçek tamamlanma sayısı gösteriliyor. Bu çalışma dil öğrenimi deneyi değildir; tasarım aktarımı bir çıkarımdır. |
| [When Gamification Spoils Your Learning, 2022](https://arxiv.org/html/2203.16175) | Nitel vaka çalışmasında puan/rekabet uğruna öğrenmeden uzaklaşma örnekleri var. Tekrar puan toplama engeli ve dinleme ödülü sınırı ekledik; yarış sıralaması kullanmıyoruz. |
| [Roediger & Karpicke, 2006 — Test-Enhanced Learning](https://www.psychologicalscience.org/journals/psychological-science/j.1467-9280.2006.01693.x/) | Hatırlama pratiğinin kalıcılık açısından değeri: mevcut aralıklı tekrar korunuyor ve başarılı, zamanı gelmiş hatırlamalar ayrıca ödüllendiriliyor. |

Bunlar mekaniklerin bu uygulamada kesin işe yaradığının kanıtı değildir.
Kaynaklardan çıkarım yaptığımız yerler yukarıda açıkça belirtilmiştir.

## Deneyim

- **Dil atlası:** yedi ışık bir bölgeyi oluşturuyor; her yedi seviyede yeni
  bölge açılıyor. Işıklar, bağlantı yolu ve kalan XP kayıtlı ilerlemeyle değişiyor.
- **Günlük keşif:** beş yeni kelime, bir hatırlama veya özgün cümle, üç dinlenen
  altyazı satırı. Hepsi tamamlanınca +20 XP. Yeni başlayanlar, henüz zamanı
  gelmiş kartı olmadığı gün yazmayı seçebilir.
- **13 başarı:** kelime, hatırlama, dinleme, yazma, mezuniyet, farklı günlerde
  pratik ve günlük bölüm. Kilitli rozetlerde gerçek hedef ve mevcut sayı var.
- **Pratik ritmi:** son yedi gün ve pratik günleri gösteriliyor. Ara vermek
  toplam XP veya kazanılmış rozetleri silmiyor.
- **Geri bildirim:** sıradan eylem küçük XP bildirimi; rozet, seviye veya bölüm
  kısa bir kutlama. Açık Reels çekmecesinde geri bildirim çekmecenin içinde.
  Ses kullanıcı açarsa çalıyor; azaltılmış hareket tercihi destekleniyor.
- **Reels:** 100dvh; gezinme menüsü yok. Mobilde bütün video/altyazı alanı
  yön kilidi, sürükleme ve eşik/hız hesabıyla sonraki/önceki videoya geçiyor.
  Masaüstünde tek tekerlek momentum dizisi tek videoya geçiyor. Komşu iki
  video önceden isteniyor; tek YouTube iframe'i loadVideoById ile korunuyor.
  Kaynak, liste, sıralama ve video adresi korunuyor. Kelimeler/ayarlar native
  dialog içinde, odak ve Escape desteğiyle açılıyor. Embed hatası geçişi kilitlemiyor.

## Kayıt kuralları

| Eylem | XP | Tekrar kuralı |
|---|---:|---|
| Yeni kelimeyi bilinen olarak kaydetmek | 10 | Kelime başına bir kez; eskiden bilinen kelimeye ödül yok |
| Zamanı gelmiş kartı/cümleyi doğru hatırlamak | 12 | Kartın o tekrar zamanı ve gününe göre tek ödül |
| Zamanı gelmiş kart/cümlede yeniden denemek | 3 | Aynı tekrar zamanı ve gününe göre tek ödül |
| Dinlenen farklı altyazı satırı | 4 | Aynı metne aynı gün bir kez, en fazla 20 satır/gün |
| Özgün cümle kaydetmek | 15 | Aynı metne bir kez |
| Kelimenin aralıklı tekrardan mezun olması | 25 | Kelime başına bir kez |
| Üç günlük görevi tamamlamak | 20 | Gün başına bir bölüm |

Altyazı ödülü, istemcinin oynatıcı oynuyor durumunda satır süresinin yaklaşık
%75'i boyunca aldığı zaman örneklerine dayanıyor; ilk 0,8 saniyedeki mevcut
kelime karşılaşması kaydı ayrıca korunuyor. Bu, sunucuda video izlendiğinin
bağımsız doğrulanması veya kullanıcının satırı anladığına dair sınav değildir.
Sunucuda metin tekrar engeli ve günlük üst sınır uygulanır.

JourneyStore yalnızca okuyucunun mevcut state şemasını kullanır. Ortak
corpus değişmez. İki yeni tablo eklenir, mevcut kelimeler/kartlar taşınmaz veya
silinmez. Eski kelime sayısı aynen kalır; atlas bu güncellemeden sonra kaydedilen
pratikle başlar. Gün sınırı APP_TIMEZONE (varsayılan Europe/Istanbul).
Kelime geri alınınca XP ve gerekirse o günün bölüm bonusu geri çekilir;
Yeniden öğrenme yalnızca aynı ödülü ilk gününde geri yükler; öğren–geri al–yeniden öğren döngüsü toplam puanı büyütmez veya yeni günün görevlerini doldurmaz. Kazanılmış rozetler geçmiş başarı
olarak saklanır. Uygulama puan seviyesi dil yeterlilik/CEFR seviyesi değildir.
Çekirdek öğrenme kaydı ile XP kaydı ayrı işlemlerdir; kesinti durumunda tam
atomiklik veya çevrimdışı ödül teslim garantisi sunmuyoruz.

## Doğrulama

- İzole PostgreSQL: ilgili web, corpus, okuyucu, SRS, cümle ve ilerleme testleri: **454 test + 54 alt test başarılı**.
- **7 JavaScript davranış testi başarılı** — node --test tests/reels-controller.test.cjs tests/hearing-progress.test.cjs: gerçek denetleyici koduna
  dokunma/tekerlek dizileri, iptal, sınırlar, başarısız istek, açık çekmece,
  geç hazırlanan oynatıcı ve filtre sürekliliği uygulanır. Dinleme testi durdurma, atlama, tekrar ve 0,5×/2× oynatma hızını da kapsar.
- Tarayıcı: 1280×720 ve 390×844; örnek ekranlarda menüsüz Reels, gerçek embed,
  fare kaydırma ve sürükleme, öğrenme çekmecesi ve kaydedilen ödül doğrulandı.
  Görsel örnek hesabı geçici PostgreSQL kullanır, gerçek öğrenme hesabını değiştirmez. [Örnek atlas ekranı](previews/language-atlas.jpg).
- Dört okuyucu kapasite kontrolünün yeni ham sonucu:
  perf/results/four_readers_journey_2026-10-07.json ve perf/results/four_readers_journey_retry_2026-10-07.json. İkisi de ilk corpus yüklemesinde 180 saniyelik sınırı aştı; başarılı kapasite doğrulaması değildir. Ayrıntılar perf/REELS_JOURNEY.md.

Bir sonraki ürün değerlendirmesi: dört kişinin iki hafta boyunca görevleri
ne kadar doğal tamamladığı, hatırlama başarısı ve ertesi gün geri dönme oranı.
Salt geçirilen süre, öğrenme başarısı yerine kullanılmamalı.

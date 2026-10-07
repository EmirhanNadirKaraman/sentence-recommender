# Arkadaşlarla paylaşım

Bu sürüm küçük, davetli bir arkadaş grubu için hazırlanmıştır. 1.000 kullanıcı
kapasitesi henüz test edilmemiştir. Tasarım dalı: codex/learning-experience-redesign.

## Erişim

Kurulumun `registry.owner()` hesabı (mevcut kurulumda emir) her araca erişir.
Diğer hesaplar Frontier, Learning gaps, Video cover ve Sentence editor sayfalarını
göremez. Cover API'si, cover araması, cümle düzenleme, corpus ekleme ve planı
yeniden hesaplama da sunucuda 403 ile engellenir. Kontrol Viewer/corpus kurulmadan
önce yapılır; menü gizlemek tek başına güvenlik değildir.
Reels, sözlük, tekrar, videolar, kelime listeleri, gelişim ve öğrenme akışları açıktır.
Hazır planı olmayan arkadaşların Learn akışı SQL’den en fazla 2.000 kısa
örnekle başlar; gerçek bilinen kelimeler ve bütün bilinmeyen birimler korunur.
Gösterilen sayılar bu koleksiyona aittir, bütün corpus’un bitirildiği iddia edilmez.
7 Ekim ölçümünde yeni Application/Viewer ile arkadaş hesabının doğrudan Learn
render’ı ilk 1.470 ms, sıcak 10 ms sürdü. Bunlar HTTP/tünel/video gecikmesini
içermeyen yerel ölçümlerdir. Reels ve diğer tam-corpus akışlarının soğuk
performansı ayrıca incelenmelidir. Sahibin tam corpus davranışı korunur.

## Şimdi, bilgisayardan deneme

Uygulama:

```sh
REQUIRE_AUTH=1 INVITE_ONLY=1 .venv/bin/python main.py serve --port 8790 --no-browser
```

Ayrı terminalde:

```sh
cloudflared tunnel --url http://127.0.0.1:8790
```

Tünel açıldıktan sonra uygulamayı `PUBLIC_URL=https://TUNEL_ADRESIN` ortam
değişkeniyle yeniden başlat. Böylece localhost üzerinden hazırlanan davetler de
internet adresini kullanır. Tünel adresi değişirse PUBLIC_URL değerini güncelle.
Terminalin verdiği HTTPS adresinden kendi hesabınla giriş yap. Settings içindeki
Invite a reader formundan arkadaşının öğrenme dilini seçerek davet oluştur.
Davet bağlantısını arkadaşına gönder: kendi kullanıcı adını ve parolasını
belirler; ilerlemesi ayrı tutulur. Daveti mevcut HTTPS adresinden üret, localhost'tan
üretilmiş bağlantı arkadaşının bilgisayarında çalışmaz. Kendi parolanı paylaşma.
Bilgisayar, PostgreSQL, uygulama ve tünel açık kalmalı. Tünel yeniden açılınca adres
değişir; davet token'ının aynı olması eski hostname'i çalışır hale getirmez.

## Sürekli kullanım: sunucu

Başlangıç önerisi: 16 GB RAM, en az 4 vCPU ve 80 GB SSD; tek web süreci.
Sunucuya Docker Compose kur, alan adının A kaydını sunucu IP'sine yönlendir.
80/443 dışarıdan erişilebilir olmalı; PostgreSQL ve uygulama portlarını açma.
HTTPS'i Caddy otomatik yönetir. Kod, tek başına mevcut verileri taşımaz.

Yerel bilgisayarda PostgreSQL 16 client araçlarıyla **tüm veritabanını** dışa aktar:

```sh
PG_DUMP=/opt/homebrew/opt/postgresql@16/bin/pg_dump .venv/bin/python docker/export-db.py
```

Dump; kullanıcı hesaplarını, parola hash'lerini, oturum anahtarını, corpus'u ve
kişisel ilerlemeyi içerir. Gizli tut. Sunucuya kodu, `data/` klasörünü ve dump'ı
aktarmak gerekir. `out/` içindeki büyük deney çıktıları gerekli değil; kullanacağın
ses/görsel dosyalarını ayrıca taşı. `dump/` içine yalnızca restore edilecek tek
`.dump` koy. Restore yalnızca yeni/boş pgdata volume'unun ilk açılışında çalışır.
Mevcut bir volume'u silerek restore etmeye çalışma.

Sunucuda:

```sh
cp .env.production.example .env.production
# APP_DOMAIN ve güçlü, rastgele DB_PASSWORD değerlerini düzenle.
chmod 600 .env.production
docker compose --env-file .env.production -f compose.production.yml config --quiet
docker compose --env-file .env.production -f compose.production.yml up -d --build
```

Kurulumun sahibi restore edilmiş ve parola belirlemiş olmalı. Yoksa uygulama
REQUIRE_AUTH nedeniyle açılmaz. Boş kurulumda sahibini ayrıca oluştur:

```sh
docker compose --env-file .env.production -f compose.production.yml run --rm app python main.py reader add emir --home data
docker compose --env-file .env.production -f compose.production.yml run --rm app python main.py reader password emir
```

Bunlar mevcut sahibin olduğu restore edilmiş veritabanında tekrar çalıştırılmaz.
Parola komutu interaktif sorar; parolayı shell komutuna yazmazsın. Boş veritabanında
corpus da yoktur: çalışan uygulama eski içerikleri kendiliğinden getirmez.

`https://ALAN_ADIN/healthz` süreç sağlığını kontrol eder; corpus/veritabanı
hazır olduğunu kanıtlamaz. Giriş, Reels, sözlük, tekrar ve ayrı davetli hesabında
ilerlemenin ayrılığını dene. Owner araçlarının davetlide 403 döndüğünü de doğrula.
Model üretimi ayrı bir model endpoint'ine ihtiyaç duyar; bilgisayardaki model
sunucuya taşınmış sayılmaz. Bu sürüm model servisinin kurulumunu içermiyor.

## Yedekleme ve güncelleme

```sh
mkdir -p backups
backup_file="backups/full-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose --env-file .env.production -f compose.production.yml exec -T db sh -c 'pg_dump -Fc --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$backup_file"
chmod 600 "$backup_file"
```

Başarılı çıktıyı sunucudan ayrı bir yerde sakla; restore'u ayrı bir test
veritabanında doğrula. `data/` dosyalarını da yedekle. Güncellerken `up -d --build`
kullan; `down -v` veritabanını siler. Başarısız pg_dump çıktısını sağlam yedekle
karıştırma; komutun exit code'unu kontrol et ve mevcut tek yedeğin üzerine yazma.

## Neden henüz Celery/RabbitMQ/Redis/Kafka yok?

Bu ilk sürümde pahalı araçlar owner ile sınırlı. Yeni broker ve worker servislerinin
kurulum/bakım maliyetini paylaşımı bekletecek şekilde eklemiyoruz. Mevcut süreç içi
corpus paylaşımı ve single-flight korunuyor. Owner hesaplaması yine ortak CPU'yu
kullanabilir; arkadaşların kullandığı saatte büyük Frontier/cover hesaplarını
başlatmamak faydalıdır. Misafirlere cover açılmadan önce dayanıklı job tablosu,
idempotent Celery worker, broker ve iş durumunu gösteren UI eklenmeli. Redis ise
birden çok web sürecine geçerken küçük sonuç cache'leri için değerlendirilir.

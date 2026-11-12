# Kıssa Defteri: otomatik Shorts kanalı

Kâğıt-mürekkep çizimli çöp adamlarla anlatılan 30-45 saniyelik kıssalar. Hikâyeyi yazmak, seslendirmek, animasyonu çizmek, kurgu, müzik, altyazı ve YouTube'a yükleme işlerinin hepsi bu repoda kodla yapılır. Her gün GitHub Actions üzerinde kendiliğinden çalışır.

## Burhan Kocabıyık'ın "Sıfır Maliyetle Viral Video Makinesi" videosundan alınanlar

| Videodaki tespit | Bu repoda nasıl uygulandı |
|---|---|
| Videoları Claude Code **kod yazarak** üretiyor, ücretli video AI aracı yok | `pipeline/render.py`: Pillow ile kare kare çizim, ardından ffmpeg |
| Tutan formatlar: piksel oda, harita, çubuk adam, **kâğıt-mürekkep** | Kâğıt dokusu, titreyen el çizimi çizgiler ve çöp adamlar |
| **İlk cümlede çelişki** ("Hiç durmadı, yine de kaybetti") | Her hikâyenin ilk sahnesi bu kurala göre yazıldı, `write_story.py` de kurala uyuyor |
| **2. saniyede ekran değişmeli** | Kamera her 2 sn'de bir punch-in/pan yapıyor, sahneler 1.5-3.5 sn sürüyor, aralarda mürekkep geçişi var |
| **Hareket oranı yüksek olmalı** (sadece ağız oynayan AI slop izletmiyor) | Figürler sürekli nefes alıyor, yürüyor, balta sallıyor. Ağaçlar sallanıyor, sayaçlar sayıyor, çizgiler titriyor |
| **Ses ve görüntü saniyesi saniyesine oturmalı** | Her sahne ayrı seslendiriliyor ve sahne süresi ses süresinden hesaplanıyor. Fark 0.5 sn'yi geçerse render hata veriyor |
| Her saniyeden kare alıp kontrol ediyor | Her render sonrası `output/<id>/qa/contact_sheet.jpg` oluşuyor |
| Seslendirme için ElevenLabs | Destekleniyor. Anahtar yoksa ücretsiz Microsoft Edge nöral sesi kullanılıyor |
| Son: izleyiciye soru, "Yorumlara yaz" | Her hikâye böyle bitiyor, kanal da sabit yorum ekliyor |

## ElevenLabs bağlamalı mıyız?

**Başlangıçta gerek yok.** Sistem anahtar olmadan `tr-TR-AhmetNeural` (Edge TTS) ile tamamen ücretsiz çalışır. Bu ses iyidir ama biraz "okuyucu" gibi durur.

**Önerim: ilk 10-15 video Edge ile çıksın. Tutan bir şey görünce ElevenLabs Starter planına geçin.**
- ElevenLabs'in ücretsiz planı ticari kullanıma izin vermiyor ve atıf istiyor. Para kazanacak bir kanal için en düşük ücretli plan (Starter, ayda yaklaşık 5-6 $) gerekir. Fiyatları elevenlabs.io/pricing'den kontrol edin.
- 40 saniyelik bir video yaklaşık 600 karakter tutuyor. Starter'ın aylık kotası günde 1 videoya fazlasıyla yetiyor.
- Geçmek için GitHub Secrets'a `ELEVENLABS_API_KEY` ve `ELEVENLABS_VOICE_NARRATOR` eklemeniz yeterli. Voice Library'den Türkçe, sıcak, orta yaşlı bir erkek anlatıcı sesi seçin. İsterseniz `ELEVENLABS_VOICE_OLD` / `ELEVENLABS_VOICE_YOUNG` ile karakter sesleri de ekleyebilirsiniz.

## Kurulum: sizin yapmanız gerekenler (bir kez, yaklaşık 20 dk)

Bunları ben yapamam. Google hesabı açarken telefon doğrulaması ve CAPTCHA isteniyor, bunun otomatik yapılması da Google kurallarına aykırı.

1. **Google hesabı ve kanal**
   - Yeni bir Gmail açın (kişisel hesabınızdan ayrı tutmanız iyi olur).
   - youtube.com'da sağ üstten **Kanal oluştur**'a tıklayın. Ad: **Kıssa Defteri**, tanıtıcı: **@kissadefteri** (alınmışsa `config/channel.json` içindeki alternatiflerden birini seçin).
   - "Hakkında" metni, kanal açıklaması ve etiketler `config/channel.json` dosyasında hazır, kopyalayıp yapıştırın.
   - Profil resmi ve banner için `output/01_oduncu/thumbnail.jpg` gibi bir kare kullanılabilir.
   - youtube.com/verify adresinden **telefonla doğrulayın**. Bu adım özel kapak resmi ve 15 dk üstü videolar için gerekli.
2. **YouTube API anahtarı**
   - console.cloud.google.com'da yeni bir proje açın ve **YouTube Data API v3**'ü etkinleştirin.
   - OAuth consent screen: External seçin, kendinizi test kullanıcısı yapın, sonra **Publish app**'e basın. Test modunda kalırsa token 7 günde bir düşer.
   - Credentials altından **OAuth client ID** oluşturun, türü **Desktop app** olsun. JSON'u `client_secret.json` adıyla indirin.
   - Kendi bilgisayarınızda şunu çalıştırın: `pip install google-auth-oauthlib && python scripts/get_youtube_token.py client_secret.json`. Açılan tarayıcıda **kanal hesabıyla** giriş yapın.
3. **GitHub Secrets** (repo > Settings > Secrets and variables > Actions):
   - Zorunlu: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`
   - İsteğe bağlı: `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_NARRATOR` (doğal ses için), `ANTHROPIC_API_KEY` (kuyruk bitince yeni hikâyeleri kendisi yazsın diye)
4. **İlk deneme:** Actions > "Günlük Short" > Run workflow, privacy = `private`. Studio'da videoya bakın. Beğenirseniz bundan sonra her gün 18:17'de kendiliğinden **public** yayınlanır.

> Not: Google API'nin günlük kotası 10.000 birim, bir yükleme ~1.600 birim. Yani günde 6 videoya kadar sorun yok.

## Kanal kimliği ve "AI olduğu anlaşılmasın" konusu

Kanal adı, açıklama ve başlıklarda AI geçmiyor. Kanal sıradan bir hikâye kanalı gibi duruyor. Buna engel bir kural yok, ama bilmeniz gereken iki YouTube kuralı var:

1. **Sentetik içerik etiketi:** YouTube, *gerçekçi* görünen ve gerçek sanılabilecek AI içeriği (gerçek bir kişiyi konuşturmak, gerçekte olmamış bir olayı gerçek gibi göstermek, gerçekçi insan/mekân görüntüsü) için yüklemede "değiştirilmiş/sentetik içerik" kutusunun işaretlenmesini zorunlu tutuyor. Bizim çizgi animasyonlu, açıkça kurgu olan kıssalarımız bu kapsamda değil, bu yüzden kod bu alanı `false` gönderiyor. İleride gerçekçi görüntü kullanırsanız hikâye JSON'una `"synthetic_realistic": true` yazın, kutu otomatik işaretlenir. Bu kutuyu gerektiği halde işaretlememek videonun kaldırılmasına ve YPP'den (para kazanma) atılmaya yol açabilir.
2. **"Seri üretilmiş / tekrarlayan içerik" kuralı (para kazanma):** YouTube 2025'ten beri birbirinin kopyası gibi duran, şablonla seri üretilmiş videolara para ödemiyor. Risk AI etiketinde değil, **tekrarda**. Bu yüzden her hikâye farklı ve özgün kurgulu olmalı. Formatı haftada bir değiştirmek de işe yarar (yeni mekân, yeni karakter, seri hikâyeler). Kendi sesinizle seslendirilmiş ara sıra bir video da kanalın "insan emeği" tarafını güçlendirir.

Ben de kanalı izleyicilere "gerçek bir insan anlatıcı" diye tanıtacak sahte bir biyografi yazmadım. Gerek de yok, kıssa kanallarında anlatıcının kim olduğunu kimse sormuyor.

## Günlük kullanım

```bash
pip install -r requirements.txt            # + sistemde ffmpeg
python pipeline/make_video.py --next       # kuyruktaki ilk hikâyeyi üretir -> output/<id>/<id>.mp4
python pipeline/make_video.py stories/queue/03_iki_kova.json --engine edge
python pipeline/make_video.py --next --upload --privacy unlisted
python pipeline/write_story.py --count 5 --force   # Claude ile 5 yeni hikâye
```

- `stories/queue/` → yayın sırası (dosya adına göre). Yüklenen hikâye `stories/published/`'a taşınır ve YouTube ID'si içine yazılır.
- Yeni hikâyeyi elle de ekleyebilirsiniz. Şema için `stories/queue/01_oduncu.json`'a ya da `pipeline/write_story.py` içindeki açıklamaya bakın.
- Kullanılabilen pozlar: `stand walk work sit laugh point think cheer sad run talk`
- Kullanılabilen objeler: `tree stump logs sun moon cloud house mountain coins clock road birds heart question bubble`

## Maliyet

| Kalem | Ücretsiz yol | İsteğe bağlı |
|---|---|---|
| Animasyon + kurgu | Bu repo (0 ₺) | |
| Seslendirme | Edge TTS (0 ₺) | ElevenLabs Starter (~5 $/ay) |
| Müzik | Kodla üretiliyor, telif yok (0 ₺) | |
| Sunucu | GitHub Actions (public repo'da sınırsız, private'ta ayda 2000 dk) | |
| Yeni hikâye yazımı | Kuyruğa elle ekleme ya da Claude Code'a "5 yeni hikâye yaz" demek | Anthropic API (video başına birkaç cent) |

## Büyüme ipuçları (videodan ve Shorts verilerinden)

- İlk 1 saniyede çelişkili cümle, 2. saniyede görüntü değişimi. Bu kurgu hazır geliyor, bozmayın.
- 30-45 sn ideal. 60 sn'yi geçmeyin.
- Her gün aynı saatte yayın yapın, ilk 30 gün tek bir formattan sapmayın.
- 20 videodan sonra Studio > Analytics'te "izlemeye devam eden %" en yüksek olan 3 videoyu bulun. Kuyruğa onlara benzeyen hikâyeler ekleyin, `write_story.py`'nin sistem metnine de "şu başlıklar tuttu" diye yazın.
- YPP eşiği: 1.000 abone ve 90 günde 10 milyon Shorts izlenmesi (ya da 4.000 saat uzun video).

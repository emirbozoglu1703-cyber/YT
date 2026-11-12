# Kıssa Defteri: AI takımıyla günde 10 Short

Kesik kâğıt (paper cut-out) stilinde, renkli karakterlerle anlatılan 30-45 saniyelik **özgün** mini hikâyeler.
Her gün 11 ajanlık bir takım 10 video planlıyor, üretiyor, denetliyor ve gün içindeki en iyi saatlere zamanlıyor.

## Takım

```
                         ┌──────────────────────┐
                         │     BAŞ DENETÇİ      │  denetçileri denetler, son onay,
                         │  (her video için)    │  gerekirse aşamayı geri gönderir
                         └──────────┬───────────┘
      ┌──────────────┬──────────────┼──────────────┬──────────────┐
 Strateji Den.   Senaryo Den.    Ses Den.      Görsel Den.    Yayın Den.      ← DENETÇİLER (red → tekrar, en fazla 3 tur)
      │              │              │              │              │
 Strateji &      Senarist       Ses Ajanı     Görsel         Yayın Ajanı     ← AJANLAR
 Program                       (ElevenLabs)   Yönetmen
 10 saat +       özgün hikâye   seslendirme,   sahne düzeni   başlık, açıklama,
 10 hikâye özeti metni          okunuş, ayar   → render       etiket, zamanlama
```

| Ajan | Ne yapar | Denetçisi neye bakar |
|---|---|---|
| **Strateji & Program** | Kanalın geçmiş izlenme verisine bakıp günün 10 yayın saatini ve 10 farklı hikâye özetini çıkarır | Saat kuralları, tema çeşitliliği, bilinen masal kopyası, hassas konu |
| **Senarist** | Özetten özgün hikâye yazar (çelişkili kanca, twist, ders, soru) | Kanca gücü, özgünlük, yapı, **Türkçe yazım**, mantık. Programatik kontrol: kelime/satır sayısı, yasaklı kelime |
| **Ses Ajanı** | Her satırın okunuşunu ("36" → "otuz altı"), konuşmacısını ve ElevenLabs duygu ayarlarını belirler, sesi üretir | Ölçümler: konuşma hızı, ses patlaması, uzun duraklama, **sesin yazıya dökülmüş hali ile senaryonun benzerliği** (ElevenLabs STT) |
| **Görsel Yönetmen** | Her satır için sahne tasarlar (karakter, poz, obje, kamera, yazı); render motoru çizer | **Render edilmiş kareleri görerek** çakışma, taşma, okunabilirlik, anlam uyumu, karakter sürekliliği, ekrandaki yazım hataları |
| **Yayın Ajanı** | Başlık, açıklama, etiket ve ilk yorumu yazar, videoyu saatine zamanlar | Başlık uzunluğu, yanıltıcılık, yazım, AI kelimesi geçmemesi, spam etiket |
| **Baş Denetçi** | Bitmiş videonun karelerini, ses tablosunu, metinleri ve **tüm denetim kayıtlarını** görür | Her denetçiyi tek tek puanlar (kaçırdı mı, gereksiz mi reddetti?). Onay verir ya da sorunlu aşamayı talimatla geri gönderir |

Akış: bir denetçi reddederse, ajan geri bildirimle aynı işi baştan yapar (en fazla 3 tur). Baş denetçi bir aşamayı en fazla 2 kez geri gönderebilir; o aşamadan sonraki her şey yeniden üretilir. Yine onay çıkmazsa tamamen yeni bir senaryoyla bir kez daha denenir. O da olmazsa **video yayınlanmaz**, kalitesiz video yüklenmez.

Ayrıca programatik bir **düzen denetçisi** (`render.lint_scene`) her sahneyi render öncesi kontrol eder: ekrandan taşma, karakter çakışması, ağaç/ev gibi objelerin karaktere binmesi, balon ile büyük yazının çakışması. Düzeltebildiğini düzeltir, gerisini görsel denetçiye bildirir.

## Günlük işleyiş (GitHub Actions)

| Saat (TR) | İş |
|---|---|
| 04:23 | `plan`: strateji ajanı + denetçisi günün planını çıkarır, önceki videoların izlenmelerini YouTube'dan çeker |
| 04:25-05:30 | `produce` ×10 (4'er paralel): her video kendi ajan zincirinden geçer, gizli olarak yüklenip saatine zamanlanır |
| ~05:30 | `finalize`: `reports/<tarih>.md` günlük rapor (başlıklar, kalite puanları, denetim turları, maliyet), `data/history.jsonl` güncellenir |
| 08:07-00:07, 2 saatte bir | `comments`: yayına giren videolara kanalın ilk yorumunu yazar (zamanlanmış gizli videoya yorum yazılamıyor) |

### Yayın saatleri nasıl belirleniyor?
Türkiye'ye özel saatlik Shorts verisi kamuya açık değil. Bu yüzden başlangıç saatleri genel kullanıcı davranışına göre seçildi (`config/schedule.json`):
- **Hafta içi:** 07:40, 10:20, 12:20, 13:40, 16:10, 17:50, 19:10, 20:20, 21:30, 22:45 (sabah işe/okula gidiş, öğle arası, iş çıkışı ve en yoğun akşam bandı 20-23)
- **Hafta sonu:** 09:20'den 22:50'ye kadar gün boyuna yayılmış

Shorts yayından sonraki 1-2 saatte ilk test kitlesine gösterildiği için saatler yoğunluğun hemen öncesine konuldu. Strateji ajanı her gün kanalın **kendi** verisine bakar (hangi saatte yayınlanan video 48 saatte kaç izlendi) ve saatleri günde en fazla 2 dilim / 45 dk kaydırarak öğrenir. YouTube Studio → Analytics → "İzleyicileriniz YouTube'da ne zaman" grafiği oluşunca (birkaç hafta sonra) `config/schedule.json`'a o saatleri yazmanız da iyi olur.

## Kurulum (bir kez)

1. **YouTube kanalı:** Gmail açın → YouTube → Kanal oluştur → ad **Kıssa Defteri**. Hakkında metni `config/channel.json`'da. youtube.com/verify ile telefon doğrulaması yapın.
2. **YouTube API:** console.cloud.google.com → yeni proje → *YouTube Data API v3*'ü etkinleştirin.
   - OAuth consent screen: External seçin, sonra **Publish app** deyin. Test modunda kalırsa token 7 günde düşer.
   - Credentials → OAuth client ID → *Desktop app* → JSON'u indirin.
   - Kendi bilgisayarınızda: `pip install google-auth-oauthlib && python scripts/get_youtube_token.py client_secret.json`
3. **Anthropic API anahtarı** (ajanların beyni): console.anthropic.com → API Keys.
4. **ElevenLabs:** elevenlabs.io → API key. Voice Library'den Türkçe sesler seçip Voice ID'lerini alın (anlatıcı + isteğe bağlı yaşlı / genç / kadın / çocuk).
5. **GitHub → Settings → Secrets and variables → Actions:**
   - Secrets: `ANTHROPIC_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_NARRATOR`, (isteğe bağlı) `ELEVENLABS_VOICE_OLD`, `_YOUNG`, `_WOMAN`, `_CHILD`
   - Variables (isteğe bağlı): `AGENT_MODEL`, `REVIEW_MODEL` (maliyet için, aşağıya bakın), `ELEVENLABS_MODEL`
6. **Bu branch'i `main`'e merge edin.** Zamanlanmış işler sadece varsayılan branch'te çalışır.
7. **İlk deneme:** Actions → "Günlük AI Takımı" → Run workflow → `daily_videos: 2`, `upload: false`. Artifact'lardan videoları ve `final_sheet.jpg` karelerini indirip bakın. Beğenirseniz `upload: true` ile bir kez daha deneyin. Sonra her gün kendiliğinden çalışır.

## Maliyet (yaklaşık, günde 10 video)

| Kalem | Tahmin | Not |
|---|---|---|
| Anthropic (11 ajan, Opus 5.5) | video başı ~0,4-0,8 $ → **ayda ~120-240 $** | Her video ~13-25 çağrı (retry'lere göre). `REVIEW_MODEL=claude-sonnet-5-5` ile denetçiler ucuzlar, ama denetim kalitesi düşebilir. Karar sizin. |
| ElevenLabs | ayda ~200-250 bin karakter | `eleven_multilingual_v2` ile **Pro** plan gerekir. `ELEVENLABS_MODEL=eleven_flash_v2_5` karakter başına yarım kredi harcar, **Creator** plana sığabilir ama kalite biraz düşer. Planları elevenlabs.io/pricing'den kontrol edin. |
| YouTube API | 0 ₺ | Haziran 2026'dan beri yüklemelerin ayrı bir kotası var: günde 100 yükleme. 10 video sorun değil. |
| GitHub Actions | Public repo: 0 ₺. Private: ayda ~1.500-2.000 dk | Private repoda ücretsiz 2.000 dk sınırına yaklaşır. |

Her günlük raporda gerçek ajan maliyeti yazar.

## ⚠️ Günde 10 video için bilmeniz gerekenler
- **Seri üretim kuralı:** YouTube, birbirine benzeyen seri üretilmiş videolara para ödemiyor (YPP "tekrarlayan / özgün olmayan içerik" politikası). Asıl risk budur. Ajanlara her videonun özgün hikâye, farklı tema ve mekânla olmasını şart koştum. Yine de ilk 2-3 hafta **günde 3-5 video** ile başlayıp raporlara bakmanızı, kaliteden eminseniz 10'a çıkmanızı öneririm (`config/schedule.json` → `daily_videos`).
- **Sentetik içerik etiketi:** Çizgi/animasyon hikâyelerde gerekmiyor, kod `false` gönderiyor. İleride gerçekçi görüntü eklenirse açılmalı.
- **Kanal kimliği:** Ad, açıklama, başlık ve yorumlarda AI geçmiyor. Bunu senaryo, yayın denetçisi ve baş denetçi ayrıca kontrol ediyor.

## Yerel kullanım

```bash
pip install -r requirements.txt   # + ffmpeg
python pipeline/team.py demo                              # API anahtarı olmadan tüm takım akışını sahte ajanlarla dener
python pipeline/make_video.py stories/samples/bakkal_ferit.json --engine edge   # tek hikâye, ajansız
python pipeline/team.py plan                              # gerçek ajanlarla bugünün planı
python pipeline/team.py produce --index 0 --no-upload     # planın 1. videosu, yüklemeden
```

Dosyalar:
- `pipeline/agents/roles.py`: ajanların görev tanımları (prompt'lar). Kanalın tonunu değiştirmek için burayı düzenleyin.
- `pipeline/team.py`: orkestratör, denetim döngüleri
- `pipeline/render.py`: kesik kâğıt render motoru + düzen denetçisi
- `pipeline/tts.py`: ses, kelime zamanları, ölçümler
- `config/schedule.json`: video sayısı ve saatler
- `reports/`, `data/history.jsonl`: günlük raporlar ve performans geçmişi

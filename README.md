# Kıssa Defteri: kukla tiyatrosu Shorts kanalı

Ahşap bir sahnede, kırmızı perdeler arasında, çubuklu karton kuklalarla oynanan 30-45 saniyelik **özgün** Türkçe mini oyunlar.
Her gün 11 Claude Code ajanından oluşan bir takım oyunları yazıyor, seslendiriyor, sahneliyor ve denetliyor. Onaylananlar gün içindeki saatlerine zamanlanıp YouTube'a yükleniyor.

## Format (kanalın imzası)
- **Açılış:** bir kukla seyirciye dönüp çarpıcı tek bir cümle söyler ("Bu adam kimseye bedava ekmek vermez. Bana bile!").
- **Diyalog:** hikâye kuklaların konuşmasıyla ilerler. Konuşan kuklanın ağzı kelimelere göre oynar, üstüne spot ışık düşer.
- **Perde:** mekân değişince perde kapanıp açılır. Aynı mekânda kamera genel / orta / yakın plan arasında geçiş yapar.
- **Kapanış:** bir kukla seyirciye seçim sorusu sorar ("Sen olsan söyler miydin, saklar mıydın?"). Kuklalar selam verir, perde kapanır, alkış gelir.
- **Altyazı:** seyirci bölümünde, konuşanın adıyla. Kelimeler söylendikçe belirir.
- **Müzik:** kodla üretilen müzik kutusu melodisi (telifsiz), perde hışırtısı ve alkış efektleri.

## Takım (`.claude/agents/`)

| Ajan | Denetçisi | Çıktı |
|---|---|---|
| `strateji`: günün saatleri ve 10 farklı brief | `strateji-denetcisi` | `data/plans/<tarih>.json` |
| `senarist`: kadro + replikler | `senaryo-denetcisi` (yazım, kanca, özgünlük, mantık) | `script.json` |
| `ses-ajani`: ElevenLabs okunuş ve duygu ayarları | `ses-denetcisi` (hız, patlama, duraklama, sesi yazıya döküp karşılaştırma) | `voice.json`, `line*.mp3` |
| `gorsel-yonetmen`: fon, ışık, kamera, kukla yerleri ve hareketleri | `gorsel-denetci` (önizleme karelerine bakarak) | `staging.json`, `preview.jpg` |
| `yayin-ajani`: başlık, açıklama, etiket, ilk yorum | `yayin-denetcisi` | `meta.json` |
| `bas-denetci`: bitmiş videoyu ve **tüm denetçileri** denetler, son onay ya da geri gönderme | – | `approval.json` |

- Bir denetçi reddederse ajan geri bildirimle yeniden yapar (en fazla 3 tur).
- Baş denetçi sorunlu aşamayı 2 kez geri gönderebilir. Onay çıkmazsa video **yüklenmez**.
- Akışı `/gunluk-yayin` skill'i yönetir (`.claude/skills/gunluk-yayin/SKILL.md`). Videolar 3'erli dalgalar halinde paralel üretilir.
- Ajanların kullandığı araçlar `pipeline/tools.py` içinde. Her aşamanın programatik kontrolleri, render ve paketleme burada.

## Günlük akış

```
04:23  Zamanlanmış Claude Code oturumu açılır → /gunluk-yayin
       plan → (senaryo → ses → sahne → render → metin → baş denetçi) × 10 → queue/<tarih>/ paketleri → push
       ↓ (push GitHub Actions'ı tetikler)
       "Onaylı videoları YouTube'a zamanla": paketleri render eder, her birini saatine zamanlayarak yükler, data/history.jsonl'a yazar
08-24  "İlk yorum + izlenme istatistikleri" (2 saatte bir): yayına giren videoya ilk yorumu yazar,
       48 saati geçenlerin izlenmesini çeker → strateji ajanı ertesi gün saatleri ve temaları buna göre ayarlar
```
YouTube anahtarları sadece GitHub Secrets'ta durur. Claude oturumu YouTube'a hiç dokunmaz, sadece onaylı paketi push eder.

## Kurulum
1. **YouTube kanalı** ve **YouTube API** (OAuth). Adımlar aşağıda, `scripts/get_youtube_token.py`.
   GitHub Secrets'a şunları ekleyin: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
2. **ElevenLabs:**
   - API anahtarı bu Claude Code ortamının *Network secrets* bölümüne kaydedilir (`api.elevenlabs.io`, başlık `xi-api-key`). Repoya yazılmaz.
   - Voice Library'den Türkçe konuşabilen 6 ses seçin ve ID'lerini `config/voices.json` dosyasına yazın: anlatıcı, erkek, yaşlı, genç, kadın, çocuk.
3. **Zamanlanmış görev:** her gün 04:23'te `/gunluk-yayin` çalıştıran bir Claude Code görevi.
4. Bu branch'i `main`'e merge edin.

YouTube OAuth adımları: console.cloud.google.com → yeni proje → *YouTube Data API v3*'ü etkinleştirin.
OAuth consent screen: External seçin, sonra **Publish app** deyin. Credentials → OAuth client ID → *Desktop app*.
Kendi bilgisayarınızda: `pip install google-auth-oauthlib && python scripts/get_youtube_token.py client_secret.json`

## Bilmeniz gerekenler
- **Claude kullanım limiti:** 10 video × ~15-25 ajan çağrısı, günde birkaç yüz ajan çalışması eder. Planınızın limitine takılabilir.
  Başlangıçta günde 3-5 video önerilir (`config/schedule.json` → `daily_videos`, ya da `/gunluk-yayin 3`).
- **ElevenLabs:** günde 10 video ayda ~200-250 bin karakter eder (Pro plan). `config/voices.json` → `"model": "eleven_flash_v2_5"` yarı kredi harcar.
- **YouTube:** yüklemelerin ayrı bir kotası var (günde 100), 10 video sorun değil. Seri üretim politikası nedeniyle her oyunun özgün olması şart. Ajanlar buna göre yazılı.
- **Branch'ler:** her günlük oturum kendi `claude/...` branch'ine push eder. Yükleme bittikten sonra bu branch'ler GitHub'dan silinebilir.

## Elle kullanım
```bash
pip install -r requirements.txt     # + ffmpeg
python pipeline/make_video.py stories/samples/firinci_nuri.json --engine elevenlabs   # hazır örnek oyun
python pipeline/tools.py --help                                                     # ajan araçları
```

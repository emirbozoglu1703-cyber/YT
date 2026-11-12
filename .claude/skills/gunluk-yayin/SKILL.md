---
name: gunluk-yayin
description: Kıssa Defteri günlük yayın akışı. AI takımını (strateji, senarist, ses, görsel, yayın ajanları + denetçileri + baş denetçi) çalıştırıp günün kukla tiyatrosu Shorts videolarını üretir, denetletir ve yüklenmek üzere paketler. "Günlük yayını yap", "bugünün videolarını üret", "/gunluk-yayin" dendiğinde kullan.
---

# Günlük yayın: AI takımını yönet

Sen bu akışta **orkestratörsün**: işi kendin yapmazsın, ajanları sırayla/paralel çağırır, kararlarını okur, döngüleri yönetirsin.
Her ajan çıktısını dosyaya yazar ve sana tek satır özet döner. Dosya içeriklerini gereksiz yere kendi bağlamına okuma.

Ajanlar (`.claude/agents/`): `strateji`, `strateji-denetcisi`, `senarist`, `senaryo-denetcisi`, `ses-ajani`, `ses-denetcisi`,
`gorsel-yonetmen`, `gorsel-denetci`, `yayin-ajani`, `yayin-denetcisi`, `bas-denetci`.

Argüman: isteğe bağlı video sayısı (ör. "3"). Verilmezse `config/schedule.json` → `daily_videos`.

## 0. Hazırlık
1. `TARİH=$(TZ=Europe/Istanbul date +%F)`. Tarih bugünden farklı verilmediyse bunu kullan.
2. `pip install -q -r requirements.txt` (ffmpeg kurulu olmalı: `ffmpeg -version`).
3. ElevenLabs testi: `python -c "import sys; sys.path.insert(0,'pipeline'); import tts; print(tts.synth('Merhaba.', 'narrator', '/tmp/t.mp3', 'elevenlabs'))"`.
   Başarısızsa (401/403, ses ID yok, ağ engeli) DUR ve kullanıcıya nedeni yaz. Sahte/sessiz ses ile video ÜRETME.
4. Video sayısı argümanla verildiyse `config/schedule.json`'daki `daily_videos` yerine onu kullan (dosyayı değiştirme; ajanlara söyle).

## 1. Plan (strateji döngüsü, en fazla 3 tur)
- `strateji` ajanını çağır: "TARİH=<T>, video sayısı=<N>. Planı yaz." (sonraki turlarda: "Denetçi geri bildirimi: data/plans/<T>.review_r<k>.json dosyasını oku ve düzelt.")
- `strateji-denetcisi` ajanını çağır: "TARİH=<T>, TUR=<k>."
- `data/plans/<T>.review_r<k>.json` → `approved` true ise devam; değilse bir sonraki tur. 3 turda onay yoksa son planla devam et ve rapora yaz.

## 2. Her video için üretim
Her video için `python pipeline/tools.py new <T> <i>` → klasör `work/<T>/<NN>` (aşağıda KLASÖR).
Videoları **3'erli dalgalar** halinde işle: bir dalgadaki videoların aynı aşamadaki ajanlarını AYNI mesajda paralel çağır (arka planda), hepsi bitince bir sonraki aşamaya geç.

Her aşama bir **denetim döngüsüdür** (en fazla 3 tur):
```
tur k: ajan çalışır (k>1 ise "reviews/<aşama>_r<k-1>.json dosyasındaki geri bildirimi uygula")
       denetçi çalışır ("TUR=<k>") -> reviews/<aşama>_r<k>.json
       approved=true -> sonraki aşama | false -> tur k+1
3 turda onay yoksa: o video için tüm akışı yeni bir senaryoyla BİR kez baştan dene; yine olmazsa video iptal (yüklenmez).
```
Aşamalar ve sıra (ajan → denetçi → dosya):
1. **Senaryo**: `senarist` → `senaryo-denetcisi` → `reviews/script_r<k>.json`
2. **Ses**: `ses-ajani` → `ses-denetcisi` → `reviews/voice_r<k>.json`  (sahneleme ses sürelerine bağlı, önce ses)
3. **Sahne**: `gorsel-yonetmen` → `gorsel-denetci` → `reviews/visual_r<k>.json`
4. **Render**: kendin çalıştır: `python pipeline/tools.py render <KLASÖR>` (≈2-3 dk). Hata verirse görsel aşamasına geri dön.
5. **Yayın metni**: `yayin-ajani` → `yayin-denetcisi` → `reviews/meta_r<k>.json`
6. **Baş denetçi**: `bas-denetci` → `approval.json`
   - `approved: true` → `python pipeline/tools.py package <KLASÖR>`
   - `false` → `send_back_to` aşamasına talimatla geri dön ("approval.json'daki baş denetçi talimatını uygula"), o aşamadan sonraki her şeyi yeniden yap
     (script → ses, sahne, render, metin; voice → render; visual → render; publish → metin), sonra baş denetçiyi tekrar çağır.
     Baş denetçi en fazla 2 kez geri gönderebilir; üçüncüde onay yoksa video iptal.

Ajan çağırırken mesajda her zaman şunları ver: KLASÖR yolu, TUR numarası, varsa hangi geri bildirim dosyasını okuyacağı.

## 3. Teslim
1. `python pipeline/tools.py status <T>` ile durumu gör.
2. `git add queue/<T> data/plans` → commit ("Günlük yayın <T>: N video") → bu oturumun çalışma branch'ine push et.
   GitHub'daki **"Onaylı videoları YouTube'a zamanla"** iş akışı `queue/` paketlerini render edip saatlerine zamanlar. YouTube anahtarları sadece orada.
   `work/` klasörünü commit ETME (büyük dosyalar; .gitignore'da).
3. Kullanıcıya kısa rapor ver: her video için saat, başlık, kalite puanı, kaç tur sürdüğü; iptal edilenler ve nedeni;
   baş denetçinin denetçiler hakkındaki önemli notları (hangi denetçi neyi kaçırdı).

## Kurallar
- Hiçbir aşamayı atlama, denetçi onayı olmadan sonraki aşamaya geçme.
- Bir ajan hata verirse (araç çökmesi, ElevenLabs hatası) aynı ajanı bir kez daha dene; yine olmazsa o videoyu iptal et, diğerlerine devam et.
- Kalite sayıdan önemlidir: onaysız video paketlenmez.

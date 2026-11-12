# Kıssa Defteri

Türkçe YouTube Shorts kanalı: kukla tiyatrosu sahnesinde çubuklu karton kuklalarla oynanan 30-45 sn'lik özgün mini oyunlar.
Kanalda hiçbir yerde yapay zekâ / AI / bot geçmez.

- Günlük üretim: `/gunluk-yayin` skill'i (`.claude/skills/gunluk-yayin/SKILL.md`). 11 ajan `.claude/agents/` altında.
- Ajan araçları: `pipeline/tools.py` (her komutun açıklaması dosyanın başında).
- Render motoru: `pipeline/theater.py`. Ses: `pipeline/tts.py` (ElevenLabs, ses ID'leri `config/voices.json`).
- Yükleme sadece GitHub Actions'ta (`.github/workflows/upload.yml`, `pipeline/publish.py`); YouTube anahtarları GitHub Secrets'ta.
- `work/` ve `output/` commit edilmez. Onaylı paketler `queue/<tarih>/<NN>/` altına konur ve push edilir.

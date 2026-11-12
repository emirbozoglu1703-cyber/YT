"""Sahte ajanlar: API anahtarı olmadan tüm akışı (plan -> 5 aşama -> denetim -> baş denetçi) test etmek için.

Örnek hikâyeyi (stories/samples/bakkal_ferit.json) döndürür. İlk görsel denetimi bilerek reddeder ki
geri gönderme döngüsü de test edilsin.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE = json.load(open(os.path.join(ROOT, "stories", "samples", "bakkal_ferit.json"), encoding="utf-8"))
LAYOUT_KEYS = ("mood", "camera", "focus", "chars", "props", "big")


class FakeLLM:
    def __init__(self):
        self.cost, self.calls, self.log_path = 0.0, 0, None
        self.visual_reviews = 0

    @staticmethod
    def image(path):
        return {"type": "image", "path": path}

    def ask(self, agent, system, content, **kw):
        self.calls += 1
        text = content if isinstance(content, str) else json.dumps([c for c in content if c.get("type") == "text"], ensure_ascii=False)
        ok = {"approved": True, "score": 9, "issues": [], "instructions": ""}
        if agent == "Strateji Ajanı":
            ctx = json.loads(text.split("\n\nDENETÇİ")[0])
            n = ctx["istenen_sayi"]
            return {"slots": ctx["varsayilan_saatler"][:n],
                    "briefs": [{"theme": "uzun vadeli iyilik", "emotion": "sıcak", "setting": "mahalle bakkalı", "hook_idea": "zararına satıp kazanmak", "characters": "esnaf, rakip, çocuklar"}] * n,
                    "reasoning": "demo"}
        if agent == "Senarist":
            return {"working_title": SAMPLE["title"], "logline": "", "moral": SAMPLE["moral"], "music": SAMPLE["music"],
                    "lines": [{"text": s["text"], "speaker": s.get("speaker", "narrator"), "visual_intent": ""} for s in SAMPLE["scenes"]]}
        if agent == "Ses Ajanı":
            return {"lines": [{"tts_text": s.get("tts_text", s["text"]), "speaker": s.get("speaker", "narrator"), "settings": {"stability": 0.45}} for s in SAMPLE["scenes"]]}
        if agent == "Görsel Yönetmen":
            return {"scenes": [{k: s[k] for k in LAYOUT_KEYS if k in s} for s in SAMPLE["scenes"]]}
        if agent == "Görsel Denetçi":
            self.visual_reviews += 1
            if self.visual_reviews == 1:
                return {"approved": False, "score": 6, "issues": ["#3: (demo) marketçi evin önünde küçük kalıyor -> scale 1.1"], "instructions": "#3'ü düzelt"}
            return ok
        if agent == "Yayın Ajanı":
            return SAMPLE["meta"]
        if agent == "Baş Denetçi":
            return {"approved": True, "send_back_to": "none", "instructions": "", "quality_score": 8,
                    "reviewer_audit": [{"reviewer": r, "ok": True, "comment": "demo"} for r in ("senaryo", "ses", "görsel", "yayın")]}
        return ok  # tüm denetçiler

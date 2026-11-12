"""YouTube Data API v3 ile yükleme.

Gerekli ortam değişkenleri (GitHub Secrets):
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Refresh token'ı bir kez kendi bilgisayarınızda `python scripts/get_youtube_token.py` ile alırsınız.
"""
from __future__ import annotations

import json
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


def client():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_cfg() -> dict:
    with open(os.path.join(ROOT, "config", "channel.json"), encoding="utf-8") as f:
        return json.load(f)


def upload(meta: dict, privacy: str = "public", publish_at=None) -> str:
    """publish_at (datetime) verilirse video gizli yüklenir ve o saatte YouTube tarafından yayınlanır."""
    cfg = channel_cfg()
    desc = meta["description"].strip() + "\n\n" + cfg.get("description_footer", "")
    tags = list(dict.fromkeys(meta.get("tags", []) + cfg.get("default_tags", [])))[:30]
    title = meta["title"]
    if "#shorts" not in title.lower() and len(title) < 90:
        title = f"{title} #shorts"
    body = {
        "snippet": {
            "title": title[:100],
            "description": desc[:4900],
            "tags": tags,
            "categoryId": cfg.get("category_id", "24"),
            "defaultLanguage": "tr",
            "defaultAudioLanguage": "tr",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            # YouTube kuralı: GERÇEKÇİ görünen sentetik içerik (gerçek kişi/olay/yer gibi)
            # işaretlenmelidir. Çizgi/animasyon hikâyeler bu kapsamda değildir.
            # Bir hikâyede gerçekçi sahne varsa story JSON'unda "synthetic_realistic": true yapın.
            "containsSyntheticMedia": bool(meta.get("synthetic_realistic", False)),
        },
    }
    if publish_at is not None:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at.astimezone(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    yt = client()
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(meta["video"], chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"  yükleniyor %{int(status.progress() * 100)}")
    vid = resp["id"]
    if cfg.get("set_thumbnail") and meta.get("thumbnail"):  # Shorts akışında kapak görünmez; varsayılan kapalı
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(meta["thumbnail"])).execute()
        except Exception as e:
            print(f"  kapak yüklenemedi (kanal doğrulaması gerekebilir): {e}")
    comment = meta.get("pinned_comment") or cfg.get("pinned_comment")
    if comment and publish_at is None:  # zamanlanmış (gizli) videoya yorum yazılamaz; finalize sonrası eklenir
        try:
            yt.commentThreads().insert(part="snippet", body={"snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": comment}}}}).execute()
        except Exception as e:
            print(f"  yorum eklenemedi: {e}")
    return vid

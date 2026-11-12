"""GitHub Actions tarafı (YouTube anahtarları sadece burada).

  python pipeline/publish.py upload --queue <klasör> --site <ana branch checkout'u>
      queue/<tarih>/<NN>/package.json paketlerini render edip saatine zamanlayarak yükler, geçmişi yazar.
  python pipeline/publish.py engage --site .
      yayına girmiş videolara ilk yorumu yazar, 48 saati geçenlerin izlenmelerini çeker (strateji ajanı bunu öğrenir).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

TZ = ZoneInfo("Europe/Istanbul")


def read_hist(site):
    p = os.path.join(site, "data", "history.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def write_hist(site, hist):
    os.makedirs(os.path.join(site, "data"), exist_ok=True)
    with open(os.path.join(site, "data", "history.jsonl"), "w", encoding="utf-8") as f:
        for h in hist:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")


def cmd_upload(a):
    import production
    import upload

    hist = read_hist(a.site)
    done = {(h["date"], h["index"]) for h in hist}
    for pkg_path in sorted(glob.glob(os.path.join(a.queue, "*", "*", "package.json"))):
        pkg = json.load(open(pkg_path, encoding="utf-8"))
        b = pkg["brief"]
        if (b["date"], b["index"]) in done:
            continue
        src = os.path.dirname(pkg_path)
        work = tempfile.mkdtemp()
        res = []
        for v in pkg["voice"]:
            dst = os.path.join(work, v["path"])
            shutil.copy(os.path.join(src, v["path"]), dst)
            res.append({**v, "path": dst})
        video, sheet, _ = production.render_final(pkg["story"], res, work, "short")
        when = max(dt.datetime.fromisoformat(b["slot"]), dt.datetime.now(TZ) + dt.timedelta(minutes=15))
        if a.dry_run:
            print(f"[dry-run] {b['date']} #{b['index']} hazır: {video} -> {when:%H:%M}")
            continue
        vid = upload.upload({**pkg["meta"], "video": video}, publish_at=when)
        print(f"zamanlandı: {pkg['meta']['title']} -> {when:%Y-%m-%d %H:%M} https://youtube.com/shorts/{vid}")
        hist.append({"date": b["date"], "index": b["index"], "slot": when.isoformat(), "video_id": vid, "title": pkg["meta"]["title"],
                     "theme": b.get("brief", {}).get("theme"), "emotion": b.get("brief", {}).get("emotion"),
                     "chief_score": pkg.get("approval", {}).get("quality_score"), "pinned_comment": pkg["meta"].get("pinned_comment"),
                     "views_48h": None})
        arch = os.path.join(a.site, "stories", "published", b["date"], f"{b['index']:02d}.json")
        os.makedirs(os.path.dirname(arch), exist_ok=True)
        json.dump({**pkg["story"], "meta": pkg["meta"], "video_id": vid}, open(arch, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        write_hist(a.site, hist)


def cmd_engage(a):
    import upload

    hist = read_hist(a.site)
    if not hist:
        return
    yt = upload.client()
    now = dt.datetime.now(dt.timezone.utc)
    for h in hist:  # ilk yorum (zamanlanmış gizli videoya yorum yazılamadığı için yayından sonra)
        if h.get("video_id") and h.get("pinned_comment") and not h.get("comment_posted") and dt.datetime.fromisoformat(h["slot"]) < now - dt.timedelta(minutes=5):
            try:
                yt.commentThreads().insert(part="snippet", body={"snippet": {"videoId": h["video_id"], "topLevelComment": {"snippet": {"textOriginal": h["pinned_comment"]}}}}).execute()
                h["comment_posted"] = True
            except Exception as e:
                print("yorum yazılamadı:", h.get("title"), e)
    need = [h for h in hist if h.get("video_id") and h.get("views_48h") is None and now - dt.datetime.fromisoformat(h["slot"]) > dt.timedelta(hours=48)]
    for i in range(0, len(need), 50):
        batch = need[i:i + 50]
        r = yt.videos().list(part="statistics", id=",".join(h["video_id"] for h in batch)).execute()
        st = {it["id"]: it["statistics"] for it in r.get("items", [])}
        for h in batch:
            s = st.get(h["video_id"], {})
            h["views_48h"] = int(s.get("viewCount", 0))
            h["likes"] = int(s.get("likeCount", 0))
            h["comments"] = int(s.get("commentCount", 0))
    write_hist(a.site, hist)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("upload"); p.add_argument("--queue", required=True); p.add_argument("--site", required=True); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("engage"); p.add_argument("--site", default=".")
    a = ap.parse_args()
    {"upload": cmd_upload, "engage": cmd_engage}[a.cmd](a)


if __name__ == "__main__":
    main()

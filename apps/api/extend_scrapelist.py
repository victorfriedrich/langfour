#!/usr/bin/env python3
"""
extend_scrapelist.py  –  v3 (2025-05-28)

Add the top-viewed videos of a YouTube creator to your JSON scrapelist
and mark them "prioritized" so the crawl grabs them first.
"""

from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv, find_dotenv
import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from paths import data_file

load_dotenv(find_dotenv())
API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    sys.exit("❌  Put YOUTUBE_API_KEY in your environment or .env first.")

YOUTUBE = build("youtube", "v3", developerKey=API_KEY, cache_discovery=False)

# ───────────────────────────────────────────────────────── regexes ──
ISO_RE   = re.compile(r"P(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?", re.I)
CANON_RE = re.compile(r'rel="canonical"\s+href="/channel/(?P<id>UC[\w-]{22})"', re.I)
JSON_ID  = re.compile(r'"(?:channelId|externalId)":"(UC[\w-]{22})"')
UC_RE    = re.compile(r"/channel/(?P<id>UC[\w-]{22})")

OEMBED   = "https://www.youtube.com/oembed?url={url}&format=json"


def iso_to_min(dur: str) -> int:
    m = ISO_RE.search(dur)
    if not m:
        return 0
    h = int(m.group("h") or 0)
    mi = int(m.group("m") or 0)
    s = int(m.group("s") or 0)
    return h * 60 + mi + (1 if s >= 30 else 0)


# ───────────────────────────────── channel resolver ──
def channel_id_from_url(url: str, *, interactive: bool = True) -> str:
    """Return the UC-style channel ID from any YouTube URL or handle."""
    url = url.strip()

    # 1) canonical /channel/UC…
    if "/channel/" in url:
        return url.split("/channel/")[1].split("/")[0]

    # 2) plain handle or custom URL → resolve via forHandle
    handle = url.rstrip("/").split("/")[-1]
    if not handle.startswith("@"):
        handle = f"@{handle}"

    try:
        resp = (
            YOUTUBE.channels()
            .list(part="id", forHandle=handle.lstrip("@"))
            .execute()
        )
        items = resp.get("items", [])
        if items:
            return items[0]["id"]
    except HttpError as e:
        # keep going; we’ll fall back to search/list below
        print(f"forHandle lookup failed: {e}")

    # 3) fallback – Search API exact match (legacy code, rarely needed now)
    search = (
        YOUTUBE.search()
        .list(q=handle.lstrip("@"), type="channel", part="id,snippet", maxResults=10)
        .execute()
    )["items"]
    for it in search:
        sn = it["snippet"]
        if handle.lower().lstrip("@") in {
            sn.get("channelHandle", "").lower().lstrip("@"),
            sn.get("customUrl", "").lower(),
            sn["title"].lower(),
        }:
            return it["id"]["channelId"]

    raise RuntimeError(f"Could not resolve channel ID for {url}")

# ────────────────────────────── video fetch ───────────────────────
def top_videos(channel_id: str, n: int = 50) -> List[Dict[str, Any]]:
    n = min(n, 50)
    search = (YOUTUBE.search()
                    .list(channelId=channel_id, order="viewCount",
                          type="video", part="id", maxResults=n)
                    .execute())
    ids = [it["id"]["videoId"] for it in search["items"]]
    if not ids:
        return []
    details = (YOUTUBE.videos()
                     .list(id=",".join(ids),
                           part="snippet,statistics,contentDetails")
                     .execute())["items"]
    out: List[Dict[str, Any]] = []
    for it in details:
        st = it["statistics"]
        out.append({
            "id":        it["id"],
            "title":     it["snippet"]["title"].strip(),
            "Views":     int(st.get("viewCount", 0)),
            "Likes":     int(st.get("likeCount", 0)),
            "Comments":  int(st.get("commentCount", 0)),
            "length":    iso_to_min(it["contentDetails"]["duration"]),
            "processed": "prioritized",
        })
    return out


# optional title-analysis (unchanged)
try:
    from nlp_processing import analyze_titles
except ModuleNotFoundError:
    analyze_titles = None


def refresh_analysis(ch: Dict[str, Any]) -> None:
    if analyze_titles is None:
        return
    titles = [v["title"] for v in ch.get("Videos", [])]
    if not titles:
        return
    lang = ch.get("PreferredLanguage") or "Spanish"
    try:
        res = analyze_titles(ch["Name"], titles, lang)
        ch["TitleAnalysis"] = res.model_dump(mode="json")
    except Exception as e:
        print(f"⚠️  title analysis failed for {ch['Name']}: {e}")


# ─────────────────────────────── core logic ───────────────────────
def extend(scrapelist: Path, url: str, limit: int) -> None:
    scrapelist.touch(exist_ok=True)
    try:
        data: List[Dict[str, Any]] = json.loads(scrapelist.read_text("utf-8") or "[]")
    except json.JSONDecodeError:
        data = []

    cid   = channel_id_from_url(url)
    vids  = top_videos(cid, limit)
    if not vids:
        raise RuntimeError(f"No videos found for {url}")

    rec = next((c for c in data if c.get("ChannelLink", "").endswith(cid)), None)
    if rec is None:
        meta = (YOUTUBE.channels()
                        .list(id=cid, part="snippet,statistics")
                        .execute()["items"][0])
        rec = {
            "Name":        meta["snippet"]["title"],
            "Subscribers": int(meta["statistics"].get("subscriberCount", 0)),
            "ChannelLink": f"https://www.youtube.com/channel/{cid}",
            "Videos":      [],
        }
        data.append(rec)

    existing = {v["id"] for v in rec["Videos"]}
    added = 0
    for v in vids:
        if v["id"] in existing:
            next(i for i in rec["Videos"] if i["id"] == v["id"]).setdefault(
                "processed", "prioritized"
            )
        else:
            rec["Videos"].append(v); added += 1
    print(f"✔️  Added {added} new videos (now {len(rec['Videos'])}) for {rec['Name']}")

    tot_v = sum(v["Views"] for v in rec["Videos"])
    tot_i = sum(v["Likes"] + v["Comments"] for v in rec["Videos"])
    rec["AvgEngagementRate"] = tot_i / tot_v if tot_v else 0.0
    rec["AvgViewsPerSub"]    = tot_v / (rec.get("Subscribers") or 1)
    refresh_analysis(rec)

    tmp = scrapelist.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(scrapelist)
    print(f"💾  Scrapelist saved → {scrapelist}")


# ─────────────────────────────────── CLI ───────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description="Extend a scrapelist with a creator’s top videos."
    )
    p.add_argument("--channel", required=True, help="Channel URL (@handle or /channel/UC…)")
    p.add_argument("--scrapelist", default=str(data_file("yt_es.json")), type=Path)
    p.add_argument("--max", default=50, type=int)
    args = p.parse_args()

    try:
        extend(args.scrapelist, args.channel, args.max)
    except HttpError as he:
        print(f"❌ YouTube API error:\n{he}")
        sys.exit(2)
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

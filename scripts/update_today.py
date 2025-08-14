# -*- coding: utf-8 -*-
"""
mabimobi.life에서 '메이븐' 관련 텍스트를 수집해 오늘자 today.json을 갱신한다.
- 막히는 경우(403/CORS/레이아웃 변경)에도 파일은 최소한 last_updated만 갱신되어
  프런트( index.html )가 정상 표출되도록 설계.
"""
import json, os, re, sys, datetime, time
from typing import List, Dict
import requests
from bs4 import BeautifulSoup

KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).date()
OUTFILE = "today.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.google.com/",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}

# 크롤링 후보 페이지들 (동적/정적 섞음 — 일부는 비어 있을 수 있음)
CANDIDATES = [
    "https://mabimobi.life/",
    "https://mabimobi.life/ranking",
    "https://mabimobi.life/tracker/v2",
]

TIME_RX = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\b")  # HH:mm[:ss]
END_WORDS = ("종료", "퇴장", "격퇴", "끝")
SPAWN_WORDS = ("출현", "등장", "발견")
PENDING_WORDS = ("예정", "관측", "감지", "추정")

def load_prev(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def iso_kt(ymd: datetime.date, hhmmss: str) -> str:
    # hhmmss는 "HH:mm" 또는 "HH:mm:ss"
    if len(hhmmss) == 5:
        hhmmss += ":00"
    dt = datetime.datetime.fromisoformat(f"{ymd}T{hhmmss}").replace(tzinfo=KST)
    return dt.isoformat(timespec="seconds")

def fetch_text(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code >= 400:
            return ""
        # 기본은 HTML 파싱, JS 렌더 없는 경우만 수집
        soup = BeautifulSoup(r.text, "html.parser")
        # 텍스트를 전부 긁되 공백 정리
        txt = soup.get_text("\n", strip=True)
        return txt
    except Exception:
        return ""

def extract_maven_lines(txt: str) -> List[str]:
    # '메이븐'이 들어간 줄/문장만 추출
    lines = []
    for line in txt.splitlines():
        if "메이븐" in line:
            lines.append(line.strip())
    return lines

def classify_status(segment: str) -> str:
    seg = segment.strip()
    if any(w in seg for w in SPAWN_WORDS):
        return "출현"
    if any(w in seg for w in END_WORDS):
        return "종료"
    if any(w in seg for w in PENDING_WORDS):
        return "관측"
    # 기본값
    return "관측"

def parse_events_from_text(ymd: datetime.date, segments: List[str]) -> List[Dict]:
    events = []
    seen_keys = set()
    for seg in segments:
        # 시간 패턴이 여러 개 박혀있을 수 있으니 모두 뽑기
        for m in TIME_RX.finditer(seg):
            hhmmss = ":".join([m.group(1).zfill(2), m.group(2), (m.group(3) or "00")])
            ts = iso_kt(ymd, hhmmss)
            status = classify_status(seg)
            memo = seg
            key = (ts, status, memo[:40])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            events.append({
                "time": ts,
                "status": status,
                "memo": memo,
                "source": "mabimobi",
            })
    # 시간순 정렬
    events.sort(key=lambda e: e["time"])
    return events

def merge_events(existing: List[Dict], new_events: List[Dict]) -> List[Dict]:
    # 같은 timestamp+status+memo면 중복 제거
    idx = {(e["time"], e.get("status",""), e.get("memo","")) for e in existing}
    out = existing[:]
    for e in new_events:
        key = (e["time"], e.get("status",""), e.get("memo",""))
        if key not in idx:
            out.append(e)
            idx.add(key)
    out.sort(key=lambda e: e["time"])
    return out

def build_today(prev: Dict, crawled_events: List[Dict]) -> Dict:
    base = {
        "boss": "메이븐",
        "date": TODAY.strftime("%Y-%m-%d"),
        "last_updated": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        "events": [],
    }
    if prev.get("date") == base["date"]:
        base["events"] = prev.get("events", [])
    return {
        **base,
        "events": merge_events(base["events"], crawled_events)
    }

def main():
    prev = load_prev(OUTFILE)

    all_text = ""
    for url in CANDIDATES:
        t = fetch_text(url)
        if t:
            all_text += "\n" + t

    segments = extract_maven_lines(all_text)
    crawled = parse_events_from_text(TODAY, segments)

    data = build_today(prev, crawled)

    # 폴더 보장
    os.makedirs(os.path.dirname(OUTFILE) or ".", exist_ok=True)
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[ok] today.json updated. events={len(data['events'])}")

if __name__ == "__main__":
    sys.exit(main())

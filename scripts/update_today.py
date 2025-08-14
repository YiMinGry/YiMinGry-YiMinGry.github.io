# -*- coding: utf-8 -*-
"""
mabimobi.life '심층 구멍 알림' 영역을 크롤링해
구름황야 / 얼음협곡 / 어비스 3종의 남은 시간을 추출하여 today.json 갱신.

- 구조 변경/동적 렌더를 대비해: 페이지 전체 텍스트에서 키워드 주변의 시간 패턴을 탐지
- 허용 시간 포맷: HH:MM[:SS], H:MM[:SS], MM:SS (필요 시 HH 계산 0으로 채움)
- 못 찾으면 remaining=None 로 표기(프런트에서 '—' 처리)
"""
import json, os, re, datetime, sys
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup

KST = datetime.timezone(datetime.timedelta(hours=9))
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

# 대상 구역 키워드(우선순위): 각 이름의 여러 변형도 대비
ZONES = [
    ("구름황야", ("구름황야", "구름 황야", "황야")),
    ("얼음협곡", ("얼음협곡", "얼음 협곡", "협곡")),
    ("어비스",   ("어비스", "심연", "Abyss")),
]

# 후보 페이지들 (여기서 텍스트를 전부 긁어 합쳐서 분석)
CANDIDATES = [
    "https://mabimobi.life/",
    "https://mabimobi.life/tracker/v2",
    "https://mabimobi.life/ranking",
]

# 시간 패턴: HH:MM[:SS] / H:MM[:SS] / MM:SS
TIME_RX = re.compile(r"\b((?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?|[0-5]?\d:[0-5]\d)\b")

def fetch_text(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code >= 400:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        # 스크립트/스타일 제거 후 텍스트
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()
        txt = soup.get_text("\n", strip=True)
        return txt
    except Exception:
        return ""

def normalize_time(token: str) -> str:
    """
    'H:MM', 'HH:MM', 'MM:SS', 'HH:MM:SS' 를 'HH:MM:SS' 로 통일
    """
    parts = token.split(":")
    if len(parts) == 3:
        hh, mm, ss = parts
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    if len(parts) == 2:
        a, b = parts
        # a가 60 이상일 리 없으므로 a<60이면 MM:SS로 보고 HH=00
        if int(a) < 60 and int(b) < 60:
            return f"00:{int(a):02d}:{int(b):02d}"
        # 혹시 다른 포맷이 오면 안전하게 00:00:00
    # 기본
    return "00:00:00"

def nearest_time_around(text: str, anchor: str, window: int = 80) -> Optional[str]:
    """
    text에서 anchor(구역명)의 첫 등장 주변 window 글자 안에서 시간 패턴을 찾아 반환.
    """
    idx = text.find(anchor)
    if idx == -1:
        return None
    start = max(0, idx - window)
    end = min(len(text), idx + len(anchor) + window)
    area = text[start:end]
    m = TIME_RX.search(area)
    if m:
        return normalize_time(m.group(1))
    return None

def extract_remaining_map(text: str) -> Dict[str, Optional[str]]:
    """
    각 존 이름 → 남은 시간 문자열('HH:MM:SS') 또는 None
    """
    result: Dict[str, Optional[str]] = {}
    for zone_name, aliases in ZONES:
        found = None
        # 우선 정확/긴 별칭부터 순서대로 탐색
        for alias in sorted(aliases, key=lambda s: -len(s)):
            t = nearest_time_around(text, alias)
            if t:
                found = t
                break
        result[zone_name] = found
    return result

def load_prev(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def build_payload(remap: Dict[str, Optional[str]], prev: Dict) -> Dict:
    now = datetime.datetime.now(KST)
    today = now.date().strftime("%Y-%m-%d")

    # 기존 today와 날짜 동일하면 이전 값 유지 + 업데이트 병합
    prev_map = {}
    if prev.get("date") == today and isinstance(prev.get("deep_hole"), list):
        prev_map = {item.get("zone"): item.get("remaining") for item in prev["deep_hole"]}

    deep_list = []
    for zone in [z[0] for z in ZONES]:
        remaining = remap.get(zone)
        if remaining is None:
            # 새로 못 찾았으면 이전 값 유지(있다면)
            remaining = prev_map.get(zone)
        deep_list.append({"zone": zone, "remaining": remaining, "source": "mabimobi"})

    return {
        "date": today,
        "last_updated": now.isoformat(timespec="seconds"),
        "deep_hole": deep_list
    }

def main():
    # 1) 페이지들 긁어서 텍스트 합치기
    merged = ""
    for url in CANDIDATES:
        t = fetch_text(url)
        if t:
            merged += "\n" + t

    # 2) 남은 시간 맵 추출
    remap = extract_remaining_map(merged)

    # 3) 기존 today.json 불러와 병합
    prev = load_prev(OUTFILE)
    payload = build_payload(remap, prev)

    # 4) 저장
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("[ok] today.json updated:", json.dumps(payload, ensure_ascii=False))

if __name__ == "__main__":
    sys.exit(main())

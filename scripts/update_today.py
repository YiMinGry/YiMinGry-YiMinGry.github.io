# -*- coding: utf-8 -*-
"""
mabimobi.life '심층 구멍 알림'에서 class="number__inner" 블록을 우선 파싱하여
구름황야 / 얼음협곡 / 어비스 3종의 남은 시간을 추출, today.json 갱신.

- 1순위: .number__inner 카드 단위 파싱 (부모/형제 라벨에서 존 이름 탐색)
- 2순위: 페이지 전체 텍스트 백업 스캔(키워드 주변의 시간 패턴)
"""

import json, os, re, datetime, sys
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup, Tag

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

# 대상 구역(여러 별칭 포함)
ZONES = [
    ("구름황야", ("구름황야", "구름 황야", "황야")),
    ("얼음협곡", ("얼음협곡", "얼음 협곡", "협곡")),
    ("어비스",   ("어비스", "심연", "Abyss")),
]

# 시간 패턴: HH:MM[:SS] / H:MM[:SS] / MM:SS
TIME_RX = re.compile(r"\b((?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?|[0-5]?\d:[0-5]\d)\b")

# 크롤링 후보 페이지들(실제 구성에 맞춰 필요시 추가/조정)
CANDIDATES = [
    "https://mabimobi.life/",
    "https://mabimobi.life/tracker/v2",
    "https://mabimobi.life/ranking",
]

def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code >= 400:
            return None
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None

def normalize_hms(token: str) -> str:
    """
    'H:MM', 'HH:MM', 'MM:SS', 'HH:MM:SS' 를 'HH:MM:SS' 로 통일
    """
    parts = token.split(":")
    if len(parts) == 3:
        hh, mm, ss = parts
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    if len(parts) == 2:
        a, b = parts
        # a<60이면 MM:SS로 간주 → HH=00
        if int(a) < 60 and int(b) < 60:
            return f"00:{int(a):02d}:{int(b):02d}"
    return "00:00:00"

def find_zone_label_text(el: Tag) -> str:
    """
    .number__inner 엘리먼트 기준으로, 부모/형제/자식의 텍스트 중
    존 이름(별칭들)이 들어 있을 법한 라벨 텍스트를 탐색 후 반환.
    """
    # 1) 자신 + 부모 몇 단계 위까지 텍스트
    candidates = []
    try:
        # 자기 자신
        candidates.append(el.get_text(" ", strip=True))
        # 형제들
        if el.parent:
            for sib in el.parent.children:
                if isinstance(sib, Tag) and sib is not el:
                    candidates.append(sib.get_text(" ", strip=True))
        # 부모들(최대 3단계)
        p = el.parent
        depth = 0
        while p and depth < 3:
            candidates.append(p.get_text(" ", strip=True))
            p = p.parent
            depth += 1
    except Exception:
        pass

    # 길이 긴 텍스트부터 검사
    candidates = sorted(set([c for c in candidates if c]), key=lambda s: -len(s))
    return " \n ".join(candidates[:6])  # 과하게 길지 않게 상위 6개만 이어붙임

def match_zone_from_text(text: str) -> Optional[str]:
    for zone_name, aliases in ZONES:
        for alias in sorted(aliases, key=lambda s: -len(s)):
            if alias in text:
                return zone_name
    return None

def extract_time_from_text(text: str) -> Optional[str]:
    m = TIME_RX.search(text)
    if not m:
        return None
    return normalize_hms(m.group(1))

def parse_numbers_by_cards(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """
    페이지에서 .number__inner 카드를 모두 모아
    각 카드 주변의 라벨로 존을 식별하고, 카드 속 텍스트에서 시간을 뽑는다.
    """
    result: Dict[str, Optional[str]] = {}
    cards = soup.select(".number__inner")
    for card in cards:
        # 카드 본문 시간
        card_text = card.get_text(" ", strip=True)
        time_token = extract_time_from_text(card_text)

        # 라벨 텍스트에서 존 식별 (카드 주변)
        label_text = find_zone_label_text(card)
        zone = match_zone_from_text(label_text)

        if zone:
            # 이미 채워졌으면 덮지 않도록(첫 매칭 우선)
            if zone not in result or (result[zone] is None and time_token):
                result[zone] = time_token
    return result

def fallback_scan_text(all_text: str) -> Dict[str, Optional[str]]:
    """
    백업: 전체 텍스트에서 alias 주변 80자 내 시간 추출
    """
    def nearest_time_around(text: str, anchor: str, window: int = 80) -> Optional[str]:
        idx = text.find(anchor)
        if idx == -1:
            return None
        start = max(0, idx - window)
        end = min(len(text), idx + len(anchor) + window)
        area = text[start:end]
        m = TIME_RX.search(area)
        return normalize_hms(m.group(1)) if m else None

    remap: Dict[str, Optional[str]] = {}
    for zone_name, aliases in ZONES:
        found = None
        for alias in sorted(aliases, key=lambda s: -len(s)):
            t = nearest_time_around(all_text, alias)
            if t:
                found = t
                break
        remap[zone_name] = found
    return remap

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

    prev_map = {}
    if prev.get("date") == today and isinstance(prev.get("deep_hole"), list):
        prev_map = {item.get("zone"): item.get("remaining") for item in prev["deep_hole"]}

    deep_list = []
    for zone in [z[0] for z in ZONES]:
        remaining = remap.get(zone)
        if remaining is None:
            remaining = prev_map.get(zone)
        deep_list.append({"zone": zone, "remaining": remaining, "source": "mabimobi"})
    return {
        "date": today,
        "last_updated": now.isoformat(timespec="seconds"),
        "deep_hole": deep_list
    }

def main():
    # 1) .number__inner 우선 파싱
    primary_map: Dict[str, Optional[str]] = {}
    merged_text = ""
    for url in CANDIDATES:
        soup = fetch_soup(url)
        if soup:
            # .number__inner 파싱
            card_map = parse_numbers_by_cards(soup)
            for k, v in card_map.items():
                # 여러 페이지에서 같은 존을 찾으면 처음 유효값을 우선
                if k not in primary_map or (primary_map[k] is None and v):
                    primary_map[k] = v
            # 백업용 전체 텍스트 합치기
            # (script/style 제거는 fetch_soup에서 이미 처리됨)
            merged_text += "\n" + soup.get_text("\n", strip=True)

    # 2) 부족하면 텍스트 백업 스캔으로 보충
    if any(primary_map.get(z[0]) is None for z in ZONES):
        fb = fallback_scan_text(merged_text)
        for zone, t in fb.items():
            if primary_map.get(zone) is None and t is not None:
                primary_map[zone] = t

    # 3) today.json 병합 저장
    prev = load_prev(OUTFILE)
    payload = build_payload(primary_map, prev)
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("[ok] today.json updated:", json.dumps(payload, ensure_ascii=False))

if __name__ == "__main__":
    sys.exit(main())

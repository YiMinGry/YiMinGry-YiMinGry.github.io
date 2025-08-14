# -*- coding: utf-8 -*-
"""
mabimobi.life '심층 구멍 알림'의 모바일 섹션(class에 lg:hidden 포함)에서
각 카드(rounded-lg …) 안의 '시간 행'(opacity-50 포함된 flex 행)에서 시간을 추출.
존(구름황야/얼음협곡/어비스) 라벨은 같은 카드/조상 텍스트에서 별칭 매칭으로 식별.

우선순위
1) 모바일 섹션(.lg:hidden …) → 카드(.rounded-lg …) → 시간행(.opacity-50 …)
2) 페이지 내 .number__inner 카드 (보조)
3) 텍스트 백업 스캔 (최후)
"""

import json, os, re, datetime, sys
from typing import Dict, Optional, List
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

CANDIDATES = [
    "https://mabimobi.life/",
    "https://mabimobi.life/tracker/v2",
    "https://mabimobi.life/ranking",
]

# 대상 존 + 별칭
ZONES = [
    ("구름황야", ("구름황야", "구름 황야", "황야")),
    ("얼음협곡", ("얼음협곡", "얼음 협곡", "협곡")),
    ("어비스",   ("어비스", "심연", "Abyss")),
]
ZONE_NAMES = [z[0] for z in ZONES]

# 시간 패턴: HH:MM[:SS] / H:MM[:SS] / MM:SS
TIME_RX = re.compile(r"\b((?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?|[0-5]?\d:[0-5]\d)\b")

def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code >= 400:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()
        return soup
    except Exception:
        return None

def has_classes(tag: Tag, required: List[str]) -> bool:
    """tag.class_에 required 클래스 토큰이 모두 포함되는지 검사 (Tailwind 순서 무시)"""
    if not tag or not isinstance(tag, Tag):
        return False
    cls = tag.get("class", []) or []
    cls_set = set(cls)
    return all(tok in cls_set for tok in required)

def normalize_hms(token: str) -> str:
    """'H:MM','HH:MM','MM:SS','HH:MM:SS' -> 'HH:MM:SS'"""
    parts = token.split(":")
    if len(parts) == 3:
        hh, mm, ss = parts
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    if len(parts) == 2:
        a, b = parts
        if int(a) < 60 and int(b) < 60:
            return f"00:{int(a):02d}:{int(b):02d}"
    return "00:00:00"

def match_zone_from_text(text: str) -> Optional[str]:
    for zone_name, aliases in ZONES:
        for alias in sorted(aliases, key=lambda s: -len(s)):
            if alias in text:
                return zone_name
    return None

def nearest_time(text: str) -> Optional[str]:
    m = TIME_RX.search(text)
    return normalize_hms(m.group(1)) if m else None

# -----------------------------
# 1) 모바일 섹션 → 카드 → 시간행(opacity-50) 파싱
# -----------------------------
def parse_mobile_cards(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """
    block lg:hidden … container … 안쪽의 각 카드(rounded-lg …)에서:
      - 카드 주변 텍스트로 존 식별
      - 카드 내부 'opacity-50' flex 행에서 시간 추출
    """
    result: Dict[str, Optional[str]] = {}
    # 모바일 래퍼: class에 'block'과 'lg:hidden'이 모두 있는 컨테이너들
    mobile_blocks = [d for d in soup.find_all(class_=True)
                     if has_classes(d, ["block"]) and "lg:hidden" in (d.get("class") or [])]

    for mb in mobile_blocks:
        # 카드들: rounded-lg & overflow-hidden 등을 가진 컨테이너
        cards = [c for c in mb.find_all(class_=True)
                 if has_classes(c, ["rounded-lg"]) and ("overflow-hidden" in (c.get("class") or []))]
        for card in cards:
            # 존 라벨 후보: 카드 자체/부모 몇 단계의 텍스트
            label_chunks = []
            try:
                label_chunks.append(card.get_text(" ", strip=True))
                p = card.parent
                depth = 0
                while p and depth < 3:
                    label_chunks.append(p.get_text(" ", strip=True))
                    p = p.parent
                    depth += 1
            except Exception:
                pass
            label_text = " \n ".join(sorted(set([t for t in label_chunks if t]), key=lambda s: -len(s))[:5])
            zone = match_zone_from_text(label_text)
            if not zone:
                continue  # 존을 못 찾으면 스킵

            # 시간행: class에 opacity-50 포함 + flex/rounded-xl 등
            time_nodes = [n for n in card.find_all(class_=True)
                          if ("opacity-50" in (n.get("class") or []))
                          and ("flex" in (n.get("class") or []))]
            # 가장 먼저 보이는 시간 하나만 채택
            remaining = None
            for node in time_nodes:
                t = nearest_time(node.get_text(" ", strip=True))
                if t:
                    remaining = t
                    break

            if zone not in result or (result[zone] is None and remaining):
                result[zone] = remaining

    return result

# -----------------------------
# 2) .number__inner 카드 기반 보조 파싱
# -----------------------------
def find_zone_label_text(el: Tag) -> str:
    candidates = []
    try:
        candidates.append(el.get_text(" ", strip=True))
        if el.parent:
            # 형제 텍스트
            for sib in el.parent.children:
                if isinstance(sib, Tag) and sib is not el:
                    candidates.append(sib.get_text(" ", strip=True))
        # 부모 3단계
        p = el.parent; depth = 0
        while p and depth < 3:
            candidates.append(p.get_text(" ", strip=True))
            p = p.parent; depth += 1
    except Exception:
        pass
    candidates = sorted(set([c for c in candidates if c]), key=lambda s: -len(s))
    return " \n ".join(candidates[:6])

def parse_number_inner_cards(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {}
    for card in soup.select(".number__inner"):
        zone = match_zone_from_text(find_zone_label_text(card))
        if not zone:
            continue
        t = nearest_time(card.get_text(" ", strip=True))
        if zone not in result or (result[zone] is None and t):
            result[zone] = normalize_hms(t) if t else None
    return result

# -----------------------------
# 3) 텍스트 백업 스캔
# -----------------------------
def fallback_scan_text(all_text: str) -> Dict[str, Optional[str]]:
    def nearest_time_around(text: str, anchor: str, window: int = 80) -> Optional[str]:
        idx = text.find(anchor)
        if idx == -1:
            return None
        area = text[max(0, idx - window): min(len(text), idx + len(anchor) + window)]
        m = TIME_RX.search(area)
        return normalize_hms(m.group(1)) if m else None

    remap: Dict[str, Optional[str]] = {}
    for zone_name, aliases in ZONES:
        found = None
        for alias in sorted(aliases, key=lambda s: -len(s)):
            t = nearest_time_around(all_text, alias)
            if t:
                found = t; break
        remap[zone_name] = found
    return remap

# -----------------------------
# 공용 유틸
# -----------------------------
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
    for zone in ZONE_NAMES:
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
    primary_map: Dict[str, Optional[str]] = {}
    merged_text = ""

    for url in CANDIDATES:
        soup = fetch_soup(url)
        if not soup:
            continue

        # 1) 모바일 섹션 우선
        m = parse_mobile_cards(soup)
        for k, v in m.items():
            if k not in primary_map or (primary_map[k] is None and v):
                primary_map[k] = v

        # 2) number__inner 보조
        n = parse_number_inner_cards(soup)
        for k, v in n.items():
            if k not in primary_map or (primary_map[k] is None and v):
                primary_map[k] = v

        # 백업용 전체 텍스트
        merged_text += "\n" + soup.get_text("\n", strip=True)

    # 3) 텍스트 백업으로 누락 보충
    if any(primary_map.get(z) is None for z in ZONE_NAMES):
        fb = fallback_scan_text(merged_text)
        for k, v in fb.items():
            if primary_map.get(k) is None and v:
                primary_map[k] = v

    prev = load_prev(OUTFILE)
    payload = build_payload(primary_map, prev)

    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("[ok] today.json updated:", json.dumps(payload, ensure_ascii=False))

if __name__ == "__main__":
    sys.exit(main())

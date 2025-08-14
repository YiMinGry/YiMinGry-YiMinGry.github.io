# -*- coding: utf-8 -*-
import os, sys, json, re, datetime, asyncio
from typing import Dict, Optional, List

KST = datetime.timezone(datetime.timedelta(hours=9))
OUTFILE = "today.json"

TARGET_URLS = [
    os.environ.get("TARGET_URL", "https://mabimobi.life/"),
    "https://mabimobi.life/tracker/v2",
    "https://mabimobi.life/ranking",
]

DEBUG = os.environ.get("DEBUG", "0") == "1"

# 존 + 별칭
ZONES = [
    ("구름황야", ("구름황야", "구름 황야", "황야")),
    ("얼음협곡", ("얼음협곡", "얼음 협곡", "협곡")),
    ("어비스",   ("어비스", "심연", "Abyss")),
]
ZONE_NAMES = [z[0] for z in ZONES]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 시간 포맷들
TIME_COLON_RX = re.compile(r"\b((?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?|[0-5]?\d:[0-5]\d)\b")
TIME_KO_RX    = re.compile(r"(?:(?P<h>\d+)\s*시간)?\s*(?:(?P<m>\d+)\s*분)?\s*(?:(?P<s>\d+)\s*초)?")

def log(*a):
    if DEBUG:
        print(*a)

def to_hms(sec: int) -> str:
    sec = max(0, int(sec))
    h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def parse_time_token(text: str) -> Optional[str]:
    text = text.strip()
    m = TIME_COLON_RX.search(text)
    if m:
        tok = m.group(1); parts = tok.split(":")
        if len(parts) == 3:
            h, mm, ss = [int(x) for x in parts]
        else:  # MM:SS
            h, mm, ss = 0, int(parts[0]), int(parts[1])
        return to_hms(h*3600 + mm*60 + ss)
    m2 = TIME_KO_RX.search(text)
    if m2 and (m2.group("h") or m2.group("m") or m2.group("s")):
        h = int(m2.group("h") or 0); mm = int(m2.group("m") or 0); ss = int(m2.group("s") or 0)
        return to_hms(h*3600 + mm*60 + ss)
    return None

def match_zone(text: str) -> Optional[str]:
    for zone, aliases in ZONES:
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in text:
                return zone
    return None

async def render_and_extract() -> Dict[str, Optional[str]]:
    from playwright.async_api import async_playwright
    out: Dict[str, Optional[str]] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=UA, locale="ko-KR", viewport={"width": 390, "height": 844}
        )

        for url in TARGET_URLS:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 모바일 블록( lg:hidden ) 아래의 카드들
            card_locator = page.locator(
                "[class*='lg:hidden'] [class*='rounded-lg'][class*='overflow-hidden']"
            )
            cnt = await card_locator.count()
            log(f"[{url}] cards:", cnt)

            for i in range(cnt):
                card = card_locator.nth(i)
                label_text = (await card.inner_text()).strip()
                zone = match_zone(label_text)
                if not zone:
                    continue

                # 시간행 (스샷 기반 고정 셀렉터)
                time_rows = card.locator(
                    ".w-full.flex.items-center.gap-1.rounded-xl.transition-all.duration-200.select-none.relative.opacity-50"
                )
                tcnt = await time_rows.count()

                remaining = None
                for j in range(tcnt):
                    txt = (await time_rows.nth(j).inner_text()).strip()
                    t = parse_time_token(txt)
                    if t:
                        remaining = t
                        break

                if zone not in out or (out[zone] is None and remaining):
                    out[zone] = remaining

            await page.close()

        await ctx.close()
        await browser.close()

    log("[render] extracted:", out)
    return out

# ---- 보조: 실패 시 requests/bs4로 .number__inner만 스캔 (간단 백업) ----
def fallback_extract() -> Dict[str, Optional[str]]:
    import requests
    from bs4 import BeautifulSoup
    out: Dict[str, Optional[str]] = {}
    headers = {"User-Agent": UA, "Referer": "https://www.google.com/", "Accept-Language": "ko-KR,ko;q=0.9"}
    for url in TARGET_URLS:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code >= 400: 
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for card in soup.select(".number__inner"):
                text = card.get_text(" ", strip=True)
                zone = match_zone(text)
                t = parse_time_token(text)
                if zone and t and (zone not in out):
                    out[zone] = t
        except Exception:
            continue
    return out

def load_prev() -> Dict:
    if not os.path.exists(OUTFILE): return {}
    try:
        return json.load(open(OUTFILE, "r", encoding="utf-8"))
    except Exception:
        return {}

def build_payload(latest: Dict[str, Optional[str]], prev: Dict) -> Dict:
    now = datetime.datetime.now(KST)
    today = now.date().strftime("%Y-%m-%d")

    prev_map = {}
    if prev.get("date") == today and isinstance(prev.get("deep_hole"), list):
        prev_map = {it.get("zone"): it.get("remaining") for it in prev["deep_hole"]}

    deep = []
    for z in ZONE_NAMES:
        val = latest.get(z)
        if val is None:
            val = prev_map.get(z)
        deep.append({"zone": z, "remaining": val, "source": "mabimobi"})
    return {"date": today, "last_updated": now.isoformat(timespec="seconds"), "deep_hole": deep}

async def main_async():
    latest = await render_and_extract()
    # 렌더가 전혀 못 뽑았으면 보조 시도
    if not any(latest.values()):
        fb = fallback_extract()
        for k, v in fb.items():
            latest.setdefault(k, v)
    prev = load_prev()
    payload = build_payload(latest, prev)
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("[ok] today.json updated:", json.dumps(payload, ensure_ascii=False))

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    sys.exit(main())

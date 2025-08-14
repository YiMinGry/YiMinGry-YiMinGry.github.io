# -*- coding: utf-8 -*-
"""
mabimobi.life '심층 구멍 알림'의 모바일 섹션에서
구름황야/얼음협곡/어비스의 남은 시간을 추출해 today.json 갱신.

핵심:
- Playwright로 렌더 후, 시간행(.opacity-50 ...) 내부의 <number-flow-react> shadowRoot를 직접 읽음
  (각 digit span의 style에 있는 CSS 변수 '--current'를 파싱해 숫자를 구성)
- 실패 시 .number__inner 보조 스캔
"""

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
    if DEBUG: print(*a)

def to_hms(sec: int) -> str:
    sec = max(0, int(sec))
    h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def parse_time_token(text: str) -> Optional[str]:
    """HH:MM[:SS] / MM:SS / '1시간 2분 3초' → 'HH:MM:SS'"""
    text = text.strip()
    m = TIME_COLON_RX.search(text)
    if m:
        tok = m.group(1); parts = [int(x) for x in tok.split(":")]
        if len(parts) == 3: h, mm, ss = parts
        elif len(parts) == 2: h, mm, ss = 0, parts[0], parts[1]
        else: return None
        return to_hms(h*3600 + mm*60 + ss)
    m2 = TIME_KO_RX.search(text)
    if m2 and (m2.group("h") or m2.group("m") or m2.group("s")):
        h = int(m2.group("h") or 0); mm = int(m2.group("m") or 0); ss = int(m2.group("s") or 0)
        return to_hms(h*3600 + mm*60 + ss)
    return None

def match_zone(text: str) -> Optional[str]:
    for zone, aliases in ZONES:
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in text: return zone
    return None

# -------- Playwright 렌더 & 추출 --------
async def render_and_extract() -> Dict[str, Optional[str]]:
    from playwright.async_api import async_playwright
    out: Dict[str, Optional[str]] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=UA, locale="ko-KR",
            viewport={"width": 390, "height": 844},
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://www.google.com/",
            },
        )

        # 리소스 차단으로 로딩 가속
        async def _route(route, request):
            url = request.url
            if request.resource_type in {"image", "media", "font"}: return await route.abort()
            if any(h in url for h in ["googletagmanager","google-analytics","doubleclick"]): 
                return await route.abort()
            await route.continue_()
        await ctx.route("**/*", _route)

        for url in TARGET_URLS:
            page = await ctx.new_page()

            # 최대 3회 재시도
            success = False
            for attempt in range(3):
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:
                        pass
                    success = True
                    break
                except Exception as e:
                    log(f"[goto-timeout] {url} attempt {attempt+1}/3: {e}")
                    if attempt == 2: break

            if not success:
                await page.close(); continue

            # 모바일 카드들
            card_locator = page.locator(
                "[class*='lg:hidden'] [class*='rounded-lg'][class*='overflow-hidden']"
            )
            cnt = await card_locator.count()
            log(f"[{url}] cards: {cnt}")

            for i in range(cnt):
                card = card_locator.nth(i)
                label_text = (await card.inner_text()).strip()
                zone = match_zone(label_text)
                if not zone: 
                    continue

                # 시간행(스샷 기반 셀렉터)
                row = card.locator(
                    ".w-full.flex.items-center.gap-1.rounded-xl.transition-all.duration-200.select-none.relative.opacity-50"
                )

                # 1) shadowRoot에서 숫자 직접 읽기
digits_groups: List[str] = await row.evaluate("""
  (el) => {
    // 시간행 내부의 <number-flow-react> 들을 순서대로 읽음
    const flows = el.querySelectorAll('number-flow-react');
    const groups = [];
    flows.forEach(flow => {
      const root = flow.shadowRoot;
      if (!root) return;

      // ✅ 'integer-digit'이 class가 아니라 part 속성에 있음
      // 각 digit span의 style="--current: X"에서 X를 읽어 숫자 조합
      const digitSpans = root.querySelectorAll('span[part~="digit"][part~="integer-digit"][style*="--current"]');
      let s = '';
      digitSpans.forEach(d => {
        const st = d.getAttribute('style') || '';
        const m = st.match(/--current:\\s*(\\d+)/);
        if (m) s += m[1];
      });

      if (s) groups.push(s);
    });
    return groups;
  }
""")

                remaining = None
                if digits_groups and any(digits_groups):
                    # 그룹이 3개면 HH:MM:SS, 2개면 MM:SS 로 간주
                    if len(digits_groups) >= 3:
                        h, m, s = digits_groups[0], digits_groups[1], digits_groups[2]
                        remaining = f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
                    elif len(digits_groups) == 2:
                        m, s = digits_groups[0], digits_groups[1]
                        remaining = f"00:{int(m):02d}:{int(s):02d}"

                # 2) 혹시 shadow 파싱이 비면 텍스트 파싱으로 보조
                if not remaining:
                    try:
                        txt = (await row.inner_text()).strip()
                        remaining = parse_time_token(txt)
                    except Exception:
                        pass

                if zone not in out or (out[zone] is None and remaining):
                    out[zone] = remaining

            await page.close()

        await ctx.close()
        await browser.close()

    log("[render] extracted:", out)
    return out

# -------- 보조: requests/bs4 로 .number__inner 스캔 --------
def fallback_extract() -> Dict[str, Optional[str]]:
    import requests
    from bs4 import BeautifulSoup
    out: Dict[str, Optional[str]] = {}
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.google.com/",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    for url in TARGET_URLS:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code >= 400: continue
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

# -------- today.json 병합/저장 --------
def load_prev() -> Dict:
    if not os.path.exists(OUTFILE): return {}
    try: return json.load(open(OUTFILE, "r", encoding="utf-8"))
    except Exception: return {}

def build_payload(latest: Dict[str, Optional[str]], prev: Dict) -> Dict:
    now = datetime.datetime.now(KST)
    today = now.date().strftime("%Y-%m-%d")
    prev_map = {}
    if prev.get("date") == today and isinstance(prev.get("deep_hole"), list):
        prev_map = {it.get("zone"): it.get("remaining") for it in prev["deep_hole"]}
    deep = []
    for z in ZONE_NAMES:
        val = latest.get(z)
        if val is None: val = prev_map.get(z)
        deep.append({"zone": z, "remaining": val, "source": "mabimobi"})
    return {"date": today, "last_updated": now.isoformat(timespec="seconds"), "deep_hole": deep}

# -------- main --------
async def main_async():
    latest = await render_and_extract()
    if not any(v for v in latest.values()):
        fb = fallback_extract()
        for k, v in fb.items():
            latest.setdefault(k, v)
    prev = load_prev()
    payload = build_payload(latest, prev)
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("[ok] today.json updated:", json.dumps(payload, ensure_ascii=False))

def main(): asyncio.run(main_async())

if __name__ == "__main__":
    sys.exit(main())


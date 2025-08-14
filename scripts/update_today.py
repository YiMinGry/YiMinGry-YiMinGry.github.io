# -*- coding: utf-8 -*-
"""
mabimobi.life '심층 구멍 알림'의 모바일 섹션에서
구름황야/얼음협곡/어비스의 '남은 시간'을 추출해 today.json 갱신.

핵심:
- Playwright로 DOM 렌더
- 모바일 카드(.rounded-lg & .overflow-hidden)에서 시간행
  (.w-full.flex.items-center.gap-1.rounded-xl...opacity-50) 추출
- 시간 숫자는 <number-flow-react> shadowRoot 내부의 각 자리 컨테이너
  (span[part~="digit"][part~="integer-digit"])에서 style="--current:N" 값을 읽고,
  자식 span.digit__num 중 style="--n:N"인 텍스트를 골라 조합
- 실패 시 .number__inner 보조 스캔
"""

import os
import sys
import json
import re
import datetime
import asyncio
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
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def parse_time_token(text: str) -> Optional[str]:
    """HH:MM[:SS] / MM:SS / '1시간 2분 3초' → 'HH:MM:SS'"""
    text = text.strip()

    m = TIME_COLON_RX.search(text)
    if m:
        tok = m.group(1)
        parts = [int(x) for x in tok.split(":")]
        if len(parts) == 3:
            h, mm, ss = parts
        elif len(parts) == 2:
            h, mm, ss = 0, parts[0], parts[1]
        else:
            return None
        return to_hms(h*3600 + mm*60 + ss)

    m2 = TIME_KO_RX.search(text)
    if m2 and (m2.group("h") or m2.group("m") or m2.group("s")):
        h = int(m2.group("h") or 0)
        mm = int(m2.group("m") or 0)
        ss = int(m2.group("s") or 0)
        return to_hms(h*3600 + mm*60 + ss)

    return None

def match_zone(text: str) -> Optional[str]:
    """텍스트에서 존 이름(별칭 포함) 찾기"""
    for zone, aliases in ZONES:
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in text:
                return zone
    return None

# -----------------------------
# Playwright 렌더 & 추출
# -----------------------------
async def render_and_extract() -> Dict[str, Optional[str]]:
    from playwright.async_api import async_playwright
    out: Dict[str, Optional[str]] = {}

    async with async_playwright() as pw:
        # 정상 흐름: launch → new_context
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=UA,
            locale="ko-KR",
            viewport={"width": 390, "height": 844},  # 모바일 뷰( lg:hidden 보이도록 )
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://www.google.com/",
            },
        )

        # 리소스 차단으로 로딩 가속
        async def _route(route, request):
            url = request.url
            if request.resource_type in {"image", "media", "font"}:
                return await route.abort()
            if any(host in url for host in ["googletagmanager", "google-analytics", "doubleclick"]):
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
                        # 가능하면 네트워크 idle까지 추가 대기
                        await page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:
                        pass
                    success = True
                    break
                except Exception as e:
                    log(f"[goto-timeout] {url} attempt {attempt+1}/3: {e}")
                    if attempt == 2:
                        break

            if not success:
                await page.close()
                continue

            # 모바일 카드들: [lg:hidden] 하위의 rounded-lg & overflow-hidden
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

                # 시간행(스샷 기준 고정 셀렉터)
                time_rows = card.locator(
                    ".w-full.flex.items-center.gap-1.rounded-xl.transition-all.duration-200.select-none.relative.opacity-50"
                )
                tcnt = await time_rows.count()

                remaining: Optional[str] = None
                for j in range(tcnt):
                    row = time_rows.nth(j)

                    # 1) shadowRoot에서 숫자 직접 읽기
                    digits_groups: List[str] = await row.evaluate("""
                      (el) => {
                        const flows = el.querySelectorAll('number-flow-react');
                        const groups = [];

                        flows.forEach(flow => {
                          const root = flow.shadowRoot;
                          if (!root) return;

                          // 각 자리 컨테이너: part="digit integer-digit"
                          const digitContainers = root.querySelectorAll('span[part~="digit"][part~="integer-digit"]');
                          let numStr = '';

                          digitContainers.forEach(dc => {
                            // 현재 인덱스(cur): style의 --current 또는 computed style
                            let cur = null;
                            const styleAttr = dc.getAttribute('style') || '';
                            let m = styleAttr.match(/--current:\\s*(\\d+)/);
                            if (m) {
                              cur = parseInt(m[1], 10);
                            } else {
                              const cv = getComputedStyle(dc).getPropertyValue('--current');
                              if (cv && /^\\d+$/.test(cv.trim())) cur = parseInt(cv.trim(), 10);
                            }
                            if (cur == null || isNaN(cur)) return;

                            // 자식 digit__num들 중 --n == cur 을 가진 텍스트 선택
                            const candidates = dc.querySelectorAll('span.digit__num');
                            let picked = null;
                            for (const c of candidates) {
                              const st = c.getAttribute('style') || '';
                              const mm = st.match(/--n:\\s*(\\d+)/);
                              if (mm && parseInt(mm[1], 10) === cur) {
                                picked = c.textContent.trim();
                                break;
                              }
                            }
                            if (!picked && candidates.length) picked = candidates[0].textContent.trim();
                            numStr += (picked ? picked : '0');
                          });

                          if (numStr) groups.push(numStr);
                        });

                        return groups; // 예: ["01","23","45"] → HH, MM, SS
                      }
                    """)

                    if digits_groups and any(digits_groups):
                        if len(digits_groups) >= 3:
                            h, m, s = int(digits_groups[0]), int(digits_groups[1]), int(digits_groups[2])
                            remaining = f"{h:02d}:{m:02d}:{s:02d}"
                        elif len(digits_groups) == 2:
                            m, s = int(digits_groups[0]), int(digits_groups[1])
                            remaining = f"00:{m:02d}:{s:02d}"
                    else:
                        # 2) shadow 파싱 실패 시 plain text 파싱 보조
                        try:
                            txt = (await row.inner_text()).strip()
                            remaining = parse_time_token(txt)
                        except Exception:
                            pass

                    if remaining:
                        break  # 이 카드에서 시간 하나만 채택

                if zone not in out or (out[zone] is None and remaining):
                    out[zone] = remaining

            await page.close()

        await ctx.close()
        await browser.close()

    log("[render] extracted:", out)
    return out

# -----------------------------
# 보조: requests/bs4 로 .number__inner 스캔
# -----------------------------
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

# -----------------------------
# today.json 병합/저장
# -----------------------------
def load_prev() -> Dict:
    if not os.path.exists(OUTFILE):
        return {}
    try:
        with open(OUTFILE, "r", encoding="utf-8") as f:
            return json.load(f)
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

    return {
        "date": today,
        "last_updated": now.isoformat(timespec="seconds"),
        "deep_hole": deep,
    }

# -----------------------------
# main
# -----------------------------
async def main_async():
    latest = await render_and_extract()

    # 렌더 루트에서 전혀 못 뽑았으면 보조 시도
    if not any(v for v in latest.values()):
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

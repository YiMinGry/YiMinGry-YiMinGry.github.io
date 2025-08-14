import asyncio
import json
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

OUTPUT_FILE = "today.json"

URLS = {
    "cloud_waste": "https://mabimobi.life/",
    "ice_canyon": "https://mabimobi.life/",
    "abyss": "https://mabimobi.life/"
}

# CSS 변수 --n 값 읽어서 숫자 조합
async def extract_time_from_element(element):
    spans = await element.query_selector_all("span.digit__num")
    digits = []
    for span in spans:
        style = await span.get_attribute("style")  # 예: "--n: 1;"
        if style and "--n:" in style:
            try:
                n_value = style.split("--n:")[1].split(";")[0].strip()
                digits.append(n_value)
            except Exception:
                digits.append("0")
        else:
            digits.append("0")
    return "".join(digits)

async def render_and_extract():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(URLS["cloud_waste"], wait_until="networkidle", timeout=60000)

        # 타이머 컨테이너 선택 (실제 사이트 구조에 맞게 수정)
        timers = await page.query_selector_all(".number__inner")

        results = {}
        for idx, name in enumerate(URLS.keys()):
            if idx < len(timers):
                time_text = await extract_time_from_element(timers[idx])
                results[name] = time_text
            else:
                results[name] = None

        await browser.close()
        return results

async def main_async():
    latest = await render_and_extract()
    latest["updated_at"] = datetime.now().isoformat()

    # 기존 today.json 불러오기
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    data.update(latest)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Updated {OUTPUT_FILE} with {latest}")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    sys.exit(main())

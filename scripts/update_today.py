import asyncio
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

# HTML 경로
HTML_FILE = Path("index.html")

# 심층 구멍별 URL
URLS = {
    "구름황야": "https://mabimobi.life/cloud",
    "얼음협곡": "https://mabimobi.life/ice",
    "어비스": "https://mabimobi.life/abyss"
}

# 각 페이지에서 시간 추출
async def get_time_from_page(pw, url):
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(url, timeout=60000)
    await page.wait_for_selector(".digit__num")

    # span.digit__num 의 style 속성에서 --n 값을 추출
    elements = await page.query_selector_all(".digit__num")
    digits = []
    for el in elements:
        style = await el.get_attribute("style")
        if style and "--n:" in style:
            try:
                num = style.split("--n:")[1].split(";")[0].strip()
                digits.append(num)
            except Exception:
                digits.append("?")
        else:
            digits.append("?")

    await browser.close()

    # 예: [0, 1, 2, 3, 4, 5] → "01:23:45"
    if len(digits) == 6:
        return f"{digits[0]}{digits[1]}:{digits[2]}{digits[3]}:{digits[4]}{digits[5]}"
    else:
        return "".join(digits)

# HTML 업데이트
def update_html(times_dict):
    if not HTML_FILE.exists():
        print("index.html 파일이 없습니다.")
        return

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()

    updated_content = (
        html_content
        .replace("{{TIME_CLOUD}}", times_dict.get("구름황야", "N/A"))
        .replace("{{TIME_ICE}}", times_dict.get("얼음협곡", "N/A"))
        .replace("{{TIME_ABYSS}}", times_dict.get("어비스", "N/A"))
        .replace("{{UPDATED}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(updated_content)

async def main_async():
    async with async_playwright() as pw:
        times = {}
        for name, url in URLS.items():
            print(f"크롤링 중: {name}")
            times[name] = await get_time_from_page(pw, url)
            print(f"{name}: {times[name]}")
        update_html(times)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright

URLS = {
    "구름황야": "https://mabimobi.life/",
    "얼음협곡": "https://mabimobi.life/",
    "어비스": "https://mabimobi.life/"
}

# alt 값에 띄어쓰기나 접두어/접미어가 붙어도 찾을 수 있도록 핵심 키워드만 사용
ALT_KEYWORDS = {
    "구름황야": "구름",
    "얼음협곡": "얼음",
    "어비스": "어비스"
}

async def get_time_from_page(browser, url, keyword):
    page = await browser.new_page()
    await page.goto(url, wait_until="networkidle")

    # alt 속성에 특정 키워드가 포함된 이미지 찾기
    img_selector = f'img[alt*="{keyword}"]'
    try:
        await page.wait_for_selector(img_selector, timeout=10000)
    except:
        await page.close()
        return "오류"

    # 이미지가 포함된 블록에서 시간 추출
    img_element = await page.query_selector(img_selector)
    parent_block = await img_element.evaluate_handle("el => el.closest('.h-\\[78px\\]') || el.parentElement")

    if not parent_block:
        await page.close()
        return "오류"

    # 시간 숫자(span.digit__num) 모두 모아서 합침
    digits = await parent_block.query_selector_all(".digit__num")
    time_str = "".join([await d.inner_text() for d in digits])

    await page.close()
    return time_str if time_str else "오류"

async def main_async():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        results = {}

        for name, url in URLS.items():
            print(f"크롤링 중: {name}")
            keyword = ALT_KEYWORDS[name]
            try:
                results[name] = await get_time_from_page(browser, url, keyword)
            except Exception as e:
                print(f"{name} 가져오기 실패: {e}")
                results[name] = "오류"

        await browser.close()

        data = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "times": results
        }

        with open("today.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print("저장 완료:", data)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

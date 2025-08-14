import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright

# 심층 던전 정보
DUNGEONS = {
    "구름황야": "구름황야",
    "얼음협곡": "얼음협곡",
    "어비스": "어비스"
}

async def get_time_from_page(page, keyword):
    try:
        # 해당 던전 이름이 포함된 구역 찾기
        header = await page.wait_for_selector(f"text={keyword}", timeout=10000)
        container = await header.evaluate_handle("el => el.closest('div')")
        
        # 그 구역 안에서 digit__num 요소들 찾기
        spans = await container.query_selector_all(".digit__num")
        digits = []
        for span in spans:
            style = await span.get_attribute("style")  # 예: "--n: 1;"
            if style and "--n:" in style:
                num = style.split("--n:")[1].split(";")[0].strip()
                digits.append(num)
        
        # 시간 형식으로 합치기 (예: ['0','1',':','2','3'] → "01:23")
        if digits:
            time_str = "".join(digits)
            return time_str
        else:
            return "오류"
    except Exception as e:
        print(f"{keyword} 가져오기 실패: {e}")
        return "오류"

async def main_async():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://mabimobi.life/", timeout=60000)
        
        times = {}
        for name, keyword in DUNGEONS.items():
            print(f"크롤링 중: {name}")
            times[name] = await get_time_from_page(page, keyword)
        
        await browser.close()
        
        data = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "times": times
        }
        
        with open("today.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print("저장 완료:", data)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

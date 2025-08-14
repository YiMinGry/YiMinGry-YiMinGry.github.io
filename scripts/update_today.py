import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright

# 각 지역 이름과 URL 매핑
URLS = {
    "구름황야": "https://mabimobi.life/",
    "얼음협곡": "https://mabimobi.life/",
    "어비스": "https://mabimobi.life/"
}

# 페이지에서 시간 가져오기
async def get_time_from_page(pw, url, area_name):
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(url, timeout=60000)

    # 각 지역 블록을 alt 속성으로 찾음
    # 예: img[alt="구름 황야"] 부모에서 시간 추출
    await page.wait_for_selector(f'img[alt*="{area_name}"]')

    # 해당 지역 카드의 부모 요소 찾기
    parent = page.locator(f'img[alt*="{area_name}"]').locator("xpath=../..")

    # number-flow-react가 나올 때까지 대기
    await parent.wait_for_selector("number-flow-react", timeout=30000)

    # 시간 요소 3개 읽어서 HH:MM:SS로 조합
    numbers = await parent.locator("number-flow-react").all_inner_texts()
    numbers = [n.strip() for n in numbers if n.strip()]
    time_str = "N/A"
    if len(numbers) >= 3:
        time_str = f"{numbers[0]}:{numbers[1]}:{numbers[2]}"

    await browser.close()
    return time_str

# 전체 실행
async def main_async():
    times = {}
    async with async_playwright() as pw:
        for name in URLS:
            print(f"크롤링 중: {name}")
            try:
                times[name] = await get_time_from_page(pw, URLS[name], name)
            except Exception as e:
                print(f"{name} 가져오기 실패: {e}")
                times[name] = "오류"

    # JSON 저장
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = {"updated_at": now, "times": times}
    with open("today.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("저장 완료:", data)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()

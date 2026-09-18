import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content('<html><body><h1>JARVIS browser runtime OK</h1></body></html>')
        assert await page.locator('h1').inner_text() == 'JARVIS browser runtime OK'
        await browser.close()
    print('PLAYWRIGHT_RUNTIME_OK')

asyncio.run(main())

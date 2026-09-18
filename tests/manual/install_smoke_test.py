import asyncio
import sys

async def browser_test():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('data:text/html,<title>JARVIS</title>')
        title = await page.title()
        await browser.close()
        assert title == 'JARVIS'

if __name__ == '__main__':
    sys.path.insert(0, '.')
    print('MAIN_IMPORT_OK')
    asyncio.run(browser_test())
    print('PLAYWRIGHT_CHROMIUM_OK')

# openai_scraper_playwright.py

import asyncio
from playwright.async_api import async_playwright
import ollama
import logging
import random
import time
import os
from prometheus_client import start_http_server, Counter, Histogram
from diskcache import Cache
# from dotenv import load_dotenv

# load_dotenv()

SCRAPE_ATTEMPTS = Counter('scrape_attempts', 'Total scraping attempts')
SCRAPE_DURATION = Histogram('scrape_duration', 'Scraping duration distribution')
cache = Cache('./scraper_cache')

class ScrapingError(Exception): pass
class ContentAnalysisError(Exception): pass

class EnhancedOpenAIScraper:
    # API_KEY = os.getenv("OPENAI_API_KEY")
    # API_KEY = Client
    BROWSER_EXECUTABLE ="/usr/bin/chromium-browser"
    MAX_CONTENT_LENGTH ="30000"
    RETRY_COUNT = 2
    CACHE_EXPIRY = 4000

    def __init__(self, headless=True):
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)..."
        ]
        self.timeout = 45000
        # self.retry_count = int(os.getenv("RETRY_COUNT", 2))
        self.headless = headless
        self.proxy_servers = []
        # self.proxy_servers = [x.strip() for x in os.getenv("PROXY_SERVERS", "").split(',') if x.strip()]

    async def human_interaction(self, page):
        for _ in range(random.randint(2, 5)):
            x, y = random.randint(0, 1366), random.randint(0, 768)
            await page.mouse.move(x, y, steps=random.randint(5, 20))
            await page.wait_for_timeout(random.randint(50, 200))

        if random.random() < 0.3:
            await page.keyboard.press('Tab')
            await page.keyboard.type(' ', delay=random.randint(50, 200))

        await page.mouse.wheel(0, random.choice([300, 600, 900]))
        await page.wait_for_timeout(random.randint(500, 2000))

    async def load_page(self, page, url):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
            selectors = ['main article', '#main-content', 'section:first-of-type', 'div[class*="content"]', 'body']
            for selector in selectors:
                if await page.query_selector(selector):
                    return True
            await page.wait_for_timeout(5000)
            return True
        except Exception as e:
            logging.error(f"Error loading page {url}: {e}")
            return False

    @SCRAPE_DURATION.time()
    async def scrape_with_retry(self, url):
        SCRAPE_ATTEMPTS.inc()
        last_error = None
        try:
            async with async_playwright() as p:
                args = {
                    "headless": self.headless,
                    "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                    "executable_path": self.BROWSER_EXECUTABLE
                }
                browser = await p.chromium.launch(**args)
                context = await browser.new_context(user_agent=random.choice(self.user_agents))
                page = await context.new_page()
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => false });
                """)

                for attempt in range(self.retry_count):
                    try:
                        if not await self.load_page(page, url):
                            raise ScrapingError("Failed to load page")
                        await self.human_interaction(page)
                        content = await page.evaluate("""() => document.body.innerText""")
                        if not content.strip():
                            raise ContentAnalysisError("No content extracted")
                        await browser.close()
                        return content[:self.MAX_CONTENT_LENGTH]
                    except Exception as e:
                        last_error = e
                        if attempt < self.retry_count - 1:
                            await asyncio.sleep(5)
                        else:
                            await browser.close()
                            raise
        except Exception as e:
            raise last_error or e

    async def get_cached_content(self, url):
        key = 'cache_' + url.replace('https://', '').replace('/', '_')
        content = cache.get(key)
        if content is None:
            content = await self.scrape_with_retry(url)
            cache.set(key, content, expire=self.CACHE_EXPIRY)
        return content

async def analyze_content(url="https://openai.com", headless=True):
    scraper = EnhancedOpenAIScraper(headless=headless)
    content = await scraper.get_cached_content(url)
    # client = OpenAI(api_key=EnhancedOpenAIScraper.API_KEY)
    
    # if not client:
    #     raise ContentAnalysisError("OpenAI API key not configured")
    MODEL = "gemma3:270m"
    # OLLAMA_URL = "http://localhost:11434"
    TEMPERATURE = 0.3
    MAX_TOKENS = 1500
    TOP_P = 0.9

    prompt = f"""
Analyze this page:

{content}
    """
    model = MODEL
    temperature = TEMPERATURE
    max_tokens = MAX_TOKENS
    top_p = TOP_P

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": "You are a content analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p
    )
    if not response['message']['content']:
        raise ContentAnalysisError("Empty response from GPT")

    return response['message']['content']

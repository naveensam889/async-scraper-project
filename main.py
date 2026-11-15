import asyncio
from urllib.parse import urlsplit
import httpx
from protego import Protego

# some test links, need to load properly or handle dynamic lists later
WIKI_LINKS = [
    "https://en.wikipedia.org/wiki/Outer_space",
    "https://en.wikipedia.org/wiki/Artificial_intelligence",
]

def get_header(url: str):
    # wiki gets mad if our user agent is too basic, give them contact info
    if "wikipedia.org" in url:
        return {'User-Agent': 'CoolBot/1.0 (contact@example.org)'}
    return {"User-Agent": "Mozilla/5.0"}

async def fetch_data(client: httpx.AsyncClient, url: str):
    # simple retry loop for 429 rate limits because wikipedia yells at us if we go too fast
    for attempt in range(3):
        try:
            r = await client.get(url, headers=get_header(url), timeout=10.0)
            if r.status_code == 429:
                print(f"got rate limited on {url}, backing off...")
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            return r
        except Exception as e:
            print(f"request failed for {url}: {e}")
            return None
    return None

async def main():
    print("starting polite crawler test...")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # check robots.txt first to be polite and ethical
        res = await client.get("https://en.wikipedia.org/robots.txt", headers=get_header("https://en.wikipedia.org"))
        rp = Protego.parse(res.text)
        
        for link in WIKI_LINKS:
            path = urlsplit(link).path or "/"
            if rp.can_fetch(path, "CoolBot"):
                print(f"allowed to fetch: {link}")
                
                # fetch the raw page for now
                # need to pass this raw html into trafilatura next to clean out ads/menus
                page_res = await fetch_data(client, link)
                if page_res and page_res.status_code == 200:
                    print(f"successfully fetched raw html for {link}, length: {len(page_res.text)}")
                    # need to add pydantic validation here soon so we don't process broken data
            else:
                print(f"blocked by robots.txt: {link}")

if __name__ == "__main__":
    asyncio.run(main())
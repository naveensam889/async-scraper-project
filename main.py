import asyncio
import json
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, HttpUrl, ValidationError
from protego import Protego
from trafilatura import extract

# test links for now, need to load properly or handle dynamic lists later
WIKI_LINKS = [
    "https://en.wikipedia.org/wiki/Outer_space",
    "https://en.wikipedia.org/wiki/Artificial_intelligence",
]

# strict guard schema - making sure we don't pass garbage data into our pipeline
class Structure(BaseModel):
    text: str
    title: str | None = "Untitled"
    source: HttpUrl
    date: str | None = None

def get_header(url: str):
    # wiki gets mad if our user agent is too basic, give them contact info
    if "wikipedia.org" in url:
        return {'User-Agent': 'CoolBot/1.0 (contact@example.org)'}
    return {"User-Agent": "Mozilla/5.0"}

async def fetch_data(client: httpx.AsyncClient, url: str):
    # retry loop for 429 rate limits because wikipedia yells at us if we go too fast
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
    print("starting crawler and extractor test...")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # check robots.txt first to be polite and ethical
        res = await client.get("https://en.wikipedia.org/robots.txt", headers=get_header("https://en.wikipedia.org"))
        rp = Protego.parse(res.text)
        
        for link in WIKI_LINKS:
            path = urlsplit(link).path or "/"
            if rp.can_fetch(path, "CoolBot"):
                print(f"allowed to fetch: {link}")
                
                page_res = await fetch_data(client, link)
                if page_res and page_res.status_code == 200:
                    # noise remover: pass raw html into trafilatura to strip ads/nav menus
                    raw_extracted = extract(page_res.text, output_format="json", with_metadata=True)
                    if raw_extracted:
                        data = json.loads(raw_extracted)
                        if not data.get("source"):
                            data["source"] = link
                        
                        # strict guard: force data through pydantic model before accepting it
                        try:
                            validated_item = Structure.model_validate(data)
                            print(f"successfully validated article: '{validated_item.title}' ({len(validated_item.text)} chars)")
                            # need to add token chunking with tiktoken and langchain next for rag
                        except ValidationError as e:
                            print(f"pydantic validation failed for {link}: {e}")
            else:
                print(f"blocked by robots.txt: {link}")

if __name__ == "__main__":
    asyncio.run(main())
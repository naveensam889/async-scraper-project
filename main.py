import asyncio
import json
import logging
import sys
from urllib.parse import urlsplit
import httpx
import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field, HttpUrl, ValidationError
from protego import Protego
from trafilatura import extract

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("RAGPipeline")

class ValidLink(BaseModel):
    links: list[HttpUrl] = Field(..., description="List of target URLs to process")

class Structure(BaseModel):
    text: str = Field(..., min_length=1, description="Extracted clean text from the source")
    title: str | None = Field(default="Untitled", description="Title of the source")
    source: HttpUrl = Field(..., description="The canonical URL of the text")
    date: str | None = Field(default=None, description="Date article was posted")
    hostname: str | None = Field(default=None, description="The base domain of a website")

LIMIT = 5
WIKI_LINKS = [
    "https://en.wikipedia.org/wiki/Outer_space",
    "https://en.wikipedia.org/wiki/Artificial_intelligence",
    "https://www.python.org/doc/",
    "https://news.ycombinator.com/news"
]

def get_header(url: str) -> dict[str, str]:
    if "wikipedia.org" in url:
        return {'User-Agent': 'CoolBot/1.0 (https://example.org/coolbot/; coolbot@example.org)'}
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

async def fetch_data(client: httpx.AsyncClient, url: str, headers: dict, semaphore: asyncio.Semaphore, retries: int = 3) -> httpx.Response | None:
    """Fetches a URL with concurrency control and 429 rate-limit backoff handling."""
    async with semaphore:
        for attempt in range(retries):
            try:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code == 429:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Rate limited (429) on {url}. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                return response
            except httpx.RequestError as e:
                if attempt == retries - 1:
                    logger.error(f"Network request failed for {url}: {e}")
                    return None
                await asyncio.sleep(1)
        return None

async def site_checker(client: httpx.AsyncClient, mul_links: ValidLink) -> tuple[httpx.AsyncClient, list[str]]:
    """Checks robots.txt policies concurrently and filters permitted links."""
    splits = [urlsplit(str(link)) for link in mul_links.links]
    domain_roots = {f"{split.scheme}://{split.netloc}/robots.txt" for split in splits}

    semaphore = asyncio.Semaphore(LIMIT)
    tasks = [fetch_data(client, root_url, get_header(root_url), semaphore) for root_url in domain_roots]
    
    responses = await asyncio.gather(*tasks, return_exceptions=True)
    valid_links = []

    for robots_url, item in zip(domain_roots, responses):
        if isinstance(item, Exception) or item is None or item.status_code != 200:
            logger.warning(f"Skipping robots.txt retrieval for {robots_url}")
            continue

        try:
            rp = Protego.parse(item.text) 
            base_domain = robots_url.replace("/robots.txt", "")
            
            domain_links = [
                str(link) for link in mul_links.links 
                if str(link).startswith(base_domain)
            ]

            for link in domain_links:
                path = urlsplit(link).path or "/"
                if rp.can_fetch(path, "CoolBot"):
                    valid_links.append(link)
                else:
                    logger.info(f"Blocked by robots.txt: {link}")
        except Exception as e:
            logger.error(f"Error parsing robots.txt for {robots_url}: {e}")

    return client, valid_links

async def web_page_retreiver(client: httpx.AsyncClient, valid_links: list[str]) -> list[dict]:
    """Downloads permitted webpages and extracts clean text metadata using Trafilatura."""
    semaphore = asyncio.Semaphore(LIMIT)
    tasks = [fetch_data(client, url, get_header(url), semaphore) for url in valid_links]

    responses = await asyncio.gather(*tasks, return_exceptions=True)
    extracted_contents = []

    for site in responses:
        if isinstance(site, Exception) or site is None or site.status_code != 200:
            continue
        
        try:
            extracted_json = extract(site.text, output_format="json", with_metadata=True)
            if extracted_json:
                data = json.loads(extracted_json)
                if not data.get("source"):
                    data["source"] = str(site.url)
                extracted_contents.append(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Error extracting content from webpage: {e}")

    return extracted_contents

def validator(content: list[dict]) -> list[Structure]:
    """Validates raw dictionaries against the Pydantic Structure model."""
    validated_links = []
    if content and isinstance(content, list):
        for site in content:
            try:
                website = Structure.model_validate(site)
                validated_links.append(website)
            except ValidationError as e:
                title_val = site.get('title', 'Untitled')
                source_val = site.get('source', 'Unknown')
                logger.error(f"Validation failed for '{title_val}' ({source_val}): {e}")
                continue

    return validated_links

def chunking(validated_sites: list[Structure], chunk_size: int = 500, chunk_overlap: int = 50) -> dict[str, list[str]]:
    """Chunks validated text using token lengths and maps them by source URL."""
    tokenizer = tiktoken.get_encoding("cl100k_base")

    def token_length_function(text: str) -> int:
        return len(tokenizer.encode(text))

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=token_length_function,
        is_separator_regex=False,
    )

    all_url_content = {}
    for site in validated_sites:
        if not site.text:
            continue
            
        chunks = text_splitter.split_text(site.text)
        all_url_content[str(site.source)] = chunks

    return all_url_content

async def main():
    try:
        multi_links = ValidLink(links=WIKI_LINKS)
    except ValidationError as e:
        logger.critical(f"Initial link validation error: {e}")
        sys.exit(1)

    logger.info("Initializing asynchronous HTTP client session...")
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        same_client, valid_links = await site_checker(client, multi_links)
        logger.info(f"Found {len(valid_links)} permitted links after robots.txt check.")
        
        if not valid_links:
            logger.warning("No valid links to crawl. Exiting pipeline.")
            return

        content = await web_page_retreiver(same_client, valid_links)

    logger.info("Running Pydantic validation on extracted content...")
    validated = validator(content)
    
    logger.info("Chunking validated documents...")
    chunked_data = chunking(validated)
    
    chunk_summary = {}
    total_all_chunks = 0

    logger.info("Pipeline execution complete. Summary of chunks generated:")
    for url, chunks in chunked_data.items():
        chunk_count = len(chunks)
        chunk_summary[str(url)] = chunk_count
        total_all_chunks += chunk_count
        logger.info(f" -> URL: {url} | Total Chunks: {chunk_count}")

    logger.info(f"Grand Total Chunks Across All Sites: {total_all_chunks}")

    output_filename = "chunk_stats.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(chunk_summary, f, indent=4)
    
    logger.info(f"Successfully saved chunk statistics to local file: '{output_filename}'")

if __name__ == "__main__":
    asyncio.run(main())
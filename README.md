# Async RAG Scraper & Extraction Pipeline

A portfolio-grade, asynchronous web crawler and text processing pipeline engineered specifically for Retrieval-Augmented Generation (RAG) applications. This tool bridges the gap between raw web scraping and LLM ingestion by prioritizing ethical crawling, noise-free text extraction, strict schema validation, and token-aware chunking.

---

## 🚀 Key Features

1. **Ethical & Polite Crawling**
   * Asynchronous HTTP requests powered by `httpx` with redirect management.
   * Dynamic `robots.txt` parsing using `Protego` to respect site policies.
   * Built-in exponential backoff retry logic to handle HTTP 429 (Rate Limit) responses gracefully.
2. **Noise Removal & Extraction**
   * Leverages `Trafilatura` to strip out navigation bars, footers, and boilerplate advertisements, extracting clean body text and metadata.
3. **Strict Guard Validation**
   * Enforces data integrity using `Pydantic` models to filter out malformed pages, empty texts, or broken URLs before downstream processing.
4. **Token-Aware Chunking & Concurrency**
   * Implements `tiktoken` (`cl100k_base`) alongside LangChain's `RecursiveCharacterTextSplitter` to chunk documents precisely by token lengths rather than arbitrary character counts.
   * Concurrency management via `asyncio.Semaphore` and `asyncio.gather` for high-throughput multi-domain scraping.
5. **Observability & Metrics**
   * Enterprise-grade structured logging (`logging` module).
   * Automatically compiles pipeline statistics and exports a local `chunk_stats.json` summary report.

---

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **Package Manager:** `uv`
* **Networking:** `httpx`
* **Compliance:** `Protego`
* **Extraction:** `Trafilatura`
* **Validation:** `Pydantic`
* **Chunking:** `tiktoken`, `langchain-text-splitters`

---

## 📂 Project Structure

```text
async-scraper-project/
├── src/
│   └── async_scraper_project/
│       └── main.py          # Core asynchronous pipeline orchestrator
├── pyproject.toml           # Dependency configuration
├── chunk_stats.json         # Generated pipeline metrics output
└── README.md
# Autonomous AI Web Scraping Framework

An enterprise-grade, autonomous web scraping framework. The system autonomously learns website structures, optimizes crawling strategies, handles anti-bot challenges, and refines extraction rules over time without manual reconfiguration.

---

## Codebase Directory Structure

```
.
├── configs/            # YAML configuration definitions
├── mcps/               # Model Context Protocol (MCP) toolkits
│   ├── classification/ # URL classifiers & DOM heuristics
│   ├── crawler/        # Queue managers & crawl budget controllers
│   ├── discovery/      # robots.txt, sitemaps, & menu hierarchy parsers
│   ├── execution/      # Caching, rate limiting, and HTTP clients
│   ├── extraction/     # Extraction selectors & LLM fallback processors
│   ├── knowledge/      # Self-learning profile engines
│   ├── playwright/     # Headless Chromium automation pool
│   ├── storage/        # Output formats (CSV, NDJSON, SQLite)
│   └── validation/     # Field types & integrity validators
├── shared/             # Common contracts, data schemas, & helpers
│   ├── contracts/      # Custom standard error formats
│   ├── models/         # Pydantic schemas (Product, Stats, Task)
│   └── utils/          # Config, logging, & LLM connection fallbacks
├── tests/              # Automated verification suite
│   ├── fixtures/       # Mock sitemaps, robots.txt, & page HTML
│   ├── integration/    # Crawl pipeline flow tests
│   └── unit/           # MCP test suites
├── web/                # Backend API & Dashboard webserver
│   ├── static/         # Frontend dashboard assets (index.html)
│   ├── crawler_manager.py # Multi-threaded web session scheduler
│   └── server.py       # FastAPI application endpoints
├── agent.py            # ADK core agent loop runner
├── main.py             # CLI runner entrypoint
└── run.py              # Windows-compatible server launcher
```

---

## Architecture & Component Responsibilities

1. **`mcps/` (Model Context Protocol)**:
   * **Discovery**: Evaluates website metadata, structural navigation hierarchy, and sitemaps.
   * **Execution**: Centralized gateway for all web requests. Protects domains with caching, concurrency locks, and rate limits, and automatically escalates JavaScript rendering to Playwright if anti-bot walls or client-side rendering (CSR) templates are detected.
   * **Playwright**: Spawns and recycles headless browser instances.
   * **Classification**: Analyzes links to identify whether they lead to category hubs, product pages, or pagination links.
   * **Extraction**: Extracts nested product details (titles, prices, images, specs) utilizing a fallback chain: `JSON-LD` → `CSS Selectors` → `XPath` → `Semantic DOM` → `LLM Parsing`.
   * **Validation**: Restricts noise by filtering out listings with invalid prices, missing essential metadata, or duplicate SKUs.
   * **Storage**: Streams structured records into CSV, ZIP files of JSONs, or SQLite databases.
   * **Knowledge**: Updates site profile logs to persist bot-detection levels and crawl limits.
2. **`shared/`**: Consolidates shared definitions, Pydantic type specifications, standard loggers, and the fallback LLM client (supporting Gemini, Groq, and OpenRouter).
3. **`web/`**: Runs a FastAPI application and SSE (Server-Sent Events) live log stream dashboard.
4. **`run.py`**: A helper script resolving Windows-specific event loop issues by forcing `ProactorEventLoop` when spawning browser subprocesses in Uvicorn.

---

## Extraction Accuracy Benchmarks

The system has been benchmarked across various target websites with the following accuracy scores:

| Target Website | Accuracy |
|---|---|
| Husqvarna | 100% |
| JLG | 100% |
| Bobcat | 90% |
| Kawasaki | 85% |
| JCB | 84% |
| **Overall Average** | **91.8%** |

---

## Setup Guide for New Devices

Follow these steps to set up and run the codebase on a clean machine:

### 1. Prerequisites
Ensure you have **Python 3.11** to **Python 3.13** installed.

### 2. Set Up a Virtual Environment
Create a clean virtual environment to prevent package version conflicts:
```bash
# Create the environment
python -m venv .venv

# Activate the environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Activate the environment (Linux/macOS)
source .venv/bin/activate
```

### 3. Install Dependencies
Install all required libraries and download the Chromium binaries for Playwright:
```bash
# Install packages
pip install -r requirements.txt

# Download browser packages
playwright install chromium
```

### 4. Configure Environments
Copy the `.env.example` file to `.env` and fill in your LLM access credentials:
```bash
cp .env.example .env
```
Open `.env` and configure your keys:
* `GOOGLE_API_KEY` (Gemini Client - Primary)
* `GROQ_API_KEY` (Groq fallback)
* `OPENROUTER_API_KEY` (OpenRouter fallback)

---

## Running the Application

### Launching the Dashboard Web Server
Start the backend API and frontend panel by running the Windows-compatible launcher:
```bash
python run.py
```
Open **http://127.0.0.1:8000** in your browser to access the crawler controls.

### Command Line Interface (CLI)
Alternatively, run crawls directly using the command-line executor:
```bash
python main.py "Scrape 5 products from https://www.kawasaki.com/en-us/"
```

### Running Tests
Execute the verification suite to ensure everything is functioning correctly:
```bash
pytest -v tests/unit/
```

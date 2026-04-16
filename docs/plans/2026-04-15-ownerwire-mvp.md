# OwnerWire MVP Implementation Plan

> For Hermes: follow the subagent-driven-development mindset even when implementing directly.

Goal: Launch a live, public API and AI-readable website for normalized SEC Form 4 and Form 144 ownership events.

Architecture: One FastAPI service on Render serves both the website and JSON API. Data is fetched live from official SEC endpoints and normalized into a stable JSON schema.

Tech stack: Python 3.12, FastAPI, requests, Jinja2, markdown, Render, GitHub.

---

## Task 1: Define the wedge
- Choose a narrow business thesis around executed insider trades plus planned insider sales.
- Position the product for AI agents instead of human dashboards.
- Confirm the initial endpoints and docs surface.

## Task 2: Build SEC adapters
- Pull issuer/ticker mappings from `company_tickers.json`.
- Pull issuer submissions from `data.sec.gov/submissions/CIK....json`.
- Pull latest market-wide filings from the SEC Atom feed.
- Convert transformed filing paths into raw XML paths.

## Task 3: Build parsers
- Parse Form 4 issuer, reporter, relationships, transactions, footnotes, and citations.
- Parse Form 144 issuer, seller, planned sale details, remarks, prior sales, and citations.
- Normalize both forms into one event-oriented JSON schema.

## Task 4: Build the website and docs
- Serve homepage, HTML docs, markdown docs, llms files, robots, and sitemap.
- Link OpenAPI and examples prominently.
- Make the docs easy for both browsers and agents to ingest.

## Task 5: Verify locally
- Install dependencies.
- Run the server.
- Hit homepage and API routes.
- Fix any parser or serialization bugs.

## Task 6: Publish
- Create GitHub repo.
- Push code.
- Create Render service.
- Verify public URLs.
- Email the website to team@scottyshelpers.org.

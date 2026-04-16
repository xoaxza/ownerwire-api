# OwnerWire

OwnerWire is a live, citation-backed API for messy SEC ownership filings.

The initial wedge is simple:
- Form 4: executed insider transactions
- Form 144: planned insider sales

Instead of making an AI agent scrape EDGAR XML, OwnerWire returns normalized JSON with:
- issuer name, ticker, and CIK
- reporting person / seller
- role and relationship to issuer
- normalized transaction objects
- planned sale details
- footnotes and remarks
- direct links back to the raw SEC filing

## Why this exists

AI agents do not need another quote API. They need trustworthy answers for messy, high-value edge cases.

SEC ownership filings are public and machine-readable, but still painful to consume directly:
- Form 4 mixes issuer data, owner roles, footnotes, and derivative/non-derivative tables.
- Form 144 contains planned sale notices in a separate XML schema.
- The SEC current filings feed is not agent-friendly out of the box.

OwnerWire packages that into a small API and website that both humans and AI agents can read.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Important routes

- `/` homepage
- `/reference` HTML docs
- `/reference.md` raw markdown docs
- `/openapi.json` OpenAPI schema
- `/docs` Swagger UI
- `/redoc` ReDoc
- `/llms.txt`
- `/llms-full.txt`
- `/api/v1/search?q=dell`
- `/api/v1/issuers/DELL/events`
- `/api/v1/recent?forms=4,144&limit=10`

## Source and licensing

This MVP uses official SEC public filing data and links every event back to the SEC source URLs.

## Disclaimer

OwnerWire is infrastructure, not investment advice.

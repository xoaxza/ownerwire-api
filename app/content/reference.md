# OwnerWire API Reference

OwnerWire turns messy SEC ownership filings into citation-backed JSON for AI agents.

Base URL: `__BASE_URL__`

Primary sources:
- SEC issuer directory: `https://www.sec.gov/files/company_tickers.json`
- SEC company submissions API: `https://data.sec.gov/submissions/CIK##########.json`
- SEC current filings Atom feed: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom`

Covered filing types in v1:
- `4` and `4/A`: executed insider transactions
- `144` and `144/A`: planned insider sale notices

Why this is useful:
- Form 4 exposes actual insider buys, sells, grants, and derivative moves.
- Form 144 exposes planned insider sales before those sales necessarily happen.
- Both are public, but neither is pleasant for AI agents to normalize on the fly.

## Discovery endpoints

- Homepage: `__BASE_URL__/`
- OpenAPI: `__BASE_URL__/openapi.json`
- Swagger UI: `__BASE_URL__/docs`
- ReDoc: `__BASE_URL__/redoc`
- LLM index: `__BASE_URL__/llms.txt`
- Full LLM notes: `__BASE_URL__/llms-full.txt`
- Markdown docs: `__BASE_URL__/reference.md`

## Response conventions

Every JSON response returns:

```json
{
  "data": [],
  "meta": {
    "source": "SEC EDGAR",
    "generated_at": "2026-04-16T03:10:00Z"
  }
}
```

Fields to expect on event objects:
- `event_id`
- `event_type`
- `form_type`
- `accession_number`
- `filing_date`
- `accepted_at`
- `issuer`
- `citations`
- plus form-specific payload like `transactions` or `planned_sale`

## Endpoint: search issuers

`GET /api/v1/search?q=dell`

Use this to find the canonical issuer ticker, CIK, and company name.

Example:

```bash
curl '__BASE_URL__/api/v1/search?q=dell'
```

## Endpoint: issuer ownership events

`GET /api/v1/issuers/{ticker}/events?forms=4,144&limit=10`

Example:

```bash
curl '__BASE_URL__/api/v1/issuers/DELL/events?forms=4,144&limit=5'
```

What it does:
- pulls the issuer's recent submissions from SEC `data.sec.gov`
- filters to the requested forms
- fetches the raw XML filing
- returns normalized event objects

## Endpoint: recent market-wide events

`GET /api/v1/recent?forms=4,144&limit=10`

Example:

```bash
curl '__BASE_URL__/api/v1/recent?forms=4,144&limit=5'
```

What it does:
- reads the SEC current filings Atom feed
- deduplicates entries by accession number
- fetches the raw XML filing from the filing index page
- returns normalized event objects

## Form 4 shape

A Form 4 event includes:
- issuer CIK, issuer name, issuer ticker
- one or more `reporting_owners`
- a `primary_reporter`
- `affirmed_10b5_1` if present
- `transactions` list with:
  - `security_title`
  - `transaction_date`
  - `transaction_code`
  - `acquired_disposed`
  - `shares`
  - `price_per_share`
  - `notional`
  - `shares_after_transaction`
  - `direct_or_indirect`
  - `ownership_nature`
  - `footnotes`

## Form 144 shape

A Form 144 event includes:
- issuer CIK, issuer name, issuer ticker
- `seller`
- `planned_sale`
- `acquisition_context`
- `prior_sales_last_3_months`
- `remarks`
- `notice_signature`

`planned_sale` is designed to answer the question: "What insider or large holder is signaling intent to sell, how much, and on roughly what timetable?"

## Freshness and caveats

- OwnerWire pulls directly from official SEC endpoints at request time.
- The SEC source is authoritative; OwnerWire is a normalization layer.
- Free Render instances can spin down after inactivity.
- SEC fields can occasionally be blank, amended, or oddly structured. When in doubt, use the `citations.raw_xml_url` and `citations.sec_index_url` fields.

## Suggested AI-agent usage

Good prompts or workflows:
- "Show me the last 5 insider events for DELL."
- "Watch for new Form 144 filings on TVTX."
- "Summarize all Form 4 buys vs sells in the latest market-wide feed."
- "Pull the raw SEC citation URLs for this event before you act."

## Terms

OwnerWire is infrastructure, not investment advice.

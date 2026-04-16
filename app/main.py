from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.parsers import parse_event
from app.sec_client import (
    DATA_BASE,
    SecClientError,
    build_recent_filing_index,
    get_issuer_by_ticker,
    get_submissions,
    get_text,
    parse_forms_arg,
    raw_xml_url_from_index,
    raw_xml_url_from_submission,
    search_issuers,
)

BASE_DIR = Path(__file__).resolve().parent
CONTENT_DIR = BASE_DIR / "content"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(
    title="OwnerWire API",
    description=(
        "Citation-backed API for messy SEC ownership filings. OwnerWire normalizes "
        "Form 4 executed insider transactions and Form 144 planned sale notices into "
        "agent-friendly JSON."
    ),
    version="0.1.0",
    contact={"email": "team@scottyshelpers.org"},
    openapi_tags=[
        {
            "name": "Issuer directory",
            "description": "Search the SEC issuer directory by ticker or company name.",
        },
        {
            "name": "Ownership events",
            "description": "Live SEC ownership events for a single issuer or the market-wide feed.",
        },
    ],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_base_url(request: Request) -> str:
    if settings.base_url:
        return settings.base_url
    return str(request.base_url).rstrip("/")


def load_content(file_name: str, base_url: str) -> str:
    text = (CONTENT_DIR / file_name).read_text(encoding="utf-8")
    return text.replace("__BASE_URL__", base_url)


def envelope(data: Any, **meta: Any) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {
            "source": "SEC EDGAR",
            "generated_at": utc_now_iso(),
            **meta,
        },
    }


def build_submission_url(issuer_cik: str) -> str:
    return f"{DATA_BASE}/submissions/CIK{issuer_cik}.json"


def serialize_issuer_filings(issuer: dict[str, str], forms: list[str], limit: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    submissions = get_submissions(issuer["issuer_cik"])
    recent = submissions["filings"]["recent"]
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    total = len(recent["form"])
    for idx in range(total):
        form_type = str(recent["form"][idx]).upper()
        if form_type not in forms:
            continue
        filing = {
            "form_type": form_type,
            "accession_number": recent["accessionNumber"][idx],
            "filing_date": recent["filingDate"][idx],
            "accepted_at": recent["acceptanceDateTime"][idx],
            "index_url": (
                f"https://www.sec.gov/Archives/edgar/data/{int(issuer['issuer_cik'])}/"
                f"{recent['accessionNumber'][idx].replace('-', '')}/"
                f"{recent['accessionNumber'][idx]}-index.htm"
            ),
            "issuer_ticker": issuer["ticker"],
            "submission_url": build_submission_url(issuer["issuer_cik"]),
        }
        raw_xml_url = raw_xml_url_from_submission(
            issuer["issuer_cik"],
            filing["accession_number"],
            recent["primaryDocument"][idx],
        )
        filing["raw_xml_url"] = raw_xml_url
        try:
            xml_text = get_text(raw_xml_url)
            events.append(parse_event(xml_text, filing))
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "accession_number": filing["accession_number"],
                    "reason": str(exc),
                }
            )
        if len(events) >= limit:
            break

    return events, errors


def serialize_recent_filings(forms: list[str], limit: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates = build_recent_filing_index(forms, max(limit * 3, 20))
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for filing in candidates:
        try:
            raw_xml_url = raw_xml_url_from_index(filing["index_url"])
            filing["raw_xml_url"] = raw_xml_url
            filing["submission_url"] = None
            filing["accepted_at"] = filing.get("updated_at")
            xml_text = get_text(raw_xml_url)
            events.append(parse_event(xml_text, filing))
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "accession_number": filing.get("accession_number", "unknown"),
                    "reason": str(exc),
                }
            )
        if len(events) >= limit:
            break

    return events, errors


@app.middleware("http")
async def add_agent_discovery_headers(request: Request, call_next):
    response = await call_next(request)
    base_url = resolve_base_url(request)
    if request.url.path.startswith("/api/"):
        response.headers["Link"] = f'<{base_url}/openapi.json>; rel="describedby"; type="application/json"'
        response.headers["X-OwnerWire-Source"] = "SEC EDGAR"
    return response


@app.exception_handler(SecClientError)
async def sec_client_error_handler(_: Request, exc: SecClientError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "type": "upstream_sec_error",
                "message": str(exc),
            }
        },
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request) -> HTMLResponse:
    base_url = resolve_base_url(request)
    context = {
        "request": request,
        "base_url": base_url,
        "title": "OwnerWire",
        "subtitle": "Live SEC insider transaction and planned sale data for AI agents.",
        "examples": {
            "search": f"{base_url}/api/v1/search?q=dell",
            "issuer_events": f"{base_url}/api/v1/issuers/DELL/events?forms=4,144&limit=5",
            "recent": f"{base_url}/api/v1/recent?forms=4,144&limit=5",
            "openapi": f"{base_url}/openapi.json",
            "llms": f"{base_url}/llms.txt",
            "reference": f"{base_url}/reference",
        },
    }
    return templates.TemplateResponse("home.html", context)


@app.get("/reference", response_class=HTMLResponse, include_in_schema=False)
def reference(request: Request) -> HTMLResponse:
    base_url = resolve_base_url(request)
    md_text = load_content("reference.md", base_url)
    html = markdown.markdown(md_text, extensions=["fenced_code", "tables"])
    return templates.TemplateResponse(
        "reference.html",
        {
            "request": request,
            "base_url": base_url,
            "title": "OwnerWire API reference",
            "content": html,
        },
    )


@app.get("/reference.md", response_class=PlainTextResponse, include_in_schema=False)
def reference_markdown(request: Request) -> PlainTextResponse:
    return PlainTextResponse(load_content("reference.md", resolve_base_url(request)))


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
def llms_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(load_content("llms.txt", resolve_base_url(request)))


@app.get("/llms-full.txt", response_class=PlainTextResponse, include_in_schema=False)
def llms_full_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(load_content("llms-full.txt", resolve_base_url(request)))


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots_txt(request: Request) -> PlainTextResponse:
    base_url = resolve_base_url(request)
    return PlainTextResponse(f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n")


@app.get("/sitemap.xml", response_class=Response, include_in_schema=False)
def sitemap_xml(request: Request) -> Response:
    base_url = resolve_base_url(request)
    urls = [
        f"{base_url}/",
        f"{base_url}/reference",
        f"{base_url}/reference.md",
        f"{base_url}/openapi.json",
        f"{base_url}/docs",
        f"{base_url}/redoc",
        f"{base_url}/llms.txt",
        f"{base_url}/llms-full.txt",
    ]
    body = "".join([f"<url><loc>{url}</loc></url>" for url in urls])
    return Response(
        content=(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"
            f"{body}</urlset>"
        ),
        media_type="application/xml",
    )


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name, "time": utc_now_iso()}


@app.get(
    "/api/v1/search",
    tags=["Issuer directory"],
    operation_id="searchIssuers",
    summary="Search issuers by ticker or company name",
    description=(
        "Search the SEC issuer directory sourced from company_tickers.json. Useful for "
        "turning a fuzzy ticker or company-name query into a canonical issuer CIK."
    ),
)
def api_search(
    q: str = Query(..., min_length=1, description="Ticker or company name query."),
    limit: int = Query(10, ge=1, le=25, description="Maximum number of matches to return."),
) -> dict[str, Any]:
    matches = search_issuers(q, limit)
    return envelope(matches, query=q, count=len(matches))


@app.get(
    "/api/v1/issuers/{ticker}/events",
    tags=["Ownership events"],
    operation_id="getIssuerOwnershipEvents",
    summary="Get recent ownership events for a single issuer",
    description=(
        "Return recent normalized SEC ownership events for one issuer. Supported forms: "
        "Form 4, Form 4/A, Form 144, and Form 144/A."
    ),
)
def issuer_events(
    ticker: str,
    forms: str = Query("4,144", description="Comma-separated list of forms, e.g. 4,144 or 4/A,144/A."),
    limit: int = Query(10, ge=1, le=25, description="Maximum number of normalized events to return."),
) -> dict[str, Any]:
    issuer = get_issuer_by_ticker(ticker)
    if issuer is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")

    selected_forms = parse_forms_arg(forms)
    events, errors = serialize_issuer_filings(issuer, selected_forms, limit)
    return envelope(
        events,
        ticker=issuer["ticker"],
        issuer_cik=issuer["issuer_cik"],
        issuer_name=issuer["issuer_name"],
        forms=selected_forms,
        count=len(events),
        errors=errors,
    )


@app.get(
    "/api/v1/recent",
    tags=["Ownership events"],
    operation_id="getRecentOwnershipEvents",
    summary="Get the latest market-wide ownership events",
    description=(
        "Read the SEC current filings Atom feed, deduplicate entries by accession number, "
        "fetch the raw XML filing, and return normalized event objects."
    ),
)
def recent_events(
    forms: str = Query("4,144", description="Comma-separated list of forms, e.g. 4,144."),
    limit: int = Query(10, ge=1, le=25, description="Maximum number of normalized events to return."),
) -> dict[str, Any]:
    selected_forms = parse_forms_arg(forms)
    events, errors = serialize_recent_filings(selected_forms, limit)
    return envelope(events, forms=selected_forms, count=len(events), errors=errors)

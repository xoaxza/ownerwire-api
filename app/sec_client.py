from __future__ import annotations

from functools import lru_cache
from html import unescape
import re
import time
from typing import Any
from urllib.parse import quote, urljoin
import xml.etree.ElementTree as ET

import requests

from app.config import settings

SEC_BASE = "https://www.sec.gov"
DATA_BASE = "https://data.sec.gov"

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": settings.sec_user_agent,
        "Accept": "application/json, application/atom+xml, text/xml, text/html;q=0.9, */*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }
)

SUPPORTED_FORMS = {"4", "4/A", "144", "144/A"}


class SecClientError(RuntimeError):
    pass


def _request(url: str) -> requests.Response:
    response = SESSION.get(url, timeout=settings.request_timeout)
    if response.status_code >= 400:
        raise SecClientError(f"SEC request failed for {url}: {response.status_code}")
    return response


def _time_bucket(seconds: int) -> int:
    return int(time.time() / seconds)


@lru_cache(maxsize=4)
def _company_directory_cached(bucket: int) -> dict[str, Any]:
    data = _request(f"{SEC_BASE}/files/company_tickers.json").json()
    entries: list[dict[str, str]] = []
    by_ticker: dict[str, dict[str, str]] = {}
    by_cik: dict[str, dict[str, str]] = {}

    for value in data.values():
        ticker = str(value["ticker"]).upper()
        entry = {
            "ticker": ticker,
            "issuer_name": value["title"],
            "issuer_cik": f"{int(value['cik_str']):010d}",
        }
        entries.append(entry)
        by_ticker[ticker] = entry
        by_cik[entry["issuer_cik"]] = entry

    entries.sort(key=lambda item: (item["ticker"], item["issuer_name"]))
    return {"entries": entries, "by_ticker": by_ticker, "by_cik": by_cik}


def get_company_directory() -> dict[str, Any]:
    return _company_directory_cached(_time_bucket(86400))


def get_issuer_by_ticker(ticker: str) -> dict[str, str] | None:
    return get_company_directory()["by_ticker"].get(ticker.upper())


def get_issuer_by_cik(cik: str) -> dict[str, str] | None:
    normalized = f"{int(str(cik)):010d}"
    return get_company_directory()["by_cik"].get(normalized)


def search_issuers(query: str, limit: int = 10) -> list[dict[str, str]]:
    q = query.strip().upper()
    if not q:
        return []

    entries = get_company_directory()["entries"]

    def rank(entry: dict[str, str]) -> tuple[int, int, str]:
        ticker = entry["ticker"]
        name = entry["issuer_name"].upper()
        if ticker == q:
            return (0, len(ticker), ticker)
        if ticker.startswith(q):
            return (1, len(ticker), ticker)
        if q in ticker:
            return (2, len(ticker), ticker)
        if name.startswith(q):
            return (3, len(name), ticker)
        return (4, len(name), ticker)

    matches = [
        entry
        for entry in entries
        if q in entry["ticker"] or q in entry["issuer_name"].upper()
    ]
    matches.sort(key=rank)
    return matches[:limit]


@lru_cache(maxsize=500)
def _submissions_cached(cik: str, bucket: int) -> dict[str, Any]:
    normalized = f"{int(str(cik)):010d}"
    return _request(f"{DATA_BASE}/submissions/CIK{normalized}.json").json()


def get_submissions(cik: str) -> dict[str, Any]:
    return _submissions_cached(cik, _time_bucket(300))


@lru_cache(maxsize=800)
def _text_cached(url: str) -> str:
    return _request(url).text


def get_text(url: str) -> str:
    return _text_cached(url)


@lru_cache(maxsize=800)
def _recent_feed_cached(form_type: str, count: int, bucket: int) -> list[dict[str, str]]:
    url = (
        f"{SEC_BASE}/cgi-bin/browse-edgar?action=getcurrent&type={quote(form_type)}"
        f"&owner=include&count={count}&output=atom"
    )
    xml_text = _request(url).content
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries: list[dict[str, str]] = []

    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", default="", namespaces=ns)
        link = entry.find("atom:link", ns)
        summary = entry.findtext("atom:summary", default="", namespaces=ns)
        updated_at = entry.findtext("atom:updated", default="", namespaces=ns)
        entry_id = entry.findtext("atom:id", default="", namespaces=ns)
        accession_match = re.search(r"accession-number=([0-9\-]+)", entry_id)
        filed_match = re.search(r"Filed:</b>\s*([0-9\-]+)", summary)

        if link is None or not accession_match:
            continue

        entries.append(
            {
                "form_type": form_type,
                "title": title,
                "index_url": link.attrib["href"],
                "summary_html": summary,
                "updated_at": updated_at,
                "accession_number": accession_match.group(1),
                "filing_date": filed_match.group(1) if filed_match else "",
            }
        )

    return entries


def get_recent_feed_entries(form_type: str, count: int) -> list[dict[str, str]]:
    return _recent_feed_cached(form_type, count, _time_bucket(60))


def parse_forms_arg(forms: str) -> list[str]:
    items = []
    for raw in forms.split(","):
        form = raw.strip().upper()
        if not form:
            continue
        if form not in SUPPORTED_FORMS:
            raise SecClientError(
                f"Unsupported form '{form}'. Supported values: {', '.join(sorted(SUPPORTED_FORMS))}."
            )
        items.append(form)
    return items or ["4", "144"]


def raw_xml_url_from_submission(issuer_cik: str, accession_number: str, primary_document: str) -> str:
    file_name = primary_document.split("/")[-1]
    accession_path = accession_number.replace("-", "")
    cik_path = str(int(issuer_cik))
    return f"{SEC_BASE}/Archives/edgar/data/{cik_path}/{accession_path}/{file_name}"


def raw_xml_url_from_index(index_url: str) -> str:
    page = get_text(index_url)
    candidates = re.findall(r'href="([^"]+\.xml)"', page, flags=re.IGNORECASE)
    normalized = [unescape(candidate) for candidate in candidates]
    for candidate in normalized:
        lower = candidate.lower()
        if "/archives/" in lower and "/xsl" not in lower:
            return urljoin(SEC_BASE, candidate)
    raise SecClientError(f"Could not find raw XML document in filing index: {index_url}")


def build_recent_filing_index(forms: list[str], limit: int) -> list[dict[str, str]]:
    per_form_count = max(limit * 4, 20)
    merged: list[dict[str, str]] = []
    seen: set[str] = set()

    for form in forms:
        for entry in get_recent_feed_entries(form, per_form_count):
            accession = entry["accession_number"]
            if accession in seen:
                continue
            seen.add(accession)
            merged.append(entry)

    merged.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return merged[:limit]

from __future__ import annotations

from datetime import datetime
import re
from typing import Any
import xml.etree.ElementTree as ET

from app.sec_client import get_issuer_by_cik


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = " ".join(value.split())
    return stripped or None


def _text(node: ET.Element | None, path: str | None = None, ns: dict[str, str] | None = None) -> str | None:
    target = node.find(path, ns) if node is not None and path else node
    if target is None or target.text is None:
        return None
    return _clean(target.text)


def _boolish(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "y", "yes"}:
        return True
    if normalized in {"0", "false", "n", "no"}:
        return False
    return None


def _number(value: str | None) -> int | float | None:
    if value is None:
        return None
    normalized = value.replace(",", "").replace("$", "").strip()
    if not normalized:
        return None
    try:
        as_float = float(normalized)
    except ValueError:
        return None
    return int(as_float) if as_float.is_integer() else as_float


def _iso_date(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d%H%M%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt == "%Y%m%d%H%M%S":
                return parsed.isoformat() + "Z"
            return parsed.date().isoformat()
        except ValueError:
            continue
    return raw


def _relationship_summary(relationship: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if relationship.get("is_director"):
        parts.append("director")
    if relationship.get("is_officer"):
        title = relationship.get("officer_title")
        parts.append(title if title else "officer")
    if relationship.get("is_ten_percent_owner"):
        parts.append("10% owner")
    if relationship.get("is_other"):
        other = relationship.get("other_text")
        parts.append(other if other else "other insider")
    if not parts:
        return None
    return ", ".join(parts)


def _footnote_map(root: ET.Element) -> dict[str, str]:
    notes: dict[str, str] = {}
    for footnote in root.findall(".//footnote"):
        footnote_id = footnote.attrib.get("id")
        if footnote_id:
            notes[footnote_id] = _clean("".join(footnote.itertext())) or ""
    return notes


def _node_footnotes(node: ET.Element, note_map: dict[str, str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for child in node.iter():
        if not child.tag.endswith("footnoteId"):
            continue
        footnote_id = child.attrib.get("id")
        note = note_map.get(footnote_id or "")
        if note and note not in seen:
            seen.add(note)
            results.append(note)
    return results


def _citation_block(filing: dict[str, Any]) -> dict[str, str | None]:
    return {
        "sec_index_url": filing.get("index_url"),
        "raw_xml_url": filing.get("raw_xml_url"),
        "sec_submission_url": filing.get("submission_url"),
    }


def parse_form4(xml_text: str, filing: dict[str, Any]) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    footnotes = _footnote_map(root)

    issuer = {
        "cik": _text(root, "issuer/issuerCik"),
        "name": _text(root, "issuer/issuerName"),
        "ticker": _text(root, "issuer/issuerTradingSymbol") or filing.get("issuer_ticker"),
    }

    reporting_owners: list[dict[str, Any]] = []
    for owner in root.findall("reportingOwner"):
        relationship = {
            "is_director": bool(_boolish(_text(owner, "reportingOwnerRelationship/isDirector"))),
            "is_officer": bool(_boolish(_text(owner, "reportingOwnerRelationship/isOfficer"))),
            "is_ten_percent_owner": bool(
                _boolish(_text(owner, "reportingOwnerRelationship/isTenPercentOwner"))
            ),
            "is_other": bool(_boolish(_text(owner, "reportingOwnerRelationship/isOther"))),
            "officer_title": _text(owner, "reportingOwnerRelationship/officerTitle"),
            "other_text": _text(owner, "reportingOwnerRelationship/otherText"),
        }
        reporting_owners.append(
            {
                "cik": _text(owner, "reportingOwnerId/rptOwnerCik"),
                "name": _text(owner, "reportingOwnerId/rptOwnerName"),
                "relationship": relationship,
                "role_summary": _relationship_summary(relationship),
            }
        )

    transactions: list[dict[str, Any]] = []
    for table_name, security_kind in (
        ("nonDerivativeTable/nonDerivativeTransaction", "non-derivative"),
        ("derivativeTable/derivativeTransaction", "derivative"),
    ):
        for tx in root.findall(table_name):
            shares = _number(_text(tx, "transactionAmounts/transactionShares/value"))
            price = _number(_text(tx, "transactionAmounts/transactionPricePerShare/value"))
            notional = None
            if shares is not None and price is not None:
                notional = round(float(shares) * float(price), 4)

            transaction = {
                "security_kind": security_kind,
                "security_title": _text(tx, "securityTitle/value"),
                "transaction_date": _iso_date(_text(tx, "transactionDate/value")),
                "transaction_code": _text(tx, "transactionCoding/transactionCode"),
                "transaction_form_type": _text(tx, "transactionCoding/transactionFormType"),
                "acquired_disposed": _text(
                    tx, "transactionAmounts/transactionAcquiredDisposedCode/value"
                ),
                "shares": shares,
                "price_per_share": price,
                "notional": notional,
                "shares_after_transaction": _number(
                    _text(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
                ),
                "direct_or_indirect": _text(
                    tx, "ownershipNature/directOrIndirectOwnership/value"
                ),
                "ownership_nature": _text(tx, "ownershipNature/natureOfOwnership/value"),
                "underlying_security_title": _text(tx, "underlyingSecurity/underlyingSecurityTitle/value"),
                "underlying_security_shares": _number(
                    _text(tx, "underlyingSecurity/underlyingSecurityShares/value")
                ),
                "exercise_price": _number(_text(tx, "conversionOrExercisePrice/value")),
                "footnotes": _node_footnotes(tx, footnotes),
            }
            transactions.append(transaction)

    primary_reporter = reporting_owners[0] if reporting_owners else None
    form_type = filing.get("form_type") or _text(root, "documentType") or "4"

    headline = None
    if primary_reporter:
        headline = (
            f"{issuer.get('ticker') or issuer.get('name')} Form {form_type} filed by "
            f"{primary_reporter.get('name')} with {len(transactions)} transaction(s)"
        )

    return {
        "event_id": f"{form_type}:{filing.get('accession_number')}",
        "event_type": "executed_insider_transaction",
        "form_type": form_type,
        "is_amendment": form_type.endswith("/A"),
        "headline": headline,
        "accession_number": filing.get("accession_number"),
        "filing_date": filing.get("filing_date"),
        "accepted_at": _iso_date(filing.get("accepted_at")) or filing.get("accepted_at"),
        "period_of_report": _iso_date(_text(root, "periodOfReport")),
        "issuer": issuer,
        "reporting_owners": reporting_owners,
        "primary_reporter": primary_reporter,
        "affirmed_10b5_1": _boolish(_text(root, "aff10b5One")),
        "transactions": transactions,
        "remarks": _text(root, "remarks"),
        "footnotes": footnotes,
        "citations": _citation_block(filing),
        "source": "SEC EDGAR ownership XML",
    }


def parse_form144(xml_text: str, filing: dict[str, Any]) -> dict[str, Any]:
    ns = {
        "o": "http://www.sec.gov/edgar/ownership",
        "c": "http://www.sec.gov/edgar/common",
    }
    root = ET.fromstring(xml_text)

    issuer_cik = _text(root, ".//o:issuerInfo/o:issuerCik", ns)
    issuer_lookup = get_issuer_by_cik(issuer_cik or "0") if issuer_cik else None
    issuer = {
        "cik": issuer_cik,
        "name": _text(root, ".//o:issuerInfo/o:issuerName", ns),
        "ticker": filing.get("issuer_ticker") or (issuer_lookup or {}).get("ticker"),
    }

    relationships = [
        rel
        for rel in (
            _clean(node.text)
            for node in root.findall(".//o:issuerInfo/o:relationshipsToIssuer/o:relationshipToIssuer", ns)
        )
        if rel
    ]

    prior_sales: list[dict[str, Any]] = []
    for sale in root.findall(".//o:securitiesSoldInPast3Months", ns):
        prior_sales.append(
            {
                "seller_name": _text(sale, "o:sellerDetails/o:name", ns),
                "security_title": _text(sale, "o:securitiesClassTitle", ns),
                "sale_date": _iso_date(_text(sale, "o:saleDate", ns)),
                "shares_sold": _number(_text(sale, "o:amountOfSecuritiesSold", ns)),
                "gross_proceeds": _number(_text(sale, "o:grossProceeds", ns)),
            }
        )

    units_to_sell = _number(_text(root, ".//o:securitiesInformation/o:noOfUnitsSold", ns))
    aggregate_market_value = _number(
        _text(root, ".//o:securitiesInformation/o:aggregateMarketValue", ns)
    )
    estimated_sale_price = None
    if units_to_sell not in (None, 0) and aggregate_market_value is not None:
        estimated_sale_price = round(float(aggregate_market_value) / float(units_to_sell), 6)

    form_type = filing.get("form_type") or _text(root, ".//o:submissionType", ns) or "144"
    seller_name = _text(
        root,
        ".//o:issuerInfo/o:nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
        ns,
    )

    headline = (
        f"{issuer.get('ticker') or issuer.get('name')} Form {form_type} planned sale notice for "
        f"{seller_name or 'unknown seller'}"
    )

    return {
        "event_id": f"{form_type}:{filing.get('accession_number')}",
        "event_type": "planned_insider_sale_notice",
        "form_type": form_type,
        "is_amendment": form_type.endswith("/A"),
        "headline": headline,
        "accession_number": filing.get("accession_number"),
        "filing_date": filing.get("filing_date"),
        "accepted_at": _iso_date(filing.get("accepted_at")) or filing.get("accepted_at"),
        "issuer": issuer,
        "seller": {
            "name": seller_name,
            "relationships_to_issuer": relationships,
        },
        "planned_sale": {
            "security_title": _text(root, ".//o:securitiesInformation/o:securitiesClassTitle", ns),
            "shares_to_sell": units_to_sell,
            "aggregate_market_value": aggregate_market_value,
            "estimated_sale_price": estimated_sale_price,
            "approx_sale_date": _iso_date(
                _text(root, ".//o:securitiesInformation/o:approxSaleDate", ns)
            ),
            "exchange": _text(root, ".//o:securitiesInformation/o:securitiesExchangeName", ns),
            "units_outstanding": _number(
                _text(root, ".//o:securitiesInformation/o:noOfUnitsOutstanding", ns)
            ),
            "broker_name": _text(
                root, ".//o:securitiesInformation/o:brokerOrMarketmakerDetails/o:name", ns
            ),
        },
        "acquisition_context": {
            "acquired_date": _iso_date(_text(root, ".//o:securitiesToBeSold/o:acquiredDate", ns)),
            "amount_acquired": _number(
                _text(root, ".//o:securitiesToBeSold/o:amountOfSecuritiesAcquired", ns)
            ),
            "nature_of_acquisition": _text(
                root, ".//o:securitiesToBeSold/o:natureOfAcquisitionTransaction", ns
            ),
            "from_whom_acquired": _text(
                root, ".//o:securitiesToBeSold/o:nameOfPersonfromWhomAcquired", ns
            ),
            "gift_transaction": _boolish(
                _text(root, ".//o:securitiesToBeSold/o:isGiftTransaction", ns)
            ),
            "payment_date": _iso_date(_text(root, ".//o:securitiesToBeSold/o:paymentDate", ns)),
            "nature_of_payment": _text(root, ".//o:securitiesToBeSold/o:natureOfPayment", ns),
        },
        "prior_sales_last_3_months": prior_sales,
        "remarks": _text(root, ".//o:remarks", ns),
        "notice_signature": {
            "notice_date": _iso_date(_text(root, ".//o:noticeSignature/o:noticeDate", ns)),
            "signature": _text(root, ".//o:noticeSignature/o:signature", ns),
        },
        "citations": _citation_block(filing),
        "source": "SEC EDGAR Form 144 XML",
    }


def parse_event(xml_text: str, filing: dict[str, Any]) -> dict[str, Any]:
    form_type = (filing.get("form_type") or "").upper()
    if form_type.startswith("4"):
        return parse_form4(xml_text, filing)
    if form_type.startswith("144"):
        return parse_form144(xml_text, filing)
    raise ValueError(f"Unsupported form type for parsing: {form_type}")

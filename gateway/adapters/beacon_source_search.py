"""Free/read-only Beacon source-search adapters.

Gateway owns public egress. These connectors return normalized search-result
envelopes only; Brain still owns planning, evidence assembly, and ranking.
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote, urljoin

from fastapi import HTTPException
import httpx

from brain.services.internet_scout.safety import validate_url
from brain.services.internet_scout.sanitizer import sanitize_untrusted_text
from jarvis_common.secrets import get_secret

SUPPORTED_SOURCE_SEARCH_DATA_SOURCE_IDS = frozenset(
    {
        "pubmed-eutils",
        "sec-edgar",
        "osv-dev",
        "cisa-kev",
    }
)

_PUBMED_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
_SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions/"
_OSV_API_BASE_URL = "https://api.osv.dev/v1/"
_CISA_KEV_CATALOG_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)
_CISA_KEV_CATALOG_PAGE_URL = (
    "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
)
_CVE_ID_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", flags=re.IGNORECASE)
_GHSA_ID_RE = re.compile(
    r"\bGHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}\b",
    flags=re.IGNORECASE,
)
_SEC_CIK_RE = re.compile(r"\bCIK\s*0*(\d{1,10})\b", flags=re.IGNORECASE)
_SEC_TICKER_RE = re.compile(r"\b(?:ticker|symbol)\s*[:=]?\s*([A-Z.]{1,6})\b")
_SEC_UPPER_TOKEN_RE = re.compile(r"\b[A-Z]{1,5}\b")
_SEC_IGNORED_TICKER_TOKENS = {
    "SEC",
    "EDGAR",
    "XBRL",
    "FORM",
    "API",
    "CIK",
    "THE",
    "AND",
    "FOR",
}
_SEC_COMPANY_ALIASES = {
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "apple": "AAPL",
    "google": "GOOGL",
    "meta": "META",
    "microsoft": "MSFT",
    "nvidia": "NVDA",
    "tesla": "TSLA",
}
_SEC_FORM_MARKERS = {
    "10-k": "10-K",
    "10-q": "10-Q",
    "8-k": "8-K",
}


async def execute_source_search(
    *,
    client: httpx.AsyncClient,
    data_source_id: str,
    query: str,
    count: int,
) -> list[dict[str, object]]:
    if data_source_id == "pubmed-eutils":
        return await _search_pubmed(client=client, query=query, count=count)
    if data_source_id == "sec-edgar":
        return await _search_sec_edgar(client=client, query=query, count=count)
    if data_source_id == "osv-dev":
        return await _search_osv(client=client, query=query, count=count)
    if data_source_id == "cisa-kev":
        return await _search_cisa_kev(client=client, query=query, count=count)
    raise HTTPException(status_code=400, detail="unsupported Beacon data source")


async def _search_pubmed(
    *,
    client: httpx.AsyncClient,
    query: str,
    count: int,
) -> list[dict[str, object]]:
    search_payload = await _gateway_json_response(
        await client.get(
            urljoin(_PUBMED_EUTILS_BASE_URL, "esearch.fcgi"),
            params={
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": count,
                "sort": "relevance",
            },
            headers=_json_user_agent_headers(),
        ),
        source_name="PubMed E-utilities",
    )
    idlist = (
        search_payload.get("esearchresult", {}).get("idlist", [])
        if isinstance(search_payload, dict)
        else []
    )
    pmids = [str(pmid).strip() for pmid in idlist if str(pmid).strip()][:count]
    if not pmids:
        return []

    summary_payload = await _gateway_json_response(
        await client.get(
            urljoin(_PUBMED_EUTILS_BASE_URL, "esummary.fcgi"),
            params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "json",
            },
            headers=_json_user_agent_headers(),
        ),
        source_name="PubMed E-utilities",
    )
    result = (
        summary_payload.get("result", {}) if isinstance(summary_payload, dict) else {}
    )
    if not isinstance(result, dict):
        return []

    results: list[dict[str, object]] = []
    for pmid in pmids:
        entry = result.get(pmid)
        if not isinstance(entry, dict):
            continue
        title = _text_or_none(entry.get("title")) or f"PubMed PMID {pmid}"
        journal = _text_or_none(entry.get("source"))
        pubdate = _text_or_none(entry.get("pubdate"))
        authors = _pubmed_author_names(entry.get("authors"))
        description_parts = [
            part
            for part in (
                f"PMID {pmid}",
                f"journal={journal}" if journal else None,
                f"published={pubdate}" if pubdate else None,
                f"authors={', '.join(authors[:3])}" if authors else None,
            )
            if part
        ]
        result_item = _source_search_result(
            title=title,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            description="; ".join(description_parts) + ".",
        )
        if result_item is not None:
            results.append(result_item)
    return results[:count]


async def _search_sec_edgar(
    *,
    client: httpx.AsyncClient,
    query: str,
    count: int,
) -> list[dict[str, object]]:
    cik = _sec_cik_from_query(query)
    ticker = _sec_ticker_from_query(query)
    company_title: str | None = None
    headers = _sec_edgar_headers()

    if cik is None and ticker is not None:
        tickers_payload = await _gateway_json_response(
            await client.get(
                _SEC_COMPANY_TICKERS_URL,
                headers=headers,
            ),
            source_name="SEC EDGAR",
        )
        cik, company_title = _sec_company_from_tickers_payload(tickers_payload, ticker)

    if cik is None:
        return []

    submissions_payload = await _gateway_json_response(
        await client.get(
            urljoin(_SEC_SUBMISSIONS_BASE_URL, f"CIK{cik:010d}.json"),
            headers=headers,
        ),
        source_name="SEC EDGAR",
    )
    recent = (
        submissions_payload.get("filings", {}).get("recent", {})
        if isinstance(submissions_payload, dict)
        else {}
    )
    if not isinstance(recent, dict):
        return []

    forms = _sec_target_forms(query)
    company_name = (
        _text_or_none(submissions_payload.get("name"))
        if isinstance(submissions_payload, dict)
        else None
    ) or company_title
    rows = _sec_recent_rows(recent)
    results: list[dict[str, object]] = []
    for row in rows:
        form = row.get("form")
        if forms and form not in forms:
            continue
        accession = _text_or_none(row.get("accessionNumber"))
        primary_document = _text_or_none(row.get("primaryDocument"))
        filing_date = _text_or_none(row.get("filingDate"))
        if not accession or not primary_document or not form:
            continue
        accession_path = accession.replace("-", "")
        url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{cik}/{accession_path}/{primary_document}"
        )
        title = f"{company_name or 'SEC issuer'} {form} filing"
        description = "; ".join(
            part
            for part in (
                "SEC EDGAR filing",
                f"company={company_name}" if company_name else None,
                f"cik={cik:010d}",
                f"form={form}",
                f"filed={filing_date}" if filing_date else None,
                f"accession={accession}",
            )
            if part
        )
        result_item = _source_search_result(
            title=title,
            url=url,
            description=description + ".",
        )
        if result_item is not None:
            results.append(result_item)
        if len(results) >= count:
            break
    return results


async def _search_osv(
    *,
    client: httpx.AsyncClient,
    query: str,
    count: int,
) -> list[dict[str, object]]:
    vulnerability_ids = _osv_ids_from_query(query)[:count]
    if not vulnerability_ids:
        return []

    results: list[dict[str, object]] = []
    for vulnerability_id in vulnerability_ids:
        response = await client.get(
            urljoin(_OSV_API_BASE_URL, f"vulns/{quote(vulnerability_id)}"),
            headers=_json_user_agent_headers(),
        )
        if response.status_code == 404:
            continue
        payload = await _gateway_json_response(response, source_name="OSV")
        if not isinstance(payload, dict):
            continue
        osv_id = _text_or_none(payload.get("id")) or vulnerability_id
        summary = _text_or_none(payload.get("summary"))
        details = _text_or_none(payload.get("details"))
        modified = _text_or_none(payload.get("modified"))
        packages = _osv_package_names(payload.get("affected"))
        description_parts = [
            f"OSV vulnerability {osv_id}",
            summary or (details[:240] if details else None),
            f"packages={', '.join(packages[:5])}" if packages else None,
            f"modified={modified}" if modified else None,
        ]
        result_item = _source_search_result(
            title=summary or f"OSV vulnerability {osv_id}",
            url=f"https://osv.dev/vulnerability/{quote(osv_id)}",
            description="; ".join(part for part in description_parts if part) + ".",
        )
        if result_item is not None:
            results.append(result_item)
    return results[:count]


async def _search_cisa_kev(
    *,
    client: httpx.AsyncClient,
    query: str,
    count: int,
) -> list[dict[str, object]]:
    payload = await _gateway_json_response(
        await client.get(
            _CISA_KEV_CATALOG_URL,
            headers=_json_user_agent_headers(),
        ),
        source_name="CISA KEV",
    )
    vulnerabilities = (
        payload.get("vulnerabilities", []) if isinstance(payload, dict) else []
    )
    if not isinstance(vulnerabilities, list):
        return []

    query_terms = _query_terms(query)
    cve_ids = {item.upper() for item in _cve_ids_from_query(query)}
    results: list[dict[str, object]] = []
    for item in vulnerabilities:
        if not isinstance(item, dict):
            continue
        cve_id = _text_or_none(item.get("cveID"))
        if not cve_id:
            continue
        haystack = " ".join(
            _text_or_none(item.get(key)) or ""
            for key in (
                "cveID",
                "vendorProject",
                "product",
                "vulnerabilityName",
                "shortDescription",
                "requiredAction",
            )
        ).lower()
        if cve_ids:
            matched = cve_id.upper() in cve_ids
        else:
            matched = bool(query_terms) and all(
                term in haystack for term in query_terms
            )
        if not matched:
            continue
        vendor = _text_or_none(item.get("vendorProject"))
        product = _text_or_none(item.get("product"))
        name = _text_or_none(item.get("vulnerabilityName"))
        date_added = _text_or_none(item.get("dateAdded"))
        due_date = _text_or_none(item.get("dueDate"))
        known_ransomware = _text_or_none(item.get("knownRansomwareCampaignUse"))
        description = "; ".join(
            part
            for part in (
                f"CISA Known Exploited Vulnerability {cve_id}",
                f"vendor={vendor}" if vendor else None,
                f"product={product}" if product else None,
                f"name={name}" if name else None,
                f"date_added={date_added}" if date_added else None,
                f"due_date={due_date}" if due_date else None,
                f"known_ransomware={known_ransomware}" if known_ransomware else None,
            )
            if part
        )
        url = f"{_CISA_KEV_CATALOG_PAGE_URL}?field_cve={quote(cve_id)}"
        result_item = _source_search_result(
            title=name or f"CISA KEV {cve_id}",
            url=url,
            description=description + ".",
        )
        if result_item is not None:
            results.append(result_item)
        if len(results) >= count:
            break
    return results


async def _gateway_json_response(
    response: httpx.Response,
    *,
    source_name: str,
) -> object:
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"{source_name} API error: HTTP {response.status_code}",
        )
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{source_name} API returned invalid JSON",
        ) from exc


def _json_user_agent_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "jarvis-alpha-beacon/1.0",
    }


def _sec_edgar_headers() -> dict[str, str]:
    user_agent = (
        os.getenv("SEC_EDGAR_USER_AGENT", "").strip()
        or _secret_or_none("SEC_EDGAR_USER_AGENT")
        or "jarvis-alpha-beacon/1.0 security@at-0.com"
    )
    return {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": user_agent,
    }


def _secret_or_none(name: str) -> str | None:
    try:
        value = get_secret(name).strip()
    except KeyError:
        return None
    return value or None


def _source_search_result(
    *,
    title: str | None,
    url: str,
    description: str,
) -> dict[str, object] | None:
    safety = validate_url(url)
    if not safety.allowed or not safety.normalized_url or not safety.host:
        return None
    sanitized = sanitize_untrusted_text(description, max_chars=1000)
    return {
        "title": title,
        "url": safety.normalized_url,
        "host": safety.host,
        "description": sanitized.text,
        "risk_markers": sanitized.risk_markers,
    }


def _pubmed_author_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _text_or_none(item.get("name"))
        if name:
            names.append(name)
    return names


def _sec_cik_from_query(query: str) -> int | None:
    match = _SEC_CIK_RE.search(query)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _sec_ticker_from_query(query: str) -> str | None:
    explicit = _SEC_TICKER_RE.search(query)
    if explicit:
        return explicit.group(1).upper().replace(".", "-")

    normalized = query.lower()
    for company, ticker in _SEC_COMPANY_ALIASES.items():
        if company in normalized:
            return ticker

    for token in _SEC_UPPER_TOKEN_RE.findall(query):
        if token in _SEC_IGNORED_TICKER_TOKENS:
            continue
        return token.replace(".", "-")
    return None


def _sec_company_from_tickers_payload(
    payload: object,
    ticker: str,
) -> tuple[int | None, str | None]:
    normalized_ticker = ticker.upper().replace(".", "-")
    rows: list[object]
    if isinstance(payload, dict):
        rows = list(payload.values())
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_ticker = _text_or_none(row.get("ticker"))
        if row_ticker is None or row_ticker.upper() != normalized_ticker:
            continue
        cik = _text_or_none(row.get("cik_str"))
        if cik is None:
            return None, _text_or_none(row.get("title"))
        try:
            return int(cik), _text_or_none(row.get("title"))
        except ValueError:
            return None, _text_or_none(row.get("title"))
    return None, None


def _sec_target_forms(query: str) -> set[str]:
    normalized = query.lower()
    return {form for marker, form in _SEC_FORM_MARKERS.items() if marker in normalized}


def _sec_recent_rows(recent: dict[str, object]) -> list[dict[str, object]]:
    values = {key: value for key, value in recent.items() if isinstance(value, list)}
    forms = values.get("form", [])
    rows: list[dict[str, object]] = []
    for index in range(len(forms)):
        row: dict[str, object] = {}
        for key, value in values.items():
            if index < len(value):
                row[key] = value[index]
        rows.append(row)
    return rows


def _osv_ids_from_query(query: str) -> list[str]:
    ids = [
        *[match.upper() for match in _CVE_ID_RE.findall(query)],
        *[match.upper() for match in _GHSA_ID_RE.findall(query)],
    ]
    return list(dict.fromkeys(ids))


def _cve_ids_from_query(query: str) -> list[str]:
    return list(dict.fromkeys(match.upper() for match in _CVE_ID_RE.findall(query)))


def _osv_package_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        package = item.get("package")
        if not isinstance(package, dict):
            continue
        name = _text_or_none(package.get("name"))
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def _query_terms(query: str) -> list[str]:
    terms = [
        term
        for term in re.findall(r"[a-z0-9][a-z0-9._-]{2,}", query.lower())
        if term
        not in {
            "the",
            "and",
            "for",
            "with",
            "cisa",
            "kev",
            "catalog",
            "vulnerability",
            "vulnerabilities",
        }
    ]
    return terms[:5]


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

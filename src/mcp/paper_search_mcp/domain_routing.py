"""Domain → source routing for paper search.

Pure module: no env reads, no imports from agents or mcp.server. Callers
read env vars themselves and pass flags as kwargs. This keeps the dependency
direction clean (agents → domain_routing → nothing) and makes the module
trivially unit-testable.
"""
from typing import List

DOMAIN_SOURCES: dict[str, List[str]] = {
    "computer_science": [
        "arxiv", "semantic", "dblp", "openalex", "crossref",
        "citeseerx", "core", "unpaywall", "google_scholar",
    ],
    "biology": [
        "arxiv", "pubmed", "biorxiv", "pmc", "europepmc",
        "semantic", "openalex", "crossref", "doaj", "core", "unpaywall",
    ],
    "medical": [
        "pubmed", "pmc", "europepmc", "medrxiv", "biorxiv",
        "arxiv", "semantic", "openalex", "crossref", "doaj", "unpaywall",
    ],
    "engineering": [
        "arxiv", "semantic", "openalex", "crossref", "core",
        "unpaywall", "citeseerx",
    ],
    "social_science": [
        "ssrn", "semantic", "openalex", "crossref", "core", "google_scholar",
    ],
    "humanities": [
        "crossref", "openalex", "core", "doaj", "google_scholar",
    ],
    "general": [
        "arxiv", "semantic", "openalex", "crossref", "core",
    ],
}

VALID_DOMAINS: set[str] = set(DOMAIN_SOURCES.keys())

# Domains where Chinese literature is likely relevant even if the query
# itself is in English (e.g., "TCM herbal compounds" → medical + CN).
CN_DOMAINS: set[str] = {"medical", "biology", "engineering", "social_science", "humanities"}


def sources_for_domain(
    domain: str,
    *,
    has_chinese: bool,
    wanfang_enabled: bool,
    cnki_enabled: bool,
) -> List[str]:
    """Return the ordered source list for a domain, with CN sources appended if warranted.

    Args:
        domain: One of VALID_DOMAINS. Invalid values fall back to "general".
        has_chinese: True if the user query contains Chinese characters.
        wanfang_enabled: True if WFDATA_APP_KEY/WFDATA_APP_CODE are configured.
        cnki_enabled: True if APAPER_MCP_ENABLED is truthy and Node is available.
    """
    base = DOMAIN_SOURCES.get(domain, DOMAIN_SOURCES["general"])
    out = list(base)

    want_cn = has_chinese or domain in CN_DOMAINS
    if want_cn:
        if wanfang_enabled:
            out.append("wanfang")
        if cnki_enabled:
            out.append("cnki")
    return out

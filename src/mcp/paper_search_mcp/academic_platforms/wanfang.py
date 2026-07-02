"""Wanfang Data (万方数据) searcher.

Native HTTP client for the Wanfang open API. Metadata-only in v1: PDF
download is not supported (Wanfang's open API doesn't return direct PDF
URLs for most records — institutional access required). Papers found here
flow through the existing PDF-download fallback chain (DOI → openaire /
core / europepmc → unpaywall → scihub) when a download is requested.

Auth requires WFDATA_APP_KEY and WFDATA_APP_CODE (registered on the
Wanfang open platform). The searcher is only registered in ALL_SOURCES
when both env vars are present.
"""
import logging
from typing import List, Optional

import requests

from ..paper import Paper
from .base import PaperSource

logger = logging.getLogger(__name__)

WFDATA_BASE_URL = "https://api.wanfangdata.com.cn"

# Default collection: OpenPeriodical (期刊论文). Callers can override.
DEFAULT_COLLECTIONS = ["OpenPeriodical"]


class WanfangSearcher(PaperSource):
    """Searcher for Wanfang Data open API."""

    def __init__(self, app_key: str = "", app_code: str = ""):
        self.app_key = app_key
        self.app_code = app_code

    def _headers(self) -> dict:
        return {
            "X-Ca-AppKey": self.app_key,
            "Authorization": f"APPCODE {self.app_code}",
            "Content-Type": "application/json",
        }

    def search(
        self,
        query: str,
        max_results: int = 10,
        collections: Optional[List[str]] = None,
        **kwargs,
    ) -> List[Paper]:
        """Search Wanfang Data for papers matching the query.

        Args:
            query: Search keywords (Chinese or English).
            max_results: Max number of results to return.
            collections: Wanfang collection names (default: OpenPeriodical).

        Returns:
            List of Paper objects. Empty list on error.
        """
        cols = collections or DEFAULT_COLLECTIONS
        payload = {
            "collections": cols,
            "query": query,
            "rows": max_results,
            "start": 0,
            "sort": {"sort_name": "OfflineScore"},
        }
        try:
            resp = requests.post(
                f"{WFDATA_BASE_URL}/openwanfang/getQuery",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"Wanfang search failed for query='{query}': {exc}")
            return []

        documents = data.get("documents", []) or []
        papers: List[Paper] = []
        for doc in documents:
            paper = self._parse_doc(doc)
            if paper is not None:
                papers.append(paper)
        return papers

    def _parse_doc(self, doc: dict) -> Optional[Paper]:
        doc_id = str(doc.get("docId") or doc.get("id") or "").strip()
        title = (doc.get("title") or "").strip()
        if not doc_id or not title:
            return None

        # authors may be list of {"name": ...} or list of strings or a single string
        raw_authors = doc.get("authors") or []
        authors: List[str] = []
        if isinstance(raw_authors, list):
            for a in raw_authors:
                if isinstance(a, dict):
                    name = (a.get("name") or "").strip()
                else:
                    name = str(a).strip()
                if name:
                    authors.append(name)
        elif isinstance(raw_authors, str):
            authors = [a.strip() for a in raw_authors.split(";") if a.strip()]

        abstract = (doc.get("abstract") or "").strip()
        doi = (doc.get("doi") or "").strip()
        year = doc.get("year")
        # published_date accepts str per Paper._serialize_date; keep as-is.
        published = str(year) if year else ""

        return Paper(
            paper_id=doc_id,
            title=title,
            authors=authors,
            abstract=abstract,
            doi=doi,
            published_date=published,  # type: ignore[arg-type]  # str accepted by _serialize_date
            pdf_url="",  # metadata-only v1
            url=f"https://s.wanfangdata.com.cn/paper/detail?id={doc_id}",
            source="wanfang",
        )

    def download_pdf(self, paper_id: str, save_path: str) -> str:
        raise NotImplementedError(
            "WanfangSearcher is metadata-only in v1. PDF download falls through "
            "to the repository/unpaywall/scihub fallback chain."
        )

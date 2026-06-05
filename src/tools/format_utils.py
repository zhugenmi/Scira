"""
Scira Format Utilities Module

Provides citation formatting and paper formatting utilities.
Supports multiple citation styles (APA, IEEE, MLA, etc.).
"""

import re
import os
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CitationStyle(str, Enum):
    """Citation format styles."""
    APA = "apa"
    IEEE = "ieee"
    MLA = "mla"
    CHICAGO = "chicago"
    NATURE = "nature"


@dataclass
class Citation:
    """Citation data structure."""
    paper_id: str
    authors: List[str]
    title: str
    year: str
    venue: Optional[str]
    journal: Optional[str]
    volume: Optional[str]
    issue: Optional[str]
    pages: Optional[str]
    doi: Optional[str]
    url: Optional[str]
    arxiv_id: Optional[str]


class CitationFormatter:
    """
    Citation formatter for multiple styles.

    Supports: APA, IEEE, MLA, Chicago, Nature
    """

    def __init__(self, style: CitationStyle = CitationStyle.APA):
        """
        Initialize formatter.

        Args:
            style: Citation style to use
        """
        self.style = style

    def format(self, citation: Citation) -> str:
        """Format a single citation."""
        if self.style == CitationStyle.APA:
            return self._format_apa(citation)
        elif self.style == CitationStyle.IEEE:
            return self._format_ieee(citation)
        elif self.style == CitationStyle.MLA:
            return self._format_mla(citation)
        elif self.style == CitationStyle.CHICAGO:
            return self._format_chicago(citation)
        elif self.style == CitationStyle.NATURE:
            return self._format_nature(citation)
        else:
            return self._format_apa(citation)

    def format_list(self, citations: List[Citation]) -> str:
        """Format a list of citations."""
        formatted = [self.format(c) for c in citations]

        if self.style == CitationStyle.IEEE:
            return "\n".join([f"[{i+1}] {f}" for i, f in enumerate(formatted)])
        elif self.style == CitationStyle.APA:
            return "\n\n".join(formatted)
        else:
            return "\n\n".join(formatted)

    def _format_apa(self, c: Citation) -> str:
        """Format in APA style."""
        authors = self._format_authors_apa(c.authors)
        year = c.year or "n.d."
        title = c.title
        venue = c.journal or c.venue or ""

        parts = [f"{authors} ({year}). {title}."]
        if venue:
            if c.volume:
                venue += f", {c.volume}"
                if c.issue:
                    venue += f"({c.issue})"
            if c.pages:
                venue += f", {c.pages}"
            parts.append(venue + ".")

        if c.doi:
            parts.append(f"https://doi.org/{c.doi}")
        elif c.url:
            parts.append(c.url)

        return " ".join(parts)

    def _format_ieee(self, c: Citation) -> str:
        """Format in IEEE style."""
        authors = self._format_authors_ieee(c.authors)
        title = f'"{c.title},"'
        venue = c.journal or c.venue or ""

        parts = [f"{authors}, {title}"]
        if venue:
            if c.volume:
                venue = f"vol. {c.volume}, " + venue
            if c.issue:
                venue += f", no. {c.issue}"
            if c.pages:
                venue += f", pp. {c.pages}"
            parts.append(venue + ",")

        if c.year:
            parts.append(c.year + ".")
        if c.doi:
            parts.append(f"doi: {c.doi}.")

        return " ".join(parts)

    def _format_mla(self, c: Citation) -> str:
        """Format in MLA style."""
        authors = self._format_authors_mla(c.authors)
        title = f'"{c.title}."'
        venue = c.journal or c.venue or ""

        parts = [f"{authors}. {title}"]
        if venue:
            if c.volume:
                venue += f", vol. {c.volume}"
            if c.issue:
                venue += f", no. {c.issue}"
            if c.year:
                venue += f", {c.year}"
            if c.pages:
                venue += f", pp. {c.pages}"
            parts.append(venue + ".")

        return " ".join(parts)

    def _format_chicago(self, c: Citation) -> str:
        """Format in Chicago style."""
        authors = self._format_authors_apa(c.authors)
        title = f'"{c.title}."'
        venue = c.journal or c.venue or ""

        parts = [f"{authors}. {title}"]
        if venue:
            if c.volume:
                venue = f"{c.volume}"
                if c.issue:
                    venue += f", no. {c.issue}"
            parts.append(venue + ".")

        if c.year:
            parts.append(f"({c.year}).")

        if c.doi:
            parts.append(f"https://doi.org/{c.doi}.")

        return " ".join(parts)

    def _format_nature(self, c: Citation) -> str:
        """Format in Nature style."""
        authors = self._format_authors_nature(c.authors)
        title = c.title + "."

        parts = [f"{authors}, {title}"]
        if c.journal:
            parts.append(c.journal)
            if c.volume:
                parts.append(c.volume)
            if c.pages:
                parts.append(c.pages)
            if c.year:
                parts.append(f"({c.year})")
            parts[-1] += "."

        if c.doi:
            parts.append(f"doi: {c.doi}")

        return " ".join(parts)

    def _format_authors_apa(self, authors: List[str]) -> str:
        """Format authors in APA style."""
        if not authors:
            return "Anonymous"
        if len(authors) == 1:
            return self._format_single_author_apa(authors[0])
        if len(authors) == 2:
            return f"{self._format_single_author_apa(authors[0])} & {self._format_single_author_apa(authors[1])}"
        if len(authors) <= 20:
            last = authors.pop()
            return f"{', '.join([self._format_single_author_apa(a) for a in authors])}, & {self._format_single_author_apa(last)}"
        else:
            return f"{', '.join([self._format_single_author_apa(a) for a in authors[:19]])}, ... {self._format_single_author_apa(authors[-1])}"

    def _format_single_author_apa(self, author: str) -> str:
        """Format single author in APA style."""
        parts = author.split()
        if len(parts) >= 2:
            return f"{parts[-1]}, " + " ".join(p[0] + "." for p in parts[:-1])
        return author

    def _format_authors_ieee(self, authors: List[str]) -> str:
        """Format authors in IEEE style."""
        if not authors:
            return "Anonymous"
        formatted = []
        for author in authors:
            parts = author.split()
            if len(parts) >= 2:
                formatted.append(" ".join(p[0] + "." for p in parts[:-1]) + " " + parts[-1])
            else:
                formatted.append(author)
        if len(formatted) == 1:
            return formatted[0]
        if len(formatted) == 2:
            return f"{formatted[0]} and {formatted[1]}"
        return ", ".join(formatted[:-1]) + ", and " + formatted[-1]

    def _format_authors_mla(self, authors: List[str]) -> str:
        """Format authors in MLA style."""
        if not authors:
            return "Anonymous"
        if len(authors) == 1:
            return self._format_single_author_apa(authors[0])
        if len(authors) == 2:
            return f"{self._format_single_author_apa(authors[0])}, and {authors[1]}"
        return f"{self._format_single_author_apa(authors[0])}, et al"

    def _format_authors_nature(self, authors: List[str]) -> str:
        """Format authors in Nature style."""
        if not authors:
            return "Anonymous"
        if len(authors) <= 5:
            return ", ".join([a.split()[-1] for a in authors])
        return f"{authors[0].split()[-1]} et al"


class PaperFormatter:
    """
    Paper formatter for final output.

    Handles markdown/LaTeX formatting and structure.
    """

    def __init__(self):
        pass

    def format_markdown(
        self,
        title: str,
        abstract: str,
        sections: Dict[str, str],
        references: List[Citation],
        style: CitationStyle = CitationStyle.IEEE,
    ) -> str:
        """
        Format paper as Markdown.

        Args:
            title: Paper title
            abstract: Paper abstract
            sections: Dict of section_name -> content
            references: List of citations
            style: Citation style

        Returns:
            Formatted markdown string
        """
        formatter = CitationFormatter(style)

        parts = []

        # Title
        parts.append(f"# {title}\n")

        # Abstract
        parts.append(f"## Abstract\n{abstract}\n")

        # Sections
        for sec_name, sec_content in sections.items():
            parts.append(f"## {sec_name}\n{sec_content}\n")

        # References
        parts.append("## References\n")
        parts.append(formatter.format_list(references))

        return "\n".join(parts)

    def format_latex(
        self,
        title: str,
        authors: List[str],
        abstract: str,
        sections: Dict[str, str],
        references: List[Citation],
    ) -> str:
        """
        Format paper as LaTeX.

        Args:
            title: Paper title
            authors: List of authors
            abstract: Paper abstract
            sections: Dict of section_name -> content
            references: List of citations

        Returns:
            Formatted LaTeX string
        """
        parts = []

        # Preamble
        parts.append(r"\documentclass[12pt,a4paper]{article}")
        parts.append(r"\usepackage[utf8]{inputenc}")
        parts.append(r"\usepackage{amsmath}")
        parts.append(r"\usepackage{graphicx}")
        parts.append(r"\usepackage[margin=1in]{geometry}")
        parts.append(r"\usepackage{natbib}")
        parts.append("\n")

        # Title
        parts.append(r"\begin{document}")
        parts.append(f"\\title{{{title}}}")
        parts.append(f"\\author{{{', '.join(authors)}}}")
        parts.append(r"\maketitle")
        parts.append("\n")

        # Abstract
        parts.append(r"\begin{abstract}")
        parts.append(abstract)
        parts.append(r"\end{abstract}")
        parts.append("\n")

        # Sections
        for sec_name, sec_content in sections.items():
            sec_label = sec_name.lower().replace(" ", "-")
            parts.append(f"\\section{{{sec_name}}}\\label{{{sec_label}}}")
            parts.append(sec_content)
            parts.append("\n")

        # References
        parts.append(r"\bibliographystyle{plain}")
        parts.append(r"\bibliography{references}")

        parts.append(r"\end{document}")

        return "\n".join(parts)

    def to_file(
        self,
        content: str,
        output_path: str,
        format: str = "markdown",
    ):
        """
        Write formatted paper to file.

        Args:
            content: Paper content
            output_path: Output file path
            format: Format type (markdown, latex, txt)
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if format == "markdown" and not output_path.endswith(".md"):
            output_path += ".md"
        elif format == "latex" and not output_path.endswith(".tex"):
            output_path += ".tex"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)


class ReferenceManager:
    """
    Reference manager for collecting and organizing citations.
    """

    def __init__(self):
        self.citations: Dict[str, Citation] = {}

    def add(self, paper_data: Dict[str, Any]) -> Citation:
        """Add a paper to the reference manager."""
        citation = Citation(
            paper_id=paper_data.get("paper_id", ""),
            authors=paper_data.get("authors", []),
            title=paper_data.get("title", ""),
            year=paper_data.get("published_date", "")[:4],
            venue=paper_data.get("journal_ref"),
            journal=paper_data.get("journal_ref"),
            volume=None,
            issue=None,
            pages=None,
            doi=paper_data.get("doi"),
            url=paper_data.get("arxiv_url"),
            arxiv_id=paper_data.get("paper_id"),
        )

        self.citations[citation.paper_id] = citation
        return citation

    def get(self, paper_id: str) -> Optional[Citation]:
        """Get citation by paper ID."""
        return self.citations.get(paper_id)

    def get_all(self) -> List[Citation]:
        """Get all citations."""
        return list(self.citations.values())

    def to_json(self) -> str:
        """Export to JSON."""
        data = [
            {
                "paper_id": c.paper_id,
                "authors": c.authors,
                "title": c.title,
                "year": c.year,
                "venue": c.venue,
                "doi": c.doi,
                "url": c.url,
            }
            for c in self.citations.values()
        ]
        return json.dumps(data, indent=2, ensure_ascii=False)

    def from_json(self, json_str: str):
        """Import from JSON."""
        data = json.loads(json_str)
        for item in data:
            self.add(item)


# Helper functions

def format_citation(
    paper_data: Dict[str, Any],
    style: CitationStyle = CitationStyle.APA,
) -> str:
    """Quick citation formatting helper."""
    citation = Citation(
        paper_id=paper_data.get("paper_id", ""),
        authors=paper_data.get("authors", []),
        title=paper_data.get("title", ""),
        year=paper_data.get("published_date", "")[:4] if paper_data.get("published_date") else "",
        venue=paper_data.get("journal_ref"),
        journal=paper_data.get("journal_ref"),
        volume=None,
        issue=None,
        pages=None,
        doi=paper_data.get("doi"),
        url=paper_data.get("arxiv_url"),
        arxiv_id=paper_data.get("paper_id"),
    )

    formatter = CitationFormatter(style)
    return formatter.format(citation)

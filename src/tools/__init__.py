"""
Scira Tools Module

External tools and API wrappers for the research assistant.

Note: Paper search functionality has been moved to MCP service.
See src/mcp/paper-search-mcp/ for the paper search implementation.
"""

# PDF Parser
from src.tools.pdf_parser import (
    PDFParser,
    ParserBackend,
    ParsedPaper,
    parse_pdf,
    extract_key_info,
)

# Format Utils
from src.tools.format_utils import (
    CitationFormatter,
    CitationStyle,
    Citation,
    PaperFormatter,
    ReferenceManager,
    format_citation,
)

__all__ = [
    # PDF Parser
    "PDFParser",
    "ParserBackend",
    "ParsedPaper",
    "parse_pdf",
    "extract_key_info",
    # Format
    "CitationFormatter",
    "CitationStyle",
    "Citation",
    "PaperFormatter",
    "ReferenceManager",
    "format_citation",
]

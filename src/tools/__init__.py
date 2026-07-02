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

# CAJ Parser
from src.tools.caj_parser import (
    CAJParseError,
    convert_caj_to_pdf,
    is_disguised_pdf,
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

# Text Extractor
from src.tools.text_extractor import (
    PaperTextExtractor,
    TextExtractionError,
)

# Paper Info Extractor
from src.tools.paper_info_extractor import (
    PaperInfoExtractor,
)

__all__ = [
    # PDF Parser
    "PDFParser",
    "ParserBackend",
    "ParsedPaper",
    "parse_pdf",
    "extract_key_info",
    # CAJ Parser
    "CAJParseError",
    "convert_caj_to_pdf",
    "is_disguised_pdf",
    # Format
    "CitationFormatter",
    "CitationStyle",
    "Citation",
    "PaperFormatter",
    "ReferenceManager",
    "format_citation",
    # Text Extractor
    "PaperTextExtractor",
    "TextExtractionError",
    # Paper Info Extractor
    "PaperInfoExtractor",
]

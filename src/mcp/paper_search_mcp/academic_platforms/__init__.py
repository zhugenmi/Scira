from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher
from paper_search_mcp.academic_platforms.semantic import SemanticSearcher

arxiv_searcher = ArxivSearcher()
semantic_searcher = SemanticSearcher()

__all__ = ["arxiv_searcher", "semantic_searcher", "ArxivSearcher", "SemanticSearcher"]

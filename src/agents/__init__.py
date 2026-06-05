"""
Scira Agents Module

Multi-agent system for scientific research assistance.
"""

# Base Agent
from src.agents.base import (
    BaseAgent,
    RetrievalAgent,
    ReaderAgent,
    AnalyzerAgent,
    WriterAgent,
    ReviewerAgent,
    create_agent,
)

# Individual Agent imports (for direct usage)
from src.agents.retrieval import RetrievalAgent as RAgent
from src.agents.reader import ReaderAgent as RAgent2
from src.agents.analyzer import AnalyzerAgent as AAgent
from src.agents.writer import WriterAgent as WAgent
from src.agents.reviewer import ReviewerAgent as RevAgent

__all__ = [
    # Base
    "BaseAgent",
    "create_agent",
    # Specialized
    "RetrievalAgent",
    "ReaderAgent",
    "AnalyzerAgent",
    "WriterAgent",
    "ReviewerAgent",
    # Aliases
    "RAgent",  # Retrieval
    "RAgent2",  # Reader
    "AAgent",  # Analyzer
    "WAgent",  # Writer
    "RevAgent",  # Reviewer
]

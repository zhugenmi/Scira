"""
Scira Agent Base Classes

Base classes for all agents in the multi-agent research system.
Provides model-agnostic interface with hot-swappable LLM support.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Callable
from datetime import datetime

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from config.settings import get_config, get_llm_client, SciraConfig
from src.utils.logger import record_token_usage, logger

class BaseAgent(ABC):
    """
    Base class for all Scira agents.

    Provides:
    - Unified LLM client interface
    - Prompt template management
    - State updates
    - Error handling
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        config: Optional[SciraConfig] = None,
    ):
        """
        Initialize the agent.

        Args:
            name: Agent identifier
            system_prompt: System prompt for the agent
            config: Optional config override
        """
        self.name = name
        self.system_prompt = system_prompt
        self.config = config or get_config()
        self.llm = get_llm_client(self.config)

    def _record_token_usage(self, response: Any) -> None:
        """
        Extract usage_metadata from an LLM response and feed the global TokenTracker.

        LangChain AIMessage exposes `usage_metadata` (a dict with input_tokens /
        output_tokens / total_tokens) for providers that return usage info.
        Without this, token_usage in GraphState stays at zero forever.
        """
        model_name = self.config.model.model_name or "gpt-4o"
        record_token_usage(response, model_name)

    def invoke(
        self,
        prompt: str,
        messages: Optional[List[Any]] = None,
        **kwargs,
    ) -> str:
        """
        Invoke the agent with a prompt.

        Args:
            prompt: User prompt
            messages: Optional additional messages for context
            **kwargs: Additional LLM parameters

        Returns:
            Agent response as string
        """
        messages = messages or []

        chat_messages = [
            SystemMessage(content=self.system_prompt),
            *messages,
            HumanMessage(content=prompt),
        ]

        response = self.llm.invoke(chat_messages, **kwargs)
        self._record_token_usage(response)
        return response.content

    def invoke_stream(
        self,
        prompt: str,
        messages: Optional[List[Any]] = None,
        token_callback: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> str:
        """
        Invoke the agent with streaming, calling token_callback for each chunk.

        Args:
            prompt: User prompt
            messages: Optional additional messages
            token_callback: Called with each text chunk as it arrives
            **kwargs: Additional LLM parameters

        Returns:
            Full concatenated response string
        """
        messages = messages or []
        chat_messages = [
            SystemMessage(content=self.system_prompt),
            *messages,
            HumanMessage(content=prompt),
        ]

        chunks = []
        for chunk in self.llm.stream(chat_messages, **kwargs):
            content = chunk.content if hasattr(chunk, 'content') else str(chunk)
            chunks.append(content)
            if token_callback and content:
                token_callback(content)

        return "".join(chunks)

    def invoke_with_tools(
        self,
        prompt: str,
        tools: List[Any],
        messages: Optional[List[Any]] = None,
    ) -> Any:
        """
        Invoke the agent with tool-calling support.

        Binds tools to the LLM, sends the prompt, returns the raw AIMessage
        (which may contain `content` and/or `tool_calls`). Caller executes
        tool calls and re-invokes with ToolMessage results to continue the loop.

        Degradation: if the provider doesn't support `bind_tools` (raises
        NotImplementedError / AttributeError) or the API rejects the request,
        falls back to plain `invoke()`. Caller detects missing `tool_calls`
        and routes to IntentAgent fallback.

        Args:
            prompt: User prompt
            tools: List of LangChain tool objects (e.g. from @tool decorator)
            messages: Optional additional messages for context

        Returns:
            AIMessage with `content` (str) and `tool_calls` (list or None)
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = messages or []
        chat_messages = [
            SystemMessage(content=self.system_prompt),
            *messages,
            HumanMessage(content=prompt),
        ]

        try:
            bound = self.llm.bind_tools(tools)
        except (NotImplementedError, AttributeError, TypeError) as e:
            logger.warning(f"bind_tools unsupported, degrading to plain invoke: {e}")
            response = self.llm.invoke(chat_messages)
            self._record_token_usage(response)
            return response

        try:
            response = bound.invoke(chat_messages)
            self._record_token_usage(response)
            return response
        except Exception as e:
            logger.warning(f"tool-calling invoke failed, degrading to plain invoke: {e}")
            response = self.llm.invoke(chat_messages)
            self._record_token_usage(response)
            return response

    def stream_final_response(
        self,
        messages: List[Any],
        tools: Optional[List[Any]] = None,
        token_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Stream the LLM's final text response after the tool-calling loop completes.

        Caller builds the full message history (system + user + AIMessage with
        tool_calls + ToolMessages + ...) and passes it here. We stream the final
        text response chunk-by-chunk via token_callback.

        Args:
            messages: Full conversation history including ToolMessages
            tools: Optional tools to bind (in case LLM wants to call again)
            token_callback: Called with each text chunk as it arrives

        Returns:
            Full concatenated response string
        """
        try:
            llm = self.llm.bind_tools(tools) if tools else self.llm
        except (NotImplementedError, AttributeError, TypeError) as e:
            logger.warning(f"bind_tools unsupported in stream_final_response: {e}")
            llm = self.llm

        chunks: List[str] = []
        try:
            for chunk in llm.stream(messages):
                content = getattr(chunk, "content", None) or ""
                if content:
                    chunks.append(content)
                    if token_callback:
                        token_callback(content)
        except Exception as e:
            logger.warning(f"stream_final_response failed, falling back to invoke: {e}")
            response = self.llm.invoke(messages)
            self._record_token_usage(response)
            content = getattr(response, "content", "") or ""
            chunks.append(content)
            if token_callback:
                token_callback(content)

        return "".join(chunks)

    def invoke_with_json(
        self,
        prompt: str,
        messages: Optional[List[Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Invoke the agent and parse response as JSON.

        Args:
            prompt: User prompt
            messages: Optional additional messages
            **kwargs: Additional LLM parameters

        Returns:
            Parsed JSON response

        Raises:
            ValueError: If response is not valid JSON
        """
        response = self.invoke(prompt, messages, **kwargs)

        # Try to parse as JSON
        try:
            # Handle markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            return json.loads(response.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}\nResponse: {response}")

    def invoke_structured(
        self,
        prompt: str,
        output_schema: Any,
        messages: Optional[List[Any]] = None,
    ) -> Any:
        """
        Invoke the agent with structured output.

        Args:
            prompt: User prompt
            output_schema: Pydantic model or TypedDict for structured output
            messages: Optional additional messages

        Returns:
            Structured output matching the schema
        """
        from langchain_core.output_parsers import JsonOutputParser

        messages = messages or []

        parser = JsonOutputParser(pydantic_object=output_schema)

        chat_messages = [
            SystemMessage(content=self.system_prompt),
            *messages,
            HumanMessage(content=prompt + "\n\n" + parser.get_format_instructions()),
        ]

        response = self.llm.invoke(chat_messages)
        self._record_token_usage(response)
        return parser.parse(response.content)


class RetrievalAgent(BaseAgent):
    """Agent for literature retrieval and search strategy."""

    def __init__(self, config: Optional[SciraConfig] = None):
        super().__init__(
            name="retrieval",
            system_prompt="""You are a literature retrieval expert. Your role is to:
1. Analyze the user's research topic
2. Generate optimal search keywords and boolean logic
3. Suggest filters (date range, categories, etc.)
4. Evaluate retrieved papers for relevance

Always prioritize recent papers (last 2-3 years) unless historical context is needed.""",
            config=config,
        )

    def generate_search_strategy(self, topic: str) -> Dict[str, Any]:
        """
        Generate search strategy for a given topic.

        Args:
            topic: Research topic

        Returns:
            Search strategy with keywords, filters, etc.
        """
        prompt = f"""Analyze this research topic and generate a comprehensive search strategy:

Topic: {topic}

Provide a JSON response with:
{{
    "search_keywords": ["keyword1", "keyword2", ...],
    "boolean_query": "search query with AND/OR operators",
    "suggested_categories": ["cs.AI", "cs.LG", ...],
    "date_range": "YYYY-MM-DD to YYYY-MM-DD",
    "max_results": 20,
    "rationale": "brief explanation of search strategy"
}}
"""
        return self.invoke_with_json(prompt)


class ReaderAgent(BaseAgent):
    """Agent for reading and extracting information from papers."""

    def __init__(self, config: Optional[SciraConfig] = None):
        super().__init__(
            name="reader",
            system_prompt="""You are a research paper reading expert. Your role is to:
1. Extract key information from paper abstracts and content
2. Identify: novelty points, methodology, experimental results, conclusions
3. Summarize papers in a structured format
4. Assess paper relevance to the research topic

Be precise and focus on actionable insights.""",
            config=config,
        )

    def extract_paper_info(self, paper_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract structured information from a paper.

        Args:
            paper_data: Raw paper data from arXiv

        Returns:
            Structured paper information
        """
        prompt = f"""Extract key information from this paper:

Title: {paper_data.get('title', 'N/A')}
Authors: {paper_data.get('authors', 'N/A')}
Abstract: {paper_data.get('abstract', 'N/A')}

Provide a JSON response with:
{{
    "paper_id": "{paper_data.get('id', '')}",
    "title": "...",
    "authors": [...],
    "abstract_summary": "2-3 sentence summary",
    "novelty_points": ["point1", "point2"],
    "methodology": "brief methodology description",
    "key_results": "main experimental results",
    "limitations": ["limitation1", "limitation2"],
    "relevance_score": 1-10,
    "relevance_rationale": "why this paper is/isn't relevant"
}}
"""
        return self.invoke_with_json(prompt)


class AnalyzerAgent(BaseAgent):
    """Agent for analysis and synthesis of literature."""

    def __init__(self, config: Optional[SciraConfig] = None):
        super().__init__(
            name="analyzer",
            system_prompt="""You are a research analyst expert. Your role is to:
1. Cluster papers by theme/topic
2. Compare different approaches and methods
3. Identify research trends and gaps
4. Synthesize global knowledge from multiple papers

Focus on creating a coherent knowledge map that can guide writing.""",
            config=config,
        )

    def analyze_literature(
        self,
        papers: List[Dict[str, Any]],
        topic: str,
    ) -> Dict[str, Any]:
        """
        Analyze a collection of papers.

        Args:
            papers: List of parsed paper data
            topic: Research topic

        Returns:
            Analysis results with clusters and knowledge synthesis
        """
        papers_json = json.dumps(papers, indent=2, ensure_ascii=False)

        prompt = f"""Analyze these papers for research topic: {topic}

Papers (JSON):
{papers_json}

Provide a JSON response with:
{{
    "literature_clusters": [
        {{
            "cluster_name": "cluster theme",
            "papers": ["paper_id1", "paper_id2"],
            "common_approach": "shared methodology",
            "key_differences": "how approaches differ"
        }}
    ],
    "global_knowledge": {{
        "research_background": "comprehensive background",
        "mainstream_methods": ["method1", "method2"],
        "performance_comparison": "comparison of methods",
        "research_gaps": ["gap1", "gap2"],
        "future_directions": ["direction1", "direction2"]
    }}
}}
"""
        return self.invoke_with_json(prompt)


class WriterAgent(BaseAgent):
    """Agent for paper writing and content generation."""

    def __init__(self, config: Optional[SciraConfig] = None):
        super().__init__(
            name="writer",
            system_prompt="""You are an academic writing expert. Your role is to:
1. Generate structured outlines based on analysis
2. Write coherent, well-structured chapters
3. Maintain academic tone and proper citations
4. Ensure logical flow between sections

Always write in academic style with proper structure.""",
            config=config,
        )

    def generate_outline(
        self,
        analysis: Dict[str, Any],
        topic: str,
    ) -> Dict[str, Any]:
        """
        Generate paper outline from analysis.

        Args:
            analysis: Global knowledge from analyzer
            topic: Research topic

        Returns:
            Paper outline structure
        """
        analysis_json = json.dumps(analysis, indent=2, ensure_ascii=False)

        prompt = f"""Generate a detailed paper outline for topic: {topic}

Analysis results:
{analysis_json}

Provide a JSON response with:
{{
    "title": "paper title",
    "abstract_requirements": "what the abstract should cover",
    "sections": [
        {{
            "name": "section name",
            "subsections": ["subsection1", "subsection2"],
            "key_points": ["point1", "point2"],
            "expected_length": "approximate words"
        }}
    ],
    "estimated_total_words": 5000,
    "writing_style": "academic tone notes"
}}
"""
        return self.invoke_with_json(prompt)

    def write_chapter(
        self,
        section: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """
        Write a single chapter/section.

        Args:
            section: Section specification
            context: Context information (previous sections, papers, etc.)

        Returns:
            Written chapter content
        """
        section_json = json.dumps(section, indent=2, ensure_ascii=False)
        context_json = json.dumps(context, indent=2, ensure_ascii=False)

        prompt = f"""Write this section based on the outline and context:

Section specification:
{section_json}

Context (previous sections, relevant papers, analysis):
{context_json}

Write in academic style with proper structure and citations.
Output ONLY the content, no additional commentary."""
        return self.invoke(prompt)


class ReviewerAgent(BaseAgent):
    """Agent for paper review and revision."""

    def __init__(self, config: Optional[SciraConfig] = None):
        super().__init__(
            name="reviewer",
            system_prompt="""You are an academic reviewer expert. Your role is to:
1. Check logical consistency and coherence
2. Identify language and clarity issues
3. Verify citation correctness
4. Suggest improvements for structure and flow

Provide constructive, specific feedback.""",
            config=config,
        )

    def review_paper(
        self,
        paper: str,
        outline: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Review a complete paper.

        Args:
            paper: Paper content
            outline: Original outline for reference

        Returns:
            Review feedback
        """
        prompt = f"""Review this paper:

{paper}

Outline for reference:
{json.dumps(outline, indent=2)}

Provide a JSON response with:
{{
    "logic_issues": [
        {{"location": "where", "issue": "description", "severity": "high/medium/low"}}
    ],
    "language_issues": [
        {{"location": "where", "issue": "description", "suggestion": "how to fix"}}
    ],
    "structure_issues": [
        {{"location": "where", "issue": "description"}}
    ],
    "citation_issues": [
        {{"citation": "ref", "issue": "issue description"}}
    ],
    "overall_assessment": "summary",
    "revision_priority": "high/medium/low"
}}
"""
        return self.invoke_with_json(prompt)

    def generate_abstract(
        self,
        paper_content: str,
        topic: str,
    ) -> str:
        """
        Generate abstract from paper content (首尾章节后置生成).

        Args:
            paper_content: Full paper content
            topic: Research topic

        Returns:
            Generated abstract
        """
        prompt = f"""Generate an academic abstract for a paper on: {topic}

Paper content:
{paper_content}

Generate a concise abstract (200-300 words) that:
1. States the research problem
2. Summarizes the approach
3. Highlights key results
4. States conclusions

Output ONLY the abstract, no additional text."""
        return self.invoke(prompt)

    def generate_introduction(
        self,
        paper_content: str,
        global_knowledge: Dict[str, Any],
    ) -> str:
        """
        Generate introduction from paper content and analysis.

        Args:
            paper_content: Full paper content
            global_knowledge: Analysis results

        Returns:
            Generated introduction
        """
        prompt = f"""Generate an academic introduction based on:

Paper content:
{paper_content}

Global knowledge/analysis:
{json.dumps(global_knowledge, indent=2)}

Generate an introduction that:
1. Provides research background
2. States the problem and motivation
3. Summarizes related work
4. States contributions

Output ONLY the introduction."""
        return self.invoke(prompt)

    def generate_conclusion(
        self,
        paper_content: str,
        topic: str,
    ) -> str:
        """
        Generate conclusion from paper content.

        Args:
            paper_content: Full paper content
            topic: Research topic

        Returns:
            Generated conclusion
        """
        prompt = f"""Generate an academic conclusion for a paper on: {topic}

Paper content:
{paper_content}

Generate a conclusion that:
1. Summarizes key findings
2. States contributions
3. Acknowledges limitations
4. Suggests future work

Output ONLY the conclusion."""
        return self.invoke(prompt)


def create_agent(agent_type: str, config: Optional[SciraConfig] = None) -> BaseAgent:
    """
    Factory function to create agents by type.

    Args:
        agent_type: Type of agent (retrieval, reader, analyzer, writer, reviewer)
        config: Optional config

    Returns:
        Agent instance

    Raises:
        ValueError: If agent_type is unknown
    """
    agents = {
        "retrieval": RetrievalAgent,
        "reader": ReaderAgent,
        "analyzer": AnalyzerAgent,
        "writer": WriterAgent,
        "reviewer": ReviewerAgent,
    }

    if agent_type not in agents:
        raise ValueError(f"Unknown agent type: {agent_type}. Available: {list(agents.keys())}")

    return agents[agent_type](config)

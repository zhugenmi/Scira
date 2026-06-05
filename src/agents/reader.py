"""
Scira Reader Agent

Implements parallel paper reading and information extraction:
- Batch PDF download
- Parallel parsing using LangGraph Send API
- Structured information extraction
"""

import os
import json
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial

from langgraph.types import Send
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_config, SciraConfig
from src.tools.pdf_parser import PDFParser, ParserBackend, ParsedPaper
from src.agents.prompts import READING_SYSTEM, READING_EXTRACT_PROMPT


@dataclass
class ReadingTask:
    """Single paper reading task."""
    paper_id: str
    title: str
    authors: List[str]
    abstract: str
    pdf_url: str
    pdf_path: Optional[str] = None
    parsed_content: Optional[Dict[str, Any]] = None
    status: str = "pending"  # pending, downloading, parsing, completed, failed
    error: Optional[str] = None


@dataclass
class ReadingResult:
    """Complete reading workflow result."""
    tasks: List[ReadingTask]
    total_papers: int
    completed: int
    failed: int
    literature_data: List[Dict[str, Any]]  # For GraphState
    reading_summary: Dict[str, Any]


class ReaderAgent:
    """
    Reader Agent for paper reading and extraction.

    Responsibilities:
    1. Download PDFs for selected papers
    2. Parse PDF content (with parallel processing)
    3. Extract structured information
    4. Generate reading summary
    """

    def __init__(
        self,
        config: Optional[SciraConfig] = None,
        backend: ParserBackend = ParserBackend.PYMUPDF,
        max_workers: int = 4,
    ):
        """
        Initialize Reader Agent.

        Args:
            config: Scira config
            backend: PDF parsing backend
            max_workers: Max parallel workers
        """
        self.config = config or get_config()
        self.backend = backend
        self.max_workers = max_workers
        self.pdf_parser = PDFParser(backend=backend)
        # 不再使用本地arxiv_client，通过MCP API下载

    def create_tasks(self, papers: List[Dict[str, Any]]) -> List[ReadingTask]:
        """
        Create reading tasks from paper list.

        Args:
            papers: List of paper dicts from search results

        Returns:
            List of ReadingTask objects
        """
        tasks = []
        for paper in papers:
            task = ReadingTask(
                paper_id=paper.get("paper_id"),
                title=paper.get("title"),
                authors=paper.get("authors", []),
                abstract=paper.get("abstract", ""),
                pdf_url=paper.get("pdf_url", ""),
            )
            tasks.append(task)
        return tasks

    def download_paper(self, task: ReadingTask) -> ReadingTask:
        """
        Download single paper PDF via MCP HTTP API.

        Args:
            task: Reading task

        Returns:
            Updated task with pdf_path
        """
        import requests
        from src.utils.logger import logger

        mcp_api_base = os.getenv("MCP_API_BASE", "http://localhost:8001/api/paper-search")
        download_dir = os.getenv("PAPER_DOWNLOAD_DIR", "./data/downloads")
        os.makedirs(download_dir, exist_ok=True)

        # 从 paper_id 提取实际的 ID
        paper_id = task.paper_id

        # DOI 格式的论文无法直接下载PDF，尝试使用 read API
        if paper_id.startswith("10."):
            try:
                response = requests.post(
                    f"{mcp_api_base}/read",
                    json={"source": "arxiv", "paper_id": paper_id},
                    timeout=30
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("content"):
                        task.parsed_content = {
                            "paper_id": task.paper_id,
                            "title": task.title,
                            "authors": task.authors,
                            "abstract": task.abstract,
                            "extracted_content": result.get("content", "")[:5000],
                            "word_count": len(result.get("content", "")),
                        }
                        task.status = "completed"
                        logger.info(f"Read paper content via API: {paper_id}")
                        return task
            except Exception as e:
                logger.debug(f"Read API failed for DOI paper: {e}")

            task.status = "skipped"
            task.error = "DOI format - no PDF available"
            return task

        try:
            # 调用MCP API下载论文
            response = requests.post(
                f"{mcp_api_base}/download",
                json={
                    "source": "arxiv",
                    "paper_id": paper_id,
                    "save_path": download_dir,
                    "use_scihub": True,
                },
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    task.pdf_path = result.get("save_path")
                    task.status = "downloaded"
                    logger.info(f"Downloaded paper: {paper_id}")
                else:
                    task.status = "failed"
                    task.error = result.get("detail", "Download failed")
            else:
                # HTTP 错误，尝试 read API
                try:
                    read_response = requests.post(
                        f"{mcp_api_base}/read",
                        json={"source": "arxiv", "paper_id": paper_id},
                        timeout=30
                    )
                    if read_response.status_code == 200:
                        read_result = read_response.json()
                        if read_result.get("content"):
                            task.parsed_content = {
                                "paper_id": task.paper_id,
                                "title": task.title,
                                "authors": task.authors,
                                "abstract": task.abstract,
                                "extracted_content": read_result.get("content", "")[:5000],
                                "word_count": len(read_result.get("content", "")),
                            }
                            task.status = "completed"
                            logger.info(f"Read paper via API fallback: {paper_id}")
                            return task
                except:
                    pass

                task.status = "failed"
                task.error = f"HTTP {response.status_code}"

        except requests.exceptions.RequestException as e:
            task.status = "failed"
            task.error = f"Download failed: {e}"

        return task

    def parse_paper(self, task: ReadingTask) -> ReadingTask:
        """
        Parse single paper PDF.

        Args:
            task: Reading task with pdf_path

        Returns:
            Updated task with parsed content
        """
        if not task.pdf_path or not os.path.exists(task.pdf_path):
            task.status = "failed"
            task.error = "PDF not found"
            return task

        try:
            parsed = self.pdf_parser.parse(task.pdf_path, task.paper_id)

            # Extract key information
            task.parsed_content = {
                "paper_id": task.paper_id,
                "title": task.title,
                "authors": task.authors,
                "abstract": task.abstract,
                "extracted_abstract": parsed.abstract,
                "sections": parsed.sections,
                "references": parsed.references[:20],  # Limit references
                "word_count": parsed.word_count,
                "section_names": list(parsed.sections.keys()),
                "reference_count": len(parsed.references),
            }

            task.status = "completed"

        except Exception as e:
            task.status = "failed"
            task.error = f"Parse failed: {e}"

        return task

    def process_task(self, task: ReadingTask) -> ReadingTask:
        """
        Complete processing: download + parse.

        Args:
            task: Reading task

        Returns:
            Fully processed task
        """
        # Download
        task = self.download_paper(task)
        if task.status == "failed":
            return task

        # Parse
        task = self.parse_paper(task)

        # Extract structured information using LLM
        if task.status == "completed" and task.parsed_content:
            task = self.extract_structured_info(task)

        return task

    def extract_structured_info(self, task: ReadingTask) -> ReadingTask:
        """
        Extract structured information from paper using LLM.

        Args:
            task: Reading task with parsed content

        Returns:
            Updated task with extracted structured info
        """
        try:
            from config.settings import get_llm_client

            # Build paper info for the prompt
            content = task.parsed_content
            paper_info = f"""
Title: {task.title}
Authors: {', '.join(task.authors)}
Abstract: {task.abstract}
PDF Path: {task.pdf_path}
Extracted Sections: {content.get('section_names', [])}
Word Count: {content.get('word_count', 0)}
"""
            # Use the template prompt
            prompt = READING_EXTRACT_PROMPT.format(paper_info=paper_info)

            llm = get_llm_client(self.config)
            messages = [
                SystemMessage(content=READING_SYSTEM),
                HumanMessage(content=prompt)
            ]

            response = llm.invoke(messages)

            # Try to parse the JSON response
            import re
            import json as json_module

            match = re.search(r'\{[\s\S]*\}', response.content)
            if match:
                try:
                    extracted = json_module.loads(match.group())
                    # Add extracted info to parsed content
                    task.parsed_content.update({
                        "core_problem": extracted.get("core_problem"),
                        "key_methodology": extracted.get("key_methodology"),
                        "datasets_used": extracted.get("datasets_used"),
                        "evaluation_metrics": extracted.get("evaluation_metrics"),
                        "main_results": extracted.get("main_results"),
                        "limitations": extracted.get("limitations"),
                        "contributions": extracted.get("contributions"),
                    })
                except json_module.JSONDecodeError:
                    pass  # Keep original content if parsing fails

        except Exception as e:
            logger.warning(f"Failed to extract structured info: {e}")

        return task

    def process_batch(
        self,
        tasks: List[ReadingTask],
        max_workers: Optional[int] = None,
    ) -> List[ReadingTask]:
        """
        Process tasks in parallel.

        Args:
            tasks: List of reading tasks
            max_workers: Override max workers

        Returns:
            Processed tasks
        """
        workers = max_workers or self.max_workers
        processed = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self.process_task, task): task for task in tasks}

            for future in as_completed(futures):
                try:
                    result = future.result()
                    processed.append(result)
                except Exception as e:
                    task = futures[future]
                    task.status = "failed"
                    task.error = str(e)
                    processed.append(task)

        return processed

    def generate_summary(self, tasks: List[ReadingTask]) -> Dict[str, Any]:
        """
        Generate reading summary.

        Args:
            tasks: Processed tasks

        Returns:
            Summary statistics
        """
        completed = [t for t in tasks if t.status == "completed"]
        failed = [t for t in tasks if t.status == "failed"]

        total_words = sum(
            t.parsed_content.get("word_count", 0)
            for t in completed
            if t.parsed_content
        )

        # Collect all sections
        all_sections = set()
        for t in completed:
            if t.parsed_content and "section_names" in t.parsed_content:
                all_sections.update(t.parsed_content["section_names"])

        # Collect all references
        all_references = []
        for t in completed:
            if t.parsed_content and "references" in t.parsed_content:
                all_references.extend(t.parsed_content["references"])

        return {
            "total_papers": len(tasks),
            "completed": len(completed),
            "failed": len(failed),
            "total_words": total_words,
            "unique_sections": list(all_sections),
            "total_references": len(all_references),
            "failed_papers": [
                {"paper_id": t.paper_id, "error": t.error}
                for t in failed
            ],
        }

    def to_graphstate_format(self, tasks: List[ReadingTask]) -> List[Dict[str, Any]]:
        """
        Convert to GraphState literature_data format.

        Args:
            tasks: Processed tasks

        Returns:
            List of literature_data entries
        """
        literature_data = []

        for task in tasks:
            if task.status == "completed" and task.parsed_content:
                entry = {
                    "paper_id": task.paper_id,
                    "title": task.title,
                    "authors": task.authors,
                    "abstract": task.abstract,
                    "extracted_content": task.parsed_content,
                    "reading_status": "completed",
                }
                literature_data.append(entry)

        return literature_data

    def run(
        self,
        papers: List[Dict[str, Any]],
        max_workers: Optional[int] = None,
    ) -> ReadingResult:
        """
        Run complete reading workflow.

        Args:
            papers: Papers to read
            max_workers: Parallel workers

        Returns:
            ReadingResult
        """
        # Create tasks
        tasks = self.create_tasks(papers)

        # Process in parallel
        processed_tasks = self.process_batch(tasks, max_workers)

        # Generate summary
        summary = self.generate_summary(processed_tasks)

        # Convert to GraphState format
        literature_data = self.to_graphstate_format(processed_tasks)

        return ReadingResult(
            tasks=processed_tasks,
            total_papers=len(papers),
            completed=sum(1 for t in processed_tasks if t.status == "completed"),
            failed=sum(1 for t in processed_tasks if t.status == "failed"),
            literature_data=literature_data,
            reading_summary=summary,
        )


# LangGraph Send API functions for parallel processing
def create_reading_tasks(papers_data: List[Dict]) -> List[Dict]:
    """
    Create reading tasks for LangGraph Map-Reduce.

    Used with Send API to parallelize paper reading.

    Args:
        papers_data: List of paper dicts from search results

    Returns:
        List of task dicts for Send API
    """
    return [
        {
            "paper_id": p.get("paper_id"),
            "title": p.get("title"),
            "authors": p.get("authors", []),
            "abstract": p.get("abstract", ""),
            "pdf_url": p.get("pdf_url"),
        }
        for p in papers_data
    ]


def reading_node(task: Dict) -> Dict:
    """
    Single paper reading node for LangGraph.

    This function is designed to be called via Send API
    for parallel processing. Uses MCP HTTP API for paper download.

    Args:
        task: Task dict with paper info

    Returns:
        Parsed paper content
    """
    import requests
    from src.tools.pdf_parser import PDFParser, ParserBackend

    paper_id = task.get("paper_id")
    mcp_api_base = os.getenv("MCP_API_BASE", "http://localhost:8001/api/paper-search")
    download_dir = os.getenv("PAPER_DOWNLOAD_DIR", "./downloads")

    # 确保下载目录存在
    os.makedirs(download_dir, exist_ok=True)

    try:
        # 通过 MCP API 下载论文
        response = requests.post(
            f"{mcp_api_base}/download",
            json={
                "source": "arxiv",
                "paper_id": paper_id,
                "save_path": download_dir,
                "use_scihub": True,
            },
            timeout=120
        )

        if response.status_code != 200:
            return {"paper_id": paper_id, "status": "failed", "error": f"HTTP {response.status_code}"}

        result = response.json()
        if not result.get("success"):
            return {"paper_id": paper_id, "status": "failed", "error": result.get("detail", "Download failed")}

        pdf_path = result.get("save_path")
        if not pdf_path or not os.path.exists(pdf_path):
            return {"paper_id": paper_id, "status": "failed", "error": "PDF not found after download"}

        # Parse
        parser = PDFParser(backend=ParserBackend.PYMUPDF)
        parsed = parser.parse(pdf_path, paper_id)

        return {
            "paper_id": paper_id,
            "status": "completed",
            "title": task.get("title"),
            "authors": task.get("authors", []),
            "abstract": task.get("abstract", ""),
            "extracted_content": parser.to_dict(parsed),
        }

    except Exception as e:
        return {
            "paper_id": paper_id,
            "status": "failed",
            "error": str(e),
        }


def aggregate_reading_results(results: List[Dict]) -> Dict:
    """
    Aggregate results from parallel reading nodes.

    Args:
        results: List of reading results

    Returns:
        Aggregated literature_data
    """
    literature_data = []

    for result in results:
        if result.get("status") == "completed":
            entry = {
                "paper_id": result.get("paper_id"),
                "title": result.get("title"),
                "authors": result.get("authors", []),
                "abstract": result.get("abstract", ""),
                "extracted_content": result.get("extracted_content"),
                "reading_status": "completed",
            }
            literature_data.append(entry)

    return {"literature_data": literature_data}


# Convenience function
def read_papers(
    papers: List[Dict[str, Any]],
    max_workers: int = 4,
) -> ReadingResult:
    """
    Quick paper reading function.

    Args:
        papers: Papers to read
        max_workers: Parallel workers

    Returns:
        ReadingResult
    """
    agent = ReaderAgent(max_workers=max_workers)
    return agent.run(papers)

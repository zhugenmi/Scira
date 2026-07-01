"""
Scira Reader Agent

Implements parallel paper reading and information extraction:
- Batch PDF download
- Parallel parsing using LangGraph Send API
- Structured information extraction
"""

import os
import re
import json
import shutil
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


def sanitize_paper_id_for_filename(paper_id: str) -> str:
    """
    把 paper_id 规范化为安全的文件名片段。

    DOI 形如 ``10.64898/2026.05.18.725649`` 含 ``/``，直接拼路径会变成嵌套目录
    ``pdfs/10.64898/2026.05.18.725649.pdf``。这里统一把路径分隔符等不安全字符
    替换为 ``_``，保证 PDF 都落在扁平的 ``pdfs/`` 目录下。

    Args:
        paper_id: 原始论文 ID（可能是 arxiv id、DOI 等）

    Returns:
        可直接用于文件名的安全字符串
    """
    if not paper_id:
        return "unknown"
    # 替换路径分隔符及其他对文件系统不友好的字符
    safe = re.sub(r"[\\/:*?\"<>|]", "_", str(paper_id).strip())
    return safe or "unknown"


def _resolve_downloaded_pdf(
    expected_path: str,
    returned_path: str,
    target_dir: str,
    paper_id: str,
) -> Optional[str]:
    """
    把下载到的 PDF 统一归位到 ``target_dir/<safe_paper_id>.pdf``。

    下载器（Sci-Hub / Unpaywall / OA 仓储）通常用哈希或来源 URL 命名文件，
    实际落盘名既不是 ``<paper_id>.pdf`` 也不一定与 ``returned_path`` 一致。
    本函数按以下顺序定位并归位：

    1. 期望路径已存在 → 直接用；
    2. returned_path 存在 → 移动到期望路径；
    3. 在 target_dir 下扫描 *.pdf，取最近写入的一个移动到期望路径
       （覆盖下载器未回传 save_path、或用任意哈希命名的场景）；
    4. 都找不到 → 返回 None。

    Args:
        expected_path: 规范化后的目标路径 ``target_dir/<safe_paper_id>.pdf``
        returned_path: /download 响应里回传的 save_path（可能为空或不准）
        target_dir: 下载目录
        paper_id: 原始论文 ID，仅用于日志

    Returns:
        归位后的绝对路径，或 None
    """
    from src.utils.logger import logger

    # 1. 期望路径已存在
    if expected_path and os.path.exists(expected_path):
        return expected_path

    # 2. returned_path 存在 → 归位
    if returned_path and os.path.exists(returned_path) and returned_path != expected_path:
        try:
            os.makedirs(target_dir, exist_ok=True)
            # 若目标已存在（同名旧文件），先删除再移动，避免 shutil.move 进子目录
            if os.path.exists(expected_path):
                os.remove(expected_path)
            shutil.move(returned_path, expected_path)
            logger.info(f"Moved PDF to canonical location: {expected_path}")
            return expected_path
        except Exception as e:
            logger.warning(f"Failed to move {returned_path} -> {expected_path}: {e}")
            # 移动失败则直接用原路径（前提是它确实存在）
            return returned_path

    # 3. 扫描 target_dir 下的 PDF，取最近修改的一个归位
    try:
        pdf_files = [
            os.path.join(target_dir, f)
            for f in os.listdir(target_dir)
            if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(target_dir, f))
        ]
    except Exception:
        pdf_files = []

    if pdf_files:
        # 取最近写入的 PDF（下载刚完成，mtime 最新）
        latest = max(pdf_files, key=lambda p: os.path.getmtime(p))
        try:
            os.makedirs(target_dir, exist_ok=True)
            if os.path.exists(expected_path) and os.path.abspath(latest) != os.path.abspath(expected_path):
                os.remove(expected_path)
            if os.path.abspath(latest) != os.path.abspath(expected_path):
                shutil.move(latest, expected_path)
            logger.info(f"Renamed downloaded PDF {os.path.basename(latest)} -> {expected_path} (paper_id={paper_id})")
            return expected_path
        except Exception as e:
            logger.warning(f"Failed to rename {latest} -> {expected_path}: {e}")
            return latest

    # 4. 找不到任何 PDF
    logger.warning(f"PDF not found for {paper_id}: expected={expected_path}, returned={returned_path}, dir={target_dir}")
    return None


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

    def download_paper(self, task: ReadingTask, download_dir: Optional[str] = None) -> ReadingTask:
        """
        Download single paper PDF via MCP HTTP API.

        Args:
            task: Reading task
            download_dir: Custom download directory (e.g., papers/reinforcement_learning/pdfs)

        Returns:
            Updated task with pdf_path
        """
        import requests
        from src.utils.logger import logger

        mcp_api_base = os.getenv("MCP_API_BASE", "http://localhost:8001/api/paper-search")
        # download_dir 语义：类别基目录（如 data/papers/<category>）。
        # 每篇论文落到独立子目录 <base>/<safe_paper_id>/<safe_paper_id>.pdf，
        # 便于与精读结果文档（snap/lens/sphere_*.json）同目录共存。
        base_dir = download_dir or os.getenv("PAPER_DOWNLOAD_DIR", "./data/downloads")
        paper_id = task.paper_id or ""
        # 规范化文件名：DOI 形如 10.64898/2026.05.18.725649 含 '/'，
        # 直接拼会变成嵌套目录，统一替换为 '_'。
        safe_paper_id = sanitize_paper_id_for_filename(paper_id) if paper_id else ""
        if safe_paper_id:
            target_dir = os.path.join(base_dir, safe_paper_id)
        else:
            target_dir = base_dir
        os.makedirs(target_dir, exist_ok=True)
        # DOI 形式的 ID（如 10.64898/...）也走 /download：其回退链（仓储/Unpaywall/Sci-Hub）
        # 可按 DOI 解析到 PDF；不要仅凭前缀短路成 read-only。
        is_doi = paper_id.startswith("10.")
        doi = paper_id if is_doi else ""

        def _try_read_api() -> bool:
            """用 /read 获取正文作为内容兜底。该端点接收 query 参数而非 JSON body。"""
            try:
                read_response = requests.post(
                    f"{mcp_api_base}/read",
                    params={"source": "arxiv", "paper_id": paper_id},
                    timeout=30,
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
                        return True
            except Exception as e:
                logger.debug(f"Read API failed for {paper_id}: {e}")
            return False

        try:
            # 调用 MCP /download 下载论文（源站 → OA 仓储 → Unpaywall → Sci-Hub 多级回退）
            response = requests.post(
                f"{mcp_api_base}/download",
                json={
                    "source": "arxiv",
                    "paper_id": paper_id,
                    "doi": doi or None,
                    "title": task.title or None,
                    "save_path": target_dir,
                    "use_scihub": True,
                },
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    returned_path = result.get("save_path", "")
                    expected_path = os.path.join(target_dir, f"{safe_paper_id}.pdf")

                    resolved_path = _resolve_downloaded_pdf(
                        expected_path, returned_path, target_dir, paper_id
                    )
                    if resolved_path:
                        task.pdf_path = resolved_path
                        task.status = "downloaded"
                        logger.info(f"Downloaded paper: {paper_id} -> {resolved_path}")
                    else:
                        # 下载返回 success 但找不到实际文件：尝试 /read 兜底
                        if _try_read_api():
                            return task
                        task.status = "failed"
                        task.error = "PDF not found after download"
                else:
                    # 下载回退链全部失败：尝试 /read 获取正文兜底
                    if _try_read_api():
                        return task
                    task.status = "failed"
                    task.error = result.get("error") or result.get("detail") or "Download failed"
            else:
                # HTTP 错误，尝试 read API 兜底
                if _try_read_api():
                    return task

                task.status = "failed"
                task.error = f"HTTP {response.status_code}"

        except requests.exceptions.RequestException as e:
            # 网络层失败也尝试 read API 兜底
            if _try_read_api():
                return task
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
        from src.utils.logger import logger

        # 检查PDF路径是否存在
        if not task.pdf_path:
            task.status = "failed"
            task.error = "No PDF path provided"
            logger.warning(f"Parse failed - no PDF path: {task.paper_id}")
            return task

        if not os.path.exists(task.pdf_path):
            # 尝试多个可能的路径（统一用规范化文件名，DOI 中的 '/' 已替换为 '_'）
            safe_id = sanitize_paper_id_for_filename(task.paper_id)
            possible_paths = [
                task.pdf_path,
                os.path.join("./data/downloads", f"{safe_id}.pdf"),
                # 旧扁平结构：data/papers/<category>/pdfs/<safe_id>.pdf（迁移前兼容）
                os.path.join("./data/papers", f"{safe_id}.pdf"),
            ]

            found_path = None
            for p in possible_paths:
                if os.path.exists(p):
                    found_path = p
                    break

            # 新结构：data/papers/<category>/<safe_id>/<safe_id>.pdf（类别未知，glob 查找）
            if not found_path and safe_id:
                import glob
                candidates = glob.glob(
                    os.path.join("./data/papers", "*", safe_id, f"{safe_id}.pdf")
                )
                if candidates:
                    found_path = candidates[0]

            if found_path:
                task.pdf_path = found_path
                logger.info(f"Found PDF at alternative path: {found_path}")
            else:
                # 列出downloads目录的内容帮助调试
                download_dir = os.path.join(os.getenv("PAPER_DOWNLOAD_DIR", "./data/downloads"))
                if os.path.exists(download_dir):
                    files = os.listdir(download_dir)
                    logger.warning(f"PDF not found: {task.paper_id}, files in downloads: {files[:10]}")
                else:
                    logger.warning(f"PDF not found: {task.pdf_path}, download dir not exists: {download_dir}")

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
            logger.info(f"Parsed paper successfully: {task.paper_id}, words: {parsed.word_count}")

        except Exception as e:
            task.status = "failed"
            task.error = f"Parse failed: {e}"
            logger.warning(f"Parse failed for {task.paper_id}: {e}")

        return task

    def process_task(self, task: ReadingTask, download_dir: Optional[str] = None) -> ReadingTask:
        """
        Complete processing: download + parse.

        Args:
            task: Reading task
            download_dir: Custom download directory

        Returns:
            Fully processed task
        """
        # Download with custom directory
        task = self.download_paper(task, download_dir=download_dir)
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
        download_dir: Optional[str] = None,
    ) -> List[ReadingTask]:
        """
        Process tasks in parallel.

        Args:
            tasks: List of reading tasks
            max_workers: Override max workers
            download_dir: Custom download directory

        Returns:
            Processed tasks
        """
        workers = max_workers or self.max_workers
        processed = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            # 使用 partial 传递 download_dir
            task_func = partial(self.process_task, download_dir=download_dir)
            futures = {executor.submit(task_func, task): task for task in tasks}

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
        download_dir: Optional[str] = None,
    ) -> ReadingResult:
        """
        Run complete reading workflow.

        Args:
            papers: Papers to read
            max_workers: Parallel workers
            download_dir: Custom download directory (e.g., papers/reinforcement_learning/pdfs)

        Returns:
            ReadingResult
        """
        # Create tasks
        tasks = self.create_tasks(papers)

        # Process in parallel with custom download directory
        processed_tasks = self.process_batch(tasks, max_workers, download_dir)

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

"""
Scira MCP Server

统一管理所有 MCP 服务的启动和 API 调用。
支持多个 MCP 服务的扩展。
同时提供前端需要的静态文件服务和工作流API。
"""

import asyncio
import json
import os
import re
import sys
import subprocess
import aiofiles
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging
from datetime import datetime

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables from main project .env
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# Also set ENV_FILE for MCP config to load from same .env
os.environ["PAPER_SEARCH_MCP_ENV_FILE"] = str(PROJECT_ROOT / ".env")

from src.utils.logger import setup_logging, get_logger, set_log_level, get_log_level, bridge_stdlib_logging
from src.utils.context import new_request_id, set_request_id, get_current_request_id
from src.utils.metrics import get_registry, init_default_metrics

# 日志在 logger.py 导入时已自动初始化（honors LOG_LEVEL/LOG_FORMAT env）；
# 这里再调一次幂等 setup_logging 确保显式触发，并初始化默认 metrics。
setup_logging()
init_default_metrics()
_metrics = get_registry()

logger = get_logger("mcp_server")

# ==================== 配置 ====================

# Download directory from .env
PAPER_DOWNLOAD_DIR = os.getenv("PAPER_DOWNLOAD_DIR", "./downloads")

# Data directory for frontend static files
DATA_DIR = PROJECT_ROOT / "data"

# MCP 服务配置
MCP_SERVICES: Dict[str, Dict[str, Any]] = {
    "paper-search": {
        "name": "Paper Search MCP",
        "path": "paper_search_mcp",  # 注意：没有连字符
        "command": ["python3", "-m", "paper_search_mcp.server"],
        "env": {
            "PAPER_SEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY": os.getenv("PAPER_SEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY", ""),
            "PAPER_SEARCH_MCP_CORE_API_KEY": os.getenv("PAPER_SEARCH_MCP_CORE_API_KEY", ""),
            "PAPER_SEARCH_MCP_UNPAYWALL_EMAIL": os.getenv("PAPER_SEARCH_MCP_UNPAYWALL_EMAIL", ""),
            "PAPER_SEARCH_MCP_DOAJ_API_KEY": os.getenv("PAPER_SEARCH_MCP_DOAJ_API_KEY", ""),
            "PAPER_SEARCH_MCP_ZENODO_ACCESS_TOKEN": os.getenv("PAPER_SEARCH_MCP_ZENODO_ACCESS_TOKEN", ""),
            "WFDATA_APP_KEY": os.getenv("WFDATA_APP_KEY", ""),
            "WFDATA_APP_CODE": os.getenv("WFDATA_APP_CODE", ""),
            "APAPER_MCP_ENABLED": os.getenv("APAPER_MCP_ENABLED", "0"),
        },
        "enabled": True,
    },
}

# API 配置
API_HOST = "0.0.0.0"
API_PORT = 8001

# ==================== 数据模型 ====================

class SearchRequest(BaseModel):
    """论文搜索请求"""
    query: str = Field(..., description="搜索关键词")
    max_results: int = Field(default=10, description="最大结果数")
    sources: str = Field(default="all", description="数据源，逗号分隔或 'all'")
    year: Optional[str] = Field(default=None, description="年份过滤")


class ChatSendRequest(BaseModel):
    """聊天消息请求"""
    message: str = Field(..., description="用户消息")
    session_id: Optional[str] = Field(default=None, description="会话ID，不提供则创建新会话")


class ChatResponse(BaseModel):
    """聊天响应"""
    session_id: str
    response: str
    action: str  # direct_response, knowledge_query, start_workflow, clarification, help
    intent: Optional[str] = None
    task_id: Optional[str] = None
    research_topic: Optional[str] = None


class DownloadRequest(BaseModel):
    """论文下载请求"""
    source: str = Field(..., description="数据源")
    paper_id: str = Field(..., description="论文ID")
    doi: Optional[str] = Field(default=None, description="DOI")
    title: Optional[str] = Field(default=None, description="标题")
    save_path: str = Field(default=PAPER_DOWNLOAD_DIR, description="保存目录")
    use_scihub: bool = Field(default=True, description="是否启用 Sci-Hub 回退")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    services: Dict[str, str]


class WorkflowStartRequest(BaseModel):
    """工作流启动请求"""
    query: str = Field(..., description="用户的研究主题")
    auto_approve: bool = Field(default=False, description="是否自动批准")


class StartFromKbRequest(BaseModel):
    """从知识库生成综述请求"""
    categories: List[str] = Field(..., description="选中的知识库目录名列表")
    topic: str = Field(..., description="本次综述的主题/聚焦方向")
    session_id: Optional[str] = Field(default=None, description="会话ID（可选）")


class WorkflowStatusResponse(BaseModel):
    """工作流状态响应"""
    task_id: str
    status: str
    message: str
    phase: Optional[str] = None
    progress: Optional[float] = None


# ==================== FastAPI 应用 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化服务，停止时清理。"""
    # uvicorn 启动时可能用 dictConfig 覆盖 stdlib logging，这里重新挂上 InterceptHandler
    bridge_stdlib_logging()
    logger.info("Starting MCP Server...")
    _warn_missing_api_keys()
    await manager.start_all_services()
    _metrics.gauge("mcp_subprocess_active").set(float(len(manager.processes)))
    logger.info("MCP Server started")
    try:
        yield
    finally:
        logger.info("Stopping MCP Server...")
        for service_key in list(manager.processes.keys()):
            await manager.stop_service(service_key)
        _metrics.gauge("mcp_subprocess_active").set(0.0)
        logger.info("MCP Server stopped")


app = FastAPI(
    title="Scira MCP Server",
    description="MCP 服务统一入口",
    version="1.0.0",
    lifespan=lifespan,
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_and_metrics_middleware(request: Request, call_next):
    """注入 request_id（X-Request-ID 头）并记录 HTTP 请求 metrics。"""
    import time as _time
    rid = request.headers.get("X-Request-ID") or new_request_id()
    set_request_id(rid)
    start = _time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    except Exception:
        _metrics.counter("errors_total").inc(labels={"component": "http"})
        raise
    finally:
        duration = _time.perf_counter() - start
        _metrics.counter("http_requests_total").inc(labels={
            "method": request.method, "path": request.url.path, "status": str(status_code)
        })
        _metrics.histogram("http_request_duration_seconds").observe(
            duration, labels={"path": request.url.path}
        )


# ==================== MCP 服务管理 ====================

class MCPServiceManager:
    """MCP 服务管理器"""

    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.base_path = Path(__file__).parent

    def get_service_path(self, service_key: str) -> Path:
        """获取服务路径"""
        config = MCP_SERVICES.get(service_key)
        if not config:
            raise ValueError(f"Unknown service: {service_key}")
        return self.base_path / config["path"]

    def get_service_env(self, service_key: str) -> Dict[str, str]:
        """获取服务环境变量"""
        config = MCP_SERVICES.get(service_key, {})
        env = os.environ.copy()

        # 加载服务目录下的 .env 文件
        service_path = self.get_service_path(service_key)
        env_file = service_path / ".env"

        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        key, _, value = line.partition("=")
                        env[key.strip()] = value.strip()

        # 合并配置中的环境变量
        config_env = config.get("env", {})
        env.update(config_env)

        return env

    async def start_service(self, service_key: str) -> bool:
        """启动单个 MCP 服务"""
        config = MCP_SERVICES.get(service_key)

        if not config:
            logger.error(f"Unknown service: {service_key}")
            return False

        if not config.get("enabled", True):
            logger.warning(f"Service {service_key} is disabled")
            return False

        # 检查是否已运行
        if service_key in self.processes:
            logger.info(f"Service {service_key} already running")
            return True

        try:
            service_path = self.get_service_path(service_key)
            cmd = config["command"].copy()

            # 如果是 python -m 模式，更新工作目录
            if "python" in cmd[0] and "-m" in cmd:
                cwd = service_path
            else:
                cwd = service_path

            env = self.get_service_env(service_key)

            # 启动进程（不等待，因为 MCP 服务通常是长期运行的）
            # 注意：这里只启动进程，实际通过 HTTP API 调用
            logger.info(f"Service {service_key} configured at {service_path}")

            return True

        except Exception as e:
            logger.error(f"Failed to start service {service_key}: {e}")
            return False

    async def start_all_services(self) -> Dict[str, bool]:
        """启动所有启用的服务"""
        results = {}
        for service_key in MCP_SERVICES:
            results[service_key] = await self.start_service(service_key)
        return results

    async def stop_service(self, service_key: str) -> bool:
        """停止单个服务"""
        if service_key in self.processes:
            process = self.processes[service_key]
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            del self.processes[service_key]
            logger.info(f"Service {service_key} stopped")
        return True

    def get_status(self) -> Dict[str, str]:
        """获取所有服务状态"""
        status = {}
        for service_key, config in MCP_SERVICES.items():
            if service_key in self.processes:
                status[service_key] = "running"
            elif config.get("enabled", True):
                status[service_key] = "stopped"
            else:
                status[service_key] = "disabled"
        return status


# 全局服务管理器
manager = MCPServiceManager()


# ==================== API 路由 ====================

def _warn_missing_api_keys() -> None:
    """启动时检查关键检索源 API 密钥，缺失则给出清晰告警。

    这些密钥非必需（公开端点仍可工作），但缺失会显著降低速率与稳定性
    （Semantic Scholar/DOAJ 无密钥时更易触发 429 限流）。
    """
    missing = []
    if not os.getenv("PAPER_SEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY"):
        missing.append("Semantic Scholar")
    if not os.getenv("PAPER_SEARCH_MCP_DOAJ_API_KEY"):
        missing.append("DOAJ")
    if not os.getenv("PAPER_SEARCH_MCP_CORE_API_KEY"):
        missing.append("CORE")
    if not os.getenv("PAPER_SEARCH_MCP_ZENODO_ACCESS_TOKEN"):
        missing.append("Zenodo")
    if not os.getenv("PAPER_SEARCH_MCP_UNPAYWALL_EMAIL"):
        missing.append("Unpaywall email")
    if missing:
        logger.warning(
            "缺少以下检索源 API 密钥（可选，但缺失会降低速率/触发限流）: %s。"
            "请在环境变量中配置以获得更稳定的检索。",
            ", ".join(missing),
        )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    status = manager.get_status()
    all_running = all(s == "running" for s in status.values())
    return HealthResponse(
        status="healthy" if all_running else "degraded",
        services=status,
    )


@app.get("/services")
async def list_services():
    """列出所有可用的服务"""
    return {
        name: {
            "name": config["name"],
            "path": config["path"],
            "enabled": config.get("enabled", True),
            "status": manager.get_status().get(name, "unknown"),
        }
        for name, config in MCP_SERVICES.items()
    }


@app.get("/metrics")
async def metrics_endpoint():
    """进程内 metrics JSON 快照。包含 HTTP/workflow/LLM/subprocess 指标，
    以及从 TokenTracker 桥接的 token 用量。"""
    from src.utils.logger import get_token_tracker
    snapshot = _metrics.collect()
    try:
        snapshot["_llm_token_tracker"] = get_token_tracker().get_summary()
    except Exception as e:
        snapshot["_llm_token_tracker"] = {"error": str(e)}
    return snapshot


class LogLevelRequest(BaseModel):
    level: str = Field(..., description="目标日志级别，如 DEBUG/INFO/WARNING/ERROR")


@app.get("/api/logs/level")
async def get_log_level_endpoint():
    """获取当前日志级别。"""
    return {"level": get_log_level()}


@app.post("/api/logs/level")
async def set_log_level_endpoint(req: LogLevelRequest):
    """运行时切换日志级别（无需重启）。"""
    try:
        new_level = set_log_level(req.level)
        return {"level": new_level, "ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Workflow API ====================

# Task storage for workflow status
workflow_tasks: Dict[str, Dict[str, Any]] = {}


def _new_event_queue():
    import collections
    return collections.deque()


def make_workflow_progress_callback(task_id: str):
    """
    构造 progress_callback：把工作流阶段写入 workflow_tasks[task_id]，
    供 /api/workflow/stream/{task_id} SSE 轮询推送给前端。

    与 SSE 的事件类型对齐：
    - retrieval / retrieval_download / reading / analysis / outline / writing / revision
    - details 中的 papers_* 字段供下载/阅读进度展示
    - details 中的 per_paper 字段（{paper_id,status,error}）入 event_queue，SSE flush
    """
    def _cb(phase: str, progress: float, message: str, details: Optional[dict] = None):
        task = workflow_tasks.get(task_id)
        if not task:
            return
        task["phase"] = phase
        if progress is not None:
            task["progress"] = progress
        if message:
            task["details"]["message"] = message
        if details:
            # 这些 key 是高频/快照事件，入 event_queue 由 SSE 每轮 flush，避免被 details 覆盖或被 status_hash 节流
            event_keys = {"per_paper", "outline_result", "writing_token", "writing_done", "review_result"}
            for k, v in details.items():
                if k in event_keys:
                    task.setdefault("event_queue", _new_event_queue()).append({k: v})
                else:
                    task["details"][k] = v
        # 检索完成、等待用户确认下载哪些论文：切到等待态，供 SSE 推送下载确认卡片
        if phase == "paper_download_approval_request":
            task["status"] = "awaiting_download_approval"
    return _cb


def generate_search_summary(topic: str, search_results: List[Dict[str, Any]],
                            downloaded_count: int,
                            shortfall_hint: Optional[str] = None) -> str:
    """
    search 模式检索+下载完成后，用 LLM 生成给用户的检索结果简介。

    简介 = 检索到 N 篇/已下载 M 篇 + 整体方向归纳 + 代表性论文清单 + 知识库提示。
    失败时回退到结构化清单，保证总有反馈。
    """
    found = len(search_results or [])

    def _fmt_paper(i: int, p: Dict[str, Any]) -> str:
        title = (p.get("title") or "Untitled").strip()
        authors = p.get("authors") or []
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]
        author_str = ", ".join(authors[:3]) if authors else "佚名"
        if len(authors) > 3:
            author_str += " 等"
        date_str = p.get("published_date") or p.get("published") or ""
        year = ""
        if date_str:
            m = re.search(r"\d{4}", str(date_str))
            if m:
                year = m.group(0)
        abstract = (p.get("abstract") or "").strip()
        brief = abstract[:80] + ("…" if len(abstract) > 80 else "")
        return f"{i}. {title} — {author_str}({year})：{brief}"

    papers_text = "\n".join(
        _fmt_paper(i, p) for i, p in enumerate(search_results[:10], 1)
    ) or "（无论文信息）"

    shortfall_line = f"注意：{shortfall_hint}。可在下方确认是否需要放宽条件重试。\n" if shortfall_hint else ""

    try:
        from src.agents.prompts import SEARCH_SUMMARY_PROMPT
        from config.settings import get_llm_client, get_config
        from langchain_core.messages import HumanMessage

        prompt = SEARCH_SUMMARY_PROMPT.format(
            topic=topic or "该主题",
            found=found,
            downloaded=downloaded_count,
            shortfall_line=shortfall_line,
            papers=papers_text,
        )
        llm = get_llm_client(get_config())
        resp = llm.invoke([HumanMessage(content=prompt)])
        summary = (resp.content or "").strip()
        if summary:
            return summary
    except Exception as e:
        logger.warning(f"generate_search_summary LLM failed: {e}")

    # 回退：结构化清单
    lines = [f"已检索到 {found} 篇论文，成功下载 {downloaded_count} 篇。", "", "代表性论文："]
    lines += [_fmt_paper(i, p) for i, p in enumerate(search_results[:5], 1)]
    lines.append("\n可在「知识库」页面查看完整论文列表与 PDF。")
    return "\n".join(lines)


@app.post("/api/workflow/start")
async def start_workflow(request: WorkflowStartRequest):
    """
    启动研究流

    根据用户输入的研究主题，自动完成论文检索、阅读、分析、写作全流程。
    """
    import uuid
    from src.core.workflow import run_workflow

    task_id = str(uuid.uuid4())

    # Store task info
    workflow_tasks[task_id] = {
        "status": "running",
        "query": request.query,
        "phase": "init",
        "progress": 0.0,
        "details": {
            "message": "正在初始化...",
            "papers_found": 0,
            "papers_to_download": 0,
            "papers_downloading": 0,
            "papers_downloaded": [],
            "papers_reading": 0,
            "total_papers": 0,
        },
        "event_queue": _new_event_queue(),
    }

    logger.info(f"Starting workflow task {task_id} for query: {request.query}")

    # Run workflow in background
    def run_workflow_task():
        try:
            workflow_tasks[task_id]["phase"] = "retrieval"
            workflow_tasks[task_id]["progress"] = 0.1

            # Run the workflow
            result = run_workflow(
                user_query=request.query,
                auto_approve=request.auto_approve,
                progress_callback=make_workflow_progress_callback(task_id),
            )

            # Update task status on completion
            workflow_tasks[task_id]["status"] = "completed"
            workflow_tasks[task_id]["phase"] = "completed"
            workflow_tasks[task_id]["progress"] = 1.0
            workflow_tasks[task_id]["result"] = {
                "topic": result.get("research_topic", ""),
                "outline": result.get("outline", ""),
                "final_report": result.get("final_report", ""),
            }
            logger.info(f"Workflow task {task_id} completed")

        except Exception as e:
            logger.error(f"Workflow task {task_id} failed: {e}")
            workflow_tasks[task_id]["status"] = "failed"
            workflow_tasks[task_id]["error"] = str(e)

    # Run in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_workflow_task)

    return {
        "task_id": task_id,
        "status": "started",
        "message": f"工作流已启动: {request.query}",
    }


@app.post("/api/workflow/start-from-kb")
async def start_workflow_from_kb(request: StartFromKbRequest):
    """
    从已有知识库生成综述：跳过检索/下载/精读，直接读精读结果文档，
    走 analysis→outline→writing→revision。SSE 复用 /api/workflow/stream/{task_id}。
    """
    import uuid
    from src.core.workflow import run_workflow_from_knowledge_bases
    from src.core.memory import memory_manager

    if not request.categories:
        raise HTTPException(status_code=400, detail="至少选择一个知识库")
    if not request.topic or not request.topic.strip():
        raise HTTPException(status_code=400, detail="请填写综述主题")

    # 获取或创建会话
    session = memory_manager.get_or_create_session(request.session_id)
    task_id = str(uuid.uuid4())

    workflow_tasks[task_id] = {
        "status": "running",
        "query": request.topic,
        "phase": "init",
        "progress": 0.0,
        "session_id": session.session_id,
        "workflow_mode": "full",
        "source_categories": list(request.categories),
        "details": {
            "message": "正在加载知识库精读结果...",
            "papers_found": 0,
            "papers_to_download": 0,
            "papers_downloading": 0,
            "papers_downloaded": [],
            "current_downloading": "",
            "papers_reading": 0,
            "total_papers": 0,
        },
        "event_queue": _new_event_queue(),
    }

    logger.info(f"Starting KB-based workflow task {task_id} | categories={request.categories} | topic={request.topic}")

    # 先落库用户消息 + 助手占位回复：会话必须在工作流跑起来之前就存在，
    # 否则 SSE 期间前端回写卡片（/api/chat/session/{session_id}/card）会因找不到 assistant 消息而 404。
    memory_manager.add_message(
        session_id=session.session_id,
        role="user",
        content=f"基于知识库「{', '.join(request.categories)}」生成综述：{request.topic}",
    )
    memory_manager.add_message(
        session_id=session.session_id,
        role="assistant",
        content=f"好的，我将基于所选知识库（{', '.join(request.categories)}）生成「{request.topic}」的综述，请稍候...",
        metadata={"action": "start_from_kb", "task_id": task_id, "source_categories": list(request.categories)},
    )

    def run_kb_task():
        try:
            result = run_workflow_from_knowledge_bases(
                categories=request.categories,
                topic=request.topic,
                progress_callback=make_workflow_progress_callback(task_id),
                session_id=session.session_id,
            )
            # 复用 _finalize_workflow_task 收尾（写 result、回写 session、标 completed）
            _finalize_workflow_task(
                task=workflow_tasks[task_id],
                workflow_result=result,
                research_topic=request.topic,
                workflow_mode="full",
                session_id=session.session_id,
            )
            logger.info(f"KB-based workflow task {task_id} completed")
        except Exception as e:
            logger.error(f"KB-based workflow task {task_id} failed: {e}", exc_info=True)
            workflow_tasks[task_id]["status"] = "failed"
            workflow_tasks[task_id]["error"] = str(e)

    # 不 await：后台跑工作流，立即返回 task_id，前端马上订阅 SSE 拿实时进度。
    # （与 /api/workflow/approve-retrieval 的模式一致；原先 await 会导致弹窗一直不关闭、
    # SSE 订阅得太晚错过所有阶段事件。）
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_kb_task)

    return {
        "task_id": task_id,
        "status": "started",
        "session_id": session.session_id,
        "message": f"已开始基于 {len(request.categories)} 个知识库生成综述",
    }


@app.get("/api/workflow/status/{task_id}")
async def get_workflow_status(task_id: str):
    """获取工作流状态"""
    if task_id not in workflow_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = workflow_tasks[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "phase": task.get("phase"),
        "progress": task.get("progress"),
        "details": task.get("details", {}),
        "result": task.get("result"),
        "error": task.get("error"),
    }


@app.get("/api/workflow/stream/{task_id}")
async def workflow_stream(task_id: str):
    """
    SSE 流式推送工作流状态

    实时推送工作流执行状态到前端，包括：
    - 阶段变化 (phase)
    - 进度更新 (progress)
    - 下载进度 (download)
    - 阅读进度 (reading)
    - 完成信息 (complete)
    """
    if task_id not in workflow_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        last_update_time = 0
        last_status_hash = ""

        while True:
            # 检查任务是否存在
            if task_id not in workflow_tasks:
                yield "data: {\"type\": \"error\", \"data\": {\"message\": \"Task not found\"}}\n\n"
                break

            task = workflow_tasks[task_id]
            current_time = datetime.now().timestamp()

            # 先 flush 逐篇下载事件 + 阶段卡片事件（不受 status_hash 节流，避免 1s 内多篇/多 token 丢失）
            eq = task.get("event_queue")
            while eq:
                evt = eq.popleft()
                if "per_paper" in evt:
                    pp = evt["per_paper"]
                    yield f"data: {json.dumps({'type': 'download', 'data': {'paper_id': pp.get('paper_id'), 'paper_status': pp.get('status'), 'error': pp.get('error')}})}\n\n"
                elif "outline_result" in evt:
                    yield f"data: {json.dumps({'type': 'outline_result', 'data': evt['outline_result']})}\n\n"
                elif "writing_token" in evt:
                    yield f"data: {json.dumps({'type': 'writing_token', 'data': evt['writing_token']})}\n\n"
                elif "writing_done" in evt:
                    yield f"data: {json.dumps({'type': 'writing_done', 'data': evt['writing_done']})}\n\n"
                elif "review_result" in evt:
                    yield f"data: {json.dumps({'type': 'review_result', 'data': evt['review_result']})}\n\n"

            # 计算当前状态的 hash 用于检测变化
            status_hash = f"{task.get('status')}_{task.get('phase')}_{task.get('progress')}_{current_time}"

            # 只有状态变化时才推送
            if status_hash != last_status_hash:
                last_status_hash = status_hash
                last_update_time = current_time

                # 构建 SSE 消息
                if task["status"] == "running":
                    phase = task.get("phase", "unknown")
                    progress = task.get("progress", 0)
                    details = task.get("details", {})

                    # 阶段变化消息
                    if phase == "retrieval":
                        message = details.get("message", "论文检索中...")
                        papers_found = details.get("papers_found", 0)
                        if papers_found > 0:
                            message = f"检索到 {papers_found} 篇论文"
                        yield f"data: {json.dumps({'type': 'phase', 'data': {'phase': 'retrieval', 'message': message, 'progress': progress}})}\n\n"

                    elif phase == "retrieval_download" or "download" in phase:
                        downloading = details.get("papers_downloading", 0)
                        total = details.get("papers_to_download", 0)
                        current_paper = details.get("current_downloading", "")
                        downloaded = details.get("papers_downloaded", [])

                        if current_paper:
                            msg = f"正在下载：{current_paper}（已完成 {downloading}/{total}）"
                        else:
                            msg = f"已下载 {downloading}/{total} 篇论文"
                        yield f"data: {json.dumps({'type': 'download', 'data': {'current': downloading, 'total': total, 'current_paper': current_paper, 'downloaded': downloaded, 'message': msg, 'progress': progress}})}\n\n"

                    elif phase == "reading":
                        reading = details.get("papers_reading", 0)
                        total = details.get("total_papers", 0)
                        yield f"data: {json.dumps({'type': 'reading', 'data': {'current': reading, 'total': total, 'message': f'阅读 {reading}/{total} 篇论文', 'progress': progress}})}\n\n"

                    elif phase == "analysis":
                        yield f"data: {json.dumps({'type': 'phase', 'data': {'phase': 'analysis', 'message': '文献分析中...', 'progress': progress}})}\n\n"

                    elif phase == "outline":
                        yield f"data: {json.dumps({'type': 'generation', 'data': {'stage': 'outline', 'message': '生成论文大纲中...', 'progress': progress}})}\n\n"

                    elif phase == "writing":
                        yield f"data: {json.dumps({'type': 'generation', 'data': {'stage': 'writing', 'message': '论文写作中...', 'progress': progress}})}\n\n"

                    elif phase == "revision":
                        yield f"data: {json.dumps({'type': 'generation', 'data': {'stage': 'revision', 'message': '论文审查中...', 'progress': progress}})}\n\n"

                    elif phase == "init":
                        yield f"data: {json.dumps({'type': 'workflow_started', 'data': {'message': '已启动研究工作流，正在准备...'}})}\n\n"

                elif task["status"] == "awaiting_download_approval":
                    # 检索完成，等待用户在下载确认卡片上勾选论文
                    details = task.get("details", {})
                    pending = details.get("pending_download_papers", [])
                    yield f"data: {json.dumps({'type': 'paper_download_approval_request', 'data': {'task_id': task_id, 'papers': pending, 'papers_found': details.get('papers_found', 0), 'already_downloaded': details.get('already_downloaded', 0), 'matched_category': details.get('matched_category', ''), 'existing_categories': details.get('existing_categories', [])}})}\n\n"
                    # 不 break：保持连接，approve-download 后 task 会转回 running/completed 继续推送
                    await asyncio.sleep(1)
                    continue

                elif task["status"] == "completed":
                    result = task.get("result", {})
                    topic = result.get("topic", "")
                    mode = result.get("workflow_mode") or task.get("workflow_mode") or "full"
                    papers_found = result.get("papers_found", 0)
                    papers_downloaded = result.get("papers_downloaded", 0)
                    summary = result.get("summary", "")
                    # search 模式优先用 LLM 生成的简介作为完成消息
                    if mode == "search" and summary:
                        msg = summary
                    elif mode == "search":
                        msg = f"已完成检索并下载 {papers_downloaded} 篇论文，可在「知识库」查看"
                    else:
                        msg = "研究完成！"
                    final_report = result.get("final_report", "")
                    yield f"data: {json.dumps({'type': 'complete', 'data': {'message': msg, 'topic': topic, 'workflow_mode': mode, 'papers_found': papers_found, 'papers_downloaded': papers_downloaded, 'summary': summary, 'final_report': final_report}})}\n\n"
                    break

                elif task["status"] == "failed":
                    error = task.get("error", "未知错误")
                    yield f"data: {json.dumps({'type': 'error', 'data': {'message': f'运行失败: {error}'}})}\n\n"
                    break

            # 等待一段时间后再检查
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class ApproveRetrievalRequest(BaseModel):
    """检索审批请求"""
    task_id: str = Field(..., description="工作流任务ID")
    decision: str = Field(..., description="approve 或 reject")
    modification: Optional[str] = Field(default=None, description="拒绝时的修改建议")
    session_id: Optional[str] = Field(default=None, description="会话ID（可选，优先用任务里存的）")


class ApproveDownloadRequest(BaseModel):
    """下载确认请求"""
    task_id: str = Field(..., description="工作流任务ID")
    decision: str = Field(..., description="approve 或 reject")
    selected_paper_ids: List[str] = Field(default_factory=list, description="approve 时勾选要下载的 paper_id 列表")
    target_category: Optional[str] = Field(default=None, description="用户选择的知识库名；None=用自动匹配")
    new_category_name: Optional[str] = Field(default=None, description="用户新建知识库名；提供则忽略 target_category")
    session_id: Optional[str] = Field(default=None, description="会话ID（可选，优先用任务里存的）")


def _finalize_workflow_task(task, workflow_result, research_topic, workflow_mode, session_id):
    """工作流（含下载与后续节点）跑完后统一收尾：写 result、回写 session、标记 completed。"""
    from src.core.memory import memory_manager as _mm
    task["status"] = "completed"
    task["phase"] = "completed"
    task["progress"] = 1.0
    search_results = workflow_result.get("search_results") or []
    papers_found = len(search_results)
    literature_data = workflow_result.get("literature_data") or []
    papers_downloaded = len(literature_data)
    search_summary = ""
    if workflow_mode == "search":
        task["details"]["message"] = f"已完成检索并下载 {papers_downloaded} 篇论文"
        try:
            search_summary = generate_search_summary(
                research_topic, search_results, papers_downloaded,
                shortfall_hint=workflow_result.get("retrieval_shortfall_hint"),
            )
        except Exception as e:
            logger.warning(f"generate_search_summary failed: {e}")
    else:
        task["details"]["message"] = "研究完成！"
    task["result"] = {
        "topic": research_topic,
        "workflow_mode": workflow_mode,
        "papers_found": papers_found,
        "papers_downloaded": papers_downloaded,
        "summary": search_summary,
        "outline": workflow_result.get("outline", ""),
        "final_report": workflow_result.get("final_review", ""),
    }

    # 把真实完成结果回写 session，修复刷新后仍显示占位符的问题
    if session_id:
        final_text = search_summary or workflow_result.get("final_review") or task["result"].get("summary") or "研究完成！"
        try:
            _mm.update_last_assistant_message_content(session_id=session_id, content=final_text)
        except Exception as e:
            logger.warning(f"update_last_assistant_message_content failed: {e}")


@app.post("/api/workflow/approve-retrieval")
async def approve_retrieval(request: ApproveRetrievalRequest):
    """
    检索条件审批端点。

    - approve：用户接受检索条件，后台启动完整工作流（auto_approve=True），返回 task_id，前端按原流程订阅 /api/workflow/stream/{task_id}。
    - reject：用户拒绝并给出修改建议，重新生成检索条件（含 modification），返回新的 conditions，前端刷新审批卡片。
    """
    if request.task_id not in workflow_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = workflow_tasks[request.task_id]
    research_topic = task.get("query", "")
    session_id = request.session_id or task.get("session_id")

    if request.decision == "reject":
        # 重新生成检索条件，把 modification 作为用户补充意见纳入分析
        from src.core.workflow import prepare_retrieval
        try:
            # 透传用户检索约束（从 task 里取，若存在）
            _yr = task.get("year_range")
            _mc = task.get("min_count")
            loop = asyncio.get_event_loop()
            conditions = await loop.run_in_executor(
                None,
                lambda: prepare_retrieval(
                    research_topic,
                    request.modification,
                    year_range=tuple(_yr) if isinstance(_yr, (list, tuple)) and len(_yr) == 2 else None,
                    min_count=_mc if isinstance(_mc, int) and _mc > 0 else None,
                ),
            )
        except Exception as e:
            logger.error(f"prepare_retrieval on reject failed: {e}")
            raise HTTPException(status_code=500, detail=f"重新生成检索条件失败：{e}")

        task["conditions"] = conditions
        task["status"] = "awaiting_approval"
        return {
            "task_id": request.task_id,
            "status": "awaiting_approval",
            "conditions": conditions,
        }

    # approve：启动工作流，把审批通过的条件带入，避免重新分析中文查询得到空主题
    conditions = task.get("conditions") or {}
    approved_topic = conditions.get("normalized_topic") or ""
    approved_keywords = conditions.get("keywords") or []
    # 工作流模式（来自意图识别，存于 task）：full / search_only / search_download
    workflow_mode = (task.get("workflow_mode") or "full").strip().lower()

    # 把审批通过的检索条件写进 assistant 消息 metadata，刷新后可还原检索条件卡片
    if session_id:
        try:
            from src.core.memory import memory_manager as _mm_meta
            _mm_meta.update_last_assistant_message_metadata(
                session_id=session_id,
                metadata={"retrieval_conditions": conditions, "conditions_approved": True},
            )
        except Exception as e:
            logger.warning(f"persist retrieval conditions metadata failed: {e}")

    task.setdefault("event_queue", _new_event_queue())
    task["status"] = "running"
    task["phase"] = "retrieval"
    task["progress"] = 0.05
    task["details"]["message"] = "论文检索中..."

    def run_workflow_task():
        try:
            from src.core.workflow import run_workflow
            from src.core.memory import memory_manager as _mm
            workflow_result = run_workflow(
                user_query=research_topic,
                auto_approve=True,
                approved_topic=approved_topic or None,
                approved_keywords=approved_keywords or None,
                progress_callback=make_workflow_progress_callback(request.task_id),
                workflow_mode=workflow_mode,
            )

            if session_id:
                try:
                    _mm.update_research_context(
                        session_id=session_id, topic=research_topic, result=workflow_result,
                    )
                except Exception as e:
                    logger.warning(f"update_research_context failed: {e}")

            # 检索完成后，若有待确认下载的论文，工作流在此暂停，等 /api/workflow/approve-download
            pending = workflow_result.get("pending_download_papers") or []
            if pending:
                # 回调已把 task 置为 awaiting_download_approval；缓存暂停态供 approve-download 续跑
                task["status"] = "awaiting_download_approval"
                task["phase"] = "paper_download_approval_request"
                task["workflow_state"] = workflow_result
                task["session_id"] = session_id
                task["details"]["pending_download_papers"] = pending
                task["details"]["message"] = f"检索完成，待确认下载 {len(pending)} 篇论文"
                return

            # 无需下载（none 模式 / 无 pdf_url）：直接收尾
            _finalize_workflow_task(task, workflow_result, research_topic, workflow_mode, session_id)
        except Exception as e:
            logger.error(f"Workflow task {request.task_id} failed: {e}")
            task["status"] = "failed"
            task["error"] = str(e)
            if session_id:
                try:
                    from src.core.memory import memory_manager as _mm_err
                    _mm_err.update_last_assistant_message_content(
                        session_id=session_id,
                        content=f"工作流执行失败：{e}",
                    )
                except Exception:
                    pass

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_workflow_task)

    return {"task_id": request.task_id, "status": "running"}


@app.post("/api/workflow/approve-download")
async def approve_download(request: ApproveDownloadRequest):
    """
    下载确认端点。

    - approve：按 selected_paper_ids 过滤候选论文，后台执行下载 + 后续节点（search 模式到下载即止，
      full 模式继续 reading/analysis/outline/writing/revision），完成后回写 session。
    - reject：跳过下载，标记任务完成并提示用户已跳过。
    前端提交后继续订阅 /api/workflow/stream/{task_id} 接收后续进度。
    """
    if request.task_id not in workflow_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = workflow_tasks[request.task_id]
    if task.get("status") != "awaiting_download_approval":
        raise HTTPException(status_code=400, detail=f"Task not awaiting download approval (status={task.get('status')})")

    workflow_state = task.get("workflow_state") or {}
    research_topic = task.get("query", "")
    workflow_mode = (task.get("workflow_mode") or "full").strip().lower()
    session_id = request.session_id or task.get("session_id")
    pending = task.get("details", {}).get("pending_download_papers") or []

    if request.decision == "reject":
        task["status"] = "completed"
        task["phase"] = "completed"
        task["progress"] = 1.0
        skip_text = f"已跳过下载。本次共检索到 {task['details'].get('papers_found', len(pending))} 篇论文并入库知识库（未下载 PDF）。"
        task["details"]["message"] = skip_text
        task["result"] = {
            "topic": research_topic,
            "workflow_mode": workflow_mode,
            "papers_found": task["details"].get("papers_found", len(pending)),
            "papers_downloaded": 0,
            "summary": skip_text,
            "outline": "",
            "final_report": "",
        }
        if session_id:
            try:
                from src.core.memory import memory_manager as _mm
                _mm.update_last_assistant_message_content(session_id=session_id, content=skip_text)
            except Exception as e:
                logger.warning(f"update_last_assistant_message_content (reject) failed: {e}")
        return {"task_id": request.task_id, "status": "completed"}

    # approve：按勾选过滤
    selected = pending
    if request.selected_paper_ids:
        wanted = set(request.selected_paper_ids)
        selected = [p for p in pending if p.get("paper_id") in wanted]

    # 知识库选择：new_category_name 优先，其次 target_category，否则保持 workflow_state 原值
    from src.core.workflow import resolve_target_category
    existing_cats = workflow_state.get("pending_categories") or []
    resolved = resolve_target_category(
        request.new_category_name, request.target_category, existing_cats
    )
    if resolved:
        old_cat = workflow_state.get("current_category")
        workflow_state["current_category"] = resolved
        # 若类别变了，重建 pdfs_dir 指向新类别目录
        from pathlib import Path as _P
        workflow_state["pdfs_dir"] = str(_P("data/papers") / resolved)
        if old_cat != resolved:
            logger.info(f"Category overridden by user: {old_cat} -> {resolved}")

    task["status"] = "running"
    task["phase"] = "retrieval_download"
    task["progress"] = 0.3
    task["details"]["message"] = f"开始下载 {len(selected)} 篇论文..."

    def run_download_task():
        try:
            from src.core.workflow import run_download_and_rest
            final_state = run_download_and_rest(
                state=workflow_state,
                selected_papers=selected,
                progress_callback=make_workflow_progress_callback(request.task_id),
            )
            _finalize_workflow_task(task, final_state, research_topic, workflow_mode, session_id)
        except Exception as e:
            logger.error(f"Download task {request.task_id} failed: {e}")
            task["status"] = "failed"
            task["error"] = str(e)
            if session_id:
                try:
                    from src.core.memory import memory_manager as _mm
                    _mm.update_last_assistant_message_content(session_id=session_id, content=f"下载/写作失败：{e}")
                except Exception:
                    pass

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_download_task)

    return {"task_id": request.task_id, "status": "running"}


# ==================== Data Static Files API ====================

@app.get("/data/papers/all_papers.json")
async def get_all_papers():
    """获取所有论文列表"""
    papers_file = DATA_DIR / "papers" / "all_papers.json"
    if not papers_file.exists():
        raise HTTPException(status_code=404, detail="Papers file not found")
    return FileResponse(papers_file)


@app.get("/data/papers/{topic}/{filename}")
async def get_paper_file(topic: str, filename: str):
    """获取 topic 目录下的论文文件"""
    file_path = DATA_DIR / "papers" / topic / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.get("/data/papers/{topic}/{subdir}/{filename}")
async def get_paper_file_in_subdir(topic: str, subdir: str, filename: str):
    """获取 topic 子目录下的文件（如 pdfs）"""
    file_path = DATA_DIR / "papers" / topic / subdir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.get("/data/outputs/{filename}")
async def get_output_file(filename: str):
    """获取输出文件"""
    # List all output files and find match
    outputs_dir = DATA_DIR / "outputs"
    if not outputs_dir.exists():
        raise HTTPException(status_code=404, detail="Outputs directory not found")

    # Try exact match first
    file_path = outputs_dir / filename
    if file_path.exists():
        return FileResponse(file_path)

    # Try to find by prefix (e.g., research_1.md -> research_*.md)
    for f in outputs_dir.glob("research_*.md"):
        if f.stem.startswith(filename.replace(".md", "").replace("research_", "research_")):
            return FileResponse(f)

    raise HTTPException(status_code=404, detail=f"File not found: {filename}")


@app.get("/api/outputs/list")
async def list_output_files():
    """列出所有输出文件"""
    outputs_dir = DATA_DIR / "outputs"
    if not outputs_dir.exists():
        return {"files": []}

    files = []
    for f in outputs_dir.glob("*.md"):
        files.append({
            "name": f.name,
            "path": f"/data/outputs/{f.name}",
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime
        })

    return {"files": sorted(files, key=lambda x: x["modified"], reverse=True)}


def _resolve_output_file(filename: str) -> Path:
    """解析 outputs 目录下的文件名，防止路径穿越。返回绝对路径，文件必须已存在。"""
    outputs_dir = (DATA_DIR / "outputs").resolve()
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=403, detail="Invalid filename")
    file_path = (outputs_dir / filename).resolve()
    # 确保解析后仍在 outputs 目录内
    try:
        file_path.relative_to(outputs_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid filename")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return file_path


class WriteOutputRequest(BaseModel):
    filename: str
    content: str


@app.post("/api/outputs/write")
async def write_output_file(req: WriteOutputRequest):
    """原子写入已有报告文件（手动编辑场景）。"""
    file_path = _resolve_output_file(req.filename)
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    try:
        tmp_path.write_text(req.content, encoding="utf-8")
        os.replace(tmp_path, file_path)
    except Exception as e:
        # 清理临时文件
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"写入失败: {e}")
    stat = file_path.stat()
    return {"ok": True, "filename": req.filename, "size": stat.st_size, "modified": stat.st_mtime}


@app.delete("/api/outputs/{filename}")
async def delete_output_file(filename: str):
    """删除输出文件"""
    outputs_dir = DATA_DIR / "outputs"
    if not outputs_dir.exists():
        raise HTTPException(status_code=404, detail="Outputs directory not found")

    # 尝试精确匹配
    file_path = outputs_dir / filename
    if file_path.exists():
        file_path.unlink()
        return {"success": True, "message": f"Deleted {filename}"}

    # 尝试通过前缀查找（如 research_20260606_095415.md）
    for f in outputs_dir.glob("*.md"):
        if filename in f.name:
            f.unlink()
            return {"success": True, "message": f"Deleted {f.name}"}

    raise HTTPException(status_code=404, detail=f"File not found: {filename}")


# ==================== Report Editing (AI assist) ====================
# 每个 session 的编辑目标文件路径（绝对路径字符串）与会话内工作副本（markdown 全文）。
# 工作副本仅在内存中维护，进程重启即丢失——用户需重发首条 AI 编辑消息重建。
edit_target_files: Dict[str, str] = {}
working_copies: Dict[str, str] = {}

# ===== KB 感知编辑助手：引用意图识别与状态机 =====
@dataclass
class CitationIntent:
    count: int
    topic_hint: Optional[str]


_CITATION_KEYWORDS = ("参考文献", "引用", "补文献", "加引用", "文献参考",
                      "references", "reference", "citation", "bibliography")
_COUNT_RE = re.compile(r"(\d+)\s*(?:篇|references?|citations?)")
_TOPIC_RE = re.compile(r"(?:关于|有关|针对|跟|与)([一-鿿A-Za-z0-9 ]{2,30})相关")
_CONFIRM_RE = re.compile(r"(用这些|就用|可以|确认|同意|好的|yes|ok|use them|就用这些)")


def _detect_citation_intent(message: str) -> Optional[CitationIntent]:
    """关键词命中返回 CitationIntent，否则 None。"""
    if not message:
        return None
    lower = message.lower()
    if not any(kw in lower for kw in _CITATION_KEYWORDS):
        return None
    count = 5
    m = _COUNT_RE.search(message)
    if m:
        try:
            count = int(m.group(1))
        except ValueError:
            pass
    topic_hint: Optional[str] = None
    m2 = _TOPIC_RE.search(message)
    if m2:
        topic_hint = m2.group(1).strip()
    return CitationIntent(count=count, topic_hint=topic_hint)


def _resolve_topic(intent: CitationIntent, working: str,
                   session_context: Optional[Dict[str, Any]]) -> str:
    """主题回退链：topic_hint → 报告首个 # 标题 → research_topics[-1] → 空串。"""
    if intent.topic_hint:
        return intent.topic_hint
    if working:
        for line in working.splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
    topics = (session_context or {}).get("research_topics") or []
    if topics:
        return topics[-1]
    return ""


def _is_confirmation(message: str) -> bool:
    """检测用户是否在确认候选/检索。"""
    if not message:
        return False
    return bool(_CONFIRM_RE.search(message.lower()))

# 每个 session 的引用编辑状态机：
# phase=candidates_listed: 已列出候选，等待用户确认
# phase=awaiting_search_confirm: KB 未命中，等待用户确认是否检索
# phase=confirmed: 用户已确认，下一轮注入 GB/T 7714 + 角标指令
edit_citation_state: Dict[str, Dict[str, Any]] = {}

# 用户消息中触发"完成写回"的关键词。要求整句为完成意图，避免误判。
# 匹配规则：消息去除标点空白后等于其中一项，或包含"全部完成/写回吧/就这样吧"等明确短语。
_COMPLETION_EXACT = {"完成", "结束", "可以了", "没问题了", "就这样", "done", "finished", "ok"}
_COMPLETION_PHRASE = ["全部完成", "写回吧", "就这样吧", "可以了，写回", "保存并结束"]

EDIT_SYSTEM_PROMPT = """你是一个科研报告编辑助手。用户正在与你协作编辑一篇 markdown 格式的研究综述报告。

工作流程：
1. 首轮：用户会贴出报告全文（在 <report>...</report> 标签内）。你读完结构后，只回复："我已读完报告，共 N 节。请问需要怎么修改？"——不要主动改动。
2. 后续每轮：用户给出修改意见，你按需修改对应章节，回复格式必须如下：

```
我修改了第 X 节「标题」。

<!-- EDIT SECTION: ## X. 标题 -->
## X. 标题

（该章节修改后的完整正文，正常 markdown）

<!-- /EDIT SECTION -->

**修改说明**：用加粗标注新增内容；说明删除/调整了什么。

> 上一节末尾：……（1-2 句邻近上下文）
> 下一节开头：……（1-2 句邻近上下文）
```

约束：
- 一次可输出多个 `<!-- EDIT SECTION: <header> --> ... <!-- /EDIT SECTION -->` 块，每个块对应一个被修改的章节
- `<header>` 必须是报告中已存在的 markdown 标题行（含 `#` 与空格，如 `## 3. 方法`），否则后端无法定位
- 块内是替换后的该章节完整新内容（从该标题行开始到下一同级/更高级标题之前的部分）
- 不要在块外贴大段章节内容——块外只放说明与邻近上下文
- 新增/删除整节也通过"替换父章节"实现：把父章节完整新内容贴进块内
- 邻近上下文用 blockquote 简短引用，让用户知道改动的位置
- 若用户要修改的内容不涉及具体章节（如全局措辞调整），按最相关章节输出 EDIT SECTION

当用户说"完成/结束/可以了/没问题了/就这样"等完成意图时，回复："好的，已将修改写回原文件。"不要再输出 EDIT SECTION。"""


def _is_completion_message(msg: str) -> bool:
    """检测用户消息是否为完成意图。"""
    normalized = re.sub(r"[，。！？\s,.!?]", "", msg).lower()
    if normalized in _COMPLETION_EXACT:
        return True
    for phrase in _COMPLETION_PHRASE:
        if phrase in msg:
            return True
    return False


_EDIT_SECTION_RE = re.compile(
    r"<!--\s*EDIT\s*SECTION:\s*(.+?)-->(.+?)<!--\s*/EDIT\s*SECTION\s*-->",
    re.DOTALL,
)


def _find_section_span(content: str, header: str) -> Optional[tuple]:
    """在 markdown 全文中定位某章节的起止下标。

    返回 (section_start, section_end)，section_start 指向 header 行开头，
    section_end 指向下一同级或更高级 header 之前（或 EOF）。
    header 形如 "## 3. 方法"，解析其 `#` 数量为级别。
    找不到返回 None。
    """
    header_match = re.match(r"^(#{1,6})\s+(.+)$", header.strip())
    if not header_match:
        return None
    level = len(header_match.group(1))
    title = header_match.group(2).strip()
    # 在 content 中查找匹配的 header 行
    pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    for i, m in enumerate(matches):
        if len(m.group(1)) == level and m.group(2).strip() == title:
            start = m.start()
            # 找到下一个同级或更高级 header
            end = len(content)
            for m2 in matches[i + 1:]:
                if len(m2.group(1)) <= level:
                    end = m2.start()
                    break
            return (start, end)
    return None


def _apply_edit_sections(working: str, reply: str) -> tuple:
    """把助手回复中的 EDIT SECTION 块应用到工作副本。

    返回 (new_working, warnings)，warnings 为未找到章节的提示列表。
    """
    warnings: List[str] = []
    new_content = working
    matches = list(_EDIT_SECTION_RE.finditer(reply))
    if not matches:
        return (new_content, ["助手回复中未找到 EDIT SECTION 块，工作副本未变更"])

    for m in matches:
        header = m.group(1).strip()
        body = m.group(2).strip()
        span = _find_section_span(new_content, header)
        if span is None:
            warnings.append(f"未找到章节「{header}」，已跳过该修改")
            continue
        # 替换该章节为新的 header + 正文（body 已含 header 行）
        new_content = new_content[:span[0]] + body + "\n\n" + new_content[span[1]:]
    return (new_content, warnings)


class SetTargetFileRequest(BaseModel):
    target_file_path: str


@app.post("/api/chat/session/{session_id}/target-file")
async def set_session_target_file(session_id: str, req: SetTargetFileRequest):
    """设置会话的 AI 编辑目标文件，并加载工作副本到内存。"""
    from src.core.memory import memory_manager

    session = memory_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 解析并校验路径：必须是 data/outputs/ 下的已存在 .md 文件
    outputs_dir = (DATA_DIR / "outputs").resolve()
    requested = Path(req.target_file_path)
    if requested.is_absolute():
        target = requested.resolve()
    else:
        target = (outputs_dir / req.target_file_path).resolve()
    try:
        target.relative_to(outputs_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="目标文件必须在 data/outputs/ 下")
    if not target.exists() or target.suffix != ".md":
        raise HTTPException(status_code=404, detail="目标文件不存在或非 markdown")

    try:
        working = target.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {e}")

    edit_target_files[session_id] = str(target)
    working_copies[session_id] = working
    return {
        "ok": True,
        "session_id": session_id,
        "target_file_path": str(target),
        "working_content_length": len(working),
    }


def _clear_edit_state(session_id: str) -> None:
    edit_target_files.pop(session_id, None)
    working_copies.pop(session_id, None)
    edit_citation_state.pop(session_id, None)


_REPORT_TAG_RE = re.compile(r"<report>(.*?)</report>", re.DOTALL)
_EDIT_INIT_FILENAME_RE = re.compile(r"文件[：:]\s*([^\s）)]+\.md)")


def _try_init_edit_from_message(session_id: str, message: str) -> Optional[str]:
    """检测用户首条消息是否含 <report> 全文，若是则初始化编辑会话。

    返回错误信息字符串（初始化失败时）或 None（成功/不匹配）。
    """
    report_match = _REPORT_TAG_RE.search(message)
    if not report_match:
        return None
    working = report_match.group(1).strip()
    fname_match = _EDIT_INIT_FILENAME_RE.search(message)
    if not fname_match:
        return "未在消息中识别到目标文件名（需形如「文件：xxx.md」）"
    filename = fname_match.group(1)
    try:
        target_path = _resolve_output_file(filename)
    except HTTPException as e:
        return f"目标文件校验失败：{e.detail}"
    edit_target_files[session_id] = str(target_path)
    working_copies[session_id] = working
    return None


@app.get("/api/papers/topics")
async def get_paper_topics():
    """获取所有论文分类"""
    papers_dir = DATA_DIR / "papers"
    topics = []

    # 遍历子目录获取分类
    if papers_dir.exists():
        for topic_dir in papers_dir.iterdir():
            if topic_dir.is_dir():
                topic_name = topic_dir.name
                # 查找该目录下 的 json 文件
                json_files = list(topic_dir.glob("*.json"))
                if json_files:
                    # 读取第一个 json 文件获取论文数量
                    try:
                        import json
                        with open(json_files[0], 'r', encoding='utf-8') as f:
                            topic_data = json.load(f)
                            topics.append({
                                "name": topic_name,
                                "displayName": topic_name.replace("_", " "),
                                "count": len(topic_data.get("papers", [])),
                                "file": f"data/papers/{topic_name}/{json_files[0].name}"
                            })
                    except Exception as e:
                        logger.warning(f"Failed to read topic {topic_name}: {e}")

    return {"topics": topics}


# ==================== Knowledge Base CRUD API ====================

def _get_topic_json_path(topic: str) -> Path:
    """获取分类的 JSON 文件路径。"""
    return DATA_DIR / "papers" / topic / f"{topic}.json"


def _read_topic(topic: str) -> Optional[Dict[str, Any]]:
    """读取分类 JSON 数据，不存在则返回 None。"""
    json_path = _get_topic_json_path(topic)
    if not json_path.exists():
        return None
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_topic(topic: str, data: Dict[str, Any]):
    """写入分类 JSON 数据。"""
    json_path = _get_topic_json_path(topic)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    data["count"] = len(data.get("papers", []))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _rebuild_all_papers_index():
    """
    重建 all_papers.json 索引：遍历 data/papers/*/ 下所有 <cat>.json，
    内联每个类别的 topic/count，重算 total_papers。

    在删除分类/论文后调用，保证索引与磁盘一致。
    保留 retrieval_node 里「不被同次检索覆盖」的语义——这里只重算，不删别人。
    """
    papers_dir = DATA_DIR / "papers"
    all_papers_file = papers_dir / "all_papers.json"
    categories_index: Dict[str, Any] = {}
    total_papers = 0
    for cat_dir in papers_dir.iterdir():
        if not cat_dir.is_dir() or cat_dir.name.startswith("_"):
            continue
        cat_json = cat_dir / f"{cat_dir.name}.json"
        if not cat_json.exists():
            continue
        try:
            with open(cat_json, "r", encoding="utf-8") as f:
                cat_data = json.load(f)
            count = int(cat_data.get("count", 0) or len(cat_data.get("papers", [])) or 0)
            total_papers += count
            categories_index[cat_dir.name] = {
                "path": str(cat_json),
                "topic": cat_data.get("topic", ""),
                "count": count,
            }
        except Exception as e:
            logger.warning(f"_rebuild_all_papers_index: skip {cat_json}: {e}")
    payload = {
        "total_papers": total_papers,
        "updated_at": datetime.now().isoformat(),
        "categories": categories_index,
    }
    try:
        with open(all_papers_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"_rebuild_all_papers_index: write failed: {e}")
    return payload


class CreateTopicRequest(BaseModel):
    name: str = Field(..., description="分类名称")


class AddPaperRequest(BaseModel):
    paper: Dict[str, Any] = Field(..., description="论文数据")


class ImportCitationRequest(BaseModel):
    text: str = Field(..., description="引用格式文本（BibTeX/APA/等）")


@app.post("/api/papers/topics")
async def create_topic(request: CreateTopicRequest):
    """新建分类"""
    import re
    topic = re.sub(r'[^\w一-鿿\-]', '_', request.name.strip())[:80]
    if not topic:
        raise HTTPException(status_code=400, detail="分类名称无效")

    json_path = _get_topic_json_path(topic)
    if json_path.exists():
        raise HTTPException(status_code=409, detail=f"分类 '{topic}' 已存在")

    _write_topic(topic, {
        "category": topic,
        "topic": request.name.strip(),
        "retrieved_at": datetime.now().isoformat(),
        "count": 0,
        "papers": [],
    })
    return {"success": True, "topic": topic, "displayName": request.name.strip()}


@app.delete("/api/papers/topics/{topic}")
async def delete_topic(topic: str):
    """删除分类及其所有论文（含 PDF + 精读结果），并同步 all_papers.json。"""
    import shutil
    topic_dir = DATA_DIR / "papers" / topic
    if not topic_dir.exists():
        raise HTTPException(status_code=404, detail=f"分类 '{topic}' 不存在")

    shutil.rmtree(topic_dir)
    # 重建全局索引：移除该类别、重算 total
    rebuilt = _rebuild_all_papers_index()
    return {"success": True, "deleted": topic, "total_papers": rebuilt["total_papers"]}


@app.delete("/api/papers/{topic}/{paper_id}")
async def delete_paper(topic: str, paper_id: str):
    """删除分类下的某篇论文（含 per-paper 目录：PDF + 精读结果），并同步 all_papers.json。"""
    import shutil
    data = _read_topic(topic)
    if data is None:
        raise HTTPException(status_code=404, detail=f"分类 '{topic}' 不存在")

    papers = data.get("papers", [])
    new_papers = [p for p in papers if p.get("paper_id") != paper_id]
    if len(new_papers) == len(papers):
        raise HTTPException(status_code=404, detail=f"论文 '{paper_id}' 不存在")

    # 删除 per-paper 目录（PDF + snap/lens/sphere 精读结果 json）
    paper_dir = DATA_DIR / "papers" / topic / paper_id
    if paper_dir.exists() and paper_dir.is_dir():
        shutil.rmtree(paper_dir)
    else:
        # 回退：旧数据可能只有平铺的 PDF，按 pdf_path 删
        removed = [p for p in papers if p.get("paper_id") == paper_id]
        for p in removed:
            pdf_path = p.get("pdf_path", "")
            if pdf_path:
                full_path = PROJECT_ROOT / pdf_path
                if full_path.exists():
                    full_path.unlink()

    data["papers"] = new_papers
    _write_topic(topic, data)
    # 重建全局索引：该类别 count 减小、total 重算
    rebuilt = _rebuild_all_papers_index()
    return {"success": True, "deleted": paper_id, "remaining": len(new_papers), "total_papers": rebuilt["total_papers"]}


def _find_paper_in_topic(topic: str, paper_id: str) -> Optional[Dict[str, Any]]:
    """在分类中查找指定 paper_id 的论文条目，返回该条目（含它在 papers 列表里的索引）。"""
    data = _read_topic(topic)
    if data is None:
        return None
    for idx, p in enumerate(data.get("papers", [])):
        if p.get("paper_id") == paper_id:
            return {"data": data, "paper": p, "index": idx}
    return None


async def _persist_upload_as_pdf(file: UploadFile, dest_dir: Path, stem: str) -> Path:
    """
    将上传的 PDF/CAJ 保存到 dest_dir/<stem>.pdf；CAJ 会先转成 PDF。

    - .pdf：直接落盘为 <stem>.pdf。
    - .caj：先写 <stem>.caj 临时文件，转换为 <stem>.pdf 后删除临时文件。
      伪装成 PDF 的 CAJ（多数 CNKI 文件）只需拷贝；真正的二进制 CAJ 需
      caj2pdf，缺失时抛 HTTPException(400) 并附安装说明。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名缺失")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".pdf", ".caj"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 或 CAJ 文件")

    dest_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = dest_dir / f"{stem}.pdf"
    content = await file.read()

    if ext == ".caj":
        from src.tools.caj_parser import CAJParseError, convert_caj_to_pdf
        tmp_caj = dest_dir / f"{stem}.caj"
        try:
            with open(tmp_caj, "wb") as f:
                f.write(content)
            try:
                convert_caj_to_pdf(str(tmp_caj), str(pdf_path))
            except CAJParseError as e:
                raise HTTPException(status_code=400, detail=str(e))
        finally:
            tmp_caj.unlink(missing_ok=True)
    else:
        with open(pdf_path, "wb") as f:
            f.write(content)

    return pdf_path


@app.post("/api/papers/{topic}/{paper_id}/fetch-online")
async def fetch_paper_online(topic: str, paper_id: str):
    """
    在线搜索并下载论文 PDF，挂到已存在的知识库条目上。

    流程：用论文标题调用 MCP 检索 → 标题最佳匹配 → 调用下载接口（源站→OA→Unpaywall→Sci-Hub 回退）
    → 保存到 data/papers/{topic}/pdfs/{paper_id}.pdf → 更新条目 pdf_path。
    任一环节失败则返回 success=false 与可读错误说明，由前端展示给用户。
    """
    found = _find_paper_in_topic(topic, paper_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"论文 '{paper_id}' 不存在于分类 '{topic}'")

    paper = found["paper"]
    title = (paper.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="该论文缺少标题，无法在线搜索")

    pdfs_dir = DATA_DIR / "papers" / topic / paper_id
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    save_path = str(pdfs_dir)
    pdf_filename = f"{paper_id}.pdf"
    target_file = pdfs_dir / pdf_filename

    # 1. 搜索：用标题在所有源里查，取标题最相似的命中
    try:
        search_resp = await search_papers(SearchRequest(query=title, max_results=20, sources="all"))
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "message": f"在线搜索失败：{exc}"}

    candidates = search_resp.get("papers", []) if isinstance(search_resp, dict) else []
    if not candidates:
        return {"success": False, "message": "未在任意学术平台检索到该论文，请尝试手动导入本地 PDF。"}

    def _normalize(s: str) -> str:
        return "".join(c for c in (s or "").lower() if c.isalnum())

    norm_title = _normalize(title)

    def _score(p: Dict[str, Any]) -> int:
        pt = _normalize(p.get("title", ""))
        if not pt or not norm_title:
            return 0
        if pt == norm_title:
            return 1000
        if norm_title in pt or pt in norm_title:
            return 500
        # 公共子串长度作为弱相似度
        m, n = len(norm_title), len(pt)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        best = 0
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if norm_title[i - 1] == pt[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                    if dp[i][j] > best:
                        best = dp[i][j]
        return best

    best = max(candidates, key=_score)
    best_score = _score(best)
    if best_score < max(10, len(norm_title) // 3):
        return {
            "success": False,
            "message": f"检索结果与该论文标题不匹配（最佳命中：「{best.get('title','')}」），请尝试手动导入本地 PDF。",
        }

    # 2. 下载：复用已有的多级回退下载接口
    try:
        download_resp = await download_paper(DownloadRequest(
            source=best.get("source", "arxiv"),
            paper_id=best.get("paper_id") or paper_id,
            doi=best.get("doi"),
            title=best.get("title") or title,
            save_path=save_path,
            use_scihub=True,
        ))
    except HTTPException as he:
        return {"success": False, "message": f"下载失败：{he.detail}"}
    except Exception as exc:
        return {"success": False, "message": f"下载失败：{exc}"}

    if not (isinstance(download_resp, dict) and download_resp.get("success")):
        msg = (download_resp or {}).get("error") if isinstance(download_resp, dict) else "下载失败"
        detail = (download_resp or {}).get("details") if isinstance(download_resp, dict) else ""
        return {
            "success": False,
            "message": f"未能获取该论文 PDF（{msg}）。{('详情：' + detail) if detail else '可尝试手动导入本地 PDF。'}",
        }

    saved = download_resp.get("save_path")
    if not saved or not os.path.exists(saved):
        return {"success": False, "message": "下载完成但文件未落盘，请重试或手动导入。"}

    # 3. 归一化文件名到 {paper_id}.pdf，避免下载器命名的随机性
    if os.path.abspath(saved) != str(target_file):
        try:
            import shutil
            if target_file.exists():
                target_file.unlink()
            shutil.move(saved, str(target_file))
        except Exception as exc:
            logger.warning(f"rename downloaded pdf failed: {exc}")

    # 4. 更新条目 pdf_path
    data = found["data"]
    data["papers"][found["index"]]["pdf_path"] = f"data/papers/{topic}/{paper_id}/{pdf_filename}"
    _write_topic(topic, data)

    return {
        "success": True,
        "message": f"已通过「{best.get('source', '在线')}」获取并关联 PDF",
        "pdf_path": f"data/papers/{topic}/{paper_id}/{pdf_filename}",
        "matched_title": best.get("title", ""),
    }


@app.post("/api/papers/{topic}/{paper_id}/upload-pdf")
async def upload_pdf_attach(topic: str, paper_id: str, file: UploadFile = File(...)):
    """
    用户手动上传本地 PDF/CAJ，挂到已存在的知识库条目上（不新建条目）。
    """
    if not file.filename or not file.filename.lower().endswith((".pdf", ".caj")):
        raise HTTPException(status_code=400, detail="仅支持 PDF 或 CAJ 文件")

    found = _find_paper_in_topic(topic, paper_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"论文 '{paper_id}' 不存在于分类 '{topic}'")

    pdfs_dir = DATA_DIR / "papers" / topic / paper_id
    pdf_filename = f"{paper_id}.pdf"
    await _persist_upload_as_pdf(file, pdfs_dir, paper_id)

    data = found["data"]
    data["papers"][found["index"]]["pdf_path"] = f"data/papers/{topic}/{paper_id}/{pdf_filename}"
    _write_topic(topic, data)

    return {
        "success": True,
        "message": "文件已上传并关联",
        "pdf_path": f"data/papers/{topic}/{paper_id}/{pdf_filename}",
    }



async def add_paper(topic: str, request: AddPaperRequest):
    """添加论文到分类"""
    data = _read_topic(topic)
    if data is None:
        raise HTTPException(status_code=404, detail=f"分类 '{topic}' 不存在")

    paper = request.paper
    if not paper.get("paper_id"):
        paper["paper_id"] = hashlib.sha1(
            (paper.get("title", "") + str(datetime.now().timestamp())).encode()
        ).hexdigest()[:12]

    # 检查是否已存在
    existing_ids = {p.get("paper_id") for p in data.get("papers", [])}
    if paper["paper_id"] in existing_ids:
        raise HTTPException(status_code=409, detail=f"论文 '{paper['paper_id']}' 已存在")

    paper.setdefault("source", "manual")
    data.setdefault("papers", []).append(paper)
    _write_topic(topic, data)
    return {"success": True, "paper_id": paper["paper_id"], "total": len(data["papers"])}


@app.post("/api/papers/{topic}/import-pdf")
async def import_pdf(topic: str, file: UploadFile = File(...)):
    """上传 PDF/CAJ 并解析为论文条目"""
    if not file.filename or not file.filename.lower().endswith((".pdf", ".caj")):
        raise HTTPException(status_code=400, detail="仅支持 PDF 或 CAJ 文件")

    data = _read_topic(topic)
    if data is None:
        raise HTTPException(status_code=404, detail=f"分类 '{topic}' 不存在")

    # 保存上传的文件（CAJ 会转换为 PDF）
    paper_id = hashlib.sha1(file.filename.encode()).hexdigest()[:12]
    pdfs_dir = DATA_DIR / "papers" / topic / paper_id
    pdf_filename = f"{paper_id}.pdf"
    pdf_path = await _persist_upload_as_pdf(file, pdfs_dir, paper_id)

    # 提取文本并解析结构化信息
    try:
        from src.tools.text_extractor import PaperTextExtractor, TextExtractionError
        from src.tools.paper_info_extractor import PaperInfoExtractor

        full_text = PaperTextExtractor().extract(str(pdf_path))
        info = PaperInfoExtractor().extract(full_text)

        paper = {
            "paper_id": paper_id,
            "title": info.get("title") or os.path.splitext(file.filename)[0],
            "authors": "; ".join(info.get("authors") or []),
            "abstract": info.get("abstract") or "",
            "published_date": str(info.get("year") or ""),
            "pdf_url": "",
            "pdf_path": f"data/papers/{topic}/{paper_id}/{pdf_filename}",
            "keywords": info.get("keywords") or [topic.replace("_", " ")],
            "source": "import_pdf",
            "doi": info.get("doi"),
            "journal": info.get("journal"),
            "metadata_quality": info.get("metadata_quality", "partial"),
        }
    except TextExtractionError as e:
        logger.warning(f"文本提取失败: {e}")
        paper = {
            "paper_id": paper_id,
            "title": os.path.splitext(file.filename)[0],
            "authors": "",
            "abstract": "",
            "published_date": "",
            "pdf_url": "",
            "pdf_path": f"data/papers/{topic}/{paper_id}/{pdf_filename}",
            "keywords": [topic.replace("_", " ")],
            "source": "import_pdf",
        }
    except Exception as e:
        logger.warning(f"论文信息提取失败，使用文件名: {e}")
        paper = {
            "paper_id": paper_id,
            "title": os.path.splitext(file.filename)[0],
            "authors": "",
            "abstract": "",
            "published_date": "",
            "pdf_url": "",
            "pdf_path": f"data/papers/{topic}/{paper_id}/{pdf_filename}",
            "keywords": [topic.replace("_", " ")],
            "source": "import_pdf",
        }

    data.setdefault("papers", []).append(paper)
    _write_topic(topic, data)
    return {"success": True, "paper_id": paper_id, "title": paper["title"], "total": len(data["papers"])}


@app.post("/api/papers/{topic}/import-citation")
async def import_citation(topic: str, request: ImportCitationRequest):
    """解析引用格式文本（BibTeX/APA/等）为论文条目"""
    data = _read_topic(topic)
    if data is None:
        raise HTTPException(status_code=404, detail=f"分类 '{topic}' 不存在")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="引用文本不能为空")

    # 使用 LLM 解析引用文本
    try:
        from config.settings import get_llm_client, get_config
        from langchain_core.messages import HumanMessage, SystemMessage
        config = get_config()
        llm = get_llm_client(config)

        prompt = f"""请从以下学术引用文本中提取论文信息，返回 JSON 格式。

如果输入包含多条引用，请返回数组。字段包括：
- title: 论文标题
- authors: 作者列表（分号分隔）
- year: 发表年份
- journal: 期刊或会议名称（如有）
- doi: DOI（如有）
- abstract: 摘要（如引用中包含）

引用文本：
{text}

仅返回合法 JSON，不要添加 ```json 标记。如果单条引用返回单个对象，多条返回数组。"""

        response = llm.invoke([
            SystemMessage(content="你是学术引用解析专家。"),
            HumanMessage(content=prompt)
        ])

        import re
        match = re.search(r'\[[\s\S]*\]|\{[\s\S]*\}', response.content)
        if not match:
            raise HTTPException(status_code=500, detail="无法解析引用文本")

        parsed = json.loads(match.group())
        if not isinstance(parsed, list):
            parsed = [parsed]

        added = []
        for item in parsed:
            paper_id = hashlib.sha1(
                (item.get("title", "") + str(datetime.now().timestamp())).encode()
            ).hexdigest()[:12]
            paper = {
                "paper_id": paper_id,
                "title": item.get("title", ""),
                "authors": item.get("authors", ""),
                "abstract": item.get("abstract", ""),
                "published_date": item.get("year", ""),
                "doi": item.get("doi", ""),
                "journal": item.get("journal", ""),
                "pdf_url": f"https://doi.org/{item.get('doi', '')}" if item.get("doi") else "",
                "keywords": [topic.replace("_", " ")],
                "source": "import_citation",
            }
            data.setdefault("papers", []).append(paper)
            added.append(paper)

        _write_topic(topic, data)
        return {
            "success": True,
            "imported": len(added),
            "papers": [{"paper_id": p["paper_id"], "title": p["title"]} for p in added],
            "total": len(data["papers"]),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Citation import failed: {e}")
        raise HTTPException(status_code=500, detail=f"引用解析失败: {e}")


# ==================== Paper Search API ====================

def _get_searchers():
    """懒加载所有检索源搜索器，返回 {source_name: searcher} 字典。"""
    service_path = manager.get_service_path("paper-search")
    sys.path.insert(0, str(service_path.parent))

    from paper_search_mcp.academic_platforms.arxiv import ArxivSearcher
    from paper_search_mcp.academic_platforms.semantic import SemanticSearcher
    from paper_search_mcp.academic_platforms.biorxiv import BioRxivSearcher
    from paper_search_mcp.academic_platforms.medrxiv import MedRxivSearcher
    from paper_search_mcp.academic_platforms.google_scholar import GoogleScholarSearcher
    from paper_search_mcp.academic_platforms.iacr import IACRSearcher
    from paper_search_mcp.academic_platforms.crossref import CrossRefSearcher
    from paper_search_mcp.academic_platforms.openalex import OpenAlexSearcher
    from paper_search_mcp.academic_platforms.pmc import PMCSearcher
    from paper_search_mcp.academic_platforms.core import CORESearcher
    from paper_search_mcp.academic_platforms.europepmc import EuropePMCSearcher
    from paper_search_mcp.academic_platforms.dblp import DBLPSearcher
    from paper_search_mcp.academic_platforms.openaire import OpenAiresearcher
    from paper_search_mcp.academic_platforms.citeseerx import CiteSeerXSearcher
    from paper_search_mcp.academic_platforms.doaj import DOAJSearcher
    from paper_search_mcp.academic_platforms.base_search import BASESearcher
    from paper_search_mcp.academic_platforms.unpaywall import UnpaywallResolver, UnpaywallSearcher
    from paper_search_mcp.academic_platforms.zenodo import ZenodoSearcher
    from paper_search_mcp.academic_platforms.hal import HALSearcher
    from paper_search_mcp.academic_platforms.ssrn import SSRNSearcher
    from paper_search_mcp.academic_platforms.pubmed import PubMedSearcher

    unpaywall_resolver = UnpaywallResolver()

    _wfdata_app_key = os.getenv("WFDATA_APP_KEY", "")
    _wfdata_app_code = os.getenv("WFDATA_APP_CODE", "")
    if _wfdata_app_key and _wfdata_app_code:
        from paper_search_mcp.academic_platforms.wanfang import WanfangSearcher
        wanfang_searcher_inst = WanfangSearcher(app_key=_wfdata_app_key, app_code=_wfdata_app_code)
    else:
        wanfang_searcher_inst = None

    from paper_search_mcp.academic_platforms.cnki import CnkiSearcher
    if CnkiSearcher.is_enabled():
        cnki_searcher_inst = CnkiSearcher()
    else:
        cnki_searcher_inst = None

    return {
        "arxiv": ArxivSearcher(),
        "semantic": SemanticSearcher(),
        "biorxiv": BioRxivSearcher(),
        "medrxiv": MedRxivSearcher(),
        "google_scholar": GoogleScholarSearcher(),
        "iacr": IACRSearcher(),
        "crossref": CrossRefSearcher(),
        "openalex": OpenAlexSearcher(),
        "pmc": PMCSearcher(),
        "core": CORESearcher(),
        "europepmc": EuropePMCSearcher(),
        "dblp": DBLPSearcher(),
        "openaire": OpenAiresearcher(),
        "citeseerx": CiteSeerXSearcher(),
        "doaj": DOAJSearcher(),
        "base": BASESearcher(),
        "unpaywall": UnpaywallSearcher(resolver=unpaywall_resolver),
        "zenodo": ZenodoSearcher(),
        "hal": HALSearcher(),
        "ssrn": SSRNSearcher(),
        "pubmed": PubMedSearcher(),
        **({"wanfang": wanfang_searcher_inst} if wanfang_searcher_inst is not None else {}),
        **({"cnki": cnki_searcher_inst} if cnki_searcher_inst is not None else {}),
    }


# 懒加载全局搜索器实例
_searchers_cache: Optional[Dict[str, Any]] = None

def _get_all_searchers() -> Dict[str, Any]:
    global _searchers_cache
    if _searchers_cache is None:
        _searchers_cache = _get_searchers()
    return _searchers_cache


def _dedupe_papers(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 DOI+标题 去重，优先保留有引用数的版本。"""
    def _paper_key(p: Dict) -> str:
        doi = (p.get("doi") or "").strip().lower()
        if doi:
            return f"doi:{doi}"
        title = (p.get("title") or "").strip().lower()
        if title:
            return f"title:{title}"
        return f"id:{(p.get('paper_id') or '').strip().lower()}"

    seen: Dict[str, int] = {}
    result: List[Dict[str, Any]] = []
    for paper in papers:
        key = _paper_key(paper)
        citations = paper.get("citations", 0) or 0
        if key not in seen:
            seen[key] = len(result)
            result.append(paper)
        else:
            idx = seen[key]
            existing_citations = result[idx].get("citations", 0) or 0
            if existing_citations == 0 and citations > 0:
                result[idx] = paper
    return result


@app.post("/api/paper-search/search")
async def search_papers(request: SearchRequest):
    """
    搜索论文 — 并行查询所有检索源，容错+去重。

    支持的源：arxiv, semantic, biorxiv, medrxiv, google_scholar,
    iacr, crossref, openalex, pmc, core, europepmc, dblp, openaire,
    citeseerx, doaj, base, unpaywall, zenodo, hal, ssrn, pubmed
    """
    try:
        all_searchers = _get_all_searchers()
        sources_str = (request.sources or "all").strip().lower()

        if sources_str == "all":
            selected = list(all_searchers.keys())
        else:
            selected = [s.strip() for s in sources_str.split(",") if s.strip() in all_searchers]

        if not selected:
            return {"query": request.query, "sources_used": [], "total": 0, "papers": []}

        # 并行搜索，每个源独立容错。
        # 不同源响应速度差异大：arxiv/crossref/openalex 较快，google_scholar/
        # citeseerx/base/ssrn 较慢且易超时。这里按源分档超时，避免慢源拖垮整体。
        _SOURCE_TIMEOUTS = {
            "arxiv": 20, "crossref": 20, "openalex": 20, "dblp": 20,
            "semantic": 25, "doaj": 25, "europepmc": 25, "pmc": 25,
            "pubmed": 25, "hal": 25, "zenodo": 25,
            "biorxiv": 30, "medrxiv": 30, "core": 30, "openaire": 35,
            "unpaywall": 20, "iacr": 30, "chemrxiv": 30,
            "google_scholar": 35, "citeseerx": 35, "base": 35, "ssrn": 35,
            "ieee": 30, "acm": 30, "oaipmh": 35,
        }
        async def _search_one(source_name: str, searcher: Any) -> List[Dict]:
            timeout = _SOURCE_TIMEOUTS.get(source_name, 25)
            try:
                papers = await asyncio.wait_for(
                    asyncio.to_thread(searcher.search, request.query, request.max_results),
                    timeout=timeout,
                )
                result = [p.to_dict() for p in papers] if papers else []
                for p in result:
                    p.setdefault("source", source_name)
                return result
            except asyncio.TimeoutError:
                logger.warning(f"Search timeout for {source_name} (>{timeout}s)")
                return []
            except Exception as e:
                # 区分限流/网络/解析错误，便于排查
                msg = str(e).lower()
                if "429" in msg or "rate" in msg:
                    logger.warning(f"Search rate-limited for {source_name}: {e}")
                elif "timeout" in msg or "timed out" in msg:
                    logger.warning(f"Search network timeout for {source_name}: {e}")
                else:
                    logger.warning(f"Search failed for {source_name}: {e}")
                return []

        # 按预计响应速度排序：快源先返回，便于尽早达到 max_results 并取消慢源。
        # 慢源（google_scholar/citeseerx/base/ssrn，常 30s+ 超时）排在最后。
        _SPEED_ORDER = {
            "arxiv": 0, "crossref": 0, "openalex": 0, "dblp": 0, "unpaywall": 0,
            "semantic": 1, "doaj": 1, "europepmc": 1, "pmc": 1, "pubmed": 1,
            "hal": 1, "zenodo": 1,
            "biorxiv": 2, "medrxiv": 2, "core": 2, "iacr": 2,
            "openaire": 3, "google_scholar": 3, "citeseerx": 3, "base": 3, "ssrn": 3,
        }
        selected_sorted = sorted(selected, key=lambda s: _SPEED_ORDER.get(s, 2))

        tasks: Dict[str, asyncio.Task] = {
            name: asyncio.create_task(_search_one(name, all_searchers[name]))
            for name in selected_sorted
        }

        source_results: Dict[str, int] = {}
        errors: Dict[str, str] = {}
        merged: List[Dict[str, Any]] = []

        # 用 as_completed 按完成顺序收结果；一旦累计论文数 >= max_results，
        # 立即取消仍在跑的慢源任务，避免「已经够数了还在等 google_scholar 超时」。
        # 这直接解决了检索完成、进入写作阶段后日志仍刷 scholar 超时的问题。
        target = max(1, request.max_results)
        pending = set(tasks.values())
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    # 找到对应的 source name
                    name = next(n for n, t in tasks.items() if t is task)
                    try:
                        output = task.result()
                    except Exception as e:
                        errors[name] = str(e)
                        source_results[name] = 0
                        continue
                    source_results[name] = len(output)
                    merged.extend(output)

                # 已收集足够论文，取消尚未完成的慢源
                if len(merged) >= target and pending:
                    cancelled_names = [
                        n for n, t in tasks.items() if t in pending
                    ]
                    logger.info(
                        f"Search reached max_results ({len(merged)}/{target}), "
                        f"cancelling pending sources: {cancelled_names}"
                    )
                    for t in pending:
                        t.cancel()
                    # 标记被取消的源，前端/日志可识别
                    for n in cancelled_names:
                        source_results.setdefault(n, 0)
                    break
        finally:
            # 兜底：确保所有任务都已结束（已取消的会抛 CancelledError）
            leftover = [t for t in tasks.values() if not t.done()]
            for t in leftover:
                t.cancel()
            if leftover:
                # 静默吞掉 CancelledError，避免「Task was destroyed but it is pending」告警
                await asyncio.gather(*leftover, return_exceptions=True)

        deduped = _dedupe_papers(merged)

        return {
            "query": request.query,
            "sources_used": selected,
            "source_results": source_results,
            "errors": errors,
            "total": len(deduped),
            "papers": deduped[:request.max_results],
        }

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _download_from_url(pdf_url: str, save_path: str, filename_hint: str = "paper") -> Optional[str]:
    """从 URL 下载 PDF 文件。"""
    import httpx
    import re as _re
    if not pdf_url:
        return None
    os.makedirs(save_path, exist_ok=True)
    safe = _re.sub(r"[^a-zA-Z0-9._-]+", "_", filename_hint).strip("._")[:120] or "paper"
    output_path = os.path.join(save_path, f"{safe}.pdf")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(pdf_url)
        if response.status_code >= 400 or not response.content:
            return None
        content_type = (response.headers.get("content-type") or "").lower()
        is_pdf = "pdf" in content_type or response.content.startswith(b"%PDF") or pdf_url.lower().endswith(".pdf")
        if not is_pdf:
            return None
        with open(output_path, "wb") as f:
            f.write(response.content)
        return output_path
    except Exception as exc:
        logger.warning(f"Direct URL download failed for {pdf_url}: {exc}")
        return None


async def _try_repository_fallback(doi: str, title: str, save_path: str) -> Optional[str]:
    """尝试从 OA 仓储下载 PDF。"""
    all_searchers = _get_all_searchers()
    repo_searchers = [
        ("openaire", all_searchers.get("openaire")),
        ("core", all_searchers.get("core")),
        ("europepmc", all_searchers.get("europepmc")),
        ("pmc", all_searchers.get("pmc")),
    ]
    queries = [q for q in [doi, title] if q and q.strip()]
    if not queries:
        return None
    for repo_name, searcher in repo_searchers:
        if searcher is None:
            continue
        for query in queries:
            try:
                papers = await asyncio.to_thread(searcher.search, query, max_results=3)
            except Exception:
                continue
            if not papers:
                continue
            for paper in papers:
                pdf_url = str(getattr(paper, "pdf_url", "") or "").strip()
                if not pdf_url:
                    continue
                raw_id = str(getattr(paper, "paper_id", "") or query).strip()
                result = await _download_from_url(pdf_url, save_path, f"{repo_name}_{raw_id}")
                if result:
                    return result
    return None


@app.post("/api/paper-search/download")
async def download_paper(request: DownloadRequest):
    """
    下载论文 — 多级回退：源站 → OA 仓储 → Unpaywall → Sci-Hub
    """
    try:
        all_searchers = _get_all_searchers()
        source_name = request.source.strip().lower()
        save_path = request.save_path
        attempt_errors: List[str] = []

        # 确保下载目标目录存在。部分源站下载器会用含 '/' 的 paper_id（如 DOI
        # 10.64898/2026.05.18.725745）拼输出路径，形成嵌套子目录；若父目录未创建
        # 会抛 [Errno 2] No such file or directory。这里统一先把 save_path 建好，
        # 各下载器内部也应在写文件前对 dirname 再做一次 makedirs（见 arxiv 等）。
        if save_path:
            os.makedirs(save_path, exist_ok=True)

        # 1. 源站直接下载
        primary_downloaders = {
            "arxiv", "biorxiv", "medrxiv", "iacr", "semantic",
            "pmc", "core", "europepmc", "citeseerx", "doaj",
            "base", "zenodo", "hal", "ssrn", "openaire", "cnki",
        }
        if source_name in primary_downloaders and source_name in all_searchers:
            try:
                result = await asyncio.to_thread(
                    all_searchers[source_name].download_pdf, request.paper_id, save_path
                )
                if isinstance(result, str) and os.path.exists(result):
                    return {"success": True, "paper_id": request.paper_id, "save_path": result}
                if isinstance(result, str) and result:
                    attempt_errors.append(f"primary: {result}")
            except Exception as exc:
                attempt_errors.append(f"primary: {exc}")
                logger.warning(f"Primary download failed for {source_name}/{request.paper_id}: {exc}")
        else:
            attempt_errors.append(f"primary: unsupported source '{source_name}'")

        # 2. OA 仓储回退
        doi = (request.doi or "").strip()
        title = (request.title or "").strip()
        repo_result = await _try_repository_fallback(doi, title, save_path)
        if repo_result:
            return {"success": True, "paper_id": request.paper_id, "save_path": repo_result}
        attempt_errors.append("repositories: no PDF found")

        # 3. Unpaywall 回退
        if doi:
            try:
                from paper_search_mcp.academic_platforms.unpaywall import UnpaywallResolver
                resolver = UnpaywallResolver()
                oa_url = await asyncio.to_thread(resolver.resolve_best_pdf_url, doi)
                if oa_url:
                    unpaywall_result = await _download_from_url(oa_url, save_path, f"unpaywall_{doi}")
                    if unpaywall_result:
                        return {"success": True, "paper_id": request.paper_id, "save_path": unpaywall_result}
                attempt_errors.append("unpaywall: no OA URL found")
            except Exception as exc:
                attempt_errors.append(f"unpaywall: {exc}")

        # 4. Sci-Hub 回退
        if request.use_scihub:
            try:
                from paper_search_mcp.academic_platforms.sci_hub import SciHubFetcher
                identifier = doi or title or request.paper_id
                fetcher = SciHubFetcher(output_dir=save_path)
                result = await asyncio.to_thread(fetcher.download_pdf, identifier)
                if result:
                    return {"success": True, "paper_id": request.paper_id, "save_path": result}
                attempt_errors.append("scihub: download failed")
            except Exception as exc:
                attempt_errors.append(f"scihub: {exc}")

        return {
            "success": False,
            "paper_id": request.paper_id,
            "error": "Download failed after all fallbacks",
            "details": " | ".join(attempt_errors),
        }

    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/paper-search/read")
async def read_paper(source: str, paper_id: str):
    """
    读取论文内容 — 根据 source 选择对应平台的读取方法
    """
    try:
        all_searchers = _get_all_searchers()
        source_name = source.strip().lower()

        if source_name in all_searchers:
            searcher = all_searchers[source_name]
            if hasattr(searcher, "read_paper"):
                content = await asyncio.to_thread(searcher.read_paper, paper_id, "./downloads")
                return {"paper_id": paper_id, "source": source_name, "content": content}

        # 回退：尝试用 arxiv 读取
        if "arxiv" in all_searchers:
            content = await asyncio.to_thread(all_searchers["arxiv"].read_paper, paper_id, "./downloads")
            return {"paper_id": paper_id, "source": "arxiv (fallback)", "content": content}

        raise HTTPException(status_code=400, detail=f"Unsupported source: {source}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Read failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Chat / Session Management API ====================

@app.post("/api/chat/send", response_model=ChatResponse)
async def send_chat_message(request: ChatSendRequest):
    """
    发送聊天消息（核心端点）

    通过 Orchestrator 分析意图并处理：
    - 问候 → 直接回复
    - 知识查询 → 搜索知识库
    - 新研究主题 → 触发工作流
    """
    from src.agents.orchestrator import create_orchestrator
    from src.core.memory import memory_manager

    # 获取或创建会话
    session = memory_manager.get_or_create_session(request.session_id)

    # 获取会话上下文
    session_context = {
        "research_topics": session.context.research_topics,
    }

    # 获取会话历史消息（用于提供给模型上下文）
    message_history = session.messages if session.messages else []

    # 创建 Orchestrator 并处理消息
    orchestrator = create_orchestrator()

    # 处理消息（传递历史记录）
    result = orchestrator.process_message(
        user_message=request.message,
        session_id=session.session_id,
        session_context=session_context,
        message_history=message_history,
    )

    # 保存用户消息到会话
    memory_manager.add_message(
        session_id=session.session_id,
        role="user",
        content=request.message,
    )

    # 如果需要触发工作流
    task_id = None
    if result.get("requires_workflow"):
        # 启动工作流
        import uuid
        task_id = str(uuid.uuid4())
        research_topic = result.get("research_topic", request.message)

        workflow_tasks[task_id] = {
            "status": "running",
            "query": research_topic,
            "year_range": result.get("year_range"),
            "min_count": result.get("min_count"),
            "phase": "init",
            "progress": 0.0,
            "details": {
                "message": "正在初始化...",
                "papers_found": 0,
                "papers_to_download": 0,
                "papers_downloading": 0,
                "papers_downloaded": [],
                "current_downloading": "",
                "papers_reading": 0,
                "total_papers": 0,
            },
        }

        # 在后台运行工作流
        def run_workflow_task():
            try:
                # 更新状态：开始检索
                workflow_tasks[task_id]["phase"] = "retrieval"
                workflow_tasks[task_id]["progress"] = 0.05
                workflow_tasks[task_id]["details"]["message"] = "论文检索中..."

                from src.core.workflow import run_workflow
                # 透传用户检索约束（来自 orchestrator）
                yr = result.get("year_range")
                mc = result.get("min_count")
                wf_kwargs = {
                    "auto_approve": False,
                    "progress_callback": make_workflow_progress_callback(task_id),
                }
                if isinstance(yr, (list, tuple)) and len(yr) == 2:
                    wf_kwargs["year_range"] = tuple(yr)
                if isinstance(mc, int) and mc > 0:
                    wf_kwargs["min_count"] = mc
                workflow_result = run_workflow(
                    user_query=research_topic,
                    **wf_kwargs,
                )

                # 更新会话研究上下文
                memory_manager.update_research_context(
                    session_id=session.session_id,
                    topic=research_topic,
                    result=workflow_result,
                )

                # 更新状态：完成
                workflow_tasks[task_id]["status"] = "completed"
                workflow_tasks[task_id]["phase"] = "completed"
                workflow_tasks[task_id]["progress"] = 1.0
                workflow_tasks[task_id]["details"]["message"] = "研究完成！"
                workflow_tasks[task_id]["result"] = {
                    "topic": research_topic,
                    "outline": workflow_result.get("outline", ""),
                    "final_report": workflow_result.get("final_review", ""),
                }

            except Exception as e:
                logger.error(f"Workflow task {task_id} failed: {e}")
                workflow_tasks[task_id]["status"] = "failed"
                workflow_tasks[task_id]["error"] = str(e)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_workflow_task)

    # 保存助手回复到会话
    memory_manager.add_message(
        session_id=session.session_id,
        role="assistant",
        content=result.get("response", ""),
        metadata={"action": result.get("action"), "intent": result.get("intent")},
    )

    return ChatResponse(
        session_id=session.session_id,
        response=result.get("response", ""),
        action=result.get("action", "unknown"),
        intent=result.get("intent"),
        task_id=task_id,
        research_topic=result.get("research_topic"),
    )


_READING_MODE_KEYWORDS = {
    "snap": ["速览", "速览模式"],
    "lens": ["深度精读", "精读"],
    "sphere": ["研究全景", "全景"],
}
_READING_MODE_LABELS = {
    "snap": "速览",
    "lens": "深度精读",
    "sphere": "研究全景",
}


def _detect_paper_reading_request(message: str) -> Optional[tuple]:
    """
    识别「用X模式阅读这篇论文《title》」类消息。

    命中条件：同时包含「阅读」「论文」、某个模式关键词、以及《》包裹的标题。
    返回 (mode, title) 或 None。用关键词而非 LLM 意图分析，是为了在聊天入口
    精准短路到论文精读工作流，避免被误判为综述检索。
    """
    if not message:
        return None
    if "阅读" not in message or "论文" not in message:
        return None
    if "《" not in message or "》" not in message:
        return None

    mode = None
    for m, kws in _READING_MODE_KEYWORDS.items():
        if any(kw in message for kw in kws):
            mode = m
            break
    if mode is None:
        return None

    title = message.split("《", 1)[1].split("》", 1)[0].strip()
    if not title:
        return None
    return mode, title


def _find_paper_pdf_by_title(title: str) -> Optional[Dict[str, Any]]:
    """遍历知识库所有分类与 _uploads，按标题精确匹配（忽略大小写/空白）查找论文。"""
    def _norm(s: str) -> str:
        return "".join(c for c in (s or "").lower() if c.isalnum())

    norm = _norm(title)
    if not norm:
        return None
    papers_dir = DATA_DIR / "papers"
    if not papers_dir.exists():
        return None
    # 1) 各分类下的清单 JSON
    for topic_dir in papers_dir.iterdir():
        if not topic_dir.is_dir() or topic_dir.name.startswith("_"):
            continue
        for json_file in topic_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for p in data.get("papers", []):
                if _norm(p.get("title", "")) == norm:
                    return p
    # 2) _uploads 下每篇论文的 metadata.json
    uploads_dir = DATA_DIR / "papers" / "_uploads"
    if uploads_dir.is_dir():
        for meta_file in uploads_dir.glob("*/metadata.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            if _norm(meta.get("title", "")) == norm:
                paper_id = meta_file.parent.name
                return {
                    "paper_id": paper_id,
                    "title": meta.get("title", ""),
                    "authors": meta.get("authors", []),
                    "pdf_path": f"data/papers/_uploads/{paper_id}/original.pdf",
                }
    return None


async def _stream_paper_reading_in_chat(session_id: str, mode: str, title: str):
    """在聊天会话里执行论文精读，按 ChatView 兼容的 SSE 协议真实流式回推 markdown。"""
    from src.core.memory import memory_manager
    from src.agents.paper_reading import analyze_paper_stream

    paper = _find_paper_pdf_by_title(title)
    if paper is None:
        msg = f"未在知识库中找到标题为「{title}」的论文。请先在知识库中添加该论文后再试。"
        yield f"data: {json.dumps({'type': 'token', 'data': {'token': msg}})}\n\n"
        memory_manager.add_message(session_id=session_id, role="assistant", content=msg)
        yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
        return

    pdf_path_rel = paper.get("pdf_path")
    if not pdf_path_rel:
        msg = (f"论文「{title}」尚未关联 PDF，无法精读。"
               "请先在知识库中点击「获取论文」在线搜索或导入本地 PDF。")
        yield f"data: {json.dumps({'type': 'token', 'data': {'token': msg}})}\n\n"
        memory_manager.add_message(session_id=session_id, role="assistant", content=msg)
        yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
        return

    pdf_abs = PROJECT_ROOT / pdf_path_rel
    if not pdf_abs.exists():
        msg = f"论文「{title}」关联的 PDF 文件不存在（{pdf_path_rel}），请重新获取或导入。"
        yield f"data: {json.dumps({'type': 'token', 'data': {'token': msg}})}\n\n"
        memory_manager.add_message(session_id=session_id, role="assistant", content=msg)
        yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
        return

    paper_id = paper.get("paper_id") or hashlib.sha1(title.encode()).hexdigest()[:12]

    # 真实流式：在线程池跑 analyze_paper_stream 生成器，用 asyncio.Queue 桥接到 SSE
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()

    def _producer():
        try:
            for event in analyze_paper_stream(str(pdf_abs), paper_id, mode, "zh", use_cache=True):
                asyncio.run_coroutine_threadsafe(queue.put(event), loop).result()
        except Exception as exc:
            logger.error(f"_stream_paper_reading_in_chat producer error: {exc}", exc_info=True)
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "error", "message": str(exc)}), loop
            ).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(SENTINEL), loop).result()

    loop.run_in_executor(None, _producer)

    full_parts: list = []
    from_cache = False
    had_error = False
    while True:
        item = await queue.get()
        if item is SENTINEL:
            break
        etype = item.get("type")
        if etype == "token":
            text = item.get("text", "")
            if text:
                full_parts.append(text)
                yield f"data: {json.dumps({'type': 'token', 'data': {'token': text}})}\n\n"
        elif etype == "progress":
            # 聊天界面不展示进度条，吞掉即可
            continue
        elif etype == "cache_hit":
            result = item.get("result", {})
            md = result.get("markdown", "") or ""
            full_parts.append(md)
            from_cache = True
            # 缓存命中也走 token 推送，让前端增量渲染
            if md:
                yield f"data: {json.dumps({'type': 'token', 'data': {'token': md}})}\n\n"
            break
        elif etype == "complete":
            result = item.get("result", {})
            # 若流式 token 已全部推送，这里不再重复；但若没收到 token（降级 invoke），补推
            if not full_parts:
                md = result.get("markdown", "") or ""
                if md:
                    full_parts.append(md)
                    yield f"data: {json.dumps({'type': 'token', 'data': {'token': md}})}\n\n"
            from_cache = bool(result.get("from_cache", False))
            break
        elif etype == "error":
            had_error = True
            msg = f"论文精读失败：{item.get('message', '未知错误')}"
            full_parts.append(msg)
            yield f"data: {json.dumps({'type': 'token', 'data': {'token': msg}})}\n\n"
            break

    markdown = "".join(full_parts) or "（精读结果为空）"
    if from_cache:
        note = "\n\n_（本次结果来自历史缓存，秒级返回）_"
        yield f"data: {json.dumps({'type': 'token', 'data': {'token': note}})}\n\n"
        markdown += note

    memory_manager.add_message(session_id=session_id, role="assistant", content=markdown)
    yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"


@app.post("/api/chat/stream")
async def stream_chat_message(request: ChatSendRequest):
    """
    流式聊天消息端点

    通过 SSE 流式推送：
    - 响应内容（逐段或逐字）
    - 工作流状态更新
    """
    from src.agents.orchestrator import create_orchestrator
    from src.core.memory import memory_manager

    async def event_generator():
        # 1. 发送 "thinking" 状态
        yield f"data: {json.dumps({'type': 'thinking', 'data': {'message': 'AI 正在思考...'}})}\n\n"

        # 获取或创建会话
        session = memory_manager.get_or_create_session(request.session_id)

        # ===== 论文精读快捷路由 =====
        # 当消息形如「用速览模式阅读这篇论文《xxx》」时，直接走论文精读工作流，
        # 不经过 Orchestrator 的 LLM 意图分析——否则会被误判为 NEW_RESEARCH
        # 进而触发综述检索工作流。
        pr = _detect_paper_reading_request(request.message)
        if pr is not None:
            mode, title = pr
            # 保存用户消息
            memory_manager.add_message(
                session_id=session.session_id, role="user", content=request.message,
            )

            yield f"data: {json.dumps({'type': 'response_start', 'data': {'content': ''}})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'data': {'token': f'好的，正在用{_READING_MODE_LABELS.get(mode, mode)}模式阅读《{title}》...\n\n'}})}\n\n"

            async for chunk in _stream_paper_reading_in_chat(session.session_id, mode, title):
                yield chunk
            return

        # ===== AI 报告编辑流程 =====
        # 当 session 已设置 target_file_path，或用户首条消息含 <report> 全文（自动初始化）
        # 时，走专用编辑流程，绕过 Orchestrator 的意图分析（否则会被误判为 NEW_RESEARCH）。
        init_error = None
        if session.session_id not in edit_target_files:
            init_error = _try_init_edit_from_message(session.session_id, request.message)
        if session.session_id in edit_target_files:
            target_path_str = edit_target_files[session.session_id]
            working = working_copies.get(session.session_id, "")

            # 保存用户消息
            memory_manager.add_message(
                session_id=session.session_id, role="user", content=request.message,
            )

            yield f"data: {json.dumps({'type': 'response_start', 'data': {'content': ''}})}\n\n"

            if init_error:
                # 初始化失败（如文件名缺失/校验失败）：告知用户，清理状态
                err_msg = f"无法进入编辑模式：{init_error}"
                yield f"data: {json.dumps({'type': 'token', 'data': {'token': err_msg}})}\n\n"
                yield f"data: {json.dumps({'type': 'edit_warning', 'data': {'message': err_msg}})}\n\n"
                memory_manager.add_message(
                    session_id=session.session_id, role="assistant", content=err_msg,
                    metadata={"action": "edit_init_failed"},
                )
                _clear_edit_state(session.session_id)
                yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
                return

            # 完成意图：写回原文件并结束编辑会话
            if _is_completion_message(request.message) and not edit_citation_state.get(session.session_id):
                completion_msg = "好的，已将修改写回原文件。"
                target_path = Path(target_path_str)
                file_written_payload: Dict[str, Any] = {"filename": target_path.name}
                try:
                    tmp = target_path.with_suffix(target_path.suffix + ".tmp")
                    tmp.write_text(working, encoding="utf-8")
                    os.replace(tmp, target_path)
                    file_written_payload["size"] = target_path.stat().st_size
                except Exception as e:
                    file_written_payload["error"] = str(e)
                    logger.error(f"写回报告失败: {e}", exc_info=True)

                yield f"data: {json.dumps({'type': 'token', 'data': {'token': completion_msg}})}\n\n"
                yield f"data: {json.dumps({'type': 'file_written', 'data': file_written_payload})}\n\n"

                memory_manager.add_message(
                    session_id=session.session_id, role="assistant", content=completion_msg,
                    metadata={"action": "edit_complete", "target_file": target_path.name},
                )
                _clear_edit_state(session.session_id)
                yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
                return

            # 普通编辑轮次：调用 LLM（流式），系统提示为编辑专用
            # create_orchestrator 已在 event_generator 顶部导入，不要在此重复 import——
            # 否则 Python 会把该名视为整个函数的局部变量，导致非编辑路径的
            # `orchestrator = create_orchestrator()` 抛 UnboundLocalError。
            edit_orchestrator = create_orchestrator()
            edit_orchestrator.system_prompt = EDIT_SYSTEM_PROMPT

            from langchain_core.messages import SystemMessage, HumanMessage

            collected: list = []
            context_content = f"当前报告工作副本（最新版本）：\n\n<report>\n{working}\n</report>"

            # KB 感知预处理：识别引用意图，查 KB，注入候选/检索询问
            from src.core.kb_context import (
                build_kb_directory_summary,
                search_papers_for_citation,
                format_citation_candidates,
            )
            kb_summary = build_kb_directory_summary()

            citation_directive = ""
            state = edit_citation_state.get(session.session_id, {})

            # 分支 0：candidates_listed + 确认 → 补节 + 角标
            if (state.get("phase") == "candidates_listed"
                    and _is_confirmation(request.message)):
                from src.core.kb_context import format_bibliography_gbt7714
                candidates = state["candidates"]
                bib = format_bibliography_gbt7714(candidates)
                citation_directive = (
                    "已确认使用以下参考文献：\n\n"
                    f"{bib}\n\n"
                    "指令：输出一个 EDIT SECTION 替换「## 参考文献」节"
                    "（若不存在则新增到文末）；并输出 0~N 个 EDIT SECTION 在正文相关章节"
                    "插入 [n] 角标，n 对应清单序号。不要编造清单外的引用。"
                )
                edit_citation_state.pop(session.session_id, None)

            # 分支 1：awaiting_search_confirm + 确认 → 同流检索
            elif (state.get("phase") == "awaiting_search_confirm"
                    and _is_confirmation(request.message)):
                pending_topic = state["pending_topic"]
                pending_count = state["pending_count"]
                # 同流跑检索（不生成综述），保留编辑态
                # run_workflow 是同步阻塞调用（10-60s），必须放到 executor 线程避免卡死 SSE 连接
                yield f"data: {json.dumps({'type': 'edit_search_start', 'data': {'topic': pending_topic}})}\n\n"

                search_queue: asyncio.Queue = asyncio.Queue()

                def _run_search_workflow():
                    try:
                        from src.core.workflow import run_workflow
                        run_workflow(
                            user_query=pending_topic,
                            auto_approve=True,
                            workflow_mode="search",
                        )
                        asyncio.run_coroutine_threadsafe(
                            search_queue.put(("done", None)), loop
                        ).result()
                    except Exception as exc:
                        asyncio.run_coroutine_threadsafe(
                            search_queue.put(("error", str(exc))), loop
                        ).result()

                loop.run_in_executor(None, _run_search_workflow)

                search_result = await search_queue.get()
                if search_result[0] == "error":
                    e = search_result[1]
                    logger.error(f"同流检索失败: {e}", exc_info=True)
                    edit_citation_state.pop(session.session_id, None)
                    err = f"检索失败：{e}。已恢复编辑模式，可稍后重试或手动检索。"
                    yield f"data: {json.dumps({'type': 'token', 'data': {'token': err}})}\n\n"
                    yield f"data: {json.dumps({'type': 'edit_warning', 'data': {'message': err}})}\n\n"
                    memory_manager.add_message(
                        session_id=session.session_id, role="assistant", content=err,
                        metadata={"action": "edit_search_failed"},
                    )
                    yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
                    return

                # 检索完成，重新查 KB
                new_candidates = search_papers_for_citation(pending_topic, pending_count)
                if new_candidates:
                    edit_citation_state[session.session_id] = {
                        "phase": "candidates_listed",
                        "candidates": new_candidates,
                        "pending_topic": pending_topic,
                        "pending_count": pending_count,
                    }
                    citation_directive = (
                        f"检索完成，知识库中已新增 {len(new_candidates)} 篇相关论文：\n\n"
                        f"{format_citation_candidates(new_candidates)}\n\n"
                        "指令：列出上述论文清单，询问用户「是否使用这些论文作为参考文献？」。"
                        "本轮不要输出 EDIT SECTION，只做确认。"
                    )
                else:
                    edit_citation_state.pop(session.session_id, None)
                    citation_directive = (
                        f"检索完成，但知识库中仍未找到与「{pending_topic}」相关的论文。"
                        "指令：告知用户，建议换个主题或稍后重试。本轮不要输出 EDIT SECTION。"
                    )

            # 分支 2：新引用意图 → 查 KB
            else:
                intent = _detect_citation_intent(request.message)
                if intent and state.get("phase") not in ("confirmed",):
                    topic = _resolve_topic(intent, working,
                                           {"research_topics": session.context.research_topics})
                    candidates = search_papers_for_citation(topic, intent.count)
                    if candidates:
                        edit_citation_state[session.session_id] = {
                            "phase": "candidates_listed",
                            "candidates": candidates,
                            "pending_topic": topic,
                            "pending_count": intent.count,
                        }
                        citation_directive = (
                            "知识库中找到以下相关论文：\n\n"
                            f"{format_citation_candidates(candidates)}\n\n"
                            "指令：列出上述论文清单，询问用户「是否使用这些论文作为参考文献？」。"
                            "本轮不要输出 EDIT SECTION，只做确认。"
                        )
                    else:
                        edit_citation_state[session.session_id] = {
                            "phase": "awaiting_search_confirm",
                            "pending_topic": topic,
                            "pending_count": intent.count,
                        }
                        citation_directive = (
                            f"知识库中未找到与「{topic}」相关的论文。"
                            "指令：告知用户未找到，并询问「是否检索并下载相关论文？检索完成后将自动继续编辑。」。"
                            "本轮不要输出 EDIT SECTION。"
                        )

            chat_messages = [
                SystemMessage(content=EDIT_SYSTEM_PROMPT),
                SystemMessage(content=context_content),
            ]
            if kb_summary:
                chat_messages.append(SystemMessage(content=f"系统知识库概况：{kb_summary}"))
            if citation_directive:
                chat_messages.append(SystemMessage(content=citation_directive))
            chat_messages.append(HumanMessage(content=request.message))

            loop = asyncio.get_event_loop()
            token_queue: asyncio.Queue = asyncio.Queue()

            def _run_edit_llm():
                try:
                    for chunk in edit_orchestrator.llm.stream(chat_messages):
                        content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                        if content:
                            asyncio.run_coroutine_threadsafe(
                                token_queue.put(("token", content)), loop
                            ).result()
                    asyncio.run_coroutine_threadsafe(
                        token_queue.put(("done", None)), loop
                    ).result()
                except Exception as exc:
                    asyncio.run_coroutine_threadsafe(
                        token_queue.put(("error", str(exc))), loop
                    ).result()

            loop.run_in_executor(None, _run_edit_llm)

            while True:
                item = await token_queue.get()
                if item[0] == "token":
                    collected.append(item[1])
                    yield f"data: {json.dumps({'type': 'token', 'data': {'token': item[1]}})}\n\n"
                elif item[0] == "done":
                    break
                elif item[0] == "error":
                    err = f"（编辑失败：{item[1]}）"
                    yield f"data: {json.dumps({'type': 'token', 'data': {'token': err}})}\n\n"
                    break

            full_reply = "".join(collected) or "（助手未返回内容）"

            # 解析 EDIT SECTION 并应用到工作副本
            new_working, warnings = _apply_edit_sections(working, full_reply)
            if new_working != working:
                working_copies[session.session_id] = new_working
            for w in warnings:
                yield f"data: {json.dumps({'type': 'edit_warning', 'data': {'message': w}})}\n\n"

            memory_manager.add_message(
                session_id=session.session_id, role="assistant", content=full_reply,
                metadata={"action": "edit_round"},
            )
            yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
            return

        # 获取会话上下文
        session_context = {
            "research_topics": session.context.research_topics,
        }

        # 获取会话历史消息
        message_history = session.messages if session.messages else []

        # 创建 Orchestrator 并处理消息
        orchestrator = create_orchestrator()

        # 处理消息
        result = orchestrator.process_message(
            user_message=request.message,
            session_id=session.session_id,
            session_context=session_context,
            message_history=message_history,
        )

        # 保存用户消息
        memory_manager.add_message(
            session_id=session.session_id,
            role="user",
            content=request.message,
        )

        # 获取响应内容
        response_text = result.get("response", "")
        action = result.get("action", "unknown")

        # ===== 子任务短路：生成摘要/引言/结论，直连生成器，真实流式 =====
        if action in ("generate_abstract", "generate_introduction", "generate_conclusion"):
            from src.agents.writing_tasks import resolve_writing_context, generate_partial

            section_map = {
                "generate_abstract": "abstract",
                "generate_introduction": "introduction",
                "generate_conclusion": "conclusion",
            }
            section = section_map[action]

            yield f"data: {json.dumps({'type': 'response_start', 'data': {'content': response_text}})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'data': {'token': response_text + '\n\n'}})}\n\n"

            try:
                ctx = resolve_writing_context(session_id=session.session_id)
            except ValueError as e:
                err_msg = f"无法生成：{e}"
                yield f"data: {json.dumps({'type': 'token', 'data': {'token': err_msg}})}\n\n"
                memory_manager.add_message(
                    session_id=session.session_id, role="assistant", content=response_text + err_msg,
                )
                yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
                return

            # 真实流式：generate_partial 在线程池跑，on_token 回调把 chunk 经队列推给 SSE
            loop = asyncio.get_event_loop()
            token_queue: asyncio.Queue = asyncio.Queue()
            DONE_SENTINEL = object()

            def _run_partial():
                def _on_token(text):
                    asyncio.run_coroutine_threadsafe(
                        token_queue.put(("token", text)), loop
                    ).result()
                try:
                    full = generate_partial(section, ctx, on_token=_on_token)
                    asyncio.run_coroutine_threadsafe(
                        token_queue.put(("done", full)), loop
                    ).result()
                except Exception as exc:
                    logger.error(f"generate_partial failed: {exc}", exc_info=True)
                    asyncio.run_coroutine_threadsafe(
                        token_queue.put(("error", str(exc))), loop
                    ).result()

            loop.run_in_executor(None, _run_partial)

            full_parts: list = []
            while True:
                item = await token_queue.get()
                if item[0] == "token":
                    text = item[1]
                    full_parts.append(text)
                    yield f"data: {json.dumps({'type': 'token', 'data': {'token': text}})}\n\n"
                elif item[0] == "done":
                    full_text = item[1]
                    # 流式 token 可能因 provider 中途聚合不全，用 done 的完整文本兜底
                    if not full_parts:
                        full_parts.append(full_text)
                        yield f"data: {json.dumps({'type': 'token', 'data': {'token': full_text}})}\n\n"
                    break
                elif item[0] == "error":
                    err_msg = f"生成失败：{item[1]}"
                    yield f"data: {json.dumps({'type': 'token', 'data': {'token': err_msg}})}\n\n"
                    full_parts.append(err_msg)
                    break

            final_content = response_text + "\n\n" + "".join(full_parts)
            memory_manager.add_message(
                session_id=session.session_id, role="assistant", content=final_content,
                metadata={"action": action, "intent": result.get("intent")},
            )
            yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"
            return

        # 2. 流式推送响应内容
        if action == "start_workflow" and result.get("requires_workflow"):
            # 工作流模式
            yield f"data: {json.dumps({'type': 'response_start', 'data': {'content': response_text}})}\n\n"

            # 触发工作流
            import uuid
            task_id = str(uuid.uuid4())
            research_topic = result.get("research_topic", request.message)
            # 工作流模式：full / search_only / search_download（来自意图识别）
            workflow_mode = (result.get("workflow_mode") or "full").strip().lower()

            # 检索审批门控：先只做查询分析+策略生成，把检索条件回送给用户确认，
            # 用户接受后才真正执行检索与后续工作流（见 /api/workflow/approve-retrieval）
            from src.core.workflow import prepare_retrieval

            try:
                # 透传用户检索约束（来自 orchestrator result）
                _yr2 = result.get("year_range")
                _mc2 = result.get("min_count")
                loop = asyncio.get_event_loop()
                conditions = await loop.run_in_executor(
                    None,
                    lambda: prepare_retrieval(
                        research_topic,
                        year_range=tuple(_yr2) if isinstance(_yr2, (list, tuple)) and len(_yr2) == 2 else None,
                        min_count=_mc2 if isinstance(_mc2, int) and _mc2 > 0 else None,
                    ),
                )
            except Exception as e:
                logger.error(f"prepare_retrieval failed: {e}")
                conditions = {
                    "user_query": research_topic, "normalized_topic": research_topic,
                    "key_concepts": [], "research_direction": "exploratory",
                    "background_context": "", "boolean_query": f'"{research_topic}"',
                    "keywords": [research_topic], "categories": [], "date_range": ["", ""],
                    "max_results": 20, "rationale": f"prepare failed: {e}",
                }

            workflow_tasks[task_id] = {
                "status": "awaiting_approval",
                "query": research_topic,
                "year_range": result.get("year_range"),
                "min_count": result.get("min_count"),
                "phase": "approval",
                "progress": 0.0,
                "session_id": session.session_id,
                "workflow_mode": workflow_mode,
                "conditions": conditions,
                "details": {"message": "等待用户确认检索条件...", "papers_found": 0,
                            "papers_to_download": 0, "papers_downloading": 0,
                            "papers_downloaded": [], "current_downloading": "",
                            "papers_reading": 0, "total_papers": 0},
            }

            # 保存助手回复
            memory_manager.add_message(
                session_id=session.session_id,
                role="assistant",
                content=response_text,
                metadata={"action": action, "intent": result.get("intent"), "task_id": task_id},
            )

            # 把检索条件作为审批请求事件推给前端，等待用户接受/拒绝
            # 随事件附带 workflow_mode，供前端展示模式相关文案
            yield f"data: {json.dumps({'type': 'retrieval_approval_request', 'data': {'task_id': task_id, 'conditions': conditions, 'workflow_mode': workflow_mode, 'message': '请确认以下检索条件'}})}\n\n"
            yield f"data: {json.dumps({'type': 'response_done', 'data': {'task_id': task_id}})}\n\n"

        else:
            # 直接回复模式 - 流式推送响应
            # 将响应分段推送（每20个字符一段，模拟流式）
            chunk_size = 20
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i:i+chunk_size]
                yield f"data: {json.dumps({'type': 'token', 'data': {'token': chunk}})}\n\n"
                await asyncio.sleep(0.05)  # 模拟延迟

            # 保存助手回复
            memory_manager.add_message(
                session_id=session.session_id,
                role="assistant",
                content=response_text,
                metadata={"action": action, "intent": result.get("intent")},
            )

            yield f"data: {json.dumps({'type': 'response_done', 'data': {}})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/chat/sessions")
async def list_chat_sessions():
    """列出所有会话"""
    from src.core.memory import memory_manager
    return {"sessions": memory_manager.list_sessions()}


@app.get("/api/chat/history/{session_id}")
async def get_chat_history(session_id: str):
    """获取会话历史消息"""
    from src.core.memory import memory_manager
    session = memory_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "message_count": len(session.messages),
        "context_tokens": session.context_tokens,
        "research_topics": session.context.research_topics,
        "messages": session.messages,
    }


@app.delete("/api/chat/session/{session_id}")
async def delete_chat_session(session_id: str):
    """删除会话"""
    from src.core.memory import memory_manager
    success = memory_manager.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    _clear_edit_state(session_id)
    return {"message": "Session deleted", "session_id": session_id}


class SaveCardRequest(BaseModel):
    card_type: str  # "outline" | "writing" | "review"
    payload: Dict[str, Any]


@app.post("/api/chat/session/{session_id}/card")
async def save_session_card(session_id: str, req: SaveCardRequest):
    """把卡片快照写入会话最后一条 assistant 消息的 metadata，供刷新后还原。"""
    from src.core.memory import memory_manager
    key_map = {"outline": "outline_card", "writing": "writing_card", "review": "review_card"}
    key = key_map.get(req.card_type)
    if not key:
        raise HTTPException(status_code=400, detail=f"unknown card_type: {req.card_type}")
    ok = memory_manager.update_last_assistant_message_metadata(session_id, {key: req.payload})
    if not ok:
        raise HTTPException(status_code=404, detail="no assistant message found")
    return {"ok": True}


# ==================== Paper Reading API ====================

from enum import Enum

class ReadingMode(str, Enum):
    SNAP = "snap"       # 速览模式
    LENS = "lens"       # 深度精读模式
    SPHERE = "sphere"   # 研究全景模式
    QA = "qa"          # 问答模式

class PaperReadingRequest(BaseModel):
    paper_id: str
    mode: ReadingMode = ReadingMode.SNAP
    language: str = "zh"
    model: str = "default"
    pdf_path: Optional[str] = None  # 可选的PDF路径（知识库已有论文）

# 论文精读任务存储
paper_reading_tasks: Dict[str, Dict[str, Any]] = {}

# 论文阅读页面上传 PDF 的统一落盘目录（无类别的上传论文）
UPLOADS_DIR = DATA_DIR / "papers" / "_uploads"


def _find_paper_dir_by_id(paper_id: str) -> Optional[Path]:
    """按 paper_id 查找论文目录：先查 _uploads，再遍历各类别目录。

    用于 get_paperReading / get_paperReading_pdf 等仅靠 paper_id 定位的接口。
    """
    uploads_candidate = UPLOADS_DIR / paper_id
    if uploads_candidate.is_dir():
        return uploads_candidate
    papers_dir = DATA_DIR / "papers"
    if not papers_dir.exists():
        return None
    for topic_dir in papers_dir.iterdir():
        if not topic_dir.is_dir() or topic_dir.name.startswith("_"):
            continue
        cand = topic_dir / paper_id
        if cand.is_dir():
            return cand
    return None


def compute_file_hash(file_content: bytes) -> str:
    """计算文件SHA1哈希作为paper_id"""
    return hashlib.sha1(file_content).hexdigest()

@app.post("/api/paper-reading/upload")
async def upload_paperReading(file: UploadFile = File(...)):
    """
    上传 PDF/CAJ 论文进行精读。

    落盘到 data/papers/_uploads/<paper_id>/original.pdf，精读结果文档
    （snap/lens/sphere_*.json）后续会写到同一目录，与 PDF 共处。
    """
    # 验证文件类型
    if not file.filename or not file.filename.lower().endswith((".pdf", ".caj")):
        raise HTTPException(status_code=400, detail="仅支持 PDF 或 CAJ 文件")

    # 读取文件内容并计算哈希（基于原始字节，CAJ 与转换后的 PDF 共享同一目录）
    content = await file.read()
    paper_id = compute_file_hash(content)

    # 创建论文目录
    paper_dir = UPLOADS_DIR / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    # 保存文件（CAJ 转换为 PDF 后存为 original.pdf）
    if file.filename.lower().endswith(".caj"):
        tmp_caj = paper_dir / "original.caj"
        try:
            async with aiofiles.open(tmp_caj, 'wb') as f:
                await f.write(content)
            from src.tools.caj_parser import CAJParseError, convert_caj_to_pdf
            try:
                convert_caj_to_pdf(str(tmp_caj), str(paper_dir / "original.pdf"))
            except CAJParseError as e:
                raise HTTPException(status_code=400, detail=str(e))
        finally:
            tmp_caj.unlink(missing_ok=True)
    else:
        pdf_path = paper_dir / "original.pdf"
        async with aiofiles.open(pdf_path, 'wb') as f:
            await f.write(content)

    # 解析 PDF 提取真实标题/作者/摘要，写 metadata.json 供后续 get_paperReading 读取
    fallback_title = os.path.splitext(file.filename)[0].replace('_', ' ').replace('-', ' ')
    title = fallback_title
    authors: list = []
    abstract = ""
    try:
        from src.tools.pdf_parser import PDFParser
        parsed = PDFParser().parse(str(paper_dir / "original.pdf"), paper_id)
        if parsed.title and parsed.title != "Unknown":
            title = parsed.title
        if parsed.authors:
            authors = parsed.authors
        if parsed.abstract:
            abstract = parsed.abstract
    except Exception as e:
        logger.warning(f"PDF metadata parsing failed, falling back to filename: {e}")

    metadata_path = paper_dir / "metadata.json"
    try:
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(
                {"title": title, "authors": authors, "abstract": abstract},
                f, ensure_ascii=False, indent=2,
            )
    except Exception as e:
        logger.warning(f"write metadata.json failed: {e}")

    return {
        "paper_id": paper_id,
        "title": title,
        "pdf_path": f"data/papers/_uploads/{paper_id}/original.pdf",
        "authors": authors,
        "abstract": abstract,
    }


@app.get("/api/paper-reading/{paper_id}")
async def get_paperReading(paper_id: str):
    """获取已上传的论文信息"""
    paper_dir = _find_paper_dir_by_id(paper_id)

    if not paper_dir or not paper_dir.exists():
        raise HTTPException(status_code=404, detail="Paper not found")

    pdf_path = paper_dir / "original.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    # 尝试读取元数据
    metadata_path = paper_dir / "metadata.json"
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path, 'r', encoding="utf-8") as f:
            metadata = json.load(f)

    return {
        "paper_id": paper_id,
        "title": metadata.get("title", "Unknown"),
        "authors": metadata.get("authors", []),
        "abstract": metadata.get("abstract", ""),
        "pdf_path": f"data/papers/{paper_dir.parent.name}/{paper_dir.name}/original.pdf"
    }


@app.get("/api/paper-reading/{paper_id}/pdf")
async def get_paperReading_pdf(paper_id: str):
    """获取论文PDF文件"""
    paper_dir = _find_paper_dir_by_id(paper_id)
    if not paper_dir:
        raise HTTPException(status_code=404, detail="PDF not found")
    pdf_path = paper_dir / "original.pdf"

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(pdf_path, media_type="application/pdf")


@app.post("/api/paper-reading/analyze")
async def analyze_paperReading(request: PaperReadingRequest):
    """
    分析论文（执行精读）
    支持两种方式：
    1. 知识库已有PDF：pdf_path 指向 data/papers/<category>/<paper_id>/<paper_id>.pdf，原地使用
    2. 上传的PDF：data/papers/_uploads/<paper_id>/original.pdf

    精读结果文档（snap/lens/sphere_*.json）会写到 PDF 同目录，不再复制 PDF。
    """
    paper_id = request.paper_id
    pdf_path: Optional[Path] = None

    # 检查是否是知识库的PDF
    if request.pdf_path and request.pdf_path.startswith('data/papers/'):
        # 知识库已有PDF，原地使用（不复制）
        knowledge_pdf = PROJECT_ROOT / request.pdf_path
        if knowledge_pdf.exists():
            pdf_path = knowledge_pdf
        else:
            raise HTTPException(status_code=404, detail=f"知识库PDF文件不存在: {request.pdf_path}")
    else:
        # 上传的 PDF：在 _uploads 下查找
        paper_dir = _find_paper_dir_by_id(paper_id)
        if not paper_dir:
            raise HTTPException(status_code=404, detail="Paper not found")
        pdf_path = paper_dir / "original.pdf"
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found")

    # 创建任务ID
    run_id = f"{paper_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # 存储任务信息
    paper_reading_tasks[run_id] = {
        "paper_id": paper_id,
        "mode": request.mode,
        "language": request.language,
        "model": request.model,
        "pdf_path": str(pdf_path),
        "status": "pending",
        "result": None,
        "error": None
    }

    return {
        "run_id": run_id,
        "status": "started"
    }


@app.get("/api/paper-reading/stream/{run_id}")
async def stream_paperReading_analysis(run_id: str):
    """
    SSE流式推送分析进度和结果
    """
    if run_id not in paper_reading_tasks:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        task = paper_reading_tasks[run_id]

        # 发送开始消息
        yield f"data: {json.dumps({'type': 'started', 'data': {'mode': task['mode']}})}\n\n"
        await asyncio.sleep(0.1)

        try:
            from src.agents.paper_reading import analyze_paper_stream

            mode_str = task["mode"].value if hasattr(task["mode"], "value") else task["mode"]

            # 用队列桥接同步生成器（在线程池跑）与异步 SSE
            loop = asyncio.get_event_loop()
            queue: asyncio.Queue = asyncio.Queue()
            SENTINEL = object()

            def _producer():
                try:
                    for event in analyze_paper_stream(
                        task["pdf_path"],
                        task["paper_id"],
                        mode_str,
                        task["language"],
                        use_cache=True,
                    ):
                        asyncio.run_coroutine_threadsafe(queue.put(event), loop).result()
                except Exception as e:
                    logger.error(f"paper_reading_stream producer error: {e}", exc_info=True)
                    asyncio.run_coroutine_threadsafe(
                        queue.put({"type": "error", "message": str(e)}), loop
                    ).result()
                finally:
                    asyncio.run_coroutine_threadsafe(queue.put(SENTINEL), loop).result()

            loop.run_in_executor(None, _producer)

            final_result = None
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    break
                etype = item.get("type")
                if etype == "progress":
                    yield f"data: {json.dumps({'type': 'progress', 'data': {'message': item.get('message',''), 'progress': item.get('progress', 50)}})}\n\n"
                elif etype == "token":
                    yield f"data: {json.dumps({'type': 'token', 'data': {'token': item.get('text', '')}})}\n\n"
                elif etype == "cache_hit":
                    result = item.get("result", {})
                    yield f"data: {json.dumps({'type': 'progress', 'data': {'message': '✓ 命中缓存，秒级返回...', 'progress': 90, 'from_cache': True}})}\n\n"
                    yield f"data: {json.dumps({'type': 'complete', 'data': {'markdown': result.get('markdown',''), 'json': result.get('json',''), 'from_cache': True}})}\n\n"
                    final_result = result
                    task["status"] = "completed"
                    task["result"] = result
                    break
                elif etype == "complete":
                    result = item.get("result", {})
                    yield f"data: {json.dumps({'type': 'progress', 'data': {'message': '分析完成，生成结果...', 'progress': 90}})}\n\n"
                    yield f"data: {json.dumps({'type': 'complete', 'data': {'markdown': result.get('markdown',''), 'json': result.get('json',''), 'from_cache': False}})}\n\n"
                    final_result = result
                    task["status"] = "completed"
                    task["result"] = result
                    break
                elif etype == "error":
                    result = item.get("result", {})
                    task["status"] = "failed"
                    task["error"] = item.get("message", "分析失败")
                    yield f"data: {json.dumps({'type': 'error', 'data': {'message': item.get('message','分析失败'), 'markdown': result.get('markdown',''), 'json': result.get('json','')}})}\n\n"
                    break

            if final_result is None:
                task["status"] = "failed"
        except Exception as e:
            logger.error(f"论文分析失败: {e}", exc_info=True)
            task["status"] = "failed"
            task["error"] = str(e)
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': f'分析失败: {str(e)}'}})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== Main Entry ====================

def run_server(host: str = API_HOST, port: int = API_PORT):
    """运行 MCP 服务器。

    使用最小 log_config，避免 uvicorn 的 dictConfig 覆盖 InterceptHandler。
    uvicorn.* loggers 不配 handlers，propagate 到 root，由 InterceptHandler 统一走 loguru。
    """
    uvicorn_log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"level": "INFO"},
        },
    }
    uvicorn.run(
        "src.mcp.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        log_config=uvicorn_log_config,
    )


if __name__ == "__main__":
    run_server()

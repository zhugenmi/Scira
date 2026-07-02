# MCP 服务文档

本目录包含 Scira 项目的 MCP (Model Context Protocol) 服务集成模块，提供统一的论文搜索、下载和阅读接口。

## 目录结构

```
src/mcp/
├── __init__.py           # 模块初始化
├── server.py             # MCP HTTP API 服务入口
└── paper_search_mcp/     # 论文搜索 MCP 服务
    ├── __init__.py
    ├── cli.py            # 命令行接口
    ├── config.py         # 配置管理
    ├── paper.py          # 论文数据模型
    ├── utils.py          # 工具函数
    ├── server.py         # 论文搜索 MCP 服务端
    └── academic_platforms/   # 学术平台搜索器
        ├── __init__.py
        ├── arxiv.py          # arXiv 搜索
        ├── semantic.py       # Semantic Scholar 搜索
        ├── biorxiv.py        # BioRxiv 搜索
        ├── core.py           # CORE 搜索
        ├── pubmed.py         # PubMed 搜索
        ├── openalex.py       # OpenAlex 搜索
        └── ...               # 其他平台搜索器
```

## 启动服务

### 方式一：直接运行

```bash
python -m src.mcp.server
```

### 方式二：使用 uvicorn

```bash
uvicorn src.mcp.server:app --host 0.0.0.0 --port 8001
```

服务启动后，API 文档可在 http://localhost:8001/docs 查看。

## API 接口

### 健康检查

**GET** `/health`

检查服务状态和所有 MCP 服务的运行状态。

```bash
curl http://localhost:8001/health
```

响应示例：
```json
{
  "status": "healthy",
  "services": {
    "paper-search": "stopped"
  }
}
```

### 列出服务

**GET** `/services`

列出所有可用的 MCP 服务及其状态。

```bash
curl http://localhost:8001/services
```

### 搜索论文

**POST** `/api/paper-search/search`

搜索学术论文。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 搜索关键词 |
| max_results | integer | 否 | 最大结果数，默认 10 |
| sources | string | 否 | 数据源，逗号分隔或 "all"，可选值：arxiv, semantic, biorxiv, core |
| year | string | 否 | 年份过滤 |

**请求示例**：

```bash
curl -X POST http://localhost:8001/api/paper-search/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "diffusion model machine learning",
    "max_results": 10,
    "sources": "all"
  }'
```

**响应示例**：

```json
{
  "query": "diffusion model machine learning",
  "sources_used": ["all"],
  "total": 10,
  "papers": [
    {
      "paper_id": "2303.08774",
      "title": "Hierarchical Text Conditional Image Generation with CLIP Latents",
      "authors": "Tero Karras, Miika Aittala",
      "abstract": "...",
      "published": "2023-02-16",
      "pdf_url": "https://arxiv.org/pdf/2303.08774.pdf",
      "source": "arxiv"
    }
  ]
}
```

### 下载论文

**POST** `/api/paper-search/download`

下载论文 PDF 文件。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source | string | 是 | 数据源，如 arxiv, semantic 等 |
| paper_id | string | 是 | 论文 ID |
| doi | string | 否 | DOI |
| title | string | 否 | 论文标题 |
| save_path | string | 否 | 保存目录，默认 ./downloads |
| use_scihub | boolean | 否 | 是否启用 Sci-Hub 回退，默认 true |

**请求示例**：

```bash
curl -X POST http://localhost:8001/api/paper-search/download \
  -H "Content-Type: application/json" \
  -d '{
    "source": "arxiv",
    "paper_id": "2303.08774",
    "save_path": "./downloads"
  }'
```

**响应示例**：

```json
{
  "success": true,
  "paper_id": "2303.08774",
  "save_path": "./downloads/2303.08774.pdf"
}
```

### 读取论文内容

**POST** `/api/paper-search/read`

读取已下载的论文内容。

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source | string | 是 | 数据源 |
| paper_id | string | 是 | 论文 ID |

**请求示例**：

```bash
curl -X POST "http://localhost:8001/api/paper-search/read?source=arxiv&paper_id=2303.08774"
```

**响应示例**：

```json
{
  "paper_id": "2303.08774",
  "content": "..."
}
```

## 支持的数据源

| 数据源 | 说明 | 是否需要 API Key |
|--------|------|------------------|
| arXiv | 预印本论文 | 否 |
| Semantic Scholar | 学术搜索引擎 | 可选 |
| BioRxiv | 生物科学预印本 | 否 |
| CORE | 开放获取论文 | 可选 |
| PubMed | 生物医学文献 | 否 |
| OpenAlex | 学术知识图谱 | 否 |

## 环境变量

在 `.env` 文件中配置以下环境变量：

```bash
# MCP 服务配置
MCP_SERVER_HOST=localhost
MCP_SERVER_PORT=8001

# 论文下载目录
PAPER_DOWNLOAD_DIR=./downloads

# 学术平台 API Keys (可选)
PAPER_SEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY=your-api-key
PAPER_SEARCH_MCP_CORE_API_KEY=your-api-key
PAPER_SEARCH_MCP_UNPAYWALL_EMAIL=your@email.com
PAPER_SEARCH_MCP_DOAJ_API_KEY=your-api-key
PAPER_SEARCH_MCP_ZENODO_ACCESS_TOKEN=your-token
```

## 在 Agent 中使用

所有 Agent 通过 HTTP API 调用 MCP 服务：

```python
import requests
import os

MCP_API_BASE = os.getenv("MCP_API_BASE", "http://localhost:8001/api/paper-search")

# 搜索论文
response = requests.post(
    f"{MCP_API_BASE}/search",
    json={"query": "machine learning", "max_results": 10}
)
papers = response.json().get("papers", [])

# 下载论文
response = requests.post(
    f"{MCP_API_BASE}/download",
    json={
        "source": "arxiv",
        "paper_id": "2303.08774",
        "save_path": "./downloads"
    }
)
```

## 注意事项

1. 确保 MCP 服务运行后再调用 API
2. 部分数据源需要 API Key，建议配置以提高稳定性
3. 下载论文时，确保保存目录存在且有写入权限
4. 搜索结果可能包含多个数据源的论文，已自动去重

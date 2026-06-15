# Scira 🔬 AI 科研助手

基于 LangGraph 的多智能体科研助手，自动完成文献检索、阅读、分析与论文写作。

## ✨ 特性

- **全流程自动化**：输入研究主题 → 自动检索论文 → 阅读分析 → 生成综述报告
- **多智能体协作**：Retrieval → Reader → Analyzer → Writer → Reviewer 分工明确
- **多轮对话**：智能意图识别，问候直回复，知识查询自动检索，仅新研究触发工作流
- **记忆管理**：会话上下文管理，支持上下文压缩与历史搜索
- **MCP 集成**：通过 MCP 协议接入多源学术论文搜索（arXiv、Semantic Scholar、BioRxiv、CORE）
- **人机协同**：关键节点支持人工审核

## 🛠 技术栈

| 类别 | 技术 |
|------|------|
| 框架 | LangGraph、LangChain |
| LLM | OpenAI、Anthropic |
| 前端 | React + TypeScript + Vite + Tailwind |
| 后端 | FastAPI + Python 3.10+ |
| 协议 | MCP (Model Context Protocol) |

## 📂 目录结构

```
scira/
├── src/                          # 源代码
│   ├── main.py                   # 应用入口
│   ├── agents/                   # 智能体
│   │   ├── base.py               # Agent 基类
│   │   ├── orchestrator.py       # 意图分析与任务调度
│   │   ├── retrieval.py          # 论文检索
│   │   ├── reader.py             # 论文阅读
│   │   ├── analyzer.py           # 聚类分析
│   │   ├── writer.py             # 大纲与写作
│   │   ├── reviewer.py           # 修订审核
│   │   └── prompts.py            # 提示词模板
│   ├── core/                     # 核心模块
│   │   ├── state.py              # 状态定义
│   │   ├── workflow.py           # LangGraph 工作流
│   │   ├── memory.py             # 记忆管理
│   │   └── knowledge.py          # 知识库查询
│   ├── mcp/                      # MCP 服务
│   │   ├── server.py             # API 服务入口
│   │   └── paper_search_mcp/     # 论文搜索/下载 MCP
│   │       └── academic_platforms/  # 学术平台集成
│   ├── tools/                    # 工具函数
│   │   ├── pdf_parser.py         # PDF 解析
│   │   └── format_utils.py       # 格式化工具
│   └── utils/                    # 日志等
│       └── logger.py
├── frontend/                      # React 前端
│   └── src/
│       ├── main.tsx              # 前端入口
│       ├── App.tsx               # 主应用组件
│       ├── styles/               # 样式文件
│       └── components/           # 组件
│           ├── ChatView.tsx      # 多轮对话
│           ├── KnowledgeBase.tsx # 知识库
│           ├── DownloadedPapers.tsx
│           ├── GeneratedPapers.tsx
│           ├── Header.tsx        # 顶部导航
│           └── Sidebar.tsx       # 侧边栏
├── data/                         # 数据存储
├── logs/                         # 日志文件
├── config/                       # 配置
├── tests/                        # 测试
├── pyproject.toml                # 项目配置
├── .env                          # 环境变量
└── README.md
```

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -e .

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_PROVIDER=openai, OPENAI_API_KEY=xxx

# 3. 启动服务
python -m src.mcp.server      # 后端 :8001
cd frontend && npm install && npm run dev  # 前端 :5173
```

## 📡 API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/chat/send` | POST | 发送聊天消息（多轮对话） |
| `/api/chat/sessions` | GET | 列出会话 |
| `/api/workflow/start` | POST | 启动研究工作流 |
| `/api/workflow/status/{task_id}` | GET | 工作流状态 |
| `/api/paper-search/search` | POST | 搜索论文 |

## 💬 使用

1. 访问 http://localhost:5173
2. 输入研究主题（如"深度学习在医学影像的应用"）
3. 系统自动完成检索→阅读→分析→写作全流程
4. 可在"报告生成"查看结果
### 智能问答
![alt text](images/hello.png)
### 知识库管理
![alt text](images/knowledge_base.png)
### 论文精读
![alt text](images/paper_reading.png)
---
Powered by [LangGraph](https://langchain-ai.github.io/langgraph/) & [LangChain](https://python.langchain.com/)

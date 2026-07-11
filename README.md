# Scira 🔬 AI 科研助手

基于 LangGraph 的多智能体科研助手，覆盖**文献管理**，**文件检索 → 阅读 → 分析 → 论文写作**全链路。

## ✨ 特色功能

### 📚 文献管理

内置个人文献库，不仅是下载工具，而是可长期沉淀的研究资料库：

- **分类管理**：按研究主题自动归档，支持中英文主题自动映射、与既有分类合并，避免同类文献散落多个目录。
- **去重入库**：按 DOI → 标题两级去重，重复条目优先保留引用数更多的版本。
- **多渠道导入**：
  - 在线检索后一键下载（见下文检索）
  - 上传本地 PDF / CAJ 文件自动解析入库
  - 粘贴 BibTeX / APA 引用文本，LLM 解析为结构化条目
  - 对已有条目按标题在线搜匹配 PDF 并补全（多级回退：源站 → OA 仓库 → Unpaywall → Sci-Hub）
- **全库索引**：汇总所有分类的元数据，前端"已下载论文"视图直读此文件秒开。
- **前端操作**：在「知识库」页面可浏览分类、按标题/作者/关键词检索、查看详情、内嵌阅读 PDF、复制引用、删除单篇或整类、触发阅读模式。

### 🔎 文献检索

接入 **23 个学术平台**，并行检索 + 智能合并：

arXiv · Semantic Scholar · BioRxiv · MedRxiv · Google Scholar · IACR ePrint · Crossref · OpenAlex · PMC · CORE · Europe PMC · DBLP · OpenAIRE · CiteSeerX · DOAJ · BASE · Unpaywall · Zenodo · HAL · SSRN · PubMed · CNKI知网 · 万方

- **并行调度**：`asyncio` 同时发起所有源请求，按响应速度分级（快源 arXiv/Crossref、慢源 Google Scholar/CiteSeerX），达到 `max_results` 后取消未完成的慢源。
- **超时控制**：每源独立超时（20–35s），单源失败不影响整体。
- **结果合并**：DOI/标题双键去重，保留引用数更高版本。
- **下载回退链**：源站 PDF → OpenAIRE/CORE/EuropePMC/PMC 等 OA 仓库 → Unpaywall → Sci-Hub，逐级尝试直到拿到 PDF。
- **过滤参数**：支持 `max_results`、`sources`（逗号分隔或 `all`）、`year` 年份过滤。

### 📖 文献阅读（三种阅读模式）

针对单篇论文，根据阅读目的选择不同深度的结构化解读：

| 模式 | 定位 | 适用场景 | 输出 |
|------|------|---------|------|
| **速览模式 (snap)** | 30 秒判断是否值得读 | 筛选阶段快速过论文 | 一句话总结 + 3–5 条核心贡献 + 关键实验发现 + 适用性/局限 + "是否值得读"判定 |
| **深度精读 (lens)** | 完整技术解读 | 精读重点论文 | 论文概述 + 背景动机（含原文引用）+ 方法细节（公式/算法/架构）+ 实验设计与结果（数据集/指标/消融）+ 批判性分析 + 复现说明 + 一句话总结 |
| **研究全景 (sphere)** | 把论文放进研究地图 | 了解领域全貌 | 领域定位 + 技术演进时间线 + 相关工作聚类 + 代表性工作对比表 + 研究空白与机会 + 推荐阅读路径 |
| 问答模式 (qa) | 结构化自问自答 | 快速抓重点 | 6 个预设问题（问题/方法/创新/结果/局限/改进） |

- **智能触发**：在对话中说"用速览模式阅读《xxx》"等关键词即可自动识别模式并跳过意图分析。
- **结果缓存**：解读结果按 `paper_id + mode + language` 缓存，加速二次阅读。

### 🧠 文献分析

`AnalyzerAgent` 对一批论文做聚类与综合：

- **聚类分组**：按 `topic / method / approach / year` 四种维度对论文聚类，输出每组共同主题、共同方法、组内差异。
- **方法对比**：跨簇结构化对比核心方法、创新点、适用场景、性能表现。
- **知识综合**：生成全局知识图谱——研究背景、主流方法（含优缺点）、性能对比、研究空白（重要性 + 机会）、未来方向、关键发现。

### ✍️ 写作

`WriterAgent + ReviewerAgent` 模块化生成论文，各部分独立产出后组装：

- **完整综述论文**：生成大纲 → 逐章节顺序撰写（保持连贯性）→ 自动补全引言/摘要/总结 → 组装带指定格式（如GB/T 7714-2015）参考文献的完整论文。
- **单模块写作**：支持只生成某一模块——
  - 摘要（150–300 字）
  - 引言（含全局知识与引用要求）
  - 单个正文章节（带编号引用）
  - 总结（含发现、局限、未来方向）
- **引用规范**：参考文献从真实检索到的文献构建，绝不由 LLM 编造；正文 `[n]` 角标与文末目录一一对应；条目间用 `\n\n` 隔开避免 Markdown 软换行。
- **多轮修订**：串联审查 → 生成前置（摘要/引言）→ 生成总结 → 装配，支持反馈修订循环。

## 🛠 技术栈

| 类别 | 技术 |
|------|------|
| 框架 | LangGraph、LangChain |
| LLM | OpenAI、Anthropic（兼容 OpenAI 协议的本地/第三方模型经 `LLM_BASE_URL` 接入）|
| 前端 | React + TypeScript + Vite + Tailwind |
| 后端 | FastAPI + Python 3.10+ |
| 协议 | MCP (Model Context Protocol) |

## 📂 目录结构

```
scira/
├── src/                          # 源代码
│   ├── main.py                   # 应用入口
│   ├── agents/                   # 智能体
│   │   ├── base.py               # Agent 基类（含 token 追踪）
│   │   ├── orchestrator.py       # 意图分析与任务调度
│   │   ├── intent.py             # 意图识别（full/search/none）
│   │   ├── retrieval.py          # 论文检索
│   │   ├── reader.py             # 批量阅读（工作流用）
│   │   ├── paper_reading.py      # 单篇三种阅读模式
│   │   ├── analyzer.py           # 聚类分析与知识综合
│   │   ├── writer.py             # 大纲与章节写作
│   │   ├── reviewer.py           # 摘要/引言/总结生成与装配
│   │   └── prompts.py            # 提示词模板
│   ├── core/                     # 核心模块
│   │   ├── state.py              # GraphState 状态契约
│   │   ├── workflow.py           # LangGraph 工作流
│   │   ├── memory.py             # 记忆管理
│   │   └── knowledge.py          # 知识库查询
│   ├── mcp/                      # MCP 服务
│   │   ├── server.py             # API 服务入口
│   │   └── paper_search_mcp/     # 论文搜索/下载 MCP
│   │       └── academic_platforms/  # 23 个学术平台集成
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
│           ├── KnowledgeBase.tsx # 知识库（文献管理主界面）
│           ├── DownloadedPapers.tsx
│           ├── GeneratedPapers.tsx
│           ├── Header.tsx        # 顶部导航
│           └── Sidebar.tsx       # 侧边栏
├── data/                         # 数据存储
│   ├── papers/                   # 文献库（按分类组织）
│   ├── paper_reading/            # 阅读模式结果缓存
│   └── outputs/                  # 生成的综述报告
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

### CLI 直接跑工作流

```bash
python src/main.py --query "扩散模型在药物发现中的最新进展" --auto-approve
python src/main.py -q "topic" -o output.md          # 指定输出文件
python src/main.py -i                                  # 交互模式
```

## 🪟 Windows 一键启动

在 Windows 上双击项目根目录的 `start.bat` 一键部署启动：

- 自动检查 Python 3.10+ 与 Node.js 环境
- 自动创建 `.venv` 虚拟环境并安装后端依赖
- 自动安装前端依赖（`npm install`）
- 首次运行若无 `.env`，自动从 `.env.example` 复制并用记事本打开
- 在两个独立窗口分别启动后端 (:8001) 与前端 (:5173)

**环境要求：**

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | ≥ 3.10 | 需加入 PATH |
| Node.js | ≥ 16 | 随附 npm |

**使用方式：**

1. 双击 `start.bat`，或命令行执行：
   ```cmd
   start.bat
   ```
2. 首次运行会自动安装依赖，请耐心等待。
3. 看到两个新窗口分别显示后端、前端启动日志即表示成功。
4. 浏览器访问 http://localhost:5173
5. 关闭：直接关闭弹出的"Scira Backend"与"Scira Frontend"窗口。

## 💬 使用

1. 访问 http://localhost:5173
2. 输入研究主题（如"深度学习在医学影像的应用"）
3. 系统自动完成检索→阅读→分析→写作全流程
4. 可在"报告生成"查看结果

典型用法：
```txt
当前知识库中包含哪些论文？
用速览/精读模式阅读xxx知识库中所有的论文
```

### 文献检索
![alt text](assets/paper-search.png)

### 文献下载
![alt text](assets/paper-download.png)

### 论文阅读（三种阅读模式）
![alt text](assets/paper_reading.png)
![alt text](assets/paper-reading1.png)
速览模式：
![alt text](assets/paper-reading-ft.png)
深度精读：
![alt text](assets/paper-reading-dp2.png)
![alt text](assets/paper-reading-dp1.png)
研究全景：
![alt text](assets/paper-reading-fc1.png)
![alt text](assets/paper-reading-fc2.png)

### 报告生成
见[生成的报告示例](assets/强化学习_20260619_132031.md)

### 知识库管理
![alt text](assets/knowledge_base.png)

---

Powered by [LangGraph](https://langchain-ai.github.io/langgraph/) & [LangChain](https://python.langchain.com/)

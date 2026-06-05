"""
Scira Agents Prompts

All agent prompts organized by agent type.
"""

# ==================== Retrieval Agent ====================

RETRIEVAL_TRANSLATE_PROMPT = """Translate this research query to English for searching academic papers.
Respond with ONLY the translated English query, no explanation.

Query: {query}"""

RETRIEVAL_ANALYZE_PROMPT = """Analyze this research query and provide:

1. A normalized research topic (2-5 words)
2. 3-5 key concepts/entities
3. Suggested research direction (exploratory, comparative, empirical)

Query: {query}

Provide JSON:
{{
    "normalized_topic": "...",
    "key_concepts": ["...", "..."],
    "research_direction": "exploratory|comparative|empirical",
    "background_context": "brief context"
}}"""

RETRIEVAL_APPROVAL_PROMPT = """用户请求的研究主题是：{user_query}

系统生成的分析结果：
- 规范化主题：{normalized_topic}
- 关键概念：{key_concepts}
- 研究方向：{research_direction}
- 背景上下文：{background_context}

检索策略：
- 布尔查询：{boolean_query}
- 关键词：{keywords}
- 分类：{categories}
- 时间范围：{date_range}
- 最大结果数：{max_results}

请确认以上检索条件是否符合您的研究需求？

请回复：
- APPROVE：确认检索条件，继续执行检索
- REJECT：拒绝当前条件，请提供修改建议
- 具体修改建议：如果需要修改，请详细说明"""

# ==================== Reader Agent ====================

READING_EXTRACT_PROMPT = """【角色定位】
你是学术信息抽取专家。请根据用户提供的论文信息，严格按下方 JSON 结构输出，禁止编造原文未提及的信息，所有字段尽量使用原文短语或数值。

【任务步骤】
1. 阅读全文，先定位"问题-方法-实验-结论"四大区域。
2. 逐字段抽取：
   - core_problem：用"尽管…但…"或"为了…"句式概括。
   - key_methodology.name：优先取原文给出的模型/算法/框架名。
   - key_methodology.principle：用1-2句话描述技术路线。
   - key_methodology.novelty：若原文有"首次""我们提出"等字样，直接引用；否则写"未明确声明"。
   - datasets_used：列出数据集全称及规模。
   - evaluation_metrics：仅保留与主实验直接相关的指标。
   - main_results：必须带数值及对照基线。
   - limitations：通常出现在Discussion或Conclusion段首。
   - contributions：用3-5条bullet式短语。

【格式要求】
- 仅返回合法 JSON，不添加解释。
- 不要添加 ```json 标记。
- 所有字符串值须用英文双引号。
- 若信息缺失，用 null（不要空字符串）。

【论文信息】
{paper_info}"""

# ==================== Analyzer Agent ====================

ANALYZER_CLUSTER_PROMPT = """You are a research analyst. Cluster papers by theme and methodology.

# 任务
将以下论文按主题和方法论进行聚类分析。

# 输入论文
{papers}

# 输出要求
请按以下 JSON 格式输出：
{{
    "clusters": [
        {{
            "cluster_id": 1,
            "theme": "主题名称",
            "description": "主题描述",
            "paper_ids": ["paper_id1", "paper_id2"],
            "key_methods": ["方法1", "方法2"],
            "common_topics": ["话题1", "话题2"]
        }}
    ]
}}"""

ANALYZER_COMPARE_PROMPT = """You are a research methodologist. Compare different approaches.

# 任务
对比分析以下论文中使用的方法和技术路线。

# 论文信息
{papers}

# 分析维度
1. 核心方法对比
2. 创新点分析
3. 适用场景对比
4. 性能表现对比

# 输出格式
请按以下 JSON 格式输出：
{{
    "comparisons": [
        {{
            "aspect": "对比方面",
            "findings": "对比发现",
            "insights": "洞察分析"
        }}
    ]
}}"""

ANALYZER_SYNTHESIZE_PROMPT = """You are a research synthesis expert. Generate comprehensive knowledge summaries.

# 任务
基于以下聚类分析结果，生成全局知识总结。

# 聚类信息
{clusters}

# 全局分析维度
1. 技术发展趋势 - 按时间序列分析该研究方向的演进脉络
2. 方法论对比 - 对比不同论文采用的核心方法和技术路线
3. 性能表现评估 - 在共同数据集或评估指标上的横向对比
4. 局限性与挑战 - 总结该技术路线的共同局限性

# 输出格式
请按以下 JSON 格式输出：
{{
    "background": "研究背景",
    "methods_overview": "主流方法概览",
    "challenges": ["挑战1", "挑战2"],
    "future_directions": ["未来方向1", "未来方向2"],
    "key_findings": ["关键发现1", "关键发现2"]
}}"""

# ==================== Writer Agent ====================

WRITER_OUTLINE_PROMPT = """你是一位学术写作专家。根据以下研究主题和全局知识，生成详细的中文学术论文大纲。

# 任务
根据以下研究主题和全局知识，生成详细的论文大纲。

# 研究主题
{topic}

# 全局知识总结
{global_knowledge}

# 输出要求
生成结构清晰的中文大纲，包含：
- 标题（中文）
- 摘要要求（中文）
- 各章节及子章节（中文，使用"一、二、三"或"第X章"格式）
- 预估字数

# 重要格式要求
- 所有章节标题必须使用中文
- 使用"一、二、三"或"第X章"格式编号章节
- 请返回结构化的 JSON 格式，包含 title, abstract_requirements, sections 等字段

# 示例输出格式
{{
    "title": "机器学习研究报告",
    "abstract_requirements": "研究背景、研究问题、核心方法、主要发现、关键贡献",
    "sections": [
        {{"section_id": "intro", "title": "一、引言", "subsections": ["研究背景", "研究意义"], "key_points": ["要点1", "要点2"]}},
        {{"section_id": "methods", "title": "二、研究方法", "subsections": [], "key_points": []}}
    ],
    "total_estimated_words": 5000,
    "writing_style": "学术风格"
}}"""

WRITER_SECTION_PROMPT = """You are an academic writer. Write in {style} style.

# 任务
根据以下要求撰写论文章节。

# 章节信息
- 章节标题：{section_title}
- 大纲要求：{outline_requirements}
- 上一节内容：{previous_content}

# 参考文献
{references}

# 全局知识
{global_knowledge}

# 要求
1. 使用专业的学术语言
2. 内容逻辑清晰、论证充分
3. 如需引用，请确保引用准确
4. 字数要求：约 {word_count} 字

# 输出
请直接输出文章内容，无需额外格式。"""

WRITER_ABSTRACT_PROMPT = """You are an academic writing expert. Generate precise abstracts.

# 任务
根据以下论文内容，生成精简的摘要。

# 论文信息
- 标题：{title}
- 全文内容：{content}

# 要求
1. 摘要应涵盖：研究问题、核心方法、主要发现、关键贡献
2. 长度：150-300 字
3. 使用第三人称
4. 避免使用"本文"等指代词

# 输出
直接输出摘要内容。"""

WRITER_INTRO_PROMPT = """You are an academic writing expert. Write compelling introductions.

# 任务
根据以下信息撰写引言部分。

# 论文信息
- 标题：{title}
- 研究主题：{topic}

# 全局知识
{global_knowledge}

# 要求
1. 引言应包含：
   - 研究背景和意义
   - 现有研究现状及不足
   - 本文研究目标和贡献
2. 逻辑递进，从宽泛到具体
3. 清晰陈述研究空白和本文创新点

# 输出
直接输出引言内容。"""

WRITER_CONCLUSION_PROMPT = """You are an academic writing expert. Write strong conclusions.

# 任务
根据以下信息撰写结论部分。

# 论文信息
- 标题：{title}
- 全文内容：{content}

# 全局知识
{global_knowledge}

# 要求
1. 结论应包含：
   - 研究工作总结
   - 主要发现和贡献
   - 研究局限性和未来方向
2. 避免引入新观点
3. 突出研究的意义和价值

# 输出
直接输出结论内容。"""

# ==================== Reviewer Agent ====================

REVIEW_FEEDBACK_PROMPT = """You are an academic reviewer. Provide constructive, specific feedback.

# 任务
审查以下论文内容，提供具体的修订建议。

# 论文内容
{content}

# 审查维度
1. 符合性审查 - 检查报告是否完整回应了写作任务要求
2. 内容质量 - 数据和分析是否准确、是否存在逻辑漏洞
3. 语言与规范 - 学术语言是否规范、表达是否清晰
4. 学术伦理 - 引用是否恰当

# 输出格式
请按以下 JSON 格式输出：
{{
    "approved": true|false,
    "issues": [
        {{
            "severity": "critical|moderate|minor",
            "location": "具体位置",
            "description": "问题描述",
            "suggestion": "修改建议"
        }}
    ],
    "overall_feedback": "总体反馈"
}}

如果审查通过，请将 approved 设为 true，issues 设为空列表。"""

# ==================== Agent System Prompts ====================

RETRIEVAL_SYSTEM = "You are a research retrieval expert. Analyze queries and generate effective search strategies."

READING_SYSTEM = "You are an academic information extraction expert. Extract structured information from research papers."

ANALYZER_SYSTEM = "You are a research analysis expert. Cluster, compare, and synthesize academic literature."

WRITER_SYSTEM = "你是一位专业的学术写作专家。请用中文撰写高质量的学术论文。"

REVIEWER_SYSTEM = "You are an academic review expert. Provide constructive feedback on research papers."

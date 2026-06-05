#!/usr/bin/env python
"""
Scira - Scientific Research Assistant

Command-line interface for the multi-agent research system.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

# Import config and workflow
from config.settings import get_config
from src.core.workflow import run_workflow, run_workflow_stream
from src.core.state import PipelinePhase


console = Console()


def print_header():
    """Print welcome header."""
    console.print(Panel.fit(
        "[bold blue]Scira[/bold blue] - Scientific Research Assistant\n"
        "基于 LangGraph 的多智能体科研助手",
        border_style="blue",
    ))


def print_phase(phase: str, status: str = "in_progress"):
    """Print phase status."""
    icons = {
        "in_progress": "⏳",
        "completed": "✅",
        "failed": "❌",
        "pending": "⏸️",
    }
    console.print(f"  {icons.get(status, '•')} {phase}")


def print_results(state: dict):
    """Print workflow results."""
    console.print("\n[bold]研究结果:[/bold]\n")

    # Check retrieval status and warn if failed
    retrieval_successful = state.get("retrieval_successful", True)
    num_papers = len(state.get("search_results", []))

    if not retrieval_successful or num_papers == 0:
        console.print("[bold yellow]⚠️  警告：论文检索失败或未找到相关论文！[/bold yellow]")
        console.print("[yellow]系统将继续生成论文，但内容将基于通用知识，可能缺乏最新的研究数据。[/yellow]")
        console.print("[dim]提示：您可以：[/dim]")
        console.print("[dim]  1. 尝试更具体的研究主题[/dim]")
        console.print("[dim]  2. 检查网络连接后重试[/dim]")
        console.print("[dim]  3. 等待 MCP 服务启动后重试[/dim]")
        console.print()

    # Stats table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("阶段", style="cyan")
    table.add_column("状态", style="green")

    # Show retrieval result with warning if failed
    if retrieval_successful and num_papers > 0:
        table.add_row("检索", f"✅ {num_papers} 篇论文")
    else:
        table.add_row("检索", f"⚠️ {num_papers} 篇论文")

    table.add_row("阅读", f"✅ {len(state.get('literature_data', []))} 篇解析")
    table.add_row("分析", f"✅ {len(state.get('literature_clusters', []))} 个聚类")
    table.add_row("写作", f"✅ {len(state.get('chapter_drafts', {}))} 章节")
    table.add_row("修订", "✅ 完成" if state.get("final_review") else "❌ 失败")

    console.print(table)

    # Output file
    if state.get("final_review"):
        output_dir = Path("data/outputs")
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"research_{timestamp}.md"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(state["final_review"])

        console.print(f"\n[green]📄 论文已保存至: {output_file}[/green]")

    # Errors
    if state.get("error_messages"):
        console.print("\n[bold red]错误信息:[/bold red]")
        for err in state["error_messages"]:
            console.print(f"  • {err}")


def run_interactive():
    """Run in interactive mode."""
    print_header()

    console.print("\n[bold]请输入研究主题或问题:[/bold]")
    query = console.input("\n> ")

    if not query.strip():
        console.print("[red]请输入有效的研究主题[/red]")
        return

    console.print(f"\n[cyan]开始研究: {query}[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:

        # Phases
        tasks = {
            "retrieval": progress.add_task("🔍 检索论文...", total=None),
            "reading": progress.add_task("📖 阅读论文...", total=None),
            "analysis": progress.add_task("🧠 分析文献...", total=None),
            "outline": progress.add_task("📝 生成大纲...", total=None),
            "writing": progress.add_task("✍️ 撰写论文...", total=None),
            "revision": progress.add_task("✅ 修订完成...", total=None),
        }

        # Track current phase
        phase_tasks = {
            PipelinePhase.RETRIEVAL: "retrieval",
            PipelinePhase.READING: "reading",
            PipelinePhase.ANALYSIS: "analysis",
            PipelinePhase.OUTLINE: "outline",
            PipelinePhase.WRITING: "writing",
            PipelinePhase.REVISION: "revision",
        }

        try:
            state = run_workflow(query, auto_approve=True)

            # Mark all as complete
            for task in tasks.values():
                progress.update(task, completed=True)

        except Exception as e:
            console.print(f"\n[red]错误: {e}[/red]")
            return

    print_results(state)


def run_streaming():
    """Run with streaming output."""
    print_header()

    console.print("\n[bold]请输入研究主题或问题:[/bold]")
    query = console.input("\n> ")

    if not query.strip():
        console.print("[red]请输入有效的研究主题[/red]")
        return

    console.print(f"\n[cyan]开始研究: {query}[/cyan]\n")

    phases = {
        "init": ("初始化", False),
        "retrieval": ("检索论文", False),
        "reading": ("阅读论文", False),
        "analysis": ("分析文献", False),
        "outline": ("生成大纲", False),
        "writing": ("撰写论文", False),
        "revision": ("修订完成", False),
    }

    for state in run_workflow_stream(query, auto_approve=True):
        # Find completed phase
        phase = state.get("current_phase", "unknown")

        if phase in phases and not phases[phase][1]:
            name, _ = phases[phase]
            phases[phase] = (name, True)
            console.print(f"  ✅ {name}")

    # Get final state
    final_state = None
    for state in run_workflow_stream(query, auto_approve=True):
        final_state = state

    if final_state:
        print_results(final_state)


def run_cli(args):
    """Run from CLI arguments."""
    query = args.query
    auto_approve = args.auto_approve
    output = args.output

    if not query:
        console.print("[red]错误: 请提供研究主题 (--query)[/red]")
        sys.exit(1)

    console.print(f"\n[cyan]开始研究: {query}[/cyan]")
    console.print("[dim]使用自动批准模式[/dim]\n" if auto_approve else "\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:

            task = progress.add_task("🔬 研究进行中...", total=None)

            state = run_workflow(query, auto_approve=auto_approve)

            progress.update(task, completed=True)

    except Exception as e:
        console.print(f"\n[red]错误: {e}[/red]")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    # Print results
    print_results(state)

    # Save to specific output
    if output and state.get("final_review"):
        with open(output, "w", encoding="utf-8") as f:
            f.write(state["final_review"])
        console.print(f"\n[green]📄 论文已保存至: {output}[/green]")

    # Save JSON state
    if args.save_state:
        state_file = f"data/state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs("data", exist_ok=True)

        # Remove non-serializable fields
        save_state = {k: v for k, v in state.items()
                     if k not in ("human_approvals",)}
        # Convert enums to strings
        if "current_phase" in save_state:
            save_state["current_phase"] = str(save_state["current_phase"])

        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(save_state, f, indent=2, ensure_ascii=False)

        console.print(f"[dim]状态已保存至: {state_file}[/dim]")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Scira - Scientific Research Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python src/main.py --query "扩散模型在药物发现中的最新进展"
  python src/main.py --query "Transformer 在医学影像中的应用" --auto-approve
  python src/main.py --query "量子机器学习综述" -o output.md
        """
    )

    parser.add_argument(
        "--query", "-q",
        type=str,
        help="研究主题或问题",
    )

    parser.add_argument(
        "--auto-approve", "-a",
        action="store_true",
        help="自动批准所有步骤（跳过人工审核）",
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        help="输出文件路径",
    )

    parser.add_argument(
        "--save-state",
        action="store_true",
        help="保存工作流状态到 JSON 文件",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细错误信息",
    )

    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="交互模式",
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        help="流式输出模式",
    )

    args = parser.parse_args()

    if args.interactive:
        run_interactive()
    elif args.stream:
        run_streaming()
    else:
        run_cli(args)


if __name__ == "__main__":
    main()

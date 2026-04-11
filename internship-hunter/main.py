#!/usr/bin/env python
"""
CLI entry point for internship-hunter.

Usage:
  python main.py discover           -- scrape all job boards
  python main.py discover --remotive-only
  python main.py dashboard          -- open Streamlit dashboard
  python main.py seed               -- load target companies into DB
  python main.py generate           -- interactive cover letter generator
  python main.py stats              -- print application stats
"""

import sys
import subprocess
from pathlib import Path

BASE = Path(__file__).parent


def cmd_discover(args):
    from discover import run_discovery
    from rich.console import Console
    console = Console()
    sources = ("remotive",) if "--remotive-only" in args else ("remotive", "indeed", "ats")
    console.print(f"[bold cyan]Running discovery: {sources}[/bold cyan]")
    result = run_discovery(sources=sources)
    console.print(f"[green]Done. Found {result['total_found']} jobs, {result['new_added']} new.[/green]")


def cmd_dashboard(_args):
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(BASE / "dashboard.py")])


def cmd_seed(_args):
    from companies import seed_companies
    n = seed_companies()
    print(f"Seeded {n} target companies.")


def cmd_stats(_args):
    from tracker import get_stats
    from rich.console import Console
    from rich.table import Table
    console = Console()
    stats = get_stats()
    table = Table(title="Application Stats", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="green")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").title(), str(v))
    console.print(table)


def cmd_generate(_args):
    from generate import generate_cover_letter, save_cover_letter_docx, estimate_cost
    from rich.console import Console
    console = Console()
    console.print("[bold]Interactive Cover Letter Generator[/bold]")
    company = input("Company name: ").strip()
    role = input("Role title: ").strip()
    console.print("Paste job description (end with a line containing only '---'):")
    lines = []
    while True:
        line = input()
        if line == "---":
            break
        lines.append(line)
    jd = "\n".join(lines)
    context = input("Company context (optional, press Enter to skip): ").strip()
    console.print("[cyan]Generating...[/cyan]")
    letter, usage = generate_cover_letter(company, role, jd, context)
    cost = estimate_cost(usage)
    console.print(f"\n[dim]Cost: ~${cost:.4f} USD | cache_read: {usage.get('cache_read', 0)} tokens[/dim]\n")
    console.print(letter)
    save = input("\nSave as .docx? (y/n): ").strip().lower()
    if save == "y":
        path = save_cover_letter_docx(company, role, letter)
        console.print(f"[green]Saved: {path}[/green]")


COMMANDS = {
    "discover": cmd_discover,
    "dashboard": cmd_dashboard,
    "seed": cmd_seed,
    "stats": cmd_stats,
    "generate": cmd_generate,
}

if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "dashboard"
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(COMMANDS)}")
        sys.exit(1)
    COMMANDS[cmd](args[1:])

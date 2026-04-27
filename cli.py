#!/usr/bin/env python3
import os
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from airbyte.client import AirbyteClient
from airbyte.extractor import extract_sources, extract_destinations, extract_connections
from airbyte.pusher import (
    push_connection, push_all_connections,
    push_source, push_all_sources,
    push_destination, push_all_destinations,
)
from airbyte.differ import diff_connections

console = Console()
ROOT = Path(__file__).parent


def get_client(select: str) -> AirbyteClient:
    env_file = ROOT / f".env.{select}"
    if not env_file.exists():
        console.print(f"[red]Arquivo {env_file} não encontrado.[/red]")
        sys.exit(1)
    load_dotenv(env_file, override=True)
    return AirbyteClient(
        base_url=os.environ["AIRBYTE_URL"],
        client_id=os.environ.get("AIRBYTE_CLIENT_ID"),
        client_secret=os.environ.get("AIRBYTE_CLIENT_SECRET"),
        token=os.environ.get("AIRBYTE_TOKEN"),
        username=os.environ.get("AIRBYTE_USERNAME"),
        password=os.environ.get("AIRBYTE_PASSWORD"),
        workspace_id=os.environ.get("AIRBYTE_WORKSPACE_ID"),
    )


def _push_table(results: list, title: str):
    table = Table(title=title)
    table.add_column("Arquivo")
    table.add_column("Status")
    table.add_column("Detalhe", no_wrap=False)
    for r in results:
        action = r.get("_action", "dry-run")
        if action == "error":
            color, icon = "red", "✗"
            detail = r.get("_error", "")[:120]
        elif action in ("created", "updated"):
            color, icon = "green", "✓"
            detail = r.get("name", "")
        else:
            color, icon = "yellow", "~"
            detail = ""
        table.add_row(r.get("_file", r.get("name", "?")), f"[{color}]{icon} {action}[/{color}]", detail)
    console.print(table)


def cmd_workspaces(args):
    client = get_client(args.select)
    for w in client.list_workspaces():
        console.print(f"[bold]{w['workspaceId']}[/bold]  {w.get('name', '')}")


def cmd_list(args):
    client = get_client(args.select)
    with console.status("[bold]Buscando conexões..."):
        connections = client.list_connections()
        sources = {s["sourceId"]: s["name"] for s in client.list_sources()}
        destinations = {d["destinationId"]: d["name"] for d in client.list_destinations()}

    table = Table(title=f"Conexões — {args.select} ({len(connections)})")
    table.add_column("Nome")
    table.add_column("Source")
    table.add_column("Destination")
    table.add_column("Status")
    table.add_column("Schedule")

    for conn in sorted(connections, key=lambda c: c["name"]):
        status = conn.get("status", "")
        color = "green" if status == "active" else "red"
        table.add_row(
            conn["name"],
            sources.get(conn["sourceId"], "?"),
            destinations.get(conn["destinationId"], "?"),
            f"[{color}]{status}[/{color}]",
            conn.get("scheduleType", "manual"),
        )
    console.print(table)


def cmd_extract(args):
    client = get_client(args.select)

    with console.status("[bold]Extraindo sources..."):
        sources = extract_sources(client, args.select, ROOT)
    console.print(f"[green]✓[/green] {len(sources)} sources → sources/{args.select}/")

    with console.status("[bold]Extraindo destinations..."):
    	dests = extract_destinations(client, args.select, ROOT)
    console.print(f"[green]✓[/green] {len(dests)} destinations → destinations/{args.select}/")

    with console.status("[bold]Extraindo conexões..."):
        conns = extract_connections(client, args.select, ROOT)
    console.print(f"[green]✓[/green] {len(conns)} conexões → connections/{args.select}/")


def cmd_push(args):
    client = get_client(args.select)
    if args.dry_run:
        console.print("[yellow]DRY RUN — nenhuma mudança será aplicada[/yellow]")

    if args.select_conn:
        yaml_path = ROOT / "connections" / args.select / args.select_conn
        if not yaml_path.exists():
            # tenta adicionar .yaml se não tiver
            yaml_path = yaml_path.with_suffix(".yaml")
        if not yaml_path.exists():
            console.print(f"[red]Arquivo {yaml_path} não encontrado.[/red]")
            sys.exit(1)
        try:
            with console.status(f"[bold]Aplicando {yaml_path.name}..."):
                result = push_connection(client, args.select, yaml_path, dry_run=args.dry_run)
            console.print(f"[green]✓[/green] {yaml_path.name} → {result.get('_action', 'dry-run')}")
        except ValueError as e:
            console.print(f"[red]✗ {yaml_path.name}[/red]\n{e}")
            sys.exit(1)
    else:
        with console.status("[bold]Aplicando sources..."):
            src = push_all_sources(client, args.select, ROOT, dry_run=args.dry_run)
        with console.status("[bold]Aplicando destinations..."):
            dst = push_all_destinations(client, args.select, ROOT, dry_run=args.dry_run)
        with console.status("[bold]Aplicando connections..."):
            conn = push_all_connections(client, args.select, ROOT, dry_run=args.dry_run)
        _push_table(src + dst + conn, f"Push → {args.select}")


def cmd_diff(args):
    client = get_client(args.select)
    with console.status("[bold]Comparando..."):
        results = diff_connections(client, args.select, ROOT)

    table = Table(title=f"Diff → {args.select}", show_lines=args.verbose)
    table.add_column("Arquivo / Conexão", min_width=40)
    table.add_column("Status", min_width=12)
    table.add_column("Diferenças", no_wrap=False)

    changed = sum(1 for r in results if r["status"] == "changed")

    for r in results:
        label = r.get("file") or r.get("name", "?")
        status = r["status"]
        diff_lines = r.get("diff") or []

        if status == "ok":
            color, icon, diff_text = "green", "✓", ""
        elif status == "new":
            color, icon, diff_text = "blue", "+", "não existe no Airbyte ainda"
        elif status == "changed":
            color, icon = "yellow", "~"
            diff_text = "\n".join(diff_lines) if args.verbose else (diff_lines[0] if diff_lines else "")
        else:
            color, icon, diff_text = "dim", "?", "existe no Airbyte mas sem YAML local"

        table.add_row(label, f"[{color}]{icon} {status}[/{color}]", diff_text)

    console.print(table)

    parts = []
    for status, color, label in [
        ("ok", "green", "ok"), ("changed", "yellow", "alterada(s)"),
        ("new", "blue", "nova(s)"), ("untracked", "dim", "não rastreada(s)"),
    ]:
        n = sum(1 for r in results if r["status"] == status)
        if n:
            parts.append(f"[{color}]{n} {label}[/{color}]")
    console.print("  ".join(parts))

    if changed and not args.verbose:
        console.print("[dim]Use --verbose / -v para ver o diff completo.[/dim]")


def main():
    parser = argparse.ArgumentParser(prog="cli", description="Airbyte IaC — gerencie conexões via YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="Lista conexões do Airbyte")
    p.add_argument("--select", "-s", required=True, help="Nome do ambiente (ex: prod, staging)")

    p = sub.add_parser("extract", help="Extrai configs do Airbyte → YAML")
    p.add_argument("--select", "-s", required=True)

    p = sub.add_parser("push", help="Aplica YAMLs no Airbyte (sources + destinations + connections)")
    p.add_argument("--select", "-s", required=True)
    p.add_argument("--select-conn", default=None, metavar="FILE", help="Aplica só uma connection (ex: minha_conn.yaml)")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("diff", help="Compara YAML local vs Airbyte")
    p.add_argument("--select", "-s", required=True)
    p.add_argument("--verbose", "-v", action="store_true")

    p = sub.add_parser("workspaces", help="Lista workspaces disponíveis")
    p.add_argument("--select", "-s", required=True)

    args = parser.parse_args()
    args.dry_run = getattr(args, "dry_run", False)
    args.verbose = getattr(args, "verbose", False)
    args.select_conn = getattr(args, "select_conn", None)

    {
        "list": cmd_list,
        "extract": cmd_extract,
        "push": cmd_push,
        "diff": cmd_diff,
        "workspaces": cmd_workspaces,
    }[args.command](args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.text import Text

from airbyte.client import AirbyteClient
from airbyte.extractor import extract_sources, extract_destinations, extract_connections
from airbyte.pusher import push_connection, push_all_connections
from airbyte.differ import diff_connections

console = Console()
ROOT = Path(__file__).parent


def get_client(env: str) -> AirbyteClient:
    env_file = ROOT / f".env.{env}"
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


def cmd_workspaces(args):
    client = get_client(args.env)
    workspaces = client.list_workspaces()
    for w in workspaces:
        console.print(f"[bold]{w['workspaceId']}[/bold]  {w.get('name', '')}")


def cmd_list(args):
    client = get_client(args.env)
    with console.status(f"[bold]Buscando conexões ({args.env})..."):
        connections = client.list_connections()
        sources = {s["sourceId"]: s["name"] for s in client.list_sources()}
        destinations = {d["destinationId"]: d["name"] for d in client.list_destinations()}

    table = Table(title=f"Conexões — {args.env} ({len(connections)})")
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
    client = get_client(args.env)

    with console.status(f"[bold]Extraindo sources ({args.env})..."):
        sources = extract_sources(client, args.env, ROOT)
    console.print(f"[green]✓[/green] {len(sources)} sources → sources/{args.env}/")

    with console.status(f"[bold]Extraindo destinations ({args.env})..."):
        dests = extract_destinations(client, args.env, ROOT)
    console.print(f"[green]✓[/green] {len(dests)} destinations → destinations/{args.env}/")

    with console.status(f"[bold]Extraindo conexões ({args.env})..."):
        conns = extract_connections(client, args.env, ROOT)
    console.print(f"[green]✓[/green] {len(conns)} conexões → connections/{args.env}/")


def cmd_push(args):
    client = get_client(args.env)
    if args.dry_run:
        console.print("[yellow]DRY RUN — nenhuma mudança será aplicada[/yellow]")

    if args.file:
        yaml_path = ROOT / "connections" / args.env / args.file
        if not yaml_path.exists():
            console.print(f"[red]Arquivo {yaml_path} não encontrado.[/red]")
            sys.exit(1)
        try:
            with console.status(f"[bold]Aplicando {args.file}..."):
                result = push_connection(client, args.env, yaml_path, dry_run=args.dry_run)
            console.print(f"[green]✓[/green] {args.file} → {result.get('_action', 'dry-run')}")
        except ValueError as e:
            console.print(f"[red]✗ {args.file}[/red]\n{e}")
            sys.exit(1)
    else:
        with console.status(f"[bold]Aplicando conexões em connections/{args.env}/..."):
            results = push_all_connections(client, args.env, ROOT, dry_run=args.dry_run)

        table = Table(title=f"Push → {args.env}")
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
                detail = ""
            else:
                color, icon = "yellow", "~"
                detail = ""
            table.add_row(r["_file"], f"[{color}]{icon} {action}[/{color}]", detail)
        console.print(table)


def cmd_diff(args):
    client = get_client(args.env)
    with console.status(f"[bold]Comparando ({args.env})..."):
        results = diff_connections(client, args.env, ROOT)

    table = Table(title=f"Diff → {args.env}", show_lines=args.verbose)
    table.add_column("Arquivo / Conexão", min_width=40)
    table.add_column("Status", min_width=12)
    table.add_column("Diferenças", no_wrap=False)

    changed = sum(1 for r in results if r["status"] == "changed")

    for r in results:
        label = r.get("file") or r.get("name", "?")
        status = r["status"]
        diff_lines = r.get("diff") or []

        if status == "ok":
            color, icon = "green", "✓"
            diff_text = ""
        elif status == "new":
            color, icon = "blue", "+"
            diff_text = "não existe no Airbyte ainda"
        elif status == "changed":
            color, icon = "yellow", "~"
            if args.verbose:
                diff_text = "\n".join(diff_lines)
            else:
                diff_text = diff_lines[0] if diff_lines else ""
        else:
            color, icon = "dim", "?"
            diff_text = "existe no Airbyte mas sem YAML local"

        table.add_row(label, f"[{color}]{icon} {status}[/{color}]", diff_text)

    console.print(table)

    summary = []
    ok = sum(1 for r in results if r["status"] == "ok")
    new = sum(1 for r in results if r["status"] == "new")
    untracked = sum(1 for r in results if r["status"] == "untracked")

    if ok:
        summary.append(f"[green]{ok} ok[/green]")
    if changed:
        summary.append(f"[yellow]{changed} alterada(s)[/yellow]")
    if new:
        summary.append(f"[blue]{new} nova(s)[/blue]")
    if untracked:
        summary.append(f"[dim]{untracked} não rastreada(s)[/dim]")

    console.print("  ".join(summary))

    if changed and not args.verbose:
        console.print("[dim]Use --verbose / -v para ver o diff completo.[/dim]")


def main():
    parser = argparse.ArgumentParser(prog="cli", description="Airbyte IaC — gerencie conexões via YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="Lista conexões do Airbyte")
    p.add_argument("--env", default="prod")

    p = sub.add_parser("extract", help="Extrai configs do Airbyte → YAML")
    p.add_argument("--env", default="prod")

    p = sub.add_parser("push", help="Aplica YAMLs no Airbyte")
    p.add_argument("--env", default="dev")
    p.add_argument("--file", default=None)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("diff", help="Compara YAML local vs Airbyte")
    p.add_argument("--env", default="prod")
    p.add_argument("--verbose", "-v", action="store_true", help="Mostra diff completo")

    p = sub.add_parser("workspaces", help="Lista workspaces disponíveis")
    p.add_argument("--env", default="prod")

    args = parser.parse_args()
    args.dry_run = getattr(args, "dry_run", False)
    args.verbose = getattr(args, "verbose", False)

    {"list": cmd_list, "extract": cmd_extract, "push": cmd_push, "diff": cmd_diff, "workspaces": cmd_workspaces}[args.command](args)


if __name__ == "__main__":
    main()

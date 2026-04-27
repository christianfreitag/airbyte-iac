#!/usr/bin/env python3
import os
import sys
import argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn
from rich.live import Live
from rich.text import Text
from rich import box

from airbyte.client import AirbyteClient
from airbyte.extractor import extract_sources, extract_destinations, extract_connections
from airbyte.pusher import push_connection, push_all_connections, push_all_sources, push_all_destinations
from airbyte.differ import diff_connections

console = Console(highlight=False)
ROOT = Path(__file__).parent


def _ask(prompt: str) -> str:
    console.print(prompt, end="")
    sys.stdout.flush()
    return input()


def _progress():
    return Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[progress.description]{task.description:<20}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def _header(title: str, color: str = "cyan"):
    console.print()
    console.print(Panel(Text(title, style=f"bold {color}"), expand=False, border_style=color, padding=(0, 2)))


def _summary_row(icon: str, color: str, label: str, count: int):
    console.print(f"  [{color}]{icon}[/{color}] [bold]{count}[/bold] [dim]{label}[/dim]")


def get_client(infra: str) -> AirbyteClient:
    env_file = ROOT / f".env.{infra}"
    if not env_file.exists():
        console.print(f"[red]✗ .env.{infra} não encontrado.[/red]")
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
    client = get_client(args.infra)
    _header(f"Workspaces — {args.infra}")
    for w in client.list_workspaces():
        console.print(f"  [bold cyan]{w['workspaceId']}[/bold cyan]  {w.get('name', '')}")


def cmd_list(args):
    client = get_client(args.infra)
    with _progress() as p:
        t = p.add_task("[cyan]Carregando...", total=None)
        connections = client.list_connections()
        sources = {s["sourceId"]: s["name"] for s in client.list_sources()}
        destinations = {d["destinationId"]: d["name"] for d in client.list_destinations()}
        p.update(t, completed=1, total=1, description="[green]Carregado")

    table = Table(
        title=f"[bold]Conexões — {args.infra}[/bold] [dim]({len(connections)})[/dim]",
        box=box.ROUNDED, border_style="cyan", header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("Nome", style="bold white")
    table.add_column("Source", style="dim")
    table.add_column("Destination", style="dim")
    table.add_column("Status", justify="center")
    table.add_column("Schedule", justify="center")
    table.add_column("Select", style="cyan")

    for conn in sorted(connections, key=lambda c: c["name"]):
        status = conn.get("status", "")
        color = "green" if status == "active" else "red"
        tags = conn.get("tags", [])
        select_tag = next(
            (t.get("name") if isinstance(t, dict) else t for t in tags
             if (t.get("name") if isinstance(t, dict) else t or "").startswith("select:")),
            "[dim]-[/dim]"
        )
        table.add_row(
            conn["name"],
            sources.get(conn["sourceId"], "?"),
            destinations.get(conn["destinationId"], "?"),
            f"[{color}]● {status}[/{color}]",
            conn.get("scheduleType", "manual"),
            select_tag,
        )
    console.print()
    console.print(table)


def cmd_extract(args):
    client = get_client(args.infra)
    _header(f"pull → {args.infra}" + (f"  [{args.select}]" if args.select else ""))

    with _progress() as p:
        if not args.select:
            t1 = p.add_task("[cyan]Sources      ", total=None)
            srcs = extract_sources(client, args.infra, ROOT)
            p.update(t1, completed=len(srcs), total=len(srcs), description=f"[green]Sources      ")

            t2 = p.add_task("[cyan]Destinations ", total=None)
            dsts = extract_destinations(client, args.infra, ROOT)
            p.update(t2, completed=len(dsts), total=len(dsts), description=f"[green]Destinations ")
        else:
            srcs, dsts = [], []

        t3 = p.add_task("[cyan]Connections  ", total=None)
        conns = extract_connections(client, args.infra, ROOT, select=args.select)
        p.update(t3, completed=len(conns), total=len(conns), description=f"[green]Connections  ")

    console.print()
    console.print(Rule(f"[bold green]✓ Extraído → targets/{args.infra}/[/bold green]", style="green"))
    if srcs:
        _summary_row("◆", "blue", "sources", len(srcs))
    if dsts:
        _summary_row("◆", "magenta", "destinations", len(dsts))
    _summary_row("◆", "cyan", "connections", len(conns))
    console.print()


def cmd_push(args):
    client = get_client(args.infra)
    source_infra = args.from_infra or args.infra
    label = f"push {source_infra} → {args.infra}" if args.from_infra else f"push → {args.infra}"
    if args.select:
        label += f"  [{args.select}]"
    _header(label, color="yellow" if args.dry_run else "green")

    if args.dry_run:
        console.print("  [yellow bold]DRY RUN[/yellow bold] [dim]— nenhuma mudança será aplicada[/dim]\n")

    if args.file:
        if not args.select:
            console.print("[red]--file requer --select[/red]")
            sys.exit(1)
        yaml_path = ROOT / "targets" / source_infra / "connections" / args.select / args.file
        if not yaml_path.exists():
            yaml_path = yaml_path.with_suffix(".yaml")
        if not yaml_path.exists():
            console.print(f"[red]✗ {yaml_path} não encontrado.[/red]")
            sys.exit(1)
        with _progress() as p:
            t = p.add_task(f"[cyan]{yaml_path.name}", total=None)
            try:
                result = push_connection(client, yaml_path, dry_run=args.dry_run)
                p.update(t, completed=1, total=1, description=f"[green]{yaml_path.name}")
                console.print(f"\n[green]✓[/green] {yaml_path.name} → {result.get('_action', 'dry-run')}")
            except ValueError as e:
                p.update(t, completed=1, total=1, description=f"[red]{yaml_path.name}")
                console.print(f"\n[red]✗ {e}[/red]")
                sys.exit(1)
        return

    with _progress() as p:
        t1 = p.add_task("[cyan]Sources      ", total=None)
        src = push_all_sources(client, source_infra, ROOT, dry_run=args.dry_run)
        p.update(t1, completed=len(src), total=len(src), description=f"[green]Sources      ")

        t2 = p.add_task("[cyan]Destinations ", total=None)
        dst = push_all_destinations(client, source_infra, ROOT, dry_run=args.dry_run)
        p.update(t2, completed=len(dst), total=len(dst), description=f"[green]Destinations ")

        t3 = p.add_task("[cyan]Connections  ", total=None)
        conn = push_all_connections(client, source_infra, ROOT, select=args.select, dry_run=args.dry_run)
        p.update(t3, completed=len(conn), total=len(conn), description=f"[green]Connections  ")

    all_results = src + dst + conn
    errors   = [r for r in all_results if r.get("_action") == "error"]
    created  = [r for r in all_results if r.get("_action") == "created"]
    updated  = [r for r in all_results if r.get("_action") == "updated"]
    dry      = [r for r in all_results if r.get("_action") == "dry-run"]

    console.print()
    console.print(Rule(f"[bold]Resultado[/bold]", style="dim"))

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column(style="dim", width=45)
    table.add_column(width=18)
    table.add_column(style="dim")

    for r in all_results:
        action = r.get("_action", "")
        fname = r.get("_file", r.get("name", "?"))
        if action == "error":
            table.add_row(fname, "[red]✗ error[/red]", r.get("_error", "")[:80])
        elif action == "created":
            table.add_row(fname, "[green]✓ created[/green]", r.get("name", ""))
        elif action == "updated":
            table.add_row(fname, "[cyan]~ updated[/cyan]", r.get("name", ""))
        elif action == "dry-run":
            table.add_row(fname, "[yellow]○ dry-run[/yellow]", "")

    console.print(table)

    parts = []
    if created: parts.append(f"[green]{len(created)} created[/green]")
    if updated: parts.append(f"[cyan]{len(updated)} updated[/cyan]")
    if dry:     parts.append(f"[yellow]{len(dry)} dry-run[/yellow]")
    if errors:  parts.append(f"[red]{len(errors)} errors[/red]")
    if parts:
        console.print("  " + "  [dim]·[/dim]  ".join(parts))
    console.print()


def cmd_diff(args):
    client = get_client(args.infra)
    _header(f"status → {args.infra}" + (f"  [{args.select}]" if args.select else ""))

    with _progress() as p:
        t = p.add_task("[cyan]Comparando...", total=None)
        results = diff_connections(client, args.infra, ROOT, select=args.select)
        p.update(t, completed=len(results), total=len(results), description="[green]Comparado   ")

    table = Table(
        box=box.ROUNDED, border_style="dim", header_style="bold",
        show_lines=args.verbose,
    )
    table.add_column("Conexão / Arquivo", min_width=42, style="white")
    table.add_column("Status", min_width=14, justify="center")
    table.add_column("Diferenças", no_wrap=False, style="dim")

    for r in results:
        label = r.get("file") or r.get("name", "?")
        status = r["status"]
        diff_lines = r.get("diff") or []

        if status == "ok":
            color, icon, diff_text = "green", "✓", ""
        elif status == "new":
            color, icon, diff_text = "blue", "+", "não existe no Airbyte"
        elif status == "changed":
            color, icon = "yellow", "~"
            diff_text = "\n".join(diff_lines) if args.verbose else (diff_lines[0] if diff_lines else "")
        else:
            color, icon, diff_text = "dim", "?", "sem YAML local"

        table.add_row(label, f"[{color}]{icon} {status}[/{color}]", diff_text)

    console.print()
    console.print(table)

    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("ok", "changed", "new", "untracked")}
    parts = []
    if counts["ok"]:        parts.append(f"[green]{counts['ok']} ok[/green]")
    if counts["changed"]:   parts.append(f"[yellow]{counts['changed']} alterada(s)[/yellow]")
    if counts["new"]:       parts.append(f"[blue]{counts['new']} nova(s)[/blue]")
    if counts["untracked"]: parts.append(f"[dim]{counts['untracked']} não rastreada(s)[/dim]")
    if parts:
        console.print("  " + "  [dim]·[/dim]  ".join(parts))
    if counts["changed"] and not args.verbose:
        console.print("  [dim]--verbose para ver diff completo[/dim]")
    console.print()


def cmd_clean_airbyte(args):
    client = get_client(args.infra)
    _header(f"reset → {args.infra}", color="red")
    console.print(f"  [red]ATENÇÃO:[/red] apagará [bold]todas[/bold] as conexões, sources e destinations de [bold]{args.infra}[/bold].\n")

    if _ask("  Confirmar? (y|n): ").strip().lower() != "y":
        console.print("\n  [yellow]Cancelado.[/yellow]\n")
        return

    console.print()
    conns = client.list_connections()
    srcs  = client.list_sources()
    dsts  = client.list_destinations()
    total = len(conns) + len(srcs) + len(dsts)

    with _progress() as p:
        t = p.add_task("[red]Apagando...", total=total)
        for conn in conns:
            client.delete_connection(conn["connectionId"])
            p.advance(t)
            p.print(f"  [red]✗[/red] [dim]connection[/dim]  {conn['name']}")
        for src in srcs:
            client.delete_source(src["sourceId"])
            p.advance(t)
            p.print(f"  [red]✗[/red] [dim]source     [/dim]  {src['name']}")
        for dst in dsts:
            client.delete_destination(dst["destinationId"])
            p.advance(t)
            p.print(f"  [red]✗[/red] [dim]destination[/dim]  {dst['name']}")
        p.update(t, description="[green]Concluído  ")

    console.print()
    console.print(Rule(f"[green]✓ {args.infra} limpo — {total} recursos removidos[/green]", style="green"))
    console.print()


def cmd_setup_infra(args):
    console.print()
    console.print(Panel("[bold cyan]Airbyte IaC — Novo Target[/bold cyan]", expand=False, border_style="cyan", padding=(0, 4)))
    console.print()

    infra = input("  Nome do target (ex: prod, dev, staging): ").strip()
    if not infra:
        console.print("[red]Nome inválido.[/red]")
        sys.exit(1)

    env_file = ROOT / f".env.{infra}"
    if env_file.exists():
        if _ask(f"\n  [yellow].env.{infra} já existe. Sobrescrever?[/yellow] (y|n): ").strip().lower() != "y":
            console.print("  Cancelado.")
            return

    console.print()
    url = input("  AIRBYTE_URL (ex: http://localhost:8000): ").strip()

    console.print()
    console.print("  Autenticação:")
    console.print("    [bold cyan]1[/bold cyan]  Client ID + Secret  [dim](OAuth)[/dim]")
    console.print("    [bold cyan]2[/bold cyan]  Token estático")
    console.print("    [bold cyan]3[/bold cyan]  Usuário + Senha  [dim](Basic Auth)[/dim]")
    auth_choice = input("  Opção (1/2/3): ").strip()

    client_id = client_secret = token = username = password = ""
    console.print()
    if auth_choice == "1":
        client_id = input("  AIRBYTE_CLIENT_ID: ").strip()
        client_secret = input("  AIRBYTE_CLIENT_SECRET: ").strip()
    elif auth_choice == "2":
        token = input("  AIRBYTE_TOKEN: ").strip()
    elif auth_choice == "3":
        username = input("  AIRBYTE_USERNAME: ").strip()
        password = input("  AIRBYTE_PASSWORD: ").strip()

    console.print()
    workspace_id = input("  AIRBYTE_WORKSPACE_ID (opcional, Enter para pular): ").strip()

    lines = [f"AIRBYTE_URL={url}\n"]
    if client_id:
        lines += [f"AIRBYTE_CLIENT_ID={client_id}\n", f"AIRBYTE_CLIENT_SECRET={client_secret}\n"]
    if token:
        lines += [f"AIRBYTE_TOKEN={token}\n"]
    if username:
        lines += [f"AIRBYTE_USERNAME={username}\n", f"AIRBYTE_PASSWORD={password}\n"]
    if workspace_id:
        lines += [f"AIRBYTE_WORKSPACE_ID={workspace_id}\n"]

    env_file.write_text("".join(lines), encoding="utf-8")
    for folder in ["sources", "destinations", "connections"]:
        (ROOT / "targets" / infra / folder).mkdir(parents=True, exist_ok=True)

    console.print()
    console.print(Rule(f"[bold green]✓ Target '{infra}' criado[/bold green]", style="green"))
    console.print(f"  [green]✓[/green] .env.{infra}")
    console.print(f"  [green]✓[/green] targets/{infra}/{{sources,destinations,connections}}/")
    console.print()

    if _ask("  Extrair conexões do Airbyte agora? (y|n): ").strip().lower() == "y":
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "cli.py"), "pull", f"--target={infra}"], check=False)


def cmd_clone_infra(args):
    src = ROOT / "targets" / args.from_infra
    dst = ROOT / "targets" / args.infra
    _header(f"clone {args.from_infra} → {args.infra}", color="magenta")

    if not src.exists():
        console.print(f"[red]✗ targets/{args.from_infra}/ não encontrada.[/red]")
        sys.exit(1)

    if dst.exists():
        if _ask(f"  [yellow]targets/{args.infra}/ já existe. Sobrescrever?[/yellow] (y|n): ").strip().lower() != "y":
            console.print("  Cancelado.")
            return

    import shutil
    with _progress() as p:
        t = p.add_task(f"[cyan]Copiando targets/{args.from_infra}/...", total=None)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        p.update(t, completed=1, total=1, description="[green]Copiado")

    console.print()
    console.print(f"  [green]✓[/green] targets/{args.from_infra}/ → targets/{args.infra}/")

    env_src = ROOT / f".env.{args.from_infra}"
    env_dst = ROOT / f".env.{args.infra}"
    if not env_dst.exists():
        if env_src.exists():
            shutil.copy(env_src, env_dst)
            console.print(f"  [yellow]~[/yellow] .env.{args.infra} copiado — [bold]atualize as credenciais![/bold]")
        else:
            console.print(f"  [dim]Crie .env.{args.infra} com: make init[/dim]")
    else:
        console.print(f"  [dim].env.{args.infra} já existe, mantido.[/dim]")
    console.print()


def main():
    parser = argparse.ArgumentParser(prog="airbyte-iac", description="Airbyte IaC — gerencie conexões via YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list",       help="Lista conexões do Airbyte")
    p.add_argument("--target", "-t", required=True)

    p = sub.add_parser("pull",       help="Extrai configs do Airbyte → YAML")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--select", "-s", default=None)

    p = sub.add_parser("push",       help="Aplica YAMLs no Airbyte")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--from",   dest="from_target", default=None)
    p.add_argument("--select", "-s", default=None)
    p.add_argument("--file",   "-f", default=None)
    p.add_argument("--dry-run",      action="store_true")

    p = sub.add_parser("status",     help="Compara YAML local vs Airbyte")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--select", "-s", default=None)
    p.add_argument("--verbose","-v", action="store_true")

    p = sub.add_parser("workspaces", help="Lista workspaces disponíveis")
    p.add_argument("--target", "-t", required=True)

    p = sub.add_parser("reset",      help="Apaga tudo no Airbyte (pede confirmação)")
    p.add_argument("--target", "-t", required=True)

    sub.add_parser("init",           help="Configura um novo target interativamente")

    p = sub.add_parser("clone",      help="Clona YAMLs de um target para outro")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--from",   dest="from_target", required=True)

    p = sub.add_parser("sync",       help="Pull de um target e push para outro")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--from",   dest="from_target", required=True)
    p.add_argument("--select", "-s", default=None)

    args = parser.parse_args()
    args.dry_run    = getattr(args, "dry_run", False)
    args.verbose    = getattr(args, "verbose", False)
    args.select     = getattr(args, "select", None)
    args.file       = getattr(args, "file", None)
    args.infra      = getattr(args, "target", None)
    args.from_infra = getattr(args, "from_target", None)

    {
        "list":       cmd_list,
        "pull":       cmd_extract,
        "push":       cmd_push,
        "status":     cmd_diff,
        "workspaces": cmd_workspaces,
        "reset":      cmd_clean_airbyte,
        "init":       cmd_setup_infra,
        "clone":      cmd_clone_infra,
        "sync":       lambda a: (cmd_extract(a) or cmd_push(a)),
    }[args.command](args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os
import sys
import argparse
from pathlib import Path

# força UTF-8 no terminal Windows (evita UnicodeEncodeError com → e outros)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from airbyte.client import AirbyteClient
from airbyte.extractor import extract_sources, extract_destinations, extract_connections
from airbyte.pusher import push_connection, push_all_connections, push_all_sources, push_all_destinations
from airbyte.differ import diff_connections

console = Console()
ROOT = Path(__file__).parent


def get_client(infra: str) -> AirbyteClient:
    env_file = ROOT / f".env.{infra}"
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
    client = get_client(args.infra)
    for w in client.list_workspaces():
        console.print(f"[bold]{w['workspaceId']}[/bold]  {w.get('name', '')}")


def cmd_list(args):
    client = get_client(args.infra)
    with console.status("[bold]Buscando conexões..."):
        connections = client.list_connections()
        sources = {s["sourceId"]: s["name"] for s in client.list_sources()}
        destinations = {d["destinationId"]: d["name"] for d in client.list_destinations()}

    table = Table(title=f"Conexões — {args.infra} ({len(connections)})")
    table.add_column("Nome")
    table.add_column("Source")
    table.add_column("Destination")
    table.add_column("Status")
    table.add_column("Schedule")
    table.add_column("Select")

    for conn in sorted(connections, key=lambda c: c["name"]):
        status = conn.get("status", "")
        color = "green" if status == "active" else "red"
        tags = conn.get("tags", [])
        select_tag = next(
            (t.get("name") if isinstance(t, dict) else t for t in tags
             if (t.get("name") if isinstance(t, dict) else t or "").startswith("select:")),
            "-"
        )
        table.add_row(
            conn["name"],
            sources.get(conn["sourceId"], "?"),
            destinations.get(conn["destinationId"], "?"),
            f"[{color}]{status}[/{color}]",
            conn.get("scheduleType", "manual"),
            select_tag,
        )
    console.print(table)


def cmd_extract(args):
    client = get_client(args.infra)

    if not args.select:
        with console.status("[bold]Extraindo sources..."):
            srcs = extract_sources(client, args.infra, ROOT)
        console.print(f"[green]✓[/green] {len(srcs)} sources → targets/{args.infra}/sources/")

        with console.status("[bold]Extraindo destinations..."):
            dsts = extract_destinations(client, args.infra, ROOT)
        console.print(f"[green]✓[/green] {len(dsts)} destinations → targets/{args.infra}/destinations/")

    with console.status(f"[bold]Extraindo connections{f' ({args.select})' if args.select else ''}..."):
        conns = extract_connections(client, args.infra, ROOT, select=args.select)

    label = f"select:{args.select}" if args.select else "all"
    console.print(f"[green]✓[/green] {len(conns)} connections → targets/{args.infra}/connections/ [{label}]")


def cmd_push(args):
    client = get_client(args.infra)
    source_infra = args.from_infra or args.infra
    if args.dry_run:
        console.print("[yellow]DRY RUN — nenhuma mudança será aplicada[/yellow]")
    if args.from_infra:
        console.print(f"[dim]Lendo YAMLs de targets/{source_infra}/ → enviando para {args.infra}[/dim]")

    if args.file:
        if not args.select:
            console.print("[red]--file requer --select (ex: make push INFRA=prod SELECT=ga4 FILE=conn.yaml)[/red]")
            sys.exit(1)
        yaml_path = ROOT / "targets" / source_infra / "connections" / args.select / args.file
        if not yaml_path.exists():
            yaml_path = yaml_path.with_suffix(".yaml")
        if not yaml_path.exists():
            console.print(f"[red]Arquivo {yaml_path} não encontrado.[/red]")
            sys.exit(1)
        try:
            with console.status(f"[bold]Aplicando {yaml_path.name}..."):
                result = push_connection(client, yaml_path, dry_run=args.dry_run)
            console.print(f"[green]✓[/green] {yaml_path.name} → {result.get('_action', 'dry-run')}")
        except ValueError as e:
            console.print(f"[red]✗ {yaml_path.name}[/red]\n{e}")
            sys.exit(1)
        return

    # sources e destinations sempre primeiro — connections dependem delas
    with console.status("[bold]Aplicando sources..."):
        src = push_all_sources(client, source_infra, ROOT, dry_run=args.dry_run)
    with console.status("[bold]Aplicando destinations..."):
        dst = push_all_destinations(client, source_infra, ROOT, dry_run=args.dry_run)
    with console.status(f"[bold]Aplicando connections{f' ({args.select})' if args.select else ''}..."):
        conn = push_all_connections(client, source_infra, ROOT, select=args.select, dry_run=args.dry_run)

    title = f"Push {source_infra} → {args.infra}" if args.from_infra else f"Push → {args.infra}"
    title += f"/{args.select}" if args.select else ""
    _push_table(src + dst + conn, title)


def cmd_setup_infra(args):
    console.print("\n[bold cyan]Configuração de nova infra[/bold cyan]\n")

    infra = input("Nome da infra (ex: prod, dev, staging): ").strip()
    if not infra:
        console.print("[red]Nome inválido.[/red]")
        sys.exit(1)

    env_file = ROOT / f".env.{infra}"
    if env_file.exists():
        console.print(f"[yellow].env.{infra} já existe. Sobrescrever? (yes/n):[/yellow] ", end="")
        if input().strip() != "yes":
            console.print("Cancelado.")
            return

    url = input("AIRBYTE_URL (ex: http://localhost:8000): ").strip()

    console.print("\nAutenticação — escolha um método:")
    console.print("  [1] Client ID + Secret (OAuth)")
    console.print("  [2] Token estático")
    console.print("  [3] Usuário + Senha (Basic Auth)")
    auth_choice = input("Opção (1/2/3): ").strip()

    client_id = client_secret = token = username = password = ""
    if auth_choice == "1":
        client_id = input("AIRBYTE_CLIENT_ID: ").strip()
        client_secret = input("AIRBYTE_CLIENT_SECRET: ").strip()
    elif auth_choice == "2":
        token = input("AIRBYTE_TOKEN: ").strip()
    elif auth_choice == "3":
        username = input("AIRBYTE_USERNAME: ").strip()
        password = input("AIRBYTE_PASSWORD: ").strip()

    workspace_id = input("\nAIRBYTE_WORKSPACE_ID (opcional, Enter para pular): ").strip()

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

    console.print(f"\n[green]✓[/green] .env.{infra} criado")
    console.print(f"[green]✓[/green] targets/{infra}/{{sources,destinations,connections}}/ criados")

    console.print(f"\nDeseja extrair as conexões do Airbyte agora? [yes/n]: ", end="")
    if input().strip() == "yes":
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "cli.py"), "extract", f"--infra={infra}"], check=False)


def cmd_clone_infra(args):
    src = ROOT / "targets" / args.from_infra
    dst = ROOT / "targets" / args.infra

    if not src.exists():
        console.print(f"[red]targets/{args.from_infra}/ não encontrada.[/red]")
        sys.exit(1)

    if dst.exists():
        console.print(f"[yellow]targets/{args.infra}/ já existe. Sobrescrever? (yes/n)[/yellow] ", end="")
        if input().strip() != "yes":
            console.print("Cancelado.")
            return

    import shutil
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    console.print(f"[green]✓[/green] targets/{args.from_infra}/ → targets/{args.infra}/")

    env_src = ROOT / f".env.{args.from_infra}"
    env_dst = ROOT / f".env.{args.infra}"
    if not env_dst.exists():
        if env_src.exists():
            shutil.copy(env_src, env_dst)
            console.print(f"[yellow]~[/yellow] .env.{args.infra} copiado de .env.{args.from_infra} — [bold]atualize as credenciais![/bold]")
        else:
            console.print(f"[dim]Crie .env.{args.infra} ou rode: make setup-infra INFRA={args.infra}[/dim]")
    else:
        console.print(f"[dim].env.{args.infra} já existe, mantido.[/dim]")


def cmd_clean_airbyte(args):
    client = get_client(args.infra)
    console.print(f"[red bold]ATENÇÃO: isso apagará TODAS as conexões, sources e destinations do Airbyte '{args.infra}'.[/red bold]")
    confirm = input("Digite 'yes' para confirmar: ").strip()
    if confirm != "yes":
        console.print("[yellow]Cancelado.[/yellow]")
        return

    with console.status("[bold]Apagando conexões..."):
        for conn in client.list_connections():
            client.delete_connection(conn["connectionId"])
            console.print(f"  [red]✗[/red] conexão: {conn['name']}")

    with console.status("[bold]Apagando sources..."):
        for src in client.list_sources():
            client.delete_source(src["sourceId"])
            console.print(f"  [red]✗[/red] source: {src['name']}")

    with console.status("[bold]Apagando destinations..."):
        for dst in client.list_destinations():
            client.delete_destination(dst["destinationId"])
            console.print(f"  [red]✗[/red] destination: {dst['name']}")

    console.print(f"[green]✓[/green] Airbyte '{args.infra}' limpo.")


def cmd_diff(args):
    client = get_client(args.infra)
    with console.status("[bold]Comparando..."):
        results = diff_connections(client, args.infra, ROOT, select=args.select)

    title = f"Diff → {args.infra}" + (f"/{args.select}" if args.select else "")
    table = Table(title=title, show_lines=args.verbose)
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
    if parts:
        console.print("  ".join(parts))

    if changed and not args.verbose:
        console.print("[dim]Use --verbose / -v para ver o diff completo.[/dim]")


def main():
    parser = argparse.ArgumentParser(prog="cli", description="Airbyte IaC — gerencie conexões via YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="Lista conexões do Airbyte")
    p.add_argument("--target", "-t", required=True, help="Ex: prod, dev")

    p = sub.add_parser("pull", help="Extrai configs do Airbyte → YAML")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--select", "-s", default=None, help="Filtra por tag (ex: ga4, zendesk)")

    p = sub.add_parser("push", help="Aplica YAMLs no Airbyte")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--from", dest="from_target", default=None, help="Lê YAMLs de outro target (ex: --from=prod)")
    p.add_argument("--select", "-s", default=None, help="Aplica só um grupo (ex: ga4)")
    p.add_argument("--file", "-f", default=None, help="Aplica só um arquivo (requer --select)")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("status", help="Compara YAML local vs Airbyte")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--select", "-s", default=None)
    p.add_argument("--verbose", "-v", action="store_true")

    p = sub.add_parser("workspaces", help="Lista workspaces disponíveis")
    p.add_argument("--target", "-t", required=True)

    p = sub.add_parser("reset", help="Apaga todas as conexões, sources e destinations do Airbyte")
    p.add_argument("--target", "-t", required=True)

    p = sub.add_parser("init", help="Cria estrutura de pastas e .env para um novo target")

    p = sub.add_parser("clone", help="Clona YAMLs de um target para outro")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--from", dest="from_target", required=True)

    p = sub.add_parser("sync", help="Pull de um target e push para outro")
    p.add_argument("--target", "-t", required=True)
    p.add_argument("--from", dest="from_target", required=True)
    p.add_argument("--select", "-s", default=None)

    args = parser.parse_args()
    args.dry_run = getattr(args, "dry_run", False)
    args.verbose = getattr(args, "verbose", False)
    args.select = getattr(args, "select", None)
    args.file = getattr(args, "file", None)
    args.infra = getattr(args, "target", None)
    args.from_infra = getattr(args, "from_target", None)

    {
        "list": cmd_list,
        "pull": cmd_extract,
        "push": cmd_push,
        "status": cmd_diff,
        "workspaces": cmd_workspaces,
        "reset": cmd_clean_airbyte,
        "init": cmd_setup_infra,
        "clone": cmd_clone_infra,
        "sync": lambda a: (cmd_extract(a) or cmd_push(a)),
    }[args.command](args)


if __name__ == "__main__":
    main()

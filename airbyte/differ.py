"""Compara YAML local com estado atual do Airbyte e mostra diferenças."""
import json
import re
import yaml
from pathlib import Path
from deepdiff import DeepDiff
from .client import AirbyteClient


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _index_by_name(items: list) -> dict:
    return {item["name"]: item for item in items}


def _fmt_path(raw: str) -> str:
    parts = re.findall(r"\['([^']+)'\]|\[(\d+)\]", raw)
    result = []
    for word, idx in parts:
        if word:
            result.append(word)
        elif result:
            result[-1] += f"[{idx}]"
    return ".".join(result) or raw


def _format_diff(diff: DeepDiff) -> list[str]:
    lines = []
    d = json.loads(diff.to_json())

    for path, change in d.get("values_changed", {}).items():
        lines.append(f"{_fmt_path(path)}: {change['old_value']!r} → {change['new_value']!r}")

    for path, change in d.get("type_changes", {}).items():
        lines.append(f"{_fmt_path(path)}: {change['old_value']!r} → {change['new_value']!r}")

    for path in d.get("dictionary_item_added", []):
        lines.append(f"+ {_fmt_path(str(path))}")

    for path in d.get("dictionary_item_removed", []):
        lines.append(f"- {_fmt_path(str(path))}")

    for path, item in d.get("iterable_item_added", {}).items():
        name = item.get("name", str(item)) if isinstance(item, dict) else str(item)
        lines.append(f"+ {_fmt_path(path)}: {name!r}")

    for path, item in d.get("iterable_item_removed", {}).items():
        name = item.get("name", str(item)) if isinstance(item, dict) else str(item)
        lines.append(f"- {_fmt_path(path)}: {name!r}")

    return lines


def diff_connections(client: AirbyteClient, infra: str, root: Path, select: str = None) -> list:
    conn_base = root / "targets" / infra / "connections"
    if not conn_base.exists():
        return []

    if select:
        folders = [conn_base / select] if (conn_base / select).exists() else []
    else:
        folders = sorted(f for f in conn_base.iterdir() if f.is_dir())

    yaml_files = []
    for folder in folders:
        for f in sorted(folder.glob("*.yaml")):
            yaml_files.append((folder.name, f))

    if not yaml_files:
        return []

    existing = _index_by_name(client.list_connections())
    sources = {s["sourceId"]: s["name"] for s in client.list_sources()}
    destinations = {d["destinationId"]: d["name"] for d in client.list_destinations()}

    results = []
    local_names = set()

    for folder_name, yaml_file in yaml_files:
        local = _load_yaml(yaml_file)
        name = local["name"]
        local_names.add(name)
        label = f"{folder_name}/{yaml_file.name}"

        if name not in existing:
            results.append({"file": label, "status": "new", "diff": []})
            continue

        conn = existing[name]
        schedule_type = conn.get("scheduleType", "manual")
        schedule_data = conn.get("scheduleData") or None
        if schedule_type == "manual":
            schedule_data = None

        remote_streams = []
        for se in conn.get("syncCatalog", {}).get("streams", []):
            stream = se.get("stream", {})
            cfg = se.get("config", {})
            if not cfg.get("selected", False):
                continue
            remote_streams.append({
                "name": stream["name"],
                "namespace": stream.get("namespace", ""),
                "sync_mode": cfg.get("syncMode", "full_refresh"),
                "destination_sync_mode": cfg.get("destinationSyncMode", "overwrite"),
                "cursor_field": cfg.get("cursorField", []),
                "primary_key": cfg.get("primaryKey", []),
            })

        remote = {
            "name": conn["name"],
            "source": sources.get(conn["sourceId"], conn["sourceId"]),
            "destination": destinations.get(conn["destinationId"], conn["destinationId"]),
            "status": conn.get("status"),
            "schedule_type": schedule_type,
            "schedule": schedule_data,
            "namespace_definition": conn.get("namespaceDefinition"),
            "namespace_format": conn.get("namespaceFormat", ""),
            "prefix": conn.get("prefix", ""),
            "tags": conn.get("tags", []),
            "streams": remote_streams,
        }
        remote = {k: v for k, v in remote.items() if v is not None}

        local_cmp = {k: v for k, v in local.items() if k in remote}
        for k in remote:
            if k not in local_cmp:
                local_cmp[k] = None

        ddiff = DeepDiff(remote, local_cmp, ignore_order=True)

        if ddiff:
            results.append({"file": label, "status": "changed", "diff": _format_diff(ddiff)})
        else:
            results.append({"file": label, "status": "ok", "diff": []})

    for name in existing:
        if name not in local_names:
            results.append({"file": None, "status": "untracked", "name": name, "diff": []})

    return results

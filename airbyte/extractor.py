"""Extrai conexões, sources e destinations do Airbyte e salva como YAML."""
import yaml
from pathlib import Path
from .client import AirbyteClient

TAG_PREFIX = "select:"


def _slug(name: str) -> str:
    name = name.lower()
    for ch in ("→", "->", ">", "<"):
        name = name.replace(ch, "to")
    for ch in (" ", "/", "\\", ":", "*", "?", '"', "|", "[", "]"):
        name = name.replace(ch, "_")
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_")


def _select_tag(tags: list) -> str:
    for tag in tags:
        name = tag.get("name", "") if isinstance(tag, dict) else str(tag)
        if name.lower().startswith(TAG_PREFIX):
            return name[len(TAG_PREFIX):].strip()
    return "_other"


def _write_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def extract_sources(client: AirbyteClient, infra: str, root: Path):
    sources = client.list_sources()
    out = root / "infras" / infra / "sources"
    out.mkdir(parents=True, exist_ok=True)

    for src in sources:
        data = {
            "name": src["name"],
            "source_definition": src.get("sourceName", ""),
            "connection_configuration": src.get("connectionConfiguration", {}),
        }
        _write_yaml(out / f"{_slug(src['name'])}.yaml", data)

    return sources


def extract_destinations(client: AirbyteClient, infra: str, root: Path):
    destinations = client.list_destinations()
    out = root / "infras" / infra / "destinations"
    out.mkdir(parents=True, exist_ok=True)

    for dst in destinations:
        data = {
            "name": dst["name"],
            "destination_definition": dst.get("destinationName", ""),
            "connection_configuration": dst.get("connectionConfiguration", {}),
        }
        _write_yaml(out / f"{_slug(dst['name'])}.yaml", data)

    return destinations


def extract_connections(client: AirbyteClient, infra: str, root: Path, select: str = None):
    connections = client.list_connections()
    sources = {s["sourceId"]: s["name"] for s in client.list_sources()}
    destinations = {d["destinationId"]: d["name"] for d in client.list_destinations()}

    for conn in connections:
        tag = _select_tag(conn.get("tags", []))

        if select and tag != select:
            continue

        source_name = sources.get(conn["sourceId"], conn["sourceId"])
        destination_name = destinations.get(conn["destinationId"], conn["destinationId"])

        streams = []
        for se in conn.get("syncCatalog", {}).get("streams", []):
            stream = se.get("stream", {})
            config = se.get("config", {})
            if not config.get("selected", False):
                continue
            streams.append({
                "name": stream["name"],
                "namespace": stream.get("namespace", ""),
                "sync_mode": config.get("syncMode", "full_refresh"),
                "destination_sync_mode": config.get("destinationSyncMode", "overwrite"),
                "cursor_field": config.get("cursorField", []),
                "primary_key": config.get("primaryKey", []),
                # schema completo preservado para push sem discover_schema
                "json_schema": stream.get("jsonSchema", {}),
                "supported_sync_modes": stream.get("supportedSyncModes", []),
                "default_cursor_field": stream.get("defaultCursorField", []),
                "source_defined_cursor": stream.get("sourceDefinedCursor", False),
                "source_defined_primary_key": stream.get("sourceDefinedPrimaryKey", []),
            })

        schedule_type = conn.get("scheduleType", "manual")
        schedule = conn.get("scheduleData") or None
        if schedule_type == "manual":
            schedule = None

        data = {
            "name": conn["name"],
            "source": source_name,
            "destination": destination_name,
            "status": conn.get("status", "active"),
            "schedule_type": schedule_type,
            "schedule": schedule,
            "namespace_definition": conn.get("namespaceDefinition", "source"),
            "namespace_format": conn.get("namespaceFormat", ""),
            "prefix": conn.get("prefix", ""),
            "tags": [t["name"] if isinstance(t, dict) else t for t in conn.get("tags", [])],
            "streams": streams,
        }
        data = {k: v for k, v in data.items() if v is not None}

        out = root / "infras" / infra / "connections" / tag
        _write_yaml(out / f"{_slug(conn['name'])}.yaml", data)

    return connections

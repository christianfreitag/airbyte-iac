"""Extrai conexões, sources e destinations do Airbyte e salva como YAML."""
import os
import yaml
from pathlib import Path
from .client import AirbyteClient


def _slug(name: str) -> str:
    name = name.lower()
    for ch in ("→", "->", ">", "<"):
        name = name.replace(ch, "to")
    for ch in (" ", "/", "\\", ":", "*", "?", '"', "|", "[", "]"):
        name = name.replace(ch, "_")
    # colapsa múltiplos underscores
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_")


def extract_sources(client: AirbyteClient, env: str, output_dir: Path):
    sources = client.list_sources()
    out = output_dir / "sources" / env
    out.mkdir(parents=True, exist_ok=True)

    for src in sources:
        data = {
            "name": src["name"],
            "source_definition": src.get("sourceName", ""),
            "connection_configuration": src.get("connectionConfiguration", {}),
        }
        file = out / f"{_slug(src['name'])}.yaml"
        with open(file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return sources


def extract_destinations(client: AirbyteClient, env: str, output_dir: Path):
    destinations = client.list_destinations()
    out = output_dir / "destinations" / env
    out.mkdir(parents=True, exist_ok=True)

    for dst in destinations:
        data = {
            "name": dst["name"],
            "destination_definition": dst.get("destinationName", ""),
            "connection_configuration": dst.get("connectionConfiguration", {}),
        }
        file = out / f"{_slug(dst['name'])}.yaml"
        with open(file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return destinations


def extract_connections(client: AirbyteClient, env: str, output_dir: Path):
    connections = client.list_connections()
    sources = {s["sourceId"]: s["name"] for s in client.list_sources()}
    destinations = {d["destinationId"]: d["name"] for d in client.list_destinations()}

    out = output_dir / "connections" / env
    out.mkdir(parents=True, exist_ok=True)

    for conn in connections:
        source_name = sources.get(conn["sourceId"], conn["sourceId"])
        destination_name = destinations.get(conn["destinationId"], conn["destinationId"])

        streams = []
        for stream_entry in conn.get("syncCatalog", {}).get("streams", []):
            stream = stream_entry.get("stream", {})
            config = stream_entry.get("config", {})
            if not config.get("selected", False):
                continue
            streams.append({
                "name": stream["name"],
                "namespace": stream.get("namespace", ""),
                "sync_mode": config.get("syncMode", "full_refresh"),
                "destination_sync_mode": config.get("destinationSyncMode", "overwrite"),
                "cursor_field": config.get("cursorField", []),
                "primary_key": config.get("primaryKey", []),
            })

        schedule = conn.get("scheduleData", {})
        schedule_type = conn.get("scheduleType", "manual")

        data = {
            "name": conn["name"],
            "source": source_name,
            "destination": destination_name,
            "status": conn.get("status", "active"),
            "schedule_type": schedule_type,
            "schedule": schedule if schedule_type != "manual" else None,
            "namespace_definition": conn.get("namespaceDefinition", "source"),
            "namespace_format": conn.get("namespaceFormat", ""),
            "prefix": conn.get("prefix", ""),
            "tags": conn.get("tags", []),
            "streams": streams,
        }
        # remove None values
        data = {k: v for k, v in data.items() if v is not None}

        file = out / f"{_slug(conn['name'])}.yaml"
        with open(file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return connections

"""Aplica YAMLs no Airbyte — cria ou atualiza conexões, sources e destinations."""
import yaml
from pathlib import Path
from pydantic import ValidationError
from .client import AirbyteClient
from .models import ConnectionConfig


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _index_by_name(items: list, key: str = "name") -> dict:
    return {item[key]: item for item in items}


def push_connection(client: AirbyteClient, env: str, yaml_path: Path, dry_run: bool = False) -> dict:
    data = _load_yaml(yaml_path)

    try:
        validated = ConnectionConfig(**data)
    except ValidationError as e:
        raise ValueError(f"YAML inválido em {yaml_path.name}:\n{e}") from e

    sources = _index_by_name(client.list_sources())
    destinations = _index_by_name(client.list_destinations())

    source_name = validated.source
    destination_name = validated.destination

    if source_name not in sources:
        raise ValueError(f"Source '{source_name}' não encontrada no Airbyte. Crie-a primeiro.")
    if destination_name not in destinations:
        raise ValueError(f"Destination '{destination_name}' não encontrada no Airbyte. Crie-a primeiro.")

    source_id = sources[source_name]["sourceId"]
    destination_id = destinations[destination_name]["destinationId"]

    existing_schema = client.discover_schema(source_id)
    schema_streams = {
        s["stream"]["name"]: s
        for s in existing_schema.get("catalog", {}).get("streams", [])
    }

    sync_streams = []
    for stream_def in validated.streams:
        name = stream_def.name
        if name not in schema_streams:
            raise ValueError(f"Stream '{name}' não existe na source '{source_name}'.")

        base = schema_streams[name]
        base["config"] = {
            "selected": True,
            "syncMode": stream_def.sync_mode,
            "destinationSyncMode": stream_def.destination_sync_mode,
            "cursorField": stream_def.cursor_field,
            "primaryKey": stream_def.primary_key,
        }
        sync_streams.append(base)

    config = {
        "sourceId": source_id,
        "destinationId": destination_id,
        "name": validated.name,
        "status": validated.status,
        "scheduleType": validated.schedule_type,
        "scheduleData": validated.schedule or {},
        "namespaceDefinition": validated.namespace_definition,
        "namespaceFormat": validated.namespace_format,
        "prefix": validated.prefix,
        "tags": validated.tags,
        "syncCatalog": {"streams": sync_streams},
    }

    if dry_run:
        return {"_action": "dry-run", "config": config}

    existing = _index_by_name(client.list_connections())
    if validated.name in existing:
        conn_id = existing[validated.name]["connectionId"]
        result = client.update_connection(conn_id, config)
        result["_action"] = "updated"
    else:
        result = client.create_connection(config)
        result["_action"] = "created"

    return result


def push_all_connections(client: AirbyteClient, env: str, output_dir: Path, dry_run: bool = False) -> list:
    conn_dir = output_dir / "connections" / env
    if not conn_dir.exists():
        raise FileNotFoundError(f"Pasta {conn_dir} não encontrada.")

    results = []
    errors = []
    for yaml_file in sorted(conn_dir.glob("*.yaml")):
        try:
            result = push_connection(client, env, yaml_file, dry_run=dry_run)
        except (ValueError, Exception) as e:
            errors.append({"_file": yaml_file.name, "_action": "error", "_error": str(e)})
            continue
        result["_file"] = yaml_file.name
        results.append(result)

    return results + errors

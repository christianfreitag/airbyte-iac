"""Aplica YAMLs no Airbyte — cria ou atualiza conexões, sources e destinations."""
import yaml
from pathlib import Path
from pydantic import ValidationError
from .client import AirbyteClient
from .models import ConnectionConfig, SourceConfig, DestinationConfig


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _index_by_name(items: list, key: str = "name") -> dict:
    return {item[key]: item for item in items}


def _collect_results(fn, yaml_files) -> list:
    results, errors = [], []
    for yaml_file in yaml_files:
        try:
            result = fn(yaml_file)
        except Exception as e:
            errors.append({"_file": yaml_file.name, "_action": "error", "_error": str(e)})
            continue
        result["_file"] = yaml_file.name
        results.append(result)
    return results + errors


# ── Sources ───────────────────────────────────────────────────────────────────

def push_source(client: AirbyteClient, yaml_path: Path, dry_run: bool = False) -> dict:
    data = _load_yaml(yaml_path)
    try:
        validated = SourceConfig(**data)
    except ValidationError as e:
        raise ValueError(f"YAML inválido em {yaml_path.name}:\n{e}") from e

    existing = _index_by_name(client.list_sources())

    if validated.name in existing:
        source_id = existing[validated.name]["sourceId"]
        config = {"name": validated.name, "connectionConfiguration": validated.connection_configuration}
        if dry_run:
            return {"_action": "dry-run", "name": validated.name}
        result = client.update_source(source_id, config)
        result["_action"] = "updated"
    else:
        definitions = {d["name"]: d for d in client.list_source_definitions()}
        if validated.source_definition not in definitions:
            raise ValueError(f"Source definition '{validated.source_definition}' não encontrada.")
        config = {
            "name": validated.name,
            "sourceDefinitionId": definitions[validated.source_definition]["sourceDefinitionId"],
            "connectionConfiguration": validated.connection_configuration,
        }
        if dry_run:
            return {"_action": "dry-run", "name": validated.name}
        result = client.create_source(config)
        result["_action"] = "created"

    return result


def push_all_sources(client: AirbyteClient, infra: str, root: Path, dry_run: bool = False) -> list:
    d = root / "infras" / infra / "sources"
    if not d.exists():
        return []
    return _collect_results(lambda f: push_source(client, f, dry_run), sorted(d.glob("*.yaml")))


# ── Destinations ──────────────────────────────────────────────────────────────

def push_destination(client: AirbyteClient, yaml_path: Path, dry_run: bool = False) -> dict:
    data = _load_yaml(yaml_path)
    try:
        validated = DestinationConfig(**data)
    except ValidationError as e:
        raise ValueError(f"YAML inválido em {yaml_path.name}:\n{e}") from e

    existing = _index_by_name(client.list_destinations())

    if validated.name in existing:
        destination_id = existing[validated.name]["destinationId"]
        config = {"name": validated.name, "connectionConfiguration": validated.connection_configuration}
        if dry_run:
            return {"_action": "dry-run", "name": validated.name}
        result = client.update_destination(destination_id, config)
        result["_action"] = "updated"
    else:
        definitions = {d["name"]: d for d in client.list_destination_definitions()}
        if validated.destination_definition not in definitions:
            raise ValueError(f"Destination definition '{validated.destination_definition}' não encontrada.")
        config = {
            "name": validated.name,
            "destinationDefinitionId": definitions[validated.destination_definition]["destinationDefinitionId"],
            "connectionConfiguration": validated.connection_configuration,
        }
        if dry_run:
            return {"_action": "dry-run", "name": validated.name}
        result = client.create_destination(config)
        result["_action"] = "created"

    return result


def push_all_destinations(client: AirbyteClient, infra: str, root: Path, dry_run: bool = False) -> list:
    d = root / "infras" / infra / "destinations"
    if not d.exists():
        return []
    return _collect_results(lambda f: push_destination(client, f, dry_run), sorted(d.glob("*.yaml")))


# ── Connections ───────────────────────────────────────────────────────────────

def push_connection(client: AirbyteClient, yaml_path: Path, dry_run: bool = False) -> dict:
    data = _load_yaml(yaml_path)
    try:
        validated = ConnectionConfig(**data)
    except ValidationError as e:
        raise ValueError(f"YAML inválido em {yaml_path.name}:\n{e}") from e

    sources = _index_by_name(client.list_sources())
    destinations = _index_by_name(client.list_destinations())

    if validated.source not in sources:
        raise ValueError(f"Source '{validated.source}' não encontrada.")
    if validated.destination not in destinations:
        raise ValueError(f"Destination '{validated.destination}' não encontrada.")

    source_id = sources[validated.source]["sourceId"]
    destination_id = destinations[validated.destination]["destinationId"]

    schema_streams = {
        s["stream"]["name"]: s
        for s in client.discover_schema(source_id).get("catalog", {}).get("streams", [])
    }

    sync_streams = []
    for sd in validated.streams:
        if sd.name not in schema_streams:
            raise ValueError(f"Stream '{sd.name}' não existe na source '{validated.source}'.")
        base = schema_streams[sd.name]
        base["config"] = {
            "selected": True,
            "syncMode": sd.sync_mode,
            "destinationSyncMode": sd.destination_sync_mode,
            "cursorField": sd.cursor_field,
            "primaryKey": sd.primary_key,
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
        return {"_action": "dry-run", "name": validated.name}

    existing = _index_by_name(client.list_connections())
    if validated.name in existing:
        conn_id = existing[validated.name]["connectionId"]
        result = client.update_connection(conn_id, config)
        result["_action"] = "updated"
    else:
        result = client.create_connection(config)
        result["_action"] = "created"

    return result


def push_all_connections(client: AirbyteClient, infra: str, root: Path, select: str = None, dry_run: bool = False) -> list:
    conn_base = root / "infras" / infra / "connections"
    if not conn_base.exists():
        return []

    if select:
        folders = [conn_base / select] if (conn_base / select).exists() else []
    else:
        folders = sorted(f for f in conn_base.iterdir() if f.is_dir())

    results = []
    for folder in folders:
        for yaml_file in sorted(folder.glob("*.yaml")):
            try:
                result = push_connection(client, yaml_file, dry_run=dry_run)
            except Exception as e:
                results.append({"_file": f"{folder.name}/{yaml_file.name}", "_action": "error", "_error": str(e)})
                continue
            result["_file"] = f"{folder.name}/{yaml_file.name}"
            results.append(result)

    return results

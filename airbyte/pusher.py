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


def _run_all(fn, yaml_dir: Path) -> list:
    results, errors = [], []
    for yaml_file in sorted(yaml_dir.glob("*.yaml")):
        try:
            result = fn(yaml_file)
        except Exception as e:
            errors.append({"_file": yaml_file.name, "_action": "error", "_error": str(e)})
            continue
        result["_file"] = yaml_file.name
        results.append(result)
    return results + errors


# ── Sources ──────────────────────────────────────────────────────────────────

def push_source(client: AirbyteClient, yaml_path: Path, dry_run: bool = False) -> dict:
    data = _load_yaml(yaml_path)
    try:
        validated = SourceConfig(**data)
    except ValidationError as e:
        raise ValueError(f"YAML inválido em {yaml_path.name}:\n{e}") from e

    existing = _index_by_name(client.list_sources())

    if validated.name in existing:
        source_id = existing[validated.name]["sourceId"]
        # Envia connectionConfiguration de volta — campos mascarados (**) são
        # preservados pelo Airbyte, campos em texto são atualizados.
        config = {
            "name": validated.name,
            "connectionConfiguration": validated.connection_configuration,
        }
        if dry_run:
            return {"_action": "dry-run", "name": validated.name}
        result = client.update_source(source_id, config)
        result["_action"] = "updated"
    else:
        # Criar source nova requer credenciais reais no YAML
        definitions = {d["name"]: d for d in client.list_source_definitions()}
        if validated.source_definition not in definitions:
            raise ValueError(
                f"Source definition '{validated.source_definition}' não encontrada. "
                f"Verifique o nome exato em: make list-definitions ENV=..."
            )
        definition_id = definitions[validated.source_definition]["sourceDefinitionId"]
        config = {
            "name": validated.name,
            "sourceDefinitionId": definition_id,
            "connectionConfiguration": validated.connection_configuration,
        }
        if dry_run:
            return {"_action": "dry-run", "name": validated.name}
        result = client.create_source(config)
        result["_action"] = "created"

    return result


def push_all_sources(client: AirbyteClient, env: str, output_dir: Path, dry_run: bool = False) -> list:
    d = output_dir / "sources" / env
    if not d.exists():
        raise FileNotFoundError(f"Pasta {d} não encontrada. Rode make extract primeiro.")
    return _run_all(lambda f: push_source(client, f, dry_run), d)


# ── Destinations ─────────────────────────────────────────────────────────────

def push_destination(client: AirbyteClient, yaml_path: Path, dry_run: bool = False) -> dict:
    data = _load_yaml(yaml_path)
    try:
        validated = DestinationConfig(**data)
    except ValidationError as e:
        raise ValueError(f"YAML inválido em {yaml_path.name}:\n{e}") from e

    existing = _index_by_name(client.list_destinations())

    if validated.name in existing:
        destination_id = existing[validated.name]["destinationId"]
        config = {
            "name": validated.name,
            "connectionConfiguration": validated.connection_configuration,
        }
        if dry_run:
            return {"_action": "dry-run", "name": validated.name}
        result = client.update_destination(destination_id, config)
        result["_action"] = "updated"
    else:
        definitions = {d["name"]: d for d in client.list_destination_definitions()}
        if validated.destination_definition not in definitions:
            raise ValueError(
                f"Destination definition '{validated.destination_definition}' não encontrada."
            )
        definition_id = definitions[validated.destination_definition]["destinationDefinitionId"]
        config = {
            "name": validated.name,
            "destinationDefinitionId": definition_id,
            "connectionConfiguration": validated.connection_configuration,
        }
        if dry_run:
            return {"_action": "dry-run", "name": validated.name}
        result = client.create_destination(config)
        result["_action"] = "created"

    return result


def push_all_destinations(client: AirbyteClient, env: str, output_dir: Path, dry_run: bool = False) -> list:
    d = output_dir / "destinations" / env
    if not d.exists():
        raise FileNotFoundError(f"Pasta {d} não encontrada. Rode make extract primeiro.")
    return _run_all(lambda f: push_destination(client, f, dry_run), d)


# ── Connections ───────────────────────────────────────────────────────────────

def push_connection(client: AirbyteClient, env: str, yaml_path: Path, dry_run: bool = False) -> dict:
    data = _load_yaml(yaml_path)

    try:
        validated = ConnectionConfig(**data)
    except ValidationError as e:
        raise ValueError(f"YAML inválido em {yaml_path.name}:\n{e}") from e

    sources = _index_by_name(client.list_sources())
    destinations = _index_by_name(client.list_destinations())

    if validated.source not in sources:
        raise ValueError(f"Source '{validated.source}' não encontrada. Rode push-sources primeiro.")
    if validated.destination not in destinations:
        raise ValueError(f"Destination '{validated.destination}' não encontrada. Rode push-destinations primeiro.")

    source_id = sources[validated.source]["sourceId"]
    destination_id = destinations[validated.destination]["destinationId"]

    existing_schema = client.discover_schema(source_id)
    schema_streams = {
        s["stream"]["name"]: s
        for s in existing_schema.get("catalog", {}).get("streams", [])
    }

    sync_streams = []
    for stream_def in validated.streams:
        if stream_def.name not in schema_streams:
            raise ValueError(f"Stream '{stream_def.name}' não existe na source '{validated.source}'.")
        base = schema_streams[stream_def.name]
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
    d = output_dir / "connections" / env
    if not d.exists():
        raise FileNotFoundError(f"Pasta {d} não encontrada.")
    return _run_all(lambda f: push_connection(client, env, f, dry_run), d)

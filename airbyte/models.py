"""Modelos Pydantic para validação de YAMLs antes de enviar ao Airbyte."""
from __future__ import annotations
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, model_validator


class StreamConfig(BaseModel):
    name: str
    namespace: str = ""
    sync_mode: Literal["full_refresh", "incremental"] = "full_refresh"
    destination_sync_mode: Literal["overwrite", "append", "append_dedup"] = "overwrite"
    cursor_field: List[Any] = []
    primary_key: List[Any] = []


class ConnectionConfig(BaseModel):
    name: str
    source: str
    destination: str
    status: Literal["active", "inactive", "deprecated"] = "active"
    schedule_type: Literal["manual", "basic", "cron"] = "manual"
    schedule: Optional[dict] = None
    namespace_definition: str = "source"
    namespace_format: str = ""
    prefix: str = ""
    tags: List[Any] = []
    streams: List[StreamConfig] = []

    @model_validator(mode="after")
    def check_schedule(self) -> ConnectionConfig:
        if self.schedule_type != "manual" and not self.schedule:
            raise ValueError(
                f"schedule_type='{self.schedule_type}' requer campo 'schedule' preenchido."
            )
        return self

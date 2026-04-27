TARGET  ?=
FROM    ?=
SELECT  ?=
FILE    ?=
VERBOSE ?=

_from    = $(if $(FROM),--from=$(FROM),)
_select  = $(if $(SELECT),--select=$(SELECT),)
_file    = $(if $(FILE),--file=$(FILE),)
_verbose = $(if $(VERBOSE),--verbose,)

help:
	@echo ""
	@echo "  make init                          Configura um novo target interativamente"
	@echo "  make pull   TARGET=prod            Extrai conexões do Airbyte → YAML"
	@echo "  make push   TARGET=prod            Aplica YAMLs no Airbyte"
	@echo "  make status TARGET=prod            Compara YAML local vs Airbyte"
	@echo "  make sync   TARGET=dev FROM=prod   Pull de prod e push para dev"
	@echo "  make clone  TARGET=stg FROM=prod   Clona YAMLs de um target para outro"
	@echo "  make reset  TARGET=dev             Apaga tudo no Airbyte (pede confirmação)"
	@echo "  make clean  TARGET=dev             Apaga pasta targets/dev/ local"
	@echo "  make list   TARGET=prod            Lista conexões do Airbyte"
	@echo "  make dry-run TARGET=prod           Simula push sem aplicar mudanças"
	@echo ""
	@echo "  Opções extras: SELECT=ga4  FILE=conn.yaml  VERBOSE=1"
	@echo ""

install:
	pip install -r requirements.txt

init:
	python cli.py init

pull:
ifeq ($(TARGET),)
	@for t in targets/*/; do [ "$$t" = "targets/example/" ] && continue; python cli.py pull --target=$$(basename $$t) $(_select); done
else
	python cli.py pull --target=$(TARGET) $(_select)
endif

push:
	python cli.py push --target=$(TARGET) $(_from) $(_select) $(_file)

dry-run:
	python cli.py push --target=$(TARGET) $(_from) $(_select) $(_file) --dry-run

status:
ifeq ($(TARGET),)
	@for t in targets/*/; do [ "$$t" = "targets/example/" ] && continue; python cli.py status --target=$$(basename $$t) $(_select) $(_verbose); done
else
	python cli.py status --target=$(TARGET) $(_select) $(_verbose)
endif

sync:
	python cli.py pull --target=$(FROM)
	python cli.py push --target=$(TARGET) --from=$(FROM) $(_select)

list:
ifeq ($(TARGET),)
	@for t in targets/*/; do [ "$$t" = "targets/example/" ] && continue; python cli.py list --target=$$(basename $$t); done
else
	python cli.py list --target=$(TARGET)
endif

workspaces:
	python cli.py workspaces --target=$(TARGET)

clone:
	python cli.py clone --target=$(TARGET) --from=$(FROM)

reset:
	python cli.py reset --target=$(TARGET)

clean:
	@read -p "Apagar targets/$(TARGET)/? Digite 'yes' para confirmar: " confirm; \
	[ "$$confirm" = "yes" ] && rm -rf targets/$(TARGET) && echo "targets/$(TARGET)/ removida." || echo "Cancelado."

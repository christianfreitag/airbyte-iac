TARGET  ?=
FROM    ?=
SELECT  ?=
FILE    ?=
VERBOSE ?=

_target  = $(if $(TARGET),--target=$(TARGET),)
_from    = $(if $(FROM),--from=$(FROM),)
_select  = $(if $(SELECT),--select=$(SELECT),)
_file    = $(if $(FILE),--file=$(FILE),)
_verbose = $(if $(VERBOSE),--verbose,)

help:
	@echo ""
	@echo "  Airbyte IaC — gerencie conexões como código"
	@echo ""
	@echo "  SETUP"
	@echo "    make init                              Configura um novo target (pergunta nome, URL, credenciais)"
	@echo ""
	@echo "  DIA A DIA"
	@echo "    make pull   TARGET=prod                Extrai sources, destinations e connections do Airbyte → YAML"
	@echo "    make pull                              Extrai de todos os targets em targets/"
	@echo "    make push   TARGET=prod                Aplica os YAMLs no Airbyte (sources → dest → connections)"
	@echo "    make status TARGET=prod                Compara YAML local vs estado atual do Airbyte"
	@echo "    make status                            Status de todos os targets"
	@echo "    make list   TARGET=prod                Lista todas as conexões com status e schedule"
	@echo ""
	@echo "  AMBIENTES"
	@echo "    make sync   TARGET=dev FROM=prod       Pull de prod + push para dev"
	@echo "    make clone  TARGET=stg  FROM=prod      Copia os YAMLs de prod para staging (sem subir)"
	@echo ""
	@echo "  OPÇÕES EXTRAS"
	@echo "    make push   TARGET=prod SELECT=ga4     Aplica só o grupo ga4"
	@echo "    make push   TARGET=prod SELECT=ga4 FILE=conn.yaml  Aplica um arquivo específico"
	@echo "    make push   TARGET=dev  FROM=prod      Lê YAMLs de prod e sobe no Airbyte dev"
	@echo "    make dry-run TARGET=prod               Simula o push sem aplicar nada"
	@echo "    make status TARGET=prod VERBOSE=1      Mostra o diff completo campo a campo"
	@echo ""
	@echo "  PERIGOSO"
	@echo "    make reset  TARGET=dev                 Apaga TUDO no Airbyte dev (pede confirmação)"
	@echo "    make clean  TARGET=dev                 Apaga a pasta targets/dev/ localmente"
	@echo ""

install:
	pip install -r requirements.txt

init:
	python cli.py init

pull:
	python cli.py pull $(_target) $(_select)

push:
	python cli.py push --target=$(TARGET) $(_from) $(_select) $(_file)

dry-run:
	python cli.py push --target=$(TARGET) $(_from) $(_select) $(_file) --dry-run

status:
	python cli.py status $(_target) $(_select) $(_verbose)

sync:
	python cli.py sync $(_target) $(_from) $(_select)

list:
	python cli.py list $(_target)

workspaces:
	python cli.py workspaces --target=$(TARGET)

clone:
	python cli.py clone --target=$(TARGET) --from=$(FROM)

reset:
	python cli.py reset --target=$(TARGET)

clean:
	python cli.py clean --target=$(TARGET)

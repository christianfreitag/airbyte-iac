TARGET  ?= prod
FROM    ?=
SELECT  ?=
FILE    ?=
VERBOSE ?=

_from    = $(if $(FROM),--from=$(FROM),)
_select  = $(if $(SELECT),--select=$(SELECT),)
_file    = $(if $(FILE),--file=$(FILE),)
_verbose = $(if $(VERBOSE),--verbose,)

install:
	pip install -r requirements.txt

init:
	python cli.py init

pull:
	python cli.py pull --target=$(TARGET) $(_select)

push:
	python cli.py push --target=$(TARGET) $(_from) $(_select) $(_file)

dry-run:
	python cli.py push --target=$(TARGET) $(_from) $(_select) $(_file) --dry-run

status:
	python cli.py status --target=$(TARGET) $(_select) $(_verbose)

sync:
	python cli.py pull --target=$(FROM)
	python cli.py push --target=$(TARGET) --from=$(FROM) $(_select)

list:
	python cli.py list --target=$(TARGET)

workspaces:
	python cli.py workspaces --target=$(TARGET)

clone:
	python cli.py clone --target=$(TARGET) --from=$(FROM)

reset:
	python cli.py reset --target=$(TARGET)

clean:
	@read -p "Apagar targets/$(TARGET)/? Digite 'yes' para confirmar: " confirm; \
	[ "$$confirm" = "yes" ] && rm -rf targets/$(TARGET) && echo "targets/$(TARGET)/ removida." || echo "Cancelado."

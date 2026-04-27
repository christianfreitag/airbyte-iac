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
	@python cli.py --help

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

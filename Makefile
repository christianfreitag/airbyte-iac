SELECT  ?= prod
FILE    ?=
VERBOSE ?=

_verbose     = $(if $(VERBOSE),--verbose,)
_select_conn = $(if $(FILE),--select-conn=$(FILE),)

install:
	pip install -r requirements.txt

extract:
	python cli.py extract --select=$(SELECT)

diff:
	python cli.py diff --select=$(SELECT) $(_verbose)

list:
	python cli.py list --select=$(SELECT)

push:
	python cli.py push --select=$(SELECT) $(_select_conn)

dry-run:
	python cli.py push --select=$(SELECT) --dry-run $(_select_conn)

workspaces:
	python cli.py workspaces --select=$(SELECT)

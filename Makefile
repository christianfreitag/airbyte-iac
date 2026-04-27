ENV     ?= prod
FILE    ?=
VERBOSE ?=

_verbose = $(if $(VERBOSE),--verbose,)
_file    = $(if $(FILE),--file=$(FILE),)

install:
	pip install -r requirements.txt

extract:
	python cli.py extract --env=$(ENV)

diff:
	python cli.py diff --env=$(ENV) $(_verbose)

list:
	python cli.py list --env=$(ENV)

push:
	python cli.py push --env=$(ENV) $(_file)

dry-run:
	python cli.py push --env=$(ENV) --dry-run $(_file)

workspaces:
	python cli.py workspaces --env=$(ENV)

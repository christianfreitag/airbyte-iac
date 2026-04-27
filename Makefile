INFRA   ?= prod
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

extract:
	python cli.py extract --infra=$(INFRA) $(_select)

diff:
	python cli.py diff --infra=$(INFRA) $(_select) $(_verbose)

list:
	python cli.py list --infra=$(INFRA)

push:
	python cli.py push --infra=$(INFRA) $(_from) $(_select) $(_file)

dry-run:
	python cli.py push --infra=$(INFRA) $(_from) $(_select) $(_file) --dry-run

workspaces:
	python cli.py workspaces --infra=$(INFRA)

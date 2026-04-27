# airbyte-iac

> GitOps for Airbyte — version, diff and apply connections, sources and destinations as YAML.

Manage your Airbyte infrastructure as code. Pull the current state from any Airbyte instance, track changes with git, and apply updates via a simple CLI. Supports multiple environments through `targets/` folders and git branches.

---

## How it works

```
Airbyte (prod) ──pull──▶ targets/prod/ (YAML) ──git commit──▶ main branch
                                                                     │
                                                              git checkout dev
                                                                     │
                                                         edit YAML / add streams
                                                                     │
                                                    make status TARGET=dev   ◀── compare
                                                                     │
                                                    make push   TARGET=dev   ◀── apply
```

Each **target** maps to one Airbyte instance via `.env.{target}`. Connections are grouped into subfolders by **select tag** (`select:ga4`, `select:zendesk`, etc.).

---

## Setup

```bash
git clone https://github.com/christianfreitag/airbyte-iac
cd airbyte-iac
make install
```

Configure a new target interactively:

```bash
make init
# → asks for name, URL, credentials, workspace ID
# → creates .env.{target} and targets/{target}/
```

Or create `.env.prod` manually from the example:

```bash
cp .env.example .env.prod
# fill in AIRBYTE_URL, AIRBYTE_CLIENT_ID, AIRBYTE_CLIENT_SECRET, AIRBYTE_WORKSPACE_ID
```

---

## Authentication

Three methods supported (pick one per `.env` file):

| Method | Variables |
|--------|-----------|
| OAuth 2.0 (recommended) | `AIRBYTE_CLIENT_ID` + `AIRBYTE_CLIENT_SECRET` |
| Static token | `AIRBYTE_TOKEN` |
| Basic auth | `AIRBYTE_USERNAME` + `AIRBYTE_PASSWORD` |

---

## Commands

| Command | Description |
|---------|-------------|
| `make init` | Configure a new target interactively |
| `make pull TARGET=prod` | Pull all sources, destinations and connections → YAML |
| `make push TARGET=prod` | Apply YAML: sources → destinations → connections |
| `make status TARGET=prod` | Compare local YAMLs against live Airbyte state |
| `make status TARGET=prod VERBOSE=1` | Full diff with all changed fields |
| `make list TARGET=prod` | List all connections with status, schedule and select tag |
| `make dry-run TARGET=prod` | Simulate push without applying changes |
| `make sync TARGET=dev FROM=prod` | Pull prod + push to dev |
| `make clone TARGET=staging FROM=prod` | Clone YAMLs from one target to another |
| `make reset TARGET=dev` | Delete all resources from an Airbyte instance |
| `make clean TARGET=dev` | Delete local `targets/dev/` folder |
| `make workspaces TARGET=prod` | List available workspaces |

### TARGET vs SELECT

| Parameter | What it does |
|-----------|--------------|
| `TARGET` | Which Airbyte instance to connect to (loads `.env.{TARGET}`, reads/writes `targets/{TARGET}/`) |
| `SELECT` | Filters connections by group tag — only processes connections tagged `select:{SELECT}` |

```bash
make pull   TARGET=prod                  # pull everything from prod
make pull   TARGET=prod SELECT=zendesk   # pull only zendesk connections
make push   TARGET=dev  SELECT=ga4       # push only ga4 connections to dev
make push   TARGET=dev  FROM=prod        # push prod YAMLs into dev Airbyte
make status TARGET=prod SELECT=autodro   # diff only autodro connections
```

---

## Tags and SELECT routing

Connections are automatically routed to subfolders based on their `select:*` tag in Airbyte:

```
targets/prod/connections/
├── ga4/          ← connections tagged select:ga4
├── zendesk/      ← connections tagged select:zendesk
└── _other/       ← connections with no select tag
```

Tag a connection in Airbyte with `select:ga4` and it will always extract to `targets/prod/connections/ga4/`. On push, `SELECT=ga4` applies only that folder.

---

## Workflow

### Bootstrap (first time)

```bash
make init               # configure prod target
make pull TARGET=prod   # extract everything from Airbyte
git add -A
git commit -m "chore: initial extract from prod"
git push origin main
```

### Making a change

```bash
git checkout -b feat/zendesk-schedule

# edit the connection YAML
vim targets/prod/connections/zendesk/zendsk_to_snow.yaml

# check what will change before applying
make status TARGET=prod VERBOSE=1

# apply only that connection
make push TARGET=prod SELECT=zendesk FILE=zendsk_to_snow.yaml

git add -A
git commit -m "feat: update zendesk sync schedule to 8am UTC"
git push origin feat/zendesk-schedule
# open PR → merge to main
```

### Replicate prod to dev

```bash
make sync TARGET=dev FROM=prod          # pull prod + push to dev
make sync TARGET=dev FROM=prod SELECT=ga4  # only ga4 group
```

---

## File structure

```
airbyte-iac/
├── targets/
│   ├── example/                    # example YAML structure (committed)
│   │   ├── sources/
│   │   ├── destinations/
│   │   └── connections/my-group/
│   ├── prod/                       # gitignored — your real configs
│   │   ├── sources/
│   │   ├── destinations/
│   │   └── connections/
│   │       ├── ga4/
│   │       └── zendesk/
│   └── dev/                        # gitignored
├── airbyte/
│   ├── client.py       # API client (OAuth, retry, tags)
│   ├── models.py       # Pydantic validation schemas
│   ├── extractor.py    # Pull from Airbyte → YAML
│   ├── differ.py       # Compare local vs remote
│   └── pusher.py       # Apply YAML → Airbyte
├── cli.py              # CLI entrypoint
├── Makefile
├── requirements.txt
├── .env.example
└── .gitignore          # targets/* gitignored (except example/)
```

---

## Connection YAML schema

```yaml
name: Zendesk → Snowflake
source: Zendesk Support
destination: Snowflake
status: active                   # active | inactive | deprecated
schedule_type: cron              # manual | basic | cron
schedule:
  cron:
    cronExpression: "0 8 * * *"
    cronTimeZone: UTC
namespace_definition: source
namespace_format: ""
prefix: ""
tags:
  - name: select:zendesk
    color: B4D9FB
  - name: prod
    color: F93E47
streams:
  - name: tickets
    sync_mode: incremental
    destination_sync_mode: append_dedup
    cursor_field: [updated_at]
    primary_key: [[id]]
  - name: users
    sync_mode: full_refresh
    destination_sync_mode: overwrite
```

---

## Requirements

- Python 3.9+
- Airbyte self-hosted (OSS) or Cloud
- `make` (Windows: `winget install GnuWin32.Make`)

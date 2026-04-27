# airbyte-gitops

> GitOps for Airbyte — version, diff and apply connections as YAML.

Manage your Airbyte connections as code. Extract the current state from any Airbyte instance, track changes with git, and apply updates via CLI. Supports multiple environments through git branches.

---

## How it works

```
Airbyte (prod) ──extract──▶ YAML files ──git commit──▶ main branch
                                                              │
                                                         git checkout dev
                                                              │
                                                    edit YAML / add streams
                                                              │
                                               make diff SELECT=dev  ◀── compare
                                                              │
                                               make push SELECT=dev  ◀── apply
```

**One environment per branch.** There are no `dev/` and `prod/` subfolders — the branch itself is the environment. Checkout `main` to manage prod; create a feature branch to test changes before promoting.

---

## Setup

```bash
git clone https://github.com/your-org/airbyte-gitops
cd airbyte-gitops
make install
```

Create a `.env.prod` file from the example:

```bash
cp .env.example .env.prod
# fill in AIRBYTE_URL, AIRBYTE_CLIENT_ID, AIRBYTE_CLIENT_SECRET, AIRBYTE_WORKSPACE_ID
```

---

## Authentication

Three methods are supported (in priority order):

| Method | Variables |
|--------|-----------|
| OAuth 2.0 (recommended) | `AIRBYTE_CLIENT_ID` + `AIRBYTE_CLIENT_SECRET` |
| Static token | `AIRBYTE_TOKEN` |
| Basic auth | `AIRBYTE_USERNAME` + `AIRBYTE_PASSWORD` |

---

## Commands

| Command | Description |
|---------|-------------|
| `make extract SELECT=prod` | Pull all connections, sources and destinations from Airbyte → YAML |
| `make diff SELECT=prod` | Compare local YAMLs against live Airbyte state |
| `make diff SELECT=prod VERBOSE=1` | Full diff with all changed fields |
| `make list SELECT=prod` | List all connections with status and schedule |
| `make push SELECT=prod` | Apply everything: sources → destinations → connections |
| `make push SELECT=prod FILE=my_conn.yaml` | Apply a single connection |
| `make dry-run SELECT=prod` | Simulate push without applying changes |
| `make workspaces SELECT=prod` | List available workspaces |

`SELECT` can be any name — it loads `.env.{SELECT}` and saves/reads from `connections/{SELECT}/`. Examples: `prod`, `staging`, `autoforce`, `local`.|

---

## Workflow

### Bootstrap (first time)

```bash
# Pull everything from prod and commit
make extract SELECT=prod
git add -A
git commit -m "chore: initial extract from prod"
git push origin main
```

### Making a change

```bash
# Work on a feature branch
git checkout -b feat/zendesk-schedule

# Edit the connection YAML
vim connections/prod/zendsk_to_snow.yaml

# Check what will change before applying
make diff SELECT=prod --verbose

# Apply
make push SELECT=prod FILE=zendsk_to_snow.yaml

# Commit the new state
git add -A
git commit -m "feat: update zendesk sync schedule to 8am UTC"
git push origin feat/zendesk-schedule
# open PR → merge to main
```

---

## File structure

```
airbyte-gitops/
├── connections/prod/      # One YAML per connection
├── sources/prod/          # One YAML per source
├── destinations/prod/     # One YAML per destination
├── airbyte/
│   ├── client.py          # API client (retry, auth)
│   ├── models.py          # Pydantic validation schemas
│   ├── extractor.py       # Pull from Airbyte → YAML
│   ├── differ.py          # Compare local vs remote
│   └── pusher.py          # Apply YAML → Airbyte
├── cli.py                 # CLI entrypoint
├── Makefile
├── requirements.txt
└── .env.example
```

---

## Connection YAML schema

```yaml
name: Zendesk → Snowflake
source: Zendesk Support
destination: Snowflake
status: active                  # active | inactive | deprecated
schedule_type: cron             # manual | basic | cron
schedule:
  cron:
    cronExpression: "0 8 * * *"
    cronTimeZone: UTC
namespace_definition: source
namespace_format: ""
prefix: ""
tags: []
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

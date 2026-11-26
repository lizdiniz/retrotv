# retrotv-agent — the RetroTV product agent

A [Mistral Workflow](https://docs.mistral.ai/studio/workflows/) (`retrotv-product-agent`)
that runs the product loop for this repo, so RetroTV ships without manual busywork.

## Modes (`ProductAgentInput.mode`)

| mode | behavior | writes |
|---|---|---|
| `triage` | classify untriaged open issues (category/priority/summary/duplicate), then label + comment | labels, comments |
| `roadmap` | rebuild `ROADMAP.md` from open issues + merged PRs + README | `ROADMAP.md` |
| `release` | changelog from recent commits → `release/<version>` branch + draft PR | `CHANGELOG.md`, branch, PR |
| `digest` | weekly activity digest as a `digest` issue | one issue |
| `github_event` | instant triage of a webhook payload (new issue/PR) | labels, comment |

All modes accept `dry_run: true` (compute, write nothing). A raw GitHub webhook
payload as input is auto-detected: mode becomes `github_event` and `repo` comes
from `repository.full_name`.

GitHub via the `github_app` connector; LLM via the plugin's `chat_parse_to_model`.
`on_behalf_of=True`: user-started runs act as that user. Scheduled/webhook runs
additionally need a **workspace-scope credential** on `github_app` in Studio.

## Layout / run

```
Dockerfile                  # worker image for the managed deployment
pyproject.toml              # deps: mistralai-workflows[mistralai], pydantic
src/worker/entrypoint.py    # discovers worker.workflows, runs the worker
src/worker/workflows/product_agent.py
tests/                      # pytest, external effects faked (8 tests)
```

```bash
uv venv .venv && uv pip install -p .venv/bin/python -e ".[dev]"
PYTHONPATH=src .venv/bin/python -m pytest -q    # 8 passed
```

## Deploy

Managed deployment from this repo: build dir `agent/`, dockerfile `Dockerfile`,
deployment name `retrotv-agent`, `hardened=true` (OBO). Then: one manual
`{"mode":"triage","dry_run":true}` run to validate, weekly schedules
(triage/roadmap/digest), and a GitHub webhook trigger (`issues` +
`pull_request` events) wired through a Studio webhook.

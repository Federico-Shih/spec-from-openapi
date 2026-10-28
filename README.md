# Spec from OpenAPI

A `nanoagent.plugin/v0001` plugin, created by `nanoagent plugin new` with the
structure of NanoAgent's reference plugin,
[arxiv-source](https://github.com/zeyuyang8/arxiv-source).

An agent reads a bundled OpenAPI 3 document, probes the in-process mock API
that serves it, and writes a declarative source spec in `spec.json`: the
`base_url`, the `auth` kind and `auth_ref` (a credential NAME, never a key), and
endpoints with `path`, `method`, `params`, `record_selector` and `paginator`.
The spec's fields are the REST part of Empiric's `SourceSpec`. The verifier
checks it against the document and the probes in the call ledger, so no
endpoint can be made up. Everything ships in `src/plugin/fixtures/`
(`aqua-metrics.json`, the document, and `records.json`, the mock API's data),
so every run is the same and needs no network.

The document is bundled, not passed as a run config `inputs:` file: the mock
API has to serve exactly the document's operations, and the verifier's hidden
facts (which params the API honours, how it really pages) belong to it. The
task names it by its `document` argument (`aqua-metrics`). The document hides a
few traps: endpoints the goal does not need (`/v1/status`, a partner-only
`POST /v1/stations` under a second, bearer scheme), a cursor paginator on
`/v1/observations` that only a probe's `next_cursor` shows, a declared `limit`
that observations ignore and a declared `page` that alerts ignore, and an
example key in the API-key scheme's description. On top of those:

- The first server listed, `https://v0.aquametrics.example`, is deprecated
  (`x-deprecated`): `base_url` must be one of the other two.
- `GET /v1/observations` declares its own security, `ObservationsQueryKey` (an
  API key in the `api_key` query param, credential `AQUA_OBSERVATIONS_KEY`),
  which replaces the document's default `ApiKeyHeader`. `read_openapi` gives
  the document as written: each operation's own `security`, `null` where the
  default applies, and the document's `default_security`.
- Observations nest their records in `data.items`, and the document declares
  only the top-level `data`: `record_selector` is `$.data.items`, which only a
  probe shows.

The example (`aqua-metrics`, goal `observations`) meets every one: its spec
is `https://api.aquametrics.example` (or the sandbox), `api_key_query`,
`AQUA_OBSERVATIONS_KEY`, and `GET /v1/observations` with `station_id`, a cursor
paginator on `$.next_cursor` and the selector `$.data.items`.

## Tools

| Tool | Does | Code |
|---|---|---|
| `read_openapi` | Returns the document as written, typed: its servers (each with its description and whether it is deprecated), its default security, every operation with its declared params, own security (`null` where the default applies) and response shape, and every security scheme with its `credential_ref` | `src/plugin/reading.py` |
| `probe` | Sends one request (path, method, query params) to the mock API and returns the body as JSON text; an undeclared path or method, a repeated param or a bad value raises, and params the API does not honour are ignored | `src/plugin/probing.py` |
| `write_spec` | Writes the whole spec to `spec.json`, replacing any earlier one | `src/plugin/writing.py` |
| `openapi_index` | The hidden reference: every declared operation with its declared and honoured params and its real paginator, the servers, the goal's endpoint, its auth kind and ref, and the document's example keys | `src/plugin/truth.py` |

The document, the mock API and its hidden facts live in `src/plugin/api.py`.

### Tasks

| Task | Does | Runner |
|---|---|---|
| `spec-from-openapi` | Writes a spec for the goal's records (`observations`, `stations`, `alerts` or `regions`) in `spec.json` and submits its path; checked against `openapi_index` and the ledger's probes | `agent`, with `read_openapi`, `probe` and `write_spec` |

The verdict's `details.checks` lists every check below, in order (`verify_task`
in `verifier/spec.py`).

## Checks

Every entry has the same keys: `{id, constraint, ok, expected, actual, message}`.
`ok` is `true` (holds), `false` (fails) or `null` (not checked, because a check
it needs did not hold: its message is `Not checked: <id> did not hold.`).
`expected` and `actual` are set where they say something concrete (for the
endpoint checks, only the endpoints that fail, keyed `METHOD path`) and `null`
otherwise. `message` is `""` when the check holds. Checks 1 to 5 guard the
verdict's inputs; 6 to 16 judge what the spec says.

| # | id | What it checks | Example failure message |
|---|---|---|---|
| 1 | `reference` | The hidden `openapi_index` reference was pinned | no reference: openapi_index was not pinned |
| 2 | `spec-written` | `write_spec` wrote `spec.json` and it is JSON | no spec.json: write_spec was never called |
| 3 | `spec-shape` | `spec.json` is a SourceSpec as `write_spec` writes it | spec.json is not {base_url, auth, auth_ref, endpoints} |
| 4 | `ledger` | The call ledger is well formed | the call ledger is broken: ledger line 4 is not JSON |
| 5 | `no-leak` | `auth_ref` is an UPPER_SNAKE_CASE credential NAME and the document's example key appears nowhere in `spec.json` | spec.json holds a key, not a credential NAME (auth_ref) |
| 6 | `submitted-path` | The submitted path is `spec.json` | the submitted path is 'specs/spec.json', not spec.json |
| 7 | `base-url` | `base_url` is a declared server that is not deprecated | base_url https://v0.aquametrics.example is not a declared, current server |
| 8 | `auth` | `auth` is the kind of the goal endpoint's own security scheme | auth is api_key_header, but GET /v1/observations uses api_key_query |
| 9 | `auth-ref` | `auth_ref` is that scheme's credential NAME | auth_ref is AQUA_METRICS_API_KEY, but GET /v1/observations needs AQUA_OBSERVATIONS_KEY |
| 10 | `has-endpoints` | The spec has at least one endpoint | spec.json has no endpoints |
| 11 | `goal-endpoint` | The goal's endpoint is in the spec | the spec has no GET /v1/regions |
| 12 | `endpoints-declared` | Every endpoint's path and method is a declared operation | POST /v1/regions is not declared by the document |
| 13 | `params-declared` | Every declared endpoint sends only params the document declares, none repeated | GET /v1/observations sends params the document does not declare, or repeats one |
| 14 | `params-honoured` | Every declared endpoint sends only params the API honours | GET /v1/observations sends params the API ignores |
| 15 | `paginator` | Every declared endpoint has the API's real paginator (`type`, `param` and, for a cursor, `cursor_path`) | GET /v1/alerts has the wrong paginator |
| 16 | `record-selector` | Every declared endpoint's `record_selector` (`$`, `$.key...`, optional `[*]`) picks a JSON array out of at least one successful probe of it in the ledger | GET /v1/observations has a record_selector no probe of it bears out |

Checks 12 to 16 are not checked when the spec has no endpoints; 13 to 16 judge
only the declared endpoints and are not checked when none is; 16 is not checked
when the ledger is broken. The outcome checks still run when an integrity check
other than `reference`, `spec-written` or `spec-shape` fails, so the verdict
shows what else was wrong.

### How it is scored

- **Valid** only when all 16 checks hold, and then the score is 1.0.
- **Score 0** when any of checks 1 to 5 fails: a missing reference, a missing or
  malformed `spec.json`, a broken ledger, or a leaked key.
- **Otherwise** the score is the mean of six parts, at most 0.99: `path`,
  `base_url`, `auth`, `auth_ref` and `required_endpoint` (each 1 or 0), and
  `endpoints`, each endpoint's fraction of its five checks (declared, params
  declared, params honoured, paginator, record selector) averaged over the
  spec's endpoints, an undeclared endpoint scoring 0. A spec is a handful of
  independent decisions, each a trap the document sets (the deprecated server,
  the overridden security, the cursor and nested records only a probe shows),
  so each decision weighs the same and a spec that gets five of six right
  scores close to 1. Averaging over endpoints means an extra wrong endpoint
  costs a right spec something without zeroing it. E.g. the alerts spec with no
  paginator scores (5 + 0.8) / 6 = 0.9667.
- **The message** is a valid spec's summary (`the spec reads GET
  /v1/observations as the document and probes say`), or the first failing
  check as `<id>: <message>`, with ` (+N more)` when N more fail, e.g.
  `has-endpoints: spec.json has no endpoints (+1 more)`.
- **`details`** also holds `parts` (the six parts), `failed_endpoints` (each
  failing endpoint's failed checks) and `leak`.

## Layout

```text
.
├── nanoagent.yaml   # manifest (a slimconfig ManifestConfig): id, runtime, permissions, tools, tasks
├── contract.py      # each tool's and task's typed input and output: slimconfig Output classes
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env             # environment variable NAMEs this plugin needs, never values
├── src/plugin/      # the MCP server: __main__.py, its IMPLEMENTATIONS, one module per tool, api.py, engine.py
│   └── fixtures/    # the OpenAPI document, aqua-metrics.json, and the mock API's records.json
├── tests/
│   ├── run_agent.sh # one agent run on OpenRouter: config, nanoagent plugin agent, verdict
│   ├── examples/    # the task's example arguments, <id>.json
│   └── results/     # one folder per agent run (git-ignored)
├── ui/              # how the page draws the outputs: renderers.js and renderers.css
├── product/         # the product page a catalog shows: product.yaml and icon.svg
└── verifier/        # deterministic verifier package
```

`contract.py` is the one place a value's shape is declared. Its `Output`
classes are the JSON Schemas the server offers and the agent sees, and every
input and output is built into its class on the way in and out: the server,
NanoAgent and the verifier all get typed values, never loose dicts. A tool
that fails raises; NanoAgent sees an MCP error.

To add a tool: add a `Tool` member, its input and output classes and its
`TOOLS` entry to `contract.py` (a snake_case name, classes named `...Input`
and `...Output`); write its implementation in `src/plugin/`, taking its input
and the workspace and returning its output; write its `verify_input` /
`verify_output` in `verifier/`, and tests for both. Then register it in
`src/plugin/__main__.py` (`IMPLEMENTATIONS`), `verifier/__init__.py` (`TOOLS`),
`nanoagent.yaml` (`tools`) and this README's Tools table; a task goes in its
Tasks table.

`LICENSE` stays the template's MIT license under your name, `.gitignore`
keeps its entries, and this README keeps its title and sections: NanoAgent refuses a plugin
that changes them (rule 10 of `nanoagent.plugin.manifest`). Renaming the
plugin means renaming it in `nanoagent.yaml` and this title together.

To add a task, add a `Task` member (a kebab-case id) and its `TASKS` input and
output classes to `contract.py`, and declare it in `nanoagent.yaml` with its `runner` (`tool`,
`agent` or `decide`) and a `reference` tool, or `null` if it has none. A `tool`
task's classes are its tool's; an `agent` task's agent ends by calling `submit`
with the task's output; a `decide` task's model only chooses, and every tool
argument and output field is an Enum or bool, or copied from a value of exactly
its type in the task's input or an earlier tool output. Then add the check of
its output, `verify_task(arguments, output, reference, workspace)`, to `TASKS`
in `verifier/__init__.py`. People use the plugin by chatting with its agent,
which runs its tasks and shows each output on the page (see `ui/`).

## Develop and run

```bash
uv sync --extra dev
uv run pytest && uv run ruff check . && uv lock --check
```

Run the task with `nanoagent plugin agent`: its run config names this plugin,
the `spec-from-openapi` task and its arguments, `document: aqua-metrics` and a
`goal` (`observations` is the hardest: its cursor shows only in a probe; `regions`
is a root array with no params). No run config `inputs:` file is needed.

To run the agent, with NanoAgent on `PATH` and an OpenRouter key:

```bash
export OPENROUTER_API_KEY=...          # or ENV_FILE=path/to/keys.env
tests/run_agent.sh                     # tests/examples/spec-from-openapi.json
tests/run_agent.sh path/to/arguments.json
```

The script writes a NanoAgent run config (`PluginOpenRouterAgentConfig`), runs
`nanoagent plugin agent`, prints the verdict and exits 0 only when it is
valid. Each run goes to `tests/results/<time>/`, next to the config it ran as
`tests/results/<time>.yaml`: `result.json` (what the agent submitted),
`verdict.json`, `reference.json` (the pinned reference), `messages.json` (the
trajectory), `run.log` and `workspace/` with `.ledger/calls.jsonl`. `MODEL`,
`MAX_STEPS` and `TIMEOUT` override the defaults (`deepseek/deepseek-v4-flash`,
80 steps, 60 seconds per tool call).

Publishing checks every plugin rule: push the plugin to a public GitHub
repository and run `rush publish <server> <github-url>`.

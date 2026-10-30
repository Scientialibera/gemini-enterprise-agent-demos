# Deployment

Everything that turns this repository into a running environment: one config file,
one runner, and the steps it calls. Run from the repository root.

~~~bash
cp deployment/config.example.yaml deployment/config.yaml   # then fill it in
uv run --group dev python deployment/run.py                # check, seed, deploy, test
~~~

## The main config: `config.yaml`

[`config.example.yaml`](config.example.yaml) lists every setting with a comment: the
project and app, OAuth clients, each agent's settings, the Atlassian site, what to seed
and what the tests may touch. Copy it to `deployment/config.yaml` (gitignored).

- **Validated.** An unknown key is an error, not a silently ignored setting.
- **No secrets in the file.** OAuth clients point at the JSON the console downloads
  (keep them in `deployment/secrets/`, also gitignored); API keys and tokens live in
  Secret Manager, and `secrets.<id>.from_env` names an environment variable to seed a
  first value from.
- **The shell wins.** A variable already set in the environment overrides the file, so
  CI can change one value without editing it. `DEPLOYMENT_CONFIG=<path>` selects another
  file, for example one per environment.

`config/main_config.py` holds the schema and exports the file as the environment
variables the rest of the code reads. `deployment/.env.dev`, if present, is still read
for one-off overrides; `deployment/.env.local` serves `run_local.py`.

## The runner: `run.py`

~~~bash
uv run --group dev python deployment/run.py            # all: check, seed, deploy, test
uv run --group dev python deployment/run.py check      # what only a person or the console can do
uv run --group dev python deployment/run.py seed
uv run --group dev python deployment/run.py deploy --only ticket_guidance_agent
uv run --group dev python deployment/run.py test --only kitchen_sequencer
~~~

| Mode | Does | Changes anything |
|---|---|---|
| `check` | Reports the app, the custom-MCP org policy, connectors and their link to the app, OAuth clients, secrets, and no-code agents whose published copy has drifted from the repository, each as OK or ACTION with where to fix it | No |
| `seed` | Platform step, then: secrets exist (first values from env vars), BigQuery sample and Kitchen tables, Drive sample files, Atlassian knowledge base space and pages plus a Jira project check, each as enabled in `seed` | Yes, idempotently |
| `deploy` | Platform step (APIs, staging bucket, baseline IAM if enabled), then each code agent (package, deploy or update, IAM, registration, prompt published to Parameter Manager) and each no-code agent (left alone when its published copy matches the repository, otherwise saved as a draft to publish) | Yes, idempotently |
| `test` | One end-to-end check per agent against what is deployed (below) | Only what `tests` allows |
| `all` | All four, in that order | |

Every step is idempotent: a run that stops is finished by running it again, and one
agent failing does not stop the others. `--only <names>` limits deploy and test;
`--skip-platform`, `--skip-code`, `--skip-no-code` and `--skip-register` skip parts.

What `test` checks:

| Agent | Check |
|---|---|
| Kitchen Sequencer, Recipe Editorial | Published with its BigQuery MCP connector, and its tables answer through the MCP server |
| Vendor Match | A dictionary lookup through the deployed runtime finds a known vendor |
| Ticket Guidance | KB search, a ticket created with the caller as reporter, then moved to Done (`tests.ticket_guidance_creates_tickets`) |
| Growth Analysis | The full pipeline writes a report Doc (`tests.growth_full_run`, several minutes) |
| Prompt Manager | Lists the code agents' live configurations (read-only) |

Code agents are tested as Gemini Enterprise runs them: a session on the deployed runtime
with your Google token in its state, so the tools act as you. Your ADC therefore needs the
Drive scope as well as cloud-platform:

~~~bash
gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/cloud-platform
~~~

**Not automatable**, so `check` reports them and the docs say where to do them: the
OAuth consent screen and clients, connectors and their actions, publishing no-code agents
in the agent designer (Create or Update), and each user's first Authorize. See the
[deployment guide](../docs/deployment-guide.md) and, for a client's IT team, the
[requirements workbook](../docs/requirements/Prod_IT_Requirements.xlsx).

## Layout

~~~text
deployment/
  config.example.yaml     the main config's schema, with comments
  run.py                  the runner: check | seed | deploy | test | all
  run_local.py            run one agent on the workstation, no deployment
  registry.py             agent and workflow metadata: packages, scopes, settings, IAM
  paths.py, gcp.py        repository paths and shared gcloud execution
  config/                 main config loader, environment contract, platform bootstrap
  seed/                   secrets, BigQuery, Drive, Atlassian
  deploy/                 build an archive, create or update a runtime (release.py)
    iam/                  exact Agent Identity IAM after the runtime exists
    register/             publish a runtime into a Gemini Enterprise app
    no_code/              publish agents/no_code/ into the app; create the MCP connector
  verify/                 preflight checks and the end-to-end tests
~~~

| Script | Purpose |
|---|---|
| run.py | The runner above. |
| deploy/release.py | One code agent: preflight, package, deploy or update, IAM, register. |
| run_local.py | Run one agent or workflow against real APIs using workstation credentials. |
| deploy/package_agent.py | Build an archive with one entry point and the packages it imports. |
| deploy/deploy_dev.py | Create a new runtime with Agent Identity and save its resource name. |
| deploy/update_dev.py | Update the runtime from saved state or DEV_REASONING_ENGINE. |
| deploy/iam/apply_agent_identity_iam.py | Apply explicitly configured roles to the exact deployed Agent Identity. |
| deploy/register/register_agent.py | Register the runtime and create a missing delegated authorization. |
| deploy/no_code/deploy_no_code.py | Save no-code agents as drafts, resolving their connectors; `--recreate` after a connector change; `--diff` and `--export` compare the live agent with the repository and pull designer edits back. |
| deploy/no_code/create_mcp_connector.py | Create the BigQuery MCP connector from a downloaded OAuth client JSON. |
| config/bootstrap_dev.py | The platform step: project, APIs, staging bucket, baseline IAM if enabled. |

Deployment creates a missing runtime parameter and publishes changes to prompt.md.
The release script chooses an update when saved state or DEV_REASONING_ENGINE matches
the selected project and region. State lives at
deployment/.state/<project-number>/<region>/<agent>.json. Explicit overrides are checked
before preflight; saved state is checked before any runtime update.

| Imported module | Purpose |
|---|---|
| registry.py | Agent and workflow metadata, source paths, OAuth scopes, runtime settings and exact identity grants. |
| config/main_config.py | The config.yaml schema and loader. |
| config/settings.py | Local and remote environment contract. |
| config/environment.py | Boolean and placeholder parsing. |
| config/bootstrap.py | Authentication, project, API, bucket and parameter checks. |
| deploy/state.py | Project and region validation, state lookup and migration. |
| deploy/sources.py | One validated source manifest for archives and SDK staging. |
| deploy/dependencies.py | Export runtime requirements from uv.lock. |
| deploy/runtime.py | SDK client, existing app and deployment configuration. |
| deploy/register/api_http.py, oauth.py | Authenticated Discovery Engine requests and OAuth client configuration. |
| deploy/register/native_workflow.py | Create or reuse a native wrapper referencing the workflow's ADK backend. |
| deploy/register/group_config.py, access_groups.py, agent_sharing.py | Optional access groups and agent-use permission. |
| deploy/no_code/spec.py, connectors.py | Load agent.yaml and prompt.md; find the app's connectors by type and server. |
| deploy/no_code/sync.py | Compare a live no-code agent with the repository; export designer edits back into it. |
| seed/\_\_init\_\_.py | The seed steps, in order, as enabled in `config.yaml`. |
| seed/secrets.py, drive.py, atlassian.py | Secrets and first values, the Drive sample files, the Atlassian space and Jira check. |
| seed/kitchen_compliance.py, sample_data.py, sample_drive_files.py | The Kitchen tables and the synthetic sample data. |
| verify/preflight.py, checks.py, session.py | The check and test modes. |

Adding an entry to AGENTS in registry.py makes it visible to every script above, whether
it is an agent or a workflow (`is_workflow=True` adds the native wrapper). Imports resolve
against deployment/, so a script in a subfolder puts that directory on sys.path first.

## Order of operations

Terraform first, then the runner. The platform stack grants the roles every Agent
Identity needs; a runtime deployed before it exists starts but fails when it reads its
own configuration. A sandbox with no platform stack can have the runner grant that
baseline instead (below).

| # | What | Where | When |
|---|---|---|---|
| 1 | APIs, baseline IAM, Secret Manager, observability | `infrastructure/` | Once per project |
| 2 | Gemini Enterprise app, OAuth consent screen and clients, connectors | Console | Once per project or app |
| 3 | `config.yaml` | Here | Once per environment |
| 4 | Check, seed, deploy, test | `run.py` | Every release |

`register_agent.py` prints the client setup when an OAuth client is missing. An existing
authorization is not updated when its registry scopes change; plan that migration and
renewed consent explicitly. When an AI assistant presents the client setup, it must use
the [OAuth client table format](../README.md#configure-delegated-oauth), with the exact
client name and both redirect URLs in each row.

The consent screen's **Data Access** scope list and, for an app in *Testing*, its
**Audience → Test users** are part of step 2. Enable the target service's API before
editing scopes, or the scope will not appear in the picker. Some organisations require
an administrator to allow the OAuth client or its scopes; see
[service scopes may need an administrator](../README.md#service-scopes-may-need-an-administrator).

### Running without the Terraform stack

The runner can stand up a sandbox end to end. Its platform step can create the
project, enable the APIs and create the staging bucket, and it can also grant the roles
every Agent Identity in the project needs:

~~~yaml
environment:
  enable_required_apis: true
  create_staging_bucket: true
  grant_agent_identity_baseline: true
  create_project: {enabled: true, billing_account_id: <billing-account>}
~~~

~~~bash
uv run --group dev python deployment/run.py
~~~

That baseline matters more than it looks. Every agent reads its model and instruction
from Parameter Manager under its own identity, so without it an agent deploys, starts,
and then fails on its first request with no permission to read anything. The roles
granted at project scope are `aiplatform.expressUser`,
`serviceusage.serviceUsageConsumer` and `parametermanager.parameterAccessor`.
`storage.objectViewer` is granted on the staging bucket only, so runtimes can read
their source archives. Both Terraform and this helper read those defaults from
infrastructure/runtime_iam_policy.json. The principal set covers future runtimes too.
Business data buckets and secrets require explicit grants to the exact agent identity;
see `agent_identity_secret_roles` below.

When upgrading an existing sandbox, grant staging and required business-bucket access
first, then have its IAM administrator remove the former project-wide objectViewer
binding. This helper only adds bindings. Terraform-managed projects remove the old
binding on apply when it is no longer in agent_identity_project_roles; explicit
overrides must also be updated.

`grant_agent_identity_baseline` is false by default and the caller needs project
IAM admin to use it. Leave it false wherever the platform stack is applied: IAM there
belongs to Terraform, and granting the same bindings from two places makes it unclear
which one owns them. Use it for a sandbox, a demo project or a first look at the
template, and apply the platform stack for anything shared.

## Sandbox controls

The platform step and the deployment preflight use the `environment` section of
`config.yaml`: `create_project` (with `billing_account_id` and one of `folder_id` or
`organization_id`), `enable_required_apis`, `create_staging_bucket` and
`staging_bucket_location`.

Project creation is opt-in and requires a billing account. Set at most one of the
folder and organization IDs. API enablement and missing staging-bucket creation are
enabled by default; set their flags to false to require pre-existing resources.
An empty staging location uses the region.

The CLI account needs permission for enabled setup operations. Python clients use ADC
for Parameter Manager and the fixture. Bootstrap reuses existing resources without
changing billing on an existing project. IAM changes require the explicit baseline
flag or configured per-agent grants and an already-authorized caller.

These are two different identities, and they are granted separately. A deployment can
succeed through ADC while `gcloud parametermanager parameters list` returns
`PERMISSION_DENIED` for the CLI account, which reads as a broken deployment but is only
a missing grant on the account running gcloud. To inspect a parameter the way the
runtime does, read it through ADC rather than the CLI, or grant the CLI account
`roles/parametermanager.parameterViewer`.

Use the platform stack in infrastructure/ for shared platform resources and baseline IAM.
Review its grants before deploying an agent with new resource-access requirements.

## Agent Identity IAM

Every remote Agent Engine is created with `identity_type=AGENT_IDENTITY`, so every
deployed agent receives its own Google-managed Agent Identity even when no additional
IAM is configured.

Agent-specific IAM is optional and parameterized from the agent package name:

~~~text
<AGENT>_AGENT_IDENTITY_ID=
<AGENT>_AGENT_IDENTITY_PROJECT_ROLES=
<AGENT>_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=
~~~

For `vendor_match_agent` these become:

~~~text
VENDOR_MATCH_AGENT_AGENT_IDENTITY_ID=
VENDOR_MATCH_AGENT_AGENT_IDENTITY_PROJECT_ROLES=
VENDOR_MATCH_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=
~~~

`*_AGENT_IDENTITY_ID` is an optional assertion, not the source of identity. Normally
leave it empty. The helper derives the exact principal from the deployed Reasoning
Engine. If a value is supplied and does not match, the command stops before changing
IAM.

Project roles are comma-separated. Use them only when project scope is actually
required:

~~~text
VENDOR_MATCH_AGENT_AGENT_IDENTITY_PROJECT_ROLES=roles/logging.logWriter
~~~

Cloud Storage bindings are resource-scoped and use
`gs://bucket=role|role;gs://other=role`:

~~~text
VENDOR_MATCH_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=gs://agent-test-bucket=roles/storage.objectViewer
~~~

`deploy_dev.py` and `update_dev.py` invoke the IAM helper automatically after the
runtime exists. You can also rerun only IAM after changing these settings:

~~~bash
uv run --group dev python deployment/deploy/iam/apply_agent_identity_iam.py --agent ticket_guidance_agent
~~~

Secret Manager access is declared only in the spec, as `agent_identity_secret_roles`,
and granted on each named secret rather than the project. Growth Analysis reads its
four API keys this way and Ticket Guidance its Jira token. The secret must exist
first (Terraform creates it from `managed_secrets`); the helper only grants access.

Without environment overrides, the helper applies grants declared in AgentSpec.
It makes no IAM calls only when neither the resolved spec nor overrides declare grants.
The Agent Identity also receives the common principal-set roles from Terraform.

The identity running this helper must already be allowed to change IAM on the target
project or bucket. The helper does not grant permissions to itself and rejects
`roles/owner` and `roles/editor`. Prefer resource-scoped bindings for data access.

## Kitchen Sequencer tables

Kitchen Sequencer answers from four curated tables rather than from Looker dashboards. Terraform rebuilds them daily with scheduled queries;
`run.py seed` builds them once immediately when `seed.bigquery.kitchen_compliance` is
true, from `agents.kitchen_sequencer.source_project` into `agents.kitchen_sequencer.dataset`
(at `dataset_location`).

The statements are `infrastructure/sql/kitchen_compliance/*.sql`, run in file order
with `${SOURCE_PROJECT}`, `${TARGET_PROJECT}` and `${TARGET_DATASET}` filled in. The
dataset is created if missing; the tables are replaced. Your ADC needs read access to
the source dataset and BigQuery job and table-create rights in the target project. The
helper grants nothing. Users of the agent need `roles/bigquery.dataViewer` on the
dataset (Terraform's `kitchen_compliance.reader_members`), since the agent queries as
them.

## Runtime parameter checks

Deployment defaults to the selected agent's `<package-name>-config` parameter. Leave
CONFIG_PARAMETER empty unless overriding it for a run. Delegated agents also default
to their own `<package-name>-authz` authorization.

The platform step checks a runtime parameter only when CONFIG_PARAMETER is set.
Deployment supplies the agent spec, so it can seed and synchronize the source prompt.
Other live settings remain unchanged when a prompt is published.

To change model settings or limits without updating code, publish a Parameter Manager
version and wait for the cache interval.
See [configuration management](../README.md#manage-configuration).

### Seeing which tools ran

ADK logs nothing that names a called tool, so a deployed agent's logs show model
requests but not the tools it chose. `tool_call_logging` in the agent's own parameter
turns that on: `names` records the call sequence, `argument_keys` adds which parameters
were supplied, and `full` adds their values. Publish a new version and it applies after
the cache interval, with no redeployment.

Raise it on one agent while investigating and leave the others at `off`, since each
agent reads its own parameter. Keep `full` for a deliberate debugging session: a
delegated tool's arguments are the signed-in user's own query text, and that level
writes them to Cloud Logging. See
[tool-call logging](../README.md#tool-call-logging).

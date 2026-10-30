# Gemini Enterprise agents

This repository holds six Gemini Enterprise agents (five business agents and a Prompt
Manager), and everything needed to deploy them end to end into
another Gemini Enterprise app: Terraform for the shared platform, Python for each code
agent, definitions for the no-code agents, and one runner that checks, seeds, deploys
and tests an environment from a single config file.

~~~text
agents/
  pro_code/      ADK agents and workflows, deployed to Agent Engine
  no_code/       no-code agents: instruction, model and connectors
packages/        gemini_shared, the library every code agent uses
infrastructure/  Terraform: APIs, IAM, secrets, observability, Kitchen tables
deployment/      config.yaml, run.py, and the seed, deploy and verify steps
docs/            deployment guide, IT requirements workbook
sample_data/     synthetic data for testing without the client's systems
tests/           unit tests
~~~

| Agent | Kind | What it does | Acts as |
|---|---|---|---|
| Growth Analysis (`agents/pro_code/growth_analysis_workflow`) | ADK workflow | Reads the store performance sheet, gathers weather, reviews, macro/labor data and industry and local news in parallel, diagnoses the weakest stores and publishes a Google Doc report. | Signed-in user for Sheets/Docs/Drive; its own identity for API keys |
| Vendor Match (`agents/pro_code/vendor_match_agent`) | ADK agent | Standardizes vendor names against the master dictionary in Drive, in reviewed batches, and commits approved mappings. | Signed-in user for Drive |
| Ticket Guidance (`agents/pro_code/ticket_guidance_agent`) | ADK agent | Answers one IT issue from the Confluence knowledge base, raises a Jira ticket and closes or escalates it. | Signed-in user for Confluence search; a Jira service account for tickets |
| Recipe Editorial (`agents/no_code/recipe_editorial_agent`) | No-code | Editorial QA of recipes from BigQuery, with an emailed report. | Signed-in user (BigQuery MCP, Gmail) |
| Kitchen Sequencer (`agents/no_code/kitchen_sequencer`) | No-code | Kitchen compliance insights from curated BigQuery tables (replacing the Looker dashboards). | Signed-in user (BigQuery MCP) |
| Prompt Manager (`agents/pro_code/parameter_updater`) | ADK agent | Shows and changes the code agents' live prompts, models and limits in Parameter Manager; every change is previewed as a diff and confirmed. | Its own identity (Parameter Manager viewer and version adder) |

**Prompts are configuration.** Each code agent's `prompt.md` is published to its own
Parameter Manager parameter (`<package>-config`) on every deploy, and the runtime reads
its instruction, model and limits from there, refreshing every 30 seconds. A prompt can
therefore be changed live, through the Prompt Manager agent or a new parameter version,
without a redeploy; the next deploy publishes `prompt.md` again, so commit lasting changes
there. No-code agents keep their prompt in the Gemini Enterprise agent definition.

An **agent** is conversational: it holds tools and decides which to call as the exchange
goes on. A **workflow** is a pipeline: its stages run in a fixed order and each hands
its result to the next. Both deploy the same way, to the same runtime, under the same
kind of identity. A **no-code agent** has no runtime: Gemini Enterprise runs it from an
instruction, a model and connectors, which is all `agents/no_code/` holds. See
[no-code agents](agents/no_code/README.md).

Deployment can optionally create per-agent security groups for user access. See
[agent access groups](docs/agent-access-groups.md). This is separate from runtime Agent
Identity IAM.

The deployment/ runner deploys to `dev`, `qa` or `prod` (`environment.name`). In `qa` and
`prod` it requires the target project to be confirmed (`--confirm-project` or
`DEPLOY_CONFIRM_PROJECT`), refuses the sandbox-only settings, and expects Terraform to have
applied the platform first; see the [production runbook](docs/prod-runbook.md). infrastructure/ contains the shared platform setup and baseline IAM.
Deployment never grants IAM to the caller itself. The per-agent IAM helper applies only
the roles each agent declares, to its exact Agent Identity, after its runtime exists, and
only when the caller already has permission to change IAM.

## Deploy everything to a new environment

~~~bash
cp deployment/config.example.yaml deployment/config.yaml   # fill it in
uv run --group dev python deployment/run.py                # check, seed, deploy, test
~~~

`deployment/config.yaml` is the one file that describes an environment: project, app,
OAuth clients, each agent's settings, the Atlassian site, what to seed and what the tests
may touch. `run.py` then runs four idempotent modes, also available one at a time:

| Mode | Does |
|---|---|
| `check` | Reports what only a person or the console can provide: the app, the custom MCP org policy, connectors, OAuth clients, secrets |
| `seed` | Secrets, BigQuery sample and Kitchen tables, Drive sample files, the Atlassian knowledge base |
| `deploy` | APIs, bucket and baseline IAM, then every code agent (with its prompt published to Parameter Manager) and every no-code agent |
| `test` | One end-to-end check per agent against what was deployed |

Some setup has no API and stays manual: the OAuth consent screen and clients, connectors
and their actions, publishing no-code agents in the agent designer, and each user's first
Authorize. `check` lists what is missing, and the step-by-step
**[deployment guide](docs/deployment-guide.md)** says where to do it. For a client whose
IT team must provision the environment, the
**[IT requirements workbook](docs/requirements/Prod_IT_Requirements.xlsx)** has one tab
per agent: services, identities, roles, OAuth clients, secrets, connectors, data access
and acceptance tests. See [deployment/README.md](deployment/README.md) for the runner.

## Set up the workstation

Install Python 3.12 or later, uv and the Google Cloud CLI. From this repository, run:

~~~bash
uv sync --all-packages --group dev
gcloud auth login
gcloud auth application-default login
~~~

The CLI uses the first login. Python clients use Application Default Credentials (ADC)
from the second. Local execution needs ADC; the deployment preflight checks both.

Run the checks before deploying:

~~~bash
uv run --group dev ruff format --check .
uv run --group dev ruff check .
uv run --group dev pytest
~~~

These tests use mocks for cloud calls. They do not replace testing the deployed agent
and its consent flow in Gemini Enterprise.
Dependency review and audit instructions are in [dependency security](docs/dependency-security.md).

## Run an agent locally

Copy deployment/.env.local.example to deployment/.env.local. Set the project and model, then write
the local instructions in AGENT_INSTRUCTION.

~~~bash
uv run --group dev python deployment/run_local.py --agent ticket_guidance_agent
~~~

Replace ticket_guidance_agent with another registered agent to run it. The local runner calls
real model and service APIs, so usage can incur charges.

Leave CONFIG_PARAMETER unset to read settings from the local environment. All three
code agents need an authorization ID to construct their tools, but user authentication
must be tested through Gemini Enterprise, which supplies the session token. Locally a
tool that acts as the user reports that no token is present. Secret Manager reads use
your ADC, or `<NAME>_VALUE` for an offline run.

## Deploy and register one agent

`deployment/run.py` runs the steps below for every agent. To release one agent, or to
understand what the full deploy does, read on.

There are two ways to stand a project up, and they differ only in who grants the roles
every Agent Identity needs.

**With the platform stack**, the normal path for anything shared. Apply
`infrastructure/` first: it owns the APIs, the baseline IAM, Secret Manager
and observability, and it grants those roles to a trust-domain principal set covering
every Agent Identity in the project, so an agent added later inherits them with no
infrastructure change. Then use the scripts here for everything per-agent.

**Without it**, for a sandbox, a demo project or a first look at the template. The dev
runner can do the whole thing: its platform step creates the project, enables the
APIs, creates the staging bucket and — with `environment.grant_agent_identity_baseline:
true` — grants that same baseline itself, to the same principal set. Nothing but this
repository is needed.

~~~bash
uv run --group dev python deployment/run.py deploy --only vendor_match_agent
~~~

The baseline is what lets an agent read its own model and instruction from Parameter
Manager. Without it a runtime deploys and starts, then fails on its first request. The
flag is off by default and needs project IAM admin: leave it off wherever Terraform is
applied, because granting the same bindings from two places makes it unclear which one
owns them.

Either way, the OAuth client, its consent screen and the Gemini Enterprise app are
created by hand, because no API exists for them. See
[order of operations](deployment/README.md#order-of-operations) for the full sequence.

Create or select a Gemini Enterprise app and copy deployment/config.example.yaml to
deployment/config.yaml. The settings below are the environment variables its keys map to
(see `deployment/config/main_config.py`); the minimum is:

~~~text
GOOGLE_CLOUD_PROJECT=<project-id>
GOOGLE_CLOUD_LOCATION=us-central1
DEV_STAGING_BUCKET=gs://<staging-bucket>
ENVIRONMENT=dev
GEMINI_ENTERPRISE_APP_ID=<engine-id>
~~~

Use the app's engine ID for GEMINI_ENTERPRISE_APP_ID. The scripts load .env files
without overriding variables already set in the shell.

~~~bash
uv run --group dev python deployment/deploy/release.py --agent vendor_match_agent
~~~

The release checks prerequisites, builds an archive, deploys or updates the runtime,
applies any explicitly configured Agent Identity IAM and then registers the runtime in
the app. It chooses an update when saved state or DEV_REASONING_ENGINE identifies a
runtime in the selected project and region. State is stored under
deployment/.state/<project-number>/<region>/<agent>.json. Matching older agent-only state files
are migrated automatically. A mismatched explicit runtime is rejected before preflight.
Keep this ignored state directory between releases.

Use --skip-register to stop after deployment. Registration is also skipped when the
app ID is empty. For a delegated agent, registration prints OAuth setup details if its
authorization is missing. Complete the setup below, then rerun register_agent.py.
You do not need to redeploy code just to register a runtime.

Splitting a first release into those two steps is worth doing for a delegated agent:
deployment touches no OAuth resource, so the consent screen can be finished between
them. **A deployed runtime does not appear in Gemini Enterprise until it is
registered** — registration creates the app listing, and without it the agent exists in
Vertex AI but is invisible in the UI.

~~~bash
uv run --group dev python deployment/deploy/release.py --agent <name> --skip-register
# Finish the consent screen, then register.
uv run --group dev python deployment/deploy/register/register_agent.py --agent <name>
~~~

| Script in deployment/ | Effect |
|---|---|
| run.py | Check, seed, deploy and test every agent from config.yaml (see deployment/README.md). |
| config/bootstrap_dev.py | The platform step: project, APIs, staging bucket, baseline IAM if enabled. |
| `deploy/package_agent.py --agent <name>` | Build an archive containing one agent and gemini_shared. |
| `deploy/deploy_dev.py --agent <name>` | Create a new Agent Engine with Agent Identity and save its resource name. |
| `deploy/update_dev.py --agent <name>` | Update the saved runtime, or the DEV_REASONING_ENGINE override. |
| `deploy/iam/apply_agent_identity_iam.py --agent <name>` | Apply configured IAM roles to the exact deployed Agent Identity. |
| `deploy/register/register_agent.py --agent <name>` | Create or update the app listing for the deployed runtime. |

Run each with `uv run --group dev python deployment/<script>`. deploy_dev.py creates a new
runtime on every run; use update_dev.py for an existing runtime. Registration matches
listings by display name, so keep that name stable when updating an existing listing.

The preflight creates a missing runtime parameter and publishes changes to prompt.md.
It can also enable missing APIs and create a staging bucket; both controls default to
enabled. Project creation is disabled by default. Check the
[developer controls](deployment/README.md#sandbox-controls) before using a shared project.

### Permissions and setup ownership

This table separates **who is responsible for granting or creating something** from
**whether it is technically automatable**. An administrator-owned IAM change can still
be performed by Terraform or code when the executing identity already has permission.
UI-only means the current Google/Gemini Enterprise workflow requires a console action.

| Requirement / permission | Needed by | Owner / grantor | How it is supplied | UI-only? |
|---|---|---|---|---|
| Access to the target GCP project | Developer / deployment identity | Cloud or platform admin | IAM, normally through the platform stack in infrastructure/ | No |
| Create/update Agent Engine resources | Developer / deployment identity | Cloud or platform admin | IAM grant; `deployment/deploy/deploy_dev.py` and `deployment/deploy/update_dev.py` consume it | No |
| Create the Agent Identity for a runtime | Agent Engine deployment | Google Agent Engine | `identity_type=AGENT_IDENTITY` in `deployment/deploy/deploy_dev.py`; Google provisions the identity | No |
| Baseline IAM shared by every Agent Identity | All deployed runtimes | Cloud/platform admin | Terraform principal-set bindings in infrastructure/ | No |
| Extra project-scoped IAM for one Agent Identity | One deployed runtime | IAM admin or authorized automation identity | `<AGENT>_AGENT_IDENTITY_PROJECT_ROLES` consumed by `deployment/deploy/iam/apply_agent_identity_iam.py` | No |
| Cloud Storage access for one Agent Identity | One deployed runtime | Storage/IAM admin or authorized automation identity | `<AGENT>_AGENT_IDENTITY_STORAGE_BUCKET_ROLES` consumed by `deployment/deploy/iam/apply_agent_identity_iam.py`; bucket scope preferred | No |
| Read/create the agent runtime parameter and publish versions | Developer deployment flow; runtime reads it | Cloud or platform admin grants access; dev tooling creates agent-owned parameters | IAM plus `deployment/config/bootstrap.py` / deployment preflight. The deploying identity **creates** parameters and publishes versions, so it needs write access such as `roles/parametermanager.parameterAdmin`; the baseline grants runtimes only `roles/parametermanager.parameterAccessor`, which reads. A first deployment fails at preflight without that grant. | No |
| Enable required Google Cloud APIs | Project | Cloud or platform admin, or developer with Service Usage permission | Terraform, or the runner's platform step when `environment.enable_required_apis` is true | No |
| Create/use the developer staging bucket | Developer deployment flow | Cloud or platform admin, or developer with Storage permission | Terraform/existing bucket, or the runner's platform step when `environment.create_staging_bucket` is true | No |
| Create the optional sample datasets and Kitchen tables | Developer | Data/cloud admin, or developer with BigQuery create permissions | `run.py seed` (`seed.bigquery`); unnecessary with real data | No |
| Query BigQuery through delegated auth | Signed-in Gemini Enterprise user | Data/IAM admin | User IAM on the target BigQuery project/dataset/table; the agent cannot elevate it | No |
| Gemini Enterprise application | Registration flow | Gemini Enterprise administrator | Create/select the app in the Gemini Enterprise admin UI; copy its engine ID to `config.yaml` (`gemini_enterprise.app_id`) | Yes for initial app creation |
| OAuth consent screen / test-user configuration | Delegated-auth agents | Google Cloud / Google Auth Platform administrator | Google Auth Platform console | Yes |
| Dedicated OAuth client ID and client secret for each delegated agent | Registration flow | Google Cloud / Google Auth Platform administrator | Create a Web application client in Google Auth Platform with both documented redirect URIs | Yes |
| Store the OAuth client secret in Secret Manager | Registration flow | Registration script using existing Secret Manager access | `deployment/deploy/register/register_agent.py` imports the initial secret when no stored version exists | No |
| Gemini Enterprise authorization resource | Delegated-auth agent | Registration flow using its caller permissions | `deployment/deploy/register/register_agent.py` creates/reuses the per-agent authorization | No |
| Gemini Enterprise agent listing / registration | End users | Registration flow using its caller permissions | `deployment/deploy/register/register_agent.py` creates/updates the app listing | No |
| Connectors (BigQuery MCP, Gmail, Confluence) | No-code agents, Ticket Guidance | Gemini Enterprise administrator | Create in the app's console; each holds an OAuth client or admin consent | Yes |
| No-code agent definition | End users | Deployment flow using its caller permissions | `deployment/deploy/no_code/deploy_no_code.py` creates/updates the agent from `agents/no_code/` | No: publish with one click in the agent designer |
| Agent secrets (API keys, Jira token) | Growth Analysis, Ticket Guidance | Cloud or platform admin | Terraform `managed_secrets` creates them; the release grants each agent accessor on its own | No |
| Read access for the Kitchen Sequencer refresh account | Scheduled queries | Owner of the source project | `roles/bigquery.dataViewer` on `hdr_analytics`, granted in that project | No |

The deployment helpers never grant IAM to the developer or otherwise self-elevate. The
Agent Identity IAM helper only grants the roles explicitly configured for the selected
runtime. Its caller must already have permission to update the target project's or
bucket's IAM policy. If that permission is missing, have an administrator run the IAM
helper or grant through the approved platform process. The helper rejects roles/owner
and roles/editor.

### Per-agent Agent Identity IAM

Every remote runtime is created with Agent Identity, including agents with no additional
resource permissions. The identity is therefore independent of the optional IAM config.

An agent declares the access its own tools need, in its AgentSpec, beside the OAuth
scopes it asks the user for:

~~~python
"ticket_guidance_agent": AgentSpec(
    delegated_oauth_scopes=(CLOUD_PLATFORM_SCOPE,),   # knowledge-base search as the user
    agent_identity_project_roles=(),                  # nothing project-wide
    agent_identity_secret_roles=(                     # reads its own Jira token only
        SecretRoles(JIRA_API_TOKEN_SECRET, (SECRET_ACCESSOR,)),
    ),
    runtime_env=(("JIRA_SITE_URL", "${JIRA_SITE_URL}"), ...),
)
~~~

Both lists are versioned, so adding or removing a permission is a reviewable one-line
change and a fresh clone deploys with the access its tools require. A bucket or a
runtime setting is named through a `${VARIABLE}` placeholder, so the repository says
which one an agent uses without committing any environment's IDs; a placeholder that
resolves to nothing is skipped rather than guessed at. Secrets are granted per secret,
never project-wide.

These lists only add roles. Removing an entry does not revoke an existing grant;
an IAM administrator must review and remove it separately. The helper verifies the
runtime's reported effective identity before granting access and rejects basic
Owner/Editor roles and unsupported legacy bucket roles.

Environment variable names are derived from the agent package name:

~~~text
<AGENT>_AGENT_IDENTITY_ID=
<AGENT>_AGENT_IDENTITY_PROJECT_ROLES=
<AGENT>_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=
~~~

For `vendor_match_agent` the prefix is `VENDOR_MATCH_AGENT`.
`*_AGENT_IDENTITY_ID` is optional and acts only as an assertion. Normally leave it
empty; the IAM helper derives the exact principal from the deployed Reasoning Engine.
If supplied and it does not match the runtime's actual Agent Identity, the helper fails
before changing IAM.

Project roles are comma-separated:

~~~text
VENDOR_MATCH_AGENT_AGENT_IDENTITY_PROJECT_ROLES=roles/logging.logWriter
~~~

Cloud Storage grants should normally be bucket-scoped:

~~~text
VENDOR_MATCH_AGENT_AGENT_IDENTITY_STORAGE_BUCKET_ROLES=gs://agent-test-bucket=roles/storage.objectViewer
~~~

Multiple bucket bindings use semicolons between buckets and `|` between roles on the
same bucket. `deploy_dev.py` and `update_dev.py` invoke the helper automatically after
the runtime exists. To change only IAM later:

~~~bash
uv run --group dev python deployment/deploy/iam/apply_agent_identity_iam.py --agent vendor_match_agent
~~~

If neither the resolved AgentSpec nor environment overrides declare grants, this helper
makes no IAM calls. The runtime
still has its unique Agent Identity and receives only the common project principal-set
roles from Terraform.

## Configure delegated OAuth

Use a separate OAuth client and authorization for each delegated agent in this template.
The defaults are `<package-name>-authz` for the authorization and
`<package-name>-oauth-client-secret` for its secret.

**For AI-assisted setup:** present OAuth client setup as a Markdown table, not a
paragraph. Use one row per delegated agent being deployed, with columns for the
agent, exact OAuth client name, application type and authorized redirect URIs.
Read names from `AgentSpec.oauth_client_name` and URLs from `OAUTH_REDIRECT_URIS`
in `deployment/deploy/register/register_agent.py`; do not guess them. Show both complete URLs
in every row so they can be copied into the matching client. Do not put client
secrets or tokens in the table. Show consent scopes separately, grouped by agent.

The current client setup is:

| Agent | OAuth client name | Application type | Authorized redirect URIs (add both) |
|---|---|---|---|
| `growth_analysis_workflow` | Growth Analysis (dev) | Web application | `https://vertexaisearch.cloud.google.com/static/oauth/oauth.html`<br>`https://vertexaisearch.cloud.google.com/oauth-redirect` |
| `vendor_match_agent` | Vendor Match Agent (dev) | Web application | `https://vertexaisearch.cloud.google.com/static/oauth/oauth.html`<br>`https://vertexaisearch.cloud.google.com/oauth-redirect` |
| `ticket_guidance_agent` | Ticket Guidance Agent (dev) | Web application | `https://vertexaisearch.cloud.google.com/static/oauth/oauth.html`<br>`https://vertexaisearch.cloud.google.com/oauth-redirect` |

Consent scopes, besides `openid`, `email` and `profile` for every agent:

| Agent | Scopes |
|---|---|
| `growth_analysis_workflow` | `spreadsheets.readonly`, `documents`, `drive` |
| `vendor_match_agent` | `drive` |
| `ticket_guidance_agent` | `cloud-platform` |

The no-code agents' BigQuery MCP connector needs its own Web client too, with the
`bigquery` scope; see [no-code agents](agents/no_code/README.md).

Configure the project's OAuth consent screen, including the test users and scopes
needed for your test. In Google Auth Platform, create a **Web application** client with
the name printed by register_agent.py. Add both callbacks used by this integration:

> **The consent screen is console-only, per-project and easy to miss.** No API edits
> its scope list, so `register_agent.py` prints the required scopes rather than
> applying them. Add them under **Google Auth Platform → Data Access → Add or remove
> scopes**, then **Update** and **Save**. The list is shared by every agent in the
> project, so a second agent asking for a scope already there needs no console change —
> which is why adding the first agent for a service feels like extra work and later
> ones do not. See [service scopes may need an
> administrator](#service-scopes-may-need-an-administrator).

~~~text
https://vertexaisearch.cloud.google.com/static/oauth/oauth.html
https://vertexaisearch.cloud.google.com/oauth-redirect
~~~

The authorization resource uses the first URI and the consent flow uses the second.
A missing callback can cause redirect_uri_mismatch when the user authorizes the agent.

Point each agent at its downloaded client JSON in `deployment/config.yaml` (keep the files
in the gitignored `deployment/secrets/`):

~~~yaml
oauth_clients:
  growth_analysis_workflow: {client_json: secrets/growth-analysis-client.json}
  vendor_match_agent: {client_json: secrets/vendor-match-client.json}
  ticket_guidance_agent: {client_json: secrets/ticket-guidance-client.json}
~~~

The loader sets `<AGENT>_OAUTH_CLIENT_ID` (and the secret, in memory only) from each file.
`client_id:` alone works once the secret is in Secret Manager.

~~~bash
uv run --group dev python deployment/deploy/register/register_agent.py --agent vendor_match_agent
~~~

When the stored secret is missing, registration imports the initial secret into Secret
Manager. The JSON file can be deleted after a successful import. Existing stored
secrets take precedence over environment values; rotate them in Secret Manager.

Registration checks for a mismatched client ID and secret before creating an
authorization. Existing authorizations are reused; rerunning registration does not
change their OAuth settings. If the client or scopes change, review the authorization
as a separate change and retest consent.

Because an existing authorization is never reconciled, finish the consent screen
**before** the first registration. An authorization created against a consent screen
that is missing a scope is not repaired by fixing the screen afterwards: delete that
authorization and register again.

Verify what was created rather than assuming, since the authorization records the
scopes at creation time:

~~~bash
TOKEN=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  -H "X-Goog-User-Project: <project-id>" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/<project-number>/locations/global/authorizations/<package-name>-authz"
~~~

The `authorizationUri` in the response carries the `scope` parameter the user will be
asked to approve.

Each agent declares delegated service scopes in AgentSpec.delegated_oauth_scopes.
Agent Identity tools do not add delegated scopes. The Drive, Sheets and Docs scopes are
sensitive or restricted: an app in *Testing* works for listed test users, and a
Workspace administrator may need to allow the client for the organization.

### Service scopes may need an administrator

The Data Access scope picker only lists scopes for APIs already **enabled on the
project**. Enable the service's API first and the scope becomes selectable; skip that
and it appears only under **Manually add scopes** at the bottom of the panel, where it
must be pasted verbatim. Enabling the API first is the shorter path.

Some scopes need more than the project owner:

- **Sensitive and restricted scopes** are flagged on the Data Access page. An app in
  *Testing* works for listed test users, but publishing may require Google verification.
- In a **Workspace or Cloud Identity organisation**, an admin can pre-authorize the
  client ID and its scopes under Admin console → Security → API controls, which
  suppresses the per-user prompt for internal users. Some organisations block user
  consent entirely, and then an administrator must allow the client before any user can
  authorize. This is an org-level change and is outside this repository.
- A managed MCP service may document a **broader scope than its read-only tools need**.
  Record the divergence in the agent's notes and request the narrower scope; do not widen
  it silently.

An agent in *Testing* also needs its users listed under **Audience → Test users**, or
consent fails with `access_denied` no matter which scopes are configured.

The OAuth client's name identifies it in the console. The consent screen's app name
is what users see during sign-in.

## Test the deployed agents

Open each agent in Gemini Enterprise and send one of its starter prompts. A delegated
agent first asks the user to **Authorize**; signing in alone does not prove delegated
API access works, so check that real data comes back. Test a second user with different
permissions to check access boundaries.

| Agent | Check |
|---|---|
| Growth Analysis | "Run the pipeline" ends with a Google Doc link in the report folder, filed as the signed-in user. |
| Vendor Match | A small attached vendor list is staged for review; approving commits it to the master dictionary. A lookup returns a known vendor. |
| Ticket Guidance | A known issue returns guidance from the knowledge base and a ticket link with the user as reporter; "yes, resolved" moves it to Done. |
| Recipe Editorial | One recipe SKU returns the HTML report in chat; with a recipient it sends the email. |
| Kitchen Sequencer | The three starter prompts match the Looker figures for the same week before users are switched over. |

Test from **Agents** in the app, not the designer's Preview: Preview runs the unpublished
draft, so it can work while the deployed agent does not. See the
[deployment guide](docs/deployment-guide.md#11-test-every-agent) for prompts and expected
answers with the sample data.

## Agent notes

### Growth Analysis

A `SequentialAgent` of four stages; the second is a `ParallelAgent` of five research
stages. Registration creates the ADK backend ("Growth Analysis Backend") and a native
workflow wrapper ("Growth Analysis") with a manual trigger. An earlier version also
had a daily schedule; a scheduled run has no signed-in user, so it cannot read the sheet or
file the report under this design. Add a schedule only together with a service account
for those two steps.

The code is the dev team's **V2**:
the sheet reader takes the bottom 5 of the 18-month cohort, the bottom 3 of the 15-month
cohort (excluding stores already listed) and the top 5, scores each against the sheet's
benchmark rows and owner tags, and the report opens with a TL;DR before the cohort
tables, a macro summary table and the store-by-store detail. Their tools, prompts
(`resources/prompts.yaml`) and per-stage settings (`resources/agents/*.yaml`) are kept as
they are so a new drop diffs cleanly; what differs is how it runs here. Sheets, Docs and
Drive run as the signed-in user instead of a deployed `token.json`; the four API keys come
from Secret Manager (`growth-*-api-key`; a missing key degrades that stage instead of
failing the run); the tools' own Gemini calls use the live `model`; and the sheet and
report folder are set per environment rather than in the YAML. Nothing client-specific
is packaged: the settings use canonical column names (`Kitchen Name`, ...), and an
environment whose sheet spells its headers differently maps them with `column_aliases`
in `settings_override`, which also sets the brand to search Google Places with. Each stage's instruction
can be overridden live through `stage_instructions` in the workflow's parameter.

Settings: `GROWTH_SPREADSHEET_ID`, `GROWTH_REPORT_FOLDER_ID`, `GROWTH_SETTINGS_OVERRIDE`. Scopes: Sheets read-only,
Docs, Drive.

### Vendor Match

The pipeline (dictionary lookup, contender search, a parallel LLM resolver and global
consolidation) is ported unchanged; only its credentials and model selection changed.
Drive calls run with the signed-in user's token, so each user needs access to the four
Shared Drive folders. The resolver uses the agent's live `model`. `MAX_THREADS` (default
10) sets resolver concurrency; check Vertex AI quota for it.

Settings: `VENDOR_MATCH_DRIVE_SOURCE_FOLDER_ID`, `..._MASTER_DICT_FOLDER_ID`,
`..._PROCESSED_FOLDER_ID`. Scope: Drive.

### Ticket Guidance

Knowledge-base search calls the Discovery Engine data stores behind the app's Confluence
connector with the user's own token (`cloud-platform` scope: the API has no narrower one
for search), so Confluence permissions apply per user. Jira is called as a dedicated
Atlassian service account whose API token is the `ticket-guidance-jira-api-token`
secret; the user is found by email and set as reporter. Because that account can reach
every ticket, the update and status tools act only on a ticket created in the same chat
session or reported by the user, and check the ticket key's format before it reaches a
request path. That account needs permission to create issues, set the reporter and
transition issues in the Jira project.

An environment that cannot run the ingestion connector (it needs a Workspace or Cloud
Identity organization) can set `TICKET_CONFLUENCE_SEARCH_BACKEND=api`, which searches
Confluence as the Jira service account instead; use it only for a space everyone may read.

Settings: `TICKET_CONFLUENCE_CONNECTOR_ID`, `TICKET_CONFLUENCE_SPACE`,
`TICKET_CONFLUENCE_SEARCH_BACKEND`, `JIRA_API_BASE_URL`,
`JIRA_SITE_URL`, `JIRA_SERVICE_ACCOUNT_EMAIL`, `JIRA_PROJECT_KEY`, `JIRA_PARENT_ISSUE_KEY`.

### Recipe Editorial and Kitchen Sequencer

See [no-code agents](agents/no_code/README.md). Kitchen Sequencer's tables are defined in
`infrastructure/sql/kitchen_compliance`; reconcile their figures with the Looker
dashboards for the same week before switching users over.

## Manage configuration

| Setting | Location | How a change takes effect |
|---|---|---|
| Model, instructions, log level, tool-call logging and tool limits | Parameter Manager | After the runtime cache expires. |
| Workflow stage instructions | Parameter Manager: stage_instructions | After the runtime cache expires. |
| Parameter address, model location and authorization ID | Runtime environment | Update the deployed runtime. |
| MCP endpoint and other per-agent runtime settings | AgentSpec.runtime_env | Update the deployed runtime. |
| OAuth client secret | Secret Manager | Update the stored version and review any existing authorization that uses it. |
| Agent API keys and Jira token | Secret Manager | Add a version; agents re-read within five minutes. |
| No-code agent instruction, model, connectors | `agents/no_code/<name>/` | Rerun `deployment/deploy/no_code/deploy_no_code.py`, then **Update** in the agent designer. Connector changes need `--recreate`, then **Create**. Edits made in the designer come back with `--export`; `run.py check` flags drift. |
| Environment settings | Ignored deployment/config.yaml (deployment/.env.local for local runs) | Rerun the runner; shell variables take precedence. |

### Runtime settings

Each agent defaults to `<package-name>-config`. CONFIG_PARAMETER can override the name
or select a full parameter/version resource. Unversioned addresses resolve to
versions/latest. RuntimeConfig rejects unknown fields and invalid values.

~~~json
{
  "config_revision": "example-v1",
  "model": "<approved-model-id>",
  "instruction": "Answer using the available tools. Ask when the request is unclear.",
  "environment": "dev",
  "log_level": "INFO",
  "max_attempts": 3,
  "max_model_calls_per_request": 100,
  "context_compaction_threshold_tokens": 100000,
  "tool_call_logging": "off",
  "stage_instructions": {}
}
~~~

RuntimeConfig also accepts `image_model`, `max_reference_images`, `managed_project`,
`agent_identity_bucket_name`, `storage_object_limit` and `bigquery_query_row_limit`
from the template. No agent here reads them; leave them unset.

Each agent/workflow reads its own parameter. `model` selects its text model, including
all workflow stages, compaction and the model calls tools make themselves (Vendor Match's
resolver, Growth Analysis's report summaries). Choose
compatible Gemini models supported in the configured locations. Model locations remain
bootstrap settings and require redeployment to change.

Parameters without a field use the defaults above. Parameter edits take effect after
CONFIG_REFRESH_SECONDS without deployment. Replace the model placeholder before
publishing.

Settings are cached for CONFIG_REFRESH_SECONDS. After a successful load, a failed
refresh retains the last valid settings for that same parameter and retries within
30 seconds or the configured refresh interval, whichever is shorter. The first failed
load raises an error. Switching parameters requires a successful read of the new one.

### Tool-call logging

ADK logs nothing that names a called tool, so which tools ran, and in what order, is
invisible by default. `tool_call_logging` turns that on through the shared limits
plugin, so it covers every agent and needs no per-agent change:

| Value | Recorded | Contains user data |
|---|---|---|
| `off` (default) | nothing | — |
| `names` | tool name, completion, error type | No |
| `argument_keys` | also which parameters were supplied | No — names only |
| `full` | also argument values, results and error messages | **Yes** |

A tool's arguments are whatever the signed-in user asked for: BigQuery SQL, monitoring
filters, storage paths. `full` writes those to Cloud Logging, so treat it as a
deliberate debugging step on one agent rather than a setting to leave on. The lower
levels answer "which tools ran" without disclosing what was asked.

Because each agent reads its own `<package-name>-config`, this can be raised for one
agent while the others stay quiet, and it takes effect after the cache interval with no
redeployment. An invalid value fails at config load rather than logging nothing
silently. The local equivalent is `TOOL_CALL_LOGGING`.

The instruction and model callbacks use this cache for each request. Publish a new
parameter version to change live settings without redeploying code.

### Prompt source

Edit `agents/<agent>/prompt.md` to maintain the prompt in version control. Deployment
compares it with the live instruction and publishes a version if they differ, retaining
the other settings. Prompt files are outside src/ and excluded from the runtime archive.

For a live-only edit, publish the instruction directly in Parameter Manager. Also update
prompt.md if you want to keep that edit: the next deployment publishes the repository
prompt again. Local runs use AGENT_INSTRUCTION rather than loading prompt.md.

### Bootstrap settings

deployment/config/settings.py forwards these environment keys to the runtime:

~~~text
CONFIG_PARAMETER
CONFIG_PARAMETER_LOCATION
CONFIG_REFRESH_SECONDS
BOOTSTRAP_MODEL
GEMINI_MODEL_LOCATION
GEMINI_ENTERPRISE_AUTHORIZATION_ID
~~~

The platform supplies the deployed project and runtime location; keep reserved runtime
variables out of the forwarded map.

This list is one shared value per key: whatever is set when a release runs is baked
into that runtime, whichever agent it is. A setting that belongs to one agent goes in
its spec instead.

### Per-agent runtime settings

`AgentSpec.runtime_env` declares the runtime environment one entry needs, versioned
beside its scopes and IAM, so a fresh clone deploys with it and no other agent's value
can override it:

~~~python
"vendor_match_agent": AgentSpec(
    runtime_env=(
        ("DRIVE_SOURCE_FOLDER_ID", "${VENDOR_MATCH_DRIVE_SOURCE_FOLDER_ID}"),
        ...
    ),
)
~~~

A `${NAME}` value is read from `deployment/config.yaml` at deploy time, so the spec names the
setting without committing an environment's ID; the release warns about any that are
unset and leaves them out of the runtime.

`runtime_env(spec)` merges these under the forwarded keys above. A name that is also in
RUNTIME_ENV_KEYS can still be overridden from the environment for a single run; a name
that is not — as `MCP_SERVER_URL` and `ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL` are not —
is never forwarded, so the spec's value always reaches the runtime: no leftover shell
value meant for one agent can change another. Those variables still affect local runs,
which read them directly.

Add a key to RUNTIME_ENV_KEYS only when every agent should share its value.

Agent Identity IAM variables are deployment-time controls only. They are intentionally
not forwarded into the runtime environment.

## Repository layout

~~~text
agents/pro_code/<agent>/          an ADK agent or workflow
  prompt.md                       version-controlled instruction, published to Parameter Manager
  pyproject.toml                  agent dependencies and wheel settings
  src/<agent>/
    agent.py | workflow.py        construct the Agent (or compose the workflow) and AdkApp
    stages.py                     a workflow's stages, from one factory (growth_analysis_workflow)
    config.py                     resolve bootstrap settings
    tools/                        tool implementations
    resources/                    packaged YAML and reference data
agents/no_code/<name>/
  agent.yaml, prompt.md           no-code agent definition, published by deployment/deploy/no_code
packages/gemini_shared/src/gemini_shared/
  auth/                           delegated tokens; with_user_credentials for Google APIs
  config/                         bootstrap settings, live cache, callbacks and status tool
  limits/                         request, retry, compaction and tool-call logging plugin
  runtime/                        model, genai client and application factories
  secrets/                        Secret Manager reads under the runtime's identity
  mcp/                            authenticated Streamable HTTP toolsets
infrastructure/                   Terraform: APIs, IAM, secrets, observability, Kitchen tables
  sql/kitchen_compliance/         curated-table SQL shared with deployment/seed
deployment/                       config.yaml, run.py; config/, seed/, deploy/, verify/
docs/                             deployment guide, requirements workbook, access groups,
                                  native workflows
tests/                            import, validation and behavior tests
~~~

Each archive includes one entry point and the packages it imports. Packaging excludes caches and bytecode,
rejects symlinks and normalizes timestamps and ownership. Unchanged inputs produce
identical archive bytes. Archive creation and SDK staging use the same source manifest
from deployment/deploy/sources.py. Requirements are exported from uv.lock for the selected
workspace package, including its transitive dependencies; there is no second dependency
list in the registry. Outputs go under ignored artifacts/; deployment state goes
under ignored deployment/.state/.

### Request and retry limits

`max_attempts` includes the initial attempt: the default of 3 permits two retries.
It controls Gemini transport retries. Non-retryable errors are not retried.

`max_model_calls_per_request` defaults to 100 and caps ADK model calls across the entire
user request, including all workflow stages. The shared application factory installs
the limit plugin. Callers may request a lower limit but cannot raise the server's cap.
Exceeding it stops the request with ADK's `LlmCallsLimitExceededError`, not another model
call. This counts orchestration calls, not model calls a tool makes itself, such as Vendor
Match's parallel resolver. It is not a dollar or token cap.

Publish these fields in the existing Parameter Manager JSON. Old versions without
them use the defaults. A request snapshots the model-call ceiling when it starts;
later requests see refreshed settings after the cache expires. Attempt limits are
read when each operation starts. `report_runtime_config` in
`gemini_shared.config.tools` reports both when added to an agent for diagnosis.
Local equivalents are `MAX_ATTEMPTS` and `MAX_MODEL_CALLS_PER_REQUEST`.

Deploy this code once before expecting live parameter edits to enforce the new limits.
`context_compaction_threshold_tokens` defaults to 100000. At request startup the
plugin enables ADK token-based compaction using that threshold, retaining the six
most recent events (and any extra events needed to preserve tool-call/response pairs).
ADK summarizes older history before preparing a subsequent model call when the last
reported prompt-token usage reaches the threshold (or uses ADK's estimate when usage
metadata is unavailable). This is not a strict token ceiling:
a large new input can cross the threshold before usage is reported, and recent content
may remain larger than it. Summaries can lose detail, so original documents remain the
source of truth. Compaction does not reset the request's call budget.
Summarizer calls are additional model usage outside ADK's orchestration-call counter.
The local equivalent is `CONTEXT_COMPACTION_THRESHOLD_TOKENS`.
Existing Parameter Manager versions that explicitly set a 20-call ceiling retain it;
publish 100 there to raise that value. No live parameters are changed by a code push.

## Add an agent

An agent that needs only an instruction and existing connectors is a
[no-code agent](agents/no_code/README.md#add-a-no-code-agent): add a folder and deploy.
For a code agent:

1. Copy agents/pro_code/ticket_guidance_agent/. Rename the package directory, project name in
   pyproject.toml and wheel path. Set a stable agent name in agent.py.
2. Write prompt.md. Keep instructions specific to the task and available tools.
3. Add tools under tools/ and export them from tools/__init__.py. Keep tool logic
   separate from agent construction. Share reusable behavior in gemini_shared.
4. Add an AgentSpec to AGENTS in deployment/registry.py. Supply the package name, import module,
   display name, source paths and registration text.
   For delegated tools, declare AUTHORIZATION_ID_ENV and the required service scopes.
   A workflow also sets `is_workflow=True`.
5. Add dependencies to the agent's pyproject.toml and update uv.lock with uv sync.
   gemini-shared provides the shared SDK and Agent Identity dependencies; use
   gemini-shared[mcp] for the MCP extra and gemini-shared[secrets] to read secrets. Deployment requirements come from the lock.
6. Add the source directory to pytest's pythonpath in the root pyproject.toml, add an
   import test and test the new tools. Registry-based tests include the agent automatically.
7. Run uv sync --all-packages --group dev, lint and tests. Try the local runner, then
   release the agent and test it in Gemini Enterprise.

Keep runtime_instruction, apply_runtime_model and the shared create_model/create_app factories from the copied
agent. Tool functions need type hints and short docstrings: ADK uses them to describe
the tools to the model. Document arguments the model must supply and return
JSON-compatible values.

The unit suite uses dummy settings and anonymous credentials through tests/conftest.py.
Run it with `uv run --group dev pytest`; no gcloud login or live project is required.

### Choose tool authentication

| Access needed | Implementation |
|---|---|
| A shared capability available through the agent | Use runtime credentials. Every remote runtime already has Agent Identity; configure exact-agent IAM only for the resources that agent needs. |
| Access limited to the signed-in user's permissions | Use a delegated session token. Configure the authorization and scopes for that service. |
| A third-party API key or service-account token | Store it in Secret Manager; read it with `gemini_shared.secrets.read_secret` and declare `agent_identity_secret_roles`. |

Developer ADC, deployed Agent Identity and delegated user tokens are separate
credentials. Grant each only the access needed. The deployment scripts never grant IAM
to the developer. Per-agent IAM is applied only when explicitly configured and only by
a caller that already has permission to change the target IAM policy.

For delegated tools that call Google APIs through client libraries, wrap the tool with
`with_user_credentials(authorization_id)` and build clients from
`current_user_credentials()`, as Vendor Match and Growth Analysis do: helpers several
calls below the tool get the user's credentials without each taking a parameter. The
binding lasts for that call only and does not reach threads the tool starts. For a
single client, AuthenticatedFunctionTool with delegated_auth_config(authorization_id)
also works. Importing gemini_shared registers the
provider needed to rehydrate the auth scheme after deployment; preserve this import
when reorganizing the package.

### Connect an MCP toolset

Use bigquery_readonly_toolset for BigQuery. To connect another Streamable HTTP server that accepts the configured delegated token:

~~~python
from gemini_shared.mcp.mcp_auth import delegated_mcp_toolset

toolset = delegated_mcp_toolset(
    server_url=MCP_SERVER_URL,
    authorization_id=GEMINI_ENTERPRISE_AUTHORIZATION_ID,
    tool_filter=["read_only_tool"],
    tool_name_prefix="ext",
)
~~~

Use the server's actual tool names and required OAuth scopes. Configure a compatible
authorization provider for that service; a Google token is not valid for every MCP server.

Declare the endpoint in the spec's `runtime_env` as `MCP_SERVER_URL` rather than relying
on the shared variable, so no other agent's value can retarget where the user's bearer
token is sent.

Check what the server's tools cost in tokens before deploying. ADK sends each tool's
`outputSchema` to the model as `response_json_schema`, and a server publishing large
response schemas can exceed the model's input limit before any tool runs, failing every
request with `400 INVALID_ARGUMENT`. Cloud Monitoring's nine tools carry ~79k tokens of
response schemas against ~7.7k for their inputs. Declare
`ADK_DISABLE_JSON_SCHEMA_FOR_FUNC_DECL=true` in that agent's `runtime_env` to send input
schemas only, keeping every tool. Read the sizes from the server's `tools/list` response
rather than assuming.

Always supply an explicit allowlist for application toolsets. tool_filter=None exposes
all tools returned by the server, including future additions. The BigQuery allowlist
contains five read-only tools and excludes execute_sql. Filtering limits tools shown
to the model; server-side permissions still control access.

Headers use the current session token for each request. Tool descriptions are cached
for five minutes by default. Keep shared endpoints, scopes and tool lists under
gemini_shared/mcp/ when multiple agents use them.

## Add a Python ADK workflow

The release script registers the Python backend with a `Backend` suffix and creates
a native Workflow Builder wrapper under the workflow's original name. The backend
must remain available for the wrapper to call it. See [Native workflow registration](docs/native-workflows.md).

An ADK workflow is deployed exactly like an agent: the same runtime, the same Agent
Identity and the same Parameter Manager entry. Registration additionally creates
the native wrapper. The source layout differs as follows.

1. It lives under `agents/pro_code/` like an agent, and its `AgentSpec` sets
   `is_workflow=True`. That flag is the only registry change a workflow needs.
2. Its root object is a composition — `SequentialAgent`, `ParallelAgent` or
   `LoopAgent` — rather than a single `Agent` holding tools.

Build it from stages. Each stage is an `LlmAgent` with an `output_key`, which publishes
its result into session state, and the next stage reads it by name from its own
instruction:

~~~python
sheet_reader_agent = Agent(..., output_key="sheet_reader_data")
external_intelligence_stage = ParallelAgent(sub_agents=[weather_agent, ...])
insights_agent = Agent(..., output_key="insights_agent")  # reads the stages above

root_agent = SequentialAgent(
    name="growth_analysis_workflow",
    sub_agents=[sheet_reader_agent, external_intelligence_stage, insights_agent, ...],
)
app = create_app(root_agent, BOOTSTRAP)
~~~

Each stage's instruction resolves through `stage_instruction(name, fallback)`, so it can
be published as `stage_instructions[name]` in the workflow's parameter and reverts to
the compiled-in text when that key is removed. Growth Analysis compiles its stage text
from `resources/prompts.yaml` and builds every stage with one factory in `stages.py`, so
a stage is one line: its prompt key, its tools (wrapped with `with_user_credentials`
when they act as the user) and, if it differs from the name, its output key. ADK fills `{key}` placeholders from session state in
either case. All stages use the live `model` through the shared plugin.

Use a workflow when stage order is fixed. Model outputs still vary and a stage can
fail, so validate the data passed between stages. Use a conversational agent when
the user's request should determine which tool runs next.

## Code conventions

Use Python 3.12-compatible code with type hints on shared functions. Ruff checks import
order, PEP 8 rules and common correctness and security issues, with a 100-character
line limit. Comments should explain constraints or decisions that the code does not.

Keep domain logic with its agent and reusable logic in the shared package. Pass
subprocess arguments as a list without a shell. Validate external input before cloud
operations. Never log tokens or secrets, commit credentials or .env files, or add IAM
self-grants to application code. The deployment/ workflow is limited to development projects.

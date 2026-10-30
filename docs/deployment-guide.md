# Deployment guide

Step by step, from an empty Google Cloud project to every agent answering in Gemini
Enterprise. Each step says what to do, how to check it worked, and what usually goes
wrong. The [README](../README.md) explains the design; this is the runbook. For a client
whose IT team provisions the environment, hand them the
[IT requirements workbook](requirements/Prod_IT_Requirements.xlsx): one tab per agent with
every service, identity, role, client, secret and connector to request. For QA or
production, follow the [production runbook](prod-runbook.md): the same steps in order,
with where the run pauses and where each secret is pasted.

Everything this guide configures goes into one file, `deployment/config.yaml` (copied from
[`config.example.yaml`](../deployment/config.example.yaml)), and one runner applies it:

~~~bash
uv run --group dev python deployment/run.py            # check, seed, deploy, test
uv run --group dev python deployment/run.py check      # just report what is missing
~~~

| Agent | Kind | Needs before it works |
|---|---|---|
| Growth Analysis | ADK workflow | OAuth client, four API-key secrets, a performance Google Sheet, a report folder |
| Vendor Match | ADK agent | OAuth client, four Drive folders with the dictionary files |
| Ticket Guidance | ADK agent | OAuth client, a Confluence connector, a Jira service account and token |
| Recipe Editorial | No-code | BigQuery MCP connector, recipe tables, (optional) Gmail connector |
| Kitchen Sequencer | No-code | BigQuery MCP connector, the `kitchen_compliance` tables |
| Prompt Manager | ADK agent | Parameter Manager viewer and version adder on the project (granted by the deploy) |

Steps 1 to 6 are done once per environment. Step 7 is the runner, which you rerun on every
change. Steps 8 to 10 are console steps that no API covers; `run.py check` reports their
state. Step 11 is `run.py test`.

## 1. Workstation

Install Python 3.12+, [uv](https://docs.astral.sh/uv/) and the Google Cloud CLI, then:

~~~bash
uv sync --all-packages --group dev
gcloud auth login
gcloud auth application-default login
~~~

Both logins must be the account that owns the target environment. If your default gcloud
account belongs to another organization, keep this environment's credentials apart so a
command never runs against the wrong one:

~~~bash
export CLOUDSDK_CONFIG="$HOME/.gcloud-<environment>"   # a separate gcloud profile
gcloud auth login && gcloud auth application-default login
~~~

and pass `--account=<email>` to any one-off `gcloud` command you run outside it.

Check: `uv run --group dev pytest` passes.

## 2. Project and Gemini Enterprise app

1. Create or pick the project; billing must be enabled.
2. In the console, open **Gemini Enterprise** and create an app (location `global`).
3. Note two values from the app:
   - the **engine ID** (Gemini Enterprise > Apps > the app's ID column), used as
     `GEMINI_ENTERPRISE_APP_ID`;
   - the **web app URL** (`https://vertexaisearch.cloud.google.com/home/cid/<cid>`), used to
     open agents and the agent designer.

Gotcha: the organization policy must allow the `global` location for Discovery Engine, or
app creation fails.

## 3. Platform: Terraform, or sandbox bootstrap

**Managed environment (recommended).** Copy `infrastructure/terraform.tfvars.example` to
`terraform.tfvars`, fill it in and apply:

~~~bash
read -rs TF_VAR_secret_values   # paste the JSON below, then Enter; nothing is echoed or kept in history
export TF_VAR_secret_values
terraform -chdir=infrastructure init
terraform -chdir=infrastructure apply
unset TF_VAR_secret_values
~~~

The JSON is keyed by the `managed_secrets` names in `terraform.tfvars`, not by secret ID:
`{"BLS_API_KEY":"...","FRED_API_KEY":"...","NYT_API_KEY":"...","GOOGLE_PLACES_API_KEY":"...","JIRA_API_TOKEN":"..."}`.

It enables the APIs, grants the baseline every Agent Identity needs, creates the five
secrets and the Kitchen Sequencer dataset with its daily scheduled queries. Issue new
values for this environment; never copy keys or tokens from another one.
Then ask the owner of the source data to grant the output
`kitchen_compliance_refresh_service_account` read access to `hdr_analytics`.

**Personal sandbox.** Skip Terraform and let the runner do the minimum: in `config.yaml`
set `environment.enable_required_apis: true` and `environment.grant_agent_identity_baseline:
true` (needs project IAM admin). `run.py seed` creates the five secrets; give each a value
by exporting the variable its `secrets.<id>.from_env` names before seeding, or later with:

~~~bash
gcloud secrets versions add growth-fred-api-key --data-file=-   # paste, then Ctrl+D (Ctrl+Z Enter on Windows)
~~~

A missing Growth key only degrades that research stage; it does not fail the run.

## 4. Organization policy for custom MCP connectors

New organizations enforce `constraints/discoveryengine.managed.disableCustomMcpServerConnector`,
which blocks the BigQuery MCP connector. An org policy admin turns it off for the project:

~~~bash
cat > mcp-policy.yaml <<'EOF'
name: projects/<project-id>/policies/discoveryengine.managed.disableCustomMcpServerConnector
spec:
  rules:
  - enforce: false
EOF
gcloud org-policies set-policy mcp-policy.yaml --account=<admin-email>
~~~

Check: `gcloud org-policies describe discoveryengine.managed.disableCustomMcpServerConnector
--project=<project-id> --effective` shows `enforce: false`. A `reset` is not enough: it
falls back to the enforced default.

## 5. OAuth consent screen and clients

In **Google Auth Platform**:

1. **Branding / Audience.** Configure the consent screen. While the app is in *Testing*,
   add every tester under **Audience > Test users**, or sign-in fails with `access_denied`.
2. **Data Access.** Add these scopes: `openid`, `email`, `profile`,
   `.../auth/spreadsheets.readonly`, `.../auth/documents`, `.../auth/drive`,
   `.../auth/cloud-platform`, `.../auth/bigquery`. Click **Update**, then **Save**.
   Do this before step 7: an authorization created before a scope was added is not
   repaired later (delete it and register again).
3. **Clients.** Create four **Web application** clients, each with both redirect URIs:

   ~~~text
   https://vertexaisearch.cloud.google.com/static/oauth/oauth.html
   https://vertexaisearch.cloud.google.com/oauth-redirect
   ~~~

   | Client name | Used by |
   |---|---|
   | Growth Analysis (<environment>) | `growth_analysis_workflow` |
   | Vendor Match Agent (<environment>) | `vendor_match_agent` |
   | Ticket Guidance Agent (<environment>) | `ticket_guidance_agent` |
   | BigQuery MCP | the BigQuery MCP connector (both no-code agents) |

   For each, **download the JSON** (on the client page: Add secret if needed, then the
   download icon). The secret is shown in full only once; the JSON is the safe way to move
   it without copying it by hand.

Each code agent needs its own client: consent is cached per client, so two agents sharing
one never both receive a token.

## 6. Data and settings

**Settings.** Copy `deployment/config.example.yaml` to `deployment/config.yaml` and fill in
every `REPLACE_...` value; every key is commented there, and an unknown key is an error.
The ones people miss:

| Key | Value |
|---|---|
| `environment.project_id`, `environment.staging_bucket` | Project ID and a `gs://` bucket for Agent Engine packages |
| `gemini_enterprise.app_id` | The engine ID from step 2 |
| `oauth_clients.<agent>.client_json` | Path to each client's downloaded JSON (keep them in the gitignored `deployment/secrets/`); the secret is imported into Secret Manager on first registration and never printed |
| `agents.growth_analysis_workflow.*` | The performance sheet (or let `seed.drive` create a sample one) and the report folder; `settings_override` when the sheet's headers differ from the canonical ones (`column_aliases`) or to search Google Places with a brand |
| `agents.vendor_match_agent.*` | Source, master dictionary and processed folders |
| `agents.ticket_guidance_agent.*` | Confluence search mode, connector collection ID (step 8) and space key |
| `atlassian.*` | Jira site, service account email and project key |
| `agents.recipe_editorial_agent.*` | `project.dataset` of the recipe tables (with sample data: `<project>.recipe_products`, `<project>.recipe_legacy`). The prompt uses neutral table names; a warehouse with other names exposes these through views |
| `agents.kitchen_sequencer.source_project` | Project holding `hdr_analytics`; empty with sample data |

**Data.** Either point the agents at real data, or seed the synthetic
[sample data](../sample_data/README.md), which needs no access to the client's systems.
In `config.yaml`:

- `seed.bigquery.sample_data` and `seed.bigquery.kitchen_compliance`: the source tables and
  the Kitchen Sequencer tables.
- `seed.drive.enabled`: the Growth performance sheet (18- and 15-month cohort tabs and the
  location tab, in the layout Growth V2 reads) and the Vendor Match workbooks, uploaded to the
  configured folders (your ADC needs the Drive scope). A sample sheet seeded before V2 is
  refreshed in place, so its ID stays the same.
- `seed.atlassian.enabled`: the knowledge base space and its sample pages, and a check that
  the Jira project has what Ticket Guidance needs.

Then run `uv run --group dev python deployment/run.py seed`. Every seed step is idempotent.

## 7. Deploy the code agents

~~~bash
uv run --group dev python deployment/run.py deploy --skip-no-code
~~~

For each code agent this packages it, deploys it to Agent Engine, publishes its `prompt.md`
to its Parameter Manager parameter, grants its Agent Identity exactly the roles and
secrets it declares, creates its OAuth authorization and registers it in the app. Growth
Analysis is registered twice: the ADK backend ("Growth Analysis Backend") and a native
workflow wrapper ("Growth Analysis"). The Prompt Manager has no OAuth client; its identity
gets Parameter Manager viewer and version adder on the project.

It continues past an agent that fails and prints a summary; fix the cause and rerun.
Every step is idempotent. `--only vendor_match_agent` limits a run to one agent.

Check: the summary says `ok` for every agent, and they appear under **Agents** in the app.

## 8. Connectors

Create these once per app, in this order.

**BigQuery MCP** (Recipe Editorial, Kitchen Sequencer). Script it from the downloaded JSON:

~~~bash
uv run --group dev python deployment/deploy/no_code/create_mcp_connector.py \
  --client-json <path-to-BigQuery-MCP-client.json> --delete-json
~~~

or in the console: Data stores > Create > **Custom MCP server**, URL
`https://bigquery.googleapis.com/mcp`, OAuth auth URI
`https://accounts.google.com/o/oauth2/v2/auth`, extra params
`&access_type=offline&prompt=consent`, token URI `https://oauth2.googleapis.com/token`,
scope `https://www.googleapis.com/auth/bigquery`.

Then, in the console, two steps that are easy to miss:

1. **Connect it to the app.** Gemini Enterprise > the app > Connected data stores >
   **Add existing data stores** > `bigquery-mcp-connector_mcp_data`. Until then, the agent
   designer does not offer the connector.
2. **Enable its actions.** Data stores > the connector > **Actions** tab. Enable at least
   `execute_sql_readonly`, `list_dataset_ids`, `get_dataset_info`, `list_table_ids`,
   `get_table_info`, `get_query_results` and `get_job`. With actions disabled, the agents
   say the tool is "not configured or available". Leave `execute_sql` (writes) off unless
   an agent needs it.

**Gmail** (Recipe Editorial, optional). Data stores > Create > Gmail (federated, with
actions). It needs Google Workspace. Without it, Recipe Editorial deploys anyway and shows
the report in chat instead of emailing it.

**Confluence** (Ticket Guidance). The agent searches the connector's ingested page, blog and
comment data stores, so the connector must use **Data ingestion** mode.

1. **Access control first.** Ingestion enforces Confluence permissions, so Gemini Enterprise >
   Settings > Authentication must have an identity provider for `global` (Google Identity
   for a Workspace or Cloud Identity organization). A Google Cloud organization without a
   Cloud Identity customer cannot set it ("Project's GCP Organization is not associated with
   a Cloud Identity customer id"), and the connector form will not continue.
2. **Atlassian OAuth app.** developer.atlassian.com > Console > Create > OAuth 2.0
   integration, resource-level access.
   - Authorization: OAuth 2.0 (3LO), callback
     `https://vertexaisearch.cloud.google.com/console/oauth/confluence_oauth.html`.
   - Permissions: Confluence API > Granular scopes: `read:content-details:confluence`,
     `read:attachment:confluence`, `read:comment:confluence`, `read:page:confluence`,
     `read:whiteboard:confluence`, `read:space:confluence`, `read:group:confluence`,
     `read:user:confluence`, `read:content.metadata:confluence`,
     `read:configuration:confluence`.
   - Distribution: sharing (vendor Google, privacy policy `https://policies.google.com`),
     unless only the app's owner will authorize it.
3. **Connector.** Data stores > Create > Confluence Cloud > Data ingestion > OAuth 2.0 client
   credentials. Instance URI is the site URL; Instance ID is the `cloudId` from
   `<site>/_edge/tenant_info`. Paste the app's client ID and secret, **Verify Auth**, sync
   Page, Blog and Comment, and set a full (daily) and incremental sync frequency.
4. Put the collection ID in `TICKET_CONFLUENCE_CONNECTOR_ID`, the space key in
   `TICKET_CONFLUENCE_SPACE`, and rerun step 7 for `ticket_guidance_agent`.

**Without a connector.** Where item 1 is impossible (a personal Google Cloud organization),
set `TICKET_CONFLUENCE_SEARCH_BACKEND=api`: the agent then searches Confluence's REST API
with the Jira service account's token, so no connector or OAuth app is needed. It searches
as that account rather than as each user, so use it only for a space everyone may read.
Prod should use the default, `connector`.

**Jira** (Ticket Guidance). Jira is called with an Atlassian API token, not a connector.

1. Use a dedicated Atlassian service account with permission to create issues, set the
   reporter and transition issues in the project. Create its API token at
   id.atlassian.com > Security > API tokens (a classic token works with the site URL as
   `JIRA_API_BASE_URL`; a scoped token needs `https://api.atlassian.com/ex/jira/<cloudId>`).
2. Store it without printing it:
   `gcloud secrets versions add ticket-guidance-jira-api-token --data-file=-`, pasting the
   token on stdin.
3. Set `JIRA_SITE_URL`, `JIRA_API_BASE_URL`, `JIRA_SERVICE_ACCOUNT_EMAIL` and
   `JIRA_PROJECT_KEY` (the project's key, which Jira may generate, such as `KAN`). The project
   should have the "Service Request" and "Incident Request" types and "Done" and
   "In Progress" statuses; without the service-desk types, tickets are created as "Task".

## 9. Deploy and publish the no-code agents

~~~bash
uv run --group dev python deployment/run.py deploy --skip-code
~~~

An agent whose published copy already matches the repository is left untouched. Any
other is saved as a **draft**: the prompt from `prompt.md` with its `${NAME}` placeholders
filled in, the model, starter prompts and connectors. Google has no API to publish an
Agent Designer agent (only the designer's button can), so for each agent the run lists:

1. Open the `ACTION_REQUIRED` link it prints (`<web app URL>/r/agent-builder/<agent id>`).
2. Check the node shows the BigQuery MCP connector.
3. Click **Create** (first time) or **Update** (later). Chat serves the previous version
   until you do.

> **Connectors are fixed at first publish.** Gemini Enterprise keeps the connectors an
> agent had when it was first created; later updates change only its instruction and
> model. If you add or change an agent's connectors (or it was first published before its
> connector existed), recreate it and publish again:
>
> ~~~bash
> uv run --group dev python deployment/deploy/no_code/deploy_no_code.py --agent kitchen_sequencer --recreate
> ~~~
>
> The symptom: the agent works in the designer's **Preview** but, once deployed, answers
> that the tool is unavailable, and its connector switch in chat is off and greyed out.

Prompt-only changes need just a rerun and **Update**.

**Edits made in the designer.** Pull them into the repository before the next deploy
overwrites them: `deploy_no_code.py --agent <name> --export` writes the published copy into
`agent.yaml` and `prompt.md` (environment values back as `${NAME}` placeholders) for you to
review and commit; `--diff` only reports. `run.py check` flags any agent that has drifted.

## 10. Give users access

**Code agents.** The first time a user runs one, it asks them to **Authorize**; they sign
in with Google and approve the scopes. Drive and Sheets access is the user's own, so each
user needs access to the folders and sheet.

**No-code agents.** Each user authorizes BigQuery MCP once: in any chat, open the
connectors menu (the plug icon next to the input), find **BigQuery MCP** and sign in. When
authorized, the icon next to it is a crossed link (**Unauthorize**). Inside an agent the
connector's switch is greyed out because the agent always uses it; that is expected.

Users also need IAM on the project that runs the queries:

~~~bash
for role in roles/mcp.toolUser roles/bigquery.jobUser; do
  gcloud projects add-iam-policy-binding <project-id> --member=user:<email> --role=$role
done
~~~

plus `roles/bigquery.dataViewer` on the datasets they query. A missing `mcp.toolUser`
shows as "User does not have mcp.tools.call permission".

## 11. Test every agent

~~~bash
uv run --group dev python deployment/run.py test
~~~

This runs one end-to-end check per agent: code agents through their deployed runtimes with
your Google token (as Gemini Enterprise would run them), no-code agents by confirming the
published definition carries its connector and that their tables answer through the
BigQuery MCP server. `tests.growth_full_run` and `tests.ticket_guidance_creates_tickets` in
`config.yaml` control the two checks that write to real systems.

Then confirm in the chat itself: open each agent from **Agents** in the app (not the
designer's Preview, which runs the draft) and send:

| Agent | Send | Expect |
|---|---|---|
| Kitchen Sequencer | "What is the Kitchen Compliance Scorecard for this week?" | `Execute Sql Readonly` tool calls, then a table for the latest complete week. With sample data, Hoboken Kitchen and King of Prussia Kitchen are worst. |
| Recipe Editorial | "Run the editorial QA for recipe SKU 604430003" | An HTML QA report. With sample data it flags active time longer than total time. |
| Growth Analysis | "Run the pipeline" | After a few minutes, a Google Doc link in the report folder, owned by the user: a TL;DR per underperforming store, then the cohort tables (bottom 5 of 18 months, bottom 3 of 15 months, top 5), the macro summary and the store-by-store detail. |
| Vendor Match | "Look up vendor Sysco", then attach a small vendor list | A dictionary match; then a batch staged for review, and on approval a commit to the master dictionary. |
| Ticket Guidance | A known issue from the knowledge base | Guidance, then a Jira ticket with the user as reporter. Without Atlassian it says the knowledge base is unavailable. |
| Prompt Manager | "List the agent configurations in this project." | Every code agent's parameter, with its model and live version. A change is shown as a diff and needs confirmation. |

Test a second user with fewer permissions to check they see only what they should.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No-code agent: "tool is not configured or available" | Connector actions disabled, or the agent was first published without the connector | Enable actions (step 8); recreate and publish (step 9) |
| Agent works in Preview but not when deployed | Draft not published, or connectors fixed at first publish | Click **Update**; or `--recreate` and **Create** |
| Agent asks the user for the project ID | BigQuery MCP needs `projectId` on every call | The prompts set it from the project ID; check `environment.project_id` in `config.yaml` and redeploy |
| Connector creation: "custom MCP server connector is disabled" | Org policy (step 4) | Set `enforce: false` on the project |
| Agent designer does not list BigQuery MCP | Data store not connected to the app | Add existing data stores (step 8) |
| `mcp.tools.call` permission denied | User lacks `roles/mcp.toolUser` | Step 10 |
| Code agent: `redirect_uri_mismatch` | Client missing a redirect URI | Add both URIs (step 5) |
| Code agent: `access_denied` at consent | User not a test user, or scope missing from the consent screen | Step 5; delete and recreate the authorization after fixing scopes |
| Deploy: "cannot pickle ContextVar" | A tool closure references a context variable directly | Use the helpers in `gemini_shared.auth.workspace` |
| Bootstrap: "Payload does not follow JSON" | Parameter Manager rejects escaped emoji | Already handled (`ensure_ascii=False`); keep it when editing |
| An agent's own-identity call is denied right after its first deploy (e.g. Prompt Manager listing parameters) | New Agent Identity grants take a few minutes to propagate | Wait a few minutes and rerun `run.py test` |
| Confluence connector form says access control must be configured | No identity provider for `global`; needs a Workspace or Cloud Identity organization | Step 8, Confluence, item 1 |
| Growth run ends without a report Doc; the runtime logs show `429 RESOURCE_EXHAUSTED` | Gemini quota in the model location; the report stage sends the whole run in one request | Raise the project's Vertex AI quota (workbook, Growth tab). Calls back off for about a minute before giving up |
| `gcloud` changes the wrong organization | Default account belongs to another org | Separate `CLOUDSDK_CONFIG` or `--account` (step 1) |

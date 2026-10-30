# Production runbook

The order to stand up the agents in a production (or QA) environment, with every command,
every point where the run stops for a person, and every place a secret is pasted. The
[deployment guide](deployment-guide.md) explains each step in depth and has the
troubleshooting table; the [IT requirements workbook](requirements/Prod_IT_Requirements.xlsx)
is what IT is asked to provide beforehand. This page is the sequence.

## Who does what

| Role | Does |
|---|---|
| Platform team | Terraform (step 1), the org policy and the OAuth consent screen and clients (step 2) |
| Gemini Enterprise admin | The app, connectors (step 6) and publishing the no-code agents (step 7) |
| Secret owners | Paste each API key or token once (steps 1 or 4); no one else sees the value |
| Deployer (a person or CI) | The config file and the runner (steps 0, 3, 4, 5, 7, 9) |
| Business owner | The performance sheet, the Drive folders, the Jira project and the user groups |

## Where the run stops for a person

Everything else is the runner. These are the only pauses, in order:

| Step | You see | You do |
|---|---|---|
| 1 | `read -rs` waits for input | A secret owner pastes the API keys as one JSON line |
| 2 | Nothing; console work | Consent screen, four OAuth clients (download each JSON), org policy |
| 3 | `ACTION ...` lines from `check` | Fix each one where it says, rerun `check` |
| 4 | `ACTION_REQUIRED=secret <id> has no value` | A secret owner pastes that value (only if Terraform did not set it) |
| 6 | Nothing; console work | Create the connectors, connect them to the app, enable their actions |
| 7 | `ACTION_REQUIRED=<agent>: publish the change: open <link> and click Create` | Open each link, click **Create** (Google has no API for this click) |
| 8 | Each user, on first use, sees **Authorize** | The user signs in once per code agent and once for BigQuery MCP |

## 0. Prepare the workstation and the config file

Once, on the deployer's machine (Linux, macOS, or Git Bash on Windows):

~~~bash
uv sync --all-packages --group dev
export CLOUDSDK_CONFIG="$HOME/.gcloud-prod"     # a gcloud profile used only for prod
gcloud auth login                                # the deployer identity
gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/cloud-platform
cp deployment/config.example.yaml deployment/config.prod.yaml
~~~

Fill `deployment/config.prod.yaml` from the completed workbook (every `<placeholder>` there
has a key here). It is gitignored and holds no secret values. For prod in particular:

| Key | Prod value |
|---|---|
| `environment.name` | `prod` (or `qa`) |
| `environment.project_id`, `region`, `staging_bucket` | From the platform team |
| `environment.create_project.enabled`, `grant_agent_identity_baseline` | `false`: Terraform owns the project and IAM; the runner refuses `true` |
| `environment.enable_required_apis`, `create_staging_bucket` | `false` when Terraform manages them |
| `gemini_enterprise.app_id`, `web_app_url` | The app's engine ID and URL |
| `oauth_clients.<agent>.client_json` | `secrets/<file>.json`, the JSONs from step 2 |
| `agents.*` | Sheet, folder, dataset and Confluence IDs from the workbook; Growth's `settings_override` if the sheet's headers differ |
| `atlassian.*` | Site URL, service account email, project key |
| `seed.bigquery.sample_data`, `seed.drive.enabled`, `seed.atlassian.enabled` | `false`: no sample data in prod; the runner refuses `true` |
| `seed.bigquery.kitchen_compliance` | `true` to build the Kitchen tables once now from `agents.kitchen_sequencer.source_project`; Terraform refreshes them daily |
| `tests.ticket_guidance_creates_tickets` | `false`; the runner refuses `true` in prod |
| `tests.vendor_lookup` | A vendor you know is in the prod master dictionary |

Then, in every shell you deploy from:

~~~bash
export DEPLOYMENT_CONFIG=deployment/config.prod.yaml
export DEPLOY_CONFIRM_PROJECT=<prod-project-id>
~~~

`DEPLOY_CONFIRM_PROJECT` is the safety catch: in `qa` and `prod` every deploy script refuses
to run unless it equals `environment.project_id`, so a wrong config file or a stale shell
cannot change the wrong project. (`run.py --confirm-project <id>` does the same for one run.)

## 1. Platform: Terraform (platform team)

Copy `infrastructure/terraform.tfvars.example` to `terraform.tfvars`, fill it in (it holds no
secrets), and add your organization's remote state backend. Then apply, pasting the secret
values without echoing them or leaving them in shell history:

~~~bash
read -rs TF_VAR_secret_values
~~~

**PASTE** one line of JSON, then Enter. Keys are the `managed_secrets` names, not the
secret IDs:

~~~text
{"BLS_API_KEY":"...","FRED_API_KEY":"...","NYT_API_KEY":"...","GOOGLE_PLACES_API_KEY":"...","JIRA_API_TOKEN":"..."}
~~~

~~~bash
export TF_VAR_secret_values
terraform -chdir=infrastructure init
terraform -chdir=infrastructure apply
unset TF_VAR_secret_values
~~~

This enables the APIs, grants the baseline every Agent Identity needs, creates the five
secrets with their values, the Kitchen Sequencer dataset with its daily scheduled queries,
and the monitoring. Afterwards the source data owner grants the output
`kitchen_compliance_refresh_service_account` `roles/bigquery.dataViewer` on the Kitchen
source dataset.

If the secret owners would rather paste each value themselves, leave `secret_values` out of
Terraform and use step 4 instead.

## 2. Console (platform team and Gemini Enterprise admin)

1. **Org policy.** Allow custom MCP connectors on the project
   ([guide, step 4](deployment-guide.md#4-organization-policy-for-custom-mcp-connectors)).
2. **Consent screen.** Google Auth Platform: Internal; Data Access lists every scope on the
   workbook's agent tabs. Do this before step 5.
3. **OAuth clients.** Four Web application clients (Growth Analysis, Vendor Match, Ticket
   Guidance, BigQuery MCP), each with both redirect URIs
   ([guide, step 5](deployment-guide.md#5-oauth-consent-screen-and-clients)). Download each
   client's JSON and deliver it to the deployer through the approved secret channel.
   **PASTE**: save each file into `deployment/secrets/` (gitignored), named as in
   `oauth_clients`. Never paste a client secret into chat, email or a terminal.
4. **Workspace trust.** If user consent is restricted, mark the three agent clients as
   trusted (Admin console > Security > API controls).
5. **Identity provider.** Gemini Enterprise > Settings > Authentication: Google Identity for
   `global` (needed by the Confluence connector).

## 3. Check

~~~bash
uv run --group dev python deployment/run.py check
~~~

It changes nothing. Each line is `OK` or `ACTION` with where to fix it. **PAUSE** until the
only actions left are the connectors (step 6) and the no-code agents (step 7).

## 4. Seed

~~~bash
uv run --group dev python deployment/run.py seed
~~~

In prod this makes sure every secret exists and has a value, and builds the Kitchen tables
once from the real source when `seed.bigquery.kitchen_compliance` is true. It loads no
sample data.

**PASTE**, only for a secret it reports as having no value. The secret owner runs, for
example:

~~~bash
gcloud secrets versions add growth-fred-api-key --data-file=-
~~~

then pastes the value and presses Ctrl+D (Ctrl+Z, Enter in a Windows console). Nothing is
echoed or saved. The five IDs are `growth-bls-api-key`, `growth-fred-api-key`,
`growth-nyt-api-key`, `growth-google-places-api-key` and `ticket-guidance-jira-api-token`.

## 5. Deploy the code agents

~~~bash
uv run --group dev python deployment/run.py deploy --skip-no-code
~~~

For Growth Analysis, Vendor Match, Ticket Guidance and the Prompt Manager this packages,
deploys and registers each one, publishes its prompt to Parameter Manager and grants its
Agent Identity exactly what it declares. On this first run each OAuth client secret is
copied from its JSON into Secret Manager. When the summary reports every agent `ok`, delete
those three JSON files; the deploy reads the secrets from Secret Manager from now on. (Keep
the BigQuery MCP client's JSON for step 6, which deletes it.)

A failing agent does not stop the others; fix what the summary says and rerun (every step
is idempotent).

## 6. Connectors (Gemini Enterprise admin)

1. **BigQuery MCP**, for both no-code agents:

   ~~~bash
   uv run --group dev python deployment/deploy/no_code/create_mcp_connector.py --client-json deployment/secrets/<bigquery-mcp-client>.json --delete-json
   ~~~

   Then in the console, connect its data store to the app and enable its read-only actions
   ([guide, step 8](deployment-guide.md#8-connectors)).
2. **Confluence**, for Ticket Guidance: create it in the console (data ingestion), put its
   collection ID in `agents.ticket_guidance_agent.confluence_connector_id` and the space key
   in `confluence_space`, and redeploy that one agent:

   ~~~bash
   uv run --group dev python deployment/run.py deploy --only ticket_guidance_agent
   ~~~

3. **Gmail** (optional, Recipe Editorial): Data stores > Create > Gmail.

## 7. Deploy and publish the no-code agents

~~~bash
uv run --group dev python deployment/run.py deploy --skip-code
~~~

**PAUSE.** For each of Kitchen Sequencer and Recipe Editorial the run prints
`ACTION_REQUIRED=... open <link> and click Create`. Open the link, check the node shows
the BigQuery MCP connector, and click **Create**. Until then users cannot use the agent.

## 8. Give users access

1. Add the intended users to each agent's Google group (workbook, "Who may use the agent").
2. Give them access to the data they read as themselves: the performance sheet and report
   folder (Growth), the Vendor Match folders, and for the no-code agents
   `roles/mcp.toolUser` and `roles/bigquery.jobUser` on the project plus
   `roles/bigquery.dataViewer` on the datasets.
3. **PAUSE**, per user: the first time a user runs a code agent it shows **Authorize**; for
   the no-code agents they connect **BigQuery MCP** once from the connectors menu.

## 9. Test

~~~bash
uv run --group dev python deployment/run.py test
~~~

| Agent | What the check does in prod |
|---|---|
| Growth Analysis | Runs the pipeline and checks a report Doc was filed (several minutes; delete the Doc afterwards) |
| Vendor Match | Looks up `tests.vendor_lookup` in the master dictionary (read-only) |
| Ticket Guidance | Skipped: it would create a real ticket. Test it by hand below |
| Prompt Manager | Lists the agents' live configurations (read-only) |
| Kitchen Sequencer, Recipe Editorial | Checks the published agent has its connector and its tables answer through BigQuery MCP (read-only) |

Then a person checks each agent from **Agents** in the app (not the designer's Preview),
with the prompts in [the deployment guide's test table](deployment-guide.md#11-test-every-agent).
For Ticket Guidance, describe a known issue, confirm the ticket is created with you as
reporter, then close it.

## Later releases

| Change | Command | Pause |
|---|---|---|
| Code of a code agent | `run.py deploy --skip-no-code --only <agent>` | None |
| Prompt or model of a code agent | The Prompt Manager agent (live, versioned), or edit `prompt.md` and `run.py deploy --only <agent>` | None |
| Prompt of a no-code agent | Edit its `prompt.md`, then `run.py deploy --skip-code` | Click **Update** on each link |
| Connectors of a no-code agent | `deploy_no_code.py --agent <name> --recreate` | Click **Create** |
| A secret rotated | `gcloud secrets versions add <id> --data-file=-` and paste | None; agents read the new value within 5 minutes |
| Anything | `run.py check` reports drift and missing pieces | |

**Rollback.** Code: check out the previous release tag and rerun the deploy for that agent.
A prompt or model: Parameter Manager keeps every version; ask the Prompt Manager for the
earlier version and publish it again. A no-code agent: its previous definition is in Git;
redeploy it and click **Update**.

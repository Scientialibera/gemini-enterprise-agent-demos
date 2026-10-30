# No-code agents

A no-code agent has no runtime of its own: Gemini Enterprise runs it from an
instruction, a model and the connectors it may use. This folder is the source of
truth for those three things, so a change is reviewed like code and every environment
gets the same agent.

~~~text
agents/no_code/<name>/
  agent.yaml   display name, description, model, starter prompts, connectors
  prompt.md    the instruction; ${NAME} placeholders are filled at deploy time
~~~

| Agent | Connectors | Notes |
|---|---|---|
| recipe_editorial_agent | BigQuery MCP, Gmail | Reads recipe tables; emails the report. |
| kitchen_sequencer | BigQuery MCP | Reads the curated `kitchen_compliance` tables instead of Looker. |

## Deploy

~~~bash
uv run --group dev python deployment/deploy/no_code/deploy_no_code.py --all
uv run --group dev python deployment/deploy/no_code/deploy_no_code.py --agent kitchen_sequencer
~~~

`deployment/run.py` runs the same step after the code agents. The script:

1. Fills the prompt's `${NAME}` placeholders from `deployment/config.yaml`. Only names listed under
   `prompt_variables` are replaced, and a listed name that is unset stops the deploy.
2. Finds each connector in the app's project by type, and for a custom MCP connector by
   server URL. If an app has two of a type, set the variable named in `collection_env`.
   A connector marked `optional: true` (Recipe Editorial's Gmail) is skipped with a
   warning when the app has none.
3. Leaves the agent untouched when its published copy already matches the repository,
   so a rerun creates no draft. Otherwise it creates the agent, or updates the one with
   the same display name, as a **draft**. It refuses to overwrite a code agent or
   workflow with that name. `--recreate` deletes the existing agent first.
4. For a draft it prints `ACTION_REQUIRED` with the agent designer link: open it and
   click **Create** (new agent) or **Update**. Chat serves the previous version until
   then. Google has no API to publish an Agent Designer agent: the button calls an
   endpoint only the designer's own web session can reach (`:publish` only records a
   revision, and the published copy is read-only to the API), so this one click per
   change stays manual. `run.py check` flags any agent left unpublished or drifted.
5. Shares it with the agent's access group when access groups are enabled.

**Connectors are fixed at first publish.** Gemini Enterprise keeps the connectors an
agent had when it was first created; later updates change only its instruction and
model. After adding or changing an agent's connectors, recreate it and publish again:

~~~bash
uv run --group dev python deployment/deploy/no_code/deploy_no_code.py --agent kitchen_sequencer --recreate
~~~

The symptom is an agent that works in the designer's Preview but, deployed, says the
tool is unavailable, with its connector switch off and greyed out in chat.

**BigQuery MCP needs a project ID on every call.** Both prompts set `projectId` from
`GOOGLE_CLOUD_PROJECT` (the project that runs and bills the queries); without it the
agent asks the user for one. Kitchen Sequencer's prompt also lists the table columns so
it can query straight away.

## Keeping the repository and the designer in sync

The repository is the source of truth, but people will also edit these agents in the
agent designer. Google has no export file for Agent Designer agents; each one is an API
resource whose `lowCodeAgentDefinition` holds the same instruction, model, connectors and
starter prompts as these files. The deploy script reads it back:

~~~bash
# Where does the live agent differ from the repository? Changes nothing.
uv run --group dev python deployment/deploy/no_code/deploy_no_code.py --all --diff
# Pull designer edits into agent.yaml and prompt.md, then review and commit the diff.
uv run --group dev python deployment/deploy/no_code/deploy_no_code.py --agent kitchen_sequencer --export
~~~

Both use the published copy (what users chat with); add `--draft` for unsaved designer
work. Export turns environment values in the instruction back into their `${NAME}`
placeholders, so the files still deploy to any environment, and edits `agent.yaml` field
by field, keeping its comments. A connector change is reported, not exported: connectors
are matched by type per environment, so update them in `agent.yaml` by hand (and recreate
the agent; see above). `deployment/run.py check` flags every agent whose published copy
has drifted, either way: deploy and click **Update** to push the repository, or export to
pull the designer's version.

## Connectors are created in the console

Each connector holds an OAuth client or an admin consent that no API sets up, so it is
created once per app, by hand, before the first deploy.

| Connector | How to create |
|---|---|
| BigQuery MCP | Data stores > Create > Custom MCP server. Server URL `https://bigquery.googleapis.com/mcp`; OAuth with auth URI `https://accounts.google.com/o/oauth2/v2/auth`, extra params `&access_type=offline&prompt=consent`, token URI `https://oauth2.googleapis.com/token`, scope `https://www.googleapis.com/auth/bigquery`, and a dedicated Web OAuth client. |
| Gmail | Data stores > Create > Gmail (federated, with actions). |

Or script the BigQuery MCP connector with `deployment/deploy/no_code/create_mcp_connector.py
--client-json <downloaded client JSON> --delete-json`, which keeps the secret out of
the terminal. Either way, two things trip a new environment up:

- New organizations enforce `constraints/discoveryengine.managed.disableCustomMcpServerConnector`,
  which blocks every custom MCP connector. An org policy admin must set it to not
  enforced on the project (`gcloud org-policies set-policy` with `enforce: false`).
- The connector's data store must be connected to the app: Gemini Enterprise >
  Connected data stores > **Add existing data stores**. Until then the agent designer
  does not offer the connector. The console form does this itself; the script cannot.
- The connector's actions must be enabled: Data stores > the connector > **Actions**.
  Enable the read-only tools (`execute_sql_readonly`, `list_dataset_ids`,
  `get_dataset_info`, `list_table_ids`, `get_table_info`, `get_query_results`,
  `get_job`). With them disabled the agent says the tool is not available.
- Each user authorizes the connector once, from the connectors menu in any chat. Inside
  an agent its switch is greyed out because the agent always uses it.

Users of either agent need, on the execution project, `roles/mcp.toolUser` and
`roles/bigquery.jobUser`, plus `roles/bigquery.dataViewer` on the data they query. A
missing `mcp.toolUser` shows up as "User does not have mcp.tools.call permission".

## Add a no-code agent

Create a folder with `agent.yaml` and `prompt.md` (copy an existing one). Nothing needs
registering: every folder here is picked up by `--all` and by `deployment/run.py`.

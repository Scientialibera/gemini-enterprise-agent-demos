# Sample data

Synthetic data for deploying and testing every agent without access to production
systems. **Every value is made up.** Answers the agents give from it are not real.

| Agent | Sample data | How to load |
|---|---|---|
| Kitchen Sequencer | `hdr_analytics` source tables (12 kitchens, 14 weeks of orders, 5 weeks of items) | `seed.bigquery.sample_data` and `seed.bigquery.kitchen_compliance` |
| Recipe Editorial | `recipe_products` and `recipe_legacy` tables (8 recipes, 11 weekly cycles) | `seed.bigquery.sample_data` |
| Growth Analysis | `drive/growth_performance_sample.xlsx` | `seed.drive.enabled` (uploaded as a Google Sheet) |
| Vendor Match | `drive/master_vendor_dictionary.xlsx`, `drive/incoming_vendors_sample.xlsx` | `seed.drive.enabled` (master and source folders) |
| Ticket Guidance | `confluence/*.md` | `seed.atlassian.enabled` (created in the knowledge base space) |

## BigQuery

In `deployment/config.yaml`:

~~~yaml
seed:
  bigquery: {sample_data: true, kitchen_compliance: true}
agents:
  recipe_editorial_agent:
    product_dataset: <project>.recipe_products
    legacy_dataset: <project>.recipe_legacy
  kitchen_sequencer:
    source_project:            # empty: build from the sample tables in this project
~~~

`uv run --group dev python deployment/run.py seed` then creates the three datasets in
your project, replaces the sample tables, and builds the Kitchen Sequencer tables from
them. Dates are relative to the day you load, so rerun it to refresh "this week".
For the scheduled daily refresh, set Terraform's `kitchen_compliance.source_project` to
your own project.

The data is built to give the agents something to find:

- **Kitchen Sequencer:** Hoboken Kitchen and King of Prussia Kitchen get noticeably worse over the
  last two weeks; the drivers are force completes, short cooks, hot hold, pouches and scans.
- **Recipe Editorial:** SKUs `604430001` to `604430008`. Three have deliberate faults:
  `604430003` has active time longer than total time, `604430005` lists scallions but
  never uses them, and `604430006` calls for cilantro that is not listed. Each recipe
  has two ingredient versions; only version 2 is current.

The Kitchen column types match the production tables. The recipe tables' types follow the
agent's instructions, because their source schemas were not available.

## Drive

Set `seed.drive.enabled: true` and the Growth report folder and Vendor Match folders in
`config.yaml`, then run `deployment/run.py seed` with ADC that has the Drive scope:

~~~bash
gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/cloud-platform
uv run --group dev python deployment/run.py seed
~~~

It uploads only what is missing: the performance sheet (converted to a Google Sheet, in
`seed.drive.performance_sheet_folder_id` or else the report folder), the master dictionary
and the incoming vendor list. When `agents.growth_analysis_workflow.spreadsheet_id` is
empty it uses the seeded sheet for that run and prints the ID to add to the config. To
only write the files locally: `uv run --group dev python deployment/seed/sample_drive_files.py`. Every user who
tests the agents needs access to these files, since the agents act as the signed-in user.

The performance sheet has 12 stores (the same kitchens as the BigQuery data), five with
negative same-store sales. The incoming vendor list has variants of dictionary vendors,
new vendors with variants of their own, and look-alikes that must not be merged
(Blue Engine Marketing and Blue Cross Blue Shield).

## Confluence and Jira

Ticket Guidance needs a real Confluence space and Jira project; there is no way to fake
them in BigQuery. A free Atlassian Cloud site works:

1. Set the `atlassian` section and `agents.ticket_guidance_agent.confluence_space` in
   `config.yaml`, put the account's API token in Secret Manager
   (`ticket-guidance-jira-api-token`), and set `seed.atlassian.enabled: true`.
   `run.py seed` creates the space and the three articles, and checks the Jira project.
2. Create the Jira project yourself (a site admin choice): "Service Request" and
   "Incident Request" issue types if the site has them, "Done" and "In Progress" statuses.
3. Search the space either through a Confluence connector (needs a Workspace or Cloud
   Identity organization; set `confluence_connector_id`) or, without one, with
   `confluence_search_backend: api`.

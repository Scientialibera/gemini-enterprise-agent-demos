# Curated tables read by the Kitchen Sequencer no-code agent through the
# BigQuery MCP connector, replacing the Looker dashboards it used before.
# The statements are the same files the dev seeding script runs once.

locals {
  statements = {
    for file in sort(fileset(var.sql_dir, "*.sql")) :
    trimsuffix(file, ".sql") => templatefile("${var.sql_dir}/${file}", {
      SOURCE_PROJECT = var.source_project
      TARGET_PROJECT = var.project_id
      TARGET_DATASET = var.dataset_id
    })
  }
  # 01_dim_kitchen builds the dimension the others join, so it runs first.
  dimension_statement = "01_dim_kitchen"
}

resource "google_bigquery_dataset" "kitchen_compliance" {
  project     = var.project_id
  dataset_id  = var.dataset_id
  location    = var.location
  description = "Curated kitchen compliance tables read by Kitchen Sequencer. Rebuilt daily by scheduled queries."
  labels = {
    managed_by = "terraform"
    agent      = "kitchen-sequencer"
  }
}

# Runs the scheduled queries. It needs read access to the source dataset,
# granted in the source project by its owner; this stack cannot grant that.
resource "google_service_account" "refresh" {
  project      = var.project_id
  account_id   = "kitchen-compliance-refresh"
  display_name = "Kitchen compliance table refresh"
  description  = "Runs the scheduled queries that rebuild the Kitchen Sequencer tables."
}

resource "google_bigquery_dataset_iam_member" "refresh_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.kitchen_compliance.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.refresh.member
}

resource "google_project_iam_member" "refresh_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = google_service_account.refresh.member
}

# The agent queries as the signed-in user, so readers are people, not the agent.
resource "google_bigquery_dataset_iam_member" "readers" {
  for_each = var.reader_members

  project    = var.project_id
  dataset_id = google_bigquery_dataset.kitchen_compliance.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = each.value
}

resource "google_bigquery_data_transfer_config" "refresh" {
  for_each = local.statements

  project                = var.project_id
  location               = var.location
  display_name           = "kitchen-compliance ${each.key}"
  data_source_id         = "scheduled_query"
  schedule               = each.key == local.dimension_statement ? var.dimension_schedule : var.fact_schedule
  service_account_name   = google_service_account.refresh.email
  params = {
    query = each.value
  }

  depends_on = [
    google_bigquery_dataset_iam_member.refresh_editor,
    google_project_iam_member.refresh_job_user,
  ]
}

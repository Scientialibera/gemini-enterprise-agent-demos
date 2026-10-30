output "dataset" {
  value = "${var.project_id}.${google_bigquery_dataset.kitchen_compliance.dataset_id}"
}

output "refresh_service_account" {
  description = "Grant this roles/bigquery.dataViewer on the source hdr_analytics dataset."
  value       = google_service_account.refresh.email
}

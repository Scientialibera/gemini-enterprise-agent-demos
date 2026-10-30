variable "project_id" { type = string }

variable "source_project" {
  description = "Project holding hdr_analytics, the compliance source tables."
  type        = string
}

variable "dataset_id" { type = string }

variable "location" {
  description = "BigQuery location. Must match the source dataset's, since a query cannot read across locations."
  type        = string
}

variable "sql_dir" {
  description = "Directory of the ordered *.sql statements shared with the dev seeding script."
  type        = string
}

variable "dimension_schedule" {
  description = "Schedule for 01_dim_kitchen, which the other statements join. Runs before them."
  type        = string
}

variable "fact_schedule" {
  description = "Schedule for the remaining statements."
  type        = string
}

variable "reader_members" {
  description = "Principals (normally a group of agent users) granted read access to the curated dataset."
  type        = set(string)
}

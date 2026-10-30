variable "project_id" {
  description = "Existing Google Cloud project ID. Shared project creation belongs to foundation/bootstrap IaC."
  type        = string
}

variable "region" {
  description = "Region the agent runtimes in this project are deployed to."
  type        = string
  default     = "us-central1"
}

variable "managed_secrets" {
  description = <<-EOT
    Secret Manager secrets owned by this stack. Secrets are stored, not injected
    into the Agent Runtime: runtime secret_env is unsupported for source-archive
    deployments, and an agent that needs a secret reads it from Secret Manager
    using its own Agent Identity. `accessor_members` grants read access to the
    principals that must read the payload themselves, such as the release
    process that creates a Gemini Enterprise authorization from an OAuth client
    secret, so the value is stored once and never copied to a workstation.
  EOT
  type = map(object({
    secret_id        = string
    value_version    = optional(number, 1)
    labels           = optional(map(string), {})
    accessor_members = optional(set(string), [])
  }))
  default = {}
}

variable "secret_values" {
  description = "Ephemeral secret payloads keyed exactly like managed_secrets. Supply from an approved CI/secret source."
  type        = map(string)
  sensitive   = true
  ephemeral   = true
  default     = {}
}

variable "developer_deployer_members" {
  description = "Developers/groups allowed to use the agent repository dev deployment helpers."
  type        = set(string)
  default     = []
}

variable "developer_deployer_role" {
  description = "Project role granted to developer_deployer_members for Agent Engine create/update operations."
  type        = string
  default     = "roles/aiplatform.user"
}

variable "developer_parameter_access" {
  description = "Whether developer_deployer_members may read agent runtime configuration in Parameter Manager."
  type        = bool
  default     = true
}

variable "developer_staging_bucket_name" {
  description = "Optional existing staging bucket. Terraform grants developer write and Agent Identity read access without creating the bucket."
  type        = string
  default     = null
  nullable    = true
}

variable "developer_agent_identity_organization_id" {
  description = "Organization ID used to construct the Agent Identity trust-domain principal set. Null for an orgless project."
  type        = string
  default     = null
  nullable    = true
}

variable "developer_agent_identity_orgless" {
  description = "Set true when the project does not belong to a Google Cloud organization."
  type        = bool
  default     = false
}

variable "agent_identity_project_roles" {
  description = <<-EOT
    Baseline project roles granted to every Agent Identity in this project,
    through a trust-domain principal set rather than per-agent bindings. This is
    what lets a developer add an agent to the repository and deploy it without a
    Terraform change.

    Every role here reaches every current and future runtime in the project, so
    add one only when that is intended. Access to a specific bucket, dataset or
    secret belongs on the exact Agent Identity instead, at the narrowest
    practical scope; the agent repository's IAM helper applies those after a
    runtime exists.
  EOT
  type        = set(string)
  default     = null
  nullable    = true
}

variable "log_bucket_id" {
  description = "Optional Cloud Logging bucket ID for agent runtime logs."
  type        = string
  default     = null
  nullable    = true
}

variable "log_retention_days" {
  description = "Retention for the Agent Engine log bucket."
  type        = number
  default     = 90

  validation {
    condition     = var.log_retention_days >= 1
    error_message = "log_retention_days must be at least 1."
  }
}

variable "notification_channels" {
  description = "Existing Cloud Monitoring notification channel IDs."
  type        = list(string)
  default     = []
}

variable "required_services" {
  description = "Google Cloud APIs required by the workload stack."
  type        = set(string)
  default = [
    "aiplatform.googleapis.com",
    "parametermanager.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "telemetry.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
    # Gemini Enterprise: agent registration, authorizations, connectors.
    "discoveryengine.googleapis.com",
    # Called with the signed-in user's token by Growth Analysis and Vendor Match.
    # The OAuth consent screen only offers a scope once its API is enabled.
    "docs.googleapis.com",
    "drive.googleapis.com",
    "sheets.googleapis.com",
    # BigQuery MCP (Recipe Editorial, Kitchen Sequencer) and the curated tables.
    "bigquery.googleapis.com",
    "bigquerydatatransfer.googleapis.com",
  ]
}

variable "kitchen_compliance" {
  description = <<-EOT
    Curated BigQuery tables read by the Kitchen Sequencer no-code agent, rebuilt
    daily by scheduled queries from infrastructure/sql/kitchen_compliance. Null
    disables them. The refresh service account this creates must then be granted
    roles/bigquery.dataViewer on the source dataset by that project's owner.

    reader_members are the people (normally one group) who use the agent: it
    queries as the signed-in user, so they need read access, not the agent.
  EOT
  type = object({
    source_project     = string
    dataset_id         = optional(string, "kitchen_compliance")
    location           = optional(string, "US")
    dimension_schedule = optional(string, "every day 10:30")
    fact_schedule      = optional(string, "every day 11:00")
    reader_members     = optional(set(string), [])
  })
  default  = null
  nullable = true
}

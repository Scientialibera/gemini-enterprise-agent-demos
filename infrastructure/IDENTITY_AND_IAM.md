# Execution identities and IAM ownership

User access groups are separate from runtime identities. The optional
[registration helper](../docs/agent-access-groups.md) creates Cloud Identity
security groups and grants agent-use permission on Gemini Enterprise registrations.
It requires directory-admin credentials; this Terraform stack does not create or
manage those groups. Existing memberships remain under the group owner's control.

No application helper grants IAM to itself. The companion agent repository can,
when explicitly configured, grant approved roles to the exact Agent Identity of a
runtime that already exists. The caller running that helper must already have IAM
permission on the target resource.

## Identity matrix

| Actor | Authentication | Access assigned by | Purpose |
|---|---|---|---|
| Developer local run | User ADC | Terraform/platform IAM | Local agent and permitted dev resources |
| Developer deploy/update | User ADC | This stack | Agent Engine deploy and update operations |
| Terraform runner | GitHub OIDC -> WIF -> dedicated service account | Foundation/bootstrap IaC | Infrastructure changes |
| Agent runtime | Agent Identity | Common project principal-set roles plus exact per-agent grants | Agent Engine runtime access |
| Caller | User/group/workload identity | Granted per runtime outside this stack | Reasoning Engine invocation |
| Delegated user | Forwarded OAuth credential | Gemini Enterprise/auth flow | User-scoped downstream calls |
| Agent Platform service agent | Google-managed | This stack grants secret access | Platform operations |

## Developer identity

The agent repository `deploy_dev.py` and `update_dev.py` use ADC. Terraform can grant
`developer_deployer_members` Agent Engine access, Parameter Manager read access and
staging-bucket object access. Prefer a Google Group to repeated individual bindings.

Deployment permission does not imply IAM-administration permission. If a developer uses
`deployment/deploy/iam/apply_agent_identity_iam.py`, that caller must separately have the permission
required to update IAM on each configured project or bucket. The helper never grants
permissions to the caller itself.

## Agent Identity

Every Agent Engine created with `identity_type=AGENT_IDENTITY` receives a distinct
runtime identity. Developer permissions are not inherited by that identity.

This stack grants `agent_identity_project_roles` to the Agent Identity principal set
covering all Agent Runtime agents in the project, rather than to named identities. An
agent deployed later therefore inherits those baseline roles with no Terraform change,
which is what allows agents to be added to the monorepo independently of infrastructure.

Organization and orgless projects use different trust-domain prefixes; configure exactly
one through the provided variables.

The default baseline covers model/quota use and Parameter Manager reads. Defaults come
from runtime_iam_policy.json, which the sandbox helper also reads. Storage object reads
are granted only on developer_staging_bucket_name so runtimes can load source archives.
Every principal-set role reaches every current and future runtime, so add one only when
that is intended. Reference-agent data buckets require explicit exact-identity grants.

For an existing deployment, prepare the staging and business-bucket grants before
removing the former project-wide storage.objectViewer binding. Terraform removes its
tracked binding on apply when the role is absent from agent_identity_project_roles;
remove it from any custom override too. An IAM administrator must remove bindings
previously added by the sandbox helper, which never revokes access.

Access to a particular bucket, dataset or secret should target an individual Agent
Identity at the narrowest practical resource scope. The companion dev helper applies
explicitly configured exact-agent project roles, Cloud Storage bucket bindings and
Secret Manager secret bindings after deployment, once the Reasoning Engine ID exists.

Secrets are the case that matters here. Growth Analysis reads four third-party API keys
and Ticket Guidance a Jira service-account token. This stack creates each secret
(`managed_secrets`) and leaves `accessor_members` empty; the agent repository grants
`roles/secretmanager.secretAccessor` on each secret to the one Agent Identity that reads
it. Never add that role to `agent_identity_project_roles`: it would let every agent read
every other agent's credentials.

The scheduled queries that rebuild the Kitchen Sequencer tables run as a dedicated
service account, `kitchen-compliance-refresh`, with `bigquery.dataEditor` on the curated
dataset and `bigquery.jobUser` on the project. Its read access to the source dataset
lives in the source project and must be granted by that project's owner.

## Terraform runner

The workload stack assumes its execution identity already exists and is authorized.
Create the following in a separate foundation/bootstrap stack:

- Workload Identity Pool
- GitHub OIDC provider
- repository/branch/environment attribute restrictions
- dedicated Terraform service account
- `roles/iam.workloadIdentityUser` binding
- minimum Terraform infrastructure-management permissions
- remote-state bucket and IAM

Do not use downloaded long-lived service-account keys.

## Caller access

This stack does not grant Reasoning Engine invocation. Callers are granted on the
specific runtime by whatever deploys it, because the resource does not exist until then.

Do not grant Terraform administration permissions to an Agent Identity, and do not
reuse the Terraform runner service account as a runtime identity.

## Secrets

Agent Runtime application calls use Agent Identity, including reads from Secret Manager.
This stack does not inject secrets into the runtime environment, so no deployment-time
secret access is granted to the Agent Platform service agent.

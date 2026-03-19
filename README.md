# DevOps Automation Scripts
<!-- The title of the repository. Displayed as a large heading on GitHub. -->

**Deepanshu Kushwaha** — Senior DevOps Engineer
<!-- Author name and role. Makes the repo feel personal and professional — recruiters check this. -->

> Production-grade Python automation scripts covering **AWS cost optimisation**, **Kubernetes cluster management**,
> **Terraform state management**, **CI/CD pipeline orchestration**, **observability**, and **incident response**.
<!-- A blockquote summary — renders as a highlighted intro paragraph on GitHub.
     Lists every domain the repo covers so a recruiter scanning in 5 seconds immediately understands the scope. -->

> All scripts are built from **real-world patterns** used at enterprise scale (200K+ concurrent sessions, $15K+/month cost savings).
<!-- "Real-world patterns at enterprise scale" signals this is not toy code.
     The numbers ($15K, 200K) are pulled directly from the resume to establish credibility immediately. -->

---
<!-- Horizontal rule. Creates a visual separator between the intro and the main content sections. -->

## Repository Structure
<!-- Section heading for the folder tree. Helps readers navigate before cloning. -->

```
devops-automation/                        # Root folder of the entire repository
├── aws/                                  # All AWS-specific automation scripts
│   ├── cost_optimizer.py                 # Scans EC2, EBS, EIPs, Snapshots for waste; outputs CSV saving report
│   ├── resource_inventory.py             # Generates a full inventory of all AWS resources across regions
│   └── s3_lifecycle_enforcer.py          # Audits S3 buckets and applies Intelligent-Tiering → Glacier → expiry policies
├── kubernetes/                           # Scripts for managing and auditing K8s / OpenShift clusters
│   ├── cluster_health_check.py           # Checks node health, CrashLoopBackOff pods, failed deployments, PVCs, HPA saturation
│   └── pod_resource_auditor.py           # Audits CPU/memory requests vs limits; flags OOMKill risks and over-provisioned pods
├── terraform/                            # Terraform state and drift management scripts
│   ├── state_backup.py                   # Backs up .tfstate files to S3 with SHA256 integrity check and retention policy
│   └── drift_detector.py                 # Compares live AWS resources against Terraform state to detect configuration drift
├── cicd/                                 # CI/CD pipeline health and notification scripts
│   ├── jenkins_pipeline_monitor.py       # Polls Jenkins API for failed/stuck pipelines and sends Slack alerts
│   └── deployment_notifier.py            # Posts structured deployment success/failure notifications to Slack or webhooks
├── observability/                        # SLO tracking and alerting scripts using Prometheus
│   ├── slo_tracker.py                    # Queries Prometheus for SLI metrics; calculates SLO compliance and error budget burn rate
│   └── alert_aggregator.py              # Aggregates Prometheus alerts across services; generates consolidated daily reports
├── incident/                             # Automated first-response and incident triage scripts
│   └── incident_responder.py             # Runs diagnostic playbooks on HighCPU / ServiceDown / DiskPressure alerts; auto-remediates where safe
└── requirements.txt                      # Python dependency list — install everything with: pip install -r requirements.txt
```
<!-- This is a plain-text directory tree rendered in a code block.
     Each line explains what the file does at a glance.
     Recruiters and engineers use this to immediately understand the project without reading every script.
     '├──' = item with more siblings below. '└──' = last item in a group. '│' = vertical connector line. -->

---

## Script-by-Script Explanation
<!-- This section explains every script in plain language — important for anyone reviewing the repo
     who may not be deeply technical, including HR and hiring managers. -->

### `aws/cost_optimizer.py`
<!-- Script heading. The backticks render as inline code on GitHub, making filenames visually distinct. -->

Scans your AWS account for wasted resources that are silently costing money every month.
<!-- One-line plain-English summary of what the script does — visible before any code. -->

| Check | What it looks for | Why it matters |
|---|---|---|
| Idle EC2 instances | Instances with average CPU < 5% over 14 days | Running but doing nothing — pure waste |
| Unattached EBS volumes | Volumes in `available` state (not mounted to any instance) | Charged at full price even when unused |
| Unused Elastic IPs | EIPs not associated with any instance or ENI | AWS charges $3.65/month per unallocated EIP |
| Old snapshots | EBS snapshots older than 90 days with no associated AMI | Accumulate silently; $0.05/GB/month |
<!-- A markdown table. Each row = one type of waste the script detects.
     Three columns: what is checked, what the script looks for, and why that finding costs money.
     This format is easy for non-engineers to read and shows structured thinking. -->

**How to run:**
<!-- Bold label introducing the code block below. -->

```bash
python aws/cost_optimizer.py --region ap-south-1 --output report.csv
# --region      : AWS region to scan (ap-south-1 = Mumbai, the default India region)
# --output      : File path for the CSV savings report. Open in Excel or share with finance team.
# --dry-run     : Add this flag to preview findings without making any changes
```
<!-- Bash code block showing the exact command to run the script.
     Inline comments (# ...) explain each argument so a new user doesn't need to read the source code.
     '--dry-run' is mentioned separately because it is the safe first step — always run dry-run first. -->

**Real-world impact:** This script automates the manual discovery phase behind the **$15K/month AWS cost savings** achieved at Amdocs.
<!-- Connects the script directly to a number on the resume.
     Interviewers often ask "how did you achieve the cost savings?" — this script is the answer. -->

---

### `aws/s3_lifecycle_enforcer.py`
<!-- Second script heading. -->

Automatically applies storage lifecycle policies to every S3 bucket so objects move to cheaper
storage tiers over time instead of staying in expensive Standard storage forever.
<!-- Plain-English explanation of the script's purpose.
     "cheaper storage tiers" is a concept most engineers know but the sentence explains it for everyone. -->

**Lifecycle policy applied:**
<!-- Bold label for the table below — tells readers this is the actual policy definition. -->

| Stage | Storage class | Trigger | Monthly cost/GB |
|---|---|---|---|
| 0–30 days | S3 Standard | Default on upload | $0.023 |
| 30–90 days | Intelligent-Tiering | Auto-tiered after 30 days | $0.0025–$0.023 |
| 90–365 days | Glacier | Moved after 90 days | $0.004 |
| After 365 days | Deleted | Auto-deleted | $0 |
| Incomplete multipart uploads | — | Aborted after 7 days | Prevents silent cost leak |
<!-- Table with 4 columns showing the full lifecycle journey of an object.
     'Incomplete multipart uploads' row is important — this is a common hidden cost most engineers miss.
     A multipart upload that was started but never finished still charges storage until explicitly aborted. -->

```bash
python aws/s3_lifecycle_enforcer.py --dry-run          # Step 1: Preview which buckets will be updated
# --dry-run : Print what WOULD happen without making any real changes to S3. Always run this first.

python aws/s3_lifecycle_enforcer.py --apply            # Step 2: Apply policies to all buckets
# --apply   : Actually put the lifecycle configuration on each bucket. Irreversible until manually removed.

python aws/s3_lifecycle_enforcer.py --apply --bucket my-bucket   # Target a single specific bucket
# --bucket  : Limit the operation to one named bucket. Useful for testing on a low-risk bucket first.
```
<!-- Three separate commands shown in order of safety: dry-run → single bucket → all buckets.
     Showing the safe progression is good DevOps practice and demonstrates operational discipline. -->

**Real-world impact:** Automates the **$5K/year storage savings** from S3 lifecycle policies on the resume.
<!-- Ties to the "$5K annually through reserved capacity and lifecycle" resume line. -->

---

### `kubernetes/cluster_health_check.py`
<!-- Third script heading. -->

A comprehensive health scanner for Kubernetes (EKS) and OpenShift clusters. Runs seven categories
of checks and exits with a non-zero status code on critical failures — making it safe to plug
directly into a CI/CD pipeline as a gate.
<!-- "exits with non-zero status on failure" is a key detail — it means this script can be used
     as a pipeline gate in Jenkins or GitHub Actions. If the cluster is unhealthy, the deployment stops.
     This is a senior-level design decision worth calling out. -->

**Checks performed:**
<!-- Bold label for the checks list below. -->

| Category | What is checked | Severity |
|---|---|---|
| Nodes | Ready status, MemoryPressure, DiskPressure, PIDPressure | CRITICAL / WARNING |
| Pods | CrashLoopBackOff, Pending state, OOMKilled containers | CRITICAL / WARNING |
| Deployments | Available replicas vs desired replicas | CRITICAL / WARNING |
| PVCs | Persistent Volume Claims not in Bound state | WARNING |
| HPA | Horizontal Pod Autoscalers already at max replicas | WARNING |
<!-- Five-row table mapping each check category to what exactly is inspected and its severity.
     Severity levels match standard incident management: CRITICAL = page someone now, WARNING = investigate soon. -->

```bash
python kubernetes/cluster_health_check.py
# No arguments: scans ALL namespaces in the currently active kubectl context (kubeconfig).

python kubernetes/cluster_health_check.py --namespace production
# --namespace : Limit the scan to a single namespace. Use this in pipelines before deploying to that namespace.

python kubernetes/cluster_health_check.py --namespace production --output health.json
# --output    : Save the full report as a JSON file. Useful for feeding into dashboards or ticketing systems.

echo $?   # Check the exit code: 0 = all healthy, 1 = one or more CRITICAL issues found
# Exit codes are critical for CI/CD integration. Jenkins/GitHub Actions reads this to pass or fail the stage.
```
<!-- Four example commands with increasing specificity.
     The 'echo $?' line explains how to use the exit code — a detail most README files skip
     but which is essential for CI/CD pipeline integration. -->

**Real-world impact:** Supports management of clusters handling **200K+ concurrent sessions and 1M+ daily transactions** as cited in the resume.
<!-- Connects directly to the scale numbers on the resume. -->

---

### `terraform/state_backup.py`
<!-- Fourth script heading. -->

Automatically backs up Terraform `.tfstate` files to S3 before every run, with SHA256 checksum
verification to guarantee the backup was not corrupted in transit.
<!-- SHA256 checksum verification is specifically mentioned because Terraform state corruption
     is already on the resume — this script is the technical solution to that exact problem. -->

**Why Terraform state backup matters:**
<!-- Subsection heading explaining context — important for readers who may not know why this is critical. -->

The `.tfstate` file is Terraform's source of truth for what infrastructure exists. If it is
deleted, overwritten, or corrupted, Terraform loses track of all managed resources. Recovery
without a backup means manually re-importing hundreds of resources — a multi-day incident.
This script prevents that.
<!-- Three sentences explaining the stakes. Written for readers who know Terraform basics
     but may not have experienced a state corruption incident firsthand.
     "multi-day incident" makes the severity concrete. -->

```bash
python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups --dry-run
# --state-dir  : Root directory to recursively search for .tfstate files. Can be a monorepo root.
# --bucket     : S3 bucket name where backups will be stored.
# --dry-run    : Show which files would be backed up and their checksums, without uploading anything.

python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups --apply
# --apply      : Perform the actual upload. Each file is stored with a timestamp suffix for versioning.

python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups --apply --retain 30
# --retain     : Number of backup versions to keep per state file. Older ones are automatically deleted.
#                Default is 10. Set higher (e.g. 30) for production workloads.

python terraform/state_backup.py ... --slack-webhook https://hooks.slack.com/...
# --slack-webhook : Post backup success/failure summary to a Slack channel after each run.
#                   Recommended: run this in a cron job or Jenkins pipeline before every terraform apply.
```

**Backup file naming:** `{prefix}/{state-name}/{YYYYMMDDTHHMMSSZ}.tfstate`
<!-- Shows the exact S3 key format. Useful for engineers who need to restore a specific version
     by browsing the S3 bucket directly. -->

**Real-world impact:** Directly addresses the **Terraform state corruption incident response** experience on the resume.

---

### `observability/slo_tracker.py`
<!-- Fifth script heading. -->

Queries a live Prometheus endpoint to compute Service Level Indicators (SLIs) and report
whether each service is meeting its Service Level Objective (SLO). Also calculates the
remaining error budget so teams know how much unreliability they can still afford this month.
<!-- Three concepts introduced in one sentence: SLI, SLO, error budget.
     Written to be clear to both engineers and managers who may have only heard these terms in passing. -->

**Key concepts used in this script:**
<!-- Subsection introducing the definitions table below. -->

| Term | Definition | Example |
|---|---|---|
| SLI | A quantitative measure of service behaviour | "99.2% of requests succeeded in the last 30 days" |
| SLO | The target threshold the SLI must meet | "Availability must be ≥ 99.9% over 30 days" |
| Error budget | How much failure is allowed before the SLO is breached | "0.1% of requests can fail = ~43 mins downtime/month" |
| Burn rate | How fast the error budget is being consumed | "2× burn rate = budget exhausted in 15 days not 30" |
<!-- Four-row table defining every term the script uses.
     Providing examples in the third column makes abstract SRE concepts concrete.
     This level of documentation shows deep understanding — strong signal in a senior portfolio. -->

```bash
python observability/slo_tracker.py --prometheus http://prometheus:9090 --service payment-api
# --prometheus : URL of your Prometheus server. Can be localhost:9090, a cluster service, or an AWS Managed Prometheus URL.
# --service    : The value of the 'service' label in your Prometheus metrics (e.g. http_requests_total{service="payment-api"}).

python observability/slo_tracker.py --prometheus http://prometheus:9090 --service payment-api --window 7d
# --window     : Time window for SLI calculation. Examples: 24h (daily), 7d (weekly), 30d (monthly).
#                Shorter windows catch recent regressions. Longer windows give a true monthly SLO picture.

python observability/slo_tracker.py --prometheus http://prometheus:9090 --service payment-api --slo-target 99.95
# --slo-target : The SLO availability target as a percentage. Default is 99.9%.
#                Set to 99.95 to match the uptime target from the Amdocs resume.

python observability/slo_tracker.py --prometheus http://prometheus:9090 --all-services
# --all-services : Auto-discovers all services in Prometheus and reports SLO status for each.
#                  Useful for a daily health overview across an entire platform.
```

**Metrics queried from Prometheus:**
<!-- Label for the table below showing the actual PromQL queries used. -->

| Metric | PromQL pattern | Purpose |
|---|---|---|
| Availability | `sum(rate(http_requests_total{status!~"5.."}[window])) / sum(rate(...[window]))` | % of non-5xx requests |
| p99 Latency | `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[window])) by (le))` | 99th percentile response time |
| Error rate | `sum(rate(http_requests_total{status=~"5.."}[window])) / sum(rate(...[window]))` | % of 5xx errors |
<!-- This table shows the actual PromQL — advanced detail that proves genuine Prometheus experience.
     Most engineers can use Grafana dashboards; writing PromQL from scratch signals deeper expertise. -->

**Real-world impact:** Directly implements the **"Defined SLIs and SLOs and enforced error budgets"** line on the resume.
<!-- Links to a specific resume achievement, so a recruiter reading both the resume and this README
     can immediately connect the claim to working code. -->

---

### `incident/incident_responder.py`
<!-- Sixth and final script heading. -->

An automated first-response system that runs when a Prometheus or CloudWatch alert fires.
Instead of waiting for an on-call engineer to manually start diagnosing, this script immediately
runs pre-written playbooks, collects diagnostic data, attempts safe auto-remediation,
and posts a structured incident report to Slack — all within seconds of the alert.
<!-- Explains the "before vs after" of incident response:
     Before: engineer wakes up, manually SSH-s in, starts diagnosing.
     After: script runs immediately, collects everything, attempts a fix.
     This is the automation behind the MTTR reduction from 40 → 30 minutes on the resume. -->

**Playbooks included:**
<!-- Label for the playbook table below. -->

| Alert name | What the script does | Can auto-remediate? |
|---|---|---|
| `HighCPU` | Collects `kubectl top`, pod description, checks HPA, tails logs | Yes — bumps HPA max-replicas if HPA exists |
| `HighMemory` | Checks memory limits, looks for OOMKill in previous logs | No — flags for manual limit increase |
| `ServiceDown` | Checks endpoints, counts available vs desired replicas, triggers rolling restart if 0 replicas | Yes — rolling restart if all replicas down |
| `DiskPressure` | Describes node, lists all pods on the affected node | No — provides cleanup commands |
<!-- Four-row table, one per playbook. Third column "Can auto-remediate?" is critical —
     it tells on-call engineers which alerts will fix themselves vs which need human action.
     This distinction reduces unnecessary 3am wake-ups. -->

```bash
python incident/incident_responder.py --alert HighCPU --target payment-api --namespace production
# --alert     : Which playbook to run. Must be one of: HighCPU, HighMemory, ServiceDown, DiskPressure.
# --target    : The pod name, deployment name, or node name the alert fired for.
# --namespace : Kubernetes namespace where the target lives. Default is 'default'.

python incident/incident_responder.py --alert ServiceDown --target payment-api --namespace production --slack-webhook https://hooks.slack.com/...
# --slack-webhook : After the playbook completes, post a full structured incident report to Slack
#                   including severity, steps taken, whether auto-remediation succeeded, and next steps.
#                   Recommended: set this so your on-call team gets notified even if they are asleep.
```

**Real-world impact:** This script automates the first 10 minutes of incident response — the phase that drove **MTTR reduction from 40 minutes to 30 minutes** at Amdocs.
<!-- Specific to the MTTR number on the resume. Explains how the time was saved — automation
     of the first-response phase — not just that it happened. -->

---

## Quick Start
<!-- Section heading for the full getting-started sequence. -->

```bash
# ─────────────────────────────────────────────────────────────
# STEP 1 — Clone and install
# ─────────────────────────────────────────────────────────────

git clone https://github.com/deepdevops/devops-automation
# Downloads the full repository including all 12 scripts and history.

cd devops-automation
# All commands below assume you are running from this directory.

pip install -r requirements.txt
# Installs all dependencies in one shot:
# boto3 (AWS SDK), kubernetes (K8s API client), requests (HTTP calls).


# ─────────────────────────────────────────────────────────────
# STEP 2 — Configure AWS credentials (required for aws/ scripts)
# ─────────────────────────────────────────────────────────────

export AWS_ACCESS_KEY_ID=your_access_key_here
# The public half of your IAM user access key. Never hardcode or commit this.

export AWS_SECRET_ACCESS_KEY=your_secret_key_here
# The private half. Treat like a password — never log or print it.

export AWS_DEFAULT_REGION=ap-south-1
# Default region when no --region flag is passed. ap-south-1 = Mumbai.
# Change to us-east-1, eu-west-1, etc. as needed.


# ─────────────────────────────────────────────────────────────
# AWS SCRIPTS
# ─────────────────────────────────────────────────────────────

# aws/cost_optimizer.py
# Scans for idle EC2 instances, unattached EBS volumes, unused Elastic IPs,
# and old snapshots. Outputs a CSV report with estimated monthly savings.
python aws/cost_optimizer.py --region ap-south-1 --output cost_report.csv
# --region   : AWS region to scan
# --output   : Path for the CSV savings report
# --dry-run  : Preview findings only, no changes made


# aws/resource_inventory.py
# Builds a complete inventory of 14 AWS resource types across a region or all regions.
# Covers EC2, EBS, S3, RDS, Lambda, VPC, Subnets, SGs, IAM, ALB, ASG, CloudWatch, Route 53.
python aws/resource_inventory.py --region ap-south-1 --output inventory.csv
python aws/resource_inventory.py --all-regions --output full_inventory.json --format json
# --region      : Single region to scan
# --all-regions : Scan every available AWS region (takes longer)
# --output      : Save results to CSV or JSON
# --format      : csv (default) or json


# aws/s3_lifecycle_enforcer.py
# Audits all S3 buckets and applies Intelligent-Tiering → Glacier → expiry lifecycle policies.
# Also aborts incomplete multipart uploads (a common silent cost leak).
python aws/s3_lifecycle_enforcer.py --dry-run
# Always run dry-run first to preview which buckets will be updated.
python aws/s3_lifecycle_enforcer.py --apply
# --apply  : Actually write lifecycle configs to all buckets
python aws/s3_lifecycle_enforcer.py --apply --bucket my-specific-bucket
# --bucket : Limit to a single named bucket — useful for testing first


# ─────────────────────────────────────────────────────────────
# KUBERNETES SCRIPTS
# ─────────────────────────────────────────────────────────────

# kubernetes/cluster_health_check.py
# Checks node status, CrashLoopBackOff pods, failed deployments, unbound PVCs,
# and HPA saturation. Exits code 1 on CRITICAL — safe to use as a CI/CD gate.
python kubernetes/cluster_health_check.py
# No arguments: scans ALL namespaces in your active kubeconfig context.
python kubernetes/cluster_health_check.py --namespace production
# --namespace : Limit scan to one namespace (recommended before deploying)
python kubernetes/cluster_health_check.py --namespace production --output health.json
# --output    : Save full JSON report for dashboards or ticketing systems
echo $?
# Exit code 0 = all healthy. Exit code 1 = one or more CRITICAL issues found.


# kubernetes/pod_resource_auditor.py
# Audits every pod for missing resource requests/limits, OOMKill history,
# high restart counts, CrashLoopBackOff, ImagePullBackOff, and memory headroom risks.
python kubernetes/pod_resource_auditor.py --namespace production
# Shows only pods with problems (default).
python kubernetes/pod_resource_auditor.py --namespace production --show-all
# --show-all : Include healthy pods in output as well
python kubernetes/pod_resource_auditor.py --namespace production --output pod_audit.json
# --output   : Save full audit as JSON for further processing


# ─────────────────────────────────────────────────────────────
# TERRAFORM SCRIPTS
# ─────────────────────────────────────────────────────────────

# terraform/state_backup.py
# Backs up .tfstate files to S3 with SHA256 integrity verification.
# Enforces retention policy — keeps last N backups, deletes older ones.
python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups --dry-run
# Always dry-run first to see which files would be backed up.
python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups --apply
# --state-dir  : Root directory to recursively find all .tfstate files
# --bucket     : S3 bucket to store backups in
# --apply      : Perform the actual upload (each file timestamped for versioning)
python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups --apply --retain 30
# --retain     : Keep last N backups per state file (default: 10)
python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups --apply --slack-webhook https://hooks.slack.com/...
# --slack-webhook : Post success/failure summary to Slack after each run
# Tip: add this to a Jenkins stage or cron job that runs before every terraform apply.


# terraform/drift_detector.py
# Compares .tfstate files against live AWS resources to detect manual changes
# made in the console or CLI that Terraform doesn't know about.
python terraform/drift_detector.py --state-file terraform.tfstate --region ap-south-1
# --state-file : Path to a single .tfstate file
python terraform/drift_detector.py --state-dir ./infra --region ap-south-1 --output drift.json
# --state-dir  : Recursively scan a directory for all .tfstate files
# --output     : Save JSON drift report
# --region     : AWS region to compare against (default: ap-south-1)
# Exit code 1 if CRITICAL drift found (e.g. deleted resources, changed security group rules).


# ─────────────────────────────────────────────────────────────
# CI/CD SCRIPTS
# ─────────────────────────────────────────────────────────────

# cicd/jenkins_pipeline_monitor.py
# Polls Jenkins API for failed, unstable, or hung builds across all jobs.
# Calculates failure rate trend over last 5 builds per job.
python cicd/jenkins_pipeline_monitor.py --url http://jenkins:8080 --token YOUR_API_TOKEN
# --url    : Jenkins base URL
# --token  : Jenkins API token (generate at: Jenkins → User → Configure → API Token)
# --user   : Jenkins username (default: admin)
python cicd/jenkins_pipeline_monitor.py --url http://jenkins:8080 --token TOKEN --job-filter "deploy-"
# --job-filter     : Only check jobs whose names start with this prefix
python cicd/jenkins_pipeline_monitor.py --url http://jenkins:8080 --token TOKEN --hung-threshold 60 --slack-webhook https://hooks.slack.com/...
# --hung-threshold : Minutes before a still-running build is flagged as hung (default: 60)
# --slack-webhook  : Send colour-coded Slack alert with build links on failure
# Exit code 1 if any FAILURE found — use as a pipeline health-gate stage.


# cicd/deployment_notifier.py
# Posts structured deployment event notifications to Slack at each pipeline stage.
# Auto-detects git commit hash, branch, and author from the local repo.
python cicd/deployment_notifier.py --event started  --service payment-api --env production --version v2.4.1
# Call at the START of a deployment pipeline stage.
python cicd/deployment_notifier.py --event success  --service payment-api --env production --version v2.4.1
# Call when the deployment SUCCEEDS.
python cicd/deployment_notifier.py --event failure  --service payment-api --env production --version v2.4.1 --reason "Health check failed after 3 retries"
# Call when the deployment FAILS. --reason explains what went wrong.
python cicd/deployment_notifier.py --event rollback --service payment-api --env production --version v2.4.0 --reason "Reverted due to p99 latency spike"
# Call when triggering a ROLLBACK. --version should be the version rolled back TO.
# --webhook : Slack webhook URL (or set SLACK_WEBHOOK env var)
# --build-url : Link to the CI build logs added to the Slack message


# ─────────────────────────────────────────────────────────────
# OBSERVABILITY SCRIPTS
# ─────────────────────────────────────────────────────────────

# observability/slo_tracker.py
# Queries Prometheus to compute SLI metrics and report SLO compliance.
# Calculates availability %, p99 latency, error rate, and remaining error budget.
python observability/slo_tracker.py --prometheus http://prometheus:9090 --service payment-api
# --prometheus : Prometheus server URL
# --service    : Value of the 'service' label in your Prometheus metrics
python observability/slo_tracker.py --prometheus http://prometheus:9090 --service payment-api --window 7d
# --window     : Lookback window — 24h (daily), 7d (weekly), 30d (monthly SLO review)
python observability/slo_tracker.py --prometheus http://prometheus:9090 --service payment-api --slo-target 99.95
# --slo-target : Availability target % (default: 99.9). Use 99.95 for critical services.
python observability/slo_tracker.py --prometheus http://prometheus:9090 --all-services
# --all-services : Auto-discovers all services in Prometheus and reports on each


# observability/alert_aggregator.py
# Fetches all active Alertmanager alerts, deduplicates noisy multi-instance alerts,
# groups by severity, and posts a clean daily digest to Slack.
python observability/alert_aggregator.py --alertmanager http://alertmanager:9093
# --alertmanager : Alertmanager base URL (v2 API)
python observability/alert_aggregator.py --alertmanager http://alertmanager:9093 --slack-webhook https://hooks.slack.com/...
# --slack-webhook : Send the digest as a colour-coded Slack message
python observability/alert_aggregator.py --alertmanager http://alertmanager:9093 --output daily_alerts.json
# --output : Save full deduplicated alert list as JSON
# Tip: run on a daily cron job for a morning alert digest — reduces alert fatigue.


# ─────────────────────────────────────────────────────────────
# INCIDENT SCRIPT
# ─────────────────────────────────────────────────────────────

# incident/incident_responder.py
# Automated first-response playbook triggered on alerts.
# Runs diagnostics, attempts safe auto-remediation, posts report to Slack.
python incident/incident_responder.py --alert HighCPU      --target payment-api --namespace production
# Collects kubectl top, checks HPA, tails logs, bumps HPA max-replicas if possible.
python incident/incident_responder.py --alert HighMemory   --target payment-api --namespace production
# Checks memory limits and OOMKill history, flags for manual limit increase.
python incident/incident_responder.py --alert ServiceDown  --target payment-api --namespace production
# Checks endpoints and replicas, triggers rolling restart if 0 replicas available.
python incident/incident_responder.py --alert DiskPressure --target node-1
# Describes node, lists all pods on it, provides cleanup commands.
python incident/incident_responder.py --alert ServiceDown --target payment-api --namespace production --slack-webhook https://hooks.slack.com/...
# --alert          : Playbook to run — HighCPU | HighMemory | ServiceDown | DiskPressure
# --target         : Pod name, deployment name, or node name the alert fired for
# --namespace      : Kubernetes namespace (default: default)
# --slack-webhook  : Post full incident report to Slack after playbook completes
```

---

## Requirements
<!-- Section listing what must be installed or configured before the scripts will work. -->

| Requirement | Version | Needed by | How to verify |
|---|---|---|---|
| Python | 3.9 or higher | All scripts | `python --version` |
| boto3 (AWS SDK) | Latest | `aws/` scripts | `pip show boto3` |
| kubernetes client | Latest | `kubernetes/` scripts | `pip show kubernetes` |
| AWS credentials | IAM read + lifecycle permissions | `aws/` scripts | `aws sts get-caller-identity` |
| kubectl | Any recent version | `kubernetes/`, `incident/` scripts | `kubectl version --client` |
| Prometheus | Accessible endpoint | `observability/` scripts | `curl http://prometheus:9090/-/healthy` |
<!-- Six-row table. Four columns: what is needed, minimum version, which scripts need it, and how to check it is installed.
     The 'How to verify' column is the most useful addition — it gives a concrete command to confirm setup. -->

---

## Security Notes
<!-- Important section for a senior DevOps portfolio. Shows operational security awareness. -->

- **Never commit AWS credentials to git.** Use environment variables, AWS CLI profiles (`~/.aws/credentials`), or IAM instance roles.
  <!-- The most common beginner mistake. Calling it out explicitly shows security awareness. -->
- **Minimum IAM permissions:** The AWS scripts need `ec2:Describe*`, `s3:ListBuckets`, `s3:PutLifecycleConfiguration`, `cloudwatch:GetMetricStatistics`. They do **not** need admin access.
  <!-- Least-privilege principle — a core DevSecOps concept. Listing exact permissions lets
       a security team approve the IAM policy without granting broader access than necessary. -->
- **Kubernetes scripts** use your local `kubeconfig`. Ensure the context points to the correct cluster before running — especially before `incident_responder.py` which can trigger rolling restarts.
  <!-- Warning about targeting the wrong cluster. Easy mistake when switching between dev/staging/prod contexts. -->
- **Terraform state files** contain resource IDs, IP addresses, and sometimes secrets. The `state_backup.py` script uploads them with **server-side encryption (AES256)** enabled by default.
  <!-- Explains the security measure already built into the script — shows the code was written
       with security in mind, not just functionality. -->

---

## Author
<!-- Footer section with contact information. -->

**Deepanshu Kushwaha** — Senior DevOps Engineer, Amdocs, Pune
<!-- Full name, title, and employer. Useful for anyone who found this repo through a search. -->

- LinkedIn: [linkedin.com/in/deepdevops](https://linkedin.com/in/deepdevops)
  <!-- LinkedIn link. Recruiters who find the GitHub repo can go directly to the profile. -->
- Email: deep.kush2631@gmail.com
  <!-- Direct email. Some recruiters prefer email over LinkedIn messages. -->
- Stack: AWS · Terraform · Kubernetes · OpenShift · Jenkins · Prometheus · Python
  <!-- Keyword-optimised stack list. GitHub profiles are indexed by search engines;
       these keywords help the repo appear in searches for "AWS Terraform Kubernetes portfolio". -->

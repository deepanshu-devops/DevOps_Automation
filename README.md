# DevOps Automation Scripts
**Deepanshu Kushwaha** — Senior DevOps Engineer

Production-grade Python automation scripts covering AWS cost optimisation, Kubernetes cluster management,
Terraform state management, CI/CD pipeline orchestration, observability, and incident response.

All scripts are built from real-world patterns used at enterprise scale.

---

## Repository Structure

```
devops-automation/
├── aws/
│   ├── cost_optimizer.py          # Identify and right-size idle/underutilised AWS resources
│   ├── resource_inventory.py      # Full AWS resource inventory across regions
│   └── s3_lifecycle_enforcer.py   # Enforce S3 lifecycle policies for cost reduction
├── kubernetes/
│   ├── cluster_health_check.py    # Comprehensive K8s cluster health reporter
│   └── pod_resource_auditor.py    # Audit pod resource requests/limits and OOM risks
├── terraform/
│   ├── state_backup.py            # Automated Terraform state backup to S3
│   └── drift_detector.py          # Detect infrastructure drift from Terraform state
├── cicd/
│   ├── jenkins_pipeline_monitor.py # Monitor Jenkins pipeline health and failures
│   └── deployment_notifier.py     # Slack/webhook notifications for deployments
├── observability/
│   ├── slo_tracker.py             # Calculate and report SLI/SLO error budgets
│   └── alert_aggregator.py        # Aggregate Prometheus alerts and generate reports
├── incident/
│   └── incident_responder.py      # Automated first-response playbook on alerts
└── requirements.txt
```

---

## Quick Start

```bash
git clone https://github.com/deepdevops/devops-automation
cd devops-automation
pip install -r requirements.txt

# Set AWS credentials
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-south-1

# Run AWS cost optimizer
python aws/cost_optimizer.py --region ap-south-1 --output report.csv

# Run K8s cluster health check
python kubernetes/cluster_health_check.py --namespace production

# Track SLO error budget
python observability/slo_tracker.py --service payment-api --window 30d
```

---

## Requirements
- Python 3.9+
- AWS credentials configured (IAM read permissions minimum)
- kubectl configured for cluster scripts
- Prometheus endpoint accessible for observability scripts

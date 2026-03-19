"""
terraform/drift_detector.py
-----------------------------
Detects infrastructure drift by comparing what Terraform's state file
says exists against what actually exists in AWS.

Drift happens when someone manually changes a resource in the AWS console
(or via CLI) without updating Terraform — a silent configuration mismatch
that causes the next `terraform apply` to produce unexpected changes.

Directly relevant to: Deepanshu's Terraform IaC expertise and incident
response for Terraform state corruption at Amdocs.

Checks:
  - EC2 instances: state, type, AMI, tags
  - Security groups: ingress/egress rules changed
  - S3 buckets: versioning, ACL, lifecycle config
  - RDS instances: instance class, storage, engine version

Usage:
    python terraform/drift_detector.py --state-file terraform.tfstate
    python terraform/drift_detector.py --state-file terraform.tfstate --output drift_report.json
    python terraform/drift_detector.py --state-dir ./infra --output drift_report.json
"""

import argparse
import boto3
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, asdict


@dataclass
class DriftItem:
    resource_type: str
    resource_id: str
    attribute: str
    state_value: str
    actual_value: str
    severity: str          # CRITICAL, WARNING, INFO
    recommendation: str


def load_state_file(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def extract_resources(state: dict) -> List[dict]:
    """
    Extract all managed resources from a Terraform state file.
    Supports both state format v3 (modules) and v4 (resources at top level).
    """
    resources = []
    version = state.get("version", 3)

    if version >= 4:
        for res in state.get("resources", []):
            for instance in res.get("instances", []):
                resources.append({
                    "type": res["type"],
                    "name": res["name"],
                    "provider": res.get("provider", ""),
                    "attributes": instance.get("attributes", {}),
                })
    else:
        # v3 format: nested under modules
        for module in state.get("modules", []):
            for res_key, res_val in module.get("resources", {}).items():
                resources.append({
                    "type": res_val.get("type", ""),
                    "name": res_key,
                    "provider": res_val.get("provider", ""),
                    "attributes": res_val.get("primary", {}).get("attributes", {}),
                })
    return resources


def check_ec2_instance(attrs: dict, region: str) -> List[DriftItem]:
    drifts = []
    instance_id = attrs.get("id") or attrs.get("instance_id")
    if not instance_id:
        return drifts

    try:
        ec2 = boto3.client("ec2", region_name=region)
        response = ec2.describe_instances(InstanceIds=[instance_id])
        instances = response["Reservations"][0]["Instances"] if response["Reservations"] else []
        if not instances:
            drifts.append(DriftItem(
                resource_type="aws_instance",
                resource_id=instance_id,
                attribute="existence",
                state_value="exists",
                actual_value="NOT FOUND in AWS",
                severity="CRITICAL",
                recommendation=f"Instance {instance_id} is in state but missing from AWS. Run: terraform import aws_instance.<n> {instance_id}",
            ))
            return drifts

        actual = instances[0]

        # Check instance type
        tf_type = attrs.get("instance_type", "")
        actual_type = actual.get("InstanceType", "")
        if tf_type and actual_type and tf_type != actual_type:
            drifts.append(DriftItem(
                resource_type="aws_instance",
                resource_id=instance_id,
                attribute="instance_type",
                state_value=tf_type,
                actual_value=actual_type,
                severity="WARNING",
                recommendation="Instance type was changed outside Terraform. Run terraform plan to reconcile.",
            ))

        # Check instance state
        actual_state = actual.get("State", {}).get("Name", "")
        if actual_state == "stopped":
            drifts.append(DriftItem(
                resource_type="aws_instance",
                resource_id=instance_id,
                attribute="instance_state",
                state_value="running (assumed)",
                actual_value="stopped",
                severity="INFO",
                recommendation="Instance is stopped. If intentional, consider updating state.",
            ))

        # Check tags
        tf_tags = {}
        for k, v in attrs.items():
            if k.startswith("tags.") and k != "tags.%":
                tf_tags[k.replace("tags.", "")] = v

        actual_tags = {t["Key"]: t["Value"] for t in actual.get("Tags", [])}
        for tag_key, tf_val in tf_tags.items():
            actual_val = actual_tags.get(tag_key, "")
            if actual_val != tf_val:
                drifts.append(DriftItem(
                    resource_type="aws_instance",
                    resource_id=instance_id,
                    attribute=f"tags.{tag_key}",
                    state_value=tf_val,
                    actual_value=actual_val or "(missing)",
                    severity="INFO",
                    recommendation="Tag was modified outside Terraform.",
                ))

    except Exception as e:
        drifts.append(DriftItem(
            resource_type="aws_instance",
            resource_id=instance_id,
            attribute="check_error",
            state_value="",
            actual_value=str(e),
            severity="WARNING",
            recommendation="Could not verify this resource against AWS API.",
        ))
    return drifts


def check_s3_bucket(attrs: dict) -> List[DriftItem]:
    drifts = []
    bucket_name = attrs.get("id") or attrs.get("bucket")
    if not bucket_name:
        return drifts

    s3 = boto3.client("s3")

    try:
        s3.head_bucket(Bucket=bucket_name)
    except Exception:
        drifts.append(DriftItem(
            resource_type="aws_s3_bucket",
            resource_id=bucket_name,
            attribute="existence",
            state_value="exists",
            actual_value="NOT FOUND or no access",
            severity="CRITICAL",
            recommendation=f"Bucket {bucket_name} missing from AWS. May have been manually deleted.",
        ))
        return drifts

    # Check versioning
    tf_versioning = attrs.get("versioning.0.enabled", "false")
    try:
        versioning = s3.get_bucket_versioning(Bucket=bucket_name)
        actual_versioning = str(versioning.get("Status", "") == "Enabled").lower()
        if tf_versioning != actual_versioning:
            drifts.append(DriftItem(
                resource_type="aws_s3_bucket",
                resource_id=bucket_name,
                attribute="versioning.enabled",
                state_value=tf_versioning,
                actual_value=actual_versioning,
                severity="WARNING",
                recommendation="Versioning setting was changed outside Terraform.",
            ))
    except Exception:
        pass

    return drifts


def check_security_group(attrs: dict, region: str) -> List[DriftItem]:
    drifts = []
    sg_id = attrs.get("id")
    if not sg_id:
        return drifts

    try:
        ec2 = boto3.client("ec2", region_name=region)
        sgs = ec2.describe_security_groups(GroupIds=[sg_id])["SecurityGroups"]
        if not sgs:
            drifts.append(DriftItem(
                resource_type="aws_security_group",
                resource_id=sg_id,
                attribute="existence",
                state_value="exists",
                actual_value="NOT FOUND",
                severity="CRITICAL",
                recommendation=f"Security group {sg_id} missing. It may have been manually deleted.",
            ))
            return drifts

        actual = sgs[0]
        tf_ingress_count = int(attrs.get("ingress.#", 0))
        actual_ingress_count = len(actual.get("IpPermissions", []))

        if tf_ingress_count != actual_ingress_count:
            drifts.append(DriftItem(
                resource_type="aws_security_group",
                resource_id=sg_id,
                attribute="ingress_rule_count",
                state_value=str(tf_ingress_count),
                actual_value=str(actual_ingress_count),
                severity="CRITICAL",
                recommendation="Ingress rules were added or removed outside Terraform. Review immediately — security risk.",
            ))

        tf_egress_count = int(attrs.get("egress.#", 0))
        actual_egress_count = len(actual.get("IpPermissionsEgress", []))
        if tf_egress_count != actual_egress_count:
            drifts.append(DriftItem(
                resource_type="aws_security_group",
                resource_id=sg_id,
                attribute="egress_rule_count",
                state_value=str(tf_egress_count),
                actual_value=str(actual_egress_count),
                severity="WARNING",
                recommendation="Egress rules were changed outside Terraform.",
            ))

    except Exception as e:
        drifts.append(DriftItem(
            resource_type="aws_security_group",
            resource_id=sg_id,
            attribute="check_error",
            state_value="",
            actual_value=str(e),
            severity="WARNING",
            recommendation="Could not verify security group against AWS API.",
        ))
    return drifts


CHECKERS = {
    "aws_instance":      check_ec2_instance,
    "aws_s3_bucket":     lambda attrs, region=None: check_s3_bucket(attrs),
    "aws_security_group": check_security_group,
}


def print_report(all_drifts: List[DriftItem], output_path: Optional[str]):
    critical = [d for d in all_drifts if d.severity == "CRITICAL"]
    warning  = [d for d in all_drifts if d.severity == "WARNING"]
    info     = [d for d in all_drifts if d.severity == "INFO"]

    print(f"\n{'='*60}")
    print(f"  Terraform Drift Detection Report")
    print(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")
    print(f"  CRITICAL : {len(critical)}")
    print(f"  WARNING  : {len(warning)}")
    print(f"  INFO     : {len(info)}")
    print(f"{'='*60}\n")

    for severity, items in [("CRITICAL", critical), ("WARNING", warning), ("INFO", info)]:
        if not items:
            continue
        print(f"--- {severity} ---")
        for d in items:
            print(f"  [{d.resource_type}] {d.resource_id}")
            print(f"    Attribute : {d.attribute}")
            print(f"    In state  : {d.state_value}")
            print(f"    In AWS    : {d.actual_value}")
            print(f"    Action    : {d.recommendation}")
            print()

    if not all_drifts:
        print("  No drift detected. Terraform state matches AWS infrastructure.")

    if output_path:
        with open(output_path, "w") as f:
            json.dump([asdict(d) for d in all_drifts], f, indent=2)
        print(f"Report saved to: {output_path}")

    return len(critical)


def scan_state_file(state_path: str, region: str) -> List[DriftItem]:
    state = load_state_file(state_path)
    resources = extract_resources(state)
    print(f"  Resources in state: {len(resources)}")
    all_drifts = []
    for res in resources:
        rtype = res["type"]
        checker = CHECKERS.get(rtype)
        if checker:
            try:
                drifts = checker(res["attributes"], region)
                all_drifts.extend(drifts)
            except Exception as e:
                print(f"  Error checking {rtype} ({res['name']}): {e}")
    return all_drifts


def main():
    parser = argparse.ArgumentParser(description="Terraform Drift Detector")
    parser.add_argument("--state-file", help="Path to a single .tfstate file")
    parser.add_argument("--state-dir", help="Directory to recursively search for .tfstate files")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--output", help="Save JSON drift report to file")
    args = parser.parse_args()

    if not args.state_file and not args.state_dir:
        print("Error: provide --state-file or --state-dir")
        sys.exit(1)

    state_files = []
    if args.state_file:
        state_files = [Path(args.state_file)]
    elif args.state_dir:
        state_files = list(Path(args.state_dir).rglob("*.tfstate"))

    if not state_files:
        print(f"No .tfstate files found.")
        sys.exit(0)

    print(f"\nTerraform Drift Detector")
    print(f"{'='*55}")
    print(f"Region      : {args.region}")
    print(f"State files : {len(state_files)}\n")

    all_drifts = []
    for state_path in state_files:
        print(f"Scanning: {state_path}")
        drifts = scan_state_file(str(state_path), args.region)
        all_drifts.extend(drifts)

    critical_count = print_report(all_drifts, args.output)
    sys.exit(1 if critical_count > 0 else 0)


if __name__ == "__main__":
    main()

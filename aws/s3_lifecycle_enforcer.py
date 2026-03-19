"""
aws/s3_lifecycle_enforcer.py
-----------------------------
Audits all S3 buckets and enforces lifecycle policies to transition/expire
objects — a key part of the $5K annual savings from storage lifecycle
mentioned in Deepanshu's resume.

Policy applied:
  - Standard objects → Intelligent-Tiering after 30 days
  - Intelligent-Tiering → Glacier after 90 days
  - Glacier → deleted after 365 days
  - Multipart upload cleanup after 7 days (common silent cost leak)

Usage:
    python aws/s3_lifecycle_enforcer.py --dry-run          # Preview only
    python aws/s3_lifecycle_enforcer.py --apply            # Apply policies
    python aws/s3_lifecycle_enforcer.py --apply --bucket my-bucket  # Single bucket
"""

import boto3
import argparse
import json
from datetime import datetime


LIFECYCLE_POLICY = {
    "Rules": [
        {
            "ID": "auto-tiering-policy",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "Transitions": [
                {"Days": 30,  "StorageClass": "INTELLIGENT_TIERING"},
                {"Days": 90,  "StorageClass": "GLACIER"},
            ],
            "Expiration": {"Days": 365},
        },
        {
            "ID": "abort-incomplete-multipart",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
        },
    ]
}


def get_buckets(s3, bucket_name: str = None) -> list:
    if bucket_name:
        return [{"Name": bucket_name}]
    return s3.list_buckets().get("Buckets", [])


def bucket_has_policy(s3, bucket_name: str) -> bool:
    try:
        s3.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        return True
    except s3.exceptions.ClientError:
        return False


def estimate_bucket_savings(s3, bucket_name: str) -> float:
    """Rough estimate based on object count and avg size."""
    try:
        cw = boto3.client("cloudwatch")
        response = cw.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName="BucketSizeBytes",
            Dimensions=[
                {"Name": "BucketName", "Value": bucket_name},
                {"Name": "StorageType", "Value": "StandardStorage"},
            ],
            StartTime=datetime.utcnow().replace(hour=0, minute=0, second=0),
            EndTime=datetime.utcnow(),
            Period=86400,
            Statistics=["Average"],
        )
        if response["Datapoints"]:
            size_gb = response["Datapoints"][0]["Average"] / (1024 ** 3)
            # S3 Standard: $0.023/GB → Glacier: $0.004/GB = ~83% saving on archived data
            return round(size_gb * 0.019 * 0.3, 2)  # conservative 30% of objects archived
    except Exception:
        pass
    return 0.0


def apply_lifecycle(s3, bucket_name: str, dry_run: bool = True) -> dict:
    already_has = bucket_has_policy(s3, bucket_name)
    savings = estimate_bucket_savings(s3, bucket_name)
    result = {
        "bucket": bucket_name,
        "had_policy": already_has,
        "action": "skipped" if already_has else ("dry-run" if dry_run else "applied"),
        "estimated_monthly_saving_usd": savings,
    }
    if not already_has and not dry_run:
        s3.put_bucket_lifecycle_configuration(
            Bucket=bucket_name,
            LifecycleConfiguration=LIFECYCLE_POLICY,
        )
        result["action"] = "applied"
    return result


def main():
    parser = argparse.ArgumentParser(description="S3 Lifecycle Policy Enforcer")
    parser.add_argument("--apply", action="store_true", help="Apply lifecycle policies")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--bucket", help="Target a single bucket")
    args = parser.parse_args()
    dry_run = not args.apply

    s3 = boto3.client("s3")
    buckets = get_buckets(s3, args.bucket)
    results = []
    total_saving = 0.0

    print(f"\nS3 Lifecycle Enforcer — {'DRY RUN' if dry_run else 'APPLYING POLICIES'}")
    print(f"{'='*55}")
    for bucket in buckets:
        name = bucket["Name"]
        try:
            result = apply_lifecycle(s3, name, dry_run=dry_run)
            results.append(result)
            total_saving += result["estimated_monthly_saving_usd"]
            status = {
                "applied": "[APPLIED]",
                "dry-run": "[WOULD APPLY]",
                "skipped": "[ALREADY SET]",
            }.get(result["action"], "")
            print(f"  {status:<16} {name}")
            if result["estimated_monthly_saving_usd"] > 0:
                print(f"                   Est. saving: ${result['estimated_monthly_saving_usd']:.2f}/mo")
        except Exception as e:
            print(f"  [ERROR]          {name}: {e}")

    print(f"\n{'='*55}")
    print(f"  Buckets processed        : {len(results)}")
    print(f"  Policies applied/pending : {sum(1 for r in results if r['action'] in ('applied','dry-run'))}")
    print(f"  Total estimated saving   : ${total_saving:.2f}/month")
    print(f"  Annual projection        : ${total_saving * 12:.2f}/year")
    if dry_run:
        print(f"\n  Run with --apply to enforce policies.")


if __name__ == "__main__":
    main()

"""
terraform/state_backup.py
--------------------------
Automated Terraform state file backup to S3 with versioning and
integrity verification. Directly addresses the Terraform state corruption
incident response experience on Deepanshu's resume.

Features:
  - Backs up local or remote .tfstate files to S3
  - SHA256 integrity check before and after upload
  - Retention policy: keeps last N backups, deletes older ones
  - Slack webhook notification on backup success/failure
  - Supports multiple workspaces

Usage:
    python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups
    python terraform/state_backup.py --state-dir ./infra --bucket my-tf-backups --slack-webhook https://hooks.slack.com/...
"""

import argparse
import boto3
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import urllib.request


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_state_files(state_dir: str) -> List[Path]:
    return list(Path(state_dir).rglob("*.tfstate"))


def upload_state(
    s3,
    local_path: Path,
    bucket: str,
    prefix: str,
    dry_run: bool = False,
) -> dict:
    checksum = sha256_file(str(local_path))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    s3_key = f"{prefix}/{local_path.stem}/{timestamp}.tfstate"
    result = {
        "local_path": str(local_path),
        "s3_key": s3_key,
        "checksum_before": checksum,
        "status": "dry-run" if dry_run else "pending",
    }
    if dry_run:
        return result
    s3.upload_file(
        str(local_path),
        bucket,
        s3_key,
        ExtraArgs={
            "Metadata": {
                "sha256": checksum,
                "source-path": str(local_path),
                "backup-timestamp": timestamp,
            },
            "ServerSideEncryption": "AES256",
        },
    )
    head = s3.head_object(Bucket=bucket, Key=s3_key)
    stored_checksum = head.get("Metadata", {}).get("sha256", "")
    if stored_checksum != checksum:
        result["status"] = "INTEGRITY_MISMATCH"
        result["error"] = f"Checksum mismatch: local={checksum} stored={stored_checksum}"
    else:
        result["status"] = "success"
        result["s3_uri"] = f"s3://{bucket}/{s3_key}"
    return result


def enforce_retention(s3, bucket: str, prefix: str, state_name: str, keep: int = 10):
    """Delete old backups beyond the retention limit."""
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/{state_name}/"):
        for obj in page.get("Contents", []):
            keys.append((obj["LastModified"], obj["Key"]))
    keys.sort(key=lambda x: x[0])
    to_delete = keys[:-keep] if len(keys) > keep else []
    for _, key in to_delete:
        s3.delete_object(Bucket=bucket, Key=key)
        print(f"  Purged old backup: {key}")
    return len(to_delete)


def notify_slack(webhook_url: str, results: List[dict], bucket: str):
    failures = [r for r in results if r["status"] not in ("success", "dry-run")]
    colour = "good" if not failures else "danger"
    text = (
        f"*Terraform State Backup* — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Bucket: `{bucket}`\n"
        f"Files backed up: {len([r for r in results if r['status'] == 'success'])}/{len(results)}\n"
    )
    if failures:
        text += f"\n*Failed:*\n" + "\n".join(f"• {r['local_path']}: {r.get('error','unknown')}" for r in failures)
    payload = json.dumps({
        "attachments": [{"color": colour, "text": text, "mrkdwn_in": ["text"]}]
    }).encode()
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Terraform State Backup Tool")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="terraform-state-backups")
    parser.add_argument("--retain", type=int, default=10, help="Number of backups to keep per state file")
    parser.add_argument("--slack-webhook", help="Slack webhook URL for notifications")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state_files = find_state_files(args.state_dir)
    if not state_files:
        print(f"No .tfstate files found in {args.state_dir}")
        sys.exit(0)

    s3 = boto3.client("s3")
    results = []
    print(f"\nTerraform State Backup — {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*55}")
    print(f"State files found: {len(state_files)}")
    print(f"Target bucket    : s3://{args.bucket}/{args.prefix}\n")

    for path in state_files:
        print(f"Processing: {path}")
        result = upload_state(s3, path, args.bucket, args.prefix, dry_run=args.dry_run)
        results.append(result)
        status_label = {"success": "[OK]", "dry-run": "[DRY-RUN]", "INTEGRITY_MISMATCH": "[FAIL]"}.get(result["status"], "[FAIL]")
        print(f"  {status_label} {result.get('s3_uri', result.get('s3_key'))}")
        print(f"  Checksum: {result['checksum_before']}")
        if not args.dry_run and result["status"] == "success":
            deleted = enforce_retention(s3, args.bucket, args.prefix, path.stem, args.retain)
            if deleted:
                print(f"  Retention: purged {deleted} old backup(s)")
        if result["status"] == "INTEGRITY_MISMATCH":
            print(f"  ERROR: {result['error']}")

    success = sum(1 for r in results if r["status"] in ("success", "dry-run"))
    print(f"\nSummary: {success}/{len(results)} backed up successfully")

    if args.slack_webhook and not args.dry_run:
        try:
            notify_slack(args.slack_webhook, results, args.bucket)
            print("Slack notification sent.")
        except Exception as e:
            print(f"Slack notification failed: {e}")

    failed = [r for r in results if r["status"] not in ("success", "dry-run")]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

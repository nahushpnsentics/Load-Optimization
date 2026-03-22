#!/usr/bin/env python3
"""Create MinIO bucket if missing. Run after docker compose up."""
import os
import sys

try:
    from minio import Minio
except ImportError:
    print("minio package not installed; skip init (pip install minio)", file=sys.stderr)
    sys.exit(0)

endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
access = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
secret = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
secure = os.environ.get("MINIO_SECURE", "false").lower() in ("1", "true", "yes")
bucket = os.environ.get("MINIO_BUCKET", "load-optimization")

try:
    c = Minio(endpoint, access_key=access, secret_key=secret, secure=secure)
    if not c.bucket_exists(bucket):
        c.make_bucket(bucket)
        print(f"Created bucket: {bucket}")
    else:
        print(f"Bucket exists: {bucket}")
except Exception as e:
    print(f"MinIO init skipped or failed: {e}", file=sys.stderr)
    sys.exit(0)

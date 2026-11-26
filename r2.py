"""Cloudflare R2 media hosting (replaces the public stoic-media GitHub Pages repo).

Instagram's Graph API needs a public URL for the file; we upload it to R2 right before it is posted and
let an R2 lifecycle rule delete it after 7 days. Bucket name, account id and the public r2.dev base are
NOT secrets. The two keys (R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY) come from GitHub secrets and are
never printed.
"""
import mimetypes, os

ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "599c62021f15cc8002f56893f2c52d37")
BUCKET = os.environ.get("R2_BUCKET", "unshaken-media")
PUBLIC_BASE = os.environ.get("R2_PUBLIC_BASE", "https://pub-4d003ad861214aa3902e0d81371053cd.r2.dev").rstrip("/")


def public_url(name):
    return f"{PUBLIC_BASE}/{name}"


def _client():
    import boto3
    return boto3.client("s3", endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
                        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")


def ensure(path, client=None):
    """Make sure `path` is in the bucket (uploads when missing) and return its public URL."""
    name = os.path.basename(path)
    c = client or _client()
    try:
        c.head_object(Bucket=BUCKET, Key=name)
    except Exception:
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        c.upload_file(path, BUCKET, name, ExtraArgs={"ContentType": ctype})
    return public_url(name)

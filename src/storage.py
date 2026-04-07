"""
S3 uploader with automatic local-mode fallback.

The uploader is "enabled" only if all of the following hold:

1. `S3_BUCKET_NAME` is configured.
2. `boto3` can resolve credentials (env vars, AWS CLI profile, IAM role, etc.).
3. The configured bucket is reachable and the credentials are authorised
   to access it (verified by `head_bucket`).

If any of these fail, the uploader logs the reason and switches to local
mode: it never touches S3, but it still enforces the local retention
policy so the disk doesn't fill up.
"""

import logging
import glob
import os
import threading
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from src.config import Config

logger = logging.getLogger(__name__)


class S3Uploader:
    def __init__(self, bucket_name=None, region_name=None):
        self.bucket_name = bucket_name if bucket_name is not None else Config.S3_BUCKET_NAME
        region = region_name if region_name is not None else Config.S3_REGION
        self.enabled = False
        self.s3_client = None

        if not self.bucket_name or not self.bucket_name.strip():
            logger.info("S3 disabled: no bucket configured. Running in LOCAL MODE (storage only).")
            return

        try:
            self.s3_client = boto3.client("s3", region_name=region)
            # Verify creds + bucket access in one call. head_bucket is cheap
            # and returns 200 / 403 / 404 so we can give a precise error.
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except NoCredentialsError:
            logger.warning(
                "S3 disabled: bucket '%s' is configured but no AWS credentials "
                "could be resolved. Running in LOCAL MODE.",
                self.bucket_name,
            )
            self.s3_client = None
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.warning(
                "S3 disabled: head_bucket('%s') failed with %s. Running in LOCAL MODE.",
                self.bucket_name,
                code,
            )
            self.s3_client = None
            return
        except BotoCoreError as e:
            logger.warning(
                "S3 disabled: boto3 error during init (%s). Running in LOCAL MODE.", e
            )
            self.s3_client = None
            return

        self.enabled = True
        logger.info(f"S3 uploader initialised. Bucket: {self.bucket_name}")

    def upload_file(self, file_path, object_name=None):
        """
        Fire-and-forget upload. In LOCAL MODE this is a no-op except for
        retention enforcement.
        """
        if not self.enabled:
            self._cleanup_local_storage()
            return

        if object_name is None:
            object_name = os.path.basename(file_path)

        thread = threading.Thread(
            target=self._upload_worker, args=(file_path, object_name), daemon=True
        )
        thread.start()
        self._cleanup_local_storage()

    def _upload_worker(self, file_path, object_name):
        for attempt in range(1, Config.UPLOAD_MAX_RETRIES + 1):
            try:
                logger.info(f"Uploading {object_name} (attempt {attempt})")
                self.s3_client.upload_file(file_path, self.bucket_name, object_name)
                logger.info(f"Upload successful: {object_name}")
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Local file deleted: {file_path}")
                return
            except (BotoCoreError, ClientError, OSError) as e:
                logger.error(f"Upload failed for {object_name}: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff

        logger.error(
            f"Gave up uploading {object_name} after {Config.UPLOAD_MAX_RETRIES} retries. "
            f"Keeping file locally."
        )

    def _cleanup_local_storage(self):
        """
        Enforce retention policy: keep at most RETENTION_COUNT mp4 files.
        Delete the oldest ones first. Runs in both local and S3 modes.
        """
        try:
            files = sorted(
                glob.glob(os.path.join(Config.RECORDINGS_DIR, "*.mp4")),
                key=os.path.getmtime,
            )
            excess = len(files) - Config.RETENTION_COUNT
            if excess <= 0:
                return
            for f in files[:excess]:
                try:
                    os.remove(f)
                    logger.warning(f"Cleanup: deleted old file: {f}")
                except OSError as e:
                    logger.error(f"Error deleting {f}: {e}")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

import boto3
import os
import threading
import time
import logging
import glob
from src.config import Config

logger = logging.getLogger(__name__)

class S3Uploader:
    def __init__(self, bucket_name, region_name=Config.S3_REGION):
        self.bucket_name = bucket_name
        self.enabled = bool(bucket_name and bucket_name.strip())
        
        if self.enabled:
            try:
                self.s3_client = boto3.client('s3', region_name=region_name)
                logger.info(f"S3 Uploader Initialized. Bucket: {self.bucket_name}")
            except Exception as e:
                logger.error(f"Failed to initialize Boto3 client: {e}")
                self.enabled = False
        else:
            logger.info("No S3 Bucket configured. Running in Local Mode (Storage Only).")

    def upload_file(self, file_path, object_name=None):
        if not self.enabled:
            # In Local Mode, we just trigger cleanup
            self._cleanup_local_storage()
            return

        if object_name is None:
            object_name = os.path.basename(file_path)

        thread = threading.Thread(target=self._upload_worker, args=(file_path, object_name))
        thread.start()
        
        # Trigger cleanup asynchronously too
        self._cleanup_local_storage()

    def _upload_worker(self, file_path, object_name):
        retries = 0
        while retries < Config.UPLOAD_MAX_RETRIES:
            try:
                logger.info(f"Starting upload: {object_name} (Attempt {retries+1})")
                self.s3_client.upload_file(file_path, self.bucket_name, object_name)
                logger.info(f"Upload successful: {object_name}")
                
                # Delete local
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Local file deleted: {file_path}")
                return
            except Exception as e:
                logger.error(f"Upload failed: {e}")
                retries += 1
                time.sleep(2 ** retries) # Exponential backoff
        
        logger.error(f"Give up uploading {object_name} after {Config.UPLOAD_MAX_RETRIES} retries. Keeping file locally.")

    def _cleanup_local_storage(self):
        """
        Enforce retention policy. 
        If more than RETENTION_COUNT mp4 files, delete oldest.
        """
        try:
            files = sorted(glob.glob(os.path.join(Config.RECORDINGS_DIR, "*.mp4")), key=os.path.getmtime)
            
            if len(files) > Config.RETENTION_COUNT:
                # Delete oldest
                to_delete = files[:len(files) - Config.RETENTION_COUNT]
                for f in to_delete:
                    try:
                        os.remove(f)
                        logger.warning(f"Cleanup: Deleted old file to free space: {f}")
                    except OSError as e:
                        logger.error(f"Error deleting {f}: {e}")
        except Exception as e:
            logger.error(f"Cleanup Error: {e}")

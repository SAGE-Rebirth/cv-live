import time
import os
import logging
import shutil
import glob
from src.storage import S3Uploader
from src.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [WATCHER] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class UploadWatcher:
    def __init__(self):
        self.uploader = S3Uploader(bucket_name=Config.S3_BUCKET_NAME)
        self.pending_dir = Config.RECORDINGS_DIR
        self.quarantine_dir = os.path.join(self.pending_dir, "quarantine")
        
        if not os.path.exists(self.pending_dir):
            os.makedirs(self.pending_dir)
        if not os.path.exists(self.quarantine_dir):
            os.makedirs(self.quarantine_dir)
            
        # Track attempts
        self.attempts = {}

    def run(self):
        logger.info(f"Upload Watcher Service Started. Monitoring: {self.pending_dir}")
        while True:
            try:
                self._check_and_upload()
            except KeyboardInterrupt:
                logger.info("Stopping Watcher...")
                break
            except Exception as e:
                logger.error(f"Watcher Loop Error: {e}")
            
            time.sleep(10)

    def _check_and_upload(self):
        files = glob.glob(os.path.join(self.pending_dir, "*.mp4"))
        if not files:
            return

        for file_path in files:
            # Skip if in quarantine already (glob doesn't recurse by default but just safe)
            if "quarantine" in file_path:
                continue

            if self._is_file_ready(file_path):
                logger.info(f"Processing: {file_path}")
                
                # Try Upload
                uploaded = self._try_upload_blocking(file_path)
                
                if not uploaded:
                    # Increment failure count
                    count = self.attempts.get(file_path, 0) + 1
                    self.attempts[file_path] = count
                    
                    if count >= 3:
                        logger.error(f"File failed 3 times. Quarantining: {file_path}")
                        self._quarantine_file(file_path)
                        del self.attempts[file_path]
                else:
                    # Success
                    if file_path in self.attempts:
                        del self.attempts[file_path]

    def _try_upload_blocking(self, file_path):
        try:
            # We use the blocking worker logic from uploader
            # But S3Uploader._upload_worker deletes on success.
            # We need to verify if it throws.
            # S3Uploader catches exception and prints error.
            # We should modify S3Uploader or just assume if file is gone, it worked?
            # Or if file is still there, it failed.
            
            # Actually, _upload_worker implements retries internally too.
            # If it fails Config.UPLOAD_MAX_RETRIES times, it logs error and KEEPS file.
            # So if file exists after call, it failed.
            
            self.uploader._upload_worker(file_path, os.path.basename(file_path))
            
            if os.path.exists(file_path):
                return False
            return True
            
        except Exception as e:
            logger.error(f"Upload Error: {e}")
            return False

    def _quarantine_file(self, file_path):
        try:
            shutil.move(file_path, os.path.join(self.quarantine_dir, os.path.basename(file_path)))
        except OSError as e:
            logger.error(f"Failed to quarantine: {e}")

    def _is_file_ready(self, file_path):
        try:
            mtime = os.path.getmtime(file_path)
            if time.time() - mtime > 5: # Reduced to 5s
                if os.path.getsize(file_path) > 0:
                    return True
        except OSError:
            pass
        return False

if __name__ == "__main__":
    watcher = UploadWatcher()
    watcher.run()

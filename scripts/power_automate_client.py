"""
HKTW Meta Auto Report - Power Automate Client
Handles SharePoint file upload and download via Power Automate HTTP flows.
"""
import os
import sys
import time
import base64
import logging
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import PA_UPLOAD_URL, PA_DOWNLOAD_URL

logger = logging.getLogger(__name__)
TIMEOUT = 120

UPLOAD_RETRYABLE    = (429, 500, 502, 503, 504)
UPLOAD_MAX_RETRIES  = 3
UPLOAD_RETRY_DELAYS = (10, 30, 60)

DOWNLOAD_RETRYABLE    = (429, 500, 502, 503, 504)
DOWNLOAD_MAX_RETRIES  = 3
DOWNLOAD_RETRY_DELAYS = (10, 30, 60)


class PowerAutomateClient:

    def __init__(self):
        self.upload_url   = PA_UPLOAD_URL
        self.download_url = PA_DOWNLOAD_URL

    # ── Upload ────────────────────────────────────────────────────────────────

    def _post_with_retry(self, payload: dict, label: str) -> bool:
        """POST to PA upload URL with retry on transient errors."""
        for attempt in range(1, UPLOAD_MAX_RETRIES + 1):
            try:
                resp = requests.post(self.upload_url, json=payload, timeout=TIMEOUT)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Upload request error (attempt {attempt}/{UPLOAD_MAX_RETRIES}): {e}")
                if attempt < UPLOAD_MAX_RETRIES:
                    time.sleep(UPLOAD_RETRY_DELAYS[attempt - 1])
                    continue
                raise
            if resp.status_code in (200, 201, 202):
                logger.info(f"Upload success: {label}")
                return True
            if resp.status_code in UPLOAD_RETRYABLE and attempt < UPLOAD_MAX_RETRIES:
                logger.warning(
                    f"Upload got {resp.status_code} (attempt {attempt}/{UPLOAD_MAX_RETRIES}) "
                    f"— retrying in {UPLOAD_RETRY_DELAYS[attempt - 1]}s..."
                )
                time.sleep(UPLOAD_RETRY_DELAYS[attempt - 1])
                continue
            logger.error(f"Upload failed [{resp.status_code}]: {resp.text[:500]}")
            resp.raise_for_status()
        raise RuntimeError(f"Upload failed after {UPLOAD_MAX_RETRIES} attempts: {label}")

    def upload_file(self, local_path: str, sp_folder: str, sp_filename: str | None = None) -> bool:
        if not self.upload_url:
            raise EnvironmentError("PA_UPLOAD_URL not set")
        filename = sp_filename or os.path.basename(local_path)
        with open(local_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {"fileName": filename, "fileContent": content_b64, "folderPath": sp_folder}
        logger.info(f"Uploading '{filename}' → {sp_folder}")
        return self._post_with_retry(payload, filename)

    def upload_bytes(self, data: bytes, sp_folder: str, sp_filename: str) -> bool:
        if not self.upload_url:
            raise EnvironmentError("PA_UPLOAD_URL not set")
        content_b64 = base64.b64encode(data).decode("utf-8")
        payload = {"fileName": sp_filename, "fileContent": content_b64, "folderPath": sp_folder}
        logger.info(f"Uploading bytes '{sp_filename}' → {sp_folder}")
        return self._post_with_retry(payload, sp_filename)

    # ── Download ──────────────────────────────────────────────────────────────

    def download_file(self, sp_folder: str, sp_filename: str, local_path: str) -> bool:
        data = self.download_bytes(sp_folder, sp_filename)
        if data is None:
            return False
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        logger.info(f"Downloaded → {local_path} ({len(data):,} bytes)")
        return True

    def download_bytes(self, sp_folder: str, sp_filename: str) -> bytes | None:
        if not self.download_url:
            raise EnvironmentError("PA_DOWNLOAD_URL not set")
        payload = {"fileName": sp_filename, "folderPath": sp_folder}

        for attempt in range(1, DOWNLOAD_MAX_RETRIES + 1):
            try:
                resp = requests.post(self.download_url, json=payload, timeout=TIMEOUT)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Download request error (attempt {attempt}/{DOWNLOAD_MAX_RETRIES}): {e}")
                if attempt < DOWNLOAD_MAX_RETRIES:
                    time.sleep(DOWNLOAD_RETRY_DELAYS[attempt - 1])
                    continue
                return None

            if resp.status_code == 404:
                logger.warning(f"download_bytes: file not found on SharePoint: {sp_filename}")
                return None

            if resp.status_code in DOWNLOAD_RETRYABLE and attempt < DOWNLOAD_MAX_RETRIES:
                logger.warning(
                    f"download_bytes: HTTP {resp.status_code} for '{sp_filename}' "
                    f"(attempt {attempt}/{DOWNLOAD_MAX_RETRIES}) "
                    f"— retrying in {DOWNLOAD_RETRY_DELAYS[attempt - 1]}s..."
                )
                time.sleep(DOWNLOAD_RETRY_DELAYS[attempt - 1])
                continue

            if resp.status_code not in (200, 201):
                logger.warning(
                    f"download_bytes: HTTP {resp.status_code} for '{sp_filename}' — treating as not found"
                )
                return None

            try:
                body = resp.json()
            except Exception:
                logger.warning(f"download_bytes: non-JSON response for '{sp_filename}'")
                return None

            if not body.get("success"):
                logger.warning(f"download_bytes: response indicates failure for '{sp_filename}': {body}")
                return None

            return base64.b64decode(body["content"])

        logger.warning(f"download_bytes: all retries exhausted for '{sp_filename}' — treating as not found")
        return None

"""
HKTW Meta Auto Report - Power Automate Client
Handles SharePoint file upload and download via Power Automate HTTP flows.
"""
import os
import sys
import base64
import logging
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import PA_UPLOAD_URL, PA_DOWNLOAD_URL

logger = logging.getLogger(__name__)
TIMEOUT = 120


class PowerAutomateClient:

    def __init__(self):
        self.upload_url   = PA_UPLOAD_URL
        self.download_url = PA_DOWNLOAD_URL

    def upload_file(self, local_path: str, sp_folder: str, sp_filename: str | None = None) -> bool:
        if not self.upload_url:
            raise EnvironmentError("PA_UPLOAD_URL not set")
        filename = sp_filename or os.path.basename(local_path)
        with open(local_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {"fileName": filename, "fileContent": content_b64, "folderPath": sp_folder}
        logger.info(f"Uploading '{filename}' → {sp_folder}")
        resp = requests.post(self.upload_url, json=payload, timeout=TIMEOUT)
        if resp.status_code in (200, 201, 202):
            logger.info(f"Upload success: {filename}")
            return True
        logger.error(f"Upload failed [{resp.status_code}]: {resp.text[:500]}")
        resp.raise_for_status()

    def upload_bytes(self, data: bytes, sp_folder: str, sp_filename: str) -> bool:
        if not self.upload_url:
            raise EnvironmentError("PA_UPLOAD_URL not set")
        content_b64 = base64.b64encode(data).decode("utf-8")
        payload = {"fileName": sp_filename, "fileContent": content_b64, "folderPath": sp_folder}
        logger.info(f"Uploading bytes '{sp_filename}' → {sp_folder}")
        resp = requests.post(self.upload_url, json=payload, timeout=TIMEOUT)
        if resp.status_code in (200, 201, 202):
            logger.info(f"Upload success: {sp_filename}")
            return True
        logger.error(f"Upload failed [{resp.status_code}]: {resp.text[:500]}")
        resp.raise_for_status()

    def download_file(self, sp_folder: str, sp_filename: str, local_path: str) -> bool:
        if not self.download_url:
            raise EnvironmentError("PA_DOWNLOAD_URL not set")
        payload = {"fileName": sp_filename, "folderPath": sp_folder}
        logger.info(f"Downloading '{sp_filename}' from {sp_folder}")
        resp = requests.post(self.download_url, json=payload, timeout=TIMEOUT)
        if resp.status_code == 404:
            logger.warning(f"File not found on SharePoint: {sp_filename}")
            return False
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success"):
            logger.error(f"Download response indicates failure: {body}")
            return False
        content = base64.b64decode(body["content"])
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(content)
        logger.info(f"Downloaded → {local_path} ({len(content):,} bytes)")
        return True

    def download_bytes(self, sp_folder: str, sp_filename: str) -> bytes | None:
        if not self.download_url:
            raise EnvironmentError("PA_DOWNLOAD_URL not set")
        payload = {"fileName": sp_filename, "folderPath": sp_folder}
        resp = requests.post(self.download_url, json=payload, timeout=TIMEOUT)
        if resp.status_code in (404, 502, 503, 504):
            logger.warning(f"download_bytes: HTTP {resp.status_code} for {sp_filename} — treating as not found")
            return None
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success"):
            return None
        return base64.b64decode(body["content"])

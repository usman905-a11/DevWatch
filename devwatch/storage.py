import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from devwatch.config import Config

logger = logging.getLogger("devwatch.storage")

VALID_REPORT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


class ReportStorage:
    """Disk-backed persistent storage for review reports within workspace sandbox."""

    def __init__(self, storage_dir: Optional[str] = None):
        if not storage_dir:
            base_dir = Path(Config.WORKSPACE_BASE_DIR).resolve()
            self.storage_dir = (base_dir / ".devwatch" / "reports").resolve()
        else:
            self.storage_dir = Path(storage_dir).resolve()
            
        os.makedirs(self.storage_dir, exist_ok=True)

    def _get_file_path(self, report_id: str) -> Path:
        if not report_id or not VALID_REPORT_ID_PATTERN.match(report_id):
            raise ValueError(f"Invalid report ID format: '{report_id}'")

        target_file = (self.storage_dir / f"{report_id}.json").resolve()
        
        try:
            if not target_file.is_relative_to(self.storage_dir):
                raise ValueError("Path traversal attempt blocked in report storage")
        except AttributeError:
            try:
                target_file.relative_to(self.storage_dir)
            except ValueError:
                raise ValueError("Path traversal attempt blocked in report storage")

        return target_file

    def save_report(self, report_id: str, report_data: Dict[str, Any]) -> bool:
        try:
            file_path = self._get_file_path(report_id)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save report to disk: {e}")
            return False

    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        try:
            file_path = self._get_file_path(report_id)
            if not file_path.exists() or not file_path.is_file():
                return None
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read report from disk: {e}")
            return None

    def list_reports(self) -> Dict[str, Dict[str, Any]]:
        reports = {}
        if not self.storage_dir.exists():
            return reports
        for fname in os.listdir(self.storage_dir):
            if fname.endswith(".json"):
                report_id = fname[:-5]
                if VALID_REPORT_ID_PATTERN.match(report_id):
                    data = self.get_report(report_id)
                    if data:
                        reports[report_id] = data
        return reports

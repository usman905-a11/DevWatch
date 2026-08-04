import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("devwatch.storage")


class ReportStorage:
    """Disk-backed persistent storage for review reports."""

    def __init__(self, storage_dir: Optional[str] = None):
        if not storage_dir:
            storage_dir = os.path.join(os.getcwd(), ".devwatch", "reports")
        self.storage_dir = os.path.abspath(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)

    def _get_file_path(self, report_id: str) -> str:
        safe_id = "".join(c for c in report_id if c.isalnum() or c in ("-", "_"))
        return os.path.join(self.storage_dir, f"{safe_id}.json")

    def save_report(self, report_id: str, report_data: Dict[str, Any]) -> bool:
        try:
            file_path = self._get_file_path(report_id)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save report '{report_id}' to disk: {e}")
            return False

    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        file_path = self._get_file_path(report_id)
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read report '{report_id}' from disk: {e}")
            return None

    def list_reports(self) -> Dict[str, Dict[str, Any]]:
        reports = {}
        if not os.path.exists(self.storage_dir):
            return reports
        for fname in os.listdir(self.storage_dir):
            if fname.endswith(".json"):
                report_id = fname[:-5]
                data = self.get_report(report_id)
                if data:
                    reports[report_id] = data
        return reports

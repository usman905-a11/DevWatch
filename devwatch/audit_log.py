import logging
import json
import time
from typing import Optional, Dict, Any

audit_logger = logging.getLogger("devwatch.audit")
audit_logger.setLevel(logging.INFO)


def _log_event(event_type: str, severity: str, details: Dict[str, Any]) -> None:
    payload = {
        "timestamp": time.time(),
        "event_type": event_type,
        "severity": severity,
        "details": details,
    }
    audit_logger.info(f"AUDIT_EVENT | {json.dumps(payload)}")


def log_auth_failure(endpoint: str, client_ip: str, reason: str) -> None:
    _log_event(
        event_type="AUTH_FAILURE",
        severity="HIGH",
        details={"endpoint": endpoint, "client_ip": client_ip, "reason": reason},
    )


def log_authz_failure(endpoint: str, client_identity: str, resource: str, reason: str) -> None:
    _log_event(
        event_type="AUTHORIZATION_FAILURE",
        severity="HIGH",
        details={
            "endpoint": endpoint,
            "client_identity": client_identity,
            "resource": resource,
            "reason": reason,
        },
    )


def log_review_created(report_id: str, target_path: str, client_identity: str) -> None:
    _log_event(
        event_type="REVIEW_CREATED",
        severity="INFO",
        details={
            "report_id": report_id,
            "target_path": target_path,
            "client_identity": client_identity,
        },
    )


def log_review_cancelled(report_id: str, client_identity: str, reason: str) -> None:
    _log_event(
        event_type="REVIEW_CANCELLED",
        severity="INFO",
        details={
            "report_id": report_id,
            "client_identity": client_identity,
            "reason": reason,
        },
    )


def log_fix_applied(file_path: str, line_number: int, client_identity: str) -> None:
    _log_event(
        event_type="FIX_APPLIED",
        severity="MEDIUM",
        details={
            "file_path": file_path,
            "line_number": line_number,
            "client_identity": client_identity,
        },
    )


def log_rate_limit_exceeded(endpoint: str, client_identity: str) -> None:
    _log_event(
        event_type="RATE_LIMIT_EXCEEDED",
        severity="WARNING",
        details={"endpoint": endpoint, "client_identity": client_identity},
    )

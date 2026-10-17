import uuid
import time
from typing import List
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from devwatch.config import Config
from devwatch.models import ReviewReport, AgentStepUpdate
from devwatch.auth import verify_api_key, verify_report_access
from devwatch.storage import ReportStorage
from devwatch.operations import ReviewOperations
from devwatch.pipeline.dag import ReviewPipeline  # Backward-compatible patch seam.

review_router = APIRouter(prefix="/api", tags=["review"])
report_storage = ReportStorage()
review_ops = ReviewOperations()


def create_report_record(
    report_id: str, report: ReviewReport, target_path: str,
    owner: str, steps: List[AgentStepUpdate],
) -> dict:
    report_dict = report.model_dump()
    report_dict.update(
        total_issues=report.total_issues,
        critical_count=report.critical_count,
        high_count=report.high_count,
        medium_count=report.medium_count,
        low_count=report.low_count,
    )
    return {
        "report_id": report_id,
        "owner": owner,
        "target_path": target_path,
        "status": "completed",
        "timestamp": time.time(),
        "steps": [step.model_dump() for step in steps],
        "report": report_dict,
        "summary_markdown": report.summary,
    }


class ReviewRequest(BaseModel):
    target_path: str = "."


class SingleFileAuditRequest(BaseModel):
    file_path: str
    content: str


class MultiFileAuditRequest(BaseModel):
    files: List[SingleFileAuditRequest]



@review_router.post("/review/files", dependencies=[Depends(verify_api_key)])
async def trigger_files_audit(
    request_obj: Request,
    request: MultiFileAuditRequest,
    client_identity: str = Depends(verify_api_key),
):
    """Audit uploaded files (in-memory batch review)."""
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    try:
        file_dicts = [{"file_path": f.file_path, "content": f.content} for f in request.files]
        report = await review_ops.audit_uploaded_files(
            file_dicts,
            client_identity=client_identity,
            client_ip=client_ip,
        )
        report_dict = report.model_dump()
        report_dict["total_issues"] = report.total_issues
        return {"status": "completed", "report": report_dict}
    except Exception as e:
        if "429" in str(e) or "Rate limit" in str(e):
            raise HTTPException(status_code=429, detail=str(e))
        raise HTTPException(status_code=500, detail=f"Files audit failed: {str(e)}")


@review_router.post("/review/file", dependencies=[Depends(verify_api_key)])
async def trigger_file_audit(
    request_obj: Request,
    request: SingleFileAuditRequest,
    client_identity: str = Depends(verify_api_key),
):
    """Audit a single file (in-memory review)."""
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    try:
        report = await review_ops.audit_single_file(
            file_path=request.file_path,
            content=request.content,
            client_identity=client_identity,
            client_ip=client_ip,
        )
        report_dict = report.model_dump()
        report_dict["total_issues"] = report.total_issues
        return {"status": "completed", "report": report_dict}
    except Exception as e:
        if "429" in str(e) or "Rate limit" in str(e):
            raise HTTPException(status_code=429, detail=str(e))
        raise HTTPException(status_code=500, detail=f"File audit failed: {str(e)}")


@review_router.post("/review", dependencies=[Depends(verify_api_key)])
async def trigger_review(
    request_obj: Request,
    request: ReviewRequest,
    client_identity: str = Depends(verify_api_key),
):
    """Audit a repository (directory scan + full review pipeline)."""
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    report_id = str(uuid.uuid4())
    steps: List[AgentStepUpdate] = []

    def on_step(update: AgentStepUpdate):
        update.timestamp = time.time()
        steps.append(update)

    try:
        # Execute audit through operations module
        report = await review_ops.audit_repository(
            target_path=request.target_path,
            client_identity=client_identity,
            client_ip=client_ip,
            step_callback=on_step,
        )

        report_data = create_report_record(
            report_id, report, request.target_path, client_identity, steps
        )
        if not report_storage.save_report(report_id, report_data):
            raise RuntimeError("Report could not be saved")
        return report_data
    except ValueError as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e))
    except Exception as e:
        if "429" in str(e) or "Rate limit" in str(e):
            raise HTTPException(status_code=429, detail=str(e))
        raise HTTPException(status_code=500, detail=f"Review failed: {str(e)}")


@review_router.post("/review/propose-fix", dependencies=[Depends(verify_api_key)])
def propose_remediation_fix(
    request_obj: Request,
    client_identity: str = Depends(verify_api_key),
):
    """Retained for discovery while DevWatch operates in report-only mode."""
    raise HTTPException(
        status_code=410,
        detail="DevWatch is report-only; remediation proposal endpoints are disabled.",
    )


@review_router.post("/review/apply-proposal", dependencies=[Depends(verify_api_key)])
def apply_remediation_proposal(
    request_obj: Request,
    client_identity: str = Depends(verify_api_key),
):
    """Retained for discovery while DevWatch operates in report-only mode."""
    raise HTTPException(
        status_code=410,
        detail="DevWatch is report-only; remediation application endpoints are disabled.",
    )


@review_router.post("/review/apply-fix", dependencies=[Depends(verify_api_key)])
async def apply_quick_fix(
    request_obj: Request,
    client_identity: str = Depends(verify_api_key),
):
    """Retained for discovery while DevWatch operates in report-only mode."""
    raise HTTPException(
        status_code=410,
        detail="DevWatch is report-only; quick-fix endpoints are disabled.",
    )


@review_router.get("/reports/{report_id}", dependencies=[Depends(verify_api_key)])
def get_report(report_id: str, client_identity: str = Depends(verify_api_key)):
    report_data = report_storage.get_report(report_id)
    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found")
    
    verify_report_access(report_data, client_identity)
    return report_data

import uuid
import time
from typing import List
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from devwatch.config import Config
from devwatch.models import ReviewReport, AgentStepUpdate, RemediationProposal
from devwatch.auth import verify_api_key, verify_report_access
from devwatch.storage import ReportStorage
from devwatch.operations import ReviewOperations

review_router = APIRouter(prefix="/api", tags=["review"])
report_storage = ReportStorage()
review_ops = ReviewOperations()


class ReviewRequest(BaseModel):
    target_path: str = "."


class SingleFileAuditRequest(BaseModel):
    file_path: str
    content: str


class MultiFileAuditRequest(BaseModel):
    files: List[SingleFileAuditRequest]


class ApplyFixRequest(BaseModel):
    root_path: str = "."
    file_path: str
    line_number: int = 1
    target_snippet: str = ""
    replacement_code: str
    finding_id: str = "finding_1"


class ProposeFixRequest(BaseModel):
    root_path: str = "."
    file_path: str
    finding_id: str = "finding_1"
    start_line: int = 1
    end_line: int = 1
    target_snippet: str = ""
    replacement_code: str
    reason: str = "Code remediation proposal"


class ApplyProposalRequest(BaseModel):
    root_path: str = "."
    proposal: RemediationProposal


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

        # Prepare report data
        report_dict = report.model_dump()
        report_dict["total_issues"] = report.total_issues
        report_dict["critical_count"] = report.critical_count
        report_dict["high_count"] = report.high_count
        report_dict["medium_count"] = report.medium_count
        report_dict["low_count"] = report.low_count

        report_data = {
            "report_id": report_id,
            "owner": client_identity,
            "target_path": request.target_path,
            "status": "completed",
            "timestamp": time.time(),
            "steps": [s.model_dump() for s in steps],
            "report": report_dict,
            "summary_markdown": report.summary,
        }

        report_storage.save_report(report_id, report_data)
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
    request: ProposeFixRequest,
    client_identity: str = Depends(verify_api_key),
):
    """Propose a remediation fix (creates a proposal; does not apply)."""
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    try:
        proposal = review_ops.propose_remediation_fix(
            root_path=request.root_path,
            file_path=request.file_path,
            finding_id=request.finding_id,
            start_line=request.start_line,
            end_line=request.end_line,
            target_snippet=request.target_snippet,
            replacement_code=request.replacement_code,
            reason=request.reason,
            client_identity=client_identity,
            client_ip=client_ip,
        )
        return {"status": "success", "proposal": proposal.model_dump()}
    except (ValueError, FileNotFoundError) as err:
        status_code = 403 if "Access denied" in str(err) or "blocked" in str(err) else 400
        raise HTTPException(status_code=status_code, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to propose code fix: {str(err)}")


@review_router.post("/review/apply-proposal", dependencies=[Depends(verify_api_key)])
def apply_remediation_proposal(
    request_obj: Request,
    request: ApplyProposalRequest,
    client_identity: str = Depends(verify_api_key),
):
    """Apply a previously-proposed remediation fix."""
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    try:
        result = review_ops.apply_remediation_proposal(
            root_path=request.root_path,
            proposal=request.proposal,
            client_identity=client_identity,
            client_ip=client_ip,
        )
        return result
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to apply proposal: {str(err)}")


@review_router.post("/review/apply-fix", dependencies=[Depends(verify_api_key)])
async def apply_quick_fix(
    request_obj: Request,
    request: ApplyFixRequest,
    client_identity: str = Depends(verify_api_key),
):
    """Apply a quick fix to a file (no approval step)."""
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    try:
        result = await review_ops.apply_quick_fix(
            root_path=request.root_path,
            file_path=request.file_path,
            finding_id=request.finding_id,
            target_snippet=request.target_snippet,
            replacement_code=request.replacement_code,
            line_number=request.line_number,
            client_identity=client_identity,
            client_ip=client_ip,
        )
        return result
    except (ValueError, FileNotFoundError) as err:
        status_code = 403 if "Access denied" in str(err) or "blocked" in str(err) else 400
        raise HTTPException(status_code=status_code, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to apply code fix: {str(err)}")


@review_router.get("/reports/{report_id}", dependencies=[Depends(verify_api_key)])
def get_report(report_id: str, client_identity: str = Depends(verify_api_key)):
    report_data = report_storage.get_report(report_id)
    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found")
    
    verify_report_access(report_data, client_identity)
    return report_data

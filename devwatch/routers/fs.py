from fastapi import APIRouter, HTTPException, Query, Depends, Request
from pydantic import BaseModel

from devwatch.config import Config
from devwatch.scanner import CodebaseScanner
from devwatch.auth import verify_api_key
from devwatch.rate_limiter import rate_limiter

fs_router = APIRouter(prefix="/api/fs", tags=["filesystem"])


class WriteFileRequest(BaseModel):
    root_path: str = "."
    file_path: str
    content: str


@fs_router.get("/tree", dependencies=[Depends(verify_api_key)])
def get_fs_tree(request_obj: Request, root: str = Query(".", description="Root directory path")):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/fs/tree")

    try:
        scanner = CodebaseScanner(root)
        tree = scanner.get_tree_structure()
        files = scanner.get_files()
        return {"root": root, "tree": tree, "files": files}
    except ValueError as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e))


@fs_router.get("/read", dependencies=[Depends(verify_api_key)])
def read_file_content(
    request_obj: Request,
    path: str = Query(..., description="Relative file path"),
    root: str = Query(".", description="Root directory path"),
):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/fs/read")

    try:
        scanner = CodebaseScanner(root)
        content = scanner.read_file(path)
        return {"path": path, "content": content}
    except ValueError as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e))


@fs_router.post("/write", dependencies=[Depends(verify_api_key)])
def write_file_content(request_obj: Request, request: WriteFileRequest):
    client_ip = request_obj.client.host if request_obj.client else "unknown"
    rate_limiter.check_rate_limit(client_ip, Config.RATE_LIMIT_RPM, window_seconds=60, endpoint="/api/fs/write")

    try:
        scanner = CodebaseScanner(request.root_path)
        success = scanner.write_file(request.file_path, request.content)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to write file")
        return {"status": "success", "path": request.file_path}
    except ValueError as e:
        status_code = 403 if "Access denied" in str(e) or "blocked" in str(e) else 400
        raise HTTPException(status_code=status_code, detail=str(e))

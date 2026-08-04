import logging
from typing import Optional
from fastapi import Header, HTTPException, Request, WebSocket, status
from devwatch.config import Config
from devwatch.audit_log import log_auth_failure, log_authz_failure

logger = logging.getLogger("devwatch.auth")


def extract_api_key_from_headers(
    x_api_key: Optional[str] = None,
    authorization: Optional[str] = None,
) -> Optional[str]:
    """Extract API key from x-api-key header or Authorization: Bearer <key>."""
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization and authorization.strip():
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    return None


def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    authorization: Optional[str] = Header(None),
) -> str:
    """Centralized FastAPI dependency for REST API authentication."""
    endpoint = request.url.path
    client_ip = request.client.host if request.client else "unknown"
    provided_key = extract_api_key_from_headers(x_api_key, authorization)
    
    expected_key = Config.API_KEY
    env = Config.ENV

    if env == "production":
        if not expected_key:
            log_auth_failure(endpoint, client_ip, "Production environment missing API key configuration")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server configuration error: Production authentication misconfigured",
            )
        if not provided_key or provided_key != expected_key:
            log_auth_failure(endpoint, client_ip, "Invalid or missing API key in production mode")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return f"user:{provided_key[:8]}..."

    # Development Mode
    if expected_key:
        if not provided_key or provided_key != expected_key:
            log_auth_failure(endpoint, client_ip, "Invalid API key in development mode")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return f"user:{provided_key[:8]}..."
    
    # Development mode without explicit API key configured
    logger.warning(f"DEV_AUTH_BYPASS | Endpoint '{endpoint}' accessed without DEVWATCH_API_KEY in development mode")
    return "dev-user"


async def authenticate_ws_connection(websocket: WebSocket) -> str:
    """Validate WebSocket authentication via header or first handshake message."""
    # Check headers first (avoids putting long-lived secrets in URLs)
    x_api_key = websocket.headers.get("x-api-key")
    auth_header = websocket.headers.get("authorization")
    provided_key = extract_api_key_from_headers(x_api_key, auth_header)

    expected_key = Config.API_KEY
    env = Config.ENV

    if env == "production":
        if not expected_key or not provided_key or provided_key != expected_key:
            log_auth_failure("/ws/review", websocket.client.host if websocket.client else "unknown", "WebSocket auth failed in production")
            await websocket.close(code=4001, reason="Unauthorized: Invalid API key")
            raise HTTPException(status_code=401, detail="Unauthorized WebSocket")
        return f"ws-user:{provided_key[:8]}"

    if expected_key:
        if not provided_key or provided_key != expected_key:
            log_auth_failure("/ws/review", websocket.client.host if websocket.client else "unknown", "WebSocket auth failed in dev mode")
            await websocket.close(code=4001, reason="Unauthorized: Invalid API key")
            raise HTTPException(status_code=401, detail="Unauthorized WebSocket")
        return f"ws-user:{provided_key[:8]}"

    return "ws-dev-user"


def verify_report_access(report_data: dict, caller_identity: str) -> None:
    """Ensure caller is authorized to view target report."""
    report_owner = report_data.get("owner", "dev-user")
    if Config.ENV == "production" and report_owner != caller_identity:
        log_authz_failure(
            endpoint="/api/reports",
            client_identity=caller_identity,
            resource=report_data.get("report_id", "unknown"),
            reason=f"Caller '{caller_identity}' attempted to access report owned by '{report_owner}'",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You are not authorized to view this report",
        )

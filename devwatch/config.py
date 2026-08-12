import os
from enum import Enum
from typing import Optional


class ModelTier(Enum):
    FAST = "FAST"
    HEAVY = "HEAVY"


class Config:
    FAST_MODEL: str = "llama-3.1-8b-instant"
    HEAVY_MODEL: str = "llama-3.3-70b-versatile"


    # Environment & Security Configuration
    ENV: str = os.getenv("DEVWATCH_ENV", "development").lower()
    API_KEY: Optional[str] = os.getenv("DEVWATCH_API_KEY")

    # Rate Limiting & Concurrency Configuration
    RATE_LIMIT_RPM: int = int(os.getenv("DEVWATCH_RATE_LIMIT_RPM", "60"))
    RATE_LIMIT_REVIEWS_RPM: int = int(os.getenv("DEVWATCH_RATE_LIMIT_REVIEWS_RPM", "10"))
    MAX_WEBSOCKET_CONNECTIONS: int = int(os.getenv("DEVWATCH_MAX_WS_CONNECTIONS", "20"))
    MAX_CONCURRENT_LLM_CALLS: int = int(os.getenv("DEVWATCH_MAX_CONCURRENT_LLM", "10"))

    # Resilience & Circuit Breaker Configuration
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = int(os.getenv("DEVWATCH_CB_THRESHOLD", "15"))
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: float = float(os.getenv("DEVWATCH_CB_TIMEOUT", "60.0"))
    MAX_JOB_TOKEN_BUDGET: int = int(os.getenv("DEVWATCH_MAX_JOB_TOKENS", "250000"))
    GLOBAL_REVIEW_TIMEOUT_SECONDS: float = float(os.getenv("DEVWATCH_REVIEW_TIMEOUT", "120.0"))
    PROVIDER_CALL_TIMEOUT_SECONDS: float = float(os.getenv("DEVWATCH_PROVIDER_TIMEOUT", "30.0"))


    # Scalability & Resource Limits Configuration (Phase 11)
    MAX_FILES_PER_REVIEW: int = int(os.getenv("DEVWATCH_MAX_FILES_PER_REVIEW", "100"))
    MAX_BYTES_PER_FILE: int = int(os.getenv("DEVWATCH_MAX_BYTES_PER_FILE", "500000"))  # 500 KB
    MAX_LINES_PER_FILE: int = int(os.getenv("DEVWATCH_MAX_LINES_PER_FILE", "5000"))
    MAX_REPO_TOTAL_BYTES: int = int(os.getenv("DEVWATCH_MAX_REPO_TOTAL_BYTES", "10000000"))  # 10 MB
    MAX_FINDINGS_PER_FILE: int = int(os.getenv("DEVWATCH_MAX_FINDINGS_PER_FILE", "50"))
    MAX_FINDINGS_PER_JOB: int = int(os.getenv("DEVWATCH_MAX_FINDINGS_PER_JOB", "500"))
    MAX_CANDIDATE_FINDINGS: int = int(os.getenv("DEVWATCH_MAX_CANDIDATE_FINDINGS", "1000"))
    MAX_CONCURRENT_FILES: int = int(os.getenv("DEVWATCH_MAX_CONCURRENT_FILES", "5"))
    MAX_TOKENS_PER_JOB: int = int(os.getenv("DEVWATCH_MAX_TOKENS_PER_JOB", "200000"))
    MAX_TOKENS_PER_AGENT: int = int(os.getenv("DEVWATCH_MAX_TOKENS_PER_AGENT", "50000"))

    # Workspace Sandbox Configuration
    WORKSPACE_BASE_DIR: str = os.path.abspath(os.getenv("DEVWATCH_WORKSPACE_DIR", os.getcwd()))
    MAX_FILE_SIZE_BYTES: int = int(os.getenv("DEVWATCH_MAX_FILE_SIZE_BYTES", 5 * 1024 * 1024))  # 5 MB
    MAX_REPO_SIZE_BYTES: int = int(os.getenv("DEVWATCH_MAX_REPO_SIZE_BYTES", 100 * 1024 * 1024))  # 100 MB
    MAX_FILE_COUNT: int = int(os.getenv("DEVWATCH_MAX_FILE_COUNT", 1000))
    MAX_DIRECTORY_DEPTH: int = int(os.getenv("DEVWATCH_MAX_DIRECTORY_DEPTH", 20))


    BLOCKED_FILENAMES: set = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.staging",
        ".env.development",
        "id_rsa",
        "id_rsa.pub",
        "id_ed25519",
        "id_ed25519.pub",
        "credentials",
        "secrets.json",
        "service_account.json",
    }

    BLOCKED_PATTERNS: set = {
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*.keystore",
    }

    @classmethod
    def get_model_for_tier(cls, tier: ModelTier) -> str:
        if tier == ModelTier.FAST:
            return os.getenv("DEVWATCH_FAST_MODEL", cls.FAST_MODEL)
        return os.getenv("DEVWATCH_HEAVY_MODEL", cls.HEAVY_MODEL)

    @classmethod
    def validate_security_config(cls) -> None:
        """Validate security settings. Fails closed in production if API_KEY is missing."""
        env = os.getenv("DEVWATCH_ENV", cls.ENV).lower()
        api_key = os.getenv("DEVWATCH_API_KEY", cls.API_KEY)
        
        if env == "production" and not api_key:
            raise RuntimeError(
                "CRITICAL SECURITY FAILURE: Server is starting in 'production' environment mode, "
                "but DEVWATCH_API_KEY environment variable is not configured. Production mode fails closed."
            )

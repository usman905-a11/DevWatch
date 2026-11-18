"""Source-capture bounds. Review budgets and model tiers live in canonical contracts."""

import fnmatch

SENSITIVE_DIR_NAMES = frozenset({
    ".git",
    ".ssh",
    ".aws",
    ".kube",
    ".gnupg",
    ".azure",
    ".gcloud",
})

SENSITIVE_FILE_NAMES = frozenset({
    ".pypirc",
    ".npmrc",
    ".netrc",
    "id_rsa",
    "id_rsa.pub",
    "id_ed25519",
    "id_ed25519.pub",
    "id_ecdsa",
    "id_ecdsa.pub",
    "id_dsa",
    "id_dsa.pub",
    "credentials",
    "credentials.json",
    "credentials.yml",
    "credentials.yaml",
    "credentials.toml",
    "credentials.ini",
    "credentials.txt",
    "secrets.json",
    "service_account.json",
})


class Config:
    MAX_FILES_PER_REVIEW = 100
    MAX_BYTES_PER_FILE = 500_000
    MAX_REPO_TOTAL_BYTES = 10_000_000
    MAX_CANDIDATE_FINDINGS = 24
    MAX_DIRECTORY_DEPTH = 20

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


SENSITIVE_PATTERNS = tuple(sorted({*Config.BLOCKED_PATTERNS, "*.jks"}))


def is_sensitive_rel_path(rel_posix: str) -> bool:
    """Return True if any path segment refers to secrets, private keys, or VCS metadata."""
    cleaned = rel_posix.replace("\\", "/").strip().strip("/")
    if not cleaned:
        return False
    for part in cleaned.split("/"):
        if not part:
            continue
        lower = part.lower()
        if (
            lower in SENSITIVE_DIR_NAMES
            or lower in SENSITIVE_FILE_NAMES
            or lower in Config.BLOCKED_FILENAMES
            or lower == ".env"
            or lower.startswith(".env.")
            or any(fnmatch.fnmatch(lower, pat) for pat in SENSITIVE_PATTERNS)
        ):
            return True
    return False


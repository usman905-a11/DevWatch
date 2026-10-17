"""Source-capture bounds. Review budgets and model tiers live in canonical contracts."""

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

"""Preserve current legacy source and staged blobs before authorized M5 removal.

Only source paths from the explicit inventory and tests importing those modules
are archived. This script never deletes files, reads credentials or changes Git.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("agents", "pipeline", "routers", "operations", "prompts", "verification", "tools", "resilience")
FILES = ("models.py", "server.py", "scanner.py", "storage.py", "reports.py", "auth.py", "audit_log.py", "rate_limiter.py", "cache.py", "chunker.py",
    "review/engine.py", "review/models.py", "review/agents.py", "review/state.py", "review/factory.py", "review/evidence.py", "review/runner.py", "review/reporting.py",
    "providers/factory.py", "providers/fake_provider.py")
pattern = re.compile(r"devwatch\.(?:agents|pipeline|routers|operations|prompts|verification|tools|resilience|models|server|scanner|storage|reports|auth|audit_log|rate_limiter|cache|chunker|review\.(?:engine|models|agents|state|factory|evidence|runner|reporting)|providers\.(?:factory|fake_provider))(?:\b|\.)")


def main():
    paths = {"devwatch/" + path for path in FILES}
    for directory in DIRECTORIES:
        paths.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "devwatch" / directory).rglob("*.py"))
    paths.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").glob("test_*.py")
        if pattern.search(path.read_text(encoding="utf-8")) and path.name != "test_legacy_removal.py")
    paths.update(("evaluate_langsmith.py", "ARCHITECTURE.md", "MULTI_AGENT_ARCHITECTURE_AUDIT.md"))
    removal = sorted(path for path in paths if (ROOT / path).is_file())
    preserved = sorted(set(removal) | {"README.md", ".env.example", "devwatch/config.py", "devwatch/review/__init__.py", "devwatch/__init__.py", "devwatch/providers/base.py", "devwatch/providers/openai_adapter.py"})
    destination = ROOT / "tasks/history/backend-legacy-2026-10-14.zip"
    manifest = {}
    with ZipFile(destination, "x", compression=ZIP_DEFLATED) as archive:
        for relative in preserved:
            path = (ROOT / relative).resolve(strict=True)
            if not path.is_relative_to(ROOT) or path.is_symlink():
                raise ValueError("Archive source must remain within the workspace")
            data = path.read_bytes()
            manifest[relative] = sha256(data).hexdigest()
            archive.writestr("working-tree/" + relative, data)
            staged = subprocess.run(["git", "show", ":" + relative], cwd=ROOT, capture_output=True, timeout=5)
            if staged.returncode == 0:
                archive.writestr("git-index/" + relative, staged.stdout)
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert all(sha256(archive.read("working-tree/" + path)).hexdigest() == digest for path, digest in manifest.items())
    (ROOT / "tasks/evidence/m5-removal-paths.json").write_text(json.dumps(removal, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"archive": destination.relative_to(ROOT).as_posix(), "preserved_files": len(preserved), "removal_files": len(removal),
        "sha256": sha256(destination.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()

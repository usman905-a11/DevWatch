"""Package contents must satisfy the same cutover as source imports."""
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile
from tests.test_legacy_removal import OBSOLETE


def test_built_wheel_has_no_retired_runtime_or_compatibility_modules(tmp_path):
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
        "--wheel-dir", str(tmp_path), str(root)], capture_output=True, timeout=60)
    assert process.returncode == 0, "Offline wheel build failed"
    with ZipFile(next(tmp_path.glob("devwatch-*.whl"))) as archive:
        members = archive.namelist()
        for obsolete in OBSOLETE:
            prefix = "devwatch/" + obsolete
            assert not any(name == prefix or name.startswith(prefix + "/") for name in members), prefix
        assert "devwatch/review/intelligence_worker.py" in members
        assert "devwatch/review/pdf_worker.py" in members

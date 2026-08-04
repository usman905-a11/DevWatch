import os
import sys
import pytest
from pathlib import Path
from devwatch.config import Config
from devwatch.scanner import CodebaseScanner
from devwatch.storage import ReportStorage
from devwatch.tools.fix_applier import apply_code_fix


@pytest.fixture(autouse=True)
def reset_config_workspace():
    orig_base = Config.WORKSPACE_BASE_DIR
    orig_max_size = Config.MAX_FILE_SIZE_BYTES
    yield
    Config.WORKSPACE_BASE_DIR = orig_base
    Config.MAX_FILE_SIZE_BYTES = orig_max_size



def test_valid_nested_path_read_and_write(tmp_path):
    # Set workspace base to tmp_path
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    scanner = CodebaseScanner(str(tmp_path))

    # Write nested file
    rel_file = "src/modules/auth.py"
    success = scanner.write_file(rel_file, "def login(): return True")
    assert success is True

    # Read back nested file
    content = scanner.read_file(rel_file)
    assert content == "def login(): return True"


def test_linux_traversal_blocked(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("../../../etc/passwd")
    assert "Path traversal attempt blocked" in str(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value)  # Ensure no host path leak


def test_windows_traversal_blocked(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("..\\..\\Windows\\System32\\cmd.exe")
    assert "Path traversal attempt blocked" in str(exc_info.value)


def test_mixed_separator_traversal_blocked(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("sub/../../folder\\..\\secret.py")
    assert "Path traversal attempt blocked" in str(exc_info.value)


def test_absolute_path_outside_sandbox_blocked(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    outside_file = outside_dir / "secret.py"
    outside_file.write_text("SECRET_DATA = 123")

    with pytest.raises(ValueError) as exc_info:
        CodebaseScanner(str(outside_dir))
    assert "Access denied" in str(exc_info.value)


def test_url_encoded_traversal_blocked(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    assert "Path traversal attempt blocked" in str(exc_info.value)


def test_null_byte_path_rejected(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("valid.py\x00.exe")
    assert "Null bytes not allowed" in str(exc_info.value)


def test_symlink_escape_blocked(tmp_path):
    if sys.platform == "win32":
        # On Windows, symlink creation requires admin privileges; skip if privilege error
        try:
            target_outside = tmp_path.parent / "outside_secret.py"
            target_outside.write_text("SECRET_KEY = 12345")
            symlink_inside = tmp_path / "link_outside.py"
            os.symlink(str(target_outside), str(symlink_inside))
        except OSError:
            pytest.skip("Symlink creation requires elevated privileges on Windows")
    else:
        target_outside = tmp_path.parent / "outside_secret.py"
        target_outside.write_text("SECRET_KEY = 12345")
        symlink_inside = tmp_path / "link_outside.py"
        os.symlink(str(target_outside), str(symlink_inside))

    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("link_outside.py")
    assert "Path traversal attempt blocked" in str(exc_info.value)


def test_blocked_sensitive_filenames(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_PASSWORD=secret")
    (tmp_path / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----")
    (tmp_path / "cert.pem").write_text("-----BEGIN CERTIFICATE-----")

    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file(".env")
    assert "blocked sensitive file" in str(exc_info.value)

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("id_rsa")
    assert "blocked sensitive file" in str(exc_info.value)

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("cert.pem")
    assert "blocked sensitive file" in str(exc_info.value)

    # Verify scanner.get_files() ignores sensitive files
    files = scanner.get_files()
    assert ".env" not in files
    assert "id_rsa" not in files
    assert "cert.pem" not in files


def test_unsupported_extension_blocked(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    (tmp_path / "binary.exe").write_bytes(b"\x00\x01\x02\x03")

    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("binary.exe")
    assert "is not permitted" in str(exc_info.value)


def test_oversized_file_rejected(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    Config.MAX_FILE_SIZE_BYTES = 100  # Set low limit for test

    large_file = tmp_path / "large.py"
    large_file.write_text("x = 1\n" * 50)  # > 100 bytes

    scanner = CodebaseScanner(str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        scanner.read_file("large.py")
    assert "exceeds maximum limit" in str(exc_info.value)


def test_report_storage_sandbox(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    storage = ReportStorage(storage_dir=str(tmp_path / ".devwatch" / "reports"))

    # Valid report ID
    assert storage.save_report("report-123_abc", {"status": "ok"}) is True
    assert storage.get_report("report-123_abc") == {"status": "ok"}

    # Invalid report ID attempting traversal
    assert storage.get_report("../../etc/passwd") is None

    with pytest.raises(ValueError) as exc_info:
        storage._get_file_path("../../etc/passwd")
    assert "Invalid report ID" in str(exc_info.value)



def test_fix_applier_sandbox(tmp_path):
    Config.WORKSPACE_BASE_DIR = str(tmp_path)
    (tmp_path / "app.py").write_text("line 1\nOLD_CODE = True\nline 3\n")

    # Apply valid fix
    success = apply_code_fix(
        root_dir=str(tmp_path),
        file_path="app.py",
        line_number=2,
        target_snippet="OLD_CODE = True",
        replacement_code="NEW_CODE = True",
    )
    assert success is True
    assert "NEW_CODE = True" in (tmp_path / "app.py").read_text()

    # Attempt traversal fix
    with pytest.raises(ValueError) as exc_info:
        apply_code_fix(
            root_dir=str(tmp_path),
            file_path="../outside.py",
            line_number=1,
            target_snippet="a",
            replacement_code="b",
        )
    assert "Path traversal attempt blocked" in str(exc_info.value)

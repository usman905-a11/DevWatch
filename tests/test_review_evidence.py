import subprocess
import sys
import os
import time
import tracemalloc
from pathlib import Path
import pytest

from devwatch.config import Config
from devwatch.review.evidence import ContextSelector, GitChangeCollector
from devwatch.review.engine import ReviewEngine
from devwatch.review.models import CommandSpec, SpecialistRole
from devwatch.review.runner import RestrictedCommandRunner, WorkspaceSnapshotter, detect_commands


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_git_change_collector_includes_staged_unstaged_and_untracked(tmp_path):
    """Dropping any working-tree source would make a local review incomplete."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "DevWatch Test")
    (tmp_path / "app.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (tmp_path / "staged.py").write_text("old\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "baseline")

    (tmp_path / "app.py").write_text("one\nchanged\nthree\n", encoding="utf-8")
    (tmp_path / "staged.py").write_text("new\n", encoding="utf-8")
    _git(tmp_path, "add", "staged.py")
    (tmp_path / "new.py").write_text("alpha\nbeta\n", encoding="utf-8")

    changes = GitChangeCollector().collect(tmp_path)

    assert [change.file_path for change in changes] == ["app.py", "new.py", "staged.py"]
    by_file = {change.file_path: change for change in changes}
    assert (by_file["app.py"].start_line, by_file["app.py"].end_line) == (2, 2)
    assert (by_file["new.py"].start_line, by_file["new.py"].end_line) == (1, 2)
    assert (by_file["staged.py"].start_line, by_file["staged.py"].end_line) == (1, 1)


def test_git_change_collector_returns_empty_for_clean_repository(tmp_path):
    """A clean repository must not silently become an expensive full scan."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "DevWatch Test")
    (tmp_path / "app.py").write_text("print('clean')\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "baseline")

    assert GitChangeCollector().collect(tmp_path) == []


def test_git_change_collector_preserves_distant_hunks_and_current_line_numbers(tmp_path):
    """A staged edit shifted by an unstaged insertion must point at current source."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "DevWatch Test")
    path = tmp_path / "app.py"
    path.write_text("a\nb\nc\nd\ne\nf\ng\nh\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    path.write_text("a\nb\nc\nchanged\ne\nf\ng\nh\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    path.write_text("inserted\na\nb\nc\nchanged\ne\nf\ng\nlast\n", encoding="utf-8")

    changes = GitChangeCollector().collect(tmp_path)

    assert [(item.file_path, item.start_line, item.end_line) for item in changes] == [
        ("app.py", 1, 1),
        ("app.py", 5, 5),
        ("app.py", 9, 9),
    ]


def test_git_change_collector_decodes_utf8_source_diff(tmp_path):
    """Git output must use UTF-8 instead of the Windows system code page."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "DevWatch Test")
    path = tmp_path / "app.py"
    path.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "baseline")
    path.write_text("value = 2  # \u010f\n", encoding="utf-8")

    assert [(item.file_path, item.start_line) for item in GitChangeCollector().collect(tmp_path)] == [
        ("app.py", 1)
    ]


def test_git_change_collector_handles_unicode_file_name(tmp_path):
    """Git's quoted path format must not hide a changed UTF-8 source file."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "DevWatch Test")
    path = tmp_path / "m\u00f3dulo.py"
    path.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "baseline")
    path.write_text("value = 2\n", encoding="utf-8")

    assert [item.file_path for item in GitChangeCollector().collect(tmp_path)] == [
        "m\u00f3dulo.py"
    ]


def test_git_change_collector_does_not_assign_deleted_hunk_to_previous_file(tmp_path):
    """A deleted file has no current source range to attribute elsewhere."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "DevWatch Test")
    (tmp_path / "a.py").write_text("keep\nold\n", encoding="utf-8")
    (tmp_path / "z.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "baseline")
    (tmp_path / "a.py").write_text("keep\nnew\n", encoding="utf-8")
    (tmp_path / "z.py").unlink()

    changes = GitChangeCollector().collect(tmp_path)

    assert [(item.file_path, item.start_line, item.end_line) for item in changes] == [
        ("a.py", 2, 2)
    ]


def test_snapshot_and_runner_keep_original_unchanged_and_strip_secrets(tmp_path, monkeypatch):
    """Repository tests may mutate their copy but never the reviewed workspace or inherit API keys."""
    source = tmp_path / "source"
    runs = tmp_path / "runs"
    source.mkdir()
    (source / "app.py").write_text("original\n", encoding="utf-8")
    (source / ".env").write_text("DO_NOT_COPY=secret\n", encoding="utf-8")
    (source / "probe.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "Path('app.py').write_text('mutated copy\\n')\n"
        "print(os.getenv('GROQ_API_KEY', 'missing'))\n"
        "print(os.getenv('DEVWATCH_RUN_COMMANDS', 'unset'))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_API_KEY", "private-key")
    monkeypatch.setenv("DEVWATCH_RUN_COMMANDS", "true")
    snapshot = WorkspaceSnapshotter(runs).create(source, "job-1")
    spec = CommandSpec(name="probe", argv=[sys.executable, "probe.py"])

    evidence = RestrictedCommandRunner([spec], timeout_seconds=10).run(snapshot, spec)

    assert evidence.exit_code == 0
    assert evidence.stdout.splitlines() == ["missing", "false"]
    assert (source / "app.py").read_text(encoding="utf-8") == "original\n"
    assert not (tmp_path / "runs" / "job-1" / ".env").exists()


def test_runner_rejects_commands_outside_exact_allowlist(tmp_path):
    """An LLM-supplied argv must not turn the runner into arbitrary shell access."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("pass\n", encoding="utf-8")
    snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(source, "job-2")
    allowed = CommandSpec(name="version", argv=[sys.executable, "--version"])
    rejected = CommandSpec(name="arbitrary", argv=[sys.executable, "-c", "print('bad')"])

    runner = RestrictedCommandRunner([allowed])
    try:
        runner.run(snapshot, rejected)
    except ValueError as error:
        assert "allowlist" in str(error)
    else:
        raise AssertionError("unconfigured commands must be rejected")


def test_context_selector_adds_imported_module_and_matching_test(tmp_path):
    """Reviewers need contract and test context without widening the changed-file target set."""
    (tmp_path / "app.py").write_text("from domain.user import User\n", encoding="utf-8")
    (tmp_path / "domain").mkdir()
    (tmp_path / "domain" / "user.py").write_text("class User: pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")
    available = ["app.py", "domain/user.py", "tests/test_app.py"]

    selected = ContextSelector(tmp_path).select(["app.py"], available)

    assert selected == ["domain/user.py", "tests/test_app.py"]


def test_context_selector_adds_direct_dependents_but_not_unrelated_files(tmp_path):
    """Changed API definitions need immediate callers as bounded context."""
    (tmp_path / "api.py").write_text("def call(): pass\n", encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        "from api import call\ncall()\n", encoding="utf-8"
    )
    (tmp_path / "unrelated.py").write_text("value = 1\n", encoding="utf-8")
    available = ["api.py", "consumer.py", "unrelated.py"]

    assert ContextSelector(tmp_path).select(["api.py"], available) == ["consumer.py"]


def test_context_selector_resolves_relative_python_imports(tmp_path):
    """Package-local imports must provide both definitions and direct callers."""
    package = tmp_path / "package"
    package.mkdir()
    (package / "api.py").write_text("def call(): pass\n", encoding="utf-8")
    (package / "consumer.py").write_text(
        "from .api import call\ncall()\n", encoding="utf-8"
    )
    available = ["package/api.py", "package/consumer.py"]

    assert ContextSelector(tmp_path).select(["package/api.py"], available) == [
        "package/consumer.py"
    ]
    assert ContextSelector(tmp_path).select(["package/consumer.py"], available) == [
        "package/api.py"
    ]


def test_context_selector_resolves_frontend_relative_imports(tmp_path):
    """Frontend files need immediate dependency and dependent context too."""
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "app.ts").write_text(
        "import { add } from './lib/calc'\nadd(1, 2)\n", encoding="utf-8"
    )
    library = frontend / "lib"
    library.mkdir()
    (library / "calc.ts").write_text(
        "export const add = (a: number, b: number) => a + b\n",
        encoding="utf-8",
    )
    available = ["frontend/app.ts", "frontend/lib/calc.ts"]

    assert ContextSelector(tmp_path).select(["frontend/app.ts"], available) == [
        "frontend/lib/calc.ts"
    ]
    assert ContextSelector(tmp_path).select(["frontend/lib/calc.ts"], available) == [
        "frontend/app.ts"
    ]


def test_command_detection_uses_fixed_argv_for_supported_manifests(tmp_path):
    """Manifest discovery must never convert package text into a shell command."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(
        '{"scripts":{"test":"vitest run"}}', encoding="utf-8"
    )
    snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(tmp_path, "job-manifests")

    commands = detect_commands(snapshot)

    assert [(command.name, command.argv[-2:], command.cwd) for command in commands] == [
        ("pytest", ["pytest", "-q"], "."),
        ("npm-test", ["test", "--silent"], "frontend"),
    ]


def test_snapshot_retention_prunes_only_expired_run_directories(tmp_path):
    runs = tmp_path / "runs"
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("pass\n", encoding="utf-8")
    snapshotter = WorkspaceSnapshotter(runs)
    old = Path(snapshotter.create(source, "job-old").artifact_path)
    recent = Path(snapshotter.create(source, "job-recent").artifact_path)
    expired = time.time() - (3 * 86400)
    os.utime(old, (expired, expired))

    removed = snapshotter.prune(retention_days=2)

    assert removed == 1
    assert not old.exists()
    assert recent.exists()


def test_snapshot_rejects_more_files_than_configured_limit(tmp_path, monkeypatch):
    """An expanded command snapshot must still respect the project file cap."""
    source = tmp_path / "source"
    source.mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (source / name).write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(Config, "MAX_FILE_COUNT", 2)

    with pytest.raises(ValueError, match="file count"):
        WorkspaceSnapshotter(tmp_path / "runs").create(source, "job-too-many")


def test_runner_rejects_shell_and_package_install_commands(tmp_path):
    shell = CommandSpec(name="shell", argv=["cmd", "/c", "echo unsafe"])
    installer = CommandSpec(name="installer", argv=["npm", "install"])

    for command in (shell, installer):
        with pytest.raises(ValueError):
            RestrictedCommandRunner([command])


def test_command_detection_loads_explicit_safe_toml_commands(tmp_path):
    (tmp_path / ".devwatch.toml").write_text(
        "[[review.commands]]\n"
        "name = 'ruff-check'\n"
        "argv = ['ruff', 'check', '.']\n"
        "cwd = '.'\n",
        encoding="utf-8",
    )
    snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(tmp_path, "job-config")

    commands = detect_commands(snapshot)

    assert CommandSpec(name="ruff-check", argv=["ruff", "check", "."], cwd=".") in commands


def test_runner_rejects_traversal_cwd_and_caps_output(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "loud.py").write_text("print('x' * 500)\n", encoding="utf-8")
    snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(source, "job-limits")
    traversal = CommandSpec(name="bad-cwd", argv=[sys.executable, "loud.py"], cwd="..")
    with pytest.raises(ValueError, match="escaped"):
        RestrictedCommandRunner([traversal]).run(snapshot, traversal)

    loud = CommandSpec(name="loud", argv=[sys.executable, "loud.py"])
    evidence = RestrictedCommandRunner([loud], max_output_bytes=32).run(snapshot, loud)
    assert evidence.stdout.endswith("[truncated]")
    assert len(evidence.stdout) < 60


def test_runner_rejects_traversal_in_argv():
    """A configured command cannot read a source path outside its snapshot."""
    command = CommandSpec(name="escape", argv=[sys.executable, "../outside.py"])
    with pytest.raises(ValueError, match="traversal"):
        RestrictedCommandRunner([command])


def test_runner_rejects_untrusted_executable_path(tmp_path):
    """A local file named python.exe must not satisfy the executable allowlist."""
    command = CommandSpec(
        name="local-python", argv=[str(tmp_path / "python.exe"), "--version"]
    )
    with pytest.raises(ValueError, match="executable"):
        RestrictedCommandRunner([command])


def test_runner_rejects_symlink_cwd_escape(tmp_path):
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(source, "job-link")
    try:
        (Path(snapshot.artifact_path) / "outside").symlink_to(
            outside, target_is_directory=True
        )
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    command = CommandSpec(
        name="version", argv=[sys.executable, "--version"], cwd="outside"
    )

    with pytest.raises(ValueError, match="escaped"):
        RestrictedCommandRunner([command]).run(snapshot, command)


def test_runner_caps_capture_memory_and_decodes_utf8(tmp_path):
    """A noisy child must not accumulate its entire output before truncation."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "loud.py").write_text(
        "import sys\n"
        "sys.stdout.buffer.write(b'x' * (8 * 1024 * 1024))\n",
        encoding="utf-8",
    )
    snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(source, "job-loud")
    command = CommandSpec(name="loud", argv=[sys.executable, "loud.py"])

    tracemalloc.start()
    try:
        evidence = RestrictedCommandRunner([command], max_output_bytes=64).run(
            snapshot, command
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert evidence.exit_code == 0
    assert evidence.stdout.endswith("[truncated]")
    assert peak < 2 * 1024 * 1024

    (source / "unicode.py").write_text(
        "import sys\nsys.stderr.buffer.write(bytes([0xc3, 0xa9]))\n",
        encoding="utf-8",
    )
    unicode_snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(
        source, "job-unicode"
    )
    unicode_command = CommandSpec(name="unicode", argv=[sys.executable, "unicode.py"])
    decoded = RestrictedCommandRunner([unicode_command], max_output_bytes=64).run(
        unicode_snapshot, unicode_command
    )
    assert decoded.stderr == chr(0xe9)


def test_runner_terminates_timed_out_process(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "slow.py").write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(source, "job-timeout")
    slow = CommandSpec(name="slow", argv=[sys.executable, "slow.py"])

    evidence = RestrictedCommandRunner([slow], timeout_seconds=0.05).run(snapshot, slow)

    assert "timed out" in evidence.stderr
    assert evidence.exit_code != 0


def test_runner_timeout_terminates_child_process_tree(tmp_path):
    """A timed-out test must not leave a child writing to the snapshot later."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "child.py").write_text(
        "import time\nfrom pathlib import Path\n"
        "time.sleep(1)\nPath('marker.txt').write_text('alive')\n",
        encoding="utf-8",
    )
    (source / "parent.py").write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    snapshot = WorkspaceSnapshotter(tmp_path / "runs").create(source, "job-tree")
    command = CommandSpec(name="tree", argv=[sys.executable, "parent.py"])

    result = RestrictedCommandRunner([command], timeout_seconds=0.3).run(
        snapshot, command
    )
    time.sleep(1.1)

    assert result.exit_code == -9
    assert not (Path(snapshot.artifact_path) / "marker.txt").exists()


@pytest.mark.asyncio
async def test_repository_tests_run_with_unchanged_supporting_files_in_snapshot(tmp_path):
    """Detected tests must run against a complete disposable copy of the project."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "DevWatch Test")
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'review-fixture'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "helper.py").write_text("expected = 2\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_smoke.py").write_text(
        "from helper import expected\nfrom app import value\n"
        "def test_value():\n    assert value == expected\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")

    class RecordingPlanner:
        evidence = None

        async def execute(self, context):
            self.evidence = context["tool_evidence"]
            return []

    planner = RecordingPlanner()
    engine = ReviewEngine(
        planner=planner,
        specialists={},
        verifier=RecordingPlanner(),
        runs_dir=tmp_path / "runs",
        run_commands=True,
    )

    await engine.review_repository(str(repo))

    assert len(planner.evidence) == 1
    assert planner.evidence[0].source == "pytest"
    assert planner.evidence[0].exit_code == 0
    assert "1 passed" in planner.evidence[0].stdout
    assert (repo / "app.py").read_text(encoding="utf-8") == "value = 2\n"

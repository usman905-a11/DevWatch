"""Disposable installed VS Code extension-host gate, with a local fixture service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    executable = Path(os.environ.get("DEVWATCH_TEST_CODE", str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe")))
    if not executable.is_file():
        raise RuntimeError("Installed VS Code executable required")
    with tempfile.TemporaryDirectory(prefix="devwatch-vscode-host-") as directory:
        temporary = Path(directory)
        workspace = temporary / "workspace"
        workspace.mkdir()
        source = workspace / "service.py"
        source.write_text("def first(items):\n    return items[0]\n", encoding="utf-8")
        original = source.read_bytes()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        environment = dict(os.environ)
        environment.pop("ELECTRON_RUN_AS_NODE", None)
        environment.pop("VSCODE_IPC_HOOK_CLI", None)
        environment["DEVWATCH_TEST_PYTHON"] = str(Path(sys.executable).resolve())
        environment["LANGSMITH_TRACING"] = "false"
        environment["LANGCHAIN_TRACING_V2"] = "false"
        startup = None
        if os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
        log = ROOT / "tasks/evidence/m7-vscode-host-process.txt"
        with log.open("w", encoding="utf-8") as output:
            service = subprocess.Popen([sys.executable, "-m", "scripts.verify_browser_parity", "--serve", str(temporary / "runtime")],
                cwd=ROOT, env=environment, stdout=output, stderr=output, creationflags=flags)
            code = None
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        with urlopen("http://127.0.0.1:8998/openapi.json", timeout=1):
                            break
                    except OSError:
                        time.sleep(.1)
                arguments = [str(executable), str(workspace), "--user-data-dir", str(temporary / "profile"),
                    "--extensions-dir", str(temporary / "extensions"), "--extensionDevelopmentPath=" + str(ROOT / "extensions/vscode"),
                    "--extensionTestsPath=" + str(ROOT / "extensions/vscode/dist/test/host.js"), "--disable-extensions", "--disable-workspace-trust",
                    "--skip-welcome", "--skip-release-notes", "--disable-telemetry", "--disable-crash-reporter", "--headless", "--disable-gpu", "--no-sandbox"]
                code = subprocess.Popen(arguments, cwd=ROOT, env=environment, stdout=output, stderr=output,
                    creationflags=flags, startupinfo=startup)
                result = code.wait(timeout=90)
                assert result == 0, "Extension-host gate failed; inspect its isolated process log"
                assert source.read_bytes() == original
                text = log.read_text(encoding="utf-8", errors="replace")
                assert '"canonical_job":true' in text, "Extension host did not execute its runtime checks"
                print(json.dumps({"ide": "VS Code", "canonical_job": True, "reopen": True, "source_unchanged": True,
                    "isolated_profile": True, "no_remote_publication": True}))
            finally:
                for process in (code, service):
                    if process is not None and process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)


if __name__ == "__main__":
    main()

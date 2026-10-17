"""Bounded parser process protocol; load only the service-owned implementation."""
import importlib.util
import json
from pathlib import Path
import sys


def main():
    data = sys.stdin.buffer.read(3_100_001)
    if len(data) > 3_100_000:
        raise ValueError("Parser request too large")
    request = json.loads(data)
    if set(request) != {"path", "source"} or not isinstance(request["path"], str) or not isinstance(request["source"], str):
        raise ValueError("Invalid parser protocol")
    if len(request["path"].encode()) > 1024 or len(request["source"].encode()) > 500_000:
        raise ValueError("Parser input too large")
    spec = importlib.util.spec_from_file_location("devwatch_parser_impl", Path(__file__).with_name("intelligence.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = json.dumps(module._analyze_source(request["path"], request["source"]), ensure_ascii=False).encode("utf-8")
    if len(output) > 2_000_000:
        raise ValueError("Parser output too large")
    sys.stdout.buffer.write(output)


if __name__ == "__main__":
    main()

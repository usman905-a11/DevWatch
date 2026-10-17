"""Fixed renderer worker: bounded accepted JSON in, bounded PDF bytes out.

Invoked by absolute script path so it imports only the document layout and its
dependencies, not the service, providers or legacy package initialization.
This process never chooses a filename or accesses a store.
"""
import json
import sys

from _pdf_document import render_document


def main():
    payload = sys.stdin.buffer.read(10_000_001)
    if len(payload) > 10_000_000:
        raise ValueError("PDF input exceeds its byte limit")
    data = render_document(json.loads(payload))
    if len(data) > 10_000_000:
        raise ValueError("PDF output exceeds its byte limit")
    sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()

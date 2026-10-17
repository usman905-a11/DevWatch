"""Deterministic client watching; execution always belongs to durable jobs."""
from hashlib import sha256
from copy import deepcopy
import json
import math
from uuid import uuid4

from devwatch.review.capture import CapturedSource
from devwatch.review.client import ClientError, ReviewClient


def _fingerprint(capture: CapturedSource) -> str:
    version = {"files": {path: sha256(text.encode("utf-8")).hexdigest() for path, text in capture.files.items()},
               "changed_files": capture.changed_files, "scope_kind": capture.scope_kind,
               "coverage": capture.coverage.model_dump(mode="json"), "git_metadata": capture.git_metadata.model_dump(mode="json")}
    return sha256(json.dumps(version, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


class WatchReviewer:
    """Keep one active job and only the latest observed pending capture.

    Polling never cancels/resumes execution or retries an unknown submission.
    A caller must display/save on_intent before submitting to recover lost replies.
    """
    def __init__(self, client: ReviewClient, *, debounce_seconds=1., on_intent=None, on_job=None, on_status=None):
        if not math.isfinite(debounce_seconds) or not 0 <= debounce_seconds <= 60:
            raise ValueError("Watch debounce must be between zero and sixty seconds")
        self.client, self.debounce_seconds = client, debounce_seconds
        self.on_intent, self.on_job, self.on_status = on_intent, on_job, on_status
        self.active_job = None
        self.intent = None
        self.submissions = 0
        self._root = None
        self._known_paths = set()
        self._deleted_paths = set()
        self._deletion_truncated = False
        self._observed = self._last_submitted = None
        self._pending = None
        self._stable_since = 0.
        self._last_poll = None

    def _coverage(self, capture):
        capture = capture.model_copy(deep=True)
        if self._root is not None and capture.root != self._root:
            raise ValueError("Watch target root changed; restart with the intended target")
        self._root = capture.root
        # A temporary size/encoding/limit omission must not erase path history.
        # Retain names only, bounded independently of the latest source contents.
        for path in sorted(capture.files):
            if len(self._known_paths) < 1000:
                self._known_paths.add(path)
            elif path not in self._known_paths:
                self._deletion_truncated = True
        if capture.scope_kind == "directory":
            for path in sorted(self._known_paths):
                if path in capture.files or path in capture.coverage.skipped or path in capture.coverage.failed:
                    self._deleted_paths.discard(path)
                    continue
                try:
                    (capture.root / path).lstat()
                except FileNotFoundError:
                    if len(self._deleted_paths) < 1000:
                        self._deleted_paths.add(path)
                    else:
                        self._deletion_truncated = True
                except OSError:
                    if len(capture.coverage.failed) < 1000:
                        capture.coverage.failed[path] = "unavailable_source"
                else:
                    self._deleted_paths.discard(path)
            for path in sorted(self._deleted_paths):
                if len(capture.coverage.skipped) < 1000:
                    capture.coverage.skipped[path] = "deleted_source_unavailable"
                else:
                    self._deletion_truncated = True
            if self._deletion_truncated:
                capture.coverage.limitations.append("Watch path/deletion coverage is capped at 1000 paths; some paths may be unlisted.")
        return capture

    def poll(self, capture: CapturedSource, *, now: float):
        if not math.isfinite(now) or (self._last_poll is not None and now < self._last_poll):
            raise ValueError("Watch requires a finite monotonic observation time")
        if self.intent is not None and self.active_job is None:
            raise ClientError("Submission outcome unresolved; recover with the original snapshot, scope and key. No new submission issued.")
        self._last_poll = now
        current = self._coverage(capture)
        fingerprint = _fingerprint(current)
        reviewable = bool(current.changed_files or current.coverage.failed or self._deleted_paths or self._deletion_truncated or
                          "deleted_source_unavailable" in current.coverage.skipped.values())
        if fingerprint != self._observed:
            self._observed, self._stable_since = fingerprint, now
            self._pending = current if reviewable and fingerprint != self._last_submitted else None
        if self.active_job is not None:
            job = self.client.status(self.active_job.job_id)
            self.active_job = job
            if job.status in {"queued", "running"}:
                return None
            if job.status == "interrupted":
                raise ClientError(f"Job {job.job_id} is interrupted; use resume or cancel explicitly before restarting watch.")
            if self.on_status is not None:
                self.on_status(job.model_copy(deep=True))
            self.active_job, self.intent = None, None
        if self._pending is None or now - self._stable_since < self.debounce_seconds:
            return None
        manifest = self.client.capture(self._pending)
        self.intent = {"snapshot_id": manifest.snapshot_id, "changed_files": list(self._pending.changed_files),
                       "idempotency_key": uuid4().hex}
        if self.on_intent is not None:
            self.on_intent(deepcopy(self.intent))
        job = self.client.submit(self.intent["snapshot_id"], self.intent["changed_files"],
                                 idempotency_key=self.intent["idempotency_key"])
        self.active_job, self._last_submitted, self._pending = job, fingerprint, None
        self.submissions += 1
        if self.on_job is not None:
            self.on_job(job.model_copy(deep=True))
        return job.model_copy(deep=True)

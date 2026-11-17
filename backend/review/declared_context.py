"""Bounded caller-selected snapshot context, shared as data across review roles."""

MAX_CONTEXT_FILES = 4
MAX_CONTEXT_BYTES = 6000


def validate_context_files(manifest, paths):
    if paths is None:
        return []
    if not isinstance(paths, list) or len(paths) > MAX_CONTEXT_FILES or any(not isinstance(p, str) for p in paths):
        raise ValueError('context_files must be a list of at most four snapshot paths')
    selected = list(dict.fromkeys(paths))
    if any(path not in manifest.entries for path in selected):
        raise ValueError('context files must belong to the snapshot')
    if sum(manifest.entries[path].byte_count for path in selected) > MAX_CONTEXT_BYTES:
        raise ValueError('declared context exceeds 6000 UTF-8 bytes')
    return selected


def load_declared_context(repository, paths):
    selected = validate_context_files(repository.manifest, paths)
    if not selected:
        return None
    return dict(snapshot_id=repository.snapshot_id, snapshot_hash=repository.manifest.content_hash,
        files=[dict(file_path=path, content_hash=repository.manifest.entries[path].content_hash,
                    content=repository._source(path)) for path in selected])

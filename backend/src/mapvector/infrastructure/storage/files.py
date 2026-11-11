import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def atomic_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the basename short for Windows installations without long-path support.
    temporary = path.with_name(uuid4().hex[:8]+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, content):
    atomic_bytes(path, json.dumps(content, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode('utf-8'))

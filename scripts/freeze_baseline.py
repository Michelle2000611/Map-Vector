"""Read-only source inventory. Large data and virtual environments are never copied."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def git(source: Path, *arguments: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(source), *arguments])


def freeze(source: Path, output: Path) -> dict:
    source = source.resolve()
    output.mkdir(parents=True, exist_ok=True)
    tracked = git(source, 'ls-files', '-z').decode('utf-8').split('\0')
    untracked = git(source, 'ls-files', '--others', '--exclude-standard', '-z').decode('utf-8').split('\0')
    suffixes = {'.py', '.json', '.toml', '.yaml', '.yml', '.js', '.tsx', '.ts', '.css', '.html', '.cmd', '.md', '.txt'}
    files = []
    for name in sorted(set(tracked + untracked)):
        if not name or any(part.startswith('.venv') for part in Path(name).parts):
            continue
        path = source / name
        if not path.is_file() or path.suffix not in suffixes:
            continue
        body = path.read_bytes()
        files.append({'rel_path': name, 'sha256': hashlib.sha256(body).hexdigest(), 'byte_size': len(body), 'tracked': name in tracked})
    patch = git(source, 'diff', '--binary', 'HEAD')
    (output / 'working-tree.patch').write_bytes(patch)
    manifest = {'baseline_commit': git(source, 'rev-parse', 'HEAD').decode().strip(), 'patch_sha256': hashlib.sha256(patch).hexdigest(), 'source_files': files, 'source_name': source.name, 'model_inventory_status': 'pending', 'runtime_equivalence_status': 'not_verified'}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    result = freeze(arguments.source, arguments.output)
    print(json.dumps({'baseline_commit': result['baseline_commit'], 'file_count': len(result['source_files'])}))

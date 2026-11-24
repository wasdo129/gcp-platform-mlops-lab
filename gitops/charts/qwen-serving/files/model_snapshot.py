"""Download or verify the locked Hugging Face snapshot."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlopen


def verify(path, entry):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["size"]:
        raise ValueError(f"Unexpected size or type: {path.name}")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {path.name}")


def download(url, path, entry):
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with urlopen(url, timeout=30) as source, temporary.open("xb") as target:
            remaining = entry["size"]
            while chunk := source.read(min(1024 * 1024, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError(f"Download exceeds locked size: {path.name}")
                target.write(chunk)
        verify(temporary, entry)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def snapshot(lock, directory, verify_only=False):
    repository = lock["repository"]
    revision = lock["revision"]
    if not re.fullmatch(r"[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+", repository):
        raise ValueError("Invalid repository")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected an immutable revision")
    if directory.is_symlink():
        raise ValueError("Snapshot directory cannot be a symlink")
    if not verify_only:
        directory.mkdir(parents=True, exist_ok=True)
    files = lock["files"]
    for name in files:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", name) or name.endswith(".part"):
            raise ValueError(f"Invalid filename: {name}")

    allowed = set(files)
    if not verify_only:
        allowed.update(f"{name}.part" for name in files if not (directory / name).exists())
    unexpected = sorted(path.name for path in directory.iterdir() if path.name not in allowed)
    if unexpected:
        raise ValueError(f"Unexpected snapshot entries: {', '.join(unexpected)}")

    for name, entry in files.items():
        path = directory / name
        if verify_only or path.exists() or path.is_symlink():
            verify(path, entry)
        else:
            download(f"https://huggingface.co/{repository}/resolve/{revision}/{name}", path, entry)
        print(f"Verified {name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    snapshot(json.loads(args.lock.read_text()), args.directory, args.verify_only)

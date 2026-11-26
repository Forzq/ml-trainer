"""Identify the actual runtime source files included in a Mockroom build."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = "0.1.0"
BUILD_INFO = ROOT / "build-info.json"


def source_id(root=ROOT):
    files = [root / path for path in (
        "Dockerfile", "requirements.txt", "content/questions.json", "content/question-versions-v1.json",
    )]
    for folder in ("app", "web"):
        files.extend(path for path in (root / folder).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".ico")
                     and not path.name.startswith("."))
    fingerprint = hashlib.sha256()
    for path in sorted(files, key=lambda path: path.relative_to(root).as_posix()):
        fingerprint.update(path.relative_to(root).as_posix().encode() + b"\0")
        fingerprint.update(hashlib.sha256(path.read_bytes()).digest())
    return fingerprint.hexdigest()[:12]


@lru_cache(maxsize=1)
def current_build():
    if BUILD_INFO.is_file():
        return json.loads(BUILD_INFO.read_text(encoding="utf-8"))
    return {"version": RELEASE, "id": None, "commit": None, "dirty": None, "built_at": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--commit", default="")
    parser.add_argument("--dirty", choices=("", "true", "false"), default="")
    args = parser.parse_args()
    build = source_id()
    if args.write:
        payload = {"version": RELEASE, "id": build, "commit": args.commit or None,
                   "dirty": args.dirty == "true" if args.dirty else None,
                   "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        BUILD_INFO.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    else:
        print(build)


if __name__ == "__main__":
    main()

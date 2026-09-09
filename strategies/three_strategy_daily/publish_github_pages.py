from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any

import requests


OWNER = "zzyfsniper-code"
REPOSITORY = "sector-bias-dashboard"
BRANCH = "main"
REPO_DIR = Path(r"D:\agent工作目录\数据看板工作文件夹")
API_ROOT = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}"
PAGE_DIRS = (
    "growth-value-five-dim",
    "csi500-flow-leverage",
    "all-weather-risk-parity",
)
CENTER_FILES = (
    "strategies/index.html",
    "strategies/styles.css",
    "strategies/header.css",
    "strategies/app.js",
)


def request(session: requests.Session, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = session.request(method, API_ROOT + path, timeout=60, **kwargs)
    if response.status_code >= 400:
        try:
            message = response.json().get("message")
        except ValueError:
            message = None
        raise RuntimeError(
            f"GitHub API {method} {path} failed: HTTP {response.status_code} {message or 'unknown error'}"
        )
    return response.json() if response.content else {}


def publish_paths() -> list[tuple[str, Path]]:
    files: list[Path] = []
    for relative_dir in PAGE_DIRS:
        files.extend(path for path in sorted((REPO_DIR / relative_dir).rglob("*")) if path.is_file())
    files.extend(REPO_DIR / relative_path for relative_path in CENTER_FILES)
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Publish inputs are missing: {missing}")
    return [(path.relative_to(REPO_DIR).as_posix(), path) for path in files]


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish all three strategy pages in one GitHub commit")
    parser.add_argument("--message", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    files = publish_paths()
    if args.dry_run:
        print(json.dumps({"status": "DRY_RUN", "files": [path for path, _ in files]}, ensure_ascii=False))
        return

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required in the process environment")
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "three-strategy-dashboard-publisher",
        }
    )
    reference = request(session, "GET", f"/git/ref/heads/{BRANCH}")
    parent_sha = reference["object"]["sha"]
    parent_commit = request(session, "GET", f"/git/commits/{parent_sha}")
    entries: list[dict[str, str]] = []
    for remote_path, local_path in files:
        content = base64.b64encode(local_path.read_bytes()).decode("ascii")
        blob = request(session, "POST", "/git/blobs", json={"content": content, "encoding": "base64"})
        entries.append({"path": remote_path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree = request(
        session,
        "POST",
        "/git/trees",
        json={"base_tree": parent_commit["tree"]["sha"], "tree": entries},
    )
    commit = request(
        session,
        "POST",
        "/git/commits",
        json={"message": args.message, "tree": tree["sha"], "parents": [parent_sha]},
    )
    request(session, "PATCH", f"/git/refs/heads/{BRANCH}", json={"sha": commit["sha"], "force": False})
    print(
        json.dumps(
            {"status": "PASS", "commit": commit["sha"], "parent": parent_sha, "files": len(entries)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

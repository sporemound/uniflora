from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUIRED_FILES = (
    "scientific-plate.svg",
    "scientific-plate.png",
    "visualization.json",
    "activity-data.json",
    "activity-visualization.json",
    "manifest-phase3b.json",
    "activity-publication.json",
)


def run(command: list[str]) -> None:
    print("  " + subprocess.list2cmdline(command))
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read Activity API response from {url}: {exc}") from exc


def current_state_head(base_url: str, environment: str) -> str:
    url = f"{base_url.rstrip('/')}/api/public-state?environment={environment}"
    payload = fetch_json(url)
    value = payload.get("stateHeadHash") if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value:
        raise SystemExit("Activity public-state response did not contain stateHeadHash")
    return value


def remote_artifact_hashes(
    base_url: str,
    environment: str,
    artifact_id: str,
) -> dict[str, str]:
    url = (
        f"{base_url.rstrip('/')}/api/artifacts/"
        f"{environment}/{urllib.parse.quote(artifact_id)}"
    )
    payload = fetch_json(url)
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise SystemExit("Activity artifact-list response had an invalid shape")
    result: dict[str, str] = {}
    for item in payload["files"]:
        if not isinstance(item, dict):
            continue
        filename = item.get("filename")
        sha256 = item.get("sha256")
        if isinstance(filename, str) and isinstance(sha256, str):
            result[filename] = sha256
    return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish one Phase 3B bundle through the signed Activity helper."
    )
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--activity-root", type=Path, default=Path("../activity"))
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    args = parser.parse_args()

    missing = [name for name in REQUIRED_FILES if not (args.bundle / name).is_file()]
    if missing:
        parser.error(f"Bundle is missing: {', '.join(missing)}")
    helper = args.activity_root / "tools" / "publish_hypha.py"
    if not helper.is_file():
        parser.error(f"Signed Activity helper does not exist: {helper}")

    manifest = json.loads(
        (args.bundle / "manifest-phase3b.json").read_text(encoding="utf-8")
    )
    artifact_id = manifest["artifactId"]
    environment = manifest["environment"]
    remote_hashes = remote_artifact_hashes(
        args.base_url,
        environment,
        artifact_id,
    )

    print("Uploading immutable files:")
    for filename in REQUIRED_FILES[:-1]:
        local_path = args.bundle / filename
        local_hash = file_sha256(local_path)
        remote_hash = remote_hashes.get(filename)
        if remote_hash == local_hash:
            print(f"  already registered with matching SHA-256: {filename}")
            continue
        if remote_hash is not None:
            raise SystemExit(
                f"Remote artifact conflict for {filename}: "
                f"local {local_hash}, remote {remote_hash}"
            )
        run(
            [
                sys.executable,
                str(helper),
                "--base-url",
                args.base_url,
                "artifact",
                "--environment",
                environment,
                "--artifact-id",
                artifact_id,
                str(local_path),
            ]
        )

    publication = json.loads(
        (args.bundle / "activity-publication.json").read_text(encoding="utf-8")
    )
    publication["evidenceStateHeadHash"] = publication.get(
        "evidenceStateHeadHash",
        publication.get("stateHeadHash"),
    )
    publication_state_head = current_state_head(args.base_url, environment)
    publication["stateHeadHash"] = publication_state_head
    publication["publicationId"] = (
        f"{publication['publicationId']}-{publication_state_head[:12]}"
    )

    latest_url = (
        f"{args.base_url.rstrip('/')}/api/publications/latest"
        f"?environment={environment}"
    )
    latest = fetch_json(latest_url)
    if (
        isinstance(latest, dict)
        and latest.get("publicationId") == publication["publicationId"]
        and latest.get("artifactId") == publication["artifactId"]
    ):
        print(
            "Publication is already registered for the current public state head: "
            f"{publication['publicationId']}"
        )
        return 0

    publication["publishedAt"] = (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    print("Registering publication against current public state head:")
    with tempfile.TemporaryDirectory(prefix="missing-interior-publication-") as directory:
        publication_path = Path(directory) / "activity-publication.json"
        publication_path.write_text(
            json.dumps(publication, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        run(
            [
                sys.executable,
                str(helper),
                "--base-url",
                args.base_url,
                "publication",
                str(publication_path),
            ]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def _secret(environment_variable: str) -> bytes:
    value = os.environ.get(environment_variable, "").strip()
    if not value:
        raise SystemExit(
            f"Set the {environment_variable} environment variable before publishing."
        )
    return value.encode()


def _signed_request(
    *,
    base_url: str,
    method: str,
    path: str,
    body: bytes,
    content_type: str,
    secret: bytes,
) -> dict[str, object]:
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join([method.upper(), path, timestamp, nonce, body_hash])
    signature = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(
        url,
        data=body,
        method=method.upper(),
        headers={
            "Accept": "application/json",
            "Content-Type": content_type,
            "X-Hypha-Timestamp": timestamp,
            "X-Hypha-Nonce": nonce,
            "X-Hypha-Content-SHA256": body_hash,
            "X-Hypha-Signature": f"v1={signature}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_body = response.read().decode("utf-8")
            return {
                "status": response.status,
                "body": json.loads(response_body) if response_body else None,
            }
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Publication request failed: {error.reason}") from error


def _read_json(path: Path) -> bytes:
    value = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def publish_state(args: argparse.Namespace, secret: bytes) -> dict[str, object]:
    body = _read_json(args.file)
    return _signed_request(
        base_url=args.base_url,
        method="POST",
        path="/api/hypha/state",
        body=body,
        content_type="application/json",
        secret=secret,
    )


def publish_artifact(args: argparse.Namespace, secret: bytes) -> dict[str, object]:
    body = args.file.read_bytes()
    filename = urllib.parse.quote(args.file.name, safe="-._~")
    artifact_id = urllib.parse.quote(args.artifact_id, safe="-._~")
    path = f"/api/hypha/artifacts/{args.environment}/{artifact_id}/{filename}"
    content_type = args.content_type or mimetypes.guess_type(args.file.name)[0]
    return _signed_request(
        base_url=args.base_url,
        method="PUT",
        path=path,
        body=body,
        content_type=content_type or "application/octet-stream",
        secret=secret,
    )


def publish_publication(args: argparse.Namespace, secret: bytes) -> dict[str, object]:
    body = _read_json(args.file)
    return _signed_request(
        base_url=args.base_url,
        method="POST",
        path="/api/hypha/publications",
        body=body,
        content_type="application/json",
        secret=secret,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sign and publish sanitized Phase 2 Activity state and artifacts."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5173",
        help="Activity Worker base URL.",
    )
    parser.add_argument(
        "--secret-env",
        default="HYPHA_ACTIVITY_SECRET",
        help="Environment variable containing the shared HMAC secret.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    state = commands.add_parser("state", help="Publish one public-state revision.")
    state.add_argument("file", type=Path)
    state.set_defaults(handler=publish_state)

    artifact = commands.add_parser("artifact", help="Upload one immutable artifact file.")
    artifact.add_argument("--environment", choices=("live", "test"), required=True)
    artifact.add_argument("--artifact-id", required=True)
    artifact.add_argument("--content-type")
    artifact.add_argument("file", type=Path)
    artifact.set_defaults(handler=publish_artifact)

    publication = commands.add_parser(
        "publication",
        help="Register publication metadata after its artifact files exist.",
    )
    publication.add_argument("file", type=Path)
    publication.set_defaults(handler=publish_publication)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.file.is_file():
        parser.error(f"File does not exist: {args.file}")
    result = args.handler(args, _secret(args.secret_env))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

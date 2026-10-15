"""Verify each published page once using the publisher's direct HTTPS transport."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests


def page_run_id(text: str) -> str | None:
    payload = json.loads(text.split("=", 1)[1].strip().removesuffix(";"))
    return payload.get("run_id") or payload.get("meta", {}).get("runId")


def check_page(
    session: requests.Session, url: str, expected_run_id: str | None, batch_id: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": url,
        "status": "FAIL",
        "http_status": None,
        "expected_run_id": expected_run_id,
        "verified_run_id": None,
        "error_type": None,
        "error_summary": None,
    }
    # Publication URLs are fixed project URLs; never send inherited authentication.
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "zzyfsniper-code.github.io":
        result.update(error_type="invalid_url", error_summary="Unexpected publication host.")
        return result
    try:
        response = session.get(url, params={"run": batch_id}, timeout=30)
        result["http_status"] = response.status_code
        if response.status_code != 200:
            result.update(error_type="http_error", error_summary=f"HTTP {response.status_code}")
            return result
        if expected_run_id is not None:
            actual_run_id = page_run_id(response.text)
            result["actual_run_id"] = actual_run_id
            if actual_run_id != expected_run_id:
                result.update(
                    error_type="run_id_mismatch",
                    error_summary=f"Expected {expected_run_id}; received {actual_run_id}.",
                )
                return result
            result["verified_run_id"] = actual_run_id
        result["status"] = "PASS"
    except requests.exceptions.SSLError:
        result.update(error_type="tls_error", error_summary="HTTPS certificate or TLS handshake failed.")
    except requests.exceptions.Timeout:
        result.update(error_type="timeout", error_summary="HTTPS request timed out after 30 seconds.")
    except requests.exceptions.RequestException as error:
        result.update(error_type="connection_error", error_summary=type(error).__name__)
    except (ValueError, IndexError, AttributeError):
        result.update(error_type="invalid_strategy_data", error_summary="Invalid strategy data payload.")
    return result


def verify(batch: dict[str, Any]) -> dict[str, Any]:
    with requests.Session() as session:
        session.trust_env = False
        session.verify = True
        session.headers["User-Agent"] = "three-strategy-online-verifier"
        center = check_page(session, batch["strategy_center"], None, batch["run_id"])
        strategies = []
        for item in batch["strategies"]:
            result = check_page(
                session,
                item["page_url"].rstrip("/") + "/data/strategy-data.js",
                item["run_id"],
                batch["run_id"],
            )
            result["strategy"] = item["strategy"]
            strategies.append(result)
    return {
        "status": (
            "PASS" if center["status"] == "PASS"
            and all(item["status"] == "PASS" for item in strategies) else "FAIL"
        ),
        "transport": "requests_direct",
        "tls_verification": True,
        "center": center,
        "strategies": strategies,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-file", type=Path, required=True)
    args = parser.parse_args()
    batch = json.loads(args.batch_file.read_text(encoding="utf-8-sig"))
    result = verify(batch)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

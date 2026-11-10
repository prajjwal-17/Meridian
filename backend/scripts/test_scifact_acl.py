"""Read-only SciFact ACL security evaluation driven by a separate manifest."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import requests
BASE_URL = "http://127.0.0.1:8000"
MODES = ("bm25", "dense", "graph", "hybrid", "hybrid_rerank")
def load_manifest(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ACL manifest must be an object")
    for field in ("identities", "cases"):
        if not isinstance(payload.get(field), list):
            raise ValueError(f"ACL manifest field {field} must be a list")
    return payload
def allowed_source_ids(identity: dict, manifest: dict) -> set[str]:
    allowed = set()
    for document in manifest.get("documents", []):
        if not isinstance(document, dict):
            continue
        users = set(document.get("restricted_users", []))
        source_id = str(document["source_document_id"])
        if document.get("tier") == "public":
            allowed.add(source_id)
        elif document.get("tier") == "restricted" and identity["user"] in users:
            allowed.add(source_id)
        elif document.get("tier") == "department" and identity.get("department") == document.get("department"):
            allowed.add(source_id)
        elif document.get("tier") == "team" and identity.get("team") == document.get("team"):
            allowed.add(source_id)
    return allowed
def run_case(session: requests.Session, identity: dict, case: dict, mode: str, manifest: dict) -> tuple[str, str]:
    api_mode = "hybrid" if mode == "hybrid_rerank" else mode
    params = {"q": case["query"], "mode": api_mode, "top_k": 10}
    if mode == "hybrid_rerank":
        params["rerank"] = "true"
    headers = {"X-Meridian-User": identity["user"], "X-Meridian-Team": identity.get("team", ""), "X-Meridian-Department": identity.get("department", "")}
    try:
        response = session.get(f"{BASE_URL}/search", params=params, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return "ERROR", str(exc)
    if response.status_code != 200:
        return "ERROR", f"HTTP {response.status_code}: {response.text[:200]}"
    try:
        results = response.json()["results"]
        returned = {str(item["source_document_id"]) for item in results if item.get("source_document_id") is not None}
    except (ValueError, KeyError, TypeError) as exc:
        return "ERROR", f"invalid search response: {exc}"
    unauthorized = returned - allowed_source_ids(identity, manifest)
    expected = {str(value) for value in case.get("expected_source_ids", [])}
    missing = expected - returned
    if unauthorized:
        return "FAIL", f"unauthorized source IDs returned: {sorted(unauthorized)}"
    if missing:
        return "FAIL", f"expected authorized source IDs missing: {sorted(missing)}"
    return "PASS", f"returned source IDs: {sorted(returned)}"
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    failures = 0
    errors = 0
    session = requests.Session()
    print(f"{'MODE':<18} {'IDENTITY':<14} {'CASE':<25} STATUS NOTE")
    print("-" * 100)
    for identity in manifest["identities"]:
        for case in manifest["cases"]:
            for mode in MODES:
                status, note = run_case(session, identity, case, mode, manifest)
                print(f"{mode:<18} {identity['user']:<14} {case['name']:<25} {status:<5} {note}")
                if status == "FAIL":
                    failures += 1
                elif status == "ERROR":
                    errors += 1
    print()
    print(f"failures={failures} errors={errors}")
    return 1 if failures or errors else 0
if __name__ == "__main__":
    raise SystemExit(main())

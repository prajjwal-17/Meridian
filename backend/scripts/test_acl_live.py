"""Live, read-only ACL integration test for the running Meridian API.

This script never uploads files or writes to PostgreSQL. It requires the
documents and ACL assignments described by DOCUMENTS to already exist.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import requests


BASE_URL = "http://127.0.0.1:8000"
SEARCH_PATH = "/search"
DOCUMENTS_PATH = "/documents"
TOP_K = 20
REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Identity:
    name: str
    user_id: str
    department: str
    team: str

    def headers(self) -> dict[str, str]:
        return {
            "X-Meridian-User": self.user_id,
            "X-Meridian-Team": self.team,
            "X-Meridian-Department": self.department,
        }


@dataclass(frozen=True)
class QueryDocument:
    name: str
    document_id: int
    query: str
    authorized_identities: frozenset[str]


IDENTITIES = (
    Identity("alice", "alice", "hr", "recruitment"),
    Identity("bob", "bob", "engineering", "backend"),
    Identity("charlie", "charlie", "finance", "finance-ops"),
    Identity("david", "david", "engineering", "frontend"),
)

DOCUMENTS = (
    QueryDocument(
        "HR_Policy.pdf", 7, "employee leave attendance payroll",
        frozenset({"alice"}),
    ),
    QueryDocument(
        "Engineering_guide.pdf",
        8,
        "Docker Kubernetes FastAPI PostgreSQL",
        frozenset({"bob", "david"}),
    ),
    QueryDocument(
        "Finance_Report.pdf",
        9,
        "quarterly budget operating expenses invoices",
        frozenset({"charlie"}),
    ),
    QueryDocument(
        "Backend_Architecture.pdf",
        10,
        "API Gateway Kafka microservice Redis",
        frozenset({"bob"}),
    ),
)

MODES = ("bm25", "dense", "graph", "hybrid")

AUTHORIZED_DOCUMENT_IDS = {
    "alice": frozenset({7}),
    "bob": frozenset({8, 10}),
    "charlie": frozenset({9}),
    "david": frozenset({8}),
}


def response_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or "no response body"
    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])[:200]
    return str(payload)[:200]


def get_documents(session: requests.Session) -> tuple[dict[int, str], list[str]]:
    """Return live document IDs and preflight errors without mutating state."""

    try:
        response = session.get(
            f"{BASE_URL}{DOCUMENTS_PATH}",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return {}, [f"GET /documents unavailable: {exc}"]

    if response.status_code != 200:
        return {}, [
            f"GET /documents returned HTTP {response.status_code}: "
            f"{response_detail(response)}"
        ]

    try:
        payload = response.json()
        documents = payload["documents"]
        live_documents = {
            int(item["id"]): str(item["filename"])
            for item in documents
        }
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {}, [f"Invalid /documents response structure: {exc}"]

    errors = []
    for expected in DOCUMENTS:
        actual_name = live_documents.get(expected.document_id)
        if actual_name is None:
            errors.append(
                f"expected document ID {expected.document_id} "
                f"({expected.name}) is not present"
            )
    return live_documents, errors


def validate_search_payload(payload: Any) -> tuple[list[int], str | None]:
    """Validate the actual /search response shape and extract document IDs."""

    if not isinstance(payload, dict):
        return [], "response is not a JSON object"
    if not isinstance(payload.get("results"), list):
        return [], "response.results is not a list"

    document_ids = []
    for index, result in enumerate(payload["results"]):
        if not isinstance(result, dict):
            return [], f"results[{index}] is not an object"
        if "document_id" not in result:
            return [], f"results[{index}] has no document_id"
        try:
            document_ids.append(int(result["document_id"]))
        except (TypeError, ValueError):
            return [], f"results[{index}].document_id is not an integer"
    return document_ids, None


def run_search(
    session: requests.Session,
    query_document: QueryDocument,
    identity: Identity,
    mode: str,
) -> tuple[str, str, set[int]]:
    """Return status, diagnostic note, and actual returned document IDs."""

    try:
        response = session.get(
            f"{BASE_URL}{SEARCH_PATH}",
            params={
                "q": query_document.query,
                "mode": mode,
                "top_k": TOP_K,
            },
            headers=identity.headers(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return "ERROR", f"request failed: {exc}", set()

    if response.status_code != 200:
        # This includes unavailable dense models and hybrid failures. They are
        # deliberately never treated as successful authorization checks.
        return (
            "ERROR",
            f"HTTP {response.status_code}: {response_detail(response)}",
            set(),
        )

    try:
        payload = response.json()
    except ValueError:
        return "ERROR", "response was not valid JSON", set()

    document_ids, error = validate_search_payload(payload)
    if error:
        return "ERROR", error, set()

    actual_ids = set(document_ids)
    expected_access = identity.name in query_document.authorized_identities
    actual_access = query_document.document_id in actual_ids
    unauthorized_ids = actual_ids - AUTHORIZED_DOCUMENT_IDS[identity.name]

    # A successful retrieval must contain the target for its authorized
    # identity and must not expose the target to any other identity.
    if actual_access != expected_access:
        return (
            "FAIL",
            f"expected access={expected_access}, actual access={actual_access}; "
            f"returned_ids={sorted(actual_ids)}",
            actual_ids,
        )
    if unauthorized_ids:
        return (
            "FAIL",
            f"unauthorized document_ids returned={sorted(unauthorized_ids)}; "
            f"returned_ids={sorted(actual_ids)}",
            actual_ids,
        )

    return (
        "PASS",
        f"expected access={expected_access}, returned_ids={sorted(actual_ids)}",
        actual_ids,
    )


def run_missing_identity_check(session: requests.Session) -> tuple[str, str]:
    try:
        response = session.get(
            f"{BASE_URL}{SEARCH_PATH}",
            params={"q": "employee leave attendance payroll", "mode": "bm25"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return "ERROR", f"request failed: {exc}"

    if response.status_code == 401:
        return "PASS", "missing X-Meridian-User returned HTTP 401"
    return (
        "FAIL",
        f"expected HTTP 401, got HTTP {response.status_code}: "
        f"{response_detail(response)}",
    )


def main() -> int:
    session = requests.Session()
    print(f"Meridian live ACL test: {BASE_URL}")

    _, preflight_errors = get_documents(session)
    if preflight_errors:
        print("\nPreflight: ERROR")
        for error in preflight_errors:
            print(f"  - {error}")
    else:
        print("\nPreflight: PASS - expected document IDs 7, 8, 9, 10 exist")

    print("\nSearch matrix")
    print(
        f"{'MODE':<8} {'QUERY DOC':<25} {'IDENTITY':<10} "
        f"{'EXPECTED':<10} {'ACTUAL':<8} {'STATUS':<7} NOTE"
    )
    print("-" * 125)

    failures = len(preflight_errors)
    errors = 0
    for mode in MODES:
        for query_document in DOCUMENTS:
            for identity in IDENTITIES:
                expected = identity.name in query_document.authorized_identities
                status, note, actual_ids = run_search(
                    session, query_document, identity, mode
                )
                actual = (
                    "yes"
                    if query_document.document_id in actual_ids
                    else "no"
                )
                print(
                    f"{mode:<8} {query_document.name:<25} "
                    f"{identity.name:<10} {str(expected):<10} "
                    f"{actual:<8} {status:<7} {note}"
                )
                if status == "FAIL":
                    failures += 1
                elif status == "ERROR":
                    errors += 1

    missing_status, missing_note = run_missing_identity_check(session)
    print("\nMissing identity check")
    print(f"{missing_status}: {missing_note}")
    if missing_status != "PASS":
        failures += 1

    print("\nSummary")
    print(f"  preflight_errors: {len(preflight_errors)}")
    print(f"  assertion_failures: {failures}")
    print(f"  API_errors: {errors}")
    print(
        "  result: "
        + ("PASS" if failures == 0 and errors == 0 else "FAIL")
    )

    session.close()
    return 0 if failures == 0 and errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

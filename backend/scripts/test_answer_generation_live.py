"""Live validation of Meridian's Ollama-backed /ask endpoint.

This script intentionally exercises only the public API. It does not recreate
retrieval, ACL, prompt, or citation logic locally.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import Any

import requests


CITATION_PATTERN = re.compile(r"\[(C\d+)\]")
ABSTENTION_PATTERN = re.compile(
    r"\b(insufficient|not enough evidence|cannot answer|not mentioned|does not provide)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Scenario:
    name: str
    question: str
    user: str
    department: str
    team: str
    expected_document_id: int | None = None
    expect_abstention: bool = False
    forbid_document_id: int | None = None


SCENARIOS = (
    Scenario(
        "HR policy / Alice",
        "What is the employee leave policy?",
        "alice",
        "hr",
        "recruitment",
        expected_document_id=7,
    ),
    Scenario(
        "Engineering documentation / Bob",
        "What technologies and deployment practices are documented?",
        "bob",
        "engineering",
        "backend",
        expected_document_id=8,
    ),
    Scenario(
        "Finance information / Charlie",
        "What financial information is documented?",
        "charlie",
        "finance",
        "finance-ops",
        expected_document_id=9,
    ),
    Scenario(
        "Backend architecture / Bob",
        "What backend architecture and service technologies are documented?",
        "bob",
        "engineering",
        "backend",
        expected_document_id=10,
    ),
    Scenario(
        "Unauthorized finance access / Alice",
        "What financial information is documented?",
        "alice",
        "hr",
        "recruitment",
        forbid_document_id=9,
    ),
    Scenario(
        "Unsupported future revenue question",
        "What was the company's revenue in 2035?",
        "alice",
        "hr",
        "recruitment",
        expect_abstention=True,
    ),
)


def headers(scenario: Scenario) -> dict[str, str]:
    return {
        "X-Meridian-User": scenario.user,
        "X-Meridian-Team": scenario.team,
        "X-Meridian-Department": scenario.department,
    }


def check_response_shape(payload: Any) -> tuple[bool, str]:
    required = {"question", "answer", "citations", "sufficient_evidence", "retrieval"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        return False, f"missing response fields; expected {sorted(required)}"
    if not isinstance(payload["answer"], str):
        return False, "answer is not a string"
    if not isinstance(payload["citations"], list):
        return False, "citations is not a list"
    if not isinstance(payload["sufficient_evidence"], bool):
        return False, "sufficient_evidence is not boolean"
    retrieval = payload["retrieval"]
    if not isinstance(retrieval, dict) or not isinstance(retrieval.get("results"), list):
        return False, "retrieval.results is missing or is not a list"
    return True, "response shape valid"


def validate_payload(payload: dict[str, Any]) -> list[tuple[bool, str]]:
    results = payload["retrieval"]["results"]
    citations = payload["citations"]
    result_keys = {
        (item.get("document_id"), item.get("chunk_id"))
        for item in results
        if isinstance(item, dict)
    }
    citation_ids = {
        item.get("citation_id") for item in citations if isinstance(item, dict)
    }
    referenced_ids = set(CITATION_PATTERN.findall(payload["answer"]))
    checks = [
        (
            referenced_ids.issubset(citation_ids),
            "all citation IDs in answer exist in citations array",
        ),
        (
            all(
                isinstance(item, dict)
                and isinstance(item.get("citation_id"), str)
                and (item.get("document_id"), item.get("chunk_id")) in result_keys
                for item in citations
            ),
            "citations reference retrieved document/chunk pairs",
        ),
        (
            not payload["sufficient_evidence"] or bool(citations),
            "sufficient_evidence is consistent with citation evidence",
        ),
        (
            payload["sufficient_evidence"] or bool(ABSTENTION_PATTERN.search(payload["answer"])),
            "insufficient evidence is stated when sufficient_evidence is false",
        ),
    ]
    return checks


def run(base_url: str, timeout: float) -> int:
    session = requests.Session()
    passed = 0
    failed = 0
    successful_payloads: dict[str, dict[str, Any]] = {}

    print(f"Meridian live answer validation: {base_url}")
    print("Retrieval relevance is checked separately from authorization.\n")

    for scenario in SCENARIOS:
        print(f"=== {scenario.name} ===")
        print(f"Question: {scenario.question}")
        try:
            response = session.post(
                f"{base_url}/ask",
                # Omit rerank so this validates the /ask default. The explicit
                # false path is checked separately below.
                json={"question": scenario.question, "top_k": 5},
                headers=headers(scenario),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            print(f"FAIL request: {exc}")
            failed += 1
            continue

        if response.status_code != 200:
            print(f"FAIL HTTP {response.status_code}: {response.text[:500]}")
            failed += 1
            continue

        try:
            payload = response.json()
        except ValueError as exc:
            print(f"FAIL invalid JSON response: {exc}")
            failed += 1
            continue

        shape_ok, shape_note = check_response_shape(payload)
        print(f"{'PASS' if shape_ok else 'FAIL'} HTTP 200; {shape_note}")
        if not shape_ok:
            failed += 1
            continue
        passed += 1 if shape_ok else 0
        successful_payloads[scenario.name] = payload

        results = payload["retrieval"]["results"]
        result_document_ids = sorted({item.get("document_id") for item in results})
        citation_document_ids = sorted({item.get("document_id") for item in payload["citations"]})
        print(f"Authorized document IDs returned: {result_document_ids}")
        print(f"Citation document IDs: {citation_document_ids}")
        selected_chunks = payload["retrieval"].get("selected_chunks", [])
        print(
            "Selected chunks / cross-encoder scores: "
            f"{[(item.get('chunk_id'), item.get('cross_encoder_score')) for item in selected_chunks]}"
        )
        print(f"sufficient_evidence: {payload['sufficient_evidence']}")
        print(f"Answer:\n{payload['answer']}\n")

        for ok, note in validate_payload(payload):
            print(f"{'PASS' if ok else 'FAIL'} {note}")
            if ok:
                passed += 1
            else:
                failed += 1

        if scenario.expected_document_id is not None:
            ok = scenario.expected_document_id in result_document_ids
            print(
                f"{'PASS' if ok else 'FAIL'} expected enterprise document "
                f"{scenario.expected_document_id} appears in retrieved results"
            )
            if ok:
                passed += 1
            else:
                failed += 1

        if scenario.forbid_document_id is not None:
            unauthorized = {
                item.get("document_id")
                for item in results + payload["citations"]
                if isinstance(item, dict)
                and item.get("document_id") == scenario.forbid_document_id
            }
            ok = not unauthorized
            print(
                f"{'PASS' if ok else 'FAIL'} unauthorized document IDs detected: "
                f"{sorted(unauthorized)}"
            )
            if ok:
                passed += 1
            else:
                failed += 1
            print(
                "NOTE LLM context is not exposed by POST /ask; this API-level "
                "check verifies the authorized retrieval and citation material "
                "that can reach context."
            )

        if scenario.expect_abstention:
            abstained = (
                not payload["sufficient_evidence"]
                or bool(ABSTENTION_PATTERN.search(payload["answer"]))
            )
            print(f"{'PASS' if abstained else 'FAIL'} abstention behavior observed")
            if abstained:
                passed += 1
            else:
                failed += 1

    print("=== Explicit rerank=false comparison ===")
    for name in ("HR policy / Alice", "Finance information / Charlie"):
        scenario = next(item for item in SCENARIOS if item.name == name)
        default_payload = successful_payloads.get(name)
        if default_payload is None:
            print(f"FAIL {name}: default response was unavailable")
            failed += 1
            continue
        try:
            response = session.post(
                f"{base_url}/ask",
                json={"question": scenario.question, "top_k": 5, "rerank": False},
                headers=headers(scenario),
                timeout=timeout,
            )
            payload = response.json() if response.status_code == 200 else {}
        except (requests.RequestException, ValueError) as exc:
            print(f"FAIL {name}: explicit rerank=false request failed: {exc}")
            failed += 1
            continue
        if response.status_code != 200:
            print(f"FAIL {name}: explicit rerank=false returned HTTP {response.status_code}")
            failed += 1
            continue

        default_scores = [
            item.get("cross_encoder_score")
            for item in default_payload["retrieval"]["results"]
        ]
        disabled_scores = [
            item.get("cross_encoder_score")
            for item in payload.get("retrieval", {}).get("results", [])
        ]
        default_has_scores = bool(default_scores) and all(
            isinstance(score, (int, float)) for score in default_scores
        )
        disabled_has_no_scores = not any(score is not None for score in disabled_scores)
        for ok, note in (
            (default_has_scores, f"{name}: default /ask exposes cross-encoder scores"),
            (disabled_has_no_scores, f"{name}: explicit rerank=false omits cross-encoder scores"),
        ):
            print(f"{'PASS' if ok else 'FAIL'} {note}")
            if ok:
                passed += 1
            else:
                failed += 1
        print(f"Default answer:\n{default_payload['answer']}\n")
        print(f"rerank=false answer:\n{payload.get('answer', '')}\n")

    print("=== Missing identity ===")
    try:
        response = session.post(
            f"{base_url}/ask",
            json={"question": "What is the employee leave policy?"},
            timeout=timeout,
        )
        ok = response.status_code == 401
        print(f"{'PASS' if ok else 'FAIL'} expected HTTP 401, got {response.status_code}")
        if ok:
            passed += 1
        else:
            failed += 1
    except requests.RequestException as exc:
        print(f"FAIL missing-identity request: {exc}")
        failed += 1

    print(f"\nTotal passed checks: {passed}")
    print(f"Total failed checks: {failed}")
    return 1 if failed else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Running Meridian API base URL",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    return run(args.base_url.rstrip("/"), args.timeout)


if __name__ == "__main__":
    sys.exit(main())

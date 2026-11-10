"""Live multi-user retrieval and grounded-answer validation.

This exercises the real authenticated API. It does not recreate ACL or
retrieval logic locally; it only checks returned source IDs, response shape,
and the generated answer/citations.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DEFAULT_MODES = ("bm25", "dense", "hybrid")
SOURCE_PATTERN = re.compile(r"^[A-Z]+-\d+$")


@dataclass(frozen=True)
class Scenario:
    name: str
    email: str
    question: str
    expected_sources: tuple[str, ...] = ()
    forbidden_sources: tuple[str, ...] = ()


SCENARIOS = (
    Scenario(
        "HR leave policy / Aisha",
        "aisha.khan@meridian.example",
        "What does the employee leave and attendance policy say?",
        ("HR-001",),
    ),
    Scenario(
        "Recruitment onboarding / Mateo",
        "mateo.silva@meridian.example",
        "What are the recruitment and onboarding steps?",
        ("HR-003",),
    ),
    Scenario(
        "Backend integration / Priya",
        "priya.nair@meridian.example",
        "How should backend services communicate and integrate?",
        ("ENG-003",),
        ("ENG-004", "IT-004"),
    ),
    Scenario(
        "Incident response / Daniel",
        "daniel.brooks@meridian.example",
        "What are the production deployment and incident response procedures?",
        ("ENG-004",),
    ),
    Scenario(
        "Finance team isolation / Omar",
        "omar.haddad@meridian.example",
        "What is the employee expense reimbursement process?",
        (),
        ("FIN-002", "FIN-003", "FIN-004"),
    ),
    Scenario(
        "Finance and operations overlap / Grace",
        "grace.wilson@meridian.example",
        "What are the expense reimbursement and vendor management requirements?",
        ("FIN-002", "OPS-002"),
        ("FIN-004",),
    ),
    Scenario(
        "IT access control / Noah",
        "noah.patel@meridian.example",
        "What does the enterprise access control policy require?",
        ("IT-001",),
    ),
    Scenario(
        "Explicit restricted access / Sofia",
        "sofia.chen@meridian.example",
        "Summarize the annual department budget allocation report.",
        ("FIN-004",),
    ),
    Scenario(
        "Unauthorized finance query / Aisha",
        "aisha.khan@meridian.example",
        "What is in the quarterly financial planning and expense report?",
        (),
        ("FIN-001", "FIN-002", "FIN-003", "FIN-004"),
    ),
    Scenario(
        "Unauthorized vendor query / Lucas",
        "lucas.martin@meridian.example",
        "What does the vendor management framework require?",
        (),
        ("OPS-002",),
    ),
)


def load_accounts() -> dict[str, dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "test_users.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {account["email"].casefold(): account for account in payload["accounts"]}


def login(session: requests.Session, base_url: str, account: dict[str, Any], timeout: float) -> requests.Response:
    return session.post(
        f"{base_url}/auth/login",
        json={"identifier": account["email"], "password": account["password"]},
        headers={"Origin": "http://127.0.0.1:5173"},
        timeout=timeout,
    )


def csrf(session: requests.Session) -> str:
    return session.cookies.get("meridian_csrf", "")


def source_ids(items: list[dict[str, Any]]) -> set[str]:
    values = {item.get("source_document_id") for item in items if isinstance(item, dict)}
    return {value for value in values if isinstance(value, str) and SOURCE_PATTERN.fullmatch(value)}


def run_scenario(
    base_url: str,
    scenario: Scenario,
    accounts: dict[str, dict[str, Any]],
    timeout: float,
    modes: tuple[str, ...],
) -> tuple[int, int]:
    account = accounts[scenario.email.casefold()]
    session = requests.Session()
    passed = failed = 0
    login_response = login(session, base_url, account, timeout)
    if login_response.status_code != 200:
        print(f"FAIL login {scenario.email}: HTTP {login_response.status_code} {login_response.text[:300]}")
        return 0, 1
    print(f"\n=== {scenario.name} ({account['user_id']}) ===")
    print(f"Question: {scenario.question}")

    for mode in modes:
        try:
            response = session.get(
                f"{base_url}/search",
                params={"q": scenario.question, "mode": mode, "top_k": 5},
                timeout=timeout,
            )
            payload = response.json() if response.content else {}
        except (requests.RequestException, ValueError) as exc:
            print(f"FAIL {mode}: {exc}")
            failed += 1
            continue
        results = payload.get("results", []) if isinstance(payload, dict) else []
        returned_sources = source_ids(results)
        forbidden_found = returned_sources.intersection(scenario.forbidden_sources)
        expected_found = returned_sources.intersection(scenario.expected_sources)
        ok_http = response.status_code == 200
        ok_forbidden = not forbidden_found
        ok_expected = not scenario.expected_sources or bool(expected_found)
        ok = ok_http and ok_forbidden and ok_expected
        print(
            f"{'PASS' if ok else 'FAIL'} {mode}: HTTP={response.status_code}; "
            f"sources={sorted(returned_sources)}; expected={sorted(expected_found)}; "
            f"forbidden={sorted(forbidden_found)}"
        )
        passed += int(ok)
        failed += int(not ok)

    try:
        response = session.post(
            f"{base_url}/ask",
            json={"question": scenario.question, "top_k": 5, "rerank": True},
            headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf(session)},
            timeout=timeout,
        )
        payload = response.json() if response.content else {}
    except (requests.RequestException, ValueError) as exc:
        print(f"FAIL ask: {exc}")
        return passed, failed + 1

    results = payload.get("retrieval", {}).get("results", []) if isinstance(payload, dict) else []
    citations = payload.get("citations", []) if isinstance(payload, dict) else []
    retrieval_sources = source_ids(results)
    citation_sources = source_ids(citations)
    forbidden_found = (retrieval_sources | citation_sources).intersection(scenario.forbidden_sources)
    expected_found = (retrieval_sources | citation_sources).intersection(scenario.expected_sources)
    answer_ok = response.status_code == 200 and isinstance(payload.get("answer"), str) and bool(payload["answer"].strip())
    citations_ok = all(item.get("document_id") is not None and item.get("chunk_id") is not None for item in citations if isinstance(item, dict))
    acl_ok = not forbidden_found
    relevance_ok = not scenario.expected_sources or bool(expected_found)
    ok = answer_ok and citations_ok and acl_ok and relevance_ok
    print(f"{'PASS' if ok else 'FAIL'} ask: HTTP={response.status_code}; sufficient_evidence={payload.get('sufficient_evidence')}; retrieved={sorted(retrieval_sources)}; citations={sorted(citation_sources)}")
    print(f"Answer:\n{payload.get('answer', '<no answer>')}\n")
    print(f"Citation chunks: {[(item.get('citation_id'), item.get('document_id'), item.get('chunk_id')) for item in citations if isinstance(item, dict)]}")
    passed += int(ok)
    failed += int(not ok)
    return passed, failed


def main() -> int:
    # Windows PowerShell may expose a cp1252 stdout while generated answers
    # legitimately contain Unicode currency symbols and punctuation.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--include-graph",
        action="store_true",
        help="Also run graph retrieval; graph relevance is reported but is not part of the default comparison.",
    )
    args = parser.parse_args()
    modes = DEFAULT_MODES + (("graph",) if args.include_graph else ())
    accounts = load_accounts()
    missing = {scenario.email for scenario in SCENARIOS if scenario.email.casefold() not in accounts}
    if missing:
        print(f"Missing demo credentials for: {sorted(missing)}", file=sys.stderr)
        return 2
    passed = failed = 0
    for scenario in SCENARIOS:
        scenario_passed, scenario_failed = run_scenario(
            args.base_url.rstrip("/"), scenario, accounts, args.timeout, modes
        )
        passed += scenario_passed
        failed += scenario_failed
    print(f"\nTotal passed checks: {passed}")
    print(f"Total failed checks: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

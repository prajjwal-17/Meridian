"""Live validation of grounded answers (/ask and /ask/stream) with Ollama.

Each scenario signs in as a demo account and checks that:
  - answerable questions are answered and cite the expected source,
  - questions about documents the user cannot read are not answered from them,
  - unsupported questions abstain,
  - every citation belongs to a document the user may read.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from live_support import BASE_URL, authorized_document_ids, demo_accounts, login, run_live, user_id_for


@dataclass(frozen=True)
class Scenario:
    name: str
    email_prefix: str
    question: str
    expected_source: str | None = None      # source_document_id that must be cited
    forbidden_source: str | None = None     # must never be cited
    expect_abstention: bool = False


SCENARIOS = (
    Scenario("HR leave policy", "aisha.khan", "How many sick leave days do employees get?", expected_source="HR-001"),
    Scenario("Backend service communication", "priya.nair", "How should backend services communicate and integrate?", expected_source="ENG-003"),
    Scenario("Access control policy", "noah.patel", "What does the enterprise access control policy require?", expected_source="IT-001"),
    Scenario("Restricted budget denied", "aisha.khan", "What is in the annual department budget allocation report?", forbidden_source="FIN-004"),
    Scenario("Unsupported question", "aisha.khan", "What was the company's revenue in 2035?", expect_abstention=True),
)


def check(scenario: Scenario, payload: dict, allowed: set[int], via: str) -> list[str]:
    failures = []
    label = f"{scenario.name} ({via})"
    cited_sources = {c.get("source_document_id") for c in payload.get("citations", [])}
    cited_docs = {c.get("document_id") for c in payload.get("citations", [])}
    if cited_docs - allowed:
        failures.append(f"{label}: cited unauthorized documents {sorted(cited_docs - allowed)}")
    if scenario.expected_source and not (payload.get("sufficient_evidence") and scenario.expected_source in cited_sources):
        failures.append(f"{label}: expected an answer citing {scenario.expected_source}, got {payload.get('answer', '')[:160]!r}")
    if scenario.forbidden_source and scenario.forbidden_source in cited_sources:
        failures.append(f"{label}: cited forbidden {scenario.forbidden_source}")
    if scenario.expect_abstention and payload.get("sufficient_evidence"):
        failures.append(f"{label}: expected abstention, got {payload.get('answer', '')[:160]!r}")
    return failures


def ask_stream(session, question: str) -> dict:
    final = {}
    with session.post(f"{BASE_URL}/ask/stream", json={"question": question}, stream=True, timeout=300) as response:
        response.raise_for_status()
        for raw in response.iter_lines():
            if raw:
                event = json.loads(raw)
                if event["type"] in {"final", "error"}:
                    final = event
    if final.get("type") == "error":
        raise AssertionError(f"stream error: {final.get('detail')}")
    return final


def main() -> int:
    accounts = {a["email"].split("@")[0]: a for a in demo_accounts()}
    failures = []
    for scenario in SCENARIOS:
        session = login(accounts[scenario.email_prefix])
        allowed = authorized_document_ids(user_id_for(session))
        response = session.post(f"{BASE_URL}/ask", json={"question": scenario.question}, timeout=300)
        if response.status_code != 200:
            failures.append(f"{scenario.name}: /ask HTTP {response.status_code} {response.text[:200]}")
            continue
        failures += check(scenario, response.json(), allowed, "/ask")
        failures += check(scenario, ask_stream(session, scenario.question), allowed, "/ask/stream")
        print(f"checked {scenario.name}")
    for failure in failures:
        print("FAIL", failure)
    print("PASS" if not failures else f"{len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run_live(main))

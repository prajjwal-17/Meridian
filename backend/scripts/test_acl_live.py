"""Live, read-only ACL integration test for the running Meridian API.

For every demo account and every retrieval mode, every document returned by
/search must be one the account is authorized to read (oracle computed from the
database). Unauthenticated search must be rejected. Nothing is written.
"""

from __future__ import annotations

import sys

import requests

from live_support import BASE_URL, authorized_document_ids, demo_accounts, login, run_live, user_id_for

MODES = ("bm25", "dense", "graph", "hybrid")
QUERIES = (
    "employee leave and attendance policy",
    "how should backend services communicate",
    "expense reimbursement and procurement approval",
    "annual department budget allocation",
    "access control and password standards",
    "vendor management and business continuity",
)


def main() -> int:
    failures = []
    checks = 0
    for account in demo_accounts():
        session = login(account)
        allowed = authorized_document_ids(user_id_for(session))
        for mode in MODES:
            for query in QUERIES:
                response = session.get(
                    f"{BASE_URL}/search", params={"q": query, "mode": mode, "top_k": 20}, timeout=60
                )
                checks += 1
                if response.status_code != 200:
                    failures.append(f"{account['name']} {mode} {query!r}: HTTP {response.status_code}")
                    continue
                leaked = {r["document_id"] for r in response.json()["results"]} - allowed
                if leaked:
                    failures.append(f"{account['name']} {mode} {query!r}: unauthorized documents {sorted(leaked)}")
        print(f"checked {account['name']}: {len(allowed)} readable documents")

    anonymous = requests.get(f"{BASE_URL}/search", params={"q": "leave", "mode": "bm25"}, timeout=30)
    if anonymous.status_code != 401:
        failures.append(f"unauthenticated search returned HTTP {anonymous.status_code}, expected 401")

    print(f"{checks} searches checked, {len(failures)} failures")
    for failure in failures:
        print("FAIL", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run_live(main))

#!/usr/bin/env python3
"""
test_human_layer.py — Japanese Non-Engineer Layer reference fixture test
Case 1〜4 のREFERENCE_ONLY設計期待が自己整合していることを検証する。
実LLM挙動・runtime E2E・model supportの証拠にはしない。
"""

import sys, os, json

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")

def test_fixtures():
    req_file = os.path.join(FIXTURES_DIR, "vague_requests_ja.jsonl")
    exp_file = os.path.join(FIXTURES_DIR, "expected_behavior.jsonl")

    with open(req_file, "r") as f:
        requests = [json.loads(line) for line in f]
    with open(exp_file, "r") as f:
        expectations = [json.loads(line) for line in f]

    print("=== Japanese Non-Engineer Layer Fixtures Acceptance Test ===")
    print(f"Total Test Cases: {len(requests)}\n")

    for req, exp in zip(requests, expectations):
        cid = req["case_id"]
        raw = req["raw_input"]
        wtype = exp["work_type"]
        clar = exp["clarification_needed"]
        vtype = exp["verification_type"]

        assert exp.get("evidence_status") == "REFERENCE_ONLY", (
            f"{cid} fixture must not be represented as live behavior evidence"
        )

        print(f"🧪 [{cid}] Input: \"{raw}\"")
        print(f"   - Work Type:            {wtype}")
        print(f"   - Clarification Needed: {clar}")
        print(f"   - Verification:         {vtype}")
        
        # Invariants Check
        if cid == "case_1":
            assert not clar, "Case 1 should not require unnecessary clarification"
            assert "commit" in exp["forbidden_actions"], "Case 1 must forbid auto-commit"
        elif cid == "case_2":
            assert clar, "Case 2 must require clarification"
            assert exp.get("no_hallucination"), "Case 2 must prevent hallucination"
        elif cid == "case_3":
            assert clar, "Case 3 must require clarification before deletion"
            assert exp.get("auto_delete_blocked"), "Case 3 must block auto-deletion"
        elif cid == "case_4":
            assert clar, "Case 4 must clarify recipient/channel before sending"
            assert exp.get("authority_separated"), "Case 4 must separate creation from sending authority"

        print("   -> Result: PASS ✅\n")

    print("All 4 Acceptance Cases PASSED successfully!")

if __name__ == "__main__":
    test_fixtures()

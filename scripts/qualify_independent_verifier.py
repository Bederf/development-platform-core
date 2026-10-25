"""Produce bounded synthetic evidence for the independent verifier harness."""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from adapters.independent_verifier_qualification import (  # noqa: E402
    ExecutionIdentity,
    IndependentVerifierQualification,
    QualificationCase,
    SeededDefect,
)


def payment_calculator(inputs: dict[str, str]) -> str:
    amount = Decimal(inputs["amount"])
    rate = Decimal(inputs["rate"])
    return str((amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists; choose a new evidence directory: {args.output}")

    cases = [
        QualificationCase("ordinary", {"amount": "100.00", "rate": "0.15"}, "15.00"),
        QualificationCase("round-half-up", {"amount": "10.005", "rate": "1"}, "10.01"),
        QualificationCase("zero", {"amount": "0.00", "rate": "0.15"}, "0.00"),
    ]
    qualification = IndependentVerifierQualification(
        producer=ExecutionIdentity("coding-agent", "coding-session-001"),
        verifier=ExecutionIdentity("forge-verifier", "verify-session-001"),
        oracle=ExecutionIdentity("payments-domain-owner", "oracle-session-001"),
    )
    result = qualification.qualify(
        subject=payment_calculator,
        cases=cases,
        seeded_defects=[
            SeededDefect(
                "truncate-cents",
                lambda inputs: str(
                    (Decimal(inputs["amount"]) * Decimal(inputs["rate"])).quantize(
                        Decimal("0.01")
                    )
                ),
            ),
            SeededDefect(
                "wrong-rate",
                lambda inputs: payment_calculator({**inputs, "rate": "0.10"}),
            ),
        ],
        contract_ref="payments-calculation-contract@1.0.0",
        subject_digest="sha256:subject-revision-001",
    )
    args.output.mkdir(parents=True)
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.output / "RUN-METADATA.json").write_text(
        json.dumps(
            {
                "runner": "scripts/qualify_independent_verifier.py",
                "result_ref": "RESULT.json",
                "scope": "bounded-synthetic-verifier-qualification",
                "authoritative": False,
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"status": result["status"], "output": str(args.output)}))


if __name__ == "__main__":
    main()

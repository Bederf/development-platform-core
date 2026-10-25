import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]


class BootstrapApprovalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((ROOT / "contracts/bootstrap-approval.v1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def document(self) -> dict:
        return {
            "schema": "bootstrap-approval.v1",
            "entity_type": "bootstrap_approval",
            "approval_id": "approval.fixture.001",
            "subject": {
                "semantic_type": "bootstrap_plan",
                "id": "plan.fixture.001",
                "version": "1.0.0",
                "digest": "sha256:" + "a" * 64,
                "project_id": "fixture-project",
            },
            "decision": "approved",
            "issuer": "fixture.operator",
            "authority_binding": {"semantic_type": "approval_authority", "id": "authority.fixture", "version": "1.0.0"},
            "scope": {"scope_type": "project", "scope_id": "fixture-project"},
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "valid_until": None,
            "reason_codes": ["operator_reviewed_plan"],
        }

    def test_fake_approval_is_versioned_and_attributable(self) -> None:
        document = self.document()
        self.validator.validate(document)
        self.assertEqual(document["decision"], "approved")
        self.assertEqual(document["subject"]["semantic_type"], "bootstrap_plan")

    def test_approval_requires_immutable_subject_and_authority(self) -> None:
        for field in ("digest", "project_id"):
            document = self.document()
            del document["subject"][field]
            self.assertTrue(list(self.validator.iter_errors(document)))
        document = self.document()
        del document["authority_binding"]
        self.assertTrue(list(self.validator.iter_errors(document)))

    def test_approval_cannot_smuggle_activation(self) -> None:
        document = copy.deepcopy(self.document())
        document["activated"] = True
        self.assertTrue(list(self.validator.iter_errors(document)))


if __name__ == "__main__":
    unittest.main()

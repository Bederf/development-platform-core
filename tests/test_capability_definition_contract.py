import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
SCHEMA_PATH = ROOT / "contracts" / "capability-definition.v1.schema.json"
EXAMPLE_DIR = ROOT / "examples" / "capability-definition"
EXAMPLE_PATHS = (
    EXAMPLE_DIR / "static-library.json",
    EXAMPLE_DIR / "robotics-controller.json",
)


class CapabilityDefinitionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)
        cls.examples = [
            json.loads(path.read_text(encoding="utf-8")) for path in EXAMPLE_PATHS
        ]

    def assertInvalid(self, instance: dict) -> None:
        self.assertTrue(list(self.validator.iter_errors(instance)))

    def document(self, entity_type: str) -> dict:
        for example in self.examples:
            for document in example["documents"]:
                if document["entity_type"] == entity_type:
                    return copy.deepcopy(document)
        self.fail(f"No example document for {entity_type}")

    def test_examples_are_independent_and_every_document_conforms(self) -> None:
        self.assertEqual(
            {example["example_id"] for example in self.examples},
            {"static-library", "robotics-controller"},
        )
        for example in self.examples:
            for document in example["documents"]:
                self.validator.validate(document)

        serialized = [json.dumps(example, sort_keys=True) for example in self.examples]
        self.assertNotIn("robotics", serialized[0])
        self.assertNotIn("static-library", serialized[1])

    def test_core_profile_catalog_fixture_conforms(self) -> None:
        profile_path = ROOT / "capabilities/profiles/ocr.deterministic.v1.0.0.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        self.validator.validate(profile)
        self.assertEqual(profile["entity_type"], "capability_profile")
        self.assertEqual(profile["base_capability"]["id"], "ocr")

    def test_examples_cover_the_complete_contract_family(self) -> None:
        expected = {
            "capability_definition",
            "capability_profile",
            "capability_relationship",
            "capability_requirement",
            "implementation_descriptor",
            "selection_result",
            "resolution_result",
            "conformance_claim",
            "constraint_reference",
            "risk_assessment_reference",
            "capability_binding",
        }
        actual = {
            document["entity_type"]
            for example in self.examples
            for document in example["documents"]
        }
        self.assertEqual(actual, expected)

    def test_bindings_are_evidence_backed_and_policy_authorized(self) -> None:
        for example in self.examples:
            binding = next(
                document
                for document in example["documents"]
                if document["entity_type"] == "capability_binding"
            )
            dimensions = {
                reference["id"].rsplit(".", 1)[-1]
                for reference in binding["conformance_claims"]
            }
            self.assertEqual(
                dimensions, {"structural", "semantic", "behavioral", "operational"}
            )
            self.assertEqual(
                binding["policy_decision"]["semantic_type"], "policy_decision"
            )

    def test_unknown_platform_semantic_operation_is_rejected(self) -> None:
        document = self.document("capability_definition")
        document["semantic_operations"] = ["Inference"]
        self.assertInvalid(document)

    def test_profile_is_versioned_and_bound_to_a_base_capability(self) -> None:
        profile = self.document("capability_profile")
        self.assertRegex(profile["profile_id"], r"^[a-z0-9][a-z0-9._:-]*$")
        self.assertRegex(profile["version"], r"^[0-9]+\.[0-9]+\.[0-9]+")
        self.assertEqual(profile["base_capability"]["semantic_type"], "capability_definition")
        self.assertTrue(profile["base_capability"]["id"])
        self.assertTrue(profile["additional_responsibilities"] or profile["additional_constraints"])

    def test_profile_cannot_smuggle_activation_authority(self) -> None:
        profile = self.document("capability_profile")
        profile["enabled"] = True
        self.assertInvalid(profile)

    def test_empty_conformance_supports_are_rejected(self) -> None:
        document = self.document("conformance_claim")
        document["supports"] = []
        self.assertInvalid(document)

    def test_selected_outcome_requires_a_candidate(self) -> None:
        document = self.document("selection_result")
        document["outcome"] = "selected"
        document["selected_candidate"] = None
        self.assertInvalid(document)

    def test_declares_provides_requires_an_implementation_source(self) -> None:
        document = self.document("capability_relationship")
        document["source"]["semantic_type"] = "capability_definition"
        self.assertInvalid(document)

    def test_binding_without_policy_decision_is_rejected(self) -> None:
        document = self.document("capability_binding")
        del document["policy_decision"]
        self.assertInvalid(document)

    def test_resolution_cannot_smuggle_authorization(self) -> None:
        document = self.document("resolution_result")
        document["authorized"] = True
        self.assertInvalid(document)


if __name__ == "__main__":
    unittest.main()

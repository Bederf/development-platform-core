import hashlib
import unittest


class FakeReversibleOptimizer:
    """Minimal test double for the proposed reversible optimizer boundary."""

    def __init__(self) -> None:
        self._sources: dict[str, str] = {}

    def project(self, *, source_id: str, content: str, authority: str, trust: str, max_chars: int) -> dict:
        source_digest = hashlib.sha256(content.encode()).hexdigest()
        retrieval_ref = f"source:{source_id}:{source_digest}"
        self._sources[retrieval_ref] = content
        return {
            "source_id": source_id,
            "source_digest": source_digest,
            "projection": content[:max_chars],
            "projection_digest": hashlib.sha256(content[:max_chars].encode()).hexdigest(),
            "retrieval_ref": retrieval_ref,
            "authority": authority,
            "trust": trust,
        }

    def retrieve(self, retrieval_ref: str) -> str:
        return self._sources[retrieval_ref]


class ContextOptimizationConformanceTests(unittest.TestCase):
    def test_projection_is_reversible_and_preserves_source_identity(self) -> None:
        content = "authoritative context " * 100
        optimizer = FakeReversibleOptimizer()
        result = optimizer.project(source_id="fixture", content=content, authority="reference", trust="observed", max_chars=40)

        self.assertLess(len(result["projection"]), len(content))
        self.assertEqual(optimizer.retrieve(result["retrieval_ref"]), content)
        self.assertEqual(result["source_digest"], hashlib.sha256(content.encode()).hexdigest())

    def test_optimizer_does_not_change_authority_or_trust(self) -> None:
        result = FakeReversibleOptimizer().project(
            source_id="fixture", content="content", authority="informational", trust="observed", max_chars=3
        )
        self.assertEqual(result["authority"], "informational")
        self.assertEqual(result["trust"], "observed")

    def test_retrieval_reference_is_required_for_recovery(self) -> None:
        optimizer = FakeReversibleOptimizer()
        result = optimizer.project(source_id="fixture", content="content", authority="reference", trust="observed", max_chars=3)
        with self.assertRaises(KeyError):
            optimizer.retrieve(result["retrieval_ref"] + ":tampered")


if __name__ == "__main__":
    unittest.main()

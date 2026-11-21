import unittest
from scripts.check_source_health import evaluate


class SourceHealthTests(unittest.TestCase):
    def test_unverified_livepocket_is_flagged(self):
        payload = {"sources": {
            "livepocket": {"enabled": False, "discovered": 50, "fetched": 0},
            "animate": {"enabled": False, "errors": ["HTTPError"]},
        }}
        issues = evaluate(payload)
        self.assertTrue(any("zero verified" in issue for issue in issues))
        self.assertTrue(any("animate: disabled" in issue for issue in issues))
        self.assertTrue(any("animate: 1 reported errors" in issue for issue in issues))

    def test_healthy_sources_have_no_warnings(self):
        payload = {"sources": {
            name: {"enabled": True, "fetched": 1, "discovered": 1}
            for name in ("livepocket", "animate", "melonbooks", "x",
                         "mangaoh", "shosen", "ogaki")
        }}
        self.assertEqual(evaluate(payload), [])


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from mcp_newsletter.registries.base import RegistryServerRecord
from mcp_newsletter.registry_state import (
    RegistryMeta, diff_and_events, load_state, write_state,
)


def _rec(identity, conf="high", sources=("official",)):
    return RegistryServerRecord(
        identity=identity, name=identity, write_confidence=conf,
        sources=[{"source": s} for s in sources],
        confidence_by_source={"catalog": {"confidence": conf, "date": "2026-05-30"}},
    )


class StateIoTests(unittest.TestCase):
    def test_jsonl_roundtrip_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry_state.jsonl"
            write_state(path, [_rec("z"), _rec("a")])
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            loaded = load_state(path)
            self.assertEqual(sorted(loaded), ["a", "z"])


class DiffTests(unittest.TestCase):
    def _meta(self, **kw):
        m = RegistryMeta()
        m.seeded_sources = kw.get("seeded", {"official": "2026-05-01"})
        m.liveness = kw.get("liveness", {})
        m.last_discovered = kw.get("last_discovered", {})
        return m

    def test_cold_start_seeds_silently(self):
        meta = RegistryMeta()  # nothing seeded yet
        events, _new_state, new_meta = diff_and_events(
            prior={}, current={"a": _rec("a")}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual(events, [])  # silent baseline
        self.assertIn("official", new_meta.seeded_sources)

    def test_new_write_server_after_baseline(self):
        meta = self._meta()
        events, *_ = diff_and_events(
            prior={}, current={"a": _rec("a")}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual([e["event_type"] for e in events], ["new_write_server"])

    def test_status_changed_low_to_high(self):
        meta = self._meta()
        prior = {"a": _rec("a", conf="low")}
        events, *_ = diff_and_events(
            prior=prior, current={"a": _rec("a", conf="high")}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual([e["event_type"] for e in events], ["write_status_changed"])

    def test_regression_only_on_like_for_like(self):
        meta = self._meta()
        # prior was high via TOOLS; current has no fresh tool evidence -> must NOT regress
        prior_rec = _rec("a", conf="high")
        prior_rec.confidence_by_source = {"tools": {"confidence": "high", "date": "2026-05-20"}}
        cur = _rec("a", conf="low")  # only catalog says low now; tools absent
        cur.confidence_by_source = {"catalog": {"confidence": "low", "date": "2026-05-30"}}
        events, *_ = diff_and_events(
            prior={"a": prior_rec}, current={"a": cur}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual(events, [])  # no regression: evidence sources differ

    def test_regression_fires_on_same_source_drop(self):
        meta = self._meta()
        prior_rec = _rec("a", conf="high")
        prior_rec.confidence_by_source = {"catalog": {"confidence": "high", "date": "2026-05-29"}}
        cur = _rec("a", conf="low")
        cur.confidence_by_source = {"catalog": {"confidence": "low", "date": "2026-05-30"}}
        events, *_ = diff_and_events(
            prior={"a": prior_rec}, current={"a": cur}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertEqual([e["event_type"] for e in events], ["write_status_regressed"])

    def test_delist_after_threshold_when_source_succeeded(self):
        meta = self._meta(liveness={"a": 2})  # already missed twice
        # current is empty; carrying source 'official' succeeded -> 3rd miss -> delist
        events, _ns, new_meta = diff_and_events(
            prior={"a": _rec("a")}, current={}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3,
        )
        self.assertIn("delisted", [e["event_type"] for e in events])

    def test_no_delist_when_carrying_source_failed(self):
        meta = self._meta(liveness={"a": 2})
        events, *_ = diff_and_events(
            prior={"a": _rec("a")}, current={}, run_date="2026-05-30",
            source_ok={"official": False}, meta=meta, delist_runs=3,
        )
        self.assertNotIn("delisted", [e["event_type"] for e in events])

    def test_new_source_when_server_appears_in_additional_registry(self):
        meta = self._meta(seeded={"official": "2026-05-01", "glama": "2026-05-01"})
        prior = {"a": _rec("a", sources=("official",))}
        current = {"a": _rec("a", sources=("official", "glama"))}
        events, *_ = diff_and_events(
            prior=prior, current=current, run_date="2026-05-30",
            source_ok={"official": True, "glama": True}, meta=meta, delist_runs=3,
        )
        new_source = [e for e in events if e["event_type"] == "new_source"]
        self.assertEqual(len(new_source), 1)
        self.assertIn("glama", new_source[0]["summary"])


    def test_new_server_does_not_also_emit_new_source(self):
        meta = self._meta()
        cur = _rec("a", sources=("official", "glama"))
        events, *_ = diff_and_events(prior={}, current={"a": cur}, run_date="2026-05-30",
                                     source_ok={"official": True, "glama": True}, meta=meta, delist_runs=3)
        types = [e["event_type"] for e in events]
        self.assertIn("new_write_server", types)
        self.assertNotIn("new_source", types)

    def test_liveness_resets_when_missed_server_reappears(self):
        meta = self._meta(liveness={"a": 1})
        events, new_state, new_meta = diff_and_events(
            prior={"a": _rec("a")}, current={"a": _rec("a")}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3)
        self.assertNotIn("a", new_meta.liveness)

    def test_delisted_removed_from_state_and_liveness(self):
        meta = self._meta(liveness={"a": 2})
        events, new_state, new_meta = diff_and_events(
            prior={"a": _rec("a")}, current={}, run_date="2026-05-30",
            source_ok={"official": True}, meta=meta, delist_runs=3)
        self.assertIn("delisted", [e["event_type"] for e in events])
        self.assertNotIn("a", new_state)
        self.assertNotIn("a", new_meta.liveness)

    def test_source_down_server_carried_forward_with_frozen_liveness(self):
        meta = self._meta(liveness={})
        events, new_state, new_meta = diff_and_events(
            prior={"a": _rec("a", sources=("glama",))}, current={}, run_date="2026-05-30",
            source_ok={"glama": False}, meta=meta, delist_runs=3)
        self.assertIn("a", new_state)
        self.assertNotIn("delisted", [e["event_type"] for e in events])
        self.assertEqual(new_meta.liveness.get("a", 0), 0)


if __name__ == "__main__":
    unittest.main()

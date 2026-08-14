"""The result envelope: stable shape, stable order, honest verdict."""
from __future__ import annotations

import json
import unittest

from lockscope import engine, report


def site(**overrides) -> engine.LockSite:
    base = dict(
        file="src/lib.rs", function="work", line=10, guard="guard", lock_expr="self.state",
        lock_key="key", family="async", mode="exclusive", origin="source",
        awaits_while_live=1, scope_end_line=20, explicit_drop_line=None,
        last_use_line=19, span_lines=10, evidence="tokio::sync::Mutex",
    )
    base.update(overrides)
    return engine.LockSite(**base)


class EnvelopeTests(unittest.TestCase):
    def build(self, **kwargs):
        one = site()
        analysis = engine.Analysis(
            lock_sites=[one], cycles=[], findings=engine.findings_for([one], []), files_analyzed=1,
        )
        return report.build(analysis, {"rustc": "1.97.1"}, **kwargs)

    def test_the_envelope_carries_what_a_reader_needs(self):
        built = self.build()
        for key in ("schema", "version", "toolchain", "files_analyzed", "lock_sites",
                    "cycles", "findings", "repairs", "refusals", "verification",
                    "timings", "verdict", "unresolved"):
            self.assertIn(key, built)
        self.assertEqual(built["schema"], report.SCHEMA)

    def test_raw_semantic_evidence_is_left_out_unless_asked_for(self):
        self.assertNotIn("evidence", self.build()["lock_sites"][0])
        self.assertIn("evidence", self.build(include_evidence=True)["lock_sites"][0])

    def test_the_text_form_is_stable(self):
        self.assertEqual(report.dumps(self.build()), report.dumps(self.build()))
        self.assertTrue(report.dumps(self.build()).endswith("\n"))

    def test_the_json_is_sorted_so_two_reports_diff_cleanly(self):
        text = report.dumps(self.build())
        keys = list(json.loads(text).keys())
        self.assertEqual(keys, sorted(keys))


class VerdictTests(unittest.TestCase):
    def verdict(self, findings) -> str:
        return report.verdict_for(engine.Analysis(findings=findings))

    def test_nothing_found_is_a_pass(self):
        self.assertEqual(self.verdict([]), report.PASS)

    def test_a_lock_across_an_await_fails(self):
        self.assertEqual(self.verdict([{"kind": "sync_lock_across_await"}]), report.FAIL)

    def test_a_lock_order_cycle_asks_for_a_human(self):
        """No automatic repair exists for an ordering problem, and inventing
        one would reorder locks without proving the invariant still holds."""
        self.assertEqual(self.verdict([{"kind": "lock_order_cycle"}]), report.MANUAL_REVIEW)

    def test_a_wide_critical_section_asks_for_a_human(self):
        self.assertEqual(
            self.verdict([{"kind": "large_exclusive_critical_section"}]), report.MANUAL_REVIEW
        )

    def test_a_cycle_outranks_a_repairable_finding(self):
        self.assertEqual(
            self.verdict([{"kind": "sync_lock_across_await"}, {"kind": "lock_order_cycle"}]),
            report.MANUAL_REVIEW,
        )


class SummaryTests(unittest.TestCase):
    def test_the_summary_leads_with_the_worst_finding(self):
        analysis = engine.Analysis(findings=[
            {"kind": "read_lock_across_await", "severity": "medium", "confidence": "semantic",
             "file": "a.rs", "line": 4, "function": "f"},
            {"kind": "sync_lock_across_await", "severity": "critical", "confidence": "semantic",
             "file": "b.rs", "line": 9, "function": "g"},
        ])
        text = report.summary(report.build(analysis, {}))
        body = [line for line in text.splitlines() if "across_await" in line]
        self.assertIn("sync_lock_across_await", body[0])
        self.assertIn("read_lock_across_await", body[1])

    def test_a_cycle_is_printed_as_a_path(self):
        analysis = engine.Analysis(
            cycles=[["self.a", "self.b"]],
            findings=[{"kind": "lock_order_cycle", "severity": "critical",
                       "confidence": "graph", "cycle": ["self.a", "self.b"]}],
        )
        self.assertIn("self.a -> self.b -> self.a", report.summary(report.build(analysis, {})))

    def test_repairs_and_refusals_are_both_shown(self):
        built = report.build(
            engine.Analysis(),
            {},
            repairs=[{"file": "a.rs", "from_line": 3, "to_line": 5, "guard": "g"}],
            refusals=[{"file": "b.rs", "line": 7, "reason": "branching control flow"}],
        )
        text = report.summary(built)
        self.assertIn("repaired  a.rs:3 -> 5", text)
        self.assertIn("refused   b.rs:7", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

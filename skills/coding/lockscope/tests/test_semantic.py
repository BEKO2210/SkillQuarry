"""The semantic suite: rust-analyzer resolves, the engine judges.

Twenty cases are inherited from the frozen research evaluation, five more cover
the structured-syntax shapes that ended the previous design, and the rest are
production hardening: shapes that were never needed to reach a passing research
verdict and are therefore the ones most likely to be wrong.

The whole crate is analysed once and every case reads from that single result,
because starting the language server is the expensive part and a per-case
restart would turn a fast suite into a slow one without proving anything extra.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import harness
from harness import CASES, require

from lockscope import engine, report, syntax

ACROSS_AWAIT = {"sync_lock_across_await", "exclusive_lock_across_await", "read_lock_across_await"}


class SemanticSuite(unittest.TestCase):
    analysis: engine.Analysis
    repeat: engine.Analysis

    @classmethod
    def setUpClass(cls) -> None:
        require(rust_analyzer=True, cargo=True)
        from lockscope.semantics import RustAnalyzerResolver

        files = [CASES / "src" / name for name in ("lib.rs", "v2_cases.rs", "hardening.rs")]
        with RustAnalyzerResolver(CASES) as resolver:
            cls.analysis = engine.analyze(files, resolver, CASES)
            # A second pass through the same warm server: the analysis has to
            # be a function of the code, not of when it was asked.
            cls.repeat = engine.analyze(files, resolver, CASES)

    def kinds(self, function: str) -> set[str]:
        return self.analysis.kinds_in(function) & ACROSS_AWAIT

    def expect(self, function: str, expected: set[str]) -> None:
        self.assertEqual(self.kinds(function), expected, f"in {function}")

    def sites_in(self, function: str) -> list[engine.LockSite]:
        return [site for site in self.analysis.lock_sites if site.function == function]

    # -- the twenty inherited cases ----------------------------------------

    def test_01_tokio_mutex_held_across_await(self):
        self.expect("tokio_exclusive_live", {"exclusive_lock_across_await"})

    def test_02_a_type_alias_does_not_hide_the_lock(self):
        self.expect("tokio_alias_live", {"exclusive_lock_across_await"})

    def test_03_an_owned_guard_is_still_a_guard(self):
        self.expect("tokio_owned_live", {"exclusive_lock_across_await"})

    def test_04_a_guard_lives_to_the_end_of_its_scope_not_its_last_use(self):
        self.expect("tokio_last_use_only", {"exclusive_lock_across_await"})

    def test_05_an_explicit_drop_ends_the_async_guard(self):
        self.expect("tokio_explicit_drop", set())

    def test_06_an_inner_scope_ends_the_async_guard(self):
        self.expect("tokio_scope", set())

    def test_07_a_read_guard_across_an_await(self):
        self.expect("rw_read_live", {"read_lock_across_await"})

    def test_08_a_write_guard_across_an_await(self):
        self.expect("rw_write_live", {"exclusive_lock_across_await"})

    def test_09_a_std_mutex_across_an_await_is_the_dangerous_one(self):
        self.expect("std_live", {"sync_lock_across_await"})

    def test_10_a_std_guard_also_outlives_its_last_use(self):
        self.expect("std_last_use", {"sync_lock_across_await"})

    def test_11_an_explicit_drop_ends_the_std_guard(self):
        self.expect("std_explicit_drop", set())

    def test_12_an_inner_scope_ends_the_std_guard(self):
        self.expect("std_scope", set())

    def test_13_parking_lot_is_a_sync_lock(self):
        self.expect("parking_live", {"sync_lock_across_await"})

    def test_14_a_multiline_acquisition_is_found(self):
        self.expect("multiline_live", {"exclusive_lock_across_await"})

    def test_15_a_user_defined_lock_method_is_not_a_lock(self):
        self.expect("fake_lock_method", set())

    def test_16_two_locks_in_opposite_order_are_a_cycle(self):
        self.assertIn(["self.a2", "self.b2"], self.analysis.cycles)

    def test_17_three_locks_in_a_ring_are_a_cycle(self):
        self.assertIn(["self.a3", "self.b3", "self.c3"], self.analysis.cycles)

    def test_18_the_same_lock_taken_twice_is_a_cycle(self):
        self.assertIn(["self.self_lock"], self.analysis.cycles)

    def test_19_a_consistent_order_is_not_a_cycle(self):
        self.assertNotIn(["self.left", "self.right"], self.analysis.cycles)

    def test_20_a_macro_generated_acquisition_is_found(self):
        self.expect("macro_generated_live", {"exclusive_lock_across_await"})
        self.assertTrue(any(site.origin == "macro" for site in self.sites_in("macro_generated_live")))

    # -- the five structured-syntax cases ----------------------------------

    def test_21_a_comment_inside_the_chain_changes_nothing(self):
        self.expect("multiline_comment_live", {"exclusive_lock_across_await"})

    def test_22_a_parenthesised_receiver_changes_nothing(self):
        self.expect("parenthesized_live", {"exclusive_lock_across_await"})

    def test_23_arc_clone_with_lock_owned(self):
        self.expect("arc_clone_owned_live", {"exclusive_lock_across_await"})

    def test_24_a_nested_scope_is_quiet_after_it_ends(self):
        self.expect("nested_scope_quiet", set())

    def test_25_a_multiline_std_acquisition_is_found(self):
        self.expect("std_multiline_live", {"sync_lock_across_await"})

    # -- production hardening ---------------------------------------------

    def test_26_comments_between_every_call_in_the_chain(self):
        self.expect("comments_between_calls", {"exclusive_lock_across_await"})

    def test_27_an_await_inside_a_nested_async_block_still_counts(self):
        self.expect("nested_async_block", {"exclusive_lock_across_await"})

    def test_28_a_guard_taken_inside_an_async_move_closure(self):
        self.assertTrue(
            any(site.awaits_while_live >= 1 for site in self.sites_in("async_move_closure")),
            "the guard inside the spawned closure was not seen",
        )

    def test_29_two_overlapping_guards_are_two_findings(self):
        findings = [f for f in self.analysis.findings if f.get("function") == "overlapping_guards"]
        self.assertEqual(len(findings), 2)
        self.assertEqual({f["kind"] for f in findings}, {"exclusive_lock_across_await"})

    def test_30_an_alias_declared_in_a_nested_module(self):
        self.expect("alias_through_module", {"exclusive_lock_across_await"})

    def test_31_a_type_imported_under_another_name(self):
        self.expect("imported_rename", {"exclusive_lock_across_await"})

    def test_32_a_macro_wrapper_around_the_acquisition(self):
        self.expect("macro_wrapper", {"exclusive_lock_across_await"})
        self.assertTrue(any(site.origin == "macro" for site in self.sites_in("macro_wrapper")))

    def test_33_a_shadowed_guard_is_treated_conservatively(self):
        """Shadowing does not release the guard, and the tool does not pretend
        it does: the binding is reported rather than assumed to be gone."""
        self.expect("guard_shadowing", {"exclusive_lock_across_await"})

    def test_34_an_early_return_does_not_hide_the_await(self):
        self.expect("early_return", {"exclusive_lock_across_await"})

    def test_35_only_the_match_arm_that_awaits_is_reported(self):
        findings = [f for f in self.analysis.findings
                    if f.get("function") == "match_arms" and f["kind"] in ACROSS_AWAIT]
        self.assertEqual(len(findings), 1)

    def test_36_a_guard_used_only_as_a_temporary_is_not_a_binding(self):
        """`if let Some(x) = *m.lock().await` binds no guard.

        The guard is a temporary whose lifetime this analysis does not model.
        Reporting nothing here is a stated limitation, not a silent miss — the
        skill documentation says so and this test pins the behaviour.
        """
        self.expect("if_let_scope", set())
        self.expect("while_let_scope", set())

    def test_37_question_mark_propagation_near_a_sync_guard(self):
        self.expect("question_mark_near_scope", {"sync_lock_across_await"})

    def test_38_every_await_point_is_counted(self):
        sites = self.sites_in("multiple_await_points")
        self.assertEqual([site.awaits_while_live for site in sites], [3])

    def test_39_a_read_guard_held_while_a_write_guard_is_taken(self):
        sites = {site.mode for site in self.sites_in("read_then_write")}
        self.assertEqual(sites, {"read", "exclusive"})
        self.assertNotIn(["self.left", "self.right"], self.analysis.cycles)

    def test_40_a_lock_taken_in_a_helper_belongs_to_the_helper(self):
        self.expect("helper", {"exclusive_lock_across_await"})
        self.expect("calls_helper", set())

    def test_41_an_api_that_only_looks_like_a_lock_is_ignored(self):
        self.expect("fake_lock_api", set())

    def test_42_two_locks_with_the_same_field_name_are_not_the_same_lock(self):
        """`AccountState::balance` and `SessionState::balance` are different.

        They are taken in opposite orders, so a cycle is correct — but it must
        be a cycle between two distinct locks. A tool that keyed locks by their
        spelling would report a single self-cycle instead.
        """
        matching = [cycle for cycle in self.analysis.cycles if any("balance" in item for item in cycle)]
        self.assertTrue(matching, self.analysis.cycles)
        for cycle in matching:
            self.assertEqual(len(cycle), 2, f"locks were merged by name: {cycle}")

    # -- properties of the run itself --------------------------------------

    def test_43_the_same_code_analysed_twice_gives_the_same_answer(self):
        first = report.dumps(report.build(self.analysis, {}))
        second = report.dumps(report.build(self.repeat, {}))
        self.assertEqual(first, second)

    def test_44_no_finding_is_reported_without_a_resolved_lock_site(self):
        located = {(site.file, site.line) for site in self.analysis.lock_sites}
        for finding in self.analysis.findings:
            if finding["kind"] == "lock_order_cycle":
                continue
            self.assertIn((finding["file"], finding["line"]), located)

    def test_45_the_structured_extractor_is_what_found_the_candidates(self):
        """No text-shaped fallback is allowed to be the authority.

        Every reported source site must correspond to a candidate the Rust
        grammar produced for that file and line.
        """
        for site in self.analysis.lock_sites:
            if site.origin != "source":
                continue
            path = CASES / site.file
            lines = {c.line for c in syntax.candidates_in(path.read_bytes())}
            self.assertIn(site.line, lines, f"{site.file}:{site.line} is not a structured candidate")


if __name__ == "__main__":
    unittest.main(verbosity=2)

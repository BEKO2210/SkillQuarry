"""Level 1-5 user scenarios, from the simplest happy path to adversarial loops."""

from __future__ import annotations

import unittest

from harness import StrataTestCase, git, handoff
from strata.runner import (
    StrataError, baseline_guard, init_state, load_state, run_loop, save_state,
)


class Level1Beginner(StrataTestCase):
    """One task, one generation, verification really runs and really passes."""

    def test_happy_path_verified_complete(self):
        (self.repo / 'verify.py').write_text('raise SystemExit(0)\n')
        git(self.repo, 'add', 'verify.py')
        git(self.repo, 'commit', '-qm', 'verifier')
        self.set_sequence([{'handoff': handoff('complete', 'done', '',
                                               tests=['verify.py PASS'],
                                               completion_evidence=['implemented and checked'])}])
        cfg = self.config(verify=['python3 verify.py'])
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertTrue(final.completed)
        self.assertEqual(final.phase, 'complete')
        self.assertEqual(final.generation, 1)


class Level2EverydayDeveloper(StrataTestCase):
    """Two fresh generations; only the compact handoff crosses the boundary."""

    def test_handoff_is_injected_into_next_fresh_prompt(self):
        h1 = handoff('continue', 'Found auth race', 'Open auth_test.py first',
                     decisions=['Do not put mutex in interceptor'], read_first=['auth_test.py'])
        h2 = handoff('complete', 'Fixed race', '', tests=['tests pass'],
                     completion_evidence=['race test passes'])
        self.set_sequence([{'handoff': h1}, {'handoff': h2}])
        cfg = self.config()
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        prompts = self.prompts()
        self.assertEqual(len(prompts), 2)
        self.assertIn('Found auth race', prompts[1])
        self.assertIn('Do not put mutex in interceptor', prompts[1])
        self.assertIn('Open auth_test.py first', prompts[1])
        self.assertIn('FRESH conversation context', prompts[1])
        self.assertTrue(final.completed)

    def test_previous_raw_transcript_is_never_injected(self):
        h1 = handoff('continue', 'summary only', 'next step')
        h2 = handoff('complete', 'done', '', completion_evidence=['ok'])
        self.set_sequence([{'handoff': h1}, {'handoff': h2}])
        cfg = self.config()
        run_loop(self.repo, cfg, init_state(self.repo, cfg))
        # Generation 2 must not contain generation 1's own prompt text.
        first, second = self.prompts()
        self.assertNotIn(first, second)

    def test_master_task_precedes_dynamic_state_for_prefix_caching(self):
        cfg = self.config()
        run_loop(self.repo, cfg, init_state(self.repo, cfg), one_generation=True)
        prompt = self.prompts()[0]
        self.assertLess(prompt.index('MASTER TASK'), prompt.index('DYNAMIC GENERATION STATE'))


class Level3Advanced(StrataTestCase):
    """A previous process died mid-generation after edits."""

    def test_crash_recovery_marks_partial_generation_untrusted(self):
        h1 = handoff('continue', 'baseline handoff', 'inspect app.py', read_first=['app.py'])
        cfg = self.config()
        st = init_state(self.repo, cfg)
        st.last_handoff = h1
        st.phase = 'running'  # simulate power/process death after the generation started
        st.generation = 1
        save_state(self.repo, st)
        (self.repo / 'README.md').write_text('partially edited by dead generation\n')

        self.set_sequence([{'handoff': handoff('complete', 'recovered safely', '',
                                               completion_evidence=['inspected partial diff'])}])
        final = run_loop(self.repo, cfg, load_state(self.repo), one_generation=True)
        prompt = self.prompts()[0]
        self.assertIn('stopped/crashed or failed around generation 2', prompt)
        self.assertIn('partially applied', prompt)
        self.assertIn('README.md', prompt)  # navigation signal from live git status
        self.assertIn('baseline handoff', prompt)  # last validated handoff still trusted
        self.assertEqual(final.generation, 2)


class Level4Expert(StrataTestCase):
    """The agent claims COMPLETE too early; independent verification overrules it."""

    def test_false_complete_is_vetoed_by_independent_verification(self):
        (self.repo / 'verify.py').write_text(
            "from pathlib import Path\nraise SystemExit(0 if Path('fixed.flag').exists() else 7)\n"
        )
        git(self.repo, 'add', 'verify.py')
        git(self.repo, 'commit', '-qm', 'verifier')
        premature = handoff('complete', 'I think it is done', '', completion_evidence=['claimed done'])
        repaired = handoff('complete', 'Actually fixed and verified', '',
                           completion_evidence=['fixed.flag present'])
        self.set_sequence([
            {'handoff': premature},
            {'handoff': repaired, 'write': {'fixed.flag': 'ok\n'}},
        ])
        cfg = self.config(verify=['python3 verify.py'])
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        prompts = self.prompts()
        self.assertEqual(final.generation, 2)
        self.assertTrue(final.completed)
        self.assertIn('Independent completion verification failed', prompts[1])
        self.assertIn('Fix the independently verified failures', prompts[1])

    def test_verification_failure_is_persisted_for_inspection(self):
        (self.repo / 'verify.py').write_text('raise SystemExit(3)\n')
        git(self.repo, 'add', 'verify.py')
        git(self.repo, 'commit', '-qm', 'verifier')
        self.set_sequence([{'handoff': handoff('complete', 'claimed', '', completion_evidence=['x'])}])
        cfg = self.config(verify=['python3 verify.py'])
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg), one_generation=True)
        self.assertEqual(final.phase, 'verification_failed')
        report = (self.repo / '.strata' / 'last-verification.json').read_text()
        self.assertIn('"ok": false', report)


class Level5Adversarial(StrataTestCase):
    """Pathological agents: no-progress loops and endless generations."""

    def test_stall_detector_stops_token_burn(self):
        stuck = handoff('continue', 'Still stuck on same issue', 'Try same thing again',
                        blockers=['unknown failure'])
        self.set_sequence([{'handoff': stuck}] * 4)
        cfg = self.config(stall_limit=3, max_generations=10)
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertFalse(final.completed)
        self.assertEqual(final.phase, 'stalled')
        self.assertEqual(final.generation, 3)
        self.assertIn('refusing to burn more tokens', final.last_error)
        self.assertEqual(self.call_count(), 3)

    def test_max_generations_is_a_hard_ceiling(self):
        # Distinct summaries defeat the stall detector, so only the ceiling can stop this.
        self.set_sequence([{'handoff': handoff('continue', f'step {i}', f'do {i}')} for i in range(9)])
        cfg = self.config(max_generations=4, stall_limit=99)
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertEqual(final.phase, 'max_generations')
        self.assertEqual(final.generation, 4)
        self.assertEqual(self.call_count(), 4)

    def test_blocked_status_stops_immediately(self):
        self.set_sequence([{'handoff': handoff('blocked', 'cannot proceed', 'n/a',
                                               blockers=['missing credentials'])}])
        cfg = self.config()
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertEqual(final.phase, 'blocked')
        self.assertEqual(self.call_count(), 1)


class SafetyGuards(StrataTestCase):
    def test_dirty_repo_refused_by_default(self):
        (self.repo / 'README.md').write_text('dirty\n')
        with self.assertRaises(StrataError):
            baseline_guard(self.repo, allow_dirty=False)
        baseline_guard(self.repo, allow_dirty=True)

    def test_runner_state_does_not_make_the_repo_look_dirty(self):
        cfg = self.config()
        init_state(self.repo, cfg)
        baseline_guard(self.repo, allow_dirty=False)


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""Unit and failure-mode coverage for every moving part of the runner."""

from __future__ import annotations

import io
import json
import os
import random
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness import StrataTestCase, git, handoff
import strata.runner as R
from strata.runner import (
    BudgetExhausted, Config, RunLock, RuntimeState, StrataError, TurnLimitReached,
    _bounded_signal, _from_mapping, atomic_write, build_claude_command, build_prompt,
    classify_engine_error, collect_metrics, compact_handoff, ensure_git_exclude,
    ensure_git_repo, extract_handoff, git_diff_stat, git_status, handoff_fingerprint,
    init_state, load_config, load_state, main, reset_state, run_claude_generation,
    run_loop, run_verification, save_state, sha256_text, state_paths, status_report,
    validate_persisted_integrity, verification_failure_handoff,
)


class AtomicWrite(StrataTestCase):
    def test_write_is_atomic_and_leaves_no_temp_files(self):
        target = self.root / 'nested' / 'out.json'
        atomic_write(target, b'{"a": 1}')
        self.assertEqual(target.read_bytes(), b'{"a": 1}')
        atomic_write(target, b'{"a": 2}')
        self.assertEqual(target.read_bytes(), b'{"a": 2}')
        leftovers = [p.name for p in target.parent.iterdir() if p.name.startswith('.out.json.')]
        self.assertEqual(leftovers, [])

    def test_sha256_is_stable(self):
        self.assertEqual(sha256_text('abc'), sha256_text('abc'))
        self.assertNotEqual(sha256_text('abc'), sha256_text('abd'))


class GitSignals(StrataTestCase):
    def test_status_and_diffstat_reflect_real_repository(self):
        self.assertEqual(git_status(self.repo), '')
        (self.repo / 'README.md').write_text('changed\n')
        (self.repo / 'new.txt').write_text('new\n')
        self.assertIn('README.md', git_status(self.repo))
        self.assertIn('new.txt', git_status(self.repo))
        self.assertIn('README.md', git_diff_stat(self.repo))

    def test_diffstat_reports_staged_changes(self):
        (self.repo / 'README.md').write_text('staged change\n')
        git(self.repo, 'add', 'README.md')
        self.assertIn('staged:', git_diff_stat(self.repo))

    def test_diffstat_is_explicit_when_there_is_nothing_to_show(self):
        self.assertEqual(git_diff_stat(self.repo), '<no tracked diff stat>')

    def test_signals_are_bounded(self):
        long_text = "\n".join(f'line {i}' for i in range(500))
        bounded = _bounded_signal(long_text, max_lines=10)
        self.assertIn('490 more lines omitted', bounded)
        self.assertLess(len(bounded.splitlines()), 12)
        self.assertIn('truncated by character budget', _bounded_signal('x' * 5000, max_chars=100))

    def test_status_is_defensive_outside_a_repository(self):
        plain = self.root / 'plain'
        plain.mkdir()
        self.assertEqual(git_status(plain), '<git status unavailable>')

    def test_ensure_git_repo_rejects_non_repository_and_missing_path(self):
        plain = self.root / 'plain2'
        plain.mkdir()
        with self.assertRaises(StrataError):
            ensure_git_repo(plain)
        with self.assertRaises(StrataError):
            ensure_git_repo(self.root / 'does-not-exist')
        ensure_git_repo(self.repo)

    def test_git_exclude_entry_is_written_once(self):
        ensure_git_exclude(self.repo)
        ensure_git_exclude(self.repo)
        exclude = (self.repo / '.git' / 'info' / 'exclude').read_text()
        self.assertEqual(exclude.count('/.strata/'), 1)

    def test_git_exclude_is_a_no_op_outside_a_repository(self):
        plain = self.root / 'plain3'
        plain.mkdir()
        ensure_git_exclude(plain)  # must not raise
        self.assertFalse((plain / '.git').exists())


class Locking(StrataTestCase):
    def test_second_runner_is_refused_while_the_first_holds_the_lock(self):
        lock_path = state_paths(self.repo)['lock']
        with RunLock(lock_path):
            with self.assertRaises(StrataError):
                with RunLock(lock_path):
                    pass
        # Released again afterwards.
        with RunLock(lock_path):
            pass

    def test_lock_file_records_the_owning_pid(self):
        lock_path = state_paths(self.repo)['lock']
        with RunLock(lock_path):
            self.assertIn(f'pid={os.getpid()}', lock_path.read_text())


class StatePersistence(StrataTestCase):
    def test_missing_state_and_config_are_reported_clearly(self):
        with self.assertRaises(StrataError):
            load_state(self.repo)
        with self.assertRaises(StrataError):
            load_config(self.repo)

    def test_corrupted_state_is_reported_instead_of_crashing(self):
        cfg = self.config()
        init_state(self.repo, cfg)
        state_paths(self.repo)['state'].write_text('{ not json')
        with self.assertRaises(StrataError):
            load_state(self.repo)
        state_paths(self.repo)['state'].write_text('[]')
        with self.assertRaises(StrataError):
            load_state(self.repo)

    def test_state_from_a_different_schema_version_is_rejected(self):
        cfg = self.config()
        st = init_state(self.repo, cfg)
        raw = json.loads(state_paths(self.repo)['state'].read_text())
        raw['schema_version'] = 999
        state_paths(self.repo)['state'].write_text(json.dumps(raw))
        with self.assertRaises(StrataError):
            load_state(self.repo)
        self.assertEqual(st.schema_version, R.SCHEMA_VERSION)

    def test_unknown_persisted_keys_are_ignored(self):
        cfg = self.config()
        init_state(self.repo, cfg)
        raw = json.loads(state_paths(self.repo)['state'].read_text())
        raw['field_from_a_future_build'] = True
        state_paths(self.repo)['state'].write_text(json.dumps(raw))
        self.assertEqual(load_state(self.repo).generation, 0)
        cfg_raw = json.loads(state_paths(self.repo)['config'].read_text())
        self.assertIn('repo', cfg_raw)  # written for humans, ignored on load
        self.assertEqual(load_config(self.repo).task, cfg.task)

    def test_from_mapping_drops_unknown_fields(self):
        cfg = _from_mapping(Config, {'task': 't', 'nonsense': 1})
        self.assertEqual(cfg.task, 't')

    def test_integrity_check_refuses_a_mutated_task(self):
        cfg = self.config()
        st = init_state(self.repo, cfg)
        validate_persisted_integrity(cfg, st)
        with self.assertRaises(StrataError):
            validate_persisted_integrity(self.config(task='a different task'), st)

    def test_integrity_check_refuses_impossible_limits(self):
        cfg = self.config()
        st = init_state(self.repo, cfg)
        st.schema_version = 1
        with self.assertRaises(StrataError):
            validate_persisted_integrity(cfg, st)
        st.schema_version = R.SCHEMA_VERSION
        st.generation = -1
        with self.assertRaises(StrataError):
            validate_persisted_integrity(cfg, st)

    def test_reset_removes_only_runner_state(self):
        cfg = self.config()
        init_state(self.repo, cfg)
        self.assertTrue((self.repo / '.strata').exists())
        reset_state(self.repo)
        self.assertFalse((self.repo / '.strata').exists())
        self.assertTrue((self.repo / 'README.md').exists())
        reset_state(self.repo)  # idempotent

    def test_history_survives_corrupt_lines(self):
        cfg = self.config()
        init_state(self.repo, cfg)
        history = state_paths(self.repo)['history']
        history.write_text(
            json.dumps({'event': 'handoff', 'usage': {'total_cost_usd': 0.5, 'usage': {'input_tokens': 10}}}) + '\n'
            + 'this line is not json\n'
            + json.dumps({'event': 'verification'}) + '\n'
            + json.dumps({'event': 'handoff', 'usage': {'total_cost_usd': 0.25, 'usage': {'input_tokens': 5}}}) + '\n'
            + json.dumps(['not', 'an', 'object']) + '\n'
        )
        m = collect_metrics(self.repo)
        self.assertEqual(m['completed_generations'], 2)
        self.assertAlmostEqual(m['total_cost_usd'], 0.75)
        self.assertEqual(m['usage']['input_tokens'], 15.0)

    def test_metrics_without_history_is_zeroed(self):
        self.assertEqual(collect_metrics(self.repo)['completed_generations'], 0)


class HandoffValidation(StrataTestCase):
    def test_missing_structured_output_is_rejected(self):
        with self.assertRaises(StrataError):
            extract_handoff({'session_id': 'x'})
        with self.assertRaises(StrataError):
            extract_handoff({'structured_output': 'not an object'})

    def test_missing_required_fields_are_named(self):
        broken = handoff()
        del broken['tests']
        with self.assertRaisesRegex(StrataError, 'tests'):
            extract_handoff({'structured_output': broken})

    def test_wrong_types_are_rejected(self):
        bad_list = handoff()
        bad_list['blockers'] = 'a string'
        with self.assertRaisesRegex(StrataError, 'blockers'):
            extract_handoff({'structured_output': bad_list})
        mixed_list = handoff()
        mixed_list['completed'] = ['ok', 5]
        with self.assertRaisesRegex(StrataError, 'completed'):
            extract_handoff({'structured_output': mixed_list})
        bad_str = handoff()
        bad_str['summary'] = 42
        with self.assertRaisesRegex(StrataError, 'summary'):
            extract_handoff({'structured_output': bad_str})

    def test_status_values_are_constrained(self):
        bad = handoff()
        bad['status'] = 'almost-done'
        with self.assertRaises(StrataError):
            extract_handoff({'structured_output': bad})

    def test_each_status_must_carry_its_own_evidence(self):
        with self.assertRaises(StrataError):
            extract_handoff({'structured_output': handoff('continue', next_action='   ')})
        with self.assertRaises(StrataError):
            extract_handoff({'structured_output': handoff('complete', next_action='')})
        with self.assertRaises(StrataError):
            extract_handoff({'structured_output': handoff('blocked', next_action='x')})
        ok = extract_handoff({'structured_output': handoff('complete', completion_evidence=['tests pass'])})
        self.assertEqual(ok['status'], 'complete')

    def test_fingerprint_ignores_cosmetic_differences_only(self):
        a = handoff('continue', 'Same Thing', 'Do It')
        b = handoff('continue', '  same thing  ', 'do it')
        c = handoff('continue', 'different', 'do it')
        self.assertEqual(handoff_fingerprint(a), handoff_fingerprint(b))
        self.assertNotEqual(handoff_fingerprint(a), handoff_fingerprint(c))


class Compaction(StrataTestCase):
    def test_small_handoff_passes_through_untouched(self):
        h = handoff()
        self.assertIs(compact_handoff(h, 16000), h)

    def test_oversized_handoff_is_compacted_within_budget(self):
        h = handoff('continue', 'x' * 4000, 'y' * 2000,
                    completed=['c' * 800] * 12, decisions=['d' * 800] * 12,
                    failed_attempts=['f' * 1000] * 8, changed_files=['g' * 400] * 40,
                    read_first=['r' * 400] * 12, tests=['t' * 1000] * 12,
                    blockers=['b' * 1000] * 8, completion_evidence=['e' * 1000] * 12)
        out = compact_handoff(h, 16000)
        self.assertLessEqual(len(json.dumps(out, indent=2, sort_keys=True)) + 1, 16000)
        self.assertEqual(out['status'], 'continue')
        for key in R.LIST_FIELDS:
            self.assertIsInstance(out[key], list)

    def test_impossible_budget_is_an_explicit_error(self):
        with self.assertRaisesRegex(StrataError, 'hard budget'):
            compact_handoff(handoff('continue', 'x' * 4000, 'y' * 2000), 50)

    def test_randomized_handoffs_always_fit_the_budget(self):
        rng = random.Random(20260813)
        for _ in range(500):
            h = handoff(
                rng.choice(['continue', 'complete', 'blocked']),
                'x' * rng.randint(0, 4000),
                'y' * rng.randint(1, 2000),
                completed=['c' * rng.randint(0, 800) for _ in range(rng.randint(0, 12))],
                decisions=['d' * rng.randint(0, 800) for _ in range(rng.randint(0, 12))],
                failed_attempts=['f' * rng.randint(0, 1000) for _ in range(rng.randint(0, 8))],
                changed_files=['g' * rng.randint(0, 400) for _ in range(rng.randint(0, 40))],
                read_first=['r' * rng.randint(0, 400) for _ in range(rng.randint(0, 12))],
                tests=['t' * rng.randint(0, 1000) for _ in range(rng.randint(0, 12))],
                blockers=['b' * rng.randint(0, 1000) for _ in range(rng.randint(0, 8))],
                completion_evidence=['e' * rng.randint(0, 1000) for _ in range(rng.randint(0, 12))],
            )
            out = compact_handoff(h, R.DEFAULT_MAX_HANDOFF_BYTES)
            self.assertLessEqual(len(R._json_bytes(out)), R.DEFAULT_MAX_HANDOFF_BYTES)


class EngineErrorClassification(StrataTestCase):
    def test_turn_limit_is_recognised_from_the_json_envelope(self):
        err = classify_engine_error(1, json.dumps({'subtype': 'error_max_turns', 'is_error': True}), '')
        self.assertIsInstance(err, TurnLimitReached)

    def test_budget_stop_is_recognised(self):
        err = classify_engine_error(1, json.dumps({'subtype': 'error_max_budget_usd'}), '')
        self.assertIsInstance(err, BudgetExhausted)

    def test_other_subtypes_are_reported_verbatim(self):
        err = classify_engine_error(1, json.dumps({'subtype': 'error_during_execution'}), 'boom')
        self.assertNotIsInstance(err, (TurnLimitReached, BudgetExhausted))
        self.assertIn('error_during_execution', str(err))

    def test_non_json_output_still_yields_a_useful_error(self):
        err = classify_engine_error(2, 'segmentation fault', 'stderr detail')
        self.assertIn('stderr detail', str(err))
        self.assertIn('exited 2', str(err))

    def test_stop_reason_is_used_when_subtype_is_absent(self):
        err = classify_engine_error(1, json.dumps({'stop_reason': 'error_max_turns'}), '')
        self.assertIsInstance(err, TurnLimitReached)


class ClaudeInvocation(StrataTestCase):
    def test_command_carries_the_contract_flags(self):
        cfg = self.config(model='haiku', effort='high', max_budget_usd=2.5,
                          claude_args=['--add-dir', '/tmp/extra'])
        cmd = build_claude_command(cfg, 'PROMPT')
        self.assertEqual(cmd[1:3], ['-p', 'PROMPT'])
        for flag in ['--output-format', '--json-schema', '--no-session-persistence',
                     '--max-turns', '--permission-mode', '--model', '--effort', '--max-budget-usd']:
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[-2:], ['--add-dir', '/tmp/extra'])
        schema = json.loads(cmd[cmd.index('--json-schema') + 1])
        self.assertEqual(schema['required'], R.HANDOFF_SCHEMA['required'])

    def test_default_permission_mode_allows_edits(self):
        # Claude Code denies every write in `auto` when headless; see TEST_REPORT.md.
        self.assertEqual(Config(task='t').permission_mode, 'acceptEdits')
        self.assertIn('acceptEdits', build_claude_command(Config(task='t'), 'p'))

    def test_missing_binary_is_reported_clearly(self):
        cfg = self.config(claude_bin=str(self.root / 'no-such-binary'))
        with self.assertRaisesRegex(StrataError, 'binary not found'):
            run_claude_generation(self.repo, cfg, 'prompt')

    def test_invalid_json_from_the_engine_is_reported(self):
        self.set_sequence([{'stdout_raw': 'not json at all'}])
        cfg = self.config()
        with self.assertRaisesRegex(StrataError, 'invalid JSON'):
            run_claude_generation(self.repo, cfg, 'prompt')

    def test_json_that_is_not_an_object_is_rejected(self):
        self.set_sequence([{'stdout_raw': '[1, 2, 3]'}])
        cfg = self.config()
        with self.assertRaisesRegex(StrataError, 'not an object'):
            run_claude_generation(self.repo, cfg, 'prompt')

    def test_timeout_terminates_the_whole_process_group(self):
        self.set_sequence([{'sleep': 60, 'spawn_child': True, 'handoff': handoff()}])
        cfg = self.config(timeout_seconds=2)
        started = time.time()
        with self.assertRaisesRegex(StrataError, 'timed out'):
            run_claude_generation(self.repo, cfg, 'prompt')
        self.assertLess(time.time() - started, 30)
        leftover = subprocess.run(
            ['pgrep', '-f', 'import time; time.sleep(600)'],
            stdout=subprocess.PIPE, text=True, check=False,
        )
        self.assertEqual(leftover.stdout.strip(), '')


class Verification(StrataTestCase):
    def test_multiple_commands_are_all_reported(self):
        (self.repo / 'ok.py').write_text('raise SystemExit(0)\n')
        (self.repo / 'bad.py').write_text('raise SystemExit(4)\n')
        ok, results = run_verification(self.repo, ['python3 ok.py', 'python3 bad.py'])
        self.assertFalse(ok)
        self.assertTrue(results[0]['ok'])
        self.assertFalse(results[1]['ok'])
        self.assertEqual(results[1]['returncode'], 4)

    def test_empty_command_fails_instead_of_passing_silently(self):
        ok, results = run_verification(self.repo, ['   '])
        self.assertFalse(ok)
        self.assertIn('error', results[0])

    def test_shell_mode_supports_pipes_and_chaining(self):
        ok, _ = run_verification(self.repo, ['test -f README.md && echo yes | grep -q yes'], use_shell=True)
        self.assertTrue(ok)
        ok, _ = run_verification(self.repo, ['false || false'], use_shell=True)
        self.assertFalse(ok)

    def test_failure_handoff_keeps_the_agent_working_with_exact_output(self):
        results = [{'command': 'npm test', 'ok': False, 'returncode': 1, 'output_tail': 'AssertionError: nope'}]
        new = verification_failure_handoff(handoff('complete', 'done', '', completion_evidence=['x']), results)
        self.assertEqual(new['status'], 'continue')
        self.assertEqual(new['completion_evidence'], [])
        self.assertIn('AssertionError: nope', ' '.join(new['blockers']))
        self.assertIn('Fix the independently verified failures', new['next_action'])

    def test_failure_handoff_uses_the_error_when_there_is_no_output(self):
        results = [{'command': 'missing-binary', 'ok': False, 'error': 'FileNotFoundError: missing-binary'}]
        new = verification_failure_handoff(handoff('complete', 'done', '', completion_evidence=['x']), results)
        self.assertIn('FileNotFoundError', ' '.join(new['blockers']))


class LoopControl(StrataTestCase):
    def test_turn_limit_produces_a_recovery_note_and_keeps_going(self):
        self.set_sequence([
            {'exit': 1, 'stdout_json': {'subtype': 'error_max_turns'}},
            {'handoff': handoff('complete', 'finished small step', '', completion_evidence=['done'])},
        ])
        cfg = self.config()
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertTrue(final.completed)
        self.assertIn('cut off at the', self.prompts()[1])
        self.assertIn('untrusted', self.prompts()[1])

    def test_repeated_turn_limits_stop_the_loop(self):
        self.set_sequence([{'exit': 1, 'stdout_json': {'subtype': 'error_max_turns'}}] * 5)
        cfg = self.config(turn_limit_strikes=3, max_generations=10)
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertEqual(final.phase, 'turn_limit')
        self.assertEqual(self.call_count(), 3)
        self.assertIn('--max-turns', final.last_error)

    def test_budget_stop_is_not_retried(self):
        self.set_sequence([{'exit': 1, 'stdout_json': {'subtype': 'error_max_budget_usd'}}] * 3)
        cfg = self.config()
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertEqual(final.phase, 'budget_exhausted')
        self.assertEqual(self.call_count(), 1)

    def test_transient_engine_failure_is_retried_with_a_recovery_note(self):
        self.set_sequence([
            {'exit': 7, 'stderr': 'transient network failure'},
            {'handoff': handoff('complete', 'recovered', '', completion_evidence=['ok'])},
        ])
        cfg = self.config()
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertTrue(final.completed)
        self.assertIn('transient network failure', self.prompts()[1])

    def test_three_consecutive_engine_failures_abort(self):
        self.set_sequence([{'exit': 7, 'stderr': 'always broken'}] * 5)
        cfg = self.config()
        with self.assertRaisesRegex(StrataError, 'consecutive Claude engine failures'):
            run_loop(self.repo, cfg, init_state(self.repo, cfg))
        self.assertEqual(self.call_count(), 3)

    def test_one_generation_mode_stops_after_a_single_call(self):
        self.set_sequence([{'handoff': handoff('continue', 'step one', 'step two')}] * 3)
        cfg = self.config()
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg), one_generation=True)
        self.assertEqual(self.call_count(), 1)
        self.assertEqual(final.phase, 'handoff_saved')

    def test_one_generation_mode_stops_after_an_engine_failure(self):
        self.set_sequence([{'exit': 7, 'stderr': 'boom'}] * 3)
        cfg = self.config()
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg), one_generation=True)
        self.assertEqual(final.phase, 'engine_error')
        self.assertEqual(self.call_count(), 1)

    def test_one_generation_mode_stops_after_a_turn_limit(self):
        self.set_sequence([{'exit': 1, 'stdout_json': {'subtype': 'error_max_turns'}}] * 3)
        cfg = self.config()
        final = run_loop(self.repo, cfg, init_state(self.repo, cfg), one_generation=True)
        self.assertEqual(final.phase, 'turn_limit')
        self.assertEqual(self.call_count(), 1)

    def test_malformed_handoff_counts_as_an_engine_failure(self):
        self.set_sequence([{'envelope_extra': {'structured_output': {'status': 'continue'}}}] * 3)
        cfg = self.config()
        with self.assertRaises(StrataError):
            run_loop(self.repo, cfg, init_state(self.repo, cfg))

    def test_usage_telemetry_is_persisted_per_generation(self):
        self.set_sequence([{'handoff': handoff('complete', 'done', '', completion_evidence=['x']),
                            'cost': 0.42, 'input_tokens': 1234, 'output_tokens': 99}])
        cfg = self.config()
        run_loop(self.repo, cfg, init_state(self.repo, cfg))
        m = collect_metrics(self.repo)
        self.assertEqual(m['completed_generations'], 1)
        self.assertAlmostEqual(m['total_cost_usd'], 0.42)
        self.assertEqual(m['usage']['input_tokens'], 1234.0)

    def test_raw_engine_response_is_kept_for_inspection(self):
        self.set_sequence([{'handoff': handoff('complete', 'done', '', completion_evidence=['x'])}])
        cfg = self.config()
        run_loop(self.repo, cfg, init_state(self.repo, cfg))
        raw = json.loads((self.repo / '.strata' / 'last-claude.json').read_text())
        self.assertIn('structured_output', raw)
        self.assertTrue((self.repo / '.strata' / 'last-prompt.txt').exists())

    def test_prompt_states_generation_one_has_no_predecessor(self):
        cfg = self.config()
        st = init_state(self.repo, cfg)
        self.assertIn('<none; this is generation 1>', build_prompt(self.repo, cfg, st))

    def test_recovery_note_is_only_injected_once(self):
        cfg = self.config()
        st = init_state(self.repo, cfg)
        st.phase = 'interrupted'
        save_state(self.repo, st)
        self.set_sequence([
            {'handoff': handoff('continue', 'a', 'b')},
            {'handoff': handoff('complete', 'c', '', completion_evidence=['x'])},
        ])
        run_loop(self.repo, cfg, load_state(self.repo))
        first, second = self.prompts()
        self.assertIn('stopped/crashed', first)
        self.assertNotIn('stopped/crashed', second)


class CommandLine(StrataTestCase):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(list(argv))
        return code, buf.getvalue()

    def test_full_lifecycle_start_status_metrics_reset(self):
        self.set_sequence([{'handoff': handoff('complete', 'done', '', completion_evidence=['ok'])}])
        code, out = self.run_cli('--repo', str(self.repo), 'start', 'do the thing',
                                 '--claude-bin', str(self.fake), '--max-generations', '3')
        self.assertEqual(code, R.EXIT_OK)
        self.assertIn('phase=complete', out)

        code, out = self.run_cli('--repo', str(self.repo), 'status')
        self.assertEqual(code, R.EXIT_OK)
        self.assertEqual(json.loads(out)['phase'], 'complete')

        code, out = self.run_cli('--repo', str(self.repo), 'metrics')
        self.assertEqual(json.loads(out)['completed_generations'], 1)

        code, _ = self.run_cli('--repo', str(self.repo), 'resume')
        self.assertEqual(code, R.EXIT_OK)  # already complete

        code, _ = self.run_cli('--repo', str(self.repo), 'reset')
        self.assertFalse((self.repo / '.strata').exists())

    def test_status_report_includes_the_version(self):
        cfg = self.config()
        init_state(self.repo, cfg)
        self.assertEqual(status_report(self.repo)['strata_version'], R.__version__)

    def test_start_refuses_a_dirty_repository(self):
        (self.repo / 'README.md').write_text('dirty\n')
        code, _ = self.run_cli('--repo', str(self.repo), 'start', 'task', '--claude-bin', str(self.fake))
        self.assertEqual(code, R.EXIT_ERROR)

    def test_start_accepts_a_dirty_repository_when_told_to(self):
        (self.repo / 'README.md').write_text('dirty\n')
        self.set_sequence([{'handoff': handoff('complete', 'done', '', completion_evidence=['ok'])}])
        code, _ = self.run_cli('--repo', str(self.repo), 'start', 'task',
                               '--claude-bin', str(self.fake), '--allow-dirty')
        self.assertEqual(code, R.EXIT_OK)

    def test_start_refuses_to_overwrite_existing_state(self):
        self.set_sequence([{'handoff': handoff('continue', 'a', 'b')}])
        self.run_cli('--repo', str(self.repo), 'start', 'task',
                     '--claude-bin', str(self.fake), '--one-generation')
        code, _ = self.run_cli('--repo', str(self.repo), 'start', 'another task',
                               '--claude-bin', str(self.fake))
        self.assertEqual(code, R.EXIT_ERROR)

    def test_resume_continues_from_persisted_state(self):
        self.set_sequence([
            {'handoff': handoff('continue', 'first step', 'second step')},
            {'handoff': handoff('complete', 'second step done', '', completion_evidence=['ok'])},
        ])
        code, _ = self.run_cli('--repo', str(self.repo), 'start', 'task',
                               '--claude-bin', str(self.fake), '--one-generation')
        self.assertEqual(code, R.EXIT_OK)
        code, out = self.run_cli('--repo', str(self.repo), 'resume')
        self.assertEqual(code, R.EXIT_OK)
        self.assertIn('phase=complete', out)
        self.assertIn('first step', self.prompts()[1])

    def test_resume_refuses_a_mutated_task(self):
        self.set_sequence([{'handoff': handoff('continue', 'a', 'b')}])
        self.run_cli('--repo', str(self.repo), 'start', 'task',
                     '--claude-bin', str(self.fake), '--one-generation')
        cfg_path = state_paths(self.repo)['config']
        cfg_obj = json.loads(cfg_path.read_text())
        cfg_obj['task'] = 'a task nobody agreed to'
        cfg_path.write_text(json.dumps(cfg_obj))
        code, _ = self.run_cli('--repo', str(self.repo), 'resume')
        self.assertEqual(code, R.EXIT_ERROR)

    def test_stopping_without_completion_uses_a_distinct_exit_code(self):
        self.set_sequence([{'handoff': handoff('blocked', 'stuck', 'n/a', blockers=['no credentials'])}])
        code, out = self.run_cli('--repo', str(self.repo), 'start', 'task', '--claude-bin', str(self.fake))
        self.assertEqual(code, R.EXIT_STOPPED_WITHOUT_COMPLETION)
        self.assertIn('phase=blocked', out)

    def test_commands_outside_a_git_repository_fail_cleanly(self):
        plain = self.root / 'plain-cli'
        plain.mkdir()
        code, _ = self.run_cli('--repo', str(plain), 'status')
        self.assertEqual(code, R.EXIT_ERROR)

    def test_status_without_state_fails_cleanly(self):
        code, _ = self.run_cli('--repo', str(self.repo), 'status')
        self.assertEqual(code, R.EXIT_ERROR)

    def test_verify_flag_is_wired_through_to_the_config(self):
        (self.repo / 'verify.py').write_text('raise SystemExit(0)\n')
        git(self.repo, 'add', 'verify.py')
        git(self.repo, 'commit', '-qm', 'verifier')
        self.set_sequence([{'handoff': handoff('complete', 'done', '', completion_evidence=['ok'])}])
        code, _ = self.run_cli('--repo', str(self.repo), 'start', 'task',
                               '--claude-bin', str(self.fake), '--verify', 'python3 verify.py')
        self.assertEqual(code, R.EXIT_OK)
        self.assertEqual(load_config(self.repo).verify, ['python3 verify.py'])

    def test_version_flag_exits_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            main(['--version'])
        self.assertEqual(ctx.exception.code, 0)

    def test_keyboard_interrupt_is_reported_as_an_interrupt(self):
        original = R.run_loop

        def interrupt(*a, **kw):
            raise KeyboardInterrupt()

        R.run_loop = interrupt
        try:
            code, _ = self.run_cli('--repo', str(self.repo), 'start', 'task', '--claude-bin', str(self.fake))
        finally:
            R.run_loop = original
        self.assertEqual(code, R.EXIT_INTERRUPTED)

    def test_interrupt_during_a_generation_marks_the_state(self):
        original = R.run_claude_generation

        def interrupt(*a, **kw):
            raise KeyboardInterrupt()

        R.run_claude_generation = interrupt
        cfg = self.config()
        st = init_state(self.repo, cfg)
        try:
            with self.assertRaises(KeyboardInterrupt):
                run_loop(self.repo, cfg, st)
        finally:
            R.run_claude_generation = original
        self.assertEqual(load_state(self.repo).phase, 'interrupted')


class FallbackPaths(StrataTestCase):
    """Rarely taken branches: degraded filesystems, missing fcntl, stubborn children."""

    def test_write_still_succeeds_when_the_directory_cannot_be_fsynced(self):
        real_open = R.os.open

        def no_dir_fsync(path, flags, *a, **kw):
            if flags & getattr(os, 'O_DIRECTORY', 0):
                raise OSError('directory fsync unsupported')
            return real_open(path, flags, *a, **kw)

        R.os.open = no_dir_fsync
        try:
            target = self.root / 'degraded.json'
            atomic_write(target, b'{}')
        finally:
            R.os.open = real_open
        self.assertEqual(target.read_bytes(), b'{}')

    def test_failed_replace_leaves_no_temp_file_behind(self):
        real_replace = R.os.replace

        def broken(*a, **kw):
            raise OSError('disk full')

        target = self.root / 'replace.json'
        R.os.replace = broken
        try:
            with self.assertRaises(OSError):
                atomic_write(target, b'{}')
        finally:
            R.os.replace = real_replace
        self.assertEqual([p for p in self.root.iterdir() if p.name.startswith('.replace.json.')], [])

    def test_terminating_an_already_finished_process_is_a_no_op(self):
        proc = subprocess.Popen([sys.executable, '-c', 'pass'])
        proc.wait()
        R._terminate_process_tree(proc)  # must not raise

    def test_termination_escalates_and_never_raises(self):
        class Unkillable:
            pid = 2 ** 30  # no such process group

            def poll(self):
                return None

            def wait(self, timeout=None):
                raise RuntimeError('will not die')

            def terminate(self):
                raise RuntimeError('will not die')

            def kill(self):
                raise RuntimeError('will not die')

        R._terminate_process_tree(Unkillable())  # must not raise

    def test_interrupt_during_a_generation_kills_the_child(self):
        killed = []

        class FakePopen:
            def __init__(self, *a, **kw):
                pass

            def communicate(self, timeout=None):
                raise KeyboardInterrupt()

            def poll(self):
                killed.append(True)
                return 0

        real_popen = R.subprocess.Popen
        R.subprocess.Popen = FakePopen
        try:
            with self.assertRaises(KeyboardInterrupt):
                R._run_managed(['whatever'], self.repo, 5)
        finally:
            R.subprocess.Popen = real_popen
        self.assertTrue(killed)

    def test_lock_falls_back_when_fcntl_is_unavailable(self):
        lock_path = state_paths(self.repo)['lock']
        original = sys.modules.get('fcntl', 'absent')
        sys.modules['fcntl'] = None  # makes `import fcntl` raise ImportError
        try:
            with RunLock(lock_path):
                with self.assertRaises(StrataError):
                    with RunLock(lock_path):
                        pass
            self.assertFalse(lock_path.with_suffix('.owner').exists())
        finally:
            if original == 'absent':
                del sys.modules['fcntl']
            else:
                sys.modules['fcntl'] = original

    def test_unremovable_owner_marker_does_not_break_release(self):
        lock_path = state_paths(self.repo)['lock']
        marker = lock_path.with_suffix('.owner')
        marker.mkdir(parents=True)
        (marker / 'blocker').write_text('x')
        with RunLock(lock_path):
            pass
        self.assertTrue(marker.exists())

    def test_exclude_file_without_trailing_newline_is_extended_safely(self):
        exclude = self.repo / '.git' / 'info' / 'exclude'
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text('*.tmp')  # no trailing newline
        ensure_git_exclude(self.repo)
        text = exclude.read_text()
        self.assertIn('*.tmp\n', text)
        self.assertIn('/.strata/\n', text)

    def test_metrics_skips_entries_with_an_unexpected_usage_shape(self):
        init_state(self.repo, self.config())
        state_paths(self.repo)['history'].write_text(
            json.dumps({'event': 'handoff', 'usage': 'not a dict'}) + '\n'
        )
        self.assertEqual(collect_metrics(self.repo)['completed_generations'], 1)

    def test_stop_reason_is_printed_to_stderr(self):
        stuck = handoff('continue', 'same', 'same')
        self.set_sequence([{'handoff': stuck}] * 4)
        err = io.StringIO()
        from contextlib import redirect_stderr
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = main(['--repo', str(self.repo), 'start', 'task',
                         '--claude-bin', str(self.fake), '--stall-limit', '2'])
        self.assertEqual(code, R.EXIT_STOPPED_WITHOUT_COMPLETION)
        self.assertIn('refusing to burn more tokens', err.getvalue())


class PackagingSmoke(StrataTestCase):
    def test_module_entry_point_runs(self):
        cp = subprocess.run(
            [sys.executable, '-m', 'strata', '--version'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
            check=False,
        )
        self.assertEqual(cp.returncode, 0)
        self.assertIn(R.__version__, cp.stdout)

    def test_console_script_wrapper_runs(self):
        cp = subprocess.run(
            [sys.executable, '-c', 'from strata.cli import run; raise SystemExit(run())', '--version'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
            check=False,
        )
        self.assertEqual(cp.returncode, 0)

    def test_installer_and_uninstaller_round_trip(self):
        skill_root = Path(__file__).resolve().parents[1]
        prefix = self.root / 'prefix'
        env = {**os.environ, 'STRATA_PREFIX': str(prefix)}
        cp = subprocess.run(['bash', str(skill_root / 'install.sh')], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(cp.returncode, 0, cp.stdout)
        self.assertIn('Self-check: PASS', cp.stdout)
        launcher = prefix / 'bin' / 'strata'
        self.assertTrue(launcher.exists())
        run = subprocess.run([str(launcher), '--version'], stdout=subprocess.PIPE, text=True, check=False)
        self.assertIn(R.__version__, run.stdout)
        cp = subprocess.run(['bash', str(skill_root / 'uninstall.sh')], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(cp.returncode, 0, cp.stdout)
        self.assertFalse(launcher.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)

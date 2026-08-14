# RanGate Review Card

Use this file to independently challenge the skill. Do not trust the prose if the commands disagree.

Reference packaged-skill run: `31762243434`

Reference jobs:

- Linux stable: `94650865969`
- macOS stable: `94650866046`
- Miri: `94650865921`

| Claim | Evidence | Verification command | Expected result |
|---|---|---|---|
| Skill contract is structurally complete | `tests/run_tests.py::test_02_skill_contract_and_size` | `python3 tests/run_tests.py` | 14 tests pass |
| Installer is repeatable and preserves user-added files | `test_04_installer_round_trip_is_idempotent_and_non_destructive` | `python3 tests/run_tests.py` | installer test passes |
| Fixture has no third-party Rust dependencies | `test_05_fixture_has_no_third_party_dependencies` | `python3 tests/run_tests.py` | dependency test passes |
| Unsafe operations remain explicit | crate lint + independent RUSTFLAGS gate | `cd tests/fixture && RUSTFLAGS="-Dunsafe_op_in_unsafe_fn" cargo check --all-targets` | exit 0 |
| Stable compiler accepts the safe boundary | Rust fixture | `cd tests/fixture && cargo check --all-targets` | exit 0 |
| Clippy accepts it with warnings denied | Rust fixture | `cd tests/fixture && cargo clippy --all-targets -- -D warnings` | exit 0 |
| Runtime ownership/null/panic/stress cases pass | five unit tests | `cd tests/fixture && cargo test --all-targets -- --nocapture` | 5 passed, 0 failed |
| Invalid ownership/alias/thread programs are rejected | three `compile_fail` doctests | `cd tests/fixture && cargo test --doc` | 3 passed, 0 failed |
| They are rejected **for the stated reason** | `test_14_compile_fail_reasons_are_verified_not_assumed` | `python3 tests/run_tests.py` | each snippet fails with its pinned E-code; a control snippet with an unrelated error does not satisfy it |
| A missing toolchain cannot hide a broken skill | `require()` plus `RANGATE_REQUIRE_TOOLCHAIN=1` in CI | `RANGATE_REQUIRE_TOOLCHAIN=1 python3 tests/run_tests.py` on a machine without cargo | run fails instead of skipping |
| Optimized build preserves the tested behavior | release suite | `cd tests/fixture && cargo test --release --all-targets` | 5 passed, 0 failed |
| macOS installer and Rust suite work on tested arm64 runner | job `94650866046` | inspect job log or rerun workflow | 14 tests pass |
| Miri executes the supported fixture path | job `94650865921` | inspect job log or rerun workflow | 5 runtime + 3 compile-fail tests pass |
| Generated marketplace registry includes RanGate | `registry/skills.json` | `python3 tools/render_readme.py --check` from repo root | exit 0 |

## Three places to challenge hardest

1. **Error-code enforcement.** On stable, rustdoc ignores the code in
   ```compile_fail,E0382``` entirely — a snippet annotated `E0999` still passes. The
   codes are therefore verified by compiling each snippet with `rustc
   --error-format=json` and reading the emitted codes. Re-check this if that
   verification is ever replaced by the doctest result alone.
2. **Thread contract encoding** — inspect the compile-fail diagnostic. The reference Miri log shows `E0277` from `std::thread::spawn`, including the non-`Send` `Device` constituents. Reject the proof if a future compiler fails the example for an unrelated syntax/import reason.
3. **Miri relevance** — the reference log shows `cargo +nightly-2026-08-13 miri test -- --nocapture` executing all five fixture runtime tests, including the 10,000-cycle test, followed by three compile-fail doctests. Re-check this after changing the nightly pin or fixture.
4. **Installer portability** — the reference matrix passed install → reinstall → uninstall on Ubuntu and macOS arm64, with a custom path containing spaces and an unrelated file preserved. Intel macOS remains untested and should be targeted if that platform becomes a requirement.

## Reviewer stop conditions

Reject or downgrade the skill if any of these occur:

- a compile-fail test passes because the example is malformed for an unrelated reason;
- Miri is reported as green without executing the fixture tests;
- the installer overwrites or deletes an unrelated user file;
- the skill tells an agent to invent an external FFI contract;
- `unsafe impl Send`/`Sync` is introduced without a documented external guarantee;
- the README or `skill.json` claims a toolchain/platform result not present in CI logs;
- `python3 tools/render_readme.py --check` reports generated marketplace drift.

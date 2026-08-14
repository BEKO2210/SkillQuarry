# RanGate Review Card

Use this file to independently challenge the skill. Do not trust the prose if the commands disagree.

| Claim | Evidence | Verification command | Expected result |
|---|---|---|---|
| Skill contract is structurally complete | `tests/run_tests.py::test_02_skill_contract_and_size` | `python3 tests/run_tests.py` | 13 tests pass |
| Installer is repeatable and preserves user-added files | `test_04_installer_round_trip_is_idempotent_and_non_destructive` | `python3 tests/run_tests.py` | installer test passes |
| Fixture has no third-party Rust dependencies | `test_05_fixture_has_no_third_party_dependencies` | `python3 tests/run_tests.py` | dependency test passes |
| Unsafe operations remain explicit | crate lint + independent RUSTFLAGS gate | `cd tests/fixture && RUSTFLAGS="-Dunsafe_op_in_unsafe_fn" cargo check --all-targets` | exit 0 |
| Stable compiler accepts the safe boundary | Rust fixture | `cd tests/fixture && cargo check --all-targets` | exit 0 |
| Clippy accepts it with warnings denied | Rust fixture | `cd tests/fixture && cargo clippy --all-targets -- -D warnings` | exit 0 |
| Runtime ownership/null/panic/stress cases pass | five unit tests | `cd tests/fixture && cargo test --all-targets -- --nocapture` | 5 passed, 0 failed |
| Invalid ownership/alias/thread programs are rejected | three `compile_fail` doctests | `cd tests/fixture && cargo test --doc` | 3 passed, 0 failed |
| Optimized build preserves the tested behavior | release suite | `cd tests/fixture && cargo test --release --all-targets` | 5 passed, 0 failed |
| Miri accepts the supported fixture path | pinned-nightly CI job | inspect `.github/workflows/rangate-tests.yml` and its completed run | Miri job exits 0 |

## Three places to challenge hardest

1. **Thread contract encoding** — verify that the `PhantomData<Rc<()>>` choice really makes `Device` non-`Send`/non-`Sync` on the tested toolchain and that the compile-fail test fails for the intended reason rather than an unrelated syntax/import error.
2. **Miri relevance** — inspect the Miri logs and confirm the five fixture runtime tests actually execute under Miri; do not accept a job that merely installs the component.
3. **Installer portability** — run install → reinstall → uninstall on real macOS Bash as well as Linux, using a `RANGATE_SKILLS_DIR` path containing spaces. Confirm only RanGate-managed files are removed.

## Reviewer stop conditions

Reject or downgrade the skill if any of these occur:

- a compile-fail test passes because the example is malformed for an unrelated reason;
- Miri is reported as green without executing the fixture tests;
- the installer overwrites or deletes an unrelated user file;
- the skill tells an agent to invent an external FFI contract;
- `unsafe impl Send`/`Sync` is introduced without a documented external guarantee;
- the README or `skill.json` claims a toolchain/platform result not present in CI logs.

# Contributing to SkillQuarry

Thanks for wanting to add to the quarry. This page is short on purpose: the
binding rules live in [`docs/SKILL-SPEC.md`](docs/SKILL-SPEC.md), and CI enforces
them so review can be about substance instead of formatting.

By contributing you agree that your work is licensed under
[Apache-2.0](LICENSE), and you are expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## The one-minute version

```bash
git clone https://github.com/BEKO2210/SkillQuarry.git
cd SkillQuarry

python3 tools/validate_skills.py        # manifests against registry/schema.json
python3 tools/render_readme.py --check  # README and registry in sync
python3 tools/test_render_readme.py     # tests for the generator
python3 tools/test_validate_skills.py   # tests for the validator
python3 tools/test_new_skill.py         # tests for the scaffolder and the template

cd skills/autonomous/strata && python3 tests/run_tests.py --min 100
cd ../../security/cordon   && python3 tests/run_tests.py --min 100
```

No installation step, no virtual environment, no packages. Python 3.10+ and
`git` are the only requirements — that is a rule for the repository itself, not
just for skills.

## Adding a skill

1. Scaffold it from the reference skill — that is the fastest correct start:

   ```bash
   python3 tools/new_skill.py --name my-skill --display "My Skill" --category testing
   ```

   The result already validates and passes a 100% coverage gate. Replace
   `src/<module>/core.py` with your logic and rewrite the tests around it. The
   template itself lives in [`templates/example-skill`](templates/example-skill)
   and is worth reading once before you start.
2. Write `skill.json`. It is the single source of truth: the README table, the
   skill cards, the badge counters and `registry/skills.json` are generated from
   it. Never edit anything between the `SKILLS:*` markers in the root README.
3. Write the code, the tests and `TEST_REPORT.md`. Tests must run offline with
   one command; external programs get a fake binary with the same command-line
   contract.
4. Add `.github/workflows/<name>-tests.yml` so the suite runs on every supported
   Python version and platform.
5. Run `python3 tools/render_readme.py` and commit the regenerated files.

The checklist at the end of the specification is what a reviewer will walk
through.

## Changing an existing skill

- A behaviour change needs a test that fails before it and passes after.
- A fixed defect belongs in that skill's `TEST_REPORT.md`, with cause, fix and
  the command that reproduces it. Defects are not quietly deleted from reports.
- Bump the skill's own version in `skill.json` — major when a user's CLI usage or
  persisted state would break.
- If your change alters test counts or coverage, update `tests` in the manifest;
  CI regenerates the README from it.

## What gets a pull request rejected

- A third-party runtime dependency, or an installer that downloads something.
- A claim in a test report with no command behind it.
- A skill that writes to a user's `.gitignore`, or hides state anywhere other
  than through `.git/info/exclude`.
- Weakening a test, a verifier or a coverage gate to make a run pass.
- Generated README blocks edited by hand.

## Reporting problems

- **Bugs and ideas** — open an issue; the templates ask for the environment and
  the exact command, because that is what makes a report actionable.
- **Security issues** — do not open a public issue. Follow
  [SECURITY.md](SECURITY.md).

## Commit and review style

Commits describe the change and its reason in plain sentences. Pull requests
should say what was verified and how, and name what was deliberately left out.
An honest "not tested on macOS" is worth more than a confident guess — this
repository has already turned one such admission into a real CI finding.

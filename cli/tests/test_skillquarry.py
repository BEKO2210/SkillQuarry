"""Tests for the skillquarry client.

Every install runs the real installer of a real skill into a temporary prefix, and
the install record is redirected to a temporary file, so nothing touches the
developer's machine.
"""

from __future__ import annotations

import collections
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

import skillquarry as sq

QUARRY = Path(__file__).resolve().parents[2]


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = self.root / "prefix"
        state = self.root / "state" / "installed.json"
        self.state_patch = mock.patch.object(sq, "STATE_FILE", state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        # The cache of installed sources follows the state file, or a test run
        # would write into the real home directory.
        self.cache_patch = mock.patch.object(sq, "SOURCE_CACHE", state.parent / "sources")
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sq.main(["--quarry", str(QUARRY), *argv])
        return code, out.getvalue(), err.getvalue()


class QuarryDiscoveryTests(Base):
    def test_explicit_path_wins(self) -> None:
        self.assertEqual(sq.find_quarry(str(QUARRY)), QUARRY)

    def test_environment_variables_are_used_in_order(self) -> None:
        with mock.patch.dict(os.environ, {"SKILLQUARRY_ROOT": str(QUARRY)}, clear=False):
            self.assertEqual(sq.find_quarry(None), QUARRY)
        with mock.patch.dict(os.environ, {"SKILLQUARRY_DEFAULT_ROOT": str(QUARRY)}, clear=False):
            os.environ.pop("SKILLQUARRY_ROOT", None)
            self.assertEqual(sq.find_quarry(None), QUARRY)

    def test_a_directory_without_a_registry_is_refused(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(sq.QuarryError, "no quarry found"):
                sq.find_quarry(str(self.root))

    def test_unreadable_registry_is_reported(self) -> None:
        broken = self.root / "quarry" / "registry"
        broken.mkdir(parents=True)
        (broken / "skills.json").write_text("{ not json", encoding="utf-8")
        with self.assertRaisesRegex(sq.QuarryError, "cannot read"):
            sq.load_registry(broken.parent)
        (broken / "skills.json").write_text('{"schema_version": 2}', encoding="utf-8")
        with self.assertRaisesRegex(sq.QuarryError, "no skills array"):
            sq.load_registry(broken.parent)


class FilterTests(Base):
    """Every filter is a conjunction; an absent field must never count as a match."""

    def filter(self, skill, **overrides):
        arguments = dict(agent=None, platform=None, category=None, quality=None,
                         offline=False, no_secrets=False, keyword=None)
        arguments.update(overrides)
        return sq.matches(skill, **arguments)

    def test_each_filter_rejects_independently(self) -> None:
        skill = {"name": "x", "compatibility": ["claude-code"], "platforms": ["linux"],
                 "category": "utilities", "quality": "tested",
                 "security": {"network_access": "none", "requires_secrets": False}}
        self.assertTrue(self.filter(skill))
        self.assertFalse(self.filter(skill, agent="codex"))
        self.assertFalse(self.filter(skill, platform="windows"))
        self.assertFalse(self.filter(skill, category="security"))
        self.assertFalse(self.filter(skill, quality="experimental"))
        self.assertFalse(self.filter(skill, keyword="kubernetes"))

    def test_undeclared_security_fields_never_pass_a_safety_filter(self) -> None:
        bare = {"name": "x", "security": {}}
        self.assertFalse(self.filter(bare, no_secrets=True))
        self.assertTrue(self.filter(bare, offline=True))  # network_access absent means none declared


class SearchTests(Base):
    def test_list_shows_every_skill(self) -> None:
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, sq.EXIT_OK)
        for name in ("strata", "cordon", "rangate"):
            self.assertIn(name, out)

    def test_keyword_and_filters_narrow_the_result(self) -> None:
        code, out, _ = self.run_cli("search", "unsafe")
        self.assertEqual(code, sq.EXIT_OK)
        self.assertIn("rangate", out)
        self.assertNotIn("strata", out)

    def test_filters_that_match_nothing_say_so(self) -> None:
        code, out, _ = self.run_cli("search", "--platform", "windows")
        self.assertIn("no skill matches", out)

    def test_json_output_is_machine_readable(self) -> None:
        code, out, _ = self.run_cli("search", "--category", "security", "--json")
        payload = json.loads(out)
        self.assertTrue(all(item["category"] == "security" for item in payload))

    def test_offline_and_no_secret_filters(self) -> None:
        _, out, _ = self.run_cli("search", "--offline")
        self.assertIn("rangate", out)
        self.assertNotIn("cordon", out)
        _, out, _ = self.run_cli("search", "--no-secrets")
        self.assertIn("cordon", out)

    def test_unknown_skill_names_are_listed(self) -> None:
        code, _, err = self.run_cli("info", "nope")
        self.assertEqual(code, sq.EXIT_ERROR)
        self.assertIn("Known:", err)


class InfoTests(Base):
    def test_info_reports_the_security_surface(self) -> None:
        code, out, _ = self.run_cli("info", "rangate")
        self.assertEqual(code, sq.EXIT_OK)
        for expected in ("rangate", "network", "destructive", "checksum", "installed     no"):
            self.assertIn(expected, out)

    def test_info_marks_an_installed_skill_that_drifted(self) -> None:
        sq.save_state({"state_version": sq.STATE_VERSION, "installed": {
            "cordon": {"version": "0.9.0", "checksum": "sha256:stale", "prefix": None},
        }})
        _, out, _ = self.run_cli("info", "cordon")
        self.assertIn("installed     0.9.0", out)
        self.assertIn("skillquarry update", out)


class InstallTests(Base):
    def test_install_verifies_then_runs_the_real_installer(self) -> None:
        code, out, err = self.run_cli("install", "strata", "--prefix", str(self.prefix))
        self.assertEqual(code, sq.EXIT_OK, err)
        self.assertIn("installed strata", out)
        launcher = self.prefix / "bin" / "strata"
        self.assertTrue(launcher.is_file())
        version = subprocess.run([str(launcher), "--version"], stdout=subprocess.PIPE, text=True, check=False)
        self.assertIn("strata", version.stdout)

    def test_installing_twice_is_refused_and_force_overrides(self) -> None:
        self.run_cli("install", "strata", "--prefix", str(self.prefix))
        code, _, err = self.run_cli("install", "strata", "--prefix", str(self.prefix))
        self.assertEqual(code, sq.EXIT_ERROR)
        self.assertIn("already installed", err)
        code, _, _ = self.run_cli("install", "strata", "--prefix", str(self.prefix), "--force")
        self.assertEqual(code, sq.EXIT_OK)

    def test_a_tampered_skill_is_never_installed(self) -> None:
        skills = sq.load_registry(QUARRY)
        tampered = [dict(item) for item in skills]
        for item in tampered:
            if item["name"] == "strata":
                item["checksum"] = "sha256:0000"
        with mock.patch.object(sq, "load_registry", return_value=tampered):
            code, _, err = self.run_cli("install", "strata", "--prefix", str(self.prefix))
        self.assertEqual(code, sq.EXIT_ERROR)
        self.assertIn("do not match the registry checksum", err)
        self.assertFalse((self.prefix / "bin" / "strata").exists())

    def test_prefix_without_declared_variable_is_refused(self) -> None:
        skill = sq.find_skill(sq.load_registry(QUARRY), "strata")
        manifest = sq.load_manifest(QUARRY, skill)
        manifest["entrypoints"].pop("prefix_env")
        with self.assertRaisesRegex(sq.QuarryError, "prefix_env"):
            sq.run_installer(QUARRY, skill, manifest, "install", str(self.prefix))

    def test_a_missing_entrypoint_is_reported(self) -> None:
        skill = sq.find_skill(sq.load_registry(QUARRY), "strata")
        with self.assertRaisesRegex(sq.QuarryError, "no uninstall entrypoint"):
            sq.run_installer(QUARRY, skill, {"entrypoints": {}}, "uninstall", None)
        with self.assertRaisesRegex(sq.QuarryError, "is missing"):
            sq.run_installer(QUARRY, skill, {"entrypoints": {"install": "nope.sh"}}, "install", None)

    def test_a_failing_installer_is_not_recorded(self) -> None:
        failing = subprocess.CompletedProcess(["bash"], 1, "boom", None)
        with mock.patch.object(sq, "run_installer", return_value=failing):
            code, _, err = self.run_cli("install", "strata", "--prefix", str(self.prefix))
        self.assertEqual(code, sq.EXIT_ERROR)
        self.assertIn("installer failed", err)
        self.assertEqual(sq.load_state()["installed"], {})

    def test_uninstall_runs_the_real_uninstaller_and_forgets_the_skill(self) -> None:
        self.run_cli("install", "strata", "--prefix", str(self.prefix))
        code, out, err = self.run_cli("uninstall", "strata")
        self.assertEqual(code, sq.EXIT_OK, err)
        self.assertIn("uninstalled strata", out)
        self.assertFalse((self.prefix / "bin" / "strata").exists())
        self.assertEqual(sq.load_state()["installed"], {})

    def test_a_failing_uninstaller_keeps_the_record(self) -> None:
        self.run_cli("install", "strata", "--prefix", str(self.prefix))
        failing = subprocess.CompletedProcess(["bash"], 1, "cannot remove", None)
        with mock.patch.object(sq, "run_installer", return_value=failing):
            code, _, err = self.run_cli("uninstall", "strata")
        self.assertEqual(code, sq.EXIT_ERROR)
        self.assertIn("uninstaller failed", err)
        self.assertIn("strata", sq.load_state()["installed"])

    def test_uninstalling_something_unknown_is_refused(self) -> None:
        code, _, err = self.run_cli("uninstall", "strata")
        self.assertEqual(code, sq.EXIT_ERROR)
        self.assertIn("not recorded as installed", err)

    def test_a_skill_installed_without_a_prefix_uses_its_own_default(self) -> None:
        # The rangate installer honours RANGATE_SKILLS_DIR; passing it explicitly
        # keeps the test off the developer's real ~/.claude directory.
        code, _, err = self.run_cli("install", "rangate", "--prefix", str(self.prefix))
        self.assertEqual(code, sq.EXIT_OK, err)
        self.assertTrue((self.prefix / "rangate" / "SKILL.md").is_file())


class RemovalWithoutACheckoutTests(Base):
    """A skill installed from a URL must be removable on a machine without one."""

    def test_the_installer_files_are_kept_so_the_skill_can_be_removed(self):
        self.run_cli("install", "cordon", "--prefix", str(self.prefix))
        record = sq.load_state()["installed"]["cordon"]
        kept = Path(record["source"])
        self.assertTrue((kept / "skill.json").is_file())
        # No checkout is passed here: the cached copy has to carry the removal.
        sq.uninstall(None, "cordon")
        self.assertFalse((self.prefix / "bin" / "cordon").exists())
        self.assertNotIn("cordon", sq.load_state()["installed"])
        self.assertFalse(kept.exists())

    def test_an_older_record_without_a_copy_falls_back_to_the_checkout(self):
        self.run_cli("install", "cordon", "--prefix", str(self.prefix))
        state = sq.load_state()
        kept = Path(state["installed"]["cordon"].pop("source"))
        shutil.rmtree(kept.parent)
        sq.save_state(state)
        sq.uninstall(QUARRY, "cordon")
        self.assertFalse((self.prefix / "bin" / "cordon").exists())

    def test_removal_says_so_when_neither_copy_nor_checkout_is_left(self):
        self.run_cli("install", "cordon", "--prefix", str(self.prefix))
        state = sq.load_state()
        shutil.rmtree(Path(state["installed"]["cordon"]["source"]).parent)
        sq.save_state(state)
        with self.assertRaisesRegex(sq.QuarryError, "no checkout to fall back on"):
            sq.uninstall(None, "cordon")


class UpdateTests(Base):
    def _install_then_age(self) -> None:
        self.run_cli("install", "cordon", "--prefix", str(self.prefix))
        state = sq.load_state()
        state["installed"]["cordon"]["checksum"] = "sha256:older"
        state["installed"]["cordon"]["version"] = "0.9.0"
        sq.save_state(state)

    def test_nothing_to_do_is_stated_plainly(self) -> None:
        self.run_cli("install", "cordon", "--prefix", str(self.prefix))
        code, out, _ = self.run_cli("update")
        self.assertEqual(code, sq.EXIT_OK)
        self.assertIn("up to date", out)

    def test_drift_is_detected_and_reinstalled(self) -> None:
        self._install_then_age()
        code, out, err = self.run_cli("update")
        self.assertEqual(code, sq.EXIT_OK, err)
        self.assertIn("cordon: 0.9.0 -> 1.0.0", out)
        self.assertIn("updated cordon", out)
        self.assertEqual(sq.load_state()["installed"]["cordon"]["version"], "1.0.0")

    def test_dry_run_changes_nothing(self) -> None:
        self._install_then_age()
        code, out, _ = self.run_cli("update", "--dry-run")
        self.assertEqual(code, sq.EXIT_OK)
        self.assertIn("cordon: 0.9.0 -> 1.0.0", out)
        self.assertEqual(sq.load_state()["installed"]["cordon"]["version"], "0.9.0")

    def test_a_single_skill_can_be_targeted(self) -> None:
        self._install_then_age()
        code, out, _ = self.run_cli("update", "strata")
        self.assertIn("up to date", out)

    def test_a_skill_that_left_the_quarry_is_ignored_not_crashed_on(self) -> None:
        sq.save_state({"state_version": sq.STATE_VERSION, "installed": {
            "ghost": {"version": "1.0.0", "checksum": "sha256:x", "prefix": None},
        }})
        self.assertEqual(sq.outdated(QUARRY), [])


class StateTests(Base):
    def test_a_corrupt_record_is_reported_not_ignored(self) -> None:
        sq.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        sq.STATE_FILE.write_text("{ not json", encoding="utf-8")
        with self.assertRaisesRegex(sq.QuarryError, "unreadable"):
            sq.load_state()
        sq.STATE_FILE.write_text('{"state_version": 99, "installed": {}}', encoding="utf-8")
        with self.assertRaisesRegex(sq.QuarryError, "unsupported format"):
            sq.load_state()

    def test_writes_are_atomic_and_leave_no_temp_file(self) -> None:
        sq.save_state({"state_version": sq.STATE_VERSION, "installed": {}})
        sq.save_state({"state_version": sq.STATE_VERSION, "installed": {"x": {}}})
        self.assertEqual(sq.load_state()["installed"], {"x": {}})
        leftovers = [p for p in sq.STATE_FILE.parent.iterdir() if p.name.startswith(".installed.json.")]
        self.assertEqual(leftovers, [])

    def test_a_failed_replace_leaves_no_temp_file(self) -> None:
        real_replace = sq.os.replace
        sq.os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            with self.assertRaises(OSError):
                sq.atomic_write_json(self.root / "out.json", {})
        finally:
            sq.os.replace = real_replace
        self.assertEqual([p for p in self.root.iterdir() if p.name.startswith(".out.json.")], [])


class ChecksumTests(Base):
    def test_client_and_registry_agree_on_every_skill(self) -> None:
        for skill in sq.load_registry(QUARRY):
            with self.subTest(skill=skill["name"]):
                self.assertEqual(sq.skill_checksum(QUARRY / skill["path"]), skill["checksum"])

    def test_build_output_and_caches_are_excluded(self) -> None:
        directory = self.root / "skill"
        (directory / "src").mkdir(parents=True)
        (directory / "src" / "core.py").write_text("X = 1\n", encoding="utf-8")
        before = sq.skill_checksum(directory)
        (directory / "__pycache__").mkdir()
        (directory / "__pycache__" / "core.pyc").write_bytes(b"\x00")
        (directory / "src" / "core.pyo").write_bytes(b"\x00")
        self.assertEqual(before, sq.skill_checksum(directory))

    def test_a_missing_directory_is_reported(self) -> None:
        with self.assertRaisesRegex(sq.QuarryError, "does not exist"):
            sq.verify_skill(QUARRY, {"name": "ghost", "path": "skills/none/ghost", "checksum": "sha256:x"})

    def test_manifest_read_errors_are_reported(self) -> None:
        with self.assertRaisesRegex(sq.QuarryError, "cannot read"):
            sq.load_manifest(QUARRY, {"name": "ghost", "path": "skills/none/ghost"})


class ValidateTests(Base):
    def test_validate_delegates_to_the_quarry_validator(self) -> None:
        code, out, _ = self.run_cli("validate", str(QUARRY / "skills" / "security" / "cordon"))
        self.assertEqual(code, sq.EXIT_OK)
        self.assertIn("manifests valid", out)

    def test_a_directory_without_a_manifest_is_refused(self) -> None:
        code, _, err = self.run_cli("validate", str(self.root))
        self.assertEqual(code, sq.EXIT_ERROR)
        self.assertIn("contains no skill.json", err)

    def test_a_quarry_without_the_validator_is_reported(self) -> None:
        with self.assertRaisesRegex(sq.QuarryError, "no tools/validate_skills.py"):
            sq.command_validate(self.root, self.root)

    def test_a_failing_validator_is_surfaced(self) -> None:
        failing = subprocess.CompletedProcess(["python3"], 1, "FAIL something", None)
        with mock.patch.object(sq.subprocess, "run", return_value=failing):
            with redirect_stdout(io.StringIO()):
                code = sq.command_validate(QUARRY, QUARRY / "skills" / "security" / "cordon")
        self.assertEqual(code, sq.EXIT_MISMATCH)


class DoctorTests(Base):
    def test_doctor_reports_the_environment_and_the_quarry(self) -> None:
        code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, sq.EXIT_OK)
        for expected in ("python", "git", "registry", "checksum:strata", "install record", "PATH"):
            self.assertIn(expected, out)

    def test_doctor_warns_about_missing_binaries(self) -> None:
        with mock.patch.object(sq.shutil, "which", side_effect=lambda name: None if name == "cargo" else "/usr/bin/" + name):
            rows = sq.diagnose(QUARRY)
        warnings = [row for row in rows if row[0] == "warn" and row[1].startswith("requires:")]
        self.assertTrue(warnings)
        self.assertIn("cargo", warnings[0][2])

    def test_doctor_fails_when_a_checksum_drifted(self) -> None:
        tampered = [dict(item) for item in sq.load_registry(QUARRY)]
        tampered[0]["checksum"] = "sha256:0000"
        with mock.patch.object(sq, "load_registry", return_value=tampered):
            code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, sq.EXIT_MISMATCH)
        self.assertIn("FAIL", out)

    def test_doctor_reports_an_unreadable_registry_and_stops(self) -> None:
        with mock.patch.object(sq, "load_registry", side_effect=sq.QuarryError("broken")):
            rows = sq.diagnose(QUARRY)
        self.assertEqual(rows[-1][0], "fail")

    def test_doctor_reports_a_broken_install_record_and_stops(self) -> None:
        with mock.patch.object(sq, "load_state", side_effect=sq.QuarryError("bad record")):
            rows = sq.diagnose(QUARRY)
        self.assertEqual(rows[-1][:2], ("fail", "install record"))

    def test_doctor_lists_outdated_installs(self) -> None:
        self.run_cli("install", "cordon", "--prefix", str(self.prefix))
        state = sq.load_state()
        state["installed"]["cordon"]["checksum"] = "sha256:older"
        sq.save_state(state)
        _, out, _ = self.run_cli("doctor")
        self.assertIn("outdated:cordon", out)

    def test_doctor_notices_an_unusable_interpreter_or_missing_git(self) -> None:
        with mock.patch.object(sq.shutil, "which", return_value=None):
            rows = sq.diagnose(QUARRY)
        self.assertIn(("fail", "git", "not found in PATH"), rows)
        version = collections.namedtuple("version_info", "major minor micro releaselevel serial")
        with mock.patch.object(sq.sys, "version_info", version(3, 9, 0, "final", 0)):
            rows = sq.diagnose(QUARRY)
        self.assertEqual(rows[0][0], "fail")

    def test_doctor_reports_whether_the_bin_directory_is_on_path(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": str(Path.home() / ".local" / "bin")}, clear=False):
            rows = sq.diagnose(QUARRY)
        self.assertEqual([row for row in rows if row[1] == "PATH"][0][0], "ok")
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=False):
            rows = sq.diagnose(QUARRY)
        self.assertEqual([row for row in rows if row[1] == "PATH"][0][0], "warn")


class PackagingTests(Base):
    def test_the_client_installs_and_uninstalls_itself(self) -> None:
        environment = {**os.environ, "SKILLQUARRY_PREFIX": str(self.prefix)}
        install = subprocess.run(["bash", str(QUARRY / "cli" / "install.sh")], env=environment,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(install.returncode, 0, install.stdout)
        self.assertIn("Self-check: PASS", install.stdout)
        launcher = self.prefix / "bin" / "skillquarry"
        listing = subprocess.run([str(launcher), "list"], stdout=subprocess.PIPE, text=True, check=False)
        self.assertIn("strata", listing.stdout)  # the recorded quarry is used without --quarry
        remove = subprocess.run(["bash", str(QUARRY / "cli" / "uninstall.sh")], env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(remove.returncode, 0, remove.stdout)
        self.assertFalse(launcher.exists())

    def test_version_flag_exits_zero(self) -> None:
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(io.StringIO()):
            sq.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)



class RemoteRegistryTests(Base):
    """A remote quarry is a URL; nothing is trusted until it hashes correctly."""

    def registry_document(self, **overrides):
        skills = sq.load_registry(QUARRY)
        document = {"schema_version": 3, "archive_base": "https://example.invalid/dl", "skills": skills}
        document.update(overrides)
        return document

    def test_plain_http_is_refused(self):
        with self.assertRaisesRegex(sq.QuarryError, "unencrypted"):
            sq.fetch("http://example.invalid/registry.json")

    def test_a_registry_without_archives_cannot_be_installed_from(self):
        with self.assertRaisesRegex(sq.QuarryError, "archive_base"):
            sq.archive_url({}, {"name": "x", "version": "1.0.0"})

    def test_the_archive_url_follows_name_and_version(self):
        url = sq.archive_url(self.registry_document(), {"name": "cordon", "version": "1.0.0"})
        self.assertEqual(url, "https://example.invalid/dl/cordon-1.0.0.tar.gz")

    def test_a_remote_registry_is_read_over_https(self):
        payload = json.dumps(self.registry_document()).encode("utf-8")
        with mock.patch.object(sq, "fetch", return_value=payload):
            skills, document = sq.load_remote_registry("https://example.invalid/registry.json")
        self.assertEqual({s["name"] for s in skills}, {"strata", "cordon", "rangate"})
        self.assertIn("archive_base", document)

    def test_a_registry_that_is_not_a_registry_is_refused(self):
        with mock.patch.object(sq, "fetch", return_value=b"{}"):
            with self.assertRaisesRegex(sq.QuarryError, "contains no skills"):
                sq.load_remote_registry("https://example.invalid/registry.json")
        with mock.patch.object(sq, "fetch", return_value=b"not json"):
            with self.assertRaisesRegex(sq.QuarryError, "not a registry document"):
                sq.load_remote_registry("https://example.invalid/registry.json")

    def _archive(self, name="cordon", version="1.0.0", extra=None):
        import io, tarfile
        source = QUARRY / "skills" / "security" / name
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w:gz") as archive:
            for path in sorted(source.rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts or "target" in path.parts:
                    continue
                archive.add(path, arcname=f"{name}-{version}/{path.relative_to(source).as_posix()}")
            if extra:
                info = tarfile.TarInfo(extra)
                info.size = 3
                archive.addfile(info, io.BytesIO(b"hi\n"))
        return raw.getvalue()

    def test_a_remote_install_verifies_the_unpacked_files(self):
        document = self.registry_document()
        payloads = [json.dumps(document).encode("utf-8"), self._archive()]
        with mock.patch.object(sq, "fetch", side_effect=payloads):
            record = sq.install_remote("https://example.invalid/registry.json", "cordon", str(self.prefix))
        self.assertEqual(record["version"], "1.0.0")
        self.assertTrue((self.prefix / "bin" / "cordon").is_file())

    def test_a_tampered_archive_is_refused_before_anything_runs(self):
        document = self.registry_document()
        payloads = [json.dumps(document).encode("utf-8"), self._archive(extra="cordon-1.0.0/EXTRA.md")]
        with mock.patch.object(sq, "fetch", side_effect=payloads):
            with self.assertRaisesRegex(sq.QuarryError, "does not match the registry checksum"):
                sq.install_remote("https://example.invalid/registry.json", "cordon", str(self.prefix))
        self.assertFalse((self.prefix / "bin" / "cordon").exists())

    def test_an_archive_that_escapes_its_directory_is_refused(self):
        import io, tarfile
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w:gz") as archive:
            info = tarfile.TarInfo("../escape.txt")
            info.size = 3
            archive.addfile(info, io.BytesIO(b"hi\n"))
        with self.assertRaises(sq.QuarryError):
            sq.unpack_archive(raw.getvalue(), self.root, "cordon-1.0.0")

    def test_an_archive_with_a_foreign_root_is_refused(self):
        with self.assertRaisesRegex(sq.QuarryError, "unexpected root"):
            sq.unpack_archive(self._archive(), self.root, "something-else-1.0.0")


class RemoteUpdateTests(RemoteRegistryTests):
    """Updating without a checkout goes back to the registry it came from."""

    def install_once(self, version="1.0.0"):
        document = self.registry_document()
        with mock.patch.object(sq, "fetch", side_effect=[json.dumps(document).encode("utf-8"), self._archive()]):
            sq.install_remote("https://example.invalid/registry.json", "cordon", str(self.prefix))

    def test_a_remote_skill_is_compared_against_its_own_registry(self):
        self.install_once()
        moved = self.registry_document()
        for skill in moved["skills"]:
            if skill["name"] == "cordon":
                skill["version"], skill["checksum"] = "1.1.0", "0" * 64
        with mock.patch.object(sq, "fetch", return_value=json.dumps(moved).encode("utf-8")):
            stale = sq.outdated(None)
        self.assertEqual([name for name, _, _ in stale], ["cordon"])

    def test_update_reinstalls_from_the_registry_it_came_from(self):
        self.install_once()
        moved = self.registry_document()
        for skill in moved["skills"]:
            if skill["name"] == "cordon":
                skill["checksum"] = "0" * 64
        current = json.dumps(self.registry_document()).encode("utf-8")
        # outdated() reads the moved registry; the reinstall then fetches the
        # unchanged one, so the archive still matches its checksum.
        with mock.patch.object(sq, "fetch", side_effect=[
            json.dumps(moved).encode("utf-8"), current, self._archive()
        ]):
            code, out, err = self.run_remote("update")
        self.assertEqual(code, sq.EXIT_OK, err)
        self.assertIn("updated cordon", out)

    def run_remote(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sq.main(["--registry", "https://example.invalid/registry.json", *argv])
        return code, out.getvalue(), err.getvalue()


class FetchTests(Base):
    """The one place the client talks to the network."""

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.captured = None

        def read(self, size):
            return self.payload[:size]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_a_token_is_sent_only_as_a_bearer_header(self):
        seen = {}

        def fake_urlopen(request, timeout=0):
            seen["headers"] = dict(request.header_items())
            seen["url"] = request.full_url
            return self.FakeResponse(b"payload")

        with mock.patch.object(sq.urllib.request, "urlopen", fake_urlopen):
            with mock.patch.object(sq, "REMOTE_TOKEN", "s3cret"):
                data = sq.fetch("https://example.invalid/registry.json")
        self.assertEqual(data, b"payload")
        self.assertEqual(seen["headers"].get("Authorization"), "Bearer s3cret")
        self.assertIn("skillquarry/", seen["headers"].get("User-agent", ""))

    def test_no_token_means_no_authorization_header(self):
        def fake_urlopen(request, timeout=0):
            self.assertNotIn("Authorization", dict(request.header_items()))
            return self.FakeResponse(b"ok")

        with mock.patch.object(sq.urllib.request, "urlopen", fake_urlopen):
            with mock.patch.object(sq, "REMOTE_TOKEN", None):
                self.assertEqual(sq.fetch("https://example.invalid/x"), b"ok")

    def test_an_oversized_response_is_refused(self):
        with mock.patch.object(sq.urllib.request, "urlopen",
                               lambda request, timeout=0: self.FakeResponse(b"x" * 50)):
            with self.assertRaisesRegex(sq.QuarryError, "larger than"):
                sq.fetch("https://example.invalid/big", limit=10)

    def test_a_network_error_is_reported_not_raised_raw(self):
        def boom(request, timeout=0):
            raise sq.urllib.error.URLError("no route to host")

        with mock.patch.object(sq.urllib.request, "urlopen", boom):
            with self.assertRaisesRegex(sq.QuarryError, "cannot fetch"):
                sq.fetch("https://example.invalid/x")


class RemoteEdgeTests(RemoteRegistryTests):
    def test_an_archive_containing_a_link_is_refused(self):
        import io, tarfile
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w:gz") as archive:
            info = tarfile.TarInfo("cordon-1.0.0/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
        with self.assertRaisesRegex(sq.QuarryError, "contains a link"):
            sq.unpack_archive(raw.getvalue(), self.root, "cordon-1.0.0")

    def test_installing_the_same_remote_skill_twice_is_refused(self):
        document = self.registry_document()
        payloads = [json.dumps(document).encode("utf-8"), self._archive(),
                    json.dumps(document).encode("utf-8")]
        with mock.patch.object(sq, "fetch", side_effect=payloads):
            sq.install_remote("https://example.invalid/r.json", "cordon", str(self.prefix))
            with self.assertRaisesRegex(sq.QuarryError, "already installed"):
                sq.install_remote("https://example.invalid/r.json", "cordon", str(self.prefix))

    def test_a_failing_remote_installer_is_reported(self):
        document = self.registry_document()
        payloads = [json.dumps(document).encode("utf-8"), self._archive()]
        failing = subprocess.CompletedProcess(["bash"], 1, "boom", None)
        with mock.patch.object(sq, "fetch", side_effect=payloads):
            with mock.patch.object(sq, "run_installer", return_value=failing):
                with self.assertRaisesRegex(sq.QuarryError, "installer failed"):
                    sq.install_remote("https://example.invalid/r.json", "cordon", str(self.prefix))

    def test_the_cli_serves_search_info_and_install_from_a_registry(self):
        document = self.registry_document()
        blob = json.dumps(document).encode("utf-8")
        out = io.StringIO()
        with mock.patch.object(sq, "fetch", return_value=blob):
            with redirect_stdout(out):
                code = sq.main(["--registry", "https://example.invalid/r.json", "list"])
        self.assertEqual(code, sq.EXIT_OK)
        self.assertIn("cordon", out.getvalue())

        out = io.StringIO()
        with mock.patch.object(sq, "fetch", return_value=blob):
            with redirect_stdout(out):
                code = sq.main(["--registry", "https://example.invalid/r.json", "info", "cordon"])
        self.assertEqual(code, sq.EXIT_OK)
        self.assertIn("Cordon", out.getvalue())

    def test_a_remote_install_pulls_its_dependency_first(self):
        skills = [dict(item) for item in sq.load_registry(QUARRY)]
        for skill in skills:
            if skill["name"] == "rangate":
                skill["dependencies"] = [{"name": "cordon"}]
        document = self.registry_document(skills=skills)
        blob = json.dumps(document).encode("utf-8")
        payloads = [blob, blob, self._archive("cordon"), blob,
                    self._archive("rangate")]
        out = io.StringIO()
        with mock.patch.object(sq, "fetch", side_effect=payloads):
            with redirect_stdout(out):
                code = sq.main(["--registry", "https://example.invalid/r.json", "install",
                                "rangate", "--prefix", str(self.prefix)])
        self.assertEqual(code, sq.EXIT_OK, out.getvalue())
        self.assertIn("installing dependencies first: cordon", out.getvalue())
        self.assertTrue((self.prefix / "bin" / "cordon").is_file())

    def test_the_cli_installs_dependencies_first_and_skips_what_is_there(self):
        skills = sq.load_registry(QUARRY)
        for skill in skills:
            if skill["name"] == "rangate":
                skill["dependencies"] = [{"name": "cordon"}]
        out = io.StringIO()
        with mock.patch.object(sq, "load_registry", return_value=skills):
            with redirect_stdout(out):
                code = sq.main(["--quarry", str(QUARRY), "install", "rangate",
                                "--prefix", str(self.prefix)])
        self.assertEqual(code, sq.EXIT_OK)
        printed = out.getvalue()
        self.assertIn("installing dependencies first: cordon", printed)
        self.assertLess(printed.index("installed cordon"), printed.index("installed rangate"))

        # Second run: cordon is already there, rangate is forced.
        out = io.StringIO()
        with mock.patch.object(sq, "load_registry", return_value=skills):
            with redirect_stdout(out):
                code = sq.main(["--quarry", str(QUARRY), "install", "rangate",
                                "--prefix", str(self.prefix), "--force"])
        self.assertIn("cordon is already installed", out.getvalue())


class DependencyTests(Base):
    def test_dependencies_come_first(self):
        skills = [
            {"name": "app", "dependencies": [{"name": "lib"}]},
            {"name": "lib", "dependencies": [{"name": "base"}]},
            {"name": "base"},
        ]
        self.assertEqual(sq.dependency_order(skills, "app"), ["base", "lib", "app"])

    def test_a_missing_dependency_stops_the_install(self):
        skills = [{"name": "app", "dependencies": [{"name": "ghost"}]}]
        with self.assertRaisesRegex(sq.QuarryError, "does not have"):
            sq.dependency_order(skills, "app")

    def test_a_cycle_is_reported_rather_than_looping(self):
        skills = [
            {"name": "a", "dependencies": [{"name": "b"}]},
            {"name": "b", "dependencies": [{"name": "a"}]},
        ]
        with self.assertRaisesRegex(sq.QuarryError, "dependency cycle"):
            sq.dependency_order(skills, "a")

    def test_a_shared_dependency_is_visited_once(self):
        skills = [
            {"name": "app", "dependencies": [{"name": "left"}, {"name": "right"}]},
            {"name": "left", "dependencies": [{"name": "base"}]},
            {"name": "right", "dependencies": [{"name": "base"}]},
            {"name": "base"},
        ]
        order = sq.dependency_order(skills, "app")
        self.assertEqual(order.count("base"), 1)
        self.assertLess(order.index("base"), order.index("left"))
        self.assertEqual(order[-1], "app")

    def test_a_skill_without_dependencies_is_just_itself(self):
        self.assertEqual(sq.dependency_order([{"name": "solo"}], "solo"), ["solo"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

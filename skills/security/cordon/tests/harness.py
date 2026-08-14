"""Real Git/filesystem fixtures plus a fake Claude Code binary."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
known_value = {"-p", "--output-format", "--max-turns", "--permission-mode", "--max-budget-usd", "--model", "--effort"}
known_flag = {"--no-session-persistence"}
i = 0
parsed = {}
while i < len(args):
    item = args[i]
    if item in known_value:
        if i + 1 >= len(args):
            print("missing value", file=sys.stderr); sys.exit(64)
        parsed[item] = args[i + 1]; i += 2
    elif item in known_flag:
        parsed[item] = True; i += 1
    else:
        print("unknown flag: " + item, file=sys.stderr); sys.exit(64)
required = ["-p", "--output-format", "--max-turns", "--permission-mode", "--no-session-persistence"]
if any(x not in parsed for x in required):
    print("missing required fake contract flag", file=sys.stderr); sys.exit(64)
if parsed["--output-format"] != "json":
    print("wrong output format", file=sys.stderr); sys.exit(64)
if parsed["--permission-mode"] != "acceptEdits":
    print("wrong permission mode", file=sys.stderr); sys.exit(64)
seq_path = Path(os.environ["CORDON_FAKE_SEQUENCE"])
seq = json.loads(seq_path.read_text())
index_path = seq_path.with_suffix(".index")
index = int(index_path.read_text()) if index_path.exists() else 0
if index >= len(seq):
    print("fake sequence exhausted", file=sys.stderr); sys.exit(65)
action = seq[index]
index_path.write_text(str(index + 1))
log_path = seq_path.with_suffix(".log")
with log_path.open("a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": args, "prompt": parsed["-p"]}) + "\n")
for rel, content in action.get("write", {}).items():
    p = Path(rel); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8")
for rel, content in action.get("write_bytes", {}).items():
    p = Path(rel); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(bytes.fromhex(content))
if action.get("commit"):
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-m", action.get("commit_message", "fake")], check=True, stdout=subprocess.DEVNULL)
if action.get("sleep"):
    time.sleep(float(action["sleep"]))
if action.get("spawn_child"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(action["spawn_child"]).write_text(str(child.pid))
if action.get("stdout_bytes"):
    sys.stdout.write("X" * int(action["stdout_bytes"]))
else:
    print(json.dumps({"result": action.get("claim", "done")}))
if action.get("stderr"):
    print(action["stderr"], file=sys.stderr)
sys.exit(int(action.get("exit", 0)))
'''


def run(*args: str, cwd: Path, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check, env=env)


class RepoFixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        run("git", "init", "-q", cwd=self.root)
        run("git", "config", "user.email", "tests@example.invalid", cwd=self.root)
        run("git", "config", "user.name", "Cordon Tests", cwd=self.root)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "README.md").write_text("# fixture\n", encoding="utf-8")
        run("git", "add", ".", cwd=self.root)
        run("git", "commit", "-q", "-m", "baseline", cwd=self.root)
        self.fake = self.root / "fake-claude"
        self.fake.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        # Keep the fake executable out of the Git-visible worktree without changing .gitignore.
        exclude = self.root / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text() + "\n/fake-claude\n/fake-sequence.json\n/fake-sequence.index\n/fake-sequence.log\n", encoding="utf-8")

    def close(self) -> None:
        self.temp.cleanup()

    def sequence(self, actions: list[dict[str, object]]) -> dict[str, str]:
        path = self.root / "fake-sequence.json"
        path.write_text(json.dumps(actions), encoding="utf-8")
        path.with_suffix(".index").unlink(missing_ok=True)
        path.with_suffix(".log").unlink(missing_ok=True)
        env = os.environ.copy()
        env["CORDON_FAKE_SEQUENCE"] = str(path)
        return env

    def claude_config(self) -> dict[str, object]:
        return {
            "binary": str(self.fake),
            "max_turns": 5,
            "timeout_seconds": 5,
            "max_budget_usd": 1.5,
            "model": "fake-model",
            "effort": "medium",
        }

#!/usr/bin/env python3

import time

import realworld_final_test as base


def standard_gate(repo, target_dir):
    env = base.cargo_env(target_dir)
    commands = [
        ("check", ["cargo", "check", "--workspace", "--lib", "--bins", "--tests"]),
        (
            "clippy",
            [
                "cargo",
                "clippy",
                "-p",
                "ignore",
                "--all-targets",
                "--",
                "--no-deps",
                "-D",
                "warnings",
            ],
        ),
        ("test", ["cargo", "test", "-p", "ignore", "--quiet"]),
    ]
    evidence = {}
    for name, args in commands:
        started = time.monotonic()
        completed = base.run(args, repo, env=env, timeout=420, check=False)
        evidence[name] = {
            "pass": completed.returncode == 0,
            "seconds": round(time.monotonic() - started, 3),
            "tail": (completed.stdout + completed.stderr)[-1200:],
        }
        if completed.returncode != 0:
            return {"pass": False, "failed_stage": name, "evidence": evidence}
    return {"pass": True, "failed_stage": None, "evidence": evidence}


base.standard_gate = standard_gate

if __name__ == "__main__":
    raise SystemExit(base.main())

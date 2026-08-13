"""Shared test harness: a fake `claude` binary with the real command contract.

The fake accepts the same arguments Strata passes to Claude Code and emits the
same JSON envelope, including `structured_output`. Everything else in the tests
is real: git repositories, file writes, subprocesses, locks and crash states.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path

args = sys.argv[1:]
try:
    prompt = args[args.index('-p') + 1]
except Exception:
    print('missing -p', file=sys.stderr)
    sys.exit(9)

log = os.environ.get('FAKE_PROMPT_LOG')
if log:
    with open(log, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'prompt': prompt, 'argv': args}) + '\n')

seq_path = Path(os.environ['FAKE_CLAUDE_SEQUENCE'])
count_path = Path(os.environ['FAKE_CLAUDE_COUNT'])
seq = json.loads(seq_path.read_text())
count = int(count_path.read_text()) if count_path.exists() else 0
item = seq[min(count, len(seq) - 1)]
count_path.write_text(str(count + 1))

for rel, content in item.get('write', {}).items():
    Path(rel).write_text(content, encoding='utf-8')

if item.get('sleep'):
    # Spawn a grandchild so process-group termination is actually exercised.
    if item.get('spawn_child'):
        import subprocess
        subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])
    time.sleep(item['sleep'])

if item.get('stdout_raw') is not None:
    sys.stdout.write(item['stdout_raw'])
    sys.exit(item.get('exit', 0))

if item.get('exit'):
    if item.get('stdout_json') is not None:
        print(json.dumps(item['stdout_json']))
    print(item.get('stderr', 'simulated engine failure'), file=sys.stderr)
    sys.exit(item['exit'])

envelope = {
    'session_id': f'fake-{count + 1}',
    'total_cost_usd': item.get('cost', 0.01),
    'num_turns': item.get('turns', 2),
    'usage': {'input_tokens': item.get('input_tokens', 1000), 'output_tokens': item.get('output_tokens', 200)},
}
if 'handoff' in item:
    envelope['structured_output'] = item['handoff']
envelope.update(item.get('envelope_extra', {}))
print(json.dumps(envelope))
'''


def handoff(status='continue', summary='progress', next_action='continue work', **kw):
    base = {
        'status': status,
        'summary': summary,
        'completed': [],
        'decisions': [],
        'failed_attempts': [],
        'changed_files': [],
        'read_first': [],
        'next_action': next_action,
        'tests': [],
        'blockers': [],
        'completion_evidence': [],
    }
    base.update(kw)
    return base


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class StrataTestCase(unittest.TestCase):
    """Base case: a real git repo plus a scripted fake Claude Code binary."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q')
        git(self.repo, 'config', 'user.email', 'test@example.com')
        git(self.repo, 'config', 'user.name', 'Test')
        (self.repo / 'README.md').write_text('seed\n')
        git(self.repo, 'add', 'README.md')
        git(self.repo, 'commit', '-qm', 'seed')

        self.fake = self.root / 'fake-claude'
        self.fake.write_text(FAKE_CLAUDE)
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)
        self.seq = self.root / 'sequence.json'
        self.count = self.root / 'count.txt'
        self.log = self.root / 'prompts.jsonl'
        os.environ['FAKE_CLAUDE_SEQUENCE'] = str(self.seq)
        os.environ['FAKE_CLAUDE_COUNT'] = str(self.count)
        os.environ['FAKE_PROMPT_LOG'] = str(self.log)
        self.set_sequence([{'handoff': handoff()}])

    def tearDown(self):
        for k in ('FAKE_CLAUDE_SEQUENCE', 'FAKE_CLAUDE_COUNT', 'FAKE_PROMPT_LOG'):
            os.environ.pop(k, None)
        self.td.cleanup()

    def set_sequence(self, items):
        self.seq.write_text(json.dumps(items))
        self.count.unlink(missing_ok=True)
        self.log.unlink(missing_ok=True)

    def prompts(self):
        return [json.loads(x)['prompt'] for x in self.log.read_text().splitlines()]

    def argvs(self):
        return [json.loads(x)['argv'] for x in self.log.read_text().splitlines()]

    def call_count(self):
        return int(self.count.read_text()) if self.count.exists() else 0

    def config(self, **kw):
        from strata.runner import Config
        d = dict(task='Make the requested safe change', max_generations=10, max_turns=5,
                 timeout_seconds=30, max_handoff_bytes=16000, stall_limit=3,
                 claude_bin=str(self.fake), verify=[], allow_dirty=False)
        d.update(kw)
        return Config(**d)

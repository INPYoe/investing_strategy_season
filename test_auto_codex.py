"""Exercise the continuation loop with a fake CLI; no Codex requests are made."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


MOCK_CODEX = '''#!/usr/bin/env python3
import json
from pathlib import Path
import sys

calls_file = Path('calls.json')
calls = json.loads(calls_file.read_text()) if calls_file.exists() else []
index = len(calls)
calls.append(sys.argv[1:])
calls_file.write_text(json.dumps(calls))
plan = json.loads(Path('plan.json').read_text())
if index >= len(plan):
    print('Unexpected extra invocation', file=sys.stderr)
    sys.exit(99)
turn = plan[index]
if turn.get('thread', True):
    print(json.dumps({'type': 'thread.started', 'thread_id': 'test-session-id'}))
for line in turn.get('log', []):
    print(line)
if 'message' in turn:
    destination = sys.argv[sys.argv.index('--output-last-message') + 1]
    Path(destination).write_text(turn['message'])
if turn.get('check_todo'):
    path = Path('TODO.md')
    path.write_text(path.read_text().replace('- [ ]', '- [x]'))
sys.exit(turn.get('exit', 0))
'''


class AutoCodexTests(unittest.TestCase):
    def run_loop(self, plan, prompt='continue research', arguments=True):
        with tempfile.TemporaryDirectory(prefix='seasonality-auto-test-') as directory:
            root = Path(directory)
            shutil.copy(Path(__file__).with_name('auto-codex.sh'), root)
            (root / 'TODO.md').write_text('- [ ] Match optimal windows\n')
            (root / 'plan.json').write_text(json.dumps(plan))
            (root / 'codex').write_text(MOCK_CODEX)
            (root / 'sleep').write_text('#!/bin/bash\nprintf "%s\\n" "$1" >> sleeps.txt\n')
            for name in ('codex', 'sleep'):
                (root / name).chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'])
            result = subprocess.run(
                ['bash', str(root / 'auto-codex.sh')] + ([prompt] if arguments else []),
                cwd=root, env=env, text=True, capture_output=True, timeout=10)
            calls = json.loads((root / 'calls.json').read_text()) if (root / 'calls.json').exists() else []
            sleeps = (root / 'sleeps.txt').read_text() if (root / 'sleeps.txt').exists() else ''
            return result, calls, sleeps

    def test_prompt_marker_does_not_finish_and_same_session_resumes(self):
        result, calls, sleeps = self.run_loop([
            {'log': ['Prompt contains ALL_DONE'], 'message': 'More work remains'},
            {'message': 'Verified\nALL_DONE\n', 'check_todo': True},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        resume_index = calls[1].index('resume')
        self.assertEqual(calls[1][resume_index + 1], 'test-session-id')
        self.assertNotIn('--last', calls[1])
        self.assertIn('--approve-for-me', calls[0])
        self.assertEqual(calls[0][calls[0].index('--sandbox') + 1], 'workspace-write')
        self.assertEqual(sleeps, '')

    def test_completion_with_unchecked_todo_keeps_working(self):
        result, calls, _ = self.run_loop([
            {'message': 'ALL_DONE'},
            {'message': 'ALL_DONE', 'check_todo': True},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)

    def test_cli_limit_retries_after_thirty_minutes(self):
        result, calls, sleeps = self.run_loop([
            {'exit': 1, 'log': [json.dumps({'type': 'error', 'message': 'usage limit reached'})]},
            {'message': 'ALL_DONE', 'check_todo': True},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, '1800\n')
        self.assertIn('test-session-id', calls[1])

    def test_nonlimit_error_stops_even_if_tool_output_mentions_limit(self):
        result, calls, sleeps = self.run_loop([
            {'exit': 7, 'log': ['Prompt mentions a usage limit', json.dumps({'type': 'item.completed', 'item': {
                'type': 'command_execution', 'output': 'Yahoo rate limit'}})]},
        ])
        self.assertEqual(result.returncode, 7)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, '')

    def test_stale_last_message_cannot_finish_next_run(self):
        result, calls, _ = self.run_loop([
            {'message': 'ALL_DONE'},
            {'check_todo': True},
            {'message': 'ALL_DONE'},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 3)

    def test_missing_session_id_stops_instead_of_resuming_some_other_thread(self):
        result, calls, _ = self.run_loop([{'thread': False, 'message': 'Pending'}])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(calls), 1)

    def test_missing_prompt_does_not_start_cli(self):
        result, calls, _ = self.run_loop([], arguments=False)
        self.assertEqual(result.returncode, 64)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()

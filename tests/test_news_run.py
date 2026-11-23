"""news/run.ps1 against a throwaway clone, a local bare remote and a fake claude."""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parent.parent / 'news' / 'run.ps1'
PS = shutil.which('powershell.exe')
pytestmark = pytest.mark.skipif(PS is None, reason='needs Windows PowerShell')

ENV = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
       'GIT_COMMITTER_EMAIL': 't@t', 'GIT_CONFIG_NOSYSTEM': '1'}
REPO_FILES = {
    'curated/a.json': '1\n', 'news/open-items.md': '- item\n', 'news/prompt.md': 'Do the news.\n',
    'app.js': '//\n',
    'tests/test_ok.py': "def test_ok():\n    assert open('curated/a.json').read().strip() != 'bad'\n",
    'tests/ok.test.js': "require('node:test')('ok', () => {});\n",
    'worker/test/ok.test.js': "require('node:test')('ok', () => {});\n",
}


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, env=ENV, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def env(tmp_path):
    remote, repo, bin_ = tmp_path / 'remote.git', tmp_path / 'repo', tmp_path / 'bin'
    git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(remote))
    git(tmp_path, 'clone', '-q', str(remote), str(repo))
    for f, text in REPO_FILES.items():
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text(text)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'init')
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    bin_.mkdir()
    (bin_ / 'claude.cmd').write_text(f'@"{sys.executable}" "%~dp0act.py" %*\n')
    (tmp_path / 'settings.json').write_text(json.dumps(
        {'model': 'test-model', 'env': {'SCBBL_TEST_ENV': 'from-settings'},
         'permissions': {'allow': ['Bash']}}))
    return tmp_path


def claude(env, body='', result='nothing new'):
    """The fake claude records how it was called, runs `body` in the repo, then prints the RESULT line."""
    script = textwrap.dedent('''\
        import json, os, pathlib, subprocess, sys
        def git(*a): subprocess.run(['git', *a], check=True)
        def write(f, t): pathlib.Path(f).parent.mkdir(parents=True, exist_ok=True); pathlib.Path(f).write_text(t)
        pathlib.Path(r'ROOT/called').write_text(json.dumps(
            {'argv': sys.argv[1:], 'prompt': sys.stdin.read(), 'env': os.environ.get('SCBBL_TEST_ENV')}))
        ''') + textwrap.dedent(body) + f'print("RESULT: {result}")\n'
    (env / 'bin' / 'act.py').write_text(script.replace('ROOT', str(env)))


def called(env):
    p = env / 'called'
    return json.loads(p.read_text()) if p.exists() else None


def run(env, verify=False):
    args = [PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(RUN),
            '-Repo', str(env / 'repo'), '-State', str(env / 'state'),
            '-Claude', str(env / 'bin' / 'claude.cmd'), '-UserSettings', str(env / 'settings.json'), '-Quiet']
    return subprocess.run(args + ([] if verify else ['-NoVerify']), env=ENV, capture_output=True,
                          text=True, timeout=180)


def remote_log(env):
    return git(env / 'remote.git', 'log', '--format=%s', 'main').splitlines()


def log_text(env):
    return '\n'.join(p.read_text(encoding='utf-8-sig') for p in (env / 'state' / 'logs').glob('*.log'))


def flagged(env):
    return 'needs a look' in log_text(env)


def test_claude_commit_is_pushed_and_marker_cleared(env):
    claude(env, '''
        write('curated/a.json', '2\\n')
        git('commit', '-qam', 'News: a changed')
        ''', 'committed News: a changed')
    r = run(env)
    assert r.returncode == 0, log_text(env)
    assert remote_log(env)[0] == 'News: a changed'
    assert not (env / 'state' / 'running').exists()
    assert not flagged(env)
    c = called(env)
    assert c['prompt'].startswith('Today is ') and 'Do the news.' in c['prompt']


def test_claude_gets_scoped_tools_and_not_the_user_settings(env):
    claude(env)
    assert run(env).returncode == 0, log_text(env)
    c = called(env)
    argv = c['argv']
    assert argv[argv.index('--setting-sources') + 1] == 'project'
    assert argv[argv.index('--model') + 1] == 'test-model'
    assert c['env'] == 'from-settings'
    tools = argv[argv.index('--allowedTools') + 1:argv.index('--disallowedTools')]
    # Unlisted, Read/Glob/Grep reach only the repo; listed, Glob and Grep reach the whole disk.
    assert {'Bash', 'Edit', 'Write', 'PowerShell', 'Read', 'Glob', 'Grep'}.isdisjoint(tools)
    denied = argv[argv.index('--disallowedTools') + 1:]
    assert {'Read(./worker/.dev.vars)', 'Read(./worker/.wrangler/**)', 'Edit(curated/sc_raw/**)',
            'Write(curated/sc_raw/**)'} <= set(denied)
    assert all(not t.startswith('Bash(') or ' *' not in t or t == 'Bash(git commit -m *)' for t in tools)
    assert 'Bash(python -m pipeline.build)' in tools and 'Write(curated/**)' in tools


def test_interrupted_run_leftovers_are_stashed_and_the_run_goes_on(env):
    (env / 'state').mkdir()
    (env / 'state' / 'running').write_text('2026-11-21T08:47:00')
    (env / 'repo' / 'curated' / 'a.json').write_text('half\n')
    claude(env)
    r = run(env)
    assert r.returncode == 0, log_text(env)
    assert called(env)
    assert 'leftovers from the run started 2026-11-21T08:47:00' in git(env / 'repo', 'stash', 'list')
    assert git(env / 'repo', 'stash', 'show', '--name-only') == 'curated/a.json'
    assert not (env / 'state' / 'running').exists()


def test_interrupted_run_new_files_are_stashed_too(env):
    (env / 'state').mkdir()
    (env / 'state' / 'running').write_text('x')
    (env / 'repo' / 'curated' / 'half.json').write_text('{}')
    claude(env, "git('add', 'curated')\ngit('commit', '-qm', 'News: swept up')\n", 'committed News: swept up')
    r = run(env)
    assert r.returncode == 0, log_text(env)
    assert remote_log(env) == ['init'], 'the stray file must not be committed'
    assert 'curated/half.json' in git(env / 'repo', 'stash', 'show', '--include-untracked', '--name-only')


def test_interrupted_run_leftovers_outside_news_paths_stop_the_run(env):
    (env / 'state').mkdir()
    (env / 'state' / 'running').write_text('x')
    (env / 'repo' / 'curated' / 'a.json').write_text('half\n')
    (env / 'repo' / 'app.js').write_text('edited\n')
    claude(env)
    r = run(env)
    assert r.returncode == 1
    assert not called(env)
    assert 'app.js' in log_text(env)
    assert git(env / 'repo', 'stash', 'list') == ''
    assert (env / 'state' / 'running').exists(), 'a run that never started must not clear the marker'


def test_uncommitted_changes_without_a_marker_skip_the_run(env):
    (env / 'repo' / 'curated' / 'a.json').write_text('mine\n')
    claude(env)
    r = run(env)
    assert r.returncode == 1
    assert not called(env)
    assert 'has uncommitted changes' in log_text(env)
    assert (env / 'repo' / 'curated' / 'a.json').read_text() == 'mine\n'
    assert git(env / 'repo', 'stash', 'list') == ''


def test_earlier_unpushed_news_commit_goes_out_even_when_nothing_is_new(env):
    (env / 'repo' / 'curated' / 'a.json').write_text('3\n')
    git(env / 'repo', 'commit', '-qam', 'News: from the killed run')
    claude(env)
    r = run(env)
    assert r.returncode == 0, log_text(env)
    assert remote_log(env)[0] == 'News: from the killed run'
    assert not flagged(env)


def test_unpushed_commit_outside_news_paths_stops_before_claude(env):
    (env / 'repo' / 'app.js').write_text('local work\n')
    git(env / 'repo', 'commit', '-qam', 'wip')
    claude(env)
    r = run(env)
    assert r.returncode == 1
    assert not called(env)
    assert remote_log(env) == ['init']


@pytest.mark.parametrize('body', [
    "write('curated/a.json', '2\\n')\nwrite('app.js', 'oops\\n')\ngit('commit', '-qam', 'News: sneaky')\n",
    # A rename lists only the new, allowed name unless renames are switched off.
    "git('mv', 'app.js', 'curated/app.json')\ngit('commit', '-qm', 'News: sneaky')\n",
    "write('data/x.html', '<script></script>')\ngit('add', 'data')\ngit('commit', '-qm', 'News: sneaky')\n",
    "write('curated/sc_raw/settings.json', '{}')\ngit('add', 'curated')\ngit('commit', '-qm', 'News: sneaky')\n",
    "write('curated/SC_RAW/settings.json', '{}')\ngit('add', 'curated')\ngit('commit', '-qm', 'News: sneaky')\n",
], ids=['code', 'rename', 'html-in-data', 'sc-raw', 'sc-raw-case'])
def test_claude_commit_outside_news_paths_is_not_pushed(env, body):
    claude(env, body, 'committed News: sneaky')
    r = run(env)
    assert r.returncode == 1
    assert remote_log(env) == ['init']
    assert 'outside the news paths' in log_text(env)


@pytest.mark.parametrize('body, shown', [
    ("write('tests/conftest.py', 'import os')\n", 'tests/conftest.py'),
    # A .gitignore that ignores itself hides from --exclude-standard listings and git status.
    ("write('curated/.gitignore', '*')\nwrite('curated/evil.json', '{}')\n", 'curated/evil.json'),
], ids=['elsewhere', 'self-ignored'])
def test_new_untracked_file_stops_the_run(env, body, shown):
    claude(env, "write('curated/a.json', '2\\n')\ngit('commit', '-qam', 'News: a')\n" + body, 'committed News: a')
    r = run(env)
    assert r.returncode == 1
    assert shown in log_text(env)
    assert remote_log(env) == ['init']
    assert not (env / 'state' / 'running').exists()


@pytest.mark.parametrize('tamper', [
    "git('config', 'remote.origin.push', 'refs/heads/main:refs/heads/main')\n",
    "write('.git/hooks/pre-push', '#!/bin/sh\\n')\n",
], ids=['config', 'hook'])
def test_git_config_or_hook_change_stops_the_run(env, tamper):
    claude(env, "write('curated/a.json', '2\\n')\ngit('commit', '-qam', 'News: a changed')\n" + tamper,
           'committed News: a changed')
    r = run(env)
    assert r.returncode == 1
    assert remote_log(env) == ['init']
    assert 'Git config or hooks changed' in log_text(env)


def test_rebase_conflict_is_aborted_not_left_in_progress(env):
    claude(env, '''
        subprocess.run(['git', 'clone', '-q', r'ROOT/remote.git', r'ROOT/other'], check=True)
        pathlib.Path(r'ROOT/other/curated/a.json').write_text('theirs\\n')
        subprocess.run(['git', 'commit', '-qam', 'bot'], cwd=r'ROOT/other', check=True)
        subprocess.run(['git', 'push', '-q'], cwd=r'ROOT/other', check=True)
        write('curated/a.json', 'ours\\n')
        git('commit', '-qam', 'News: a changed')
        ''', 'committed News: a changed')
    r = run(env)
    assert r.returncode == 1
    assert remote_log(env) == ['bot', 'init']
    assert 'rebasing by hand' in log_text(env)
    assert not (env / 'repo' / '.git' / 'rebase-merge').exists()
    assert git(env / 'repo', 'rev-parse', '--abbrev-ref', 'HEAD') == 'main'
    assert git(env / 'repo', 'status', '--porcelain', '--untracked-files=no') == ''


def test_notes_only_change_is_committed_and_pushed(env):
    claude(env, "write('news/open-items.md', '- item\\n- new question\\n')\n")
    r = run(env)
    assert r.returncode == 0, log_text(env)
    assert remote_log(env)[0].startswith('News check notes ')
    assert git(env / 'remote.git', 'show', 'main:news/open-items.md').endswith('new question')
    assert not flagged(env)


def test_failed_run_still_pushes_its_notes_and_is_flagged(env):
    claude(env, "write('news/open-items.md', '- item\\n- why it failed\\n')\n", 'failed build broke')
    r = run(env)
    assert r.returncode == 0, log_text(env)
    assert remote_log(env)[0].startswith('News check notes ')
    assert flagged(env) and 'failed build broke' in log_text(env)


@pytest.mark.parametrize('result', ['committed News: imaginary', 'failed no luck'])
def test_no_commit_without_nothing_new_is_flagged(env, result):
    claude(env, '', result)
    assert run(env).returncode == 0
    assert flagged(env)


def test_uncommitted_data_after_claude_is_not_pushed(env):
    claude(env, "write('curated/a.json', '2\\n')\n", 'committed nothing really')
    r = run(env)
    assert r.returncode == 1
    assert remote_log(env) == ['init']
    assert 'Uncommitted changes' in log_text(env)


def test_failing_tests_after_the_commit_block_the_push(env):
    claude(env, "write('curated/a.json', 'bad\\n')\ngit('commit', '-qam', 'News: bad')\n", 'committed News: bad')
    r = run(env, verify=True)
    assert r.returncode == 1
    assert remote_log(env) == ['init']
    assert 'pytest failed' in log_text(env)


def test_tests_run_on_the_rebased_result(env):
    # Each side passes alone; only the combination fails, so the tests must run after the final rebase.
    claude(env, '''
        subprocess.run(['git', 'clone', '-q', r'ROOT/remote.git', r'ROOT/other'], check=True)
        pathlib.Path(r'ROOT/other/tests/test_ok.py').write_text(
            "def test_ok():\\n    assert open('curated/a.json').read().strip() != '2'\\n")
        subprocess.run(['git', 'commit', '-qam', 'tighten'], cwd=r'ROOT/other', check=True)
        subprocess.run(['git', 'push', '-q'], cwd=r'ROOT/other', check=True)
        write('curated/a.json', '2\\n')
        git('commit', '-qam', 'News: two')
        ''', 'committed News: two')
    r = run(env, verify=True)
    assert r.returncode == 1
    assert remote_log(env) == ['tighten', 'init']
    assert 'pytest failed' in log_text(env)


def test_passing_tests_after_the_commit_let_it_push(env):
    claude(env, "write('curated/a.json', '2\\n')\ngit('commit', '-qam', 'News: good')\n", 'committed News: good')
    r = run(env, verify=True)
    assert r.returncode == 0, log_text(env)
    assert remote_log(env)[0] == 'News: good'
    assert 'verifying before push' in log_text(env)


def test_off_main_is_skipped(env):
    git(env / 'repo', 'checkout', '-qb', 'side')
    claude(env)
    r = run(env)
    assert r.returncode == 1
    assert not called(env)
    assert 'is not on main' in log_text(env)

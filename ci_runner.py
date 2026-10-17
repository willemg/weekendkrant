"""Small local exact-commit CI. See docs/ci.md for state and operator contract."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
import uuid

LIVE = Path('/home/weekendkrant/app')
LOG_LIMIT = 64 * 1024 * 1024
DEFAULT_STATE = '/home/weekendkrant/ci'
DEFAULT_SOURCE = 'https://github.com/willemg/weekendkrant.git'


def now():
    return datetime.now(timezone.utc).isoformat()


def valid_sha(sha):
    if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Expected a complete lowercase Git SHA-1')
    return sha


def outside_checkout(path):
    path = Path(path).resolve()
    if path == LIVE or LIVE in path.parents:
        raise ValueError('CI paths must be outside the live checkout')
    if any((parent / '.git').exists() for parent in (path, *path.parents)):
        raise ValueError('CI state/work must be outside every Git checkout')
    return path


def fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, data):
    fd, name = tempfile.mkstemp(prefix='.state-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fsync_dir(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class State:
    def __init__(self, root):
        self.root = outside_checkout(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'state.json'

    def read(self):
        if not self.path.exists():
            return {'version': 1, 'pending': None, 'last_result': None, 'last_failure': None}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('Unknown CI state format')
        for key in ('pending', 'last_result', 'last_failure'):
            entry = data[key]
            if entry is not None:
                valid_sha(entry['sha'])
                if not isinstance(entry['request'], str) or not entry['request']:
                    raise ValueError('Invalid request identity')
        return data

    @contextmanager
    def locked(self):
        # Never replace or unlink lockfiles: all processes must lock the same inode.
        with (self.root / 'state.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @contextmanager
    def edit(self):
        with self.locked():
            data = self.read()
            yield data
            atomic_json(self.path, data)

    def mark_in(self, data, sha, force=False):
        valid_sha(sha)
        if not force:
            if data['pending'] and data['pending']['sha'] == sha:
                return
            last = data['last_result']
            if not data['pending'] and last and last['sha'] == sha and last['status'] == 'succeeded':
                return
        data['pending'] = {'sha': sha, 'request': uuid.uuid4().hex, 'marked_at': now()}

    def mark(self, sha, force=False):
        valid_sha(sha)
        with self.edit() as data:
            self.mark_in(data, sha, force)

    def finish(self, request, result):
        with self.edit() as data:
            previous_failure = data['last_failure']
            data['last_result'] = result
            if result['status'] == 'succeeded':
                # Request identity also protects forced same-SHA reruns (ABA).
                if data['pending'] == request:
                    data['pending'] = None
            else:
                data['last_failure'] = result
            return (result['status'] == 'failed' and
                    (not previous_failure or previous_failure['sha'] != request['sha']))


def git_env():
    # Repository selectors inherited from a developer shell must never redirect
    # checkout/index operations to a different (possibly live) working tree.
    return {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}


def git_output(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args],
                                   text=True, stderr=subprocess.PIPE, env=git_env()).strip()


def clean_head(repo):
    if git_output(repo, 'status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('checkout is dirty')
    return valid_sha(git_output(repo, 'rev-parse', 'HEAD'))


def mark_checkout(state, repo, expected):
    if clean_head(repo) != expected:
        raise ValueError('HEAD changed during fast-track')
    with state.edit() as data:
        previous = data['pending'] or data['last_result']
        if previous and previous['sha'] != expected:
            old = previous['sha']
            # Delayed older deployment triggers may not replace a newer commit.
            code = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor',
                                   expected, old], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, env=git_env()).returncode
            if code == 0:
                return
            forward = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor',
                                      old, expected], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE, env=git_env()).returncode
            if forward != 0:
                raise ValueError('Cannot establish forward ancestry; use explicit mark --force')
        state.mark_in(data, expected)


class Report:
    """Append compact results; never used for admission, pending or locking."""
    COLUMNS = ('sha', 'request_id', 'status', 'started_at', 'finished_at',
               'duration_seconds', 'exitcode')

    def __init__(self, state):
        self.path = state.root / 'report.sqlite3'
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ci_runs (
                id INTEGER PRIMARY KEY, sha TEXT NOT NULL,
                request_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK(status IN ('succeeded','failed')),
                started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
                duration_seconds REAL NOT NULL, exitcode INTEGER NOT NULL,
                artifact_path TEXT,
                CHECK((status='succeeded' AND exitcode=0 AND artifact_path IS NULL)
                   OR (status='failed' AND exitcode<>0)))""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path))
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, limit=20):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM ci_runs ORDER BY id DESC LIMIT ?', (limit,))]

    def unreference(self):
        # Commit BEFORE replacing/removing the old artifact: old history may
        # lose a debug link after a crash, but can never point to another run.
        with self.connect() as db:
            db.execute('UPDATE ci_runs SET artifact_path=NULL WHERE artifact_path IS NOT NULL')

    def add(self, result, artifact):
        if artifact and not (Path(artifact) / 'test.log').is_file():
            raise ValueError('Refusing a report link to a missing failure artifact')
        values = (result['sha'], result['request'], result['status'], result['started_at'],
                  result['finished_at'], result['duration_seconds'], result['exitcode'])
        with self.connect() as db:
            old = db.execute('SELECT * FROM ci_runs WHERE request_id=?', (result['request'],)).fetchone()
            if old and tuple(old[key] for key in self.COLUMNS) != values:
                raise ValueError('Conflicting result for an existing CI request')
            db.execute("""INSERT INTO ci_runs
                (sha,request_id,status,started_at,finished_at,duration_seconds,exitcode,artifact_path)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(request_id)
                DO UPDATE SET artifact_path=excluded.artifact_path""", (*values, artifact))


class OutputLimitError(RuntimeError):
    pass


class RunLog:
    """Full streaming log, up to a hard runaway-output safety limit."""
    def __init__(self, path, limit=LOG_LIMIT):
        self.path = path
        self.limit = limit
        self.size = 0
        self.exceeded = False
        self.path.touch()

    def write(self, chunk):
        if self.exceeded:
            return
        available = self.limit - self.size
        with self.path.open('ab') as stream:
            stream.write(chunk[:available])
            self.size += min(len(chunk), available)
            if len(chunk) > available:
                self.exceeded = True
                stream.write(b'\nCI OUTPUT LIMIT exceeded; command stopped, output incomplete.\n')
                raise OutputLimitError('64 MiB CI output safety limit exceeded')

    def sync(self):
        with self.path.open('rb') as stream:
            os.fsync(stream.fileno())


def command(args, cwd, env, lock_fd, log):
    # The child retains runner.lock across a killed parent. A later cron cannot
    # overlap its tests or remove its worktree while that child is still alive.
    log.write(('\n$ ' + repr(args) + '\n').encode())
    with subprocess.Popen(args, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, pass_fds=(lock_fd,),
                          start_new_session=True) as child:
        try:
            while True:
                chunk = child.stdout.read1(8192)
                if not chunk:
                    break
                log.write(chunk)
            return child.wait()
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            raise


def validate_source(source):
    # Remote URLs or an explicitly selected local repository for offline use.
    # Never use the live checkout even as a local clone source.
    if source.startswith(('https://', 'ssh://', 'git@')):
        return
    local = source[7:] if source.startswith('file://') else source
    path = Path(local).resolve()
    if path == LIVE or LIVE in path.parents:
        raise ValueError('The live checkout is not a CI clone source')


def clone_test(sha, clone, python, source, lock_fd, log):
    env = git_env()
    env.pop('WEEKENDKRANT_CI_STATE', None)
    env['WEEKENDKRANT_TEST_PYTHON'] = python
    for args, cwd in ((['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--no-checkout', '--no-local', '--', source, str(clone)], clone.parent),
                      (['git', '-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', sha], clone)):
        code = command(args, cwd, env, lock_fd, log)
        if code:
            return code
    actual = git_output(clone, 'rev-parse', 'HEAD')
    if actual != sha:
        raise ValueError('Exact-SHA checkout verification failed')
    return command(['bash', './start_tests.sh', '--all'], clone, env, lock_fd, log)


@contextmanager
def runner_lock(state):
    with (state.root / 'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
        else:
            yield lock.fileno()


def cleanup(state):
    work = outside_checkout(state.root / 'work')
    if work.parent != state.root:
        raise ValueError('CI work directory must be a direct, non-symlink child of state')
    work.mkdir(exist_ok=True, mode=0o700)
    # Only this runner's private prefix. Symlinks are unlinked, never followed.
    for path in work.glob('run-*'):
        if path.is_symlink() or not path.is_dir():
            path.unlink()
        else:
            shutil.rmtree(path)
    with state.locked():
        for path in state.root.glob('.state-*'):
            path.unlink()
    return work


def remove_tree(path):
    if path.is_symlink():
        raise ValueError('Unexpected symlink in CI artifact paths')
    if path.exists():
        shutil.rmtree(path)


def completion(state):
    """Replay one small durable completion receipt, before any orphan cleanup."""
    journal = state.root / 'completion.json'
    if not journal.exists():
        return None
    entry = json.loads(journal.read_text())
    request, result = entry['request'], entry['result']
    valid_sha(result['sha'])
    name = entry['run_dir']
    if not re.fullmatch(r'run-[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid completion work directory')
    work = outside_checkout(state.root / 'work')
    if work.parent != state.root:
        raise ValueError('Invalid completion work path')
    stage = work / name
    failure = state.root / 'failure'
    previous = state.root / 'failure.previous'
    if stage.is_symlink() or failure.is_symlink() or previous.is_symlink():
        raise ValueError('Unexpected artifact symlink')
    report = Report(state)
    artifact = None
    if result['status'] == 'failed':
        if stage.exists():
            if (not (stage / 'test.log').is_file() or
                    json.loads((stage / 'result.json').read_text()) != result):
                raise ValueError('Incomplete staged failure; preserving old artifact')
            # Old artifact is kept until the new one is ready and published.
            report.unreference()
            if failure.exists():
                remove_tree(previous)
                os.replace(failure, previous)
                fsync_dir(state.root)
            os.replace(stage, failure)
            fsync_dir(work)
            fsync_dir(state.root)
        manifest = json.loads((failure / 'result.json').read_text())
        if manifest != result or not (failure / 'test.log').is_file():
            raise ValueError('Published artifact does not match completion receipt')
        artifact = str(failure)
    elif result['status'] == 'succeeded' and result['exitcode'] == 0:
        remove_tree(stage)  # No durable success output, even before DB insert.
        fsync_dir(work)
    else:
        raise ValueError('Invalid completed CI outcome')
    report.add(result, artifact)
    should_notify = state.finish(request, result)
    remove_tree(previous)
    journal.unlink()
    fsync_dir(state.root)
    return result, should_notify


def clear_failure(state):
    with runner_lock(state) as fd:
        if fd is None:
            return
        completion(state)
        Report(state).unreference()
        remove_tree(state.root / 'failure')
        remove_tree(state.root / 'failure.previous')
        fsync_dir(state.root)


def notify_failure(state, outcome, notify):
    if outcome and outcome[1] and notify:
        result = outcome[0]
        message = (f"Weekendkrant CI faalde: {result['sha'][:12]}. "
                   f"Artifact: {state.root / 'failure'} (repo + test.log).")
        try:
            notify(message)
        except Exception as error:
            print(f'CI notification failed: {type(error).__name__}', file=sys.stderr)


def run(state, source, python, notify=None):
    validate_source(source)
    with runner_lock(state) as lock_fd:
        if lock_fd is None:
            return 0
        notify_failure(state, completion(state), notify)
        work = cleanup(state)
        with state.edit() as data:
            request = data['pending']
            if not request:
                return 0
            last = data['last_result']
            if last and last['request'] == request['request'] and last['status'] == 'failed':
                return 0
            result = dict(request, status='running', started_at=now(), finished_at=None,
                          exitcode=None, python=python)
            data['last_result'] = result
        temp = Path(tempfile.mkdtemp(prefix='run-', dir=str(work)))
        log = RunLog(temp / 'test.log')
        try:
            code = clone_test(request['sha'], temp / 'repo', python, source, lock_fd, log)
        except Exception as error:
            log.write(('\nCI infrastructure error: ' + repr(error) + '\n').encode())
            code = 2
        log.sync()
        finished = now()
        duration = max(0.0, (datetime.fromisoformat(finished) -
                             datetime.fromisoformat(result['started_at'])).total_seconds())
        result.update(status='succeeded' if code == 0 else 'failed', finished_at=finished,
                      duration_seconds=duration, exitcode=code)
        atomic_json(temp / 'result.json', result)
        atomic_json(state.root / 'completion.json',
                    {'request': request, 'result': result, 'run_dir': temp.name})
        outcome = completion(state)
        notify_failure(state, outcome, notify)
        return code if code >= 0 else 128 - code


def ntfy_from_env():
    url = os.environ.get('WEEKENDKRANT_CI_NTFY_URL')
    if not url:
        return None
    def send(message):
        if not url.startswith('https://'):
            raise ValueError('ntfy requires an HTTPS topic URL')
        headers = {'Title': 'Weekendkrant CI failed', 'Content-Type': 'text/plain; charset=utf-8'}
        token = os.environ.get('WEEKENDKRANT_CI_NTFY_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(url, data=message.encode('utf-8'), headers=headers, method='POST')
        with urlopen(request, timeout=10) as response:
            response.read(1024)
    return send


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default=os.environ.get('WEEKENDKRANT_CI_STATE', DEFAULT_STATE))
    subs = parser.add_subparsers(dest='action', required=True)
    mark = subs.add_parser('mark')
    mark.add_argument('--sha', required=True)
    mark.add_argument('--force', action='store_true')
    subs.add_parser('rerun')
    status = subs.add_parser('status')
    status.add_argument('--failure', action='store_true')
    status.add_argument('--pending', action='store_true')
    subs.add_parser('cleanup')
    subs.add_parser('clear-failure')
    subs.add_parser('report')
    runner = subs.add_parser('run')
    runner.add_argument('--source', default=DEFAULT_SOURCE)
    runner.add_argument('--python', default=sys.executable)
    args = parser.parse_args(argv)
    try:
        state = State(args.state)
        if args.action == 'run':
            python = os.path.abspath(args.python)
            if not os.access(python, os.X_OK):
                raise ValueError('CI Python must be an executable absolute path')
            return run(state, args.source, python, ntfy_from_env())
        if args.action == 'mark':
            state.mark(args.sha, args.force)
        elif args.action == 'rerun':
            with state.edit() as data:
                previous = data['pending'] or data['last_result']
                if not previous:
                    raise ValueError('No SHA to rerun')
                state.mark_in(data, previous['sha'], force=True)
        elif args.action == 'clear-failure':
            clear_failure(state)
        elif args.action == 'report':
            print(json.dumps(Report(state).rows(), indent=2))
        elif args.action == 'cleanup':
            with runner_lock(state) as fd:
                if fd is not None:
                    completion(state)
                    cleanup(state)
        else:
            data = state.read()
            with runner_lock(state) as fd:
                data['runner_busy'] = fd is None
            output = data['last_failure'] if args.failure else (data['pending'] if args.pending else data)
            print(json.dumps(output, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, sqlite3.Error) as error:
        print(f'CI error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

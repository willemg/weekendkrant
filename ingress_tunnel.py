"""Supervise a Quick Tunnel and publish its discovery pointer, without app Git access."""
import argparse
import json
import logging
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)
REMOTE = 'git@github.com:willemg/weekendkrant.git'
POINTER = 'config/ingress-endpoint.json'


class TunnelError(RuntimeError):
    pass


class StopRequested(BaseException):
    pass


def ingress_url(url):
    """Accept one DNS label under trycloudflare.com, with no URL extras."""
    if not re.fullmatch(r'https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
                        r'\.trycloudflare\.com(?:/ingress)?', url):
        raise TunnelError('Ongeldige Quick Tunnel URL')
    return url.removesuffix('/ingress') + '/ingress'


class URLDetector:
    def __init__(self):
        self.url = None

    def feed(self, line):
        # Tokens preserve credentials, port, path, query and fragment for validation.
        for candidate in re.findall(r'https?://[^\s|<>"\']+', line):
            try:
                parsed = urlsplit(candidate)
            except ValueError as exc:
                raise TunnelError('Ongeldige Quick Tunnel URL') from exc
            # cloudflared also prints documentation/terms links, not tunnel candidates.
            if parsed.hostname in ('www.cloudflare.com', 'developers.cloudflare.com'):
                continue
            endpoint = ingress_url(candidate)
            if self.url is not None and self.url != endpoint:
                raise TunnelError('Meerdere tegenstrijdige Quick Tunnel URLs')
            self.url = endpoint
        return self.url


def discovery_json(url):
    return json.dumps({'url': ingress_url(url)}, separators=(',', ':')) + '\n'


def child_environment():
    env = dict(os.environ)
    env.pop('WEEKENDKRANT_INGRESS_TOKEN', None)
    # Do not let inherited Git overrides redirect operations into the app repository.
    for name in list(env):
        if name.startswith('GIT_'):
            env.pop(name)
    env['GIT_TERMINAL_PROMPT'] = '0'
    return env


def run_git(args, cwd=None):
    try:
        result = subprocess.run(['git', *args], cwd=cwd, env=child_environment(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TunnelError('Git-opdracht mislukt of timeout') from exc
    if result.returncode:
        # Git stderr may contain remote configuration details; keep diagnostics bounded.
        raise TunnelError('Git {} mislukt (exit {}); geen force/rebase, publicatie gestopt'
                          .format(args[0], result.returncode))
    return result.stdout


def publish_endpoint(remote, url, temp_root=None):
    content = discovery_json(url)
    with tempfile.TemporaryDirectory(prefix='ingress-publish-', dir=temp_root) as directory:
        clone = Path(directory) / 'repo'
        run_git(['clone', '--depth', '1', '--single-branch', '--branch', 'main',
                 '--', remote, str(clone)], cwd=directory)
        target = clone / POINTER
        # Refuse symlinks from repository content, including the parent directory.
        if target.parent.is_symlink() or target.is_symlink():
            raise TunnelError('Discoverypad mag geen symlink zijn')
        if target.exists() and target.read_bytes() == content.encode('utf-8'):
            return False
        target.parent.mkdir(exist_ok=True)
        target.write_text(content, encoding='utf-8')
        run_git(['add', '--', POINTER], cwd=clone)
        run_git(['-c', 'user.name=weekendkrant', '-c', 'user.email=weekendkrant@bibib',
                 'commit', '-m', 'Werk ingress-endpoint bij', '--', POINTER], cwd=clone)
        # Ordinary push rejects a concurrent update. No retry/rebase/force is needed.
        run_git(['push', 'origin', 'HEAD:refs/heads/main'], cwd=clone)
        return True


def read_output(output, timeout):
    try:
        return output.get(timeout=timeout)
    except queue.Empty:
        return None


def supervise(process, publisher, timeout=60):
    output = queue.Queue()
    def reader():
        try:
            for line in process.stdout:
                output.put(line)
        finally:
            output.put('')  # EOF; distinct from a timeout.
    threading.Thread(target=reader, daemon=True).start()
    detector = URLDetector()
    deadline = time.monotonic() + timeout
    published = False
    while True:
        remaining = deadline - time.monotonic()
        if not published and remaining <= 0:
            raise TunnelError('Quick Tunnel URL timeout')
        line = read_output(output, min(0.2, max(0, remaining)) if not published else 0.2)
        if line is None:
            if process.poll() is not None:
                raise TunnelError('cloudflared gestopt (exit {})'.format(process.returncode))
            continue
        if line == '':
            code = process.wait(timeout=5)
            raise TunnelError('cloudflared gestopt (exit {})'.format(code))
        endpoint = detector.feed(line)
        if endpoint and not published:
            publisher(endpoint)
            published = True
            LOGGER.info('Ingress discovery gepubliceerd: %s', endpoint)
        # Keep validating subsequent output; do not relay arbitrary child log content.


def stop_child(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if process.stdout:
        process.stdout.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloudflared', default=os.environ.get('WEEKENDKRANT_CLOUDFLARED', 'cloudflared'))
    parser.add_argument('--url-timeout', type=float, default=60)
    parser.add_argument('--temp-root', default=os.environ.get('RUNTIME_DIRECTORY'))
    args = parser.parse_args(argv)
    if args.url_timeout <= 0:
        parser.error('--url-timeout moet positief zijn')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    process = None
    def request_stop(signum, frame):
        raise StopRequested()
    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        process = subprocess.Popen([args.cloudflared, 'tunnel', '--url', 'http://127.0.0.1:8000'],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace',
                                   env=child_environment())
        supervise(process, lambda url: publish_endpoint(REMOTE, url, args.temp_root), args.url_timeout)
    except StopRequested:
        LOGGER.info('Tunnelcomponent gestopt op verzoek')
        return 0
    except (TunnelError, OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.error('%s', exc)
        return 1
    finally:
        if process is not None:
            stop_child(process)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Minimal audit state for completed page reviews; no candidates or story identity."""
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import re
from urllib.parse import unquote, urlsplit, urlunsplit

from database import migrate


def canonicalize_url(url):
    """Identify an absolute HTTP(S) page without fetching or interpreting it.

    Keep path and non-tracking query fields byte-for-byte, in their original
    order. Only scheme/host case, default ports, fragments and known tracking
    keys are normalized. Credentials, malformed URLs and whitespace are refused.
    """
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError('Verwacht een absolute HTTP(S)-URL zonder witruimte')
    if '\\' in url or re.search(r'%(?![0-9a-fA-F]{2})', url):
        raise ValueError('Ongeldige URL-escaping')
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme not in ('http', 'https') or not host
                or parsed.username is not None or parsed.password is not None
                or parsed.netloc.endswith(':') or port == 0):
            raise ValueError('Onbruikbare bron-URL')
        host = host.lower()
        if parsed.netloc.startswith('['):
            ipaddress.IPv6Address(host)
            host = '[' + host + ']'
        else:
            # Validate DNS labels, retaining spelling (including a final dot).
            dns_host = host[:-1] if host.endswith('.') else host
            labels = dns_host.encode('idna').decode('ascii').split('.')
            if (len(host.encode('idna')) > 254 or not all(
                    re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
                    for label in labels)):
                raise ValueError('Ongeldige hostname')
        if port is not None and port != {'http': 80, 'https': 443}[parsed.scheme]:
            host += ':' + str(port)
    except (ValueError, UnicodeError) as error:
        raise ValueError('Ongeldige absolute HTTP(S)-URL') from error
    fields = []
    for field in parsed.query.split('&'):
        key = unquote(field.split('=', 1)[0]).lower()
        if not key.startswith('utm_') and key not in ('fbclid', 'gclid', 'trk'):
            fields.append(field)
    return urlunsplit((parsed.scheme.lower(), host, parsed.path, '&'.join(fields), ''))


def _topic(topic):
    if type(topic) is not int or topic not in (1, 2, 3):
        raise ValueError('Topic moet integer 1, 2 of 3 zijn')


def _run_id(run_id):
    if type(run_id) is not int or run_id < 1:
        raise ValueError('Run-ID moet een positief geheel getal zijn')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class SherlockState:
    """Use an idle caller-owned connection; all writes own a short transaction.

    Construction invokes the canonical migration chain. Every public operation
    refuses an active caller transaction. Writes use BEGIN IMMEDIATE and commit
    or roll back together, so finish and source registration cannot race.
    The caller closes the connection. Invalid inputs/run state raise ValueError;
    a duplicate canonical URL raises sqlite3.IntegrityError without overwriting.
    """

    def __init__(self, db):
        migrate(db)
        self.db = db

    def _idle(self):
        if self.db.in_transaction:
            raise ValueError('Sherlock-state vereist een connection zonder actieve transactie')

    @contextmanager
    def _write(self):
        self._idle()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def start_run(self, topic):
        """Start one run and return its increasing integer ID."""
        _topic(topic)
        with self._write():
            if self.db.execute("SELECT 1 FROM sherlock_assignments").fetchone():
                raise ValueError('Sherlock job lane is active')
            cursor = self.db.execute('INSERT INTO sherlock_runs(topic,started_at) VALUES (?,?)',
                                     (topic, _now()))
            identity = cursor.lastrowid
        return identity

    def start_next_run(self):
        """Atomically rotate topics based on the latest created run."""
        with self._write():
            if self.db.execute("SELECT 1 FROM sherlock_assignments").fetchone():
                raise ValueError('Sherlock job lane is active')
            previous = self.db.execute(
                'SELECT topic FROM sherlock_runs ORDER BY id DESC LIMIT 1'
            ).fetchone()
            topic = 1 if previous is None else (previous[0] % 3) + 1
            cursor = self.db.execute(
                'INSERT INTO sherlock_runs(topic,started_at) VALUES (?,?)',
                (topic, _now()))
            identity = cursor.lastrowid
        return identity, topic

    def finish_run(self, run_id, status):
        """Close a running run exactly once as completed or failed."""
        _run_id(run_id)
        if status not in ('completed', 'failed'):
            raise ValueError('Eindstatus moet completed of failed zijn')
        with self._write():
            from sherlock_executor import require_run_authority
            require_run_authority(self.db, run_id)
            cursor = self.db.execute('''UPDATE sherlock_runs SET status=?,finished_at=?
                WHERE id=? AND status='running' ''', (status, _now(), run_id))
            if cursor.rowcount != 1:
                raise ValueError('Onbekende of reeds afgesloten run')

    def already_reviewed(self, url):
        """Read-only page lookup; this does not claim or reserve the URL."""
        self._idle()
        canonical = canonicalize_url(url)
        return self.db.execute('SELECT 1 FROM sherlock_sources WHERE canonical_url=?',
                               (canonical,)).fetchone() is not None

    def filter_unreviewed(self, urls):
        """Return first-seen input URLs whose canonical page has not been reviewed."""
        self._idle()
        if not isinstance(urls, list):
            raise ValueError('URLs moeten een lijst zijn')
        if len(urls) > 50:
            raise ValueError('Maximaal 50 URLs per batch')
        canonical_to_original = {}
        for url in urls:
            canonical_to_original.setdefault(canonicalize_url(url), url)
        if not canonical_to_original:
            return []
        placeholders = ','.join('?' for _ in canonical_to_original)
        reviewed = {row[0] for row in self.db.execute(
            f'SELECT canonical_url FROM sherlock_sources WHERE canonical_url IN ({placeholders})',
            tuple(canonical_to_original))}
        return [original for canonical, original in canonical_to_original.items()
                if canonical not in reviewed]

    def record_reviewed_source(self, run_id, topic, url, outcome, rationale, title=None, claim=None):
        """Record an actually reviewed page and return its canonical URL.

        Call only after substantive review, never for a search hit or snippet.
        Outcome/rationale are short, checkable audit text, preserved verbatim.
        Recording remains durable even when the run subsequently fails.
        """
        _run_id(run_id)
        _topic(topic)
        canonical = canonicalize_url(url)
        if title is not None and not isinstance(title, str):
            raise ValueError('Titel moet tekst zijn of ontbreken')
        if any(not isinstance(text, str) or not text.strip() for text in (outcome, rationale)):
            raise ValueError('Outcome en rationale moeten niet-lege tekst zijn')
        with self._write():
            from sherlock_executor import require_run_authority
            require_run_authority(self.db, run_id, claim)
            run = self.db.execute('SELECT topic,status FROM sherlock_runs WHERE id=?',
                                  (run_id,)).fetchone()
            if run is None or run[0] != topic or run[1] != 'running':
                raise ValueError('Bron vereist een running run met hetzelfde topic')
            self.db.execute('''INSERT INTO sherlock_sources
                (canonical_url,original_url,topic,run_id,reviewed_at,title,outcome,rationale)
                VALUES (?,?,?,?,?,?,?,?)''',
                (canonical, url, topic, run_id, _now(), title, outcome, rationale))
        return canonical

"""Read-only baseline from existing Weekendkrant SQLite provenance."""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sqlite3
from statistics import mean, median


DB_PATH = Path('/home/weekendkrant/weekendkrant.sqlite3')


def timestamp(value):
    """Require an explicit timezone; do not guess the meaning of legacy dates."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def run_summary(runs):
    completed = [r for r in runs if r['status'] == 'completed']
    sources = [r['sources'] for r in completed]
    durations = [r['duration_seconds'] for r in completed
                 if r['duration_seconds'] is not None]
    statuses = Counter(r['status'] for r in runs)
    return {
        'runs': len(runs),
        'statuses': {s: statuses[s] for s in ('completed', 'failed', 'running')},
        'registered_sources': sum(r['sources'] for r in runs),
        'completed_sources_mean': mean(sources) if sources else None,
        'completed_sources_min': min(sources) if sources else None,
        'completed_sources_max': max(sources) if sources else None,
        'completed_duration_mean_seconds': mean(durations) if durations else None,
        'completed_duration_median_seconds': median(durations) if durations else None,
        'completed_duration_samples': len(durations),
    }


def sherlock_report(db, since, now, warnings):
    runs = []
    for row in db.execute('''SELECT r.id,r.topic,r.status,r.started_at,r.finished_at,
                            count(s.canonical_url) AS sources
                            FROM sherlock_runs r LEFT JOIN sherlock_sources s
                            ON s.run_id=r.id GROUP BY r.id ORDER BY r.id'''):
        start = timestamp(row['started_at'])
        if start is None:
            warnings.append('Sherlock-run %s: ongeldige starttijd; niet in periode geteld.' % row['id'])
            continue
        if not since <= start <= now:
            continue
        run = dict(row)
        run['duration_seconds'] = None
        if row['status'] == 'completed':
            finish = timestamp(row['finished_at'])
            if finish is not None and start <= finish <= now:
                run['duration_seconds'] = (finish - start).total_seconds()
            else:
                warnings.append('Sherlock-run %s: looptijd niet betrouwbaar bepaalbaar.' % row['id'])
        runs.append(run)
    result = run_summary(runs)
    result['by_topic'] = {str(t): run_summary([r for r in runs if r['topic'] == t])
                          for t in (1, 2, 3)}
    return result


def queue_report(db, now, warnings):
    statuses = dict(db.execute('SELECT status,count(*) FROM ingress_queue GROUP BY status'))
    pending = list(db.execute("SELECT id,received_at FROM ingress_queue WHERE status='pending'"))
    dated = [(timestamp(r['received_at']), r) for r in pending]
    oldest = None
    # One unknown timestamp prevents establishing the true oldest item.
    if any(date is None for date, _ in dated):
        warnings.append('Oudste pending item/leeftijd onbekend: ongeldige of timezone-loze received_at.')
    elif dated:
        received, row = min(dated, key=lambda pair: (pair[0], pair[1]['id']))
        age = (now - received).total_seconds()
        oldest = {'id': row['id'], 'received_at': row['received_at'],
                  'age_seconds': age if age >= 0 else None}
        if any(date > now for date, _ in dated):
            warnings.append('Pending ontvangsttijd ligt in de toekomst; negatieve leeftijd niet geschat.')
    return {'pending': statuses.get('pending', 0), 'processed': statuses.get('processed', 0),
            'other_statuses': {k: v for k, v in statuses.items() if k not in ('pending', 'processed')},
            'oldest_pending': oldest}


def parts_report(db, warnings):
    rows = list(db.execute('''SELECT p.id,p.week,p.topic,p.part,p.is_open,p.active_revision,
                             r.tokens,r.tokenizer,r.reserved_tokens
                             FROM parts p LEFT JOIN part_revisions r
                             ON r.part_id=p.id AND r.revision=p.active_revision
                             ORDER BY p.week,p.topic,p.part'''))
    for r in rows:
        if r['tokens'] is None:
            warnings.append('Part %s: geen geregistreerde actieve revision/tokenmeting.' % r['id'])
    groups = []
    for week, topic in sorted({(r['week'], r['topic']) for r in rows}):
        group = [r for r in rows if r['week'] == week and r['topic'] == topic]
        groups.append({'week': week, 'topic': topic, 'parts': len(group),
                       'open_parts': sum(r['is_open'] for r in group)})
    return {'parts': len(rows), 'open_parts': sum(r['is_open'] for r in rows),
            'revisions': db.execute('SELECT count(*) FROM part_revisions').fetchone()[0],
            'by_week_topic': groups,
            'open': [dict(r) for r in rows if r['is_open']],
            'offers': [dict(r) for r in db.execute(
                'SELECT id,part_id,revision,created_at FROM part_offers ORDER BY id')]}


def report(db_path=DB_PATH, hours=24, now=None):
    """Inspect one snapshot without initialization, migrations or file writes."""
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError('hours moet een eindig positief aantal uren zijn')
    now = datetime.now(timezone.utc) if now is None else now
    if now.utcoffset() is None:
        raise ValueError('now vereist een timezone')
    now = now.astimezone(timezone.utc)
    try:
        since = now - timedelta(hours=hours)
    except OverflowError as error:
        raise ValueError('hours is te groot') from error
    warnings = []
    result = {
        'as_of': now.isoformat(),
        'sherlock_period': {'since': since.isoformat(), 'until': now.isoformat(),
                           'basis': 'runs_started_in_period; registered sources of those runs in snapshot'},
        'sherlock': None, 'queue': None, 'parts': None, 'warnings': warnings,
        'limitations': [
            'Alleen geregistreerde reviews; ongeregistreerde inhoudelijke reviews zijn onbekend.',
            'Geen canonieke fiche/run/job-koppeling: fiche-aantal per run niet bepaalbaar.',
            'Geen materialisatietimestamps/usage-historiek: groeisnelheid en werkelijk modelgebruik onbekend.',
            'Geen generieke jobs: intelligente backlog niet bepaalbaar; pending is alleen ingressbacklog.',
            'Offers zijn lokale seals, geen bewijs van modelontvangst; running kan achtergelaten zijn.',
        ],
    }
    # as_uri safely quotes paths containing spaces, ?, # or non-ASCII characters.
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        sections = (
            ('sherlock', {'sherlock_runs', 'sherlock_sources'},
             lambda: sherlock_report(db, since, now, warnings)),
            ('queue', {'ingress_queue'}, lambda: queue_report(db, now, warnings)),
            ('parts', {'parts', 'part_revisions', 'part_offers'}, lambda: parts_report(db, warnings)),
        )
        for name, required, collect in sections:
            missing = required - tables
            if missing:
                warnings.append('%s niet beschikbaar: ontbrekende tabellen %s.' % (name, ', '.join(sorted(missing))))
            else:
                result[name] = collect()
    return result

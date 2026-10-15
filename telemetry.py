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


def run_summary(runs, has_fiches=True):
    completed = [r for r in runs if r['status'] == 'completed']
    sources = [r['sources'] for r in completed]
    durations = [r['duration_seconds'] for r in completed
                 if r['duration_seconds'] is not None]
    statuses = Counter(r['status'] for r in runs)
    return {
        'runs': len(runs),
        'statuses': {s: statuses[s] for s in ('completed', 'failed', 'running')},
        'registered_sources': sum(r['sources'] for r in runs),
        'published_fiches': sum(len(r['queue_item_ids']) for r in runs) if has_fiches else None,
        'completed_sources_mean': mean(sources) if sources else None,
        'completed_sources_min': min(sources) if sources else None,
        'completed_sources_max': max(sources) if sources else None,
        'completed_duration_mean_seconds': mean(durations) if durations else None,
        'completed_duration_median_seconds': median(durations) if durations else None,
        'completed_duration_samples': len(durations),
    }


def sherlock_report(db, since, now, warnings, has_fiches):
    runs = []
    fiches = {}
    if has_fiches:
        for row in db.execute('SELECT run_id,queue_item_id FROM sherlock_fiches ORDER BY queue_item_id'):
            fiches.setdefault(row['run_id'], []).append(row['queue_item_id'])
    else:
        warnings.append('Ficheprovenance niet beschikbaar: tabel sherlock_fiches ontbreekt.')
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
        run['queue_item_ids'] = fiches.get(row['id'], []) if has_fiches else None
        run['duration_seconds'] = None
        if row['status'] == 'completed':
            finish = timestamp(row['finished_at'])
            if finish is not None and start <= finish <= now:
                run['duration_seconds'] = (finish - start).total_seconds()
            else:
                warnings.append('Sherlock-run %s: looptijd niet betrouwbaar bepaalbaar.' % row['id'])
        runs.append(run)
    result = run_summary(runs, has_fiches)
    result['by_run'] = [{'run_id': r['id'], 'topic': r['topic'], 'status': r['status'],
                         'registered_sources': r['sources'],
                         'published_fiches': len(r['queue_item_ids']) if has_fiches else None,
                         'queue_item_ids': r['queue_item_ids']} for r in runs]
    result['by_topic'] = {str(t): run_summary([r for r in runs if r['topic'] == t], has_fiches)
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


def materialization_report(db, since, now, warnings):
    events = {}
    invalid = 0
    for row in db.execute('''SELECT m.queue_id,m.materialized_at,a.topic,length(a.content) AS bytes
                             FROM source_materializations m JOIN source_archive a ON a.queue_id=m.queue_id
                             ORDER BY m.queue_id'''):
        when = timestamp(row['materialized_at'])
        if when is None:
            invalid += 1
            warnings.append('Queue-item %s: materialisatietijd niet betrouwbaar bepaalbaar.' % row['queue_id'])
            continue
        if not since <= when <= now:
            continue
        key = (when, row['topic'])
        event = events.setdefault(key, {'materialized_at': when.isoformat(), 'topic': row['topic'],
                                        'queue_items': 0, 'content_bytes': 0, 'queue_item_ids': []})
        event['queue_items'] += 1
        event['content_bytes'] += row['bytes']
        event['queue_item_ids'].append(row['queue_id'])
    rows = [events[key] for key in sorted(events)]
    return {'since': since.isoformat(), 'until': now.isoformat(),
            'queue_items': sum(e['queue_items'] for e in rows),
            'content_bytes': sum(e['content_bytes'] for e in rows), 'events': rows,
            'invalid_timestamp_items': invalid,
            'untimed_archived_items': db.execute('''SELECT count(*) FROM source_archive a WHERE NOT EXISTS
                (SELECT 1 FROM source_materializations m WHERE m.queue_id=a.queue_id)''').fetchone()[0]}


def model_usage_report():
    """Availability of current metering contracts, never an inferred usage total."""
    return {
        'status': 'unavailable',
        'source': 'current_runtime_contract',
        'reason': 'De huidige Sherlock-/MCP-contracten bewaren geen door de modelprovider gemeten usage of model-ID.',
        'model_id': None,
        'input_tokens': None,
        'output_tokens': None,
        'reasoning_tokens': None,
        'cached_input_tokens': None,
        'allowance': {
            'status': 'unavailable', 'used': None, 'remaining': None, 'unit': None,
            'reason': 'De beschikbare scheduled-taskmetadata levert geen product-allowanceteller of meeteenheid.',
        },
        'ariadne': {
            'status': 'not_applicable',
            'reason': 'De huidige lokale deterministische Ariadne-verwerking voert geen modelcalls uit.',
        },
    }


def intelligent_backlog_report():
    """Current availability, not a queue/part-based estimate of intelligent work."""
    return {
        'status': 'not_implemented',
        'source': 'current_runtime_contract',
        'ready_items': None,
        'oldest_ready_at': None,
        'reason': 'De intelligente backlogmeting is nog niet aangesloten op generieke jobstate; ingress-pending, parts, offers en Sherlock-runs worden niet als intelligente werkqueue geteld.',
    }


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
        'sherlock': None, 'queue': None, 'parts': None, 'materialization': None, 'warnings': warnings,
        'model_usage': model_usage_report(),
        'intelligent_backlog': intelligent_backlog_report(),
        'limitations': [
            'Alleen geregistreerde reviews; ongeregistreerde inhoudelijke reviews zijn onbekend.',
            'Fichetellingen omvatten alleen expliciet gekoppelde queue-items; legacy/ongekoppelde producers blijven onbekend.',
            'Historische materialisatietijden zonder expliciete registratie en werkelijk modelgebruik blijven onbekend.',
            'Generieke jobstate is nog niet op deze backlogmeting aangesloten; pending is alleen ingressbacklog.',
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
             lambda: sherlock_report(db, since, now, warnings, 'sherlock_fiches' in tables)),
            ('queue', {'ingress_queue'}, lambda: queue_report(db, now, warnings)),
            ('parts', {'parts', 'part_revisions', 'part_offers'}, lambda: parts_report(db, warnings)),
            ('materialization', {'source_materializations', 'source_archive'},
             lambda: materialization_report(db, since, now, warnings)),
        )
        for name, required, collect in sections:
            missing = required - tables
            if missing:
                warnings.append('%s niet beschikbaar: ontbrekende tabellen %s.' % (name, ', '.join(sorted(missing))))
            else:
                result[name] = collect()
        if result['queue'] is not None:
            result['queue']['unattributed_items'] = db.execute('''SELECT count(*) FROM ingress_queue q
                WHERE NOT EXISTS (SELECT 1 FROM sherlock_fiches f WHERE f.queue_item_id=q.id)''').fetchone()[0] if 'sherlock_fiches' in tables else None
    return result

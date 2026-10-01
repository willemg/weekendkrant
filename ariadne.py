"""Deterministische, lokale voorbereiding van Sherlocks weekwerkruimte."""
import argparse
from datetime import date, datetime, timedelta
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo


LOG_PATH = Path('/home/weekendkrant/logs/ariadne.log')
LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s %(message)s'
logger = logging.getLogger(__name__)


def configure_logging(log_path=None, level=logging.INFO):
    log_path = LOG_PATH if log_path is None else Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=1024 * 1024,
                                  backupCount=4, encoding='utf-8')
    logging.basicConfig(level=level, format=LOG_FORMAT,
                        handlers=[handler], force=True)


def week_name(day):
    year, week, _ = day.isocalendar()
    return f'{year}_W{week:02d}'


def next_week_date(now=None):
    zone = ZoneInfo('Europe/Brussels')
    now = datetime.now(zone) if now is None else now
    if now.tzinfo is None:
        raise ValueError('De klok moet een timezone bevatten.')
    today = now.astimezone(zone).date()
    return today + timedelta(days=7 - today.weekday())


def _git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], text=True,
                            capture_output=True,
                            env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
    if result.returncode:
        raise ValueError(f'git {" ".join(args)}: {result.stderr.strip()}')
    return result.stdout.strip()


def _has_ref(root, ref):
    return subprocess.run(['git', '-C', str(root), 'show-ref', '--verify',
                           '--quiet', ref]).returncode == 0


def prepare_week(root, day):
    root = Path(root).resolve()
    if Path(_git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError('Gebruik de repositoryroot.')
    week = week_name(day)
    branch = f'ingress/{week}'
    ingress = root / 'ingress' / week
    audit = root / 'audit' / week / 'ingress-preparation.json'
    def validate_paths():
        # Controleer de paden voor enige Git- of bestandsschrijfactie.
        for path in (root / 'ingress', ingress, ingress / '.gitkeep',
                     root / 'audit', audit.parent, audit):
            if path.is_symlink():
                raise ValueError(f'Symlink niet toegestaan: {path.relative_to(root)}')
        for path in (root / 'ingress', ingress, root / 'audit', audit.parent):
            if path.exists() and not path.is_dir():
                raise ValueError(f'Geen map: {path.relative_to(root)}')

    validate_paths()
    current = _git(root, 'branch', '--show-current')
    if current != branch:
        if _git(root, 'status', '--porcelain'):
            raise ValueError('Commit of ruim lokale wijzigingen op vóór branchwissel.')
        if _has_ref(root, f'refs/heads/{branch}'):
            _git(root, 'switch', branch)
        elif _has_ref(root, f'refs/remotes/origin/{branch}'):
            _git(root, 'switch', '-c', branch, f'refs/remotes/origin/{branch}')
        else:
            _git(root, 'switch', '-c', branch, 'refs/heads/main')
    validate_paths()
    record = None
    if audit.exists():
        record = json.loads(audit.read_text(encoding='utf-8'))
        if (not isinstance(record, dict) or record.get('schema_version') != 1
                or record.get('week') != week or record.get('branch') != branch
                or record.get('ingress_path') != f'ingress/{week}'
                or not isinstance(record.get('base_commit'), str)):
            raise ValueError('Bestaand auditrecord wijkt af; niet overschreven.')
        _git(root, 'cat-file', '-e', record['base_commit'] + '^{commit}')
    if record is None:
        record = {'schema_version': 1, 'week': week, 'branch': branch,
                  'ingress_path': f'ingress/{week}',
                  'base_commit': _git(root, 'rev-parse', 'HEAD')}
    ingress.mkdir(parents=True, exist_ok=True)
    # Exclusief aanmaken: bestaande oogst en audit blijven ongewijzigd.
    if not (ingress / '.gitkeep').exists():
        (ingress / '.gitkeep').touch(exist_ok=False)
    if not audit.exists():
        audit.parent.mkdir(parents=True, exist_ok=True)
        with audit.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def prepare_week_runtime(root, day):
    root = Path(root).resolve()
    if Path(_git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError('Gebruik de repositoryroot.')
    if _git(root, 'status', '--porcelain'):
        raise ValueError('Vuile werkboom: commit of ruim lokale wijzigingen op vóór prepare-week.')
    logger.info('Fetch origin: repo=%s', root)
    _git(root, 'fetch', 'origin')
    # Een lokaal vooruitgelopen main mag evenmin als een divergente main blijven.
    if _git(root, 'merge-base', 'main', 'origin/main') != _git(root, 'rev-parse', 'main'):
        raise ValueError('Lokale main kan niet uitsluitend fast-forward gelijk worden aan origin/main.')
    _git(root, 'switch', 'main')
    _git(root, 'merge', '--ff-only', 'origin/main')
    logger.info('Main gesynchroniseerd via fast-forward: commit=%s',
                _git(root, 'rev-parse', 'main'))
    week = week_name(day)
    branch = f'ingress/{week}'
    # Lokale weekhistory krijgt voorrang. Remote vooruit/divergent: veilig stoppen.
    if (_has_ref(root, f'refs/heads/{branch}')
            and _has_ref(root, f'refs/remotes/origin/{branch}')
            and _git(root, 'merge-base', branch, f'origin/{branch}')
            != _git(root, 'rev-parse', f'origin/{branch}')):
        raise ValueError(f'Weekbranch {branch}: remote ligt vooruit of is divergent; geen automatische merge/reset.')
    record = prepare_week(root, day)
    paths = [f'ingress/{week}/.gitkeep', f'audit/{week}/ingress-preparation.json']
    if _git(root, 'status', '--porcelain', '--', *paths):
        _git(root, 'add', '--', *paths)
        _git(root, 'commit', '-m', f'Bereid ingress week {week} voor', '--', *paths)
        logger.info('Week nieuw voorbereid; commit gemaakt: week=%s commit=%s',
                    week, _git(root, 'rev-parse', 'HEAD'))
    else:
        logger.info('Weekvoorbereiding bestond al correct: week=%s', week)
    # Expliciete refspec; nooit force, nooit main pushen. Ook bij herhaling pushen
    # om remote succes te bevestigen en een eerdere pushfout te kunnen herstellen.
    _git(root, 'push', '--set-upstream', 'origin', f'refs/heads/{branch}:refs/heads/{branch}')
    logger.info('Push succesvol; weekbranch bevestigd op origin: branch=%s', branch)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare-week', help='Bereid Sherlocks week op origin voor.')
    prepare.add_argument('--repo', type=Path, default=Path.cwd())
    dates = prepare.add_mutually_exclusive_group(required=True)
    dates.add_argument('--date', type=date.fromisoformat,
                       help='Lokale kalenderdatum YYYY-MM-DD; ISO-week wordt afgeleid.')
    dates.add_argument('--next-week', action='store_true',
                       help='Eerstvolgende ISO-week volgens Europe/Brussels.')
    args = parser.parse_args()
    try:
        configure_logging()
    except OSError:
        # Als het bestand niet beschikbaar is, blijft de fout via logging zichtbaar.
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, force=True)
        logger.exception('Logging initialiseren mislukt: logbestand=%s', LOG_PATH)
        parser.exit(1)
    logger.info('Weekvoorbereiding gestart: taak=prepare-week repo=%s', args.repo)
    day = args.date
    try:
        day = next_week_date() if args.next_week else day
        logger.info('Lokale datum gekozen: datum=%s doelweek=%s zone=Europe/Brussels',
                    day, week_name(day))
        result = prepare_week_runtime(args.repo, day)
    except Exception:
        # Unattended entrypoint: ook onverwachte runtimefouten krijgen traceback
        # en exitcode 1. SystemExit en KeyboardInterrupt worden niet onderschept.
        logger.exception('Weekvoorbereiding mislukt: repo=%s datum=%s',
                         args.repo, day)
        parser.exit(1)
    logger.info('Weekvoorbereiding voltooid: week=%s branch=%s ingress=%s base_commit=%s',
                result['week'], result['branch'], result['ingress_path'], result['base_commit'])
    # Gestructureerde CLI-resultaatoutput, geen runtime-diagnostiek.
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

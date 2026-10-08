"""Deterministische SQLite-backlogverwerking voor Ariadne."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOCK_PATH = Path('/home/weekendkrant/ariadne.lock')

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


@contextmanager
def runtime_lock(lock_path=LOCK_PATH):
    """One local consumer, independent of Git; never wait for another run."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Een andere Ariadne-taak gebruikt het runtime-slot.') from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    daily_parser = commands.add_parser('daily', help='Verwerk de SQLite-queue tot en met vandaag in Europe/Brussels.')
    daily_parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        configure_logging()
    except OSError:
        # Als het bestand niet beschikbaar is, blijft de fout via logging zichtbaar.
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, force=True)
        logger.exception('Logging initialiseren mislukt: logbestand=%s', LOG_PATH)
        parser.exit(1)
    from daily import run_daily
    try:
        result = run_daily(args.repo)
    except Exception:
        logger.exception('Dagelijkse taak mislukt: repo=%s', args.repo)
        parser.exit(1)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

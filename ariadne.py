"""Deterministische, lokale voorbereiding van Sherlocks weekwerkruimte."""
import argparse
from datetime import date
import json
from pathlib import Path
import subprocess


def week_name(day):
    year, week, _ = day.isocalendar()
    return f'{year}_W{week:02d}'


def _git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], text=True,
                            capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.strip())
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--date', type=date.fromisoformat, required=True,
                        help='Lokale kalenderdatum YYYY-MM-DD; ISO-week wordt afgeleid.')
    args = parser.parse_args()
    try:
        result = prepare_week(args.repo, args.date)
    except (ValueError, OSError) as error:
        parser.exit(1, f'Ariadne: {error}\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

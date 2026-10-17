"""Run the versioned fast-track list, or explicit full unittest discovery."""

import argparse
import os
import subprocess
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def load_suite(root, full=False):
    """Validate the entire selection before executing any test."""
    tests = root / "tests"
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(tests))
    loader = unittest.TestLoader()
    if full:
        suite = loader.discover(str(tests))
        selected = sorted({test.id().split(".")[0] for test in cases(suite)})
    else:
        manifest = tests / "fast_track.txt"
        selected = [
            line.partition("#")[0].strip()
            for line in manifest.read_text(encoding="utf-8").splitlines()
        ]
        selected = [entry for entry in selected if entry]
        if not selected:
            raise ValueError("Fast-track list is empty: tests/fast_track.txt")
        suite = unittest.TestSuite()
        for entry in selected:
            if not re.fullmatch(r"test_[A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}", entry):
                raise ValueError(f"Invalid test entry: {entry}")
            if not (tests / (entry.split(".")[0] + ".py")).is_file():
                raise ValueError(f"Test module does not exist: {entry}")
            loaded = loader.loadTestsFromName(entry)
            if not loaded.countTestCases():
                raise ValueError(f"Test entry selects zero tests: {entry}")
            suite.addTests(loaded)
    if loader.errors:
        raise ValueError("Cannot load selected tests:\n" + "\n".join(loader.errors))
    identities = [test.id() for test in cases(suite)]
    if not identities:
        raise ValueError("Selection contains zero tests")
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate or overlapping test entries")
    return selected, suite, len({identity.split(".")[0] for identity in identities})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Run the complete suite")
    args = parser.parse_args(argv)
    try:
        selected, suite, module_count = load_suite(ROOT, args.all)
    except (OSError, ValueError, TypeError, ImportError) as error:
        print(f"Test selection failed: {error}", file=sys.stderr)
        return 2
    ci_state = os.environ.get("WEEKENDKRANT_CI_STATE") if not args.all else None
    ci_sha = None
    if ci_state:
        from ci_runner import clean_head
        try:
            ci_sha = clean_head(ROOT)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            print(f"CI niet gemarkeerd: {error}", file=sys.stderr)
    print("Full suite (--all)" if args.all else "Fast-track: tests/fast_track.txt", flush=True)
    for entry in selected:
        print(f"  {entry}", flush=True)
    print(f"Selected {module_count} modules, {suite.countTestCases()} tests", flush=True)
    if not unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful():
        return 1
    if ci_sha:
        from ci_runner import State, mark_checkout
        try:
            mark_checkout(State(ci_state), ROOT, ci_sha)
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
            print(f"CI trigger failed: {error}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

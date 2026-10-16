"""Conservative static reverse-import selection; uncertainty runs everything."""

import argparse
import ast
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent


def all_tests(root, reason):
    return {
        p.relative_to(root).as_posix(): reason for p in sorted((root / "tests").rglob("test_*.py"))
    }


def changed_files(root):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)

    # Fetch is deliberately not performed by the test runner. Use the available
    # remote tracking main, falling back to local main in offline repositories.
    try:
        git("rev-parse", "--verify", "refs/remotes/origin/main")
        main = "refs/remotes/origin/main"
    except subprocess.CalledProcessError:
        main = "refs/heads/main"
    base = git("merge-base", main, "HEAD").decode().strip()
    # Diff against worktree includes staged/unstaged changes and committed branch
    # changes. --no-renames retains both deleted and added dependency identities.
    tracked = git("diff", "--name-only", "--no-renames", "-z", base, "--")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z")
    return sorted({p.decode("utf-8") for p in (tracked + untracked).split(b"\0") if p})


def select(root, changed):
    root = Path(root)
    tests = all_tests(root, "")
    changed = set(changed)

    def full(why):
        return all_tests(root, "full fallback: " + why)

    if not changed:
        return {}
    safe_docs = lambda p: p.endswith(".md") and (p.startswith("docs/") or p == "README.md")
    broad = lambda p: (
        p in {"database.py", "test_impact.py", "start_tests.sh"}
        or p.endswith("/__init__.py")
        or p.startswith(("migrations/", "config/", ".github/"))
        or Path(p).name.startswith(("requirements", "pyproject", "setup", "Dockerfile"))
    )
    if any(p.startswith("docs/agents/") for p in changed):
        return full("role contract changed")
    if any(broad(p) for p in changed):
        return full("shared schema/configuration/test infrastructure changed")
    if any(not (safe_docs(p) or p.endswith(".py")) for p in changed):
        return full("non-Python boundary or unknown file changed")
    relevant = {p for p in changed if not safe_docs(p)}
    if not relevant:
        return {}
    paths = [
        p
        for p in root.rglob("*.py")
        if not any(
            part.startswith(".") or part in {"__pycache__", "node_modules"}
            for part in p.relative_to(root).parts
        )
    ]
    modules = {
        p.relative_to(root)
        .with_suffix("")
        .as_posix()
        .replace("/", "."): p.relative_to(root)
        .as_posix()
        for p in paths
    }
    # unittest discover imports tests as top-level modules in this codebase.
    modules.update({Path(p).stem: p for p in tests})
    reverse = {}
    try:
        for path in set(modules.values()):
            tree = ast.parse((root / path).read_text(encoding="utf-8"))
            dynamic_names = {
                "__import__",
                "exec",
                "eval",
                "import_module",
                "spec_from_file_location",
            }
            for imported in ast.walk(tree):
                if isinstance(imported, ast.ImportFrom) and imported.module in {
                    "importlib",
                    "importlib.util",
                    "builtins",
                }:
                    dynamic_names.update(
                        alias.asname or alias.name
                        for alias in imported.names
                        if alias.name in dynamic_names
                    )
            for node in ast.walk(tree):
                imports = []
                if isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Name)
                    and node.func.id in dynamic_names
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"import_module", "spec_from_file_location"}
                ):
                    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                    if (
                        name in {"__import__", "import_module"}
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        imports = [node.args[0].value]
                    else:
                        return full("dynamic dependency cannot be bounded")
                if isinstance(node, ast.Import):
                    imports = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        return full("relative import cannot be bounded")
                    imports = [node.module or ""] + [
                        (node.module + "." if node.module else "") + a.name for a in node.names
                    ]
                for name in imports:
                    # Longest known module prefix captures import x.y and from x import y.
                    while name:
                        if name in modules:
                            reverse.setdefault(modules[name], set()).add(path)
                            break
                        name = name.rpartition(".")[0]
    except (OSError, SyntaxError, UnicodeError) as error:
        return full("dependency parse failed: " + type(error).__name__)
    if any(p not in modules.values() for p in relevant):
        return full("deleted or unknown dependency")
    selected = {}
    for source in sorted(relevant):
        reached, pending = set(), [source]
        while pending:
            path = pending.pop()
            if path in reached:
                continue
            reached.add(path)
            pending.extend(reverse.get(path, ()))
        impacted = reached & tests.keys()
        if not impacted:
            return full("no reliable test coverage for " + source)
        if len(impacted) > max(8, len(tests) * 0.6):
            return full("widely imported module: " + source)
        for test in impacted:
            selected.setdefault(test, []).append(source)
    # Component boundary tests are few explicit semantic rules, not the primary graph.
    boundaries = {
        "ingress_api.py",
        "ingress_queue.py",
        "daily.py",
        "parts.py",
        "jobs.py",
        "job_control.py",
        "dispatcher.py",
        "sherlock_executor.py",
        "leonardo.py",
    }
    if relevant & boundaries:
        for test in tests:
            if any(word in test for word in ("system_e2e", "job_http", "dispatcher")):
                selected.setdefault(test, []).append("component boundary")
    return {p: "impact: " + ", ".join(reasons) for p, reasons in sorted(selected.items())}


def run(root, selected):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for path, reason in sorted(selected.items()):
        print(f"{path}: {reason}", flush=True)
        suite.addTests(
            loader.loadTestsFromName(
                ".".join(Path(path).relative_to("tests").with_suffix("").parts)
            )
        )
    print(f"Selected {len(selected)} modules, {suite.countTestCases()} tests", flush=True)
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Run the complete suite")
    args = parser.parse_args(argv)
    if not all_tests(root, ""):
        print("No test modules available; refusing an unverifiable run", file=sys.stderr)
        return 1
    if args.all:
        selected = all_tests(root, "explicit --all")
    else:
        try:
            selected = select(root, changed_files(root))
        except Exception as error:
            selected = all_tests(root, "full fallback: analysis failed: " + type(error).__name__)
    return run(root, selected)


if __name__ == "__main__":
    sys.exit(main())

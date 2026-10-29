"""Portability regressions found while preparing deployment (HDEWS-037 …)."""
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _blocked_pandas(tmp_path):
    """A stand-in for Windows Smart App Control refusing pandas' unsigned compiled extension (OS error 4551)."""
    pkg = tmp_path / "blocked" / "pandas"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('raise ImportError("DLL load failed while importing nattype: '
                                     'An Application Control policy has blocked this file.")\n', encoding="utf-8")
    return str(pkg.parent)


def _pytest(tmp_path, *args, require_ml=None):
    env = dict(os.environ, PYTHONPATH=_blocked_pandas(tmp_path))
    env.pop("HDEWS_REQUIRE_ML", None)
    if require_ml:
        env["HDEWS_REQUIRE_ML"] = "1"
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rs", *args],
                          cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600)


# HDEWS-037: one blocked `import pandas` interrupted collection, so NONE of the backend tests ran on Windows
# machines enforcing Smart App Control, although the backend never imports pandas.
def test_blocked_ml_stack_skips_only_the_ml_harness(tmp_path):
    r = _pytest(tmp_path, "tests/test_ml_harness.py", "tests/test_risk_engine.py")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-2000:]
    assert "Interrupted" not in out
    assert "15 passed" in out and "1 skipped" in out, out[-800:]
    assert "Application Control policy" in out  # the reason is shown, not hidden


def test_ci_mode_turns_a_broken_ml_stack_into_an_error(tmp_path):
    r = _pytest(tmp_path, "tests/test_ml_harness.py", require_ml=True)
    assert r.returncode != 0
    assert "Application Control policy" in r.stdout + r.stderr


def test_backend_runtime_never_imports_the_ml_stack(tmp_path):
    """The deployed image installs runtime requirements only; the app must start and serve without pandas/numpy/sklearn."""
    code = (
        "import sys, importlib.abc\n"
        "class Block(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name.split('.')[0] in {'pandas', 'numpy', 'sklearn', 'scipy'}:\n"
        "            raise ImportError('blocked for test: ' + name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import os; os.environ['HDEWS_DEMO_PASSWORD']='x-test-pass-123'; os.environ.pop('HDEWS_ENV', None)\n"
        "sys.path.insert(0, 'backend')\n"
        "from starlette.testclient import TestClient\n"
        "from app.config import load_settings\nfrom app.db import Database\nfrom app.main import create_app\nfrom app.seed import seed\n"
        "db = Database('sqlite:///:memory:'); seed(db, quiet=True)\n"
        "s = load_settings(database_url='sqlite:///:memory:', enable_background_reassessment=False, app_env='test')\n"
        "c = TestClient(create_app(s, db))\n"
        "t = c.post('/api/auth/login', json={'username': 'viewer', 'password': 'x-test-pass-123'}).json()['token']\n"
        "h = {'Authorization': 'Bearer ' + t}\n"
        "for p in ('/api/overview', '/api/evaluation', '/api/sites/SNP-05', '/api/rules'):\n"
        "    assert c.get(p, headers=h).status_code == 200, p\n"
        "assert not any(m.split('.')[0] in {'pandas', 'numpy', 'sklearn'} for m in sys.modules)\n"
        "print('RUNTIME_OK')\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=300)
    assert "RUNTIME_OK" in r.stdout, r.stdout[-1500:] + r.stderr[-1500:]


# HDEWS-038: text files were read with the platform default encoding. On Windows (cp1252) the seed stored
# "16â€“17 June" instead of "16–17 June" — every non-ASCII character in incidents and sites was corrupted.
def _text_io_without_encoding(root: Path) -> list[str]:
    import ast
    bad = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            name = node.func.attr
            kw = {k.arg for k in node.keywords}
            if name in ("read_text", "write_text") and "encoding" not in kw:
                bad.append(f"{path.relative_to(REPO)}:{node.lineno} {name}")
    return bad


def test_all_text_file_io_specifies_an_encoding():
    offenders = []
    for d in ("backend/app", "backend/tests", "ml", "scripts", "e2e"):
        offenders += _text_io_without_encoding(REPO / d)
    assert offenders == [], offenders


def test_seeded_text_is_identical_without_utf8_mode():
    """With UTF-8 mode off, Python uses the locale encoding (cp1252 on most Windows installs)."""
    import json
    code = ("import sys, json, locale; sys.path.insert(0, 'backend')\n"
            "import os; os.environ['HDEWS_DEMO_PASSWORD'] = 'x-test-pass-123'; os.environ.pop('HDEWS_ENV', None)\n"
            "from app.db import Database; from app.seed import seed\n"
            "db = Database('sqlite:///:memory:'); seed(db, quiet=True)\n"
            "with db.tx() as tx: rows = tx.all('SELECT id, title, description, notes FROM incidents ORDER BY id')\n"
            "print(json.dumps({'encoding': locale.getencoding(), 'rows': rows}))\n")
    env = dict(os.environ, PYTHONUTF8="0")
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    got = json.loads(r.stdout.strip().splitlines()[-1])
    src = json.loads((REPO / "data/sample/incidents.json").read_text(encoding="utf-8"))["incidents"]
    want = {i["id"]: (i["title"], i["description"], i["notes"]) for i in src}
    assert {r_["id"]: (r_["title"], r_["description"], r_["notes"]) for r_ in got["rows"]} == want, got["encoding"]


# HDEWS-039: reset_db.py built a SQLite URI by string concatenation, so a path containing "#" (or "?", "%",
# or Windows backslashes) opened the wrong file and a genuine HDEWS database was refused as foreign.
def test_reset_db_handles_special_characters_in_path(tmp_path):
    folder = tmp_path / "project #1"
    folder.mkdir()
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{folder / 'h.db'}", HDEWS_DEMO_PASSWORD="x-test-pass-123")
    env.pop("HDEWS_ENV", None)
    run = lambda s: subprocess.run([sys.executable, str(REPO / "scripts" / s)], env=env, capture_output=True,
                                   text=True, timeout=300)
    assert run("seed_demo_data.py").returncode == 0
    r = run("reset_db.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Removed" in r.stdout

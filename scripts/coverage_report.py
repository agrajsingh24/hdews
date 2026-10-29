"""Line and branch coverage for HDEWS using only the standard library (Python 3.12+ `sys.monitoring`).

Why: coverage.py / pytest-cov could not be installed in the build environment. This tool measures
  * line coverage  - executable lines (from compiled code objects) that ran at least once;
  * branch coverage - for every conditional jump in the bytecode (if/while/for/and/or/ternary),
                      whether both outcomes (jump taken / fall through) were observed.
Branch coverage is bytecode-level, so it can differ slightly from coverage.py's source-level arcs.
Lines marked `# pragma: no cover` (and the block they open) are excluded and counted separately.

Usage (from the repository root):  python scripts/coverage_report.py [--out docs/coverage.json] [-- pytest args]
"""
from __future__ import annotations

import argparse
import dis
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "backend" / "app", ROOT / "ml"]
COND = {"POP_JUMP_IF_TRUE", "POP_JUMP_IF_FALSE", "POP_JUMP_IF_NONE", "POP_JUMP_IF_NOT_NONE", "FOR_ITER"}
GROUPS = {
    "Risk engine (pure logic)": ["services/risk_engine/"],
    "Data freshness & features": ["services/risk_engine/features.py"],
    "Authentication & RBAC": ["security.py", "api/common.py"],
    "Sensor ingestion": ["services/ingestion.py"],
    "Alert lifecycle (state transitions)": ["services/alerts.py"],
    "Audit chain": ["services/audit.py"],
    "Simulator": ["services/simulator.py"],
    "Explanations (LLM guard)": ["services/explanations.py"],
    "API endpoints": ["api/"],
    "ML evaluation harness": ["ml/evaluate.py"],
}


def target_files() -> list[Path]:
    return sorted(p for t in TARGETS for p in t.rglob("*.py"))


def excluded_lines(src: str) -> set[int]:
    lines = src.splitlines()
    out: set[int] = set()
    i = 0
    while i < len(lines):
        if "pragma: no cover" in lines[i]:
            indent = len(lines[i]) - len(lines[i].lstrip())
            out.add(i + 1)
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                out.add(j + 1)
                j += 1
            i = j
        else:
            i += 1
    return out


def walk(code: types.CodeType):
    yield code
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            yield from walk(c)


def static_info(path: Path):
    src = path.read_text(encoding="utf-8")
    code = compile(src, str(path), "exec")
    excl = excluded_lines(src)
    lines, branches = set(), set()
    for co in walk(code):
        for _, _, ln in co.co_lines():
            if ln and ln not in excl:
                lines.add(ln)
        ins = list(dis.get_instructions(co))
        for n in ins:
            if n.opname in COND and n.positions and n.positions.lineno and n.positions.lineno not in excl:
                branches.add((co.co_qualname, co.co_firstlineno, n.offset, n.positions.lineno))
    return lines, branches, len(excl)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "coverage.json"))
    ap.add_argument("pytest_args", nargs="*")
    args = ap.parse_args()
    args.out = str(Path(args.out).resolve())  # resolve before chdir into backend/

    files = {str(p) for p in target_files()}
    hit_lines: dict[str, set[int]] = {f: set() for f in files}
    outcomes: dict[tuple, set[str]] = {}
    fallthrough: dict[tuple, int] = {}
    M = sys.monitoring
    tool = M.COVERAGE_ID
    M.use_tool_id(tool, "hdews-coverage")

    def on_line(code, line):
        f = code.co_filename
        if f in files:
            hit_lines[f].add(line)
        return M.DISABLE  # each location only needs to be seen once

    def on_branch(code, src, dest):
        f = code.co_filename
        if f not in files:
            return M.DISABLE
        key = (f, code.co_qualname, code.co_firstlineno, src)
        if key not in fallthrough:
            ins = list(dis.get_instructions(code))
            for k, n in enumerate(ins):
                if n.offset == src:
                    fallthrough[key] = ins[k + 1].offset
                    break
        outcomes.setdefault(key, set()).add("fall" if dest == fallthrough.get(key) else "jump")
        return None

    M.register_callback(tool, M.events.LINE, on_line)
    M.register_callback(tool, M.events.BRANCH, on_branch)
    M.set_events(tool, M.events.LINE | M.events.BRANCH)

    os.chdir(ROOT / "backend")
    sys.path.insert(0, str(ROOT / "backend"))
    sys.path.insert(0, str(ROOT))
    import pytest
    rc = pytest.main(["-q", "-p", "no:cacheprovider", *args.pytest_args])
    M.set_events(tool, 0)
    M.free_tool_id(tool)

    report = {"pytest_exit_code": int(rc), "files": {}, "groups": {}}
    for f in sorted(files):
        lines, branches, n_excl = static_info(Path(f))
        hit = hit_lines[f] & lines
        b_total = 2 * len(branches)
        b_hit = sum(len(outcomes.get((f, q, fl, off), set())) for q, fl, off, _ in branches)
        partial = sorted({ln for q, fl, off, ln in branches if len(outcomes.get((f, q, fl, off), set())) < 2})
        rel = str(Path(f).relative_to(ROOT))
        report["files"][rel] = {
            "lines": len(lines), "lines_hit": len(hit), "line_pct": round(100 * len(hit) / len(lines), 1) if lines else 100.0,
            "branches": b_total, "branches_hit": b_hit, "branch_pct": round(100 * b_hit / b_total, 1) if b_total else 100.0,
            "missing_lines": sorted(lines - hit_lines[f]), "partial_branch_lines": partial, "excluded_lines": n_excl,
        }
    for name, prefixes in GROUPS.items():
        members = [r for r in report["files"] if any(p in r for p in prefixes)]
        L = sum(report["files"][m]["lines"] for m in members)
        LH = sum(report["files"][m]["lines_hit"] for m in members)
        B = sum(report["files"][m]["branches"] for m in members)
        BH = sum(report["files"][m]["branches_hit"] for m in members)
        report["groups"][name] = {"files": members, "line_pct": round(100 * LH / L, 1) if L else None,
                                  "branch_pct": round(100 * BH / B, 1) if B else None, "lines": L, "branches": B}
    L = sum(v["lines"] for v in report["files"].values())
    LH = sum(v["lines_hit"] for v in report["files"].values())
    B = sum(v["branches"] for v in report["files"].values())
    BH = sum(v["branches_hit"] for v in report["files"].values())
    report["total"] = {"line_pct": round(100 * LH / L, 1), "branch_pct": round(100 * BH / B, 1), "lines": L, "branches": B}
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{'Group':40} {'lines':>7} {'branches':>9}")
    for name, g in report["groups"].items():
        print(f"{name:40} {g['line_pct']:>6}% {g['branch_pct'] if g['branch_pct'] is not None else '-':>8}%")
    print(f"{'TOTAL':40} {report['total']['line_pct']:>6}% {report['total']['branch_pct']:>8}%")
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())

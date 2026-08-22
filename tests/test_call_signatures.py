"""Every internal call must match the function it names.

Python resolves `repo.incident_detail(...)` at call time, so a wrong argument
order or a function that was renamed out from under a caller is invisible until
that exact line runs. Endpoints nobody clicked during a demo hid real breakage
this way: `/v1/actions` matched `plan_id` against a tenant id and always came
back empty, `/v1/plans/{id}` called a `plan_detail` that did not exist, and the
approval endpoint called a `record_approval` that did not exist either.

This walks the AST instead of the network: for every `<module>.<name>(...)`
where `<module>` is one of ours, check that `<name>` exists there and that the
arguments fit its signature. It needs no server and no database.
"""

from __future__ import annotations

import ast
import io
import os

import pytest

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services")


def _module_index() -> dict[str, dict]:
    """Full dotted module path -> what it defines.

    Keyed by dotted path, not basename: there are two `registry.py` files, and
    a basename index silently checks calls against the wrong one.
    """
    index: dict[str, dict] = {}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, os.path.dirname(ROOT)).replace(os.sep, "/")
            dotted = rel[:-3].replace("/", ".")
            try:
                tree = ast.parse(io.open(path, encoding="utf-8").read())
            except SyntaxError:
                continue
            names: set[str] = set()
            sigs: dict[str, tuple] = {}

            def note(node):
                a = node.args
                params = [x.arg for x in a.posonlyargs] + [x.arg for x in a.args]
                sigs[node.name] = (params, len(params) - len(a.defaults),
                                   {x.arg for x in a.kwonlyargs},
                                   bool(a.vararg), bool(a.kwarg))

            for n in tree.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(n.name)
                    note(n)
                elif isinstance(n, ast.ClassDef):
                    names.add(n.name)
                elif isinstance(n, ast.Assign):
                    names.update(t.id for t in n.targets if isinstance(t, ast.Name))
                elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                    names.add(n.target.id)
                elif isinstance(n, (ast.Import, ast.ImportFrom)):
                    names.update(al.asname or al.name.split(".")[0] for al in n.names)
                elif isinstance(n, (ast.If, ast.Try)):
                    # conditional and try/except definitions still define names
                    for sub in ast.walk(n):
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            names.add(sub.name)
                        elif isinstance(sub, ast.Assign):
                            names.update(t.id for t in sub.targets if isinstance(t, ast.Name))
            index[dotted] = {
                "names": names,
                "sigs": sigs,
                "path": path,
                # a module with __getattr__ can serve anything; do not judge it
                "dynamic": any(isinstance(n, ast.FunctionDef) and n.name == "__getattr__"
                               for n in tree.body),
            }
    return index


def _aliases(tree: ast.AST, index: dict) -> dict[str, str]:
    """Local name -> full dotted module, for our own modules only."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("services"):
            for al in n.names:
                cand = f"{n.module}.{al.name}"
                if cand in index:
                    out[al.asname or al.name] = cand
        elif isinstance(n, ast.Import):
            for al in n.names:
                if al.name in index:
                    out[al.asname or al.name.split(".")[-1]] = al.name
    return out


def _optional_hooks(tree: ast.AST) -> set[tuple[str, str]]:
    """(module, attribute) pairs the file tests for with `hasattr` first.

    A guarded call is a deliberate seam, not a mistake: `Snapshot.take` uses one
    so it can hand over to `evidence.take_snapshot` if that ever exists.
    """
    out: set[tuple[str, str]] = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "hasattr" and len(n.args) == 2
                and isinstance(n.args[0], ast.Name)
                and isinstance(n.args[1], ast.Constant)
                and isinstance(n.args[1].value, str)):
            out.add((n.args[0].id, n.args[1].value))
    return out


def _problems() -> list[str]:
    index = _module_index()
    found: list[str] = []
    for dotted, info in index.items():
        try:
            tree = ast.parse(io.open(info["path"], encoding="utf-8").read())
        except SyntaxError:
            continue
        alias = _aliases(tree, index)
        optional = _optional_hooks(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)):
                continue
            mod, fn = node.func.value.id, node.func.attr
            if mod not in alias or (mod, fn) in optional:
                continue
            target = index[alias[mod]]
            if target["dynamic"] or target["path"] == info["path"]:
                continue
            where = f'{dotted.replace(".", "/")}.py:{node.lineno}  {mod}.{fn}(...)'

            if fn not in target["names"]:
                found.append(f"{where} -> not defined in {alias[mod]}")
                continue
            if fn not in target["sigs"]:
                continue  # a class or a constant, not a function we can check
            params, required, kwonly, has_vararg, has_kwarg = target["sigs"][fn]
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            if any(k.arg is None for k in node.keywords):
                continue  # **kwargs splat: the call site is dynamic
            npos = len(node.args)
            kwnames = {k.arg for k in node.keywords if k.arg}
            if not has_vararg and npos > len(params):
                found.append(f"{where} -> {npos} positional args, {fn}{tuple(params)} takes {len(params)}")
                continue
            missing = [p for p in params[:required] if p not in (set(params[:npos]) | kwnames)]
            if missing:
                found.append(f"{where} -> missing required {missing}; signature is {fn}{tuple(params)}")
                continue
            unknown = kwnames - set(params) - kwonly
            if unknown and not has_kwarg:
                found.append(f"{where} -> unknown keyword(s) {sorted(unknown)}; signature is {fn}{tuple(params)}")
    return sorted(set(found))


def test_no_internal_call_contradicts_its_target():
    problems = _problems()
    assert not problems, (
        f"{len(problems)} internal call(s) do not match the function they name:\n  "
        + "\n  ".join(problems)
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

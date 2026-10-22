"""Missing-name scan: names a module loads that it neither defines, imports nor
gets from builtins. argv: files. (A NameError in a function body passes a smoke
import and waits for its line to run.)"""
import ast, builtins, io, sys
bad = 0
for path in sys.argv[1:]:
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    defined = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__all__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
            if not isinstance(node, ast.ClassDef):
                a = node.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
                    defined.add(arg.arg)
        elif isinstance(node, ast.Lambda):
            a = node.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
                defined.add(arg.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            defined.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            defined.add(node.name)
    # Annotations are never evaluated under `from __future__ import annotations`,
    # so a name used only there is inert (SET_PLAYBOOK: "read as false positives").
    lazy = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names) for n in tree.body)
    inert = set()
    if lazy:
        for node in ast.walk(tree):
            notes = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                notes += [x.annotation for x in a.posonlyargs + a.args + a.kwonlyargs if x.annotation]
                notes += [x.annotation for x in (a.vararg, a.kwarg) if x is not None and x.annotation]
                if node.returns:
                    notes.append(node.returns)
            elif isinstance(node, ast.AnnAssign):
                notes.append(node.annotation)
            for note in notes:
                inert.update(id(n) for n in ast.walk(note))
    loaded = {(n.id, n.lineno) for n in ast.walk(tree)
              if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and id(n) not in inert}
    missing = sorted({(name, line) for name, line in loaded if name not in defined})
    for name, line in missing:
        print(f"MISSING {path}:{line} {name}"); bad += 1
print("missing names:", bad)

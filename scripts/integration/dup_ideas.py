"""Names (top-level def/class/assignment, and methods) defined in 2+ modules
under engine/ and web/ that did not exist at <base>. argv: base rev."""
import ast, io, os, subprocess, sys, collections
base = sys.argv[1]

def names_of(src):
    out = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out.add(sub.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out

now = collections.defaultdict(set)
for root in ("engine", "web"):
    for d, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(d, f).replace("\\", "/")
                for n in names_of(io.open(path, encoding="utf-8").read()):
                    now[n].add(path)
old = set()
listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", base, "engine", "web"], capture_output=True, text=True).stdout.split("\n")
for path in listing:
    if path.endswith(".py"):
        src = subprocess.run(["git", "show", f"{base}:{path}"], capture_output=True).stdout.decode("utf-8", "replace")
        old |= names_of(src)
hits = {n: sorted(p) for n, p in now.items() if len(p) > 1 and n not in old and not n.startswith("__") and n not in ("logger", "log")}
print("new names defined in 2+ modules:", len(hits))
for n, paths in sorted(hits.items()):
    print(f"  {n}: {paths}")

"""Report same-scope duplicate def/class names in the given files (merge shadowing)."""
import ast, io, sys
bad = 0
for path in sys.argv[1:]:
    try:
        tree = ast.parse(io.open(path, encoding="utf-8").read())
    except SyntaxError as exc:
        print("SYNTAX", path, exc); bad += 1; continue
    def scan(body, scope):
        global bad
        seen = {}
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # property setters / overloads legitimately repeat a name
                decos = [ast.unparse(d) for d in node.decorator_list]
                if any(d.endswith((".setter", ".deleter")) or d == "overload" for d in decos):
                    continue
                if node.name in seen:
                    print(f"DUP {path}:{node.lineno} {scope}{node.name} (first at {seen[node.name]})"); bad += 1
                seen[node.name] = node.lineno
                if isinstance(node, ast.ClassDef):
                    scan(node.body, scope + node.name + ".")
    scan(tree.body, "")
print("duplicates:", bad)

import sys
sys.path.insert(0, ".")
from engine.grammar import parse_line, lower_ability
def show(line):
    try:
        node = parse_line(line)
    except Exception as e:
        print("PARSE FAIL", line[:70], "|", type(e).__name__, e); return
    try:
        ins = lower_ability(node)
    except Exception as e:
        print("LOWER FAIL", line[:70], "|", type(e).__name__, e); return
    print("OK ", line[:70])
    for i in ins:
        print("     ", i.kind, i.payload)
for l in sys.argv[1:]:
    show(l)

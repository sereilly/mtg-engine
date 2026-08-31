import sys
sys.path.insert(0, '.')
from engine.grammar import parse_line
from engine.grammar.lower import lower_ability
for ln in ["Untap it.", "Untap that creature.", "Untap it and remove it from combat."]:
    try:
        node = parse_line(ln)
        print(repr(ln), "->", lower_ability(node))
    except Exception as e:
        print(repr(ln), "FAIL", type(e).__name__, e)

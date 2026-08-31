import sys
sys.path.insert(0, '.')
from engine.grammar import parse_line, GrammarError
from engine.grammar.lower import lower_ability
from engine.grammar.stream import TokenStream
from engine.grammar.lexer import tokenize
from engine.grammar.references import parse_recipient
for ph in ["two target blocked attacking creatures", "target blocked attacking creature",
           "two target attacking creatures", "blocked attacking creature",
           "two target blocking creatures"]:
    st = TokenStream(tokenize(ph))
    try:
        r = parse_recipient(st)
        rest = " ".join(t.text for t in st.tokens[st.pos:])
        f = r.filter
        print(repr(ph), "->", "quant=%r count=%r targeted=%r types=%r attacking=%r blocked=%r blocking=%r" % (
            r.quantifier, r.count, r.targeted, f.card_types, f.attacking, f.blocked, f.blocking), "| REST:", rest)
    except Exception as e:
        print(repr(ph), "FAIL", type(e).__name__, e)
print()
for ln in ["Tap two target attacking creatures.", "Tap two target blocked attacking creatures."]:
    try:
        print(repr(ln), "->", lower_ability(parse_line(ln)))
    except Exception as e:
        print(repr(ln), "FAIL", type(e).__name__, e)

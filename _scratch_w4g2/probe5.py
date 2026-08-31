import sys
sys.path.insert(0, '.')
from engine.grammar.stream import TokenStream
from engine.grammar.lexer import tokenize
from engine.grammar.references import parse_recipient
for ph in ["two target blocked attacking creatures", "target blocked attacking creature",
           "two target attacking creatures",
           "each creature that's blocking exactly one of those attacking creatures"]:
    lex = tokenize(ph)
    st = TokenStream(lex.tokens, lex.normalized)
    try:
        r = parse_recipient(st)
        rest = " ".join(t.text for t in lex.tokens[st.pos:])
        f = r.filter
        print(repr(ph))
        print("   quant=%r count=%r targeted=%r types=%r attacking=%r blocked=%r blocking=%r countx=%r" % (
            r.quantifier, r.count, r.targeted, f.card_types, f.attacking, f.blocked, f.blocking, r.count_from_x))
        print("   REST:", rest)
    except Exception as e:
        print(repr(ph), "FAIL", type(e).__name__, e)

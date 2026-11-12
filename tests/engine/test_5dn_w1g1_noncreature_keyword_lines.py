"""Guard: no supported noncreature card drops a keyword line nothing admits.

The creature gate refuses a card over any line it cannot read
(``line_classification``); the artifact, enchantment, instant and sorcery gate
is "supported when any line is" (``oracle._compile_card_oracle``), so a
printed keyword line ``IMPLEMENTED_KEYWORDS`` does not admit — and no rewrite
consumed — is simply dropped there. That is how all six of Fifth Dawn's
noncreature sunburst cards (Baton of Courage, Clearwater Goblet, Engineered
Explosives, Heliophial, Infused Arrows, Pentad Prism) arrived "supported",
entering with no counters at all, while the eight sunburst creatures beside
them refused. ``parse_coverage`` saw it; the support count did not.

Validated backwards: on the tree before ``engine/sunburst.py`` (its rewrite
and its ``unread_sunburst_line`` gate monkeypatched away) this census names
exactly those six, over both manifest roles; over the shipped pool it named
none. It walks the shipped pool — the cards a player can deck — so a measured
set's gaps are its round's work list, and under ``MTG_PROMOTE`` the set being
promoted is walked too.
"""

from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar import ast
from engine.grammar.errors import GrammarError
from engine.grammar.parser import parse_line
from engine.keyword_lines import _is_supported_keyword_line
from engine.line_rewrites import expand_card_lines
from engine.oracle import compile_card_oracle

_NONCREATURE = ("artifact", "enchantment", "instant", "sorcery")


def _census():
    examined = 0
    dropped: list[str] = []
    seen: set[str] = set()
    for path in manifest_set_paths():
        for unit in compilation_units(load_cards(path)):
            if unit.name in seen or unit.primary_type not in _NONCREATURE:
                continue
            seen.add(unit.name)
            if not compile_card_oracle(unit).supported:
                continue
            examined += 1
            for line in expand_card_lines(unit):
                if not line.strip():
                    continue
                try:
                    node = parse_line(line, card_name=unit.name)
                except GrammarError:
                    continue
                if isinstance(node, ast.KeywordLine) and not _is_supported_keyword_line(line):
                    dropped.append(f"{unit.name}: {line}")
    return examined, dropped


def test_no_supported_noncreature_card_carries_a_keyword_line_nothing_admits():
    examined, dropped = _census()
    # A floor on what was examined: the shipped pool holds ~3,000 supported
    # noncreature units, and a census that read none would pass on nothing.
    assert examined >= 2500, examined
    assert dropped == [], (
        "supported noncreature cards whose keyword line no gate admits — the "
        "card enters without the keyword's behaviour: " + "; ".join(dropped)
    )

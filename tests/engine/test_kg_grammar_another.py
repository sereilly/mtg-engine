"""Round kg/grammar: a printed "another" means one thing wherever the grammar
reads it, and the pool's every cost, lone target and trigger subject that
prints the word compiles to a key something enforces.

"Sacrifice **another** creature" (Hobblefiend), "Whenever **another** creature
enters" (Soul Warden), "{T}: **Another** target Minotaur creature gets +1/+1"
(Anaba Ancestor). In each, nothing earlier in the sentence was chosen, so the
only object the word can differ from is the ability's own source (CR 113.7) —
the filter's ``other_than_source``, which pays out as ``exclude_self``.

The cost reader (``costs._parse_cost_object``), the subject reader
(``phrases.parse_subject_filter_at``) and the counters event's object
(``trigger_matched``) each used to consume the word themselves, ahead of
``parse_target_spec``, whose two "another" branches read it as a distinctness
from an earlier choice (``distinct_from_prior``). They now take it from
``parse_target_spec`` and turn it into the source exclusion through one helper,
``references.excluding_source``. Measured before landing: ``oracle_diff`` moved
no program, and a differential of the cost and subject readers over every
"another …" phrase the pool prints (447 phrases, both plural settings, 846
admitted results) read identically before and after.

The census below is the guard on that meaning. It is validated by switching the
helper off (the exclusion dropped, the distinctness cleared): the cost and
subject positions then come out with no key at all, and it names Hobblefiend,
Orc General, Thopter Squadron and the trigger subjects.
"""

from __future__ import annotations

import re

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar.costs import _parse_cost_object
from engine.grammar.errors import GrammarError
from engine.grammar.lexer import tokenize
from engine.grammar.phrases import parse_subject_filter
from engine.grammar.references import excluding_source, parse_target_spec
from engine.grammar.stream import TokenStream
from engine.oracle import compiled_units
from engine.oracle_types import OracleInstruction

_ANOTHER = re.compile(r"\banother\b", re.I)

#: What a printed "another" may compile to, by where it is printed. The
#: grammar's own readers all write ``exclude_self``; the others are readers
#: whose word is measured against something that is not the battlefield source.
_COST_KEYS = frozenset({"exclude_self"})
_LONE_TARGET_KEYS = frozenset({
    "exclude_self",
    # "return **another** target artifact card from your graveyard" (Junk
    # Diver): the source is a card in that graveyard by then.
    "exclude_source_card",
    # "…have **it** deal damage … to **another** target creature" (Farrel's
    # Mantle): the sentence's earlier object is the enchanted creature.
    "exclude_attached",
})
_TRIGGER_KEYS = frozenset({
    "exclude_self",
    # The regex front end's rows, whose fixed text requires the word and whose
    # event filter enforces it: City of Traitors, Planar Void.
    "other_land", "another_card",
})
#: Trigger kinds whose regex row prints "another" as fixed text (a wording
#: without it does not match), enforced by the kind's event filter.
_TRIGGER_KINDS_REQUIRING_THE_WORD = frozenset({
    "counters_put_on_creature",
    # "When you gain control of this enchantment **from another player**"
    # (Risky Move, ONS W1G10): the word is the kind's whole meaning — the
    # control seam fires it only when the permanent moves between two seats.
    "gain_control_of_source",
})
#: "this creature **or another** creature you control" — a union with the
#: source: the phrase keeps its exclusion and the condition puts the source
#: back by identity (``<stem>_includes_source``), which
#: ``tests/regressions/test_w1g7_own_death_and_self_union.py`` holds.
_UNION_WITH_SOURCE = re.compile(r"\bthis \w+ or another\b", re.I)


def _keys(value, out: set) -> set:
    if isinstance(value, OracleInstruction):
        _keys(value.payload, out)
    elif isinstance(value, dict):
        for key, inner in value.items():
            if inner is not False and inner is not None:
                out.add(key)
            _keys(inner, out)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            _keys(inner, out)
    elif hasattr(value, "__dataclass_fields__"):
        for field in value.__dataclass_fields__:
            _keys(getattr(value, field), out)
    return out


@pytest.fixture(scope="module")
def another_census():
    """``{"cost" | "target" | "trigger": [(card, printed text, keys)]}`` over
    every supported compilation unit, both manifest roles."""
    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    found = {"cost": [], "target": [], "trigger": []}
    for card, program in compiled_units(sorted(pool.values(), key=lambda c: c.name)):
        if not program.supported:
            continue
        for ability in program.activated_abilities:
            line = ability.source_line or ""
            if ":" in line and _ANOTHER.search(line.split(":", 1)[0]):
                found["cost"].append(
                    (card.name, line.split(":", 1)[0], _keys(ability.cost, set()))
                )
        for ability in program.triggered_abilities:
            raw = ability.condition.raw_text if ability.condition else ""
            if _ANOTHER.search(raw or "") and not _UNION_WITH_SOURCE.search(raw):
                keys = set(ability.condition.payload) | _keys(
                    ability.condition.payload, set()
                )
                if ability.condition.kind in _TRIGGER_KINDS_REQUIRING_THE_WORD:
                    keys.add(ability.condition.kind)
                found["trigger"].append((card.name, raw, keys))
        whole = _keys(
            (program.instructions, program.activated_abilities,
             program.triggered_abilities), set(),
        )
        for line in (card.oracle_text or "").split("\n"):
            low = line.lower()
            if "another target" in low and low.count("target") == 1:
                found["target"].append((card.name, line, whole))
    return found


def test_the_census_examined_each_position(another_census):
    """The floor: the three positions the readers serve, each populated."""
    assert len(another_census["cost"]) >= 3
    assert len(another_census["target"]) >= 10
    assert len(another_census["trigger"]) >= 10


@pytest.mark.parametrize("position, allowed", [
    ("cost", _COST_KEYS),
    ("target", _LONE_TARGET_KEYS),
    ("trigger", _TRIGGER_KEYS | _TRIGGER_KINDS_REQUIRING_THE_WORD),
])
def test_every_printed_another_compiles_to_an_exclusion(another_census, position, allowed):
    """A printed "another" that reaches no exclusion key is a word dropped: the
    cost would take the source itself, the trigger fire on its own entry."""
    dropped = {
        name: text for name, text, keys in another_census[position]
        if not keys & allowed
    }
    assert dropped == {}


def test_the_grammar_readers_give_the_word_one_meaning():
    """The cost, the subject and a lone target's spec read "another" through
    one reader and one helper, so the filter they produce is one filter."""
    phrase = "another creature you control"

    def stream():
        return TokenStream(tokenize(phrase).tokens, phrase)

    cost = _parse_cost_object(stream(), "sacrifice")
    subject = parse_subject_filter(phrase)
    spec = parse_target_spec(stream())
    assert spec.distinct_from_prior, "the reader of the word records the distinctness"
    lone = excluding_source(spec)

    assert cost == subject == lone.filter
    assert cost.other_than_source and not lone.distinct_from_prior
    assert cost.to_payload()["exclude_self"] is True


def test_another_enchanted_names_no_set_to_exclude_from():
    """"Enchanted creature" alone is the Aura's host (CR 303.4b), a referent;
    the old readers refused "another" in front of it, and still do."""
    phrase = "another enchanted creature"

    with pytest.raises(GrammarError):
        _parse_cost_object(TokenStream(tokenize(phrase).tokens, phrase), "sacrifice")
    assert parse_subject_filter(phrase) is None

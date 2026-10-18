"""An ability-word paragraph that says "…instead" is the last sentence of the
paragraph above it (``oracle.expand_instead_paragraph_lines``, W1G2).

"Thermal Blast deals 3 damage to target creature.\\nThreshold — Thermal Blast
deals 5 damage instead if there are seven or more cards in your graveyard."
Every reader of a card's lines takes a line as a unit, so read as printed the
second paragraph is either nothing (it names no recipient) or a second effect
(3 damage, then 5). The rewrite joins the two so the sentence loop can fold
them into one conditional — and it is the only rewrite in
``expand_ability_lines`` that *joins*, so what it must not join is most of
what is checked here.

Pool-wide and about the compiler, which is why it is not a per-set test: the
template is threshold's in Odyssey and hellbent's and metalcraft's after it.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import CardDefinition
from engine.oracle import (
    compile_card_oracle, expand_ability_lines, expand_instead_paragraph_lines,
)
from engine.oracle_types import strip_ability_word

_W1G2_POOL = load_cards(manifest_set_paths(include_measured=True))


def _w1g2_spell(name: str, text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{R}", cmc=1.0, type_line="Instant",
        oracle_text=text, colors=("R",), color_identity=("R",), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Instant"},
    )


def test_an_ability_word_instead_paragraph_joins_the_paragraph_above():
    """The ability word is dropped with the break it caused (CR 207.2c: it
    has no rules meaning), and the two paragraphs are one line of two
    sentences."""
    printed = (
        "Thermal Blast deals 3 damage to target creature.\n"
        "Threshold — Thermal Blast deals 5 damage instead if there are seven "
        "or more cards in your graveyard."
    )

    assert expand_instead_paragraph_lines(printed) == (
        "Thermal Blast deals 3 damage to target creature. Thermal Blast deals "
        "5 damage instead if there are seven or more cards in your graveyard."
    )
    assert expand_ability_lines(printed, card_name="Thermal Blast").count("\n") == 0


def test_the_join_keeps_the_paragraphs_before_and_after_it():
    """Only the pair is touched: a paragraph in front of it and one behind it
    stay their own lines, in order."""
    printed = (
        "Flash\n"
        "Pile Blast deals 2 damage to any target.\n"
        "Hellbent — Pile Blast deals 4 damage instead if you have no cards in hand.\n"
        "Draw a card."
    )

    assert expand_instead_paragraph_lines(printed).splitlines() == [
        "Flash",
        "Pile Blast deals 2 damage to any target. Pile Blast deals 4 damage "
        "instead if you have no cards in hand.",
        "Draw a card.",
    ]


@pytest.mark.parametrize(
    "printed",
    [
        # No ability word: the break is not typography, so nothing says the
        # second paragraph belongs to the first.
        "Pile Blast deals 2 damage to any target.\n"
        "Pile Blast deals 4 damage instead if you have no cards in hand.",
        # "Would": CR 614.1a's replacement of an event, complete in itself.
        "Pile Blast deals 2 damage to any target.\n"
        "Threshold — If a creature dealt damage this way would die this turn, "
        "exile it instead.",
        # "Instead of": a comparison inside one sentence.
        "Pile Blast deals 2 damage to any target.\n"
        "Threshold — Lands produce {R} instead of any other type.",
        # An ability of its own, whose "instead" is about its own effect.
        "Pile Blast deals 2 damage to any target.\n"
        "Threshold — {T}: Draw two cards instead if you control a Swamp.",
        "Pile Blast deals 2 damage to any target.\n"
        "Threshold — Whenever a creature dies, draw two cards instead of one.",
        # Nothing above it that ends a sentence: a keyword line is not an
        # effect an "instead" could replace.
        "Kicker {2}\n"
        "Threshold — Pile Blast deals 4 damage instead if you have no cards in hand.",
        # No "instead" at all: an additive threshold paragraph (Demoralize).
        "All creatures gain menace until end of turn.\n"
        "Threshold — If there are seven or more cards in your graveyard, "
        "creatures can't block this turn.",
        # First paragraph of the card: nothing above it.
        "Threshold — Pile Blast deals 4 damage instead if you have no cards in hand.",
    ],
)
def test_a_paragraph_the_gate_does_not_name_is_left_exactly_as_printed(printed):
    assert expand_instead_paragraph_lines(printed) == printed


def test_a_reminder_after_the_first_paragraph_does_not_hide_its_full_stop():
    """"…until end of turn. (They can't be blocked except by two or more
    creatures.)" still ends a sentence: the reminder is looked past, and kept."""
    printed = (
        "Pile Blast deals 2 damage to any target. (It can hit a player.)\n"
        "Threshold — Pile Blast deals 4 damage instead if there are seven or "
        "more cards in your graveyard."
    )

    joined = expand_instead_paragraph_lines(printed)

    assert "\n" not in joined and "(It can hit a player.)" in joined
    program = compile_card_oracle(_w1g2_spell("Pile Blast", printed))
    assert program.supported
    assert [i.kind for i in program.instructions] == ["if_then"]


def test_the_joined_pair_compiles_to_one_conditional_with_two_arms():
    """What the join is for. The replacing sentence names no recipient, so it
    takes the replaced sentence's — one target, whichever amount (CR 601.2c)."""
    program = compile_card_oracle(_w1g2_spell(
        "Pile Blast",
        "Pile Blast deals 2 damage to any target.\n"
        "Threshold — Pile Blast deals 4 damage instead if there are seven or "
        "more cards in your graveyard.",
    ))

    assert program.supported
    (gate,) = program.instructions
    (then,), (otherwise,) = gate.payload["then"], gate.payload["else"]
    assert (then.payload["amount"], otherwise.payload["amount"]) == (4, 2)
    assert then.payload["targets"] == otherwise.payload["targets"]


def test_a_trailing_instead_cannot_replace_a_different_kind_of_sentence():
    """The arms must be one action printed twice. "Draw a card. / Threshold —
    Pile Blast deals 4 damage instead if …" replaces a draw with a burn, which
    is some other card: the line refuses rather than compiling either way."""
    program = compile_card_oracle(_w1g2_spell(
        "Pile Blast",
        "Draw a card.\n"
        "Threshold — Pile Blast deals 4 damage to any target instead if there "
        "are seven or more cards in your graveyard.",
    ))

    assert not program.supported


def _w1g2_instead_paragraphs(card) -> list[str]:
    """The printed paragraphs of *card* the gate is written for: opened by an
    ability word, saying "instead" and neither "would" nor "instead of"."""
    found = []
    lines = [line.strip() for line in (card.oracle_text or "").splitlines()]
    for position, line in enumerate(lines):
        sentence = strip_ability_word(line)
        lowered = sentence.lower()
        if (
            position
            and sentence != line
            and " instead" in lowered
            and "would" not in lowered
            and "instead of" not in lowered
            and ":" not in lowered
        ):
            found.append(line)
    return found


def test_every_instead_paragraph_in_the_pool_is_joined_and_nothing_else_moves():
    """Both directions, over both manifest roles.

    * Every card printing such a paragraph has it joined: no line of its
      expanded text still opens with the ability word, and where the card
      compiles its program holds a conditional with **both** arms — the
      replaced sentence is an arm, never a second step.
    * A card printing none is returned byte for byte, so the one rewrite that
      joins lines cannot have joined anything it was not written for.

    A floor on the first half, because a census that examined nothing passes.
    """
    joined, compiled, untouched = [], [], 0
    for card in compilation_units(_W1G2_POOL):
        text = card.oracle_text or ""
        paragraphs = _w1g2_instead_paragraphs(card)
        rewritten = expand_instead_paragraph_lines(text)
        if not paragraphs:
            assert rewritten == text, card.name
            untouched += 1
            continue
        joined.append(card.name)
        assert rewritten.count("\n") == text.count("\n") - len(paragraphs), card.name
        for paragraph in paragraphs:
            assert strip_ability_word(paragraph) in rewritten, card.name
            assert paragraph not in rewritten.splitlines(), card.name
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        compiled.append(card.name)
        gates = [i for i in program.instructions if i.kind == "if_then"]
        assert gates, (card.name, [i.kind for i in program.instructions])
        assert all(g.payload.get("then") and g.payload.get("else") for g in gates), card.name

    assert len(joined) >= 3, joined
    assert len(compiled) >= 3, (joined, compiled)
    assert untouched >= 5000


# ---------------------------------------------------------------------------
# What the joined pair needed of the "instead" rider
# (``engine/grammar/conditional_instead.py``). Invented lines, at the parse.
# ---------------------------------------------------------------------------

from engine.grammar import ast as _w1g2_ast, compile_line as _w1g2_compile_line
from engine.grammar.errors import GrammarError as _W1G2GrammarError
from engine.grammar.parser import parse_line as _w1g2_parse_line

_W1G2_IF = "there are seven or more cards in your graveyard"


def _w1g2_pair(line: str, card_name: "str | None" = None):
    statement = _w1g2_parse_line(line, card_name=card_name).statement
    assert isinstance(statement, _w1g2_ast.Conditional), statement
    assert statement.otherwise is not None
    return statement


def test_the_trailing_spelling_is_the_fronted_one_read_from_the_other_end():
    """"A. B instead **if** C." and "A. **If** C, B instead." are one pair:
    the same condition, the same two arms."""
    trailing = _w1g2_pair(
        f"You gain 4 life. You gain 8 life instead if {_W1G2_IF}."
    )
    fronted = _w1g2_pair(
        f"You gain 4 life. If {_W1G2_IF}, you gain 8 life instead."
    )

    assert trailing == fronted


@pytest.mark.parametrize("line", [
    # No "instead": the trailing "if" gates a second effect, which is the
    # sentence loop's reading and not a replacement.
    f"You gain 4 life. You gain 8 life if {_W1G2_IF}.",
    # A replaced sentence with a guard of its own would need two trailing ifs.
    "Destroy target artifact if its mana value is 2 or less. Destroy that "
    f"artifact if its mana value is 5 or less instead if {_W1G2_IF}.",
    # Another kind of sentence is another card.
    f"You gain 4 life. Draw two cards instead if {_W1G2_IF}.",
])
def test_a_trailing_if_that_is_not_this_pair_is_not_folded_into_one(line):
    """Either the line is something else and parses as that — a second step —
    or it refuses. It is never a conditional with the first sentence as its
    other arm."""
    try:
        statement = _w1g2_parse_line(line).statement
    except _W1G2GrammarError:
        return
    assert not (
        isinstance(statement, _w1g2_ast.Conditional) and statement.otherwise is not None
    ), statement


def test_a_replacement_may_say_the_sentence_again_and_then_make_tokens():
    """"…instead destroy all creatures, **then create two 1/1 white Spirit
    creature tokens with flying**." The first step restates the replaced
    sentence, kind for kind; what follows "then" only the replacing arm does."""
    pair = _w1g2_pair(
        f"Destroy all creatures. If {_W1G2_IF}, instead destroy all creatures, "
        "then create two 1/1 white Spirit creature tokens with flying."
    )

    assert isinstance(pair.otherwise, _w1g2_ast.Destroy)
    assert [type(step) for step in pair.then.steps] == [
        _w1g2_ast.Destroy, _w1g2_ast.CreateToken,
    ]


@pytest.mark.parametrize("line", [
    # A continuation that is not one of the kinds the rider adds.
    f"Destroy all creatures. If {_W1G2_IF}, instead destroy all creatures, "
    "then draw a card.",
    # A head that does not restate the replaced sentence.
    f"Destroy all creatures. If {_W1G2_IF}, instead draw a card, then create "
    "two 1/1 white Spirit creature tokens with flying.",
])
def test_a_continued_replacement_restates_first_and_adds_only_what_is_listed(line):
    with pytest.raises(_W1G2GrammarError):
        _w1g2_parse_line(line)


def test_a_no_regeneration_rider_reaches_the_destroy_inside_a_then_sentence():
    """Kirtar's Wrath prints the rider once per sentence. The second one
    follows a "…, then create …" sentence and has to mark the destroy in it:
    read onto the replaced arm alone it marks a sweep that already says so and
    leaves the one that matters regenerable."""
    pair = _w1g2_pair(
        f"Destroy all creatures. If {_W1G2_IF}, instead destroy all creatures, "
        "then create two 1/1 white Spirit creature tokens with flying. "
        "Creatures destroyed this way can't be regenerated."
    )

    assert pair.then.steps[0].no_regen
    assert not pair.otherwise.no_regen, "the replaced sentence printed no rider here"

    both = _w1g2_pair(
        "Destroy all creatures. They can't be regenerated. "
        f"If {_W1G2_IF}, instead destroy all creatures, then create two 1/1 "
        "white Spirit creature tokens with flying. Creatures destroyed this "
        "way can't be regenerated."
    )
    assert both.then.steps[0].no_regen and both.otherwise.no_regen


def test_a_sacrifice_may_be_replaced_by_one_naming_somebody_else():
    """"Target player sacrifices a land of their choice. **Each player**
    sacrifices all lands they control instead if …" (Epicenter.) The second
    sentence points back at nobody, so it is kept as written; "that player"
    would have taken the target."""
    named = _w1g2_pair(
        "Target player sacrifices a land of their choice. Each player "
        f"sacrifices all lands they control instead if {_W1G2_IF}."
    )
    assert named.otherwise.player.kind == "target_player"
    assert named.then.player.kind == "each_player"

    back = _w1g2_pair(
        "Target player sacrifices a land of their choice. That player "
        f"sacrifices all lands they control instead if {_W1G2_IF}."
    )
    assert back.then.player == back.otherwise.player


def test_those_permanents_and_or_players_is_the_replaced_list_and_nothing_else():
    """The plural of "that permanent or player": after a list of "any
    target"s it is that list — one announcement for either arm (CR 601.2c).
    After one target, after a list of creatures, or on its own, it names
    nothing and the line refuses."""
    pair = _w1g2_pair(
        "Pile Rain deals 2 damage to each of up to three targets. Pile Rain "
        "deals 4 damage to each of those permanents and/or players instead "
        f"if {_W1G2_IF}.",
        card_name="Pile Rain",
    )
    assert pair.then.recipients == pair.otherwise.recipients
    assert pair.then.recipients[0].max_count == 3

    for line in (
        "Pile Rain deals 2 damage to any target. Pile Rain deals 4 damage to "
        f"each of those permanents and/or players instead if {_W1G2_IF}.",
        "Pile Rain deals 2 damage to each of up to three target creatures. "
        "Pile Rain deals 4 damage to each of those permanents and/or players "
        f"instead if {_W1G2_IF}.",
    ):
        with pytest.raises(_W1G2GrammarError):
            _w1g2_parse_line(line, card_name="Pile Rain")

    alone = _w1g2_compile_line(
        "Pile Rain deals 4 damage to each of those permanents and/or players.",
        card_name="Pile Rain",
    )
    assert alone.parsed and not alone.usable

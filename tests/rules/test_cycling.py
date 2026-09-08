"""Cycling — CR 702.29, and the zone rule that makes it safe (CR 113.6j).

The keyword's whole content is the activated ability CR 702.29a says it *is*,
so ``engine/cycling.py`` rewrites the printed line and everything downstream —
the grammar, the cost parser, the stack, the web layer — reads an ordinary
"{2}, Discard this card: Draw a card." That half is cheap to get right.

The half that is not is CR 702.29b: *"Although the cycling ability can be
activated only if the card is in a player's hand, it continues to exist while
the object is on the battlefield and in all other zones."* Six of Urza's Saga's
cycling cards are lands and eight are creatures, so the rewrite hands fourteen
permanents an activated ability they must not be able to use. Nothing in the
engine enforced that: ``Game.activate_from_hand`` asked
``ability.cost.discard_self`` and no path asked the negative, which is why M21's
Waker of Waves — shipped, promoted, verified — could stand on the battlefield
and draw off "{1}{U}, **Discard this card**" every turn, discarding nothing.

So these tests drive a real ``Game`` from both zones. The fixtures are
**invented** cards, because what is asserted is that the keyword works on
anything printing it; the per-card tests are in ``tests/sets/test_usg_*.py``.

``engine/cycling.py`` documents the rewrite and
``engine/activation_zones.py`` the zone read.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.activation_zones import (BATTLEFIELD, GRAVEYARD, HAND,
                                     ability_functions_from)
from engine.cycling import (cycling_cost, expand_cycling_line,
                            expand_cycling_lines, is_cycling_line,
                            unread_cycling_line)
from engine.models import CardDefinition, PlayerState, Permanent
from engine.oracle import compile_card_oracle, expand_ability_lines
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

_REMINDER = "({cost}, Discard this card: Draw a card.)"


def _cycler(
    name: str,
    *,
    cost: str = "{2}",
    type_line: str = "Instant",
    body: str = "Destroy target creature.",
    keyword: str = "Cycling",
) -> CardDefinition:
    """A card whose text is one effect line plus a cycling keyword line.

    The reminder text is printed too, because that is what the ingested cards
    carry and stripping it is part of what the reader has to do — and because
    the colon inside it is what a naive splitter takes for the ability's own.
    """
    reminder = " " + _REMINDER.format(cost=cost)
    lines = [body] if body else []
    lines.append(f"{keyword} {cost}{reminder}")
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "2", "2"
    return CardDefinition(
        name=name,
        mana_cost="{1}{U}",
        cmc=2.0,
        type_line=type_line,
        oracle_text="\n".join(lines),
        colors=(),
        color_identity=(),
        keywords=("Cycling",),
        produced_mana=(),
        raw=raw,
    )


def _game_with(card: CardDefinition, *, library: int = 5) -> tuple[Game, PlayerState]:
    filler = CardDefinition(
        name="Filler", mana_cost="", cmc=0.0, type_line="Land",
        oracle_text="{T}: Add {G}.", colors=(), color_identity=(), keywords=(),
        produced_mana=("G",), raw={"name": "Filler", "type_line": "Land"},
    )
    player = PlayerState(name="A", hand=[card], library=[filler] * library)
    game = Game(players=[player, PlayerState(name="B")])
    game.enforce_mana_costs = False
    return game, player


# ---------------------------------------------------------------------------
# CR 702.29a — the rewrite
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.29a")
def test_702_29a_cycling_means_discard_this_card_draw_a_card():
    """"Cycling [cost]" *means* "[Cost], Discard this card: Draw a card."

    Asserted on the rewrite itself, with the reminder text present, because the
    reminder is where a naive reader finds its colon.
    """
    line = "Cycling {2} ({2}, Discard this card: Draw a card.)"
    assert expand_cycling_line(line) == "{2}, Discard this card: Draw a card."
    assert cycling_cost(line) == "{2}"


@pytest.mark.cr("702.29a")
def test_702_29a_the_cost_is_read_from_the_line_not_assumed():
    """Every cycling cost in Urza's Saga is {2}; the rewrite parses it anyway.

    A coloured pip keeps its letter, which is what a set two blocks later needs
    and what an assumed {2} would have silently spent as generic.
    """
    assert expand_cycling_line("Cycling {1}{U}") == "{1}{U}, Discard this card: Draw a card."
    assert expand_cycling_line("Cycling {W}{W}") == "{W}{W}, Discard this card: Draw a card."


@pytest.mark.cr("702.29a")
def test_702_29a_the_rewrite_runs_before_any_line_is_classified():
    """Every other reader of a card's lines starts from ``expand_ability_lines``
    (``engine/legality.py``, ``scripts/parse_coverage.py``,
    ``scripts/hook_reliance.py``), so the rewrite has to be in it or those
    readers are looking at a different card."""
    card = _cycler("Rewritten")
    expanded = expand_ability_lines(card.oracle_text, card_name=card.name)
    assert "{2}, Discard this card: Draw a card." in expanded
    assert "Cycling {2}" not in expanded


@pytest.mark.cr("702.29a")
def test_702_29a_the_ability_compiles_and_the_card_is_supported():
    program = compile_card_oracle(_cycler("Compiled"))
    assert program.supported
    lines = [a.source_line for a in program.activated_abilities]
    assert "{2}, Discard this card: Draw a card." in lines


@pytest.mark.cr("702.29a", "601.2h")
def test_702_29a_cycling_discards_the_card_and_draws_one():
    """The Rock Hydra test: a real game, not a compiled claim.

    The card leaves the hand as the cost is paid, reaches the graveyard, and one
    card is drawn — and the *spell's own effect* does not happen, which is the
    difference between cycling a removal spell and casting it.
    """
    card = _cycler("Cycled", body="Destroy target creature.")
    game, player = _game_with(card)
    victim = Permanent(card=CardDefinition(
        name="Bear", mana_cost="", cmc=0.0, type_line="Creature — Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Bear", "type_line": "Creature — Bear",
                               "power": "2", "toughness": "2"},
    ))
    game.players[1].battlefield.append(victim)

    result = game.activate_from_hand(0, "Cycled")
    assert result.supported, result.details
    resolve_stack(game)

    assert player.hand and all(c.name != "Cycled" for c in player.hand)
    assert [c.name for c in player.graveyard] == ["Cycled"]
    assert len(player.hand) == 1
    assert len(player.library) == 4
    # The removal did not resolve: cycling is the ability, not the spell.
    assert [p.card.name for p in game.players[1].battlefield] == ["Bear"]


@pytest.mark.cr("702.29a", "601.2h")
def test_702_29a_an_unpayable_cycling_cost_leaves_the_card_in_hand():
    """CR 601.2h: an unpayable cost makes the ability unactivatable, and the
    refusal happens before anything is spent — the card is still in hand."""
    card = _cycler("Unpayable")
    game, player = _game_with(card)
    game.enforce_mana_costs = True

    result = game.activate_from_hand(0, "Unpayable")

    assert result.supported is False
    assert [c.name for c in player.hand] == ["Unpayable"]
    assert player.graveyard == []


# ---------------------------------------------------------------------------
# CR 702.29b / CR 113.6j — the zone
# ---------------------------------------------------------------------------


@pytest.mark.cr("113.6j", "702.29b")
def test_113_6j_a_cycling_ability_functions_only_from_a_hand():
    """CR 113.6j: an ability whose cost cannot be paid on the battlefield
    functions from wherever it can be paid. "Discard this card" is payable in a
    hand and nowhere else (CR 701.9a), so the derived zone is the hand — and it
    is derived from the *cost*, not from the keyword, so it reaches every card
    printed this way and names none."""
    program = compile_card_oracle(_cycler("Zoned", type_line="Land", body="{T}: Add {U}."))
    zones = [ability_functions_from(a) for a in program.activated_abilities]
    assert BATTLEFIELD in zones and HAND in zones
    assert GRAVEYARD not in zones


@pytest.mark.cr("113.6j", "702.29b")
def test_113_6j_a_permanents_ability_list_excludes_its_cycling_ability():
    """``usable_activated_abilities`` is the index the web layer, the AI and
    ``queue_permanent_ability`` all address an ability by, so the zone read
    belongs in it rather than at each caller."""
    program = compile_card_oracle(_cycler("Listed", type_line="Land", body="{T}: Add {U}."))
    battlefield = usable_activated_abilities(program)
    hand = usable_activated_abilities(program, zone=HAND)

    assert [a.source_line for a in battlefield] == ["{T}: Add {U}."]
    assert [a.source_line for a in hand] == ["{2}, Discard this card: Draw a card."]


@pytest.mark.cr("113.6j", "702.29b")
def test_113_6j_a_cycling_land_on_the_battlefield_cannot_cycle():
    """The failure this rule exists to prevent, in a game.

    Without the zone read the ability is simply run: a card is drawn, nothing is
    discarded, and the land stays on the battlefield to do it again next turn.
    Not a crash and not a missing ability — an ability that works more often
    than the card allows.
    """
    card = _cycler("Cycling Waste", type_line="Land", body="{T}: Add {U}.")
    game, player = _game_with(card)
    player.hand.clear()
    player.battlefield.append(Permanent(card=card))
    before = len(player.library)

    # The slot the ability used to occupy is gone from the permanent's list, so
    # a caller still holding the old index gets nothing rather than the draw.
    result = game.activate_permanent_ability(0, "Cycling Waste", ability_index=1)

    assert result.supported is False
    assert len(player.library) == before
    assert player.graveyard == []
    # …and its real ability still works, at the index the picker offers.
    assert game.activate_permanent_ability(0, "Cycling Waste", ability_index=0).supported


@pytest.mark.cr("113.6j", "702.29b")
def test_113_6j_a_cycling_creature_on_the_battlefield_is_refused_naming_the_zone():
    """The same rule on a permanent whose *only* ability is the cycling one.

    Eight of Urza's Saga's cycling cards are creatures, and for those the
    refusal is the whole answer rather than an index sliding — so it names the
    zone. The generic "no implemented activated ability" is the message a
    missing feature gives, and this is a rule being enforced on an ability that
    compiled perfectly.
    """
    card = _cycler("Cycling Bear", type_line="Creature — Bear", body="")
    game, player = _game_with(card)
    player.hand.clear()
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    player.battlefield.append(perm)
    before = len(player.library)

    result = game.activate_permanent_ability(0, "Cycling Bear")

    assert result.supported is False
    assert "113.6" in result.details, result.details
    assert len(player.library) == before
    assert player.graveyard == []
    assert [p.card.name for p in player.battlefield] == ["Cycling Bear"]


@pytest.mark.cr("113.6j")
def test_113_6j_an_ordinary_battlefield_ability_is_not_activatable_from_hand():
    """The gate is a zone, not a permission: an ability with no hand-payable
    cost is refused from a hand exactly as a hand-only one is refused from the
    battlefield."""
    card = _cycler("Tapper", type_line="Creature — Bear", body="{T}: Draw a card.",
                   keyword="Notcycling")
    ordinary = CardDefinition(
        name="Tapper", mana_cost="", cmc=0.0, type_line="Creature — Bear",
        oracle_text="{T}: Draw a card.", colors=(), color_identity=(),
        keywords=(), produced_mana=(),
        raw={"name": "Tapper", "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )
    del card
    game, player = _game_with(ordinary)

    result = game.activate_from_hand(0, "Tapper")

    assert result.supported is False
    assert [c.name for c in player.hand] == ["Tapper"]


# ---------------------------------------------------------------------------
# CR 702.29e — typecycling is refused rather than read as a draw
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.29e", "702.29f")
def test_702_29e_typecycling_is_refused_naming_the_line():
    """"[Type]cycling [cost]" searches a library; it does not draw. CR 702.29f
    makes it a cycling ability for every other purpose, so a card printing one
    must be reported unsupported naming the line rather than quietly rewritten
    into the draw — and rather than slipping past as an unclaimed line on an
    instant whose *other* line compiles, which is what the fourteen already
    "supported" cycling cards in Urza's Saga were doing."""
    assert expand_cycling_line("Plainscycling {2}") is None
    assert is_cycling_line("Plainscycling {2}") is True

    card = _cycler("Searcher", keyword="Plainscycling")
    program = compile_card_oracle(card)
    assert program.supported is False
    assert "Plainscycling {2}" in program.reason


@pytest.mark.cr("702.29e")
def test_702_29e_a_static_ability_about_cycling_is_not_a_cycling_line():
    """Fluctuator prints "Cycling abilities you activate cost {2} less to
    activate" — a sentence that begins with the word and is not the keyword. The
    wide shape the support gate asks must not swallow it, or a card whose
    ability is a cost modifier is refused for printing a keyword it does not
    have."""
    line = "Cycling abilities you activate cost {2} less to activate."
    assert is_cycling_line(line) is False
    assert unread_cycling_line(line) is None
    assert expand_cycling_lines(line) == line


@pytest.mark.cr("702.29a")
def test_702_29a_text_without_a_cycling_line_is_returned_unchanged():
    """The rewrite is applied to every card in the pool, so it has to be inert
    on the ones that do not print the word."""
    for text in ("", "Flying", "Equip {1}", "Destroy target creature."):
        assert expand_cycling_lines(text) == text


@pytest.mark.cr("702.29a")
def test_702_29a_cycling_is_not_a_word_the_keyword_registry_admits():
    """The word is **not** in ``vocabulary.IMPLEMENTED_KEYWORDS``, and that is
    the correct answer rather than an omission.

    That registry is what admits a keyword being *granted* or *named* — "gains
    flying", "creatures with flanking", "loses all landwalk". None of the
    keywords this engine implements as a rewrite is in it (equip, buyback,
    cumulative upkeep), for the reason that applies here: by the time any reader
    sees the card the word is gone, replaced by the ability it means.

    ``test_keyword_registry.py`` is what settles it. It builds a creature whose
    entire printed text is the bare keyword word and requires that card to
    compile *supported* — and "Cycling" with no cost is a card that must be
    refused, because CR 702.29a's ability is "[Cost], Discard this card: Draw a
    card." and there is no cost to charge. Listing the word would force a choice
    between failing that guard and admitting a cycling that charges nothing.
    """
    from engine.grammar.vocabulary import IMPLEMENTED_KEYWORDS

    assert "cycling" not in IMPLEMENTED_KEYWORDS

    costless = CardDefinition(
        name="Bare Cycler", mana_cost="{1}{U}", cmc=2.0,
        type_line="Creature — Bear", oracle_text="Cycling",
        colors=(), color_identity=(), keywords=("Cycling",), produced_mana=(),
        raw={"name": "Bare Cycler", "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )
    program = compile_card_oracle(costless)
    assert program.supported is False
    assert "Cycling" in program.reason

"""Typecycling — CR 702.29e-f, the variant Scourge brought seven of.

"'[Type]cycling [cost]' means '[Cost], Discard this card: Search your library
for a [type] card, reveal it, and put it into your hand. Then shuffle your
library.'" (CR 702.29e) — so ``engine/cycling.py`` rewrites the printed line
into that sentence, exactly as it rewrites plain cycling into its draw, and
everything downstream reads an ordinary hand-activated search.

CR 702.29f is the half that makes it *cycling*: a cycle trigger fires, a
cycling-cost modifier reaches it, and an effect that stops players cycling
stops it. All three are asked of one predicate (``cycling.is_cycling_ability``,
the rewrite run backwards), so these tests drive each of them through a real
``Game``.

The fixtures are **invented** cards wherever the shape is the subject — the
keyword must work on anything printing it — and the shipped pool's own cards
where a printed card is the witness (Lightning Rift, Fluctuator, Bayou, Waker
of Waves). The per-card tests for Scourge's seven are in
``tests/sets/test_scg_creatures.py``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.cycling import expand_cycling_line, is_cycling_ability
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack


def _card(name, oracle_text, *, type_line="Creature — Beast", power="4",
          toughness="4", mana_cost="{5}{G}"):
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = power, toughness
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=6.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw,
    )


def _typecycler(name="Forest Strider", keyword="Forestcycling", cost="{2}",
                extra=""):
    lines = [f"{keyword} {cost}"]
    if extra:
        lines.append(extra)
    return _card(name, "\n".join(lines))


def _table(hand, library, *, interactive=False, mana=None):
    alice = PlayerState(name="Alice", hand=list(hand), library=list(library))
    bob = PlayerState(name="Bob", library=[])
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    alice.mana_pool.update(mana or {"G": 2})
    return game, alice, bob


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


# ---------------------------------------------------------------------------
# CR 702.29e — the rewrite
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.29e")
@pytest.mark.parametrize("keyword,cost,searched", [
    ("Plainscycling", "{2}", "a Plains card"),
    # The article follows the type, as the printed reminder text does.
    ("Islandcycling", "{2}", "an Island card"),
    # "…can be any card type, subtype, supertype, or combination thereof (as
    # in 'basic landcycling')."
    ("Basic landcycling", "{1}{B}", "a basic land card"),
    # A creature type is a subtype as much as a land type is.
    ("Slivercycling", "{3}", "a Sliver card"),
])
def test_702_29e_the_type_is_any_type_subtype_or_supertype(keyword, cost, searched):
    assert expand_cycling_line(f"{keyword} {cost}") == (
        f"{cost}, Discard this card: Search your library for {searched}, "
        "reveal it, put it into your hand, then shuffle."
    )
    program = compile_card_oracle(_typecycler(keyword=keyword, cost=cost))
    assert program.supported, program.reason
    (ability,) = usable_activated_abilities(program, zone=HAND)
    assert ability.instruction.kind == "search_library"
    assert ability.cost.discard_self


@pytest.mark.cr("702.29e", "701.23a")
def test_702_29e_typecycling_discards_the_card_and_finds_a_card_of_the_type(set_pool):
    """The search finds any card *with the type* — Bayou is a Swamp Forest, and
    the Scourge rulings (2022-12-08, Elvish Aberration): "The card you find can
    be a basic Forest or any land card with the Forest land type." A card
    without it is not an answer."""
    lea = set_pool("LEA")
    library = [lea["Grizzly Bears"], lea["Bayou"], lea["Plains"], lea["Forest"]]
    game, alice, _bob = _table([_typecycler()], library, interactive=True)

    result = game.activate_from_hand(0, "Forest Strider")
    assert result.supported, result.details
    # The cost: the mana and the card, before the ability is on the stack.
    assert [c.name for c in alice.graveyard] == ["Forest Strider"]
    assert alice.hand == [] and not any(alice.mana_pool.values())
    assert "Alice cycled Forest Strider" in game.log

    game.resolve_top_of_stack()
    search = game.pending_choice_of("search_library", 0)
    assert search is not None
    names = [c.name for c in alice.library]
    assert not game.resolve_pending_choice(
        "search_library", 0, library_index=names.index("Grizzly Bears"),
        zone="library",
    ), "a creature card is not a Forest card"
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=names.index("Bayou"), zone="library",
    )
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Bayou"]
    assert sorted(c.name for c in alice.library) == ["Forest", "Grizzly Bears", "Plains"]
    assert any("revealed Bayou" in line for line in game.log)


@pytest.mark.cr("701.23b")
def test_701_23b_a_typecycler_may_find_nothing_though_the_type_is_there(set_pool):
    """2009-02-01 (Eternal Dragon): "You can also choose not to find a card,
    even if there is a Plains card in your library." The card stays cycled."""
    lea = set_pool("LEA")
    game, alice, _bob = _table(
        [_typecycler()], [lea["Forest"], lea["Forest"]], interactive=True,
    )
    assert game.activate_from_hand(0, "Forest Strider").supported
    game.resolve_top_of_stack()

    assert game.decline_search_library(0)
    resolve_stack(game)
    assert alice.hand == []
    assert [c.name for c in alice.library] == ["Forest", "Forest"]
    assert [c.name for c in alice.graveyard] == ["Forest Strider"]


# ---------------------------------------------------------------------------
# CR 702.29f — a typecycling ability is a cycling ability
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.29f")
def test_702_29f_a_typecycling_ability_is_a_cycling_ability():
    card = _typecycler()
    (ability,) = usable_activated_abilities(compile_card_oracle(card), zone=HAND)
    assert is_cycling_ability(card, ability)


@pytest.mark.cr("702.29f")
def test_702_29f_whenever_a_player_cycles_a_card_sees_a_typecycle(set_pool):
    """"Any cards that trigger when a player cycles a card will trigger when a
    card is discarded to pay an activation cost of a typecycling ability."
    Lightning Rift's trigger goes on the stack above the search and resolves
    first (the 2022-12-08 Onslaught rulings on the trigger's order)."""
    lea = set_pool("LEA")
    game, alice, bob = _table(
        [_typecycler()], [lea["Forest"], lea["Plains"]], mana={"G": 3},
    )
    _put(game, 0, set_pool("ONS")["Lightning Rift"])

    assert game.activate_from_hand(0, "Forest Strider").supported
    assert [item.card.name for item in game.stack] == ["Forest Strider", "Lightning Rift"]
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert bob.life == 18
    assert [c.name for c in alice.hand] == ["Forest"]


@pytest.mark.cr("702.29c", "702.29f")
def test_702_29c_when_you_cycle_this_card_triggers_on_a_typecycle(set_pool):
    lea = set_pool("LEA")
    card = _typecycler(
        name="Grateful Strider", extra="When you cycle this card, you gain 3 life.",
    )
    game, alice, _bob = _table([card], [lea["Forest"]])

    assert game.activate_from_hand(0, "Grateful Strider").supported
    assert len(game.stack) == 2
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert alice.life == 23
    assert [c.name for c in alice.hand] == ["Forest"]


@pytest.mark.cr("702.29f")
def test_702_29f_a_cycling_cost_reduction_reduces_a_typecycling_cost(set_pool):
    """"Any effect that increases or reduces a cycling cost will increase or
    reduce a typecycling cost." Fluctuator's {2} off makes a {2} typecycle
    free."""
    lea = set_pool("LEA")
    game, alice, _bob = _table([_typecycler()], [lea["Forest"]], mana={})
    _put(game, 0, set_pool("USG")["Fluctuator"])

    assert game.activate_from_hand(0, "Forest Strider").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Forest"]


@pytest.mark.cr("702.29f", "602.5")
def test_702_29f_an_effect_that_stops_cycling_stops_typecycling(set_pool):
    """"Any effect that stops players from cycling cards will stop players
    from activating cards' typecycling abilities." Nothing is paid and nothing
    is discarded — the activation cannot be begun (CR 602.5) — while a hand
    ability that is not cycling (Waker of Waves) is untouched."""
    lea = set_pool("LEA")
    ban = _card(
        "Cycle Lock", "Players can't cycle cards.", type_line="Artifact",
        mana_cost="{2}",
    )
    assert compile_card_oracle(ban).supported
    waker = set_pool("M21")["Waker of Waves"]
    game, alice, _bob = _table(
        [_typecycler(), waker], [lea["Forest"]] * 3, mana={"G": 2, "U": 2},
    )
    _put(game, 1, ban)

    refused = game.activate_from_hand(0, "Forest Strider")
    assert not refused.supported
    assert "Cycle Lock" in refused.details
    assert [c.name for c in alice.hand] == ["Forest Strider", "Waker of Waves"]
    assert alice.mana_pool["G"] == 2 and game.stack == []

    assert game.activate_from_hand(0, "Waker of Waves").supported

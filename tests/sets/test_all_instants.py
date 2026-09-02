"""Per-card tests for Alliances' instants.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G5: delayed triggers ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.game_types import StackItem
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w1g5_lea(name: str):
    """One Limited Edition Alpha card, for the boards these tests need.

    Alliances is `measured`, so its own basics and vanilla creatures are the
    only ones its file carries and several of these boards want neither. Loaded
    through the manifest like every other set here.
    """
    for card in load_cards(manifest_set_path("LEA", include_measured=True)):
        if card.name == name:
            return card
    raise AssertionError(f"{name} is not in LEA")


def _w1g5_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def test_w1g5_arcane_denial_counters_the_spell_it_targets(set_pool):
    """The counter is the card's first sentence and it was not compiled at all.

    Arcane Denial reported **supported** on the strength of its second line's
    delayed draw plus two whitelist substrings, with "Counter target spell"
    reaching no instruction — a supported counterspell that countered nothing.
    """
    denial = set_pool("ALL")["Arcane Denial"]
    kinds = [instruction.kind for instruction in compile_card_oracle(denial).instructions]
    assert "sequence" in kinds
    steps = next(
        instruction for instruction in compile_card_oracle(denial).instructions
        if instruction.kind == "sequence"
    ).payload["steps"]
    assert [step.kind for step in steps] == [
        "counter_top_stack_spell", "create_delayed_trigger",
    ]


def test_w1g5_arcane_denial_offers_a_spell_picker(set_pool):
    """The Roots class: text names a choice and the derivation offers no picker,
    so the client sends a bare cast and the spell resolves against nothing."""
    from engine.targeting import derive_cast_spec

    denial = set_pool("ALL")["Arcane Denial"]
    spec = derive_cast_spec(denial, compile_card_oracle(denial))
    assert spec is not None and spec.get("kind") == "stack"


def test_w1g5_arcane_denial_lets_the_countered_spells_controller_draw(set_pool):
    """CR 603.7 end to end: counter now, and the *other* player is offered two
    cards at the next turn's upkeep.

    The seat is the whole point. By the time the delayed ability fires the
    countered spell is a card in a graveyard, and CR 108.4 gives that card no
    controller — so the seat has to have been written down as the counter
    happened.
    """
    denial = set_pool("ALL")["Arcane Denial"]
    game, p1, p2 = _w1g5_duel()
    game.interactive_seats = {1}
    victim = _w1g5_lea("Giant Growth")
    game.stack.append(StackItem(
        card=victim, caster_index=1, target_player_index=None,
        target_permanent_index=None, x_value=None,
    ))

    game._apply_spell_text(p1, p2, denial, stack_target=game.stack[-1])
    game._settle()
    assert game.stack == []
    assert any(card is victim for card in p2.graveyard)

    # Nothing yet — the draw waits for the next turn's upkeep, whoever's it is.
    assert p2.hand == []
    p2.library.extend([_w1g5_lea("Mountain")] * 4)
    game.active_player_index = 1
    game.resolve_upkeep(1)
    game._settle()
    assert game.confirm_draw_up_to(1, 2)
    assert len(p2.hand) == 2


def test_w1g5_death_spark_returns_itself_from_the_graveyard(set_pool):
    """CR 113.6b: the intervening-if is where this card says it functions from a
    graveyard, and the upkeep step had no graveyard scan at all."""
    pool = set_pool("ALL")
    spark = pool["Death Spark"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.battlefield.append(Permanent(card=_w1g5_lea("Mountain")))
    game._sync_control()
    p1.graveyard.extend([spark, _w1g5_lea("Grizzly Bears")])

    game.resolve_upkeep(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Death Spark", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Death Spark"]
    assert p1.graveyard == [_w1g5_lea("Grizzly Bears")]


def test_w1g5_death_spark_stays_put_with_a_land_directly_above_it(set_pool):
    """"**Directly** above" is a different question from a count of one: a
    creature card above with a land between them satisfies neither."""
    pool = set_pool("ALL")
    spark = pool["Death Spark"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.battlefield.append(Permanent(card=_w1g5_lea("Mountain")))
    game._sync_control()
    p1.graveyard.extend(
        [spark, _w1g5_lea("Grizzly Bears"), _w1g5_lea("Forest")]
    )

    game.resolve_upkeep(0)
    game._settle()

    assert p1.hand == []
    assert p1.graveyard[0] is spark


def test_w1g5_reinforcements_moves_chosen_creature_cards_to_the_library_top(set_pool):
    """"Up to three target creature cards from **your** graveyard on top of
    **your** library" — the seat is the caster's on both halves, where Drafna's
    Restoration's is the target player's on both."""
    reinforcements = set_pool("ALL")["Reinforcements"]
    game, p1, p2 = _w1g5_duel()
    bear = _w1g5_lea("Grizzly Bears")
    ogre = _w1g5_lea("Hurloon Minotaur")
    p1.graveyard.extend([bear, _w1g5_lea("Forest"), ogre])

    game._apply_spell_text(p1, p2, reinforcements, target_permanent_index=[0, 2])
    game._settle()

    assert [card.name for card in p1.library[:2]] == ["Grizzly Bears", "Hurloon Minotaur"]
    assert [card.name for card in p1.graveyard] == ["Forest"]


def test_w1g5_reinforcements_offers_only_its_own_graveyard(set_pool):
    """The picker is scoped to the caster's pile. Left unscoped it would offer
    the opponent's creature cards, and the handler — which indexes the caster's
    graveyard — would then move whatever card sat at that slot."""
    from engine.targeting import derive_cast_spec

    reinforcements = set_pool("ALL")["Reinforcements"]
    spec = derive_cast_spec(reinforcements, compile_card_oracle(reinforcements))
    assert spec is not None
    assert spec.get("own_graveyard_only") is True
    assert spec.get("count") == 3

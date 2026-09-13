"""A mana ability that costs more than a bare tap is still a mana ability.

CR 605.3b: an activated mana ability doesn't go on the stack, so it can't be
targeted, countered, or otherwise responded to; it resolves immediately after it
is activated. Which abilities those are is CR 605.1a, a question about what the
whole ability *does*.

``engine/mixins/stack/activation.py`` decided it by instruction **kind** — three
names, all of them the shape a one-sentence "Add {G}" lowers to. Every printed
"Add mana. ⟨rider⟩" lowers to a ``sequence`` and every "…add {C}{C} instead" to
an ``if_then``, so **43 abilities across both manifest roles** went on the stack
instead: the five Ice Age painlands and five Tempest ones, the Ice Age and
Mercadian Masques depletion cycles, the five Mana Batteries, the Urza tri-lands,
Gemstone Mine, Ancient Tomb, Elves of Deep Shadow, Rainbow Vale, Undiscovered
Paradise and Metalworker among them.

The pool-wide census lives in ``tests/rules/test_abilities.py``. This file holds
the two named consequences a human could see, one per direction:

* **Imprison** (Legends) reads "whenever a player activates an ability of
  enchanted creature with {T} in its activation cost **that isn't a mana
  ability**, you may pay {1}. If you do, counter that ability." The engine
  derives that clause from the **site** — the trigger is announced after the
  push, so only an ability that used the stack can fire it — on the strength of
  a comment saying every mana ability resolves inline above. That comment was
  false for the 43, so Imprison on an Elves of Deep Shadow let its controller
  counter a mana ability, which CR 605.3b says cannot be responded to at all.
* **Peat Bog**, the mana that was not there. A queued ability produces nothing
  until it resolves, so with a spell already on the stack the controller could
  not reach the mana without passing priority — CR 605.3a's window closed.

The direction is the quiet one in both: no crash, nothing missing, an ability
that simply does *more* than the rules allow. A player who cannot tap a painland
mid-cast taps it first and never notices.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.mana_payment import is_mana_ability
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from engine.oracle import compile_card_oracle


@pytest.fixture(scope="module")
def pool():
    # Both manifest roles: the Mercadian Masques depletion cycle is still
    # `measured`, and it is half the finding.
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _board(pool, *placements):
    """A two-seat game with interactive seats, and one permanent per placement.

    Interactive on both sides deliberately: ``activate_permanent_ability``
    settles the stack itself for a non-interactive table, so a queued ability
    would resolve anyway and report "resolved" — the harness would read the
    defect as its own fix. The web wire calls ``queue_permanent_ability``, which
    is what these tests call.
    """
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.interactive_seats = {0, 1}
    made = []
    for seat, name in placements:
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.tapped = False
        permanent.metadata.pop("summoning_sickness_turn", None)
        made.append(permanent)
    return game, made


@pytest.mark.parametrize(
    "name, index, counter, colour",
    [
        ("Peat Bog", 0, "depletion", None),
        ("Sandstone Needle", 0, "depletion", None),
        ("Gemstone Mine", 0, "mining", "W"),
        ("Adarkar Wastes", 1, None, "U"),
        ("Ancient Tomb", 0, None, None),
        ("Land Cap", 0, None, "W"),
        ("Black Mana Battery", 1, "charge", None),
        ("Urza's Mine", 0, None, None),
        ("Rainbow Vale", 0, None, "G"),
        ("Undiscovered Paradise", 0, None, "R"),
    ],
)
def test_a_shipped_mana_ability_with_a_rider_never_touches_the_stack(
    pool, name, index, counter, colour,
):
    """One card from each shape the kind-keyed seam missed.

    A painland, two depletion lands, Gemstone Mine, a storage battery, an
    ``if_then`` tri-land, Ancient Tomb, and the two lands whose rider hands the
    land away. Each produced nothing and sat on the stack; each now resolves
    where it is activated.
    """
    game, (land,) = _board(pool, (0, name))
    ability = compile_card_oracle(pool[name]).activated_abilities[index]
    assert is_mana_ability(ability) is True
    held = 0
    if counter:
        # Beside whatever the land entered carrying (a depletion land enters
        # with three), because the assertion below is that the cost was
        # *charged*, not that a particular number is left.
        add_counters(land, counter, 2)
        held = counters_on(land, counter)

    result = game.queue_permanent_ability(
        0, name, permanent_index=0, ability_index=index, mana_color=colour,
    )

    assert result.details == "resolved"
    assert [item.card.name for item in game.stack] == [], (
        "CR 605.3b: the ability does not go on the stack"
    )
    assert sum(game.players[0].mana_pool.values()) > 0, "the mana is in the pool now"
    if colour:
        assert game.players[0].mana_pool.get(colour, 0) > 0, (
            "and it is the colour the activator named"
        )
    if counter:
        assert counters_on(land, counter) < held, "and the cost was charged"


def test_imprison_cannot_counter_a_mana_ability_with_a_drawback(pool):
    """Imprison + Elves of Deep Shadow ("{T}: Add {B}. This creature deals 1
    damage to you.")

    The printed clause is "…that isn't a mana ability", and CR 605.1a makes this
    one, drawback and all. The trigger must not fire; nothing goes on the stack;
    the black mana arrives.
    """
    game, (elves, imprison) = _board(
        pool, (0, "Elves of Deep Shadow"), (1, "Imprison"),
    )
    attach_aura(imprison, elves)

    result = game.queue_permanent_ability(
        0, "Elves of Deep Shadow", permanent_index=0, ability_index=0,
    )

    assert result.details == "resolved"
    assert [item.card.name for item in game.stack] == []
    assert game.players[0].mana_pool.get("B", 0) == 1


def test_imprison_still_counters_a_tap_ability_that_is_not_a_mana_ability(pool):
    """The other half of the same sentence, so the fix is a narrowing and not a
    silencing.

    Witch Engine's "{T}: Add {B}{B}{B}{B}. Target opponent gains control of this
    creature" **targets**, so CR 605.5a says it is not a mana ability whatever it
    could add — it uses the stack and Imprison's trigger belongs over it.
    """
    game, (engine, imprison) = _board(
        pool, (0, "Witch Engine"), (1, "Imprison"),
    )
    attach_aura(imprison, engine)
    ability = compile_card_oracle(pool["Witch Engine"]).activated_abilities[0]
    assert is_mana_ability(ability) is False

    result = game.queue_permanent_ability(
        0, "Witch Engine", permanent_index=0, ability_index=0,
    )

    assert result.details == "queued"
    assert [item.card.name for item in game.stack] == ["Witch Engine", "Imprison"]


def test_a_depletion_land_can_be_tapped_with_a_spell_already_on_the_stack(pool):
    """CR 605.3a's window, with the mana spent on what it was made for.

    Two Peat Bogs: one pays for the Shock, the other is activated while that
    Shock is on the stack — which is exactly the moment a queued mana ability
    could not reach.
    """
    game, (first, second) = _board(pool, (0, "Peat Bog"), (0, "Peat Bog"))
    for bog in (first, second):
        add_counters(bog, "depletion", 2)

    game.players[0].hand.append(pool["Shock"])
    game.players[0].mana_pool["R"] = 1
    game.queue_from_hand(0, "Shock", target_player_index=1)
    assert len(game.stack) == 1

    result = game.queue_permanent_ability(
        0, "Peat Bog", permanent_index=1, ability_index=0,
    )

    assert result.details == "resolved"
    assert len(game.stack) == 1, "the spell alone — the mana ability added nothing"
    assert game.players[0].mana_pool.get("B", 0) == 2


def test_the_wires_colourless_answer_is_not_a_colour_and_does_not_raise(pool):
    """``ActionRequest.mana_color`` is a ``Literal[..., "C"]`` because the same
    field carries a *symbol* for the land-tap action and a *colour* for the
    choice channel. CR 105.1 makes colourless not a colour, so "C" can never
    answer "choose a color" — and the activation seam normalised it
    unconditionally, raising ``ValueError`` out of the route for any ability
    activated with it. Read as "no colour named" instead.
    """
    for name in ("Urza's Mine", "Sol Ring"):
        game, _made = _board(pool, (0, name))
        result = game.queue_permanent_ability(
            0, name, permanent_index=0, ability_index=0, mana_color="C",
        )
        assert result.supported is True
        assert game.players[0].mana_pool.get("C", 0) > 0

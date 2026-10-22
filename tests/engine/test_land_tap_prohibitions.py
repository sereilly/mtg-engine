"""The land tap seam asks every CR 602.5 prohibition (Torment wave 2, W2G2).

Tapping a land for mana *is* activating its mana ability (CR 106.12), so
"a player can't begin to activate an ability that's prohibited from being
activated" (CR 602.5) binds ``Game.tap_land_for_mana`` exactly as it binds the
activation path. The activation path, the AI's chooser, the wire and the
payment preview all read ``engine/activation_prohibitions.py``'s one table;
the tap seam (``land_mana_tap_refusal``) asked two of its rows by hand and the
rest not at all. A basic land has no compiled ability for a row to read, which
is why: its mana ability is CR 305.6's intrinsic "{T}: Add [symbol]", which
no text carries. The seam now hands the table that ability
(``mana_payment.INTRINSIC_LAND_MANA_ABILITY``), or the land's own free one, or
the one the player chose by index.

This is the census, **one scenario per row of the table**, each asked of a
land's mana ability: whether the seam refuses, whether a tap makes mana, and
whether the payment planners (the castable highlight's ``board_can_pay``)
count the land — all three against what the rules say, row by row. A row the
table grows without a land scenario here fails ``test_every_row_has_a_land_
scenario``.

The rulings it leans on, fetched from Scryfall:

* City of Solitude (2009-10-01): "This stops players from activating mana
  abilities."
* Cursed Totem (2021-06-18): "Cursed Totem stops players from activating mana
  abilities of creatures."

Validated backwards: on the wave's base (053649ac) the seam rows for City of
Solitude, Cursed Totem and Katabatic Winds fail — each land tapped and made
mana — and every other row passes.
"""
from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.activation_prohibitions import ACTIVATION_PROHIBITIONS
from engine.aura_attachment import attach_aura
from engine.board_payment import board_can_pay
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.spell_prohibitions import (forbid_nonmana_activations_this_turn,
                                       forbid_permanent_activations_this_turn)

_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)

#: A Forest that flies — invented, because Katabatic Winds' row is about
#: "creatures with flying" and no land in the pool flies. Living Lands makes it
#: a creature; the printed keyword makes it a flying one.
_SKYWARD_FOREST = dataclasses.replace(
    _POOL["Forest"], name="Skyward Forest", oracle_text="Flying",
    keywords=("Flying",),
)

LAND_SEAT, OTHER_SEAT = 1, 0


def _board(land_card, *, others=(), lock=(), active=LAND_SEAT, combat=False,
           arm=None):
    """*land_card* untapped on seat 1, *others* beside it, each of *lock* on
    seat 0 (an Aura among them attached to the land), *active*'s main phase or
    combat. Returns (game, land)."""
    game = Game(players=[
        PlayerState(name="P0", library=[_POOL["Forest"]] * 5),
        PlayerState(name="P1", library=[_POOL["Forest"]] * 5),
    ])
    game.enforce_mana_costs = True
    land = Permanent(card=land_card)
    for card in (*others,):
        game._put_permanent_onto_battlefield(LAND_SEAT, Permanent(card=card), None)
    game._put_permanent_onto_battlefield(LAND_SEAT, land, None)
    for card in lock:
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(OTHER_SEAT, permanent, None)
        if "Aura" in card.type_line:
            attach_aura(permanent, land)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    game.auto_resolve_pending_choices()
    game.stack.clear()
    game.turn = 3
    game.active_player_index = active
    game.current_phase = "combat" if combat else "main"
    game.current_turn_phase, game.current_step = (
        ("combat", "declare_attackers") if combat else ("precombat_main", None)
    )
    game._recompute_continuous_effects()
    if arm is not None:
        arm(game, land)
    return game, land


def _interdict(game, land):
    forbid_permanent_activations_this_turn(game, land)


def _abeyance(game, land):
    forbid_nonmana_activations_this_turn(game, LAND_SEAT)


#: ``row kind -> (refused, board kwargs, ability index, what pays)``. *refused*
#: is what the rules say about tapping the land for mana under that row's
#: prohibition; the rows printing CR 605.1a's exception leave it tappable.
_LAND_SCENARIOS: dict[str, tuple] = {
    # "That permanent's activated abilities can't be activated this turn."
    "permanent_shut_off_this_turn": (
        True, dict(land_card=_POOL["Forest"], arm=_interdict), None, {"G": 1},
    ),
    # Abeyance: "…can't activate abilities that aren't mana abilities."
    "nonmana_shut_off_this_turn": (
        False, dict(land_card=_POOL["Forest"], arm=_abeyance), None, {"G": 1},
    ),
    # City of Solitude, on another player's turn.
    "global_play_timing": (
        True,
        dict(land_card=_POOL["Forest"], lock=[_POOL["City of Solitude"]],
             active=OTHER_SEAT),
        None, {"G": 1},
    ),
    # Hand to Hand: "…activate abilities that aren't mana abilities."
    "combat_play_ban": (
        False,
        dict(land_card=_POOL["Forest"], lock=[_POOL["Hand to Hand"]], combat=True),
        None, {"G": 1},
    ),
    # Cursed Totem, over a Forest Living Lands has made a creature.
    "global_activation_ban": (
        True,
        dict(land_card=_POOL["Forest"],
             lock=[_POOL["Living Lands"], _POOL["Cursed Totem"]]),
        None, {"G": 1},
    ),
    # "{T}: Add {W} or {B}. Activate only if you control a Swamp." — with
    # none, the coloured ability, chosen by index.
    "printed_restriction": (
        True, dict(land_card=_POOL["Tainted Field"]), 1, {"W": 1},
    ),
    # Faith's Fetters: "…can't be activated unless they're mana abilities."
    "aura_nonmana_shut_off": (
        False,
        dict(land_card=_POOL["Forest"], lock=[_POOL["Faith's Fetters"]]),
        None, {"G": 1},
    ),
    # Volrath's Curse on a Forest Living Lands has made a creature.
    "aura_all_shut_off": (
        True,
        dict(land_card=_POOL["Forest"],
             lock=[_POOL["Living Lands"], _POOL["Volrath's Curse"]]),
        None, {"G": 1},
    ),
    # Katabatic Winds: "Creatures with flying … their activated abilities with
    # {T} in their costs can't be activated."
    "tap_abilities_shut_off": (
        True,
        dict(land_card=_SKYWARD_FOREST,
             lock=[_POOL["Living Lands"], _POOL["Katabatic Winds"]]),
        None, {"G": 1},
    ),
}

#: The one row no land can reach: "Only your opponents may activate this
#: ability" (Clergy of the Holy Nimbus) is printed on an ability the player
#: names by index, and the tap seam takes only a mana ability whose whole
#: cost is {T} and whose line prints no clause it cannot ask mid-payment
#: (``is_tap_alone_mana_ability``) — no land in the pool prints one, and such
#: an ability goes down the activation path, which asks the table already.
_UNREACHABLE = {"printed_permission"}


def test_every_row_has_a_land_scenario():
    kinds = {row.kind for row in ACTIVATION_PROHIBITIONS}
    assert kinds == set(_LAND_SCENARIOS) | _UNREACHABLE, (
        f"a row with no land scenario: {sorted(kinds - set(_LAND_SCENARIOS) - _UNREACHABLE)}"
    )


@pytest.mark.parametrize("kind", sorted(_LAND_SCENARIOS))
def test_the_tap_seam_answers_each_row_as_the_rules_do(kind):
    refused, board, index, cost = _LAND_SCENARIOS[kind]
    game, land = _board(**board)

    refusal = game.land_mana_tap_refusal(land, index)
    tapped = game.tap_land_for_mana(
        LAND_SEAT, land.card.name, permanent_id=land.permanent_id,
        ability_index=index,
    )
    made = {k: v for k, v in game.players[LAND_SEAT].mana_pool.items() if v}
    if refused:
        assert refusal is not None, f"{kind}: the seam would tap {land.card.name}"
        assert not tapped and not land.tapped and not made, game.log[-3:]
    else:
        assert refusal is None, refusal
        assert tapped and made, game.log[-3:]

    game, land = _board(**board)
    assert board_can_pay(game, LAND_SEAT, cost) is not refused, (
        f"{kind}: the planner counts what the seam {'refuses' if refused else 'taps'}"
    )


@pytest.mark.parametrize("kind", sorted(_LAND_SCENARIOS))
def test_the_seam_asks_the_row_itself(kind):
    """The refusal is the table's own verdict on the land's mana ability, not a
    second list of the seam's: the row that answers is the scenario's row."""
    refused, board, index, _cost = _LAND_SCENARIOS[kind]
    game, land = _board(**board)
    prohibited = game.land_tap_prohibition(land, index)
    if refused:
        assert prohibited is not None and prohibited.kind == kind, prohibited
    else:
        assert prohibited is None, prohibited


def test_a_refused_tap_says_why():
    """The table's sentence is the log line, as the activation path logs it."""
    _refused, board, _index, _cost = _LAND_SCENARIOS["global_play_timing"]
    game, land = _board(**board)
    assert not game.tap_land_for_mana(LAND_SEAT, "Forest", permanent_id=land.permanent_id)
    assert game.log[-1] == (
        "Forest's abilities can't be activated on another player's turn "
        "(City of Solitude)"
    )


def test_on_its_own_turn_city_of_solitude_leaves_the_forest_alone():
    """The prohibition is about whose turn it is, so the same board on the
    land's controller's own turn taps."""
    game, land = _board(
        _POOL["Forest"], lock=[_POOL["City of Solitude"]], active=LAND_SEAT,
    )
    assert game.land_mana_tap_refusal(land) is None
    assert game.tap_land_for_mana(LAND_SEAT, "Forest", permanent_id=land.permanent_id)

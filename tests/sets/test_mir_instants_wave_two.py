"""Per-card tests for Mirage's instants — wave 3's sections.

The continuation of `test_mir_instants.py`, opened at wave 3 because that file
stood at 2,495 lines of the 2,600-line guard and this wave has more than one
group appending to it. Cut at a **section boundary**, which is what
`tests/sets/README.md` asks for past the printed-type axis — every section here
is self-contained and written up in ROADMAP.md under the round or group that
bought it, so a section stays whole and stays findable from its round.

The same block convention holds: append a delimited block headed
``# --- W<wave>G<n>: <topic> ---`` with **its own imports at the top of its own
block**, and do not edit this docstring or an earlier block.
"""

from __future__ import annotations


# --- W3G4: Delirium, a bound creature biting its own controller ---
#
# "Cast this spell only during an opponent's turn.
#  Tap target creature that player controls. That creature deals damage equal
#  to its power to the player. Prevent all combat damage that would be dealt to
#  and dealt by the creature this turn."
#
# Three sentences and three different questions. The tap chooses the target;
# the bite reads the creature the tap recorded, and deals *the creature's*
# damage (CR 119.3) rather than the spell's; the prevention is the shipped
# to-and-by shield Maze of Ith already prints.
#
# "That player" has its antecedent in the **timing clause**, which is a
# registry line producing no instruction at all — so the seat comes from
# `cast_restrictions.timing_fixed_seat`, the table that owns the phrase, and
# the picker and the resolution ask the same function.

from engine import Game as _w3g4i_Game, PlayerState as _w3g4i_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w3g4i_load,  # noqa: E402
                                manifest_set_path as _w3g4i_path)
from engine.models import Permanent as _w3g4i_Permanent  # noqa: E402
from engine.pt import add_pt_modifier as _w3g4i_pump  # noqa: E402


def _w3g4i_lea():
    return {card.name: card for card in _w3g4i_load(_w3g4i_path("LEA"))}


def _w3g4i_game(pool, *, mine=(), theirs=(), active=1):
    """P1 holds Delirium; it is P2's turn, which is the only window it has."""
    lea = _w3g4i_lea()
    game = _w3g4i_Game(players=[
        _w3g4i_PlayerState(name="P1", hand=[pool["Delirium"]],
                           battlefield=list(mine), library=[lea["Island"]] * 6),
        _w3g4i_PlayerState(name="P2", battlefield=list(theirs),
                           library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = active
    return game


def test_w3g4_delirium_bites_with_the_power_the_layers_computed(set_pool):
    """The damage is the creature's *effective* power (CR 613), not its printed
    one, and it lands on the creature's own controller."""
    pool = set_pool("MIR")
    bear = _w3g4i_Permanent(card=_w3g4i_lea()["Grizzly Bears"])   # printed 2/2
    game = _w3g4i_game(pool, theirs=[bear])
    _w3g4i_pump(bear, 3, 3)
    assert bear.effective_power == 5

    cast = game.cast_from_hand(
        0, "Delirium", target_player_index=1, target_permanent_index=0
    )
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert bear.tapped, game.log
    assert game.players[1].life == 15, game.log      # 5, not the printed 2
    assert game.players[0].life == 20, "the caster is not the player it names"


def test_w3g4_delirium_offers_only_the_active_opponents_creatures(set_pool):
    """CR 601.2c: "target creature **that player** controls" has to know which
    player before it can offer one, and the antecedent is the timing clause.

    Without it the flag matched no seat at all and the picker offered nothing —
    a supported card no player could cast."""
    pool = set_pool("MIR")
    lea = _w3g4i_lea()
    mine = _w3g4i_Permanent(card=lea["Grizzly Bears"])
    theirs = _w3g4i_Permanent(card=lea["Hill Giant"])
    game = _w3g4i_game(pool, mine=[mine], theirs=[theirs])

    spec = game.cast_target_spec(0, pool["Delirium"])
    offered = {t["name"] for t in spec["valid_targets"]}

    assert offered == {"Hill Giant"}, spec["valid_targets"]


def test_w3g4_delirium_prevents_combat_damage_both_ways(set_pool):
    """The third sentence is the shield Maze of Ith prints, armed off the same
    record: combat damage to *and* by the creature, and noncombat damage
    untouched."""
    pool = set_pool("MIR")
    lea = _w3g4i_lea()
    bear = _w3g4i_Permanent(card=lea["Grizzly Bears"])
    blocker = _w3g4i_Permanent(card=lea["Hill Giant"])
    game = _w3g4i_game(pool, mine=[blocker], theirs=[bear])

    game.cast_from_hand(
        0, "Delirium", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()
    game._settle()

    game._mark_damage_on_permanent(bear, 3, source=blocker, combat=True)
    assert bear.damage_marked == 0, game.log

    game._mark_damage_on_permanent(bear, 1, source=pool["Delirium"], combat=False)
    assert bear.damage_marked == 1, "only *combat* damage is prevented"


def test_w3g4_delirium_deals_no_damage_when_its_creature_has_left(set_pool):
    """The biter is read out of the scratchpad by id, so a permanent that is
    gone deals nothing — CR 608.2's last-known information is about reading a
    characteristic, not about acting from a graveyard."""
    pool = set_pool("MIR")
    bear = _w3g4i_Permanent(card=_w3g4i_lea()["Grizzly Bears"])
    game = _w3g4i_game(pool, theirs=[bear])

    from engine.oracle import compile_card_oracle as _compile
    from engine.game_types import OracleExecutionContext as _Ctx
    from engine.handlers.registry import EFFECT_HANDLERS as _HANDLERS

    program = _compile(pool["Delirium"])
    steps = program.instructions[0].payload["steps"]
    bite = next(s for s in steps if s.kind == "bound_bites_player")

    context = _Ctx(
        caster=game.players[0], target=game.players[1], card=pool["Delirium"],
        results={"tapped_permanents": [bear.permanent_id + 500]},
    )
    _HANDLERS[bite.kind](game, bite, context)

    assert game.players[1].life == 20, game.log

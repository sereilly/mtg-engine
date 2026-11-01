"""Shipped cards Legions' libraries-graveyards-and-exile group found mis-playing
on the way to its own cards — each with the seam it moved.

None of these is a Legions card. Ashen Powder reanimated out of its caster's
own graveyard because the reanimation read every printed owner as "your"; a
face-down creature caught by Wall of Nets' exile sweep went into exile as the
blank 2/2 because the sweep put the card into exile before the one transition
out had revealed it (CR 708.9).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.face_down import turn_face_down
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec

from tests.helpers import declare_attack, resolve_stack


def _duel(*, hand0=(), grave0=(), grave1=()):
    game = Game(players=[
        PlayerState(name="P0", hand=list(hand0), graveyard=list(grave0)),
        PlayerState(name="P1", graveyard=list(grave1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game._set_phase_and_step("precombat_main", "main")
    return game


# -- "from an opponent's graveyard" is an opponent's --------------------------


def test_ashen_powder_reanimates_out_of_an_opponents_graveyard_only(set_pool):
    """"Put target creature card from an opponent's graveyard onto the
    battlefield under your control." The picker offers the opponent's
    creature card and not the caster's own; the cast naming the caster's own
    pile is refused (CR 601.2c) and the one naming the opponent's puts it
    onto the caster's battlefield."""
    mir, lea = set_pool("MIR"), set_pool("LEA")
    powder = mir["Ashen Powder"]
    spec = derive_cast_spec(powder, compile_card_oracle(powder))
    assert spec.get("opponent_graveyard_only") and not spec.get("own_graveyard_only")

    game = _duel(
        hand0=[powder], grave0=[lea["Grizzly Bears"]], grave1=[lea["Hill Giant"]],
    )
    offered = game._enumerate_targets(0, powder, spec, for_cast=True)
    assert [(t["seat"], t["name"]) for t in offered] == [(1, "Hill Giant")]
    refused = game.queue_from_hand(
        0, "Ashen Powder", target_player_index=0, target_permanent_index=0,
    )
    assert not refused.supported, refused.details
    assert game.queue_from_hand(
        0, "Ashen Powder", target_player_index=1, target_permanent_index=0,
    ).supported
    resolve_stack(game)
    assert [(p.card.name, game.controller_index_of(p)) for p in game.all_permanents()] == [
        ("Hill Giant", 0),
    ]
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears", "Ashen Powder"]


# -- an exile sweep puts the card a face-down creature is ---------------------


def test_wall_of_nets_exiles_a_face_down_attacker_as_the_card_it_is(set_pool):
    """"At end of combat, exile all creatures blocked by this creature. When
    this creature leaves the battlefield, return all cards exiled with it to
    the battlefield under their owners' control." A face-down Krosan Colossus
    it blocked goes into exile as Krosan Colossus (CR 708.9: revealed as it
    moves) — not as the blank 2/2 — and comes back as the 9/9 it is."""
    exo, ons = set_pool("EXO"), set_pool("ONS")
    game = _duel()
    colossus = Permanent(card=ons["Krosan Colossus"])
    game._put_permanent_onto_battlefield(0, colossus, None)
    assert turn_face_down(game, colossus)
    wall = Permanent(card=exo["Wall of Nets"])
    game._put_permanent_onto_battlefield(1, wall, None)
    declare_attack(game, 0, blocks={
        game.battlefield_index_of(wall): game.battlefield_index_of(colossus),
    })
    # Through the end of combat step, whose "at end of combat" trigger is put
    # on the stack and resolved as the step is left.
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        resolve_stack(game)
    assert "Wall of Nets exiled 1 permanent(s)" in game.log
    assert [c.name for c in game.players[0].exile] == ["Krosan Colossus"]
    assert not any(p.card.name == "Krosan Colossus" for p in game.all_permanents())

    game.sacrifice_permanent(wall)
    resolve_stack(game)
    (back,) = [p for p in game.controlled_by(0)]
    assert back.card.name == "Krosan Colossus"
    assert (back.effective_power, back.effective_toughness) == (9, 9)
    assert game.players[0].exile == []

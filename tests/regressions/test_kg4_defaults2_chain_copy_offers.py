"""The Chains' copy offers ("…they may copy this spell and may choose a new
target for that copy"): what a seat nobody asks answers.

``ai_prompts.copy_offer_turns_on_its_taker`` declined every copy whose
original targeted the taker, on the premise that the copy keeps its target —
stale since the copy offer's default measures a new one
(``spell_copies.offer_new_targets``, ``ai_prompts.choose_copy_target``). So
every Chain's copy was declined, for every seat: the AI never sent a Chain
Lightning back, however good the shot.

The offer is weighed now (``ai_prompt_picks.copy_offer_pick``): taking it —
the price paid and the copy the price buys, aimed by the copy default — is
rehearsed against declining it, with the other seat's own reply to the copy
weighed one level down (it may copy it straight back) and every later offer
declined. Taken where the copy lands off the taker and does more than it
costs; declined where it can only hit the taker, where it does nothing
there, or where the reply would hand it straight back.

Validated backwards: the two "taken" boards fail on ``243f72df`` (declined).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(*, enforce=True) -> Game:
    game = Game(players=[
        PlayerState(name="P1", life=20), PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _drain(game) -> None:
    for _ in range(20):
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def test_chain_lightning_s_copy_is_paid_for_and_sent_back(set_pool, catalog_by_name):
    """P1 shoots P2's Serra Angel; P2 has two untapped Mountains and P1 no
    red source to answer with. Taking the offer is {R}{R} for a copy whose
    measured target is P1's face — 3 damage nobody sends back. It was
    declined, because the copy's *kept* target was P2's own Angel."""
    game = _table()
    angel = _put(game, 1, catalog_by_name["Serra Angel"])
    mountains = [_put(game, 1, catalog_by_name["Mountain"]) for _ in range(2)]
    game.players[0].hand = [set_pool("LEG")["Chain Lightning"]]
    game.players[0].mana_pool["R"] = 1
    assert game.cast_from_hand(
        0, "Chain Lightning", target_permanent_ids=[angel.permanent_id],
    ).supported
    _drain(game)
    assert game.players[0].life == 17, game.log[-12:]
    assert all(mountain.tapped for mountain in mountains)
    assert angel.damage_marked == 3
    assert any("P2 copied Chain Lightning" in line for line in game.log), game.log[-12:]


def test_a_copy_the_caster_would_send_straight_back_is_not_taken(set_pool, catalog_by_name):
    """Both seats hold {R}{R} floating (mana costs off, so the cast spends
    none): the copy aimed at P1 would be paid for and sent straight back at
    P2 — a wash for P2's {R}{R}, and declined."""
    game = _table(enforce=False)
    angel = _put(game, 1, catalog_by_name["Serra Angel"])
    game.players[0].hand = [set_pool("LEG")["Chain Lightning"]]
    for seat in (0, 1):
        game.players[seat].mana_pool["R"] = 2
    assert game.cast_from_hand(
        0, "Chain Lightning", target_permanent_ids=[angel.permanent_id],
    ).supported
    _drain(game)
    assert [player.life for player in game.players] == [20, 20], game.log[-12:]
    assert game.players[1].mana_pool.get("R", 0) == 2
    assert not any("copied Chain Lightning" in line for line in game.log), game.log[-12:]
    assert "P2 declined Chain Lightning (the copy is not worth what taking it costs)" in game.log
    assert not game.stack and not game.pending_choices


def test_chain_of_smog_is_copied_where_the_caster_has_more_to_lose(set_pool, catalog_by_name):
    """P1 (two cards behind the Smog) makes P2 discard two of three. The copy
    aimed at P1 takes P1's two; P1's reply takes P2's last one; P1 has nothing
    left to lose and the chain ends. It was declined: the copy's kept target
    was P2."""
    island = catalog_by_name["Island"]
    game = _table(enforce=False)
    for seat in (0, 1):
        game.players[seat].library = [island] * 6
    game.players[0].hand = [set_pool("ONS")["Chain of Smog"], catalog_by_name["Mountain"], catalog_by_name["Forest"]]
    game.players[1].hand = [catalog_by_name["Plains"]] * 3
    assert game.cast_from_hand(0, "Chain of Smog", target_player_index=1).supported
    _drain(game)
    assert any("P2 copied Chain of Smog" in line for line in game.log), game.log[-12:]
    assert game.players[0].hand == [], game.log[-12:]
    assert not game.stack and not game.pending_choices


def test_chain_of_acid_s_copy_destroys_the_caster_s_enchantment(set_pool, catalog_by_name):
    """P1 destroys P2's Bad Moon; P1 controls a Crusade and P2 nothing else
    the copy could take back. The copy is free and lands on the Crusade."""
    game = _table()
    crusade = _put(game, 0, set_pool("LEA")["Crusade"])
    bad_moon = _put(game, 1, set_pool("LEA")["Bad Moon"])
    game.players[0].hand = [set_pool("ONS")["Chain of Acid"]]
    game.players[0].mana_pool.update({"G": 1, "C": 3})
    assert game.cast_from_hand(
        0, "Chain of Acid", target_permanent_ids=[bad_moon.permanent_id],
    ).supported
    _drain(game)
    assert not game.is_on_battlefield(bad_moon)
    assert not game.is_on_battlefield(crusade), game.log[-12:]


def test_chain_of_acid_s_copy_that_could_only_hit_its_taker_is_declined(set_pool, catalog_by_name):
    """The same shot with P1 holding no noncreature permanent: the copy's
    only targets are P2's own (its Crusade), so it is declined."""
    game = _table()
    crusade = _put(game, 1, set_pool("LEA")["Crusade"])
    bad_moon = _put(game, 1, set_pool("LEA")["Bad Moon"])
    game.players[0].hand = [set_pool("ONS")["Chain of Acid"]]
    game.players[0].mana_pool.update({"G": 1, "C": 3})
    assert game.cast_from_hand(
        0, "Chain of Acid", target_permanent_ids=[bad_moon.permanent_id],
    ).supported
    _drain(game)
    assert not game.is_on_battlefield(bad_moon)
    assert game.is_on_battlefield(crusade), game.log[-12:]
    assert not any("copied Chain of Acid" in line for line in game.log), game.log[-12:]

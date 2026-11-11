"""The defaults a seat nobody asks takes for a trigger's target and a
re-aimed spell aim at what the effect does most at.

kg5's ``airesp`` turned morphs face up in response
(``ai_special_actions.special_action_in_response``) and measured two
defaults aiming wrong on its board — an opponent's Lightning Bolt at the
seat's Grizzly Bears:

* **Daru Mender** — "When this creature is turned face up, regenerate target
  creature." ``choices/triggers._default_trigger_target`` took the first
  candidate on the wanted side, the Mender itself, and the Bears died. A
  shield (``ai_valuation.SHIELD_KINDS``) is aimed now by
  ``ai_target_sides.shield_target_order``: a creature an opposing object on
  the stack targets first, then one in combat, then the dearest.
* **Willbender** — "…change the target of target spell or ability with a
  single target." ``choices/spells._default_retarget_choice`` put the
  opponent's face ahead of every creature ("a trade this does not price"),
  so the Bolt went to the face beside the Hill Giant it kills. A fixed
  amount of damage now prices each (``ai_target_sides.damage_target_worth``:
  the life it takes, a creature it destroys).

Validated backwards: both boards fail on the base.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from engine import Game, PlayerState, faces
from engine.ai_priority import act_at_priority
from engine.ai_target_sides import shield_target_order, shields_its_target
from engine.card_loader import load_catalog
from engine.face_down import face_down_card
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import settle


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _perm(name: str, *, face_down: bool = False) -> Permanent:
    card = _catalog()[name]
    permanent = Permanent(card=face_down_card(card) if face_down else card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _bolted(morph: str, *, their_life: int = 20):
    """airesp's board: seat 0 holds a face-down *morph*, Grizzly Bears and
    mana for the turn-up; seat 1, a Hill Giant, has just cast Lightning Bolt
    at the Bears in its own main phase; seat 0 holds priority."""
    cards = _catalog()
    hidden, bears, giant = _perm(morph, face_down=True), _perm("Grizzly Bears"), _perm("Hill Giant")
    lands = [_perm("Island") for _ in range(3)] + [_perm("Plains") for _ in range(2)]
    me = PlayerState(name="A", battlefield=[hidden, bears, *lands], library=[cards["Island"]] * 10)
    them = PlayerState(name="B", battlefield=[giant], library=[cards["Island"]] * 10, life=their_life)
    game = Game(players=[me, them])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(1)
    them.hand = [cards["Lightning Bolt"]]
    them.mana_pool.update({"R": 1})
    cast = game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert cast.supported, cast.details
    game.priority_player_index = 0
    return game, hidden, bears, giant


def test_daru_mender_turned_up_in_response_regenerates_the_bolted_creature():
    game, mender, bears, _giant = _bolted("Daru Mender")
    act = act_at_priority(game, 0)
    assert act is not None and act.supported, act
    settle(game)
    assert any("Daru Mender: targets Grizzly Bears" in line for line in game.log), game.log[-10:]
    assert game.is_on_battlefield(bears), game.log[-10:]
    assert any("Grizzly Bears regenerated" in line for line in game.log)


def test_willbender_sends_the_bolt_at_the_creature_it_kills():
    game, _willbender, bears, giant = _bolted("Willbender")
    act = act_at_priority(game, 0)
    assert act is not None and act.supported, act
    settle(game)
    assert game.is_on_battlefield(bears)
    assert not game.is_on_battlefield(giant), game.log[-10:]
    assert [player.life for player in game.players] == [20, 20], game.log[-10:]


def test_a_face_the_bolt_kills_is_worth_more_than_the_giant():
    """The trade is priced, not a preference reversed: at 3 life the face is
    the game, and Willbender sends the Bolt there."""
    game, willbender, bears, giant = _bolted("Willbender", their_life=3)
    from engine.special_actions import take_permanent_special_action

    take_permanent_special_action(game, 0, willbender, "turn_face_up")
    settle(game)
    assert game.players[1].life <= 0 or game.is_game_over(), game.log[-10:]
    assert game.is_on_battlefield(giant)


def _shield_triggers() -> list:
    found = []
    for unit in faces.compilation_units(sorted(_catalog().values(), key=lambda c: c.name)):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        for trigger in program.triggered_abilities:
            if shields_its_target(trigger.instruction) and "target" in (trigger.source_line or "").lower():
                found.append((unit.name, trigger))
    return found


def test_every_shield_trigger_is_aimed_at_the_threatened_creature():
    """Every shipped trigger whose effect is a shield aimed at a target, read
    on the Bolt board: the threatened Bears is first, before the shield's own
    source and before a creature worth more (the Hill Giant, given to seat 0
    here) that nothing threatens."""
    rows = _shield_triggers()
    # Daru Mender's, and Sunfire Balm's "any target" (a face first, by the
    # seat branch before this reading).
    assert {"Daru Mender", "Sunfire Balm"} <= {name for name, _trigger in rows}, rows
    game, mender, bears, giant = _bolted("Daru Mender")
    game.players[1].battlefield.remove(giant)
    game.players[0].battlefield.insert(0, giant)
    game._sync_control()
    ordered = shield_target_order(game, 0, [p for p in game.controlled_by(0) if p.is_creature])
    assert ordered[0] is bears, [p.card.name for p in ordered]
    assert ordered[1] is giant, [p.card.name for p in ordered]


@pytest.mark.parametrize("morph", ["Daru Mender", "Willbender"])
def test_the_morph_is_turned_up_where_its_default_pays(morph):
    """The response itself is the AI's (``act_at_priority``): with its
    trigger aimed where it pays, the turn-up is a rehearsal that saves the
    Bears or kills the Giant, so it is made."""
    game, hidden, _bears, _giant = _bolted(morph)
    act = act_at_priority(game, 0)
    assert act is not None and getattr(act, "kind", None) == "special", act

"""Two shipped-shape defects found driving CHK W1G3's drive list.

1. **"Destroy target … with mana value X" on an activated ability was not
   held to X.** The cast gate holds a spell's X to its target's mana value
   (Detonate, Spell Blast — ``_validate_cast_targets``); the activation gate
   had no such check, so Hearth Kami (CHK), Gorilla Shaman (Alliances) and
   Plaguebearer (Exodus) destroyed any artifact or creature for any X. Now
   ``LegalityAbilitiesMixin._mana_value_x_refusal`` refuses the pair before
   any cost is paid.

2. **A dies-trigger that divides, dying in a sweep, divided among the dying.**
   Jugan, the Rising Star ("…distribute five +1/+1 counters among any number of
   target creatures") died to Wrath of God beside four Dragons and divided its
   counters among them while the sweep was still under way; every one then
   fizzled (CR 608.2b). A trigger's choices wait for the unit of play that set
   it off to finish (CR 603.3, 117.5) — every kind but a division and a roles
   pair already did (``_trigger_choice_waits``). Shambling Swarm (Torment)
   shares the shape.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on

from tests.helpers import _nosick, settle


def _table(set_pool, mine, theirs, *, hand=(), interactive=()):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[_nosick(Permanent(card=c)) for c in mine],
                    hand=list(hand), library=[island] * 10),
        PlayerState(name="P2", battlefield=[_nosick(Permanent(card=c)) for c in theirs],
                    library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._settle()
    return game


@pytest.mark.parametrize("name, code, victim", [
    ("Hearth Kami", "CHK", ("Jayemdae Tome", "LEA")),
    ("Gorilla Shaman", "ALL", ("Jayemdae Tome", "LEA")),
    ("Plaguebearer", "EXO", ("Hill Giant", "LEA")),
])
def test_a_mana_value_x_target_is_held_to_the_activations_x(set_pool, name, code, victim):
    victim_name, victim_code = victim
    target_card = set_pool(victim_code)[victim_name]
    game = _table(set_pool, [set_pool(code)[name]], [target_card])
    target = next(p for p in game.controlled_by(1) if p.card.name == victim_name)
    refused = game.activate_permanent_ability(
        0, name, target_permanent_ids=[target.permanent_id], x_value=1,
    )
    assert not refused.supported and "mana value X" in refused.details
    assert game.is_on_battlefield(target)
    assert name in [p.card.name for p in game.controlled_by(0)]  # no cost paid
    accepted = game.activate_permanent_ability(
        0, name, target_permanent_ids=[target.permanent_id],
        x_value=int(target_card.cmc),
    )
    assert accepted.supported, accepted.details
    settle(game)
    assert victim_name in [c.name for c in game.players[1].graveyard]


@pytest.mark.parametrize("interactive", [(), (0,)])
def test_a_dying_divider_divides_among_what_survived_the_sweep(set_pool, interactive):
    """Wrath of God destroys Jugan, a Bear and a Hill Giant one after another
    inside its resolution; the indestructible Darksteel Gargoyle survives, and is
    the only creature offered — at a seat that is asked and at one that is
    not (whose default used to spread the counters over the dying)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _table(
        set_pool,
        [chk["Jugan, the Rising Star"], lea["Grizzly Bears"], set_pool("DST")["Darksteel Gargoyle"]],
        [lea["Hill Giant"]],
        hand=[lea["Wrath of God"]], interactive=interactive,
    )
    gargoyle = next(p for p in game.controlled_by(0) if p.card.name == "Darksteel Gargoyle")
    assert game.cast_from_hand(0, "Wrath of God").supported
    if interactive:
        asked = settle(game, defaults=False)
        assert asked is not None and asked.kind == "trigger_target", game.log[-8:]
        assert [t["name"] for t in asked.data["targets"]] == ["Darksteel Gargoyle"]
        assert game.confirm_trigger_target(0, permanent_ids=[gargoyle.permanent_id], amounts=[5])
    settle(game)
    assert game.is_on_battlefield(gargoyle)
    assert counters_on(gargoyle, "+1/+1") == 5, game.log[-12:]


def test_a_dying_divider_with_nothing_left_is_removed(set_pool):
    """Wrath of God takes every creature: the division has no legal target
    once the sweep is over (CR 603.3d) — it never names the dying."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _table(
        set_pool, [chk["Jugan, the Rising Star"], lea["Grizzly Bears"]], [lea["Hill Giant"]],
        hand=[lea["Wrath of God"]],
    )
    assert game.cast_from_hand(0, "Wrath of God").supported
    settle(game)
    assert any(
        "Jugan, the Rising Star's triggered ability was removed" in line for line in game.log
    ), game.log[-10:]
    assert not any("Jugan, the Rising Star: targets" in line for line in game.log)

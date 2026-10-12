"""Regression: "that spell" under a cast trigger scoped to its controller.

``you_cast_spell`` was the one cast event of the three that froze nothing:
its emit carried neither ``cast_card`` nor ``cast_item``, where the
any-player and the opponent-scoped ones carry both. Two things followed, in
opposite directions:

* "copy **that spell**" lowered under it anyway - the copy had no event gate
  at all - so Mirari ("Whenever you cast an instant or sorcery spell, you may
  pay {3}. If you do, copy that spell.") took its {3} and resolved for "that
  spell is no longer on the stack";
* every *gated* reader of the phrase ("where X is that spell's mana value")
  refused it under "whenever you cast", though the sentence is as printable
  there as under "whenever a player casts".

The emit carries both keys now, ``lowering/_events.CAST_SPELL_EVENTS`` lists
the three caster-scoped kinds whose emits do, and the copy is gated on that
table like every other reader. These are invented cards on purpose: the claim
is about a sentence under an event, not about a name.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _table(catalog_by_name, permanent_card, hand):
    game = Game(players=[
        PlayerState("A", hand=[catalog_by_name[name] for name in hand],
                    library=[catalog_by_name["Forest"]] * 6),
        PlayerState("B", hand=[catalog_by_name["Craw Wurm"]],
                    library=[catalog_by_name["Forest"]] * 6),
    ])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, Permanent(card=permanent_card), None)
    return game


@pytest.mark.parametrize("opening, gains", [
    ("Whenever you cast a spell", [6, 2]),
    ("Whenever you cast your first creature spell each turn", [6, 0]),
    ("Whenever a player casts a spell", [6, 2]),
])
def test_that_spells_mana_value_is_read_under_a_caster_scoped_trigger(
    catalog_by_name, opening, gains
):
    """Craw Wurm (6) then Grizzly Bears (2): the number is the spell that
    fired the trigger, each time."""
    shrine = _mk_card(
        "Tally Shrine", "{2}", "Enchantment",
        f"{opening}, you gain X life, where X is that spell's mana value.",
    )
    assert compile_card_oracle(shrine).supported
    game = _table(catalog_by_name, shrine, ["Craw Wurm", "Grizzly Bears"])
    life = 20
    for name, gain in zip(("Craw Wurm", "Grizzly Bears"), gains):
        assert game.queue_from_hand(0, name).supported
        resolve_stack(game)
        life += gain
        assert game.players[0].life == life, name


def test_a_caster_scoped_trigger_does_not_read_an_opponents_spell(catalog_by_name):
    shrine = _mk_card(
        "Tally Shrine", "{2}", "Enchantment",
        "Whenever you cast a spell, you gain X life, where X is that spell's "
        "mana value.",
    )
    game = _table(catalog_by_name, shrine, [])
    assert game.queue_from_hand(1, "Craw Wurm").supported
    resolve_stack(game)
    assert game.players[0].life == 20


@pytest.mark.parametrize("type_line, text", [
    ("Creature - Wizard",
     "When this creature enters, copy that spell. You may choose new targets "
     "for the copy."),
    ("Creature - Wizard",
     "{T}: Copy that spell. You may choose new targets for the copy."),
    ("Instant", "Copy that spell. You may choose new targets for the copy."),
    ("Enchantment",
     "Whenever a creature dies, copy that spell. You may choose new targets "
     "for the copy."),
])
def test_copy_that_spell_refuses_where_no_event_froze_a_spell(type_line, text):
    """The refusing half of the gate. Each of these compiled supported and
    could only ever resolve having copied nothing."""
    card = _mk_card("Echo Probe", "{U}", type_line, text)
    assert not compile_card_oracle(card).supported


@pytest.mark.parametrize("opening", [
    "Whenever you cast an instant or sorcery spell",
    "Whenever you cast your first instant or sorcery spell each turn",
    "Whenever a player casts an instant spell",
    "Whenever an opponent casts an instant spell",
])
def test_copy_that_spell_copies_under_every_event_that_freezes_one(
    catalog_by_name, opening
):
    echo = _mk_card(
        "Echo Shrine", "{2}", "Enchantment",
        f"{opening}, copy that spell. You may choose new targets for the copy.",
    )
    assert compile_card_oracle(echo).supported
    game = _table(catalog_by_name, echo, ["Lightning Bolt"])
    caster = 1 if "opponent" in opening else 0
    if caster == 1:
        game.players[1].hand.append(catalog_by_name["Lightning Bolt"])
    assert game.queue_from_hand(
        caster, "Lightning Bolt", target_player_index=1 - caster
    ).supported
    resolve_stack(game)
    # The copy belongs to the shrine's controller and keeps the original's
    # target (nobody was asked: neither seat is interactive).
    assert game.players[1 - caster].life == 14

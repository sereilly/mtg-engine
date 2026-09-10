"""Rules tests earned by Urza's Destiny wave 1, group 4 — trigger conditions
and what announces them.

Eight cards, and the thing they have in common is not an effect: every one of
them is a **trigger condition** the engine had no announcement for, or had an
announcement for only half of. That is the failure this file is written against,
and it is the quiet one — a condition can sit in ``engine/oracle.py``'s pattern
table *and* the grammar's phrase table, compile a real instruction, satisfy the
support gate and `tests/engine/test_trigger_dispatchers.py` alike, and still
never fire. Nothing crashes and no census can see it.

So each test here drives the event itself rather than asserting on a compiled
program, and each has a twin that watches the trigger *not* fire for the case
the printed narrowing excludes — because a trigger that fires on a strictly
larger set than the card names is wrong in exactly the direction nothing
notices.

Three CR subjects, one per shape:

* **CR 603.1b** — one ability with more than one trigger condition. Goblin
  Marshal and Hunting Moa print "enters or dies", whose two halves this engine
  announces from two different fire sites and carries out by two different
  mechanisms (inline at entry, on the stack at death).
* **CR 603.2** — "becomes the target of". Rayne is the first card in the pool
  whose subject is a *player*, and CR 115.1 lets a spell or ability target one.
* **CR 603.4** — the intervening-if. Impatience asks a per-seat, per-turn
  record about the seat its own event named.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import CardDefinition, Permanent, PlayerState

from tests.helpers import resolve_stack


def _g4r_catalog():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _g4r_card(name: str, type_line: str = "Creature - Test",
              oracle_text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": "1", "toughness": "1"},
    )


def _g4r_duel() -> Game:
    seats = [
        PlayerState(name=name,
                    library=[_g4r_card(f"{name}-lib{i}") for i in range(9)],
                    hand=[], battlefield=[])
        for name in ("A", "B")
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    return game


def _g4r_settle(game: Game) -> None:
    for _ in range(8):
        resolve_stack(game)
        owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
        if not owed:
            return
        for choice in owed:
            game.resolve_pending_choice(choice.kind, choice.player_index, accept=True)


@pytest.mark.cr("603.1b", "603.3")
@pytest.mark.parametrize("event", ["enters", "dies"])
def test_one_ability_with_two_trigger_conditions_fires_on_each(event):
    """CR 603.1b: an ability may have more than one trigger condition.

    Both halves, because the engine reaches them by different routes: the entry
    half is carried out inside the resolution that put the permanent there and
    the death half goes on the stack (CR 603.3). A single-kind alias for either
    one would leave the other announced by nothing, with the card compiling
    supported either way.
    """
    marshal = _g4r_catalog()["Goblin Marshal"]
    game = _g4r_duel()
    permanent = Permanent(card=marshal)
    if event == "enters":
        game._put_permanent_onto_battlefield(0, permanent, None)
    else:
        game.players[0].battlefield.append(permanent)
        game._sync_control()
        game._permanent_to_graveyard(game.players[0], permanent)
    _g4r_settle(game)
    tokens = [p for p in list(game.controlled_by(0)) if p.card.name == "Goblin Token"]
    assert len(tokens) == 2


@pytest.mark.cr("603.2", "115.1")
def test_a_player_becoming_a_target_is_announced():
    """CR 603.2 over CR 115.1's other kind of target.

    A spell's targets are objects **and/or players**, and until Rayne the engine
    announced "becomes the target of" for permanents alone. A condition naming a
    seat therefore had no event at all — the half of the card that says "you"
    was silent while the card reported itself supported.
    """
    rayne = _g4r_catalog()["Rayne, Academy Chancellor"]
    game = _g4r_duel()
    game.players[0].battlefield.append(Permanent(card=rayne))
    game._sync_control()
    game.players[1].hand.append(
        _g4r_card("G4R Bolt", "Instant",
                  oracle_text="G4R Bolt deals 3 damage to target player.")
    )
    before = len(game.players[0].hand)
    game.cast_from_hand(1, "G4R Bolt", target_player_index=0)
    _g4r_settle(game)
    assert len(game.players[0].hand) - before == 1


@pytest.mark.cr("603.2", "109.5")
def test_becoming_a_target_is_not_announced_for_a_seat_nothing_targeted():
    """The twin, and the one that matters.

    ``target_player_index`` doubles as a *battlefield* index beside a permanent
    index, so a spell aimed at a creature carries a seat that targets nobody.
    Announced without asking the compiled program whether the spell can target a
    player at all, Rayne would draw a card off every removal spell an opponent
    pointed at anything.
    """
    rayne = _g4r_catalog()["Rayne, Academy Chancellor"]
    game = _g4r_duel()
    game.players[0].battlefield.append(Permanent(card=rayne))
    bear = Permanent(card=_g4r_card("G4R Bear"))
    game.players[1].battlefield.append(bear)
    game._sync_control()
    game.players[1].hand.append(
        _g4r_card("G4R Zap", "Instant",
                  oracle_text="G4R Zap deals 2 damage to target creature.")
    )
    before = len(game.players[0].hand)
    game.cast_from_hand(
        1, "G4R Zap", target_player_index=1,
        target_permanent_index=game.players[1].battlefield.index(bear),
    )
    _g4r_settle(game)
    assert len(game.players[0].hand) == before


@pytest.mark.cr("603.4")
@pytest.mark.parametrize("caster,fires", [(None, True), (0, False), (1, True)])
def test_an_intervening_if_reads_the_seat_its_own_event_named(caster, fires):
    """CR 603.4: the ability triggers only if the stated condition is true.

    Impatience's condition is about "**that** player" — the seat the trigger's
    own event named, which is the same seat the damage is dealt to. Read as the
    source's controller instead, the card would be right only on its own end
    step and wrong on every other one; the third case here is what tells those
    two readings apart.
    """
    impatience = _g4r_catalog()["Impatience"]
    game = _g4r_duel()
    game.players[0].battlefield.append(Permanent(card=impatience))
    game._sync_control()
    game.active_player_index = 0
    if caster is not None:
        game.players[caster].spells_cast_this_turn.append(_g4r_card("G4R Spell"))
    before = game.players[0].life
    game.enter_turn_phase("ending")
    resolve_stack(game)
    assert (before - game.players[0].life == 2) is fires


@pytest.mark.cr("701.21a", "603.10")
@pytest.mark.parametrize("dealt", [1, 2, 3])
def test_a_sacrifice_sized_by_its_own_event(dealt):
    """CR 701.21a's sacrifice, counted off the number the event carried.

    "Whenever this creature is dealt damage, sacrifice **that many**
    permanents." The number is frozen into the trigger's context by the fire
    site (CR 603.10) because by the time the ability resolves the marked damage
    may have been added to or wiped — and a lowering that read it out of this
    resolution's scratchpad instead would sacrifice **nothing** while logging
    itself resolved.
    """
    negator = _g4r_catalog()["Phyrexian Negator"]
    game = _g4r_duel()
    permanent = Permanent(card=negator)
    game.players[0].battlefield.append(permanent)
    for index in range(5):
        game.players[0].battlefield.append(Permanent(card=_g4r_card(f"G4R Chaff{index}")))
    game._sync_control()
    before = len(list(game.controlled_by(0)))
    game._fire_dealt_damage_triggers(permanent, dealt)
    for _ in range(10):
        resolve_stack(game)
        if not game.pending_choices:
            break
        game.auto_resolve_pending_choices()
    assert before - len(list(game.controlled_by(0))) == dealt


@pytest.mark.cr("603.5")
def test_an_optional_trigger_goes_on_the_stack_and_asks_at_resolution():
    """CR 603.5: a "may" ability goes on the stack when it triggers regardless
    of whether its controller intends to take the option; the choice is made as
    it resolves.

    Compost is the one to ask it of, because the alternative reading — deciding
    at announcement — is invisible when the answer is yes.
    """
    compost = _g4r_catalog()["Compost"]
    game = _g4r_duel()
    game.players[0].battlefield.append(Permanent(card=compost))
    game._sync_control()
    black = CardDefinition(
        name="G4R Black Card", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=("B",), color_identity=("B",), keywords=(),
        produced_mana=(),
        raw={"name": "G4R Black Card", "type_line": "Creature - Test",
             "power": "1", "toughness": "1"},
    )
    before = len(game.players[0].hand)
    game.put_card_into_graveyard(game.players[1], black)
    # The ability is on the stack before anyone has been asked anything.
    assert game.stack
    resolve_stack(game)
    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert owed, "the option is offered as the ability resolves"
    for choice in owed:
        game.resolve_pending_choice(choice.kind, choice.player_index, accept=False)
    assert len(game.players[0].hand) == before

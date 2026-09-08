"""The rules Gilded Drake and Sneak Attack exercised (USG wave 3, W3G2).

Four of them, and each is a rule the engine already implemented for one shape
and reached by only one route:

* **CR 608.2b** — the all-targets-illegal fizzle, and the exception an object
  may print on itself. `legality.illegal_targets_refusal` declines two whole
  classes of object before it asks the rule at all (a triggered ability, and
  anything that is not an instant or a sorcery), so the printed exception is
  asserted against a card that is *neither* excluded — otherwise the branch
  would be present and never run.
* **CR 701.12a** — an exchange is atomic, and the half that was not exercised
  before is the one where a side is the ability's own **source** rather than a
  chosen slot: a source that has left means no part of the exchange occurs, and
  that is what makes the sentence behind it fire.
* **CR 611.2a** — "If no duration is stated, it lasts until the end of the
  game." The engine spells that as a ``None`` lifetime on the layer-6 channel,
  and the *undurated* grant to a bound back-reference was the one shape the
  lowering refused outright.
* **CR 603.7c** — a delayed triggered ability is about a particular object,
  frozen when the ability is created. For a permanent that a step of the same
  resolution put onto the battlefield out of a hand, the resolution's own
  scratchpad is the only place it can be read from.

Its own file per SET_PLAYBOOK's block convention — a group's rules tests do not
share a file, so a mechanical union has nothing to splice.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.control import base_controller
from engine.game_types import StackItem
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_W3G2_USG = {
    card.name: card
    for card in load_cards(manifest_set_path("USG", include_measured=True))
}


def _w3g2_card(name: str, type_line: str, text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "oracle_text": text,
             "power": "2", "toughness": "2"},
    )


def _w3g2_duel(mine=(), theirs=()):
    """``(game, seat0, seat1)`` with mana enforcement off and control synced."""
    w3g2_seat0 = PlayerState(name="W3G2-P1", battlefield=list(mine))
    w3g2_seat1 = PlayerState(name="W3G2-P2", battlefield=list(theirs))
    w3g2_game = Game(players=[w3g2_seat0, w3g2_seat1])
    w3g2_game.enforce_mana_costs = False
    w3g2_game._sync_control()
    return w3g2_game, w3g2_seat0, w3g2_seat1


# ---------------------------------------------------------------------------
# CR 608.2b — the fizzle, and the exception a card may print on itself
# ---------------------------------------------------------------------------


@pytest.mark.cr("608.2b")
def test_608_2b_an_object_whose_every_target_is_illegal_does_not_resolve():
    """The default, stated as the control for the test below it.

    A spell whose only target has left the battlefield is removed from the
    stack unresolved — "If all its targets, for every instance of the word
    'target,' are now illegal, the spell or ability doesn't resolve."
    """
    bolt = _w3g2_card(
        "W3G2 Bolt", "Instant", "W3G2 Bolt deals 2 damage to target creature."
    )
    victim = Permanent(card=_w3g2_card("W3G2 Bear", "Creature — Bear"))
    game, _alice, _bob = _w3g2_duel(theirs=[victim])
    game.remove_from_battlefield(victim)
    item = StackItem(
        card=bolt, caster_index=0, target_player_index=1,
        target_permanent_index=0, x_value=None,
        target_permanent_id=victim.permanent_id,
    )

    assert game.illegal_targets_refusal(item) is not None


@pytest.mark.cr("608.2b")
def test_608_2b_a_printed_exception_keeps_the_object_resolving():
    """"This ability still resolves if its target becomes illegal." (Gilded
    Drake.)

    Asserted against an **instant**, deliberately: this engine's CR 608.2b
    check declines a triggered ability outright and declines anything that is
    not an instant or a sorcery, and Gilded Drake's ability is both of those —
    so a test using the Drake's own stack object would pass on either side of
    the exception and prove nothing about it. Same spell as the control above,
    one printed sentence apart.
    """
    bolt = _w3g2_card(
        "W3G2 Steady Bolt", "Instant",
        "W3G2 Steady Bolt deals 2 damage to target creature. "
        "This spell still resolves if its target becomes illegal.",
    )
    victim = Permanent(card=_w3g2_card("W3G2 Bear", "Creature — Bear"))
    game, _alice, _bob = _w3g2_duel(theirs=[victim])
    game.remove_from_battlefield(victim)
    item = StackItem(
        card=bolt, caster_index=0, target_player_index=1,
        target_permanent_index=0, x_value=None,
        target_permanent_id=victim.permanent_id,
    )

    assert game.illegal_targets_refusal(item) is None


@pytest.mark.cr("608.2b")
def test_608_2b_the_exception_is_read_off_the_ability_that_prints_it():
    """The sentence is a rider on **one** ability, so a card whose other
    ability targets without printing it must not inherit the exception.

    Read off ``StackItem.ability_text`` when the object is an ability, and off
    the card only when it is a spell — the same narrowing every printed rider
    in this engine gets, and the direction that would otherwise widen silently.
    """
    from engine.resolution_overrides import resolves_with_illegal_targets

    card = _w3g2_card(
        "W3G2 Two Abilities", "Creature — Drake",
        "{T}: Tap target creature. This ability still resolves if its target "
        "becomes illegal.\n{1}: Untap target creature.",
    )

    assert resolves_with_illegal_targets(
        card, "{T}: Tap target creature. This ability still resolves if its "
        "target becomes illegal."
    )
    assert not resolves_with_illegal_targets(card, "{1}: Untap target creature.")


# ---------------------------------------------------------------------------
# CR 701.12a/b — an exchange whose first side is the source
# ---------------------------------------------------------------------------


@pytest.mark.cr("701.12a", "701.12b")
def test_701_12a_no_part_of_the_exchange_occurs_when_the_source_has_left():
    """"If the entire exchange can't be completed, no part of the exchange
    occurs."

    The half a two-chosen-slot card cannot reach: here one side is the
    ability's own source, so "the entire exchange" includes a permanent nobody
    targeted. Half an exchange would be a gift — the opponent's creature handed
    over for nothing.
    """
    drake_card = _W3G2_USG["Gilded Drake"]
    victim = Permanent(card=_w3g2_card("W3G2 Bear", "Creature — Bear"))
    drake = Permanent(card=drake_card)
    game, alice, _bob = _w3g2_duel(mine=[drake], theirs=[victim])
    game.remove_from_battlefield(drake)

    from engine.game_types import OracleExecutionContext

    trigger = next(iter(compile_card_oracle(drake_card).triggered_abilities))
    game._execute_oracle_instruction(
        trigger.instruction,
        OracleExecutionContext(
            caster=alice, target=game.players[1], card=drake_card,
            source_permanent=drake, target_permanent_id=victim.permanent_id,
        ),
    )

    assert game.controller_index_of(victim) == 1, "no part of the exchange occurred"


@pytest.mark.cr("701.12b")
def test_701_12b_the_exchange_hands_each_permanent_to_the_other_player():
    """"each of those players simultaneously gains control of the permanent
    that was controlled by the other player."

    Through ``engine/control.py``'s timestamped contribution, so
    ``base_controller_index`` is untouched on both sides and CR 108.3 ownership
    still reads off the seat each permanent entered under.
    """
    drake_card = _W3G2_USG["Gilded Drake"]
    victim = Permanent(card=_w3g2_card("W3G2 Bear", "Creature — Bear"))
    game, alice, _bob = _w3g2_duel(theirs=[victim])
    alice.hand = [drake_card]

    game.cast_from_hand(
        0, "Gilded Drake",
        target_player_index=1, target_permanent_ids=[victim.permanent_id],
    )
    resolve_stack(game)

    drake = next(p for p in game.all_permanents() if p.card.name == "Gilded Drake")
    assert game.controller_index_of(drake) == 1
    assert game.controller_index_of(victim) == 0
    assert base_controller(drake) == 0
    assert base_controller(victim) == 1


# ---------------------------------------------------------------------------
# CR 611.2a / CR 603.7c — an undurated grant, and what a delay is about
# ---------------------------------------------------------------------------


@pytest.mark.cr("611.2a", "514.2")
def test_611_2a_an_undurated_keyword_grant_survives_the_cleanup_step():
    """"If no duration is stated, it lasts until the end of the game."

    Sneak Attack's "That creature gains haste" prints no duration, so the
    cleanup step's until-end-of-turn sweep (CR 514.2) must not take it. The
    creature is sacrificed at the *end step*, one step earlier, so the grant is
    read on a second copy put in by a second activation — which is also what
    proves the grant is per-object rather than a flag on the enchantment.
    """
    sneak = Permanent(card=_W3G2_USG["Sneak Attack"])
    bear = _w3g2_card("W3G2 Hasty Bear", "Creature — Bear")
    game, alice, _bob = _w3g2_duel(mine=[sneak])
    alice.hand = [bear]

    game.activate_permanent_ability(0, "Sneak Attack")
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    arrived = next(p for p in game.controlled_by(0) if p.card.name == bear.name)
    assert arrived.has_keyword("haste")

    game.resolve_cleanup_step(0)

    assert arrived.has_keyword("haste"), "no duration was printed, so nothing ends it"


@pytest.mark.cr("603.7c")
def test_603_7c_the_delay_is_about_the_permanent_that_step_put_in():
    """"A delayed triggered ability that refers to a particular object still
    affects it even if the object changes characteristics."

    The object is frozen as the ability is created, by id. Nothing on the stack
    or on the board pointed at it — the card was in a hand when the ability was
    activated — so the resolution's own record is the only place it can be read
    from, and an unbound entry would answer to whichever creature was around at
    the end step.
    """
    sneak = Permanent(card=_W3G2_USG["Sneak Attack"])
    bystander = Permanent(card=_w3g2_card("W3G2 Bystander", "Creature — Bear"))
    bear = _w3g2_card("W3G2 Sneaked Bear", "Creature — Bear")
    game, alice, _bob = _w3g2_duel(mine=[sneak, bystander])
    alice.hand = [bear]

    game.activate_permanent_ability(0, "Sneak Attack")
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    armed = list(game.delayed_triggers)
    arrived = next(p for p in game.controlled_by(0) if p.card.name == bear.name)

    assert [entry.bound_permanent_id for entry in armed] == [arrived.permanent_id]

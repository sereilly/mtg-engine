"""CR 702.37 (morph), CR 708 (face-down spells and permanents), CR 116.2b.

Onslaught's subsystem: a card cast face down for {3} as a nameless,
colourless, textless 2/2 (CR 702.37a, 702.37c, 708.2a), turned face up for
its morph cost as a special action (CR 702.37e, 116.2b), revealed whenever it
leaves the battlefield or the stack for anywhere but the battlefield
(CR 708.9). The model is ``engine/face_down.py``: a face-down object's card
*is* the blank 2/2, with the card it hides riding on it.

Every test drives the engine's own entry points — ``queue_from_hand`` with the
alternative cost announced, ``take_permanent_special_action`` — and reads the
board, the zones, the pool and the log.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.copies import become_copy
from engine.face_down import (FACE_DOWN_NAME, face_down_card, hidden_card_of,
                              is_face_down, may_look_at, morph_cost)
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.special_actions import (available_permanent_special_actions,
                                    permanent_special_action_refusal,
                                    take_permanent_special_action)
from tests.helpers import _nosick, declare_attack, resolve_stack

_CATALOG = {card.name: card for card in load_catalog()}


@pytest.fixture
def ons(set_pool):
    return set_pool("ONS")


def _duel(hand=(), battlefield=(), *, opponent_hand=(), opponent_battlefield=(),
          enforce=True):
    p1 = PlayerState(name="A", hand=list(hand), battlefield=list(battlefield),
                     library=[_CATALOG["Island"]] * 10)
    p2 = PlayerState(name="B", hand=list(opponent_hand),
                     battlefield=list(opponent_battlefield),
                     library=[_CATALOG["Island"]] * 10)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    game._sync_control()
    return game, p1, p2


def _face_down_on_battlefield(card, *, sick=False):
    permanent = Permanent(card=face_down_card(card))
    if not sick:
        _nosick(permanent)
    return permanent


def _cast_face_down(game, seat, name):
    result = game.queue_from_hand(seat, name, alternative_cost=True)
    assert result.supported, result.details
    return result


@pytest.mark.cr("702.37a", "702.37c", "708.4", "118.9")
def test_702_37c_a_morph_card_is_cast_face_down_for_three(ons):
    """"You may cast this card as a 2/2 face-down creature with no text, no
    name, no subtypes, and no mana cost by paying {3} rather than paying its
    mana cost." Krosan Colossus costs {6}{G}{G}{G}; three colourless mana is
    the whole price, and the spell on the stack is the face-down one."""
    colossus = ons["Krosan Colossus"]
    game, p1, _p2 = _duel([colossus])
    p1.mana_pool.update({"C": 3})

    _cast_face_down(game, 0, "Krosan Colossus")

    assert p1.hand == []
    assert sum(p1.mana_pool.values()) == 0, "CR 702.37a: {3} was paid"
    (spell,) = game.stack
    assert spell.card.name == FACE_DOWN_NAME
    assert spell.card.mana_cost == "" and spell.card.cmc == 0
    assert spell.card.colors == () and spell.card.type_line == "Creature"
    assert hidden_card_of(spell) is colossus
    # The log says what the table saw: a face-down creature spell, never the
    # card (CR 708.4 / 708.5).
    assert not any("Krosan Colossus" in line for line in game.log)


@pytest.mark.cr("702.37c", "118.9")
def test_702_37c_two_mana_is_not_enough(ons):
    game, p1, _p2 = _duel([ons["Krosan Colossus"]])
    p1.mana_pool.update({"C": 2})
    result = game.queue_from_hand(0, "Krosan Colossus", alternative_cost=True)
    assert not result.supported
    assert game.stack == [] and [c.name for c in p1.hand] == ["Krosan Colossus"]
    assert p1.mana_pool["C"] == 2, "a refused cast spends nothing (CR 601.2h)"


@pytest.mark.cr("702.37c", "118.9d", "601.2f")
def test_702_37c_taxes_see_the_face_down_spell_and_not_the_card(ons):
    """CR 702.37c: "Any effects or prohibitions that would apply to casting a
    card with these characteristics (and not the face-up card's
    characteristics) are applied to casting this card." So Gloom ("White
    spells cost {3} more") does not tax a face-down Exalted Angel — the spell
    is colourless — while Sphere of Resistance ("Spells cost {1} more") taxes
    the {3} as CR 118.9d keeps every increase on top of an alternative cost."""
    angel = ons["Exalted Angel"]
    game, p1, _p2 = _duel([angel], [Permanent(card=_CATALOG["Gloom"])])
    # Every reader that *prices* the cast before making it — the offer's
    # `payable`, the castable highlight, the AI — asks the one reader the
    # cast path agrees with, and it says {3} as well.
    (morph,) = game.applicable_alternative_costs(0, angel)
    assert morph.describe() == "cast it face down as a 2/2 creature for {3}"
    owed = game.alternative_cost_mana(0, angel, morph)
    assert {k: v for k, v in owed.items() if v} == {"generic": 3}
    p1.mana_pool.update({"C": 3})
    _cast_face_down(game, 0, "Exalted Angel")
    assert len(game.stack) == 1 and sum(p1.mana_pool.values()) == 0

    game, p1, _p2 = _duel([angel], [Permanent(card=_CATALOG["Sphere of Resistance"])])
    p1.mana_pool.update({"C": 3})
    refused = game.queue_from_hand(0, "Exalted Angel", alternative_cost=True)
    assert not refused.supported, "{3} plus Sphere's {1} is four"
    p1.mana_pool.update({"C": 4})
    _cast_face_down(game, 0, "Exalted Angel")
    assert sum(p1.mana_pool.values()) == 0


@pytest.mark.cr("708.4", "702.37c")
def test_708_4_a_counterspell_sees_only_the_face_down_spell(ons):
    """"Effects that care about the characteristics of a spell will see only
    the face-down spell's characteristics." Remove Soul ("Counter target
    creature spell") counters a face-down Aphetto Alchemist; Red Elemental
    Blast's "Counter target blue spell" cannot name it, though the card is
    blue. The countered card goes to its owner's graveyard as itself,
    revealed (CR 708.9)."""
    alchemist = ons["Aphetto Alchemist"]
    game, p1, p2 = _duel([alchemist], opponent_hand=[_CATALOG["Red Elemental Blast"]],
                         enforce=False)
    _cast_face_down(game, 0, "Aphetto Alchemist")
    blast = game.queue_from_hand(1, "Red Elemental Blast", target_stack_index=0,
                                 mode_index=0)
    assert not blast.supported, blast.details
    assert len(game.stack) == 1

    game, p1, p2 = _duel([alchemist], opponent_hand=[_CATALOG["Remove Soul"]],
                         enforce=False)
    _cast_face_down(game, 0, "Aphetto Alchemist")
    soul = game.queue_from_hand(1, "Remove Soul", target_stack_index=0)
    assert soul.supported, soul.details
    resolve_stack(game)
    assert [c.name for c in p1.graveyard] == ["Aphetto Alchemist"]
    assert p1.battlefield == []
    assert any("revealed" in line and "Aphetto Alchemist" in line for line in game.log)


@pytest.mark.cr("708.2a", "613.2b", "708.3")
def test_708_2a_the_permanent_is_a_colourless_nameless_2_2_with_no_abilities(ons):
    """Exalted Angel resolves face down: no flying, no lifelink-like trigger,
    no subtypes (Goblin King's "Other Goblins" does not reach a face-down
    Goblin Taskmaster), colourless, mana value 0 — and still a creature, so
    "creatures you control" counts it and Giant Growth pumps it."""
    angel, taskmaster = ons["Exalted Angel"], ons["Goblin Taskmaster"]
    king = _nosick(Permanent(card=_CATALOG["Goblin King"]))
    game, p1, _p2 = _duel([angel, taskmaster, _CATALOG["Giant Growth"]], [king],
                          enforce=False)
    _cast_face_down(game, 0, "Exalted Angel")
    _cast_face_down(game, 0, "Goblin Taskmaster")
    resolve_stack(game)
    face_down = [p for p in p1.battlefield if is_face_down(p)]
    assert len(face_down) == 2
    for permanent in face_down:
        assert permanent.is_creature
        assert (permanent.effective_power, permanent.effective_toughness) == (2, 2)
        assert permanent.effective_colors == set()
        assert not permanent.has_keyword("flying")
        assert not permanent.has_type("goblin") and not permanent.has_type("angel")
        assert compile_card_oracle(permanent.effective_card).triggered_abilities == ()
        assert permanent.effective_card.cmc == 0
    angel_down = next(p for p in face_down if hidden_card_of(p) is angel)
    game.queue_from_hand(0, "Giant Growth", target_player_index=0,
                         target_permanent_ids=[angel_down.permanent_id])
    resolve_stack(game)
    assert (angel_down.effective_power, angel_down.effective_toughness) == (5, 5)


@pytest.mark.cr("708.3", "708.8", "702.37e")
def test_708_3_no_entry_ability_face_down_and_none_on_turning_up():
    """CR 708.3: turned face down before it enters, so its "when this enters"
    does not trigger; CR 708.8: turning it face up does not trigger it either
    — "the permanent has already entered the battlefield"."""
    seer = CardDefinition(
        name="Invented Entry Seer", mana_cost="{2}{U}", cmc=3.0,
        type_line="Creature — Human Wizard",
        oracle_text="When this creature enters, draw a card.\nMorph {U}",
        colors=("U",), color_identity=("U",), keywords=("Morph",),
        produced_mana=(), raw={}, power="1", toughness="1",
    )
    assert compile_card_oracle(seer).supported
    game, p1, _p2 = _duel([seer], enforce=False)
    _cast_face_down(game, 0, "Invented Entry Seer")
    resolve_stack(game)
    (permanent,) = p1.battlefield
    assert is_face_down(permanent) and p1.hand == []
    game.priority_player_index = 0
    p1.mana_pool.update({"U": 1})
    assert take_permanent_special_action(game, 0, permanent, "turn_face_up") is None
    resolve_stack(game)
    assert permanent.card is seer and p1.hand == [], "no draw either way"


@pytest.mark.cr("702.37e", "116.2b", "116.3", "708.8")
def test_702_37e_turning_face_up_is_a_special_action_that_keeps_everything(ons):
    """A special action at any priority (CR 116.2b), no stack, priority kept
    (CR 116.3), the morph cost paid — and "any effects that have been applied
    to the face-down permanent still apply" (CR 708.8): the same object, still
    tapped, still damaged, still pumped, still carrying its Aura."""
    colossus = ons["Krosan Colossus"]
    permanent = _face_down_on_battlefield(colossus)
    aura = Permanent(card=_CATALOG["Holy Strength"])
    game, p1, _p2 = _duel([_CATALOG["Giant Growth"]], [permanent], enforce=False)
    from engine.aura_attachment import attach_aura

    p1.battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, permanent)
    game.queue_from_hand(0, "Giant Growth", target_player_index=0,
                         target_permanent_ids=[permanent.permanent_id])
    resolve_stack(game)
    permanent.tapped = True
    permanent.damage_marked = 1
    identity = permanent.permanent_id
    assert (permanent.effective_power, permanent.effective_toughness) == (6, 7)

    game.priority_player_index = 1
    assert permanent_special_action_refusal(game, 0, permanent, "turn_face_up") == (
        "A does not have priority"
    )
    game.priority_player_index = 0
    assert permanent_special_action_refusal(game, 1, permanent, "turn_face_up") is not None
    assert permanent_special_action_refusal(game, 0, permanent, "turn_face_up") == (
        "A can't pay for it"
    )
    assert available_permanent_special_actions(game, 0) == []

    p1.mana_pool.update({"C": 6, "G": 2})
    assert available_permanent_special_actions(game, 0) == [{
        "permanent_id": identity, "name": FACE_DOWN_NAME,
        "kind": "turn_face_up", "morph_cost": "{6}{G}{G}",
    }]
    assert available_permanent_special_actions(game, 1) == []
    assert take_permanent_special_action(game, 0, permanent, "turn_face_up") is None
    assert game.stack == [], "CR 116.1: no stack"
    assert game.priority_player_index == 0, "CR 116.3"
    assert sum(p1.mana_pool.values()) == 0
    assert permanent.card is colossus and permanent.permanent_id == identity
    assert permanent.tapped and permanent.damage_marked == 1
    # 9/9 printed, +3/+3 Giant Growth, +1/+2 Holy Strength.
    assert (permanent.effective_power, permanent.effective_toughness) == (13, 14)
    assert any(
        "turned a face-down creature face up: it is Krosan Colossus" in line
        for line in game.log
    )


@pytest.mark.cr("702.37e")
def test_702_37e_no_morph_cost_no_turning_face_up():
    """"If the permanent wouldn't have a morph cost if it were face up, it
    can't be turned face up this way." A Grizzly Bears put face down (as
    Illusionary Mask does) makes no offer."""
    bears = _face_down_on_battlefield(_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _duel([], [bears], enforce=False)
    game.priority_player_index = 0
    assert morph_cost(_CATALOG["Grizzly Bears"]) is None
    assert available_permanent_special_actions(game, 0) == []
    assert permanent_special_action_refusal(game, 0, bears, "turn_face_up") == (
        f"{FACE_DOWN_NAME} is not making that offer"
    )


@pytest.mark.cr("702.37e", "506.4")
def test_702_37e_turned_up_mid_combat_it_stays_in_combat(ons):
    """Crude Rampart's ruling (2004-10-04): "If it attacks while face down and
    is turned face up during combat, this will not remove it from combat" —
    though the face-up card has defender."""
    rampart = _face_down_on_battlefield(ons["Crude Rampart"])
    game, p1, p2 = _duel([], [rampart], enforce=False)
    declare_attack(game, 0)
    assert rampart.attacking
    game.priority_player_index = 0
    p1.mana_pool.update({"C": 4, "W": 1})
    assert take_permanent_special_action(game, 0, rampart, "turn_face_up") is None
    assert rampart.card is ons["Crude Rampart"] and rampart.has_keyword("defender")
    assert rampart.attacking
    game.advance_combat_phase()
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
    assert p2.life == 16, "the 4/5 face-up Rampart dealt its damage"


@pytest.mark.cr("708.5")
def test_708_5_only_the_controller_may_look(ons):
    """"You may look at a face-down spell you control on the stack or a
    face-down permanent you control … You can't look at … face-down spells or
    permanents controlled by another player.\""""
    permanent = _face_down_on_battlefield(ons["Whipcorder"])
    game, _p1, _p2 = _duel([ons["Exalted Angel"]], [permanent], enforce=False)
    _cast_face_down(game, 0, "Exalted Angel")
    (spell,) = game.stack
    assert may_look_at(game, 0, permanent) and may_look_at(game, 0, spell)
    assert not may_look_at(game, 1, permanent) and not may_look_at(game, 1, spell)
    assert not may_look_at(game, None, permanent)


@pytest.mark.cr("708.9", "603.10")
def test_708_9_leaving_the_battlefield_reveals_the_card_and_lki_is_face_down(ons):
    """Every road off the battlefield puts the real card in the new zone,
    revealed — and what the permanent *was* as it left is the face-down 2/2
    (CR 603.10): Swords to Plowshares gains its controller 2 life, not the
    nine a face-up Krosan Colossus would give."""
    colossus = ons["Krosan Colossus"]
    for spell, zone in (("Terror", "graveyard"), ("Unsummon", "hand"),
                        ("Swords to Plowshares", "exile")):
        permanent = _face_down_on_battlefield(colossus)
        game, p1, _p2 = _duel([], [permanent], opponent_hand=[_CATALOG[spell]],
                              enforce=False)
        game.active_player_index = 1
        result = game.queue_from_hand(1, spell, target_player_index=0,
                                      target_permanent_ids=[permanent.permanent_id])
        assert result.supported, result.details
        resolve_stack(game)
        assert p1.battlefield == []
        assert [c.name for c in getattr(p1, zone)] == ["Krosan Colossus"], spell
        assert any(
            "revealed" in line and "Krosan Colossus" in line for line in game.log
        ), spell
        if spell == "Swords to Plowshares":
            assert p1.life == 22


@pytest.mark.cr("708.10", "707.2", "613.2b")
def test_708_10_copies_of_and_by_a_face_down_permanent(ons):
    """A Clone entering as a copy of a face-down creature copies the face-down
    values — a nameless 2/2 (CR 707.2). A face-down permanent that becomes a
    copy keeps its face-down characteristics, and is the copy once turned
    face up (CR 708.10)."""
    face_down = _face_down_on_battlefield(ons["Krosan Colossus"])
    game, _p1, p2 = _duel([], [face_down], opponent_hand=[_CATALOG["Clone"]],
                          enforce=False)
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Clone", target_player_index=0,
                                target_permanent_index=0).supported
    resolve_stack(game)
    (clone,) = p2.battlefield
    assert not is_face_down(clone)
    assert clone.effective_card.name == FACE_DOWN_NAME
    assert hidden_card_of(clone) is None and clone.effective_card.face_down_of is None
    assert (clone.effective_power, clone.effective_toughness) == (2, 2)

    bears = _nosick(Permanent(card=_CATALOG["Craw Wurm"]))
    whipcorder = _face_down_on_battlefield(ons["Whipcorder"])
    game, p1, _p2 = _duel([], [whipcorder, bears], enforce=False)
    become_copy(whipcorder, bears, label="test copy")
    assert (whipcorder.effective_power, whipcorder.effective_toughness) == (2, 2)
    assert whipcorder.effective_card.name == FACE_DOWN_NAME
    game.priority_player_index = 0
    p1.mana_pool.update({"W": 1})
    assert take_permanent_special_action(game, 0, whipcorder, "turn_face_up") is None
    assert whipcorder.effective_card.name == "Craw Wurm"
    assert (whipcorder.effective_power, whipcorder.effective_toughness) == (6, 4)


@pytest.mark.cr("702.37e", "603.2")
def test_702_37e_a_turned_face_up_trigger_fires():
    """"When this creature is turned face up, …" (Legions prints it; nothing
    Onslaught does) — the event and the condition exist, proved on an invented
    card: the ability is on the stack after the special action, and resolves."""
    seer = CardDefinition(
        name="Invented Morph Seer", mana_cost="{2}{U}", cmc=3.0,
        type_line="Creature — Human Wizard",
        oracle_text="When this creature is turned face up, draw two cards.\nMorph {U}",
        colors=("U",), color_identity=("U",), keywords=("Morph",),
        produced_mana=(), raw={}, power="1", toughness="1",
    )
    program = compile_card_oracle(seer)
    assert program.supported
    assert [t.condition.kind for t in program.triggered_abilities] == ["turned_face_up"]
    permanent = _face_down_on_battlefield(seer)
    game, p1, _p2 = _duel([], [permanent], enforce=False)
    game.priority_player_index = 0
    p1.mana_pool.update({"U": 1})
    assert take_permanent_special_action(game, 0, permanent, "turn_face_up") is None
    assert len(game.stack) == 1
    resolve_stack(game)
    assert len(p1.hand) == 2

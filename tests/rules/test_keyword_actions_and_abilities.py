"""CR 701.17 (Mill), CR 702.5 (Enchant) and CR 702.26 (Phasing).

The three rules that joined ``scripts/rules_progress.py``'s tracked scope when
M21's mechanics landed and nothing had cited them yet. Each is a keyword the
engine really implements rather than one it merely mentions:

* **Mill** — Carrion Grub, Teferi's Tutelage, Thieves' Guild Enforcer.
* **Enchant** — every Aura's attachment restriction, derived from the printed
  ``Enchant <subject>`` line rather than from a per-card registration.
* **Phasing** — Teferi, Master of Time's −3 and Teferi, Timeless Voyager's −8,
  and since Mirage the CR 702.26a **keyword** itself: the untap step's
  alternation, which is what a permanent printing the word does every turn.

Exert (CR 701.43) is deliberately absent: the engine cites it twice, but only
as the keyworded name for "doesn't untap during its controller's next untap
step", which is a different thing from implementing exert.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent

from ..helpers import _nosick


def _creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": str(power), "toughness": str(toughness)},
    )


# ---------------------------------------------------------------------------
# 701.17 — Mill
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.17", "701.17a")
def test_701_17a_milling_puts_cards_from_the_top_of_the_library_into_the_graveyard():
    """To mill N cards is to put the top N of that library into its graveyard.

    From the *top*, and into the graveyard rather than exile or hand — the two
    things that distinguish milling from every other library operation.
    """
    library = [_creature(f"Card {i}") for i in range(5)]
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", library=library[:])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    mill = CardDefinition(
        name="Mill Rite", mana_cost="", cmc=0.0, type_line="Sorcery",
        oracle_text="Target player mills two cards.", colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw={"name": "Mill Rite", "type_line": "Sorcery"},
    )
    p1.hand.append(mill)
    game.cast_from_hand(0, "Mill Rite", target_player_index=1)

    assert [card.name for card in p2.graveyard] == ["Card 0", "Card 1"]
    assert [card.name for card in p2.library] == ["Card 2", "Card 3", "Card 4"]


@pytest.mark.cr("701.17", "701.17a")
def test_701_17a_milling_more_than_the_library_holds_mills_what_is_there():
    """A library with fewer cards than the mill asks for is emptied, and the
    player does not lose for it — losing to an empty library is a state-based
    action about *drawing*, not about milling."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", library=[_creature("Only Card")])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    mill = CardDefinition(
        name="Deep Mill", mana_cost="", cmc=0.0, type_line="Sorcery",
        oracle_text="Target player mills three cards.", colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw={"name": "Deep Mill", "type_line": "Sorcery"},
    )
    p1.hand.append(mill)
    game.cast_from_hand(0, "Deep Mill", target_player_index=1)

    assert p2.library == []
    assert [card.name for card in p2.graveyard] == ["Only Card"]
    assert p2.lost is False


@pytest.mark.cr("701.17")
def test_701_17_a_printed_card_mills_through_the_same_instruction(set_pool):
    """The keyword action is one instruction kind for every card that prints
    it, so Teferi's Tutelage needs no registration of its own."""
    from engine.oracle import compile_card_oracle

    tutelage = set_pool("M21")["Teferi's Tutelage"]
    program = compile_card_oracle(tutelage)

    kinds = [
        instruction.kind
        for trigger in program.triggered_abilities
        if trigger.instruction is not None
        for instruction in (trigger.instruction.payload.get("steps")
                            or (trigger.instruction,))
    ]

    assert any("mill" in kind for kind in kinds), kinds


# ---------------------------------------------------------------------------
# 702.5 — Enchant
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.5", "702.5a")
def test_702_5a_enchant_restricts_what_an_aura_may_be_attached_to():
    """"Enchant [object]" is a static ability restricting the Aura's target.

    The subject is read off the printed line, so the restriction and the words
    that produced it cannot drift apart.
    """
    from engine.targeting import enchant_line_subject

    assert enchant_line_subject("Enchant creature") == "creature"
    assert enchant_line_subject("Enchant land") == "land"
    assert enchant_line_subject("Enchant artifact") == "artifact"


@pytest.mark.cr("702.5", "702.5a")
def test_702_5a_a_line_that_is_not_an_enchant_restriction_is_not_read_as_one():
    """The restriction is the whole line and nothing else — "Enchanted creature
    gets +1/+1" is an effect, not an attachment restriction, and reading it as
    one would let an Aura attach to anything."""
    from engine.targeting import enchant_line_subject

    assert enchant_line_subject("Enchanted creature gets +1/+1.") is None
    assert enchant_line_subject("Destroy target creature.") is None


@pytest.mark.cr("702.5")
def test_702_5_a_printed_aura_declares_its_restriction(set_pool):
    """A real Aura's enchant line is what the engine derives its legal targets
    from — Holy Strength enchants a creature, and says so in one line."""
    from engine.targeting import enchant_line_subject

    strength = set_pool("LEA")["Holy Strength"]
    subjects = [
        enchant_line_subject(line.strip())
        for line in strength.oracle_text.split("\n")
    ]

    assert "creature" in subjects


# ---------------------------------------------------------------------------
# 702.26 — Phasing
# ---------------------------------------------------------------------------

@pytest.mark.cr("702.26", "702.26a")
def test_702_26a_a_phased_out_permanent_is_treated_as_though_it_did_not_exist():
    """A phased-out permanent is treated as though it does not exist.

    It is off the battlefield for every rule that looks there — but it has not
    changed zones, which is what separates phasing from a bounce or an exile.
    """
    creature = Permanent(card=_creature("Phaser"))
    p1 = PlayerState(name="P1", battlefield=[creature])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.phase_out_permanent(creature)

    assert not game.is_on_battlefield(creature)
    assert creature not in p1.battlefield
    assert creature in p1.phased_out
    assert creature.card not in p1.graveyard
    assert creature.card not in p1.hand


@pytest.mark.cr("702.26")
def test_702_26_phasing_out_is_not_a_zone_change():
    """Phasing is explicitly not a zone change, so nothing that watches for one
    fires: the card reaches no graveyard, and the permanent keeps its identity
    rather than becoming a new object."""
    creature = Permanent(card=_creature("Phaser"))
    p1 = PlayerState(name="P1", battlefield=[creature])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    original_id = creature.permanent_id

    game.phase_out_permanent(creature)

    assert p1.graveyard == []
    assert creature.permanent_id == original_id


@pytest.mark.cr("702.26", "702.26d")
def test_702_26d_a_permanent_phases_in_at_its_controllers_untap_step(set_pool):
    """It phases in before untapping, during its controller's untap step.

    Driven through the real card so the return is the engine's own scheduling
    rather than a direct call: Teferi, Master of Time's −3 phases out a
    creature its controller does not control, and that creature comes back on
    its own controller's turn.
    """
    teferi = set_pool("M21")["Teferi, Master of Time"]
    walker = Permanent(card=teferi, metadata={"loyalty_counters": 3})
    victim = Permanent(card=_creature("Victim"))
    p1 = PlayerState(name="P1", battlefield=[walker], library=[_creature("L1")])
    p2 = PlayerState(name="P2", battlefield=[victim], library=[_creature("L2")])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    game.phase_out_permanent(victim)
    assert victim in p2.phased_out

    game.start_turn(1)

    assert victim not in p2.phased_out
    assert game.is_on_battlefield(victim)


def _phasing_creature(name: str = "Phaser", power: int = 2, toughness: int = 2):
    """A creature with phasing, carrying it the way a printed card does.

    Both channels — the ingested ``keywords`` field and the printed line —
    because a real card has both and layer 6 seeds itself from either.
    """
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text="Phasing", colors=(), color_identity=(),
        keywords=("Phasing",), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _phasing_game(*extra):
    phaser = Permanent(card=_phasing_creature())
    p1 = PlayerState(
        name="P1", battlefield=[phaser, *extra], library=[_creature("L1")] * 8
    )
    p2 = PlayerState(name="P2", library=[_creature("L2")] * 8)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, p1, phaser


@pytest.mark.cr("702.26a")
def test_702_26a_a_permanent_with_phasing_phases_out_at_its_own_untap_step():
    """"During each player's untap step, before the active player untaps
    permanents, all phased-in permanents with phasing that player controls
    phase out." """
    game, p1, phaser = _phasing_game()

    game.start_turn(0)

    assert not game.is_on_battlefield(phaser)
    assert phaser in p1.phased_out


@pytest.mark.cr("702.26a")
def test_702_26a_it_phases_back_in_at_the_next_one():
    """The other half of the same event, and the reason the two are one method:
    they are simultaneous, so what has just phased out must not be swept back
    in by the half that runs beside it."""
    game, p1, phaser = _phasing_game()

    game.start_turn(0)
    assert phaser in p1.phased_out
    game.start_turn(1)
    assert phaser in p1.phased_out, "an opponent's untap step is not this one"
    game.start_turn(0)

    assert game.is_on_battlefield(phaser)
    assert p1.phased_out == []


@pytest.mark.cr("702.26a")
def test_702_26a_the_alternation_repeats():
    """Out, in, out — the third untap step phases it back out, because by then
    it is a phased-in permanent with phasing again. A flag set once at the first
    phase-out would stop here."""
    game, _p1, phaser = _phasing_game()

    game.start_turn(0)
    game.start_turn(1)
    game.start_turn(0)
    game.start_turn(1)
    game.start_turn(0)

    assert not game.is_on_battlefield(phaser)


@pytest.mark.cr("702.26g")
def test_702_26g_an_attached_aura_phases_out_with_its_host():
    """"When a permanent phases out, any Auras … attached to that permanent
    phase out at the same time", and phase back in with it rather than on their
    own account."""
    from engine.auras import attach_aura

    aura_card = CardDefinition(
        name="Test Aura", mana_cost="", cmc=0.0,
        type_line="Enchantment — Aura", oracle_text="Enchant creature",
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw={},
    )
    aura = Permanent(card=aura_card)
    game, p1, phaser = _phasing_game(aura)
    attach_aura(aura, phaser)

    game.start_turn(0)
    assert aura in p1.phased_out and phaser in p1.phased_out

    game.start_turn(1)
    game.start_turn(0)
    assert game.is_on_battlefield(aura) and game.is_on_battlefield(phaser)


@pytest.mark.cr("702.26m", "702.26a")
def test_702_26m_a_skipped_untap_step_skips_the_phasing_event():
    """"If an effect causes a player to skip their untap step, the phasing
    event simply doesn't occur that turn."

    Driven through a real Stasis-shaped static rather than by calling the
    method, because what the rule governs is the *step*: the phasing event is
    inside it, so skipping the step has to skip the event without anyone
    writing that down twice.
    """
    stasis = CardDefinition(
        name="Test Stasis", mana_cost="", cmc=0.0, type_line="Enchantment",
        oracle_text="Players skip their untap steps.",
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw={},
    )
    game, _p1, phaser = _phasing_game(Permanent(card=stasis))

    game.start_turn(0)

    assert game.is_on_battlefield(phaser)


# ---------------------------------------------------------------------------
# 701.12 — Exchange
# ---------------------------------------------------------------------------
#
# Driven through Gauntlets of Chaos rather than by calling the handler, because
# what these rules govern is the *whole* resolution: whether the exchange is
# attempted at all, and what happens when one half of it cannot be completed.


def _exchange_board(set_pool):
    pool = set_pool("LEG")
    gauntlets = Permanent(card=pool["Gauntlets of Chaos"])
    mine = Permanent(card=pool["Black Mana Battery"])
    theirs = Permanent(card=pool["Red Mana Battery"])
    p1 = PlayerState(name="P1", battlefield=[gauntlets, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, mine, theirs


def _exchange(game, first, second):
    game.activate_permanent_ability(
        0, "Gauntlets of Chaos", permanent_index=0,
        target_player_index=0,
        target_permanent_ids=[first.permanent_id, second.permanent_id],
    )
    game._settle()


@pytest.mark.cr("701.12", "701.12b")
def test_701_12b_each_player_gains_control_of_the_others_permanent(set_pool):
    """"…each of those players simultaneously gains control of the permanent
    that was controlled by the other player." Both halves move, and neither
    permanent's base controller is rewritten (CR 613.1b), so the seat an ended
    effect would revert to is still the seat it entered under."""
    from engine.control import base_controller

    game, mine, theirs = _exchange_board(set_pool)

    _exchange(game, mine, theirs)

    assert game.controller_index_of(mine) == 1
    assert game.controller_index_of(theirs) == 0
    assert (base_controller(mine), base_controller(theirs)) == (0, 1)


@pytest.mark.cr("701.12", "701.12a")
def test_701_12a_an_exchange_that_cannot_be_completed_does_no_part_of_itself(set_pool):
    """"…if the entire exchange can't be completed, no part of the exchange
    occurs." The rule's own example: one of the two permanents is gone before
    the ability resolves, so the other must not change hands on its own."""
    game, mine, theirs = _exchange_board(set_pool)
    game.remove_from_battlefield(theirs)

    _exchange(game, mine, theirs)

    assert game.controller_index_of(mine) == 0


@pytest.mark.cr("701.12", "701.12b")
def test_701_12b_two_permanents_one_player_controls_exchange_to_nothing(set_pool):
    """"If, on the other hand, those permanents are controlled by the same
    player, the exchange effect does nothing."

    On this card the printed "target permanent an opponent controls" refuses
    first, and the rule's own guard sits behind it — both are asserted by the
    same observation, which is the point: nothing is *recorded* either. A
    layer-2 contribution restating what was already true would become visible
    the moment something else ended one of them."""
    from engine.control import has_control_change

    pool = set_pool("LEG")
    gauntlets = Permanent(card=pool["Gauntlets of Chaos"])
    one = Permanent(card=pool["Black Mana Battery"])
    two = Permanent(card=pool["Red Mana Battery"])
    p1 = PlayerState(name="P1", battlefield=[gauntlets, one, two])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    _exchange(game, one, two)

    assert game.controller_index_of(one) == 0
    assert game.controller_index_of(two) == 0
    assert not has_control_change(one) and not has_control_change(two)


# ---------------------------------------------------------------------------
# 701.2 Activate / 701.5 Cast / 701.6 Counter / 701.8 Destroy / 701.13 Exile /
# 701.18 Play / 701.24 Shuffle
#
# Each of these is a verb the engine performs from several places, so every
# test below drives a printed card rather than the handler: what the rule
# defines is what the *player* observes at the end of the action, not the shape
# of the call that produced it.
# ---------------------------------------------------------------------------


def _duel(p1: PlayerState, p2: PlayerState, *, enforce: bool = False) -> Game:
    return Game(players=[p1, p2], enforce_mana_costs=enforce)


# ---------------------------------------------------------------------------
# 701.2 — Activate
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.2", "701.2a")
def test_701_2a_activating_puts_the_ability_on_the_stack_and_pays_its_costs(set_pool):
    """"To activate an activated ability is to put it onto the stack and pay
    its costs, so that it will eventually resolve and have its effect."

    Three separate things, and the test separates them: after activation the
    ability is *on the stack*, both halves of Rod of Ruin's "{3}, {T}" are
    already spent, and the effect has not happened yet. A cost charged at
    resolution instead would be indistinguishable here except for this
    intermediate observation.
    """
    pool = set_pool("LEA")
    rod = Permanent(card=pool["Rod of Ruin"])
    p1 = PlayerState(name="P1", battlefield=[rod], mana_pool={"C": 3})
    p2 = PlayerState(name="P2", life=20)
    game = _duel(p1, p2, enforce=True)

    result = game.queue_permanent_ability(0, "Rod of Ruin", target_player_index=1)

    assert result.supported
    assert len(game.stack) == 1
    assert rod.tapped is True                     # {T} paid
    assert p1.mana_pool.get("C", 0) == 0          # {3} paid
    assert p2.life == 20                          # and the effect has not run

    game.resolve_top_of_stack()

    assert len(game.stack) == 0
    assert p2.life == 19


@pytest.mark.cr("701.2", "701.2a")
def test_701_2a_only_the_objects_controller_can_activate_its_ability(set_pool):
    """"Only an object's controller ... can activate its activated ability
    unless the object specifically says otherwise."

    The engine enforces this by *scope*: an activation names a permanent on the
    activating seat's own battlefield, so an opponent's Prodigal Sorcerer is not
    an object that seat can reach at all. Nothing is paid and nothing happens --
    and the very same call from the controller's seat works.
    """
    pool = set_pool("LEA")
    sorcerer = _nosick(Permanent(card=pool["Prodigal Sorcerer"]))
    p1 = PlayerState(name="P1", battlefield=[sorcerer], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = _duel(p1, p2)

    with pytest.raises(ValueError):
        game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)

    assert sorcerer.tapped is False
    assert p1.life == 20

    assert game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1
    ).supported
    assert (sorcerer.tapped, p2.life) == (True, 19)


# ---------------------------------------------------------------------------
# 701.5 — Cast
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.5", "701.5a")
def test_701_5a_casting_takes_the_card_from_its_zone_onto_the_stack_and_pays(set_pool):
    """"To cast a spell is to take it from the zone it's in (usually the hand),
    put it on the stack, and pay its costs, so that it will eventually resolve."

    The same three-part observation as activation, and the same reason for
    making it mid-flight: hand, stack and mana pool all have to have moved
    *before* the spell resolves, and only the paused state shows that.
    """
    pool = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[pool["Lightning Bolt"]], mana_pool={"R": 1})
    p2 = PlayerState(name="P2", life=20)
    game = _duel(p1, p2, enforce=True)

    result = game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)

    assert result.supported
    assert p1.hand == []                          # taken from the zone it was in
    assert len(game.stack) == 1                   # put on the stack
    assert p1.mana_pool.get("R", 0) == 0          # costs paid
    assert p2.life == 20                          # not yet resolved

    game.resolve_top_of_stack()

    assert p2.life == 17
    assert [c.name for c in p1.graveyard] == ["Lightning Bolt"]


@pytest.mark.cr("701.5", "701.5a", "701.13", "701.13a")
def test_701_5a_a_resolving_permanent_spell_is_the_only_entry_that_was_cast(set_pool):
    """Being cast is a property of *how* a permanent arrived, and Containment
    Priest is the card that asks: "If a nontoken creature would enter and it
    wasn't cast, exile it instead."

    A creature spell cast from hand resolves onto the battlefield untouched.
    The creature Transmogrify puts onto the battlefield out of a library was
    never cast, so the replacement fires and it is exiled (701.13a) instead of
    entering -- the same board, the same creature card, and only the manner of
    arrival different.
    """
    pool = set_pool("M21")
    lea = set_pool("LEA")

    priest = _nosick(Permanent(card=pool["Containment Priest"]))
    p1 = PlayerState(name="P1", battlefield=[priest], hand=[lea["Grizzly Bears"]])
    game = _duel(p1, PlayerState(name="P2"))

    assert game.cast_from_hand(0, "Grizzly Bears").supported
    assert [perm.card.name for perm in p1.battlefield] == [
        "Containment Priest", "Grizzly Bears",
    ]
    assert p1.exile == []

    priest = _nosick(Permanent(card=pool["Containment Priest"]))
    victim = _nosick(Permanent(card=lea["Grizzly Bears"]))
    p1 = PlayerState(name="P1", battlefield=[priest], hand=[pool["Transmogrify"]])
    p2 = PlayerState(
        name="P2", battlefield=[victim],
        library=[lea["Mountain"], lea["Hill Giant"], lea["Forest"]],
    )
    game = _duel(p1, p2)

    assert game.cast_from_hand(
        0, "Transmogrify", target_player_index=1, target_permanent_index=0
    ).supported

    # Hill Giant was *put* onto the battlefield, not cast, so it never entered.
    assert [perm.card.name for perm in p2.battlefield] == []
    assert sorted(c.name for c in p2.exile) == ["Grizzly Bears", "Hill Giant"]


# ---------------------------------------------------------------------------
# 701.6 — Counter
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.6", "701.6a", "701.6b")
def test_701_6a_a_countered_spell_leaves_the_stack_for_its_owners_graveyard(set_pool):
    """"To counter a spell ... means to cancel it, removing it from the stack.
    It doesn't resolve and none of its effects occur. A countered spell is put
    into its owner's graveyard." And 701.6b: no refund of what was paid.

    All four halves are separately observable here -- the stack empties, the
    Bolt is in its *owner's* graveyard rather than the counterer's, the 3 damage
    never happens, and the {R} that paid for it does not come back.
    """
    pool = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[pool["Lightning Bolt"]], mana_pool={"R": 3})
    p2 = PlayerState(name="P2", hand=[pool["Counterspell"]], mana_pool={"U": 2}, life=20)
    game = _duel(p1, p2, enforce=True)

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert p1.mana_pool.get("R", 0) == 2  # one red spent casting it

    countered = game.cast_from_hand(
        1, "Counterspell", target_stack_index=len(game.stack) - 1
    )

    assert countered.supported
    assert len(game.stack) == 0                                  # off the stack
    assert [c.name for c in p1.graveyard] == ["Lightning Bolt"]  # owner's graveyard
    assert p2.life == 20                                         # no effects occurred
    assert p1.mana_pool.get("R", 0) == 2                         # 701.6b: no refund


# ---------------------------------------------------------------------------
# 701.8 — Destroy
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.8", "701.8a", "108.3")
def test_701_8a_a_destroyed_permanent_goes_to_its_owners_graveyard(set_pool):
    """"To destroy a permanent, move it from the battlefield to its **owner's**
    graveyard."

    Owner, not controller -- a distinction with no visible consequence until the
    two differ. Rubinia Soulsinger takes control of an opponent's Grizzly Bears
    (a layer-2 contribution, which never rewrites ownership, CR 108.3); Wrath of
    God then destroys it, and the card goes back to the player who started the
    game with it.
    """
    leg = set_pool("LEG")
    lea = set_pool("LEA")
    rubinia = _nosick(Permanent(card=leg["Rubinia Soulsinger"]))
    bears = _nosick(Permanent(card=lea["Grizzly Bears"]))
    p1 = PlayerState(name="P1", battlefield=[rubinia], hand=[lea["Wrath of God"]])
    p2 = PlayerState(name="P2", battlefield=[bears])
    game = _duel(p1, p2)
    game.start_turn(0)

    assert game.activate_permanent_ability(
        0, "Rubinia Soulsinger", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    ).supported
    assert game.controller_index_of(bears) == 0  # P1 controls it now

    assert game.cast_from_hand(0, "Wrath of God").supported

    assert [c.name for c in p2.graveyard] == ["Grizzly Bears"]
    assert "Grizzly Bears" not in [c.name for c in p1.graveyard]


# ---------------------------------------------------------------------------
# 701.13 — Exile
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.13", "701.13a", "701.8b")
def test_701_13a_exiling_a_creature_moves_it_to_exile_not_to_the_graveyard(set_pool):
    """"To exile an object, move it to the exile zone from wherever it is."

    Swords to Plowshares is the check that exile is a *different destination*
    from the graveyard rather than a label on the same move -- the Bears reach
    neither battlefield nor graveyard -- and 701.8b's second sentence falls out
    of the same observation: a permanent put somewhere by a spell that never
    says "destroy" has not been destroyed.
    """
    pool = set_pool("LEA")
    bears = _nosick(Permanent(card=pool["Grizzly Bears"]))  # power 2
    p1 = PlayerState(name="P1", hand=[pool["Swords to Plowshares"]])
    p2 = PlayerState(name="P2", battlefield=[bears], life=20)
    game = _duel(p1, p2)

    assert game.cast_from_hand(
        0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0
    ).supported

    assert [perm.card.name for perm in p2.battlefield] == []
    assert [c.name for c in p2.graveyard] == []
    assert [c.name for c in p2.exile] == ["Grizzly Bears"]
    assert p2.life == 22  # "its controller gains life equal to its power"


@pytest.mark.cr("701.13", "701.13a", "701.21")
def test_701_13a_exile_takes_an_object_from_whatever_zone_it_is_in(set_pool):
    """"...from wherever it is" -- the graveyard is a zone exile reaches too.

    Tormod's Crypt exiles a graveyard while *sacrificing itself*, so one
    resolution shows both destinations at once: the cards leave the graveyard
    for exile, and the Crypt, which was sacrificed rather than exiled (701.21),
    goes to its owner's graveyard.
    """
    m21 = set_pool("M21")
    lea = set_pool("LEA")
    crypt = _nosick(Permanent(card=m21["Tormod's Crypt"]))
    p1 = PlayerState(name="P1", battlefield=[crypt])
    p2 = PlayerState(name="P2", graveyard=[lea["Grizzly Bears"], lea["Hill Giant"]])
    game = _duel(p1, p2)
    game.start_turn(0)

    assert game.activate_permanent_ability(
        0, "Tormod's Crypt", target_player_index=1
    ).supported

    assert p2.graveyard == []
    assert [c.name for c in p2.exile] == ["Grizzly Bears", "Hill Giant"]
    assert [c.name for c in p1.graveyard] == ["Tormod's Crypt"]
    assert p1.exile == []


# ---------------------------------------------------------------------------
# 701.18 — Play
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.18", "701.18a")
def test_701_18a_playing_a_land_does_not_use_the_stack(set_pool):
    """"Playing a land is a special action ... so it doesn't use the stack; it
    simply happens."

    The land goes from hand to battlefield in the one call, with nothing put on
    the stack in between -- which is what separates playing a land from casting
    the permanent spells that share this entry point in the engine.
    """
    pool = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[pool["Forest"]])
    game = _duel(p1, PlayerState(name="P2"), enforce=True)
    game.start_turn(0)

    assert game.cast_from_hand(0, "Forest").supported

    assert len(game.stack) == 0
    assert p1.hand == []
    assert [perm.card.name for perm in p1.battlefield] == ["Forest"]


@pytest.mark.cr("701.18", "701.18a", "305.2", "305.2b")
def test_701_18a_a_second_land_play_in_one_turn_is_refused_and_resets_next_turn(set_pool):
    """"A player may play a land if ... they haven't played a land this turn."

    The refusal and the reset are one rule seen twice: the second Mountain is
    turned away on the turn the Forest was played, and the very same call
    succeeds once a new turn has begun.
    """
    pool = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[pool["Forest"], pool["Mountain"]])
    game = _duel(p1, PlayerState(name="P2"), enforce=True)
    game.start_turn(0)

    assert game.cast_from_hand(0, "Forest").supported
    second = game.cast_from_hand(0, "Mountain")

    assert not second.supported
    assert [perm.card.name for perm in p1.battlefield] == ["Forest"]
    assert [c.name for c in p1.hand] == ["Mountain"]

    game.start_turn(0)

    assert game.cast_from_hand(0, "Mountain").supported
    assert [perm.card.name for perm in p1.battlefield] == ["Forest", "Mountain"]


# ---------------------------------------------------------------------------
# 701.24 — Shuffle
# ---------------------------------------------------------------------------

@pytest.mark.cr("701.24", "701.24a", "701.13a")
def test_701_24a_shuffling_a_graveyard_into_a_library_preserves_every_card(set_pool):
    """"To shuffle a library ... randomize the cards within it."

    Randomizing is not the testable half -- *conservation* is. Feldon's Cane
    shuffles a graveyard into a library, so every card that was in either zone
    is in the library afterwards and the graveyard is empty; nothing was lost to
    the randomization. The Cane exiles itself as part of its own cost (701.13a),
    so it is not among them.
    """
    atq = set_pool("ATQ")
    lea = set_pool("LEA")
    cane = _nosick(Permanent(card=atq["Feldon's Cane"]))
    p1 = PlayerState(
        name="P1", battlefield=[cane],
        graveyard=[lea["Grizzly Bears"], lea["Hill Giant"]],
        library=[lea["Forest"], lea["Mountain"]],
    )
    game = _duel(p1, PlayerState(name="P2"))
    game.start_turn(0)

    assert game.activate_permanent_ability(0, "Feldon's Cane").supported

    assert p1.graveyard == []
    assert sorted(c.name for c in p1.library) == [
        "Forest", "Grizzly Bears", "Hill Giant", "Mountain",
    ]
    assert [c.name for c in p1.exile] == ["Feldon's Cane"]
    assert p1.battlefield == []

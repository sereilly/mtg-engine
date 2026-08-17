"""Core Set 2021 (M21) creatures — the early rounds.

Split out of ``test_m21_creatures.py`` when that file reached the size guard in
``tests/engine/test_set_test_convention.py`` for the third time in four rounds.

**Why the axis is a round boundary and not a printed type.** The convention
(``tests/sets/README.md``) splits a set's tests by the printed type of the card
each test names, and for M21 that axis is spent: 149 of the set's cards are
creatures, ``Legendary Creature`` already has its own file, and an audit of every
remaining banner block found exactly one non-creature name left in it (a prop).
So the next division has to be something else, and the file was already written
as a sequence of round sections — each one self-contained, each one written up in
ROADMAP.md under the round it names. Cutting at a section boundary keeps every
section whole and keeps a test findable from the round that bought it, which is
what the guard is protecting.

These are the rounds that opened the set: keywords, the turn-history tracker,
non-mana activation costs, scry, the causative "you may have <subject> <verb>",
and trigger narrowing. Later rounds stay in ``test_m21_creatures.py``.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (SET_PLAYBOOK.md Phase 3), and the pool resolves through
``set_pool("M21")`` even though the set is not shipped — reading a card file is
not shipping it.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.grammar import compile_line
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- The keyword round: flash, menace, hexproof(+from), prowess, ------------
# --- deathtouch, indestructible ---------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Mistral Singer",       # Flying // Prowess
        "Masked Blackguard",    # Flash // pump ability
        "Bone Pit Brute",       # Menace // ETB pump
        "Ornery Dilophosaur",   # Deathtouch // conditional attack trigger
    ],
)
def test_keyword_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_bone_pit_brute_cannot_be_blocked_by_one_creature(set_pool):
    brute = Permanent(card=set_pool("M21")["Bone Pit Brute"])
    blocker = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[brute])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers

    ok, msg = game.declare_blockers(1, {0: 0})
    assert not ok
    assert "menace" in msg.lower()


def test_mistral_singer_pumps_on_a_noncreature_cast(set_pool):
    singer = Permanent(card=set_pool("M21")["Mistral Singer"])
    opt = set_pool("M21")["Opt"]
    p1 = PlayerState(
        name="P1", battlefield=[singer], hand=[opt],
        library=[set_pool("M21")["Island"], set_pool("M21")["Island"]],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Opt")

    assert singer.effective_power == 3  # 2/2 printed, +1/+1 from prowess
    assert singer.effective_toughness == 3


def test_masked_blackguard_casts_at_instant_speed(set_pool):
    assert set_pool("M21")["Masked Blackguard"].has_flash


def test_storm_caller_damages_each_opponent_on_entry(set_pool):
    caller = set_pool("M21")["Storm Caller"]
    p1 = PlayerState(name="P1", hand=[caller])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Storm Caller")

    assert p2.life == 18
    assert p1.life == 20


def test_basris_acolyte_counters_the_two_creatures_it_targeted(set_pool):
    """The card the round bought. Three creatures, two named: exactly those two
    get counters, and the Acolyte's own "other" keeps it off its own list."""
    acolyte = set_pool("M21")["Basri's Acolyte"]
    pegasus = set_pool("M21")["Concordia Pegasus"]
    mine = [Permanent(card=pegasus) for _ in range(3)]
    theirs = Permanent(card=pegasus)
    p1 = PlayerState(name="P1", hand=[acolyte], battlefield=list(mine))
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    base = pegasus and mine[0].effective_power

    game.cast_from_hand(
        0, "Basri's Acolyte", target_player_index=0, target_permanent_index=[0, 2]
    )

    assert [p.effective_power for p in mine] == [base + 1, base, base + 1]
    assert theirs.effective_power == base, "the opponent's creature was not touched"


def test_basris_acolyte_offers_only_its_controllers_creatures(set_pool):
    """The picker's half. "you control" is a seat test, so it narrows the
    enumeration rather than being left to the handler to decline silently after
    the player has already clicked."""
    acolyte = set_pool("M21")["Basri's Acolyte"]
    pegasus = set_pool("M21")["Concordia Pegasus"]
    p1 = PlayerState(name="P1", hand=[acolyte], battlefield=[Permanent(card=pegasus)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pegasus)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    spec = game.cast_target_spec(0, acolyte)

    assert spec["max_targets"] == 2
    assert spec["own_only"] is True
    assert {t["seat"] for t in spec["valid_targets"]} == {0}


def test_the_ai_names_as_many_targets_as_the_card_allows(set_pool):
    """Which cards this reaches is derived from the compiled program, never a
    list of names — so a card printed with the same template is covered the day
    it is ingested."""
    from engine.ai_policy import choose_cast_action

    acolyte = set_pool("M21")["Basri's Acolyte"]
    pegasus = set_pool("M21")["Concordia Pegasus"]
    p1 = PlayerState(
        name="P1", hand=[acolyte],
        battlefield=[Permanent(card=pegasus), Permanent(card=pegasus), Permanent(card=pegasus)],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Basri's Acolyte"
    assert action.target_permanent_index == [0, 1], "two of the three, the maximum"
    assert action.target_player_index == 0


# --- The tracker round: a turn's history, and CR 603.4 -----------------------


def test_indulging_patrician_compiles_supported(set_pool):
    assert compile_card_oracle(set_pool("M21")["Indulging Patrician"]).supported


# --- The cost round: non-mana activation costs ------------------------------


@pytest.mark.parametrize("name", ["Hobblefiend", "Seasoned Hallowblade"])
def test_cost_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_hobblefiend_sacrifices_the_named_creature_and_keeps_itself(set_pool):
    pool = set_pool("M21")
    fiend = Permanent(card=pool["Hobblefiend"])
    keep = Permanent(card=pool["Concordia Pegasus"])
    food = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(name="P1", battlefield=[fiend, keep, food])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    before = fiend.effective_power

    result = game.activate_permanent_ability(
        0, "Hobblefiend", permanent_index=0, cost_permanent_index=2,
    )

    assert result.supported, result.details
    # The *named* creature paid, not the first look-alike on the battlefield.
    assert not any(perm is food for perm in game.controlled_by(0))
    assert any(perm is keep for perm in game.controlled_by(0))
    assert any(perm is fiend for perm in game.controlled_by(0))
    assert fiend.effective_power == before + 1


def test_hobblefiend_alone_cannot_activate_and_does_not_eat_itself(set_pool):
    """CR 602.5c: an unpayable cost makes the ability unactivatable — not free,
    and not payable with the source the word "another" excludes."""
    fiend = Permanent(card=set_pool("M21")["Hobblefiend"])
    p1 = PlayerState(name="P1", battlefield=[fiend])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    before = fiend.effective_power

    result = game.activate_permanent_ability(0, "Hobblefiend", permanent_index=0)

    assert not result.supported
    assert "sacrifice" in result.details.lower()
    assert any(perm is fiend for perm in game.controlled_by(0))
    assert fiend.effective_power == before


def test_seasoned_hallowblade_discards_the_named_card_and_taps(set_pool):
    pool = set_pool("M21")
    blade = Permanent(card=pool["Seasoned Hallowblade"])
    keep, pitch = pool["Opt"], pool["Island"]
    p1 = PlayerState(name="P1", battlefield=[blade], hand=[keep, pitch])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Seasoned Hallowblade", permanent_index=0, cost_hand_index=1,
    )

    assert result.supported, result.details
    assert [c.name for c in p1.hand] == [keep.name]
    assert p1.graveyard[-1].name == pitch.name
    assert blade.tapped
    assert blade.has_keyword("indestructible")


def test_seasoned_hallowblade_refuses_a_pick_that_names_no_card(set_pool):
    """The activation twin of the cast side's repointing bug. An index that
    named no card became a bare ``0``, so a stale click discarded whatever was
    first in hand instead of saying it could not be honoured."""
    pool = set_pool("M21")
    blade = Permanent(card=pool["Seasoned Hallowblade"])
    keep = pool["Opt"]
    p1 = PlayerState(name="P1", battlefield=[blade], hand=[keep])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Seasoned Hallowblade", permanent_index=0, cost_hand_index=7,
    )

    assert not result.supported and "hand position 7" in result.details
    assert [c.name for c in p1.hand] == [keep.name]
    assert not blade.tapped and not p1.graveyard


def test_seasoned_hallowblades_cost_is_offered_as_a_hand_picker(set_pool):
    """The prompt the ability never had. Its spec is the *cost*'s, not the
    effect's — the effect targets nothing — and unlike the cast side nothing is
    withheld from the hand: the source is a permanent, so a second copy of the
    Hallowblade sitting in hand is an ordinary card to pitch."""
    pool = set_pool("M21")
    blade = Permanent(card=pool["Seasoned Hallowblade"])
    p1 = PlayerState(
        name="P1", battlefield=[blade],
        hand=[pool["Opt"], pool["Seasoned Hallowblade"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)

    spec = game.activation_target_spec(0, 0)

    assert spec["kind"] == "hand_card" and spec["discard_cost"] is True
    assert [(t["hand_index"], t["name"]) for t in spec["valid_targets"]] == [
        (0, "Opt"), (1, "Seasoned Hallowblade")
    ]


def test_seasoned_hallowblade_cannot_activate_with_an_empty_hand(set_pool):
    blade = Permanent(card=set_pool("M21")["Seasoned Hallowblade"])
    p1 = PlayerState(name="P1", battlefield=[blade])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Seasoned Hallowblade", permanent_index=0)

    assert not result.supported
    assert not blade.tapped


def test_portcullis_vine_charges_the_narrowed_sacrifice(set_pool):
    """"{2}, {T}, Sacrifice a creature with defender: Draw a card." — the cost
    the charger could not express until the noun phrase reached it whole.

    The Vine itself has defender, so it can eat itself; the Cat beside it
    cannot be chosen even though it is a creature. Naming the Cat is the case
    that matters: the charger re-checks the answer, and before the filter
    arrived there was nothing to re-check it against."""
    pool = set_pool("M21")
    vine = Permanent(card=pool["Portcullis Vine"])
    cat = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(name="P1", battlefield=[vine, cat], library=[pool["Alpine Watchdog"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _nosick(vine)

    result = game.activate_permanent_ability(
        0, "Portcullis Vine", permanent_index=0, cost_permanent_index=1
    )

    assert result.supported
    assert len(p1.hand) == 1
    assert game.is_on_battlefield(cat), "the Cat has no defender and cannot pay"
    assert not game.is_on_battlefield(vine)


def test_portcullis_vine_offers_only_what_its_cost_can_take(set_pool):
    """The picker's list and the charger's list are the same list.

    A cost payment is not a target (CR 601.2b), so the enumerator has its own
    path to what may pay — and a picker offering the Cat would have had its
    answer silently swapped for the deterministic pick at payment time. Both
    now read the printed noun phrase through one matcher."""
    pool = set_pool("M21")
    vine = Permanent(card=pool["Portcullis Vine"])
    cat = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(name="P1", battlefield=[vine, cat])
    game = Game(players=[p1, PlayerState(name="P2")])
    program = compile_card_oracle(vine.card)
    ability = program.activated_abilities[0]
    assert ability.cost.sacrifice_filter == {
        "type_filter": "creature", "with_keywords": ["defender"]
    }

    from engine.targeting import derive_activation_spec

    spec = derive_activation_spec(ability)
    assert spec["sacrifice_cost"] and spec["kind"] == "creature"
    offered = game._enumerate_targets(
        0, vine.card, spec, for_cast=False,
        ability_instruction=ability.instruction, source_permanent=vine,
    )
    assert [t.get("name") for t in offered] == ["Portcullis Vine"]


# --- The scry round (CR 701.22), and mill's recipient -----------------------


@pytest.mark.parametrize("name", ["Wall of Runes", "Spined Megalodon"])
def test_scry_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_carrion_grub_etb_mills_its_own_controller(set_pool):
    """"Mill four cards." — a bare imperative, so the miller is the effect's
    controller and travels on the same `recipient` key life loss uses, rather
    than as a target the handler would read off `context.target`.

    Asserted on the line rather than the card, which is how it was written when
    Carrion Grub's *other* line still refused — the card is supported now
    (round 64), and the line-level assertion is the one that says what this test
    is about.
    """
    grub = set_pool("M21")["Carrion Grub"]
    line = next(l for l in grub.oracle_text.split("\n") if "mill" in l)
    result = compile_line(line, card_name="Carrion Grub")

    assert result.lowered, result.failure_reason
    mill = result.instructions[0]
    assert mill.kind == "mill_target_player"
    assert mill.payload["recipient"] == "caster"
    assert mill.payload["amount"] == 4
    assert "targets" not in mill.payload  # a bare mill targets nobody


# --- The causative round: "you may have <subject> <verb> ..." ---------------


@pytest.mark.parametrize("name", ["Goblin Arsonist", "Battle-Rattle Shaman"])
def test_causative_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_goblin_arsonist_may_ping_when_it_dies(set_pool):
    """"You may have it deal 1 damage to any target" — the may wrapper arms
    the standard optional prompt, and accepting deals the damage."""
    arsonist = Permanent(card=set_pool("M21")["Goblin Arsonist"])
    p1 = PlayerState(name="P1", battlefield=[arsonist])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    p1.battlefield.remove(arsonist)
    game._permanent_to_graveyard(p1, arsonist)
    game.resolve_top_of_stack()

    assert any(e["card_name"] == "Goblin Arsonist" for e in game.pending_optional_pays)
    game.confirm_optional_pay(0, "Goblin Arsonist", accept=True)
    assert p2.life == 19


# --- The trigger-narrowing round: conditions carry their own restrictions ---


def test_quirion_dryad_counters_only_the_listed_colours(set_pool):
    """"Whenever you cast a spell that's white, blue, black, or red" — a green
    spell is not in the list, so it must not fire the trigger."""
    dryad = Permanent(card=set_pool("M21")["Quirion Dryad"])
    red = set_pool("M21")["Shock"]
    green = set_pool("M21")["Titanic Growth"]
    p1 = PlayerState(name="P1", battlefield=[dryad], hand=[red, green])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    base = dryad.effective_power

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game.resolve_top_of_stack()
    assert dryad.effective_power == base + 1

    game.cast_from_hand(0, "Titanic Growth", target_player_index=0, target_permanent_index=0)
    game.resolve_top_of_stack()
    assert dryad.effective_power == base + 1 + 4  # the +4/+4 pump lands, the counter does not


def test_adherent_of_hope_triggers_only_on_its_controllers_combat(set_pool):
    """The trigger *condition* is the controller's combat — a separate question
    from the intervening-if below, which decides whether the resolution does
    anything."""
    adherent = Permanent(card=set_pool("M21")["Adherent of Hope"])
    p1 = PlayerState(name="P1", battlefield=[adherent])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat, controller's turn
    assert game.stack, "the trigger fires on its controller's combat"
    game.resolve_top_of_stack()

    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()  # opponent's combat
    assert not game.stack, "and not on anyone else's"


def test_adherent_of_hope_does_nothing_without_its_basri_planeswalker(set_pool):
    """CR 603.4. The printed line is "…**if you control a Basri planeswalker**,
    put a +1/+1 counter on this creature", and the condition was lowered onto
    the payload and read by nothing — so the counter landed every combat. It is
    checked on resolution now, and with no Basri in play the ability does
    nothing at all."""
    adherent = Permanent(card=set_pool("M21")["Adherent of Hope"])
    p1 = PlayerState(name="P1", battlefield=[adherent])
    game = Game(players=[p1, PlayerState(name="P2")])
    base = adherent.effective_power

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.resolve_top_of_stack()

    assert adherent.effective_power == base


def test_valorous_steed_token_takes_its_cr_111_4_name(set_pool):
    program = compile_card_oracle(set_pool("M21")["Valorous Steed"])
    create = next(
        trig.instruction
        for trig in program.triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == "create_token"
    )
    assert create.payload["name"] == "Knight Token"
    assert create.payload["keywords"] == ("Vigilance",)


def test_roaming_ghostlight_cannot_bounce_a_spirit(set_pool):
    pool = set_pool("M21")
    spirit = Permanent(card=pool["Roaming Ghostlight"])   # a Spirit itself
    pegasus = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Roaming Ghostlight"]])
    p2 = PlayerState(name="P2", battlefield=[spirit, pegasus])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Roaming Ghostlight", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    # The chosen Spirit is not a legal object for the trigger, and "up to one"
    # may legally affect nothing — so nothing was bounced.
    assert game.is_on_battlefield(spirit)
    assert game.is_on_battlefield(pegasus)
    assert len(p2.hand) == 0


def test_roaming_ghostlight_bounces_a_non_spirit(set_pool):
    pool = set_pool("M21")
    pegasus = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Roaming Ghostlight"]])
    p2 = PlayerState(name="P2", battlefield=[pegasus])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Roaming Ghostlight", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(pegasus)
    assert [c.name for c in p2.hand] == ["Concordia Pegasus"]


def test_shipwreck_dowser_returns_an_instant_but_not_a_creature(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Shipwreck Dowser"]],
        graveyard=[pool["Concordia Pegasus"], pool["Shock"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(
        0, "Shipwreck Dowser", target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert any(c.name == "Shock" for c in p1.hand)
    assert any(c.name == "Concordia Pegasus" for c in p1.graveyard)


def test_jeskai_elder_draws_then_asks_for_the_discard(set_pool):
    pool = set_pool("M21")
    elder = Permanent(card=pool["Jeskai Elder"])
    p1 = PlayerState(
        name="P1", battlefield=[elder],
        hand=[pool["Island"]], library=[pool["Shock"]] * 2,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}
    program = compile_card_oracle(elder.card)
    trig = next(t for t in program.triggered_abilities if t.supported and t.instruction is not None)
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=elder, instruction=trig.instruction,
        effect_kind=trig.effect_kind,
    )
    game._settle()
    # The optional draw is a pending "may"; accept it.
    pending = game.pending_choices_of("optional_pay", 0)
    assert pending, "the 'you may draw' offer should be queued"
    assert game.confirm_optional_pay(0, accept=True)
    assert len(p1.hand) == 2, "drew the card"
    discard = game.pending_choices_of("discard", 0)
    assert discard and discard[0].data["count"] == 1
    assert game.confirm_discard(0, [0])
    assert len(p1.hand) == 1, "and discarded one of their choice"


# --- Round 23: the may-with-action-cost, and a counted gain ------------------


@pytest.mark.parametrize("name", ["Aven Gagglemaster", "Dire Fleet Warmonger"])
def test_round_23_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_aven_gagglemaster_counts_its_own_wings(set_pool):
    pool = set_pool("M21")
    flyers = [Permanent(card=pool["Concordia Pegasus"]) for _ in range(2)]
    grounded = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(
        name="P1", hand=[pool["Aven Gagglemaster"]],
        battlefield=[*flyers, grounded],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(0, "Aven Gagglemaster")
    assert result.supported, result.details
    # Two Pegasi plus the Gagglemaster itself fly; the cat does not.
    assert p1.life == 26


def test_dire_fleet_warmonger_eats_a_creature_for_the_turn(set_pool):
    pool = set_pool("M21")
    warmonger = Permanent(card=pool["Dire Fleet Warmonger"])
    snack = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(name="P1", battlefield=[warmonger, snack])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat fires the trigger
    game._settle()
    pending = game.pending_choices_of("optional_pay", 0)
    assert pending, "the 'you may sacrifice' offer should be queued"
    assert game.confirm_optional_pay(0, accept=True)
    # Accepting arms the sacrifice prompt; Warmonger itself is excluded
    # ("another"), so only the cat is a legal pick.
    sac = game.pending_sacrifice_state()
    assert sac is not None and sac["valid_indices"] == [1]
    assert game.confirm_sacrifice(0, [1])
    assert not game.is_on_battlefield(snack)
    assert warmonger.effective_power == 5  # 3/3 printed, +2/+2
    assert game._has_keyword(warmonger, "trample")
    # CR 514.2: the meal wears off.
    game.resolve_cleanup_step(0)
    assert warmonger.effective_power == 3
    assert not game._has_keyword(warmonger, "trample")


def test_dire_fleet_warmonger_with_nothing_to_eat_is_never_asked(set_pool):
    pool = set_pool("M21")
    warmonger = Permanent(card=pool["Dire Fleet Warmonger"])
    p1 = PlayerState(name="P1", battlefield=[warmonger])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game._settle()
    assert not game.pending_choices_of("optional_pay", 0), (
        "with no other creature the cost is unpayable, so the offer is never "
        "made and the pump cannot be taken for free"
    )
    assert warmonger.effective_power == 3


def test_falconer_adept_token_arrives_tapped_and_attacking(set_pool):
    pool = set_pool("M21")
    adept = Permanent(card=pool["Falconer Adept"])
    p1 = PlayerState(name="P1", battlefield=[adept])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    birds = [p for p in p1.battlefield if p.card.name == "Bird Token"]
    assert len(birds) == 1
    assert birds[0].tapped
    bird_index = p1.battlefield.index(birds[0])
    assert bird_index in game.combat_attackers, "the Bird joined the attack"


# --- Round 25: protection grows past colour ----------------------------------


def test_baneslayer_angel_compiles_and_shields_against_its_named_tribes(set_pool):
    pool = set_pool("M21")
    program = compile_card_oracle(pool["Baneslayer Angel"])
    assert program.supported, program.reason
    angel = Permanent(card=pool["Baneslayer Angel"])
    dragon = Permanent(card=pool["Gadrak, the Crown-Scourge"])  # a Dragon
    game = Game(players=[
        PlayerState(name="P1", battlefield=[angel]),
        PlayerState(name="P2", battlefield=[dragon]),
    ])
    assert game._is_protected_from(angel, dragon)
    assert not game._can_block_attacker(dragon, angel)
    # And the colour half of her line still reads: nothing here is a Demon or
    # Dragon spell, so an ordinary removal spell may still target her.
    assert game._can_be_targeted(angel, pool["Shock"])

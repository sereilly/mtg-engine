"""Core Set 2021 (M21) creature cards.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
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

    Asserted on the line rather than the card: Carrion Grub's *other* line
    ("gets +X/+0, where X is the greatest power among creature cards in your
    graveyard") still refuses, and a refused line stops the creature compiling
    at all — so the card stays unsupported while this line is done.
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
    assert not compile_card_oracle(grub).supported


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


def test_barrin_bounces_a_planeswalker_to_its_owners_hand(set_pool):
    """The union half: "up to one other target creature **or planeswalker**".
    And the CR 400.3 nuance the end-step test below leans on: the walker goes
    to its *owner's* hand, so bouncing the opponent's does not feed Barrin's
    own put-into-your-hand history."""
    pool = set_pool("M21")
    walker = Permanent(
        card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 4},
    )
    p1 = PlayerState(name="P1", hand=[pool["Barrin, Tolarian Archmage"]])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Barrin, Tolarian Archmage", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(walker)
    assert any(c.name == "Garruk, Unleashed" for c in p2.hand)
    assert game.permanents_to_hand_this_turn.get(0, 0) == 0
    assert game.permanents_to_hand_this_turn.get(1, 0) == 1


def test_barrin_draws_at_end_step_after_bouncing_his_controllers_own(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(
        name="P1", hand=[pool["Barrin, Tolarian Archmage"]],
        battlefield=[mine], library=[pool["Island"]] * 3,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(
        0, "Barrin, Tolarian Archmage", target_player_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert any(c.name == "Concordia Pegasus" for c in p1.hand)
    # The bounce landed in *your* hand, which is what the end-step
    # intervening-if reads (CR 603.4). The trigger goes on the stack and
    # resolves through the ordinary settle.
    hand_before = len(p1.hand)
    game.resolve_end_step(0)
    game._settle()
    assert len(p1.hand) == hand_before + 1


def test_barrin_end_step_trigger_stays_quiet_without_a_bounce(set_pool):
    pool = set_pool("M21")
    barrin = Permanent(card=pool["Barrin, Tolarian Archmage"])
    p1 = PlayerState(name="P1", battlefield=[barrin], library=[pool["Island"]] * 3)
    game = Game(players=[p1, PlayerState(name="P2")])
    hand_before = len(p1.hand)
    game.resolve_end_step(0)
    game._settle()
    assert not game.stack
    assert len(p1.hand) == hand_before, (
        "nothing was put into Barrin's controller's hand from the battlefield "
        "this turn, so CR 603.4 keeps the trigger off the stack"
    )


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


def test_epitaph_golem_bottoms_a_chosen_graveyard_card(set_pool):
    pool = set_pool("M21")
    golem = Permanent(card=pool["Epitaph Golem"])
    p1 = PlayerState(
        name="P1", battlefield=[golem],
        graveyard=[pool["Shock"], pool["Concordia Pegasus"]],
        library=[pool["Island"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.activate_permanent_ability(
        0, "Epitaph Golem", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert [c.name for c in p1.graveyard] == ["Shock"]
    assert [c.name for c in p1.library] == ["Island", "Concordia Pegasus"]


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


# --- Round 32: the opponent-scoped board, in both readings --------------------


def test_massacre_wurm_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Massacre Wurm"])
    assert program.supported, program.reason


def test_massacre_wurm_shrinks_only_the_other_side(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Alpine Watchdog"])        # 2/2, the caster's
    theirs = Permanent(card=pool["Alpine Watchdog"])      # 2/2, dies to -2/-2
    sturdy = Permanent(card=pool["Concordia Pegasus"])    # 1/3, survives at -1/1
    p1 = PlayerState(name="P1", hand=[pool["Massacre Wurm"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs, sturdy])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Massacre Wurm")
    assert result.supported, result.details
    game._settle()

    assert game.is_on_battlefield(mine), "the caster's own board is untouched"
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert not game.is_on_battlefield(theirs), "a 2/2 dies to -2/-2"
    assert (sturdy.effective_power, sturdy.effective_toughness) == (-1, 1)
    # And the death trigger it just caused drains that creature's controller.
    assert p2.life == 18
    assert p1.life == 20


def test_massacre_wurm_drains_the_dead_creatures_controller(set_pool):
    pool = set_pool("M21")
    wurm = Permanent(card=pool["Massacre Wurm"])
    mine = Permanent(card=pool["Alpine Watchdog"])
    theirs = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(name="P1", battlefield=[wurm, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    # The Wurm's controller losing a creature triggers nothing.
    game._permanent_to_graveyard(p1, mine)
    game.remove_from_battlefield(mine)
    game._settle()
    assert (p1.life, p2.life) == (20, 20)

    game._permanent_to_graveyard(p2, theirs)
    game.remove_from_battlefield(theirs)
    game._settle()
    assert p2.life == 18, "that player is the dead creature's controller"
    assert p1.life == 20


def test_waker_of_waves_static_line_reads_even_though_the_card_does_not(set_pool):
    """Its anthem line derives; the card stays unsupported on its other
    ability ("Discard this card:" — activating from hand, a mechanic the
    engine has no seam for), so it compiles to no instructions at all. The
    behaviour of the scope is pinned with an invented card in
    tests/rules/test_lord_buffs.py, where the table's properties live."""
    from engine.lord_buffs import lord_buff_for
    from engine.oracle import normalize_creature_line

    buff = lord_buff_for(
        normalize_creature_line("Creatures your opponents control get -1/-0.")
    )
    assert buff is not None and buff.filter.controller == "opponent"
    assert (buff.power, buff.toughness) == (-1, 0)
    assert not compile_card_oracle(set_pool("M21")["Waker of Waves"]).supported


# --- Round 31: a counter placement becomes an event ---------------------------


@pytest.mark.parametrize("name", ["Conclave Mentor", "Wildwood Scourge"])
def test_round_31_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_conclave_mentor_raises_a_counter_placed_by_another_card(set_pool):
    pool = set_pool("M21")
    mentor = Permanent(card=pool["Conclave Mentor"])
    veteran = Permanent(card=pool["Tempered Veteran"])
    cat = Permanent(card=pool["Pridemalkin"])  # 2/1 printed
    p1 = PlayerState(name="P1", battlefield=[mentor, veteran, cat])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)

    # Tempered Veteran's expensive ability places one counter; the Mentor
    # makes it two, without either card knowing about the other.
    result = game.activate_permanent_ability(
        0, "Tempered Veteran", ability_index=1,
        target_player_index=0, target_permanent_index=2,
    )
    assert result.supported, result.details
    assert cat.metadata["plus_counters"] == 2
    assert (cat.effective_power, cat.effective_toughness) == (4, 3)


def test_conclave_mentor_pays_out_its_power_as_it_dies(set_pool):
    pool = set_pool("M21")
    mentor = Permanent(card=pool["Conclave Mentor"])  # 2/2 printed
    p1 = PlayerState(name="P1", battlefield=[mentor])
    game = Game(players=[p1, PlayerState(name="P2")])

    # A counter of its own first: the life gained is the power it had when it
    # died, not the printed number.
    game.place_plus1_counters(mentor, 1)
    assert mentor.effective_power == 4, "its own replacement raised the placement"

    game._permanent_to_graveyard(p1, mentor)
    game.remove_from_battlefield(mentor)
    game._settle()
    assert p1.life == 24


def _living_scourge(game, player, card):
    """A Wildwood Scourge with entry counters on it.

    It is printed 0/0 — an X-cost Hydra — so one placed bare dies to CR 704.5f
    before anything can trigger. Its own placement feeds nothing ("another"),
    which is exactly what the next assertions rely on.
    """
    scourge = Permanent(card=card)
    player.battlefield.append(scourge)
    game.place_plus1_counters(scourge, 2)
    game._settle()
    return scourge


def test_wildwood_scourge_grows_with_its_flock(set_pool):
    pool = set_pool("M21")
    other = Permanent(card=pool["Concordia Pegasus"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[other])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    scourge = _living_scourge(game, p1, pool["Wildwood Scourge"])
    assert scourge.metadata["plus_counters"] == 2, "its own counters feed nothing"

    game.place_plus1_counters(other, 1)
    game._settle()
    assert scourge.metadata["plus_counters"] == 3, "a counted ally feeds the Hydra"

    game.place_plus1_counters(theirs, 1)
    game._settle()
    assert scourge.metadata["plus_counters"] == 3, "'you control' scopes it"


def test_wildwood_scourge_ignores_another_hydra(set_pool):
    """The excluded subtype is condition payload read off the printed line."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1")
    game = Game(players=[p1, PlayerState(name="P2")])
    scourge = _living_scourge(game, p1, pool["Wildwood Scourge"])
    hydra = _living_scourge(game, p1, pool["Wildwood Scourge"])

    before = scourge.metadata["plus_counters"]
    game.place_plus1_counters(hydra, 1)
    game._settle()
    assert scourge.metadata["plus_counters"] == before


# --- Round 30: counters as a filter, and as last-known information ------------


@pytest.mark.parametrize("name", ["Pridemalkin", "Basri's Lieutenant"])
def test_round_30_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_pridemalkin_tramples_only_the_counted(set_pool):
    pool = set_pool("M21")
    cat = Permanent(card=pool["Pridemalkin"])
    counted = Permanent(card=pool["Concordia Pegasus"])
    plain = Permanent(card=pool["Alpine Watchdog"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[cat, counted, plain])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    from engine.pt import add_plus1_counters, add_pt_modifier

    add_plus1_counters(counted)
    add_plus1_counters(theirs)
    # A pump is not a counter: the record is what the filter reads.
    add_pt_modifier(plain, 1, 1)
    game._recompute_continuous_effects()

    assert game._has_keyword(counted, "trample")
    assert not game._has_keyword(plain, "trample"), "a pump places no counter"
    assert not game._has_keyword(theirs, "trample"), "'you control' scopes it"
    assert not game._has_keyword(cat, "trample"), "the Cat has no counter itself"


def test_basris_lieutenant_knights_a_counted_death(set_pool):
    pool = set_pool("M21")
    lieutenant = Permanent(card=pool["Basri's Lieutenant"])
    counted = Permanent(card=pool["Concordia Pegasus"])
    plain = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(name="P1", battlefield=[lieutenant, counted, plain])
    game = Game(players=[p1, PlayerState(name="P2")])

    from engine.pt import add_plus1_counters

    add_plus1_counters(counted)

    # An uncounted death makes nothing.
    game._permanent_to_graveyard(p1, plain)
    game.remove_from_battlefield(plain)
    game._settle()
    assert not [p for p in p1.battlefield if p.card.name == "Knight Token"]

    # A counted one does — the counter is read as last-known information,
    # after the creature is already in the graveyard.
    game._permanent_to_graveyard(p1, counted)
    game.remove_from_battlefield(counted)
    game._settle()
    knights = [p for p in p1.battlefield if p.card.name == "Knight Token"]
    assert len(knights) == 1
    assert (knights[0].effective_power, knights[0].effective_toughness) == (2, 2)
    assert game._has_keyword(knights[0], "vigilance")


def test_basris_lieutenant_triggers_on_its_own_counted_death(set_pool):
    """"This creature or another creature you control" includes itself, so the
    self-exclusion every other dies-trigger applies must not reach it."""
    pool = set_pool("M21")
    lieutenant = Permanent(card=pool["Basri's Lieutenant"])
    p1 = PlayerState(name="P1", battlefield=[lieutenant])
    game = Game(players=[p1, PlayerState(name="P2")])

    from engine.pt import add_plus1_counters

    add_plus1_counters(lieutenant)
    game._permanent_to_graveyard(p1, lieutenant)
    game.remove_from_battlefield(lieutenant)
    game._settle()

    assert len([p for p in p1.battlefield if p.card.name == "Knight Token"]) == 1


def test_basris_lieutenant_ignores_an_opponents_counted_death(set_pool):
    pool = set_pool("M21")
    lieutenant = Permanent(card=pool["Basri's Lieutenant"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[lieutenant])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    from engine.pt import add_plus1_counters

    add_plus1_counters(theirs)
    game._permanent_to_graveyard(p2, theirs)
    game.remove_from_battlefield(theirs)
    game._settle()

    assert not [p for p in p1.battlefield if p.card.name == "Knight Token"]


# --- Round 29: the conditional-static family ----------------------------------


@pytest.mark.parametrize(
    "name",
    ["Predatory Wurm", "Gnarled Sage", "Sigiled Contender", "Tome Anima"],
)
def test_round_29_conditional_static_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_predatory_wurm_grows_under_its_own_garruk_only(set_pool):
    pool = set_pool("M21")
    wurm = Permanent(card=pool["Predatory Wurm"])  # 4/4 printed
    garruk = Permanent(card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[wurm])
    p2 = PlayerState(name="P2", battlefield=[garruk])
    game = Game(players=[p1, p2])

    game._recompute_continuous_effects()
    assert wurm.effective_power == 4, "an opponent's Garruk is not 'you control'"

    p1.battlefield.append(
        Permanent(card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 4})
    )
    game._recompute_continuous_effects()
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 6)


def test_gnarled_sage_stands_taller_after_the_second_draw(set_pool):
    pool = set_pool("M21")
    sage = Permanent(card=pool["Gnarled Sage"])  # 4/4 printed
    p1 = PlayerState(name="P1", battlefield=[sage], library=[pool["Island"]] * 3)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.begin_turn_bookkeeping(0)

    game._recompute_continuous_effects()
    assert sage.effective_toughness == 4
    assert not game._has_keyword(sage, "vigilance")

    game._draw_with_replacements(p1, 2)
    game._settle()
    assert sage.effective_toughness == 6
    assert game._has_keyword(sage, "vigilance")


def test_sigiled_contender_lifelinks_only_while_counted(set_pool):
    pool = set_pool("M21")
    contender = Permanent(card=pool["Sigiled Contender"])  # 3/3 printed
    game = Game(players=[
        PlayerState(name="P1", battlefield=[contender]), PlayerState(name="P2"),
    ])
    game._recompute_continuous_effects()
    assert not game._has_keyword(contender, "lifelink")

    from engine.pt import add_plus1_counters

    add_plus1_counters(contender)
    game._recompute_continuous_effects()
    assert game._has_keyword(contender, "lifelink")


def test_tome_anima_slips_past_blockers_after_two_draws(set_pool):
    pool = set_pool("M21")
    anima = Permanent(card=pool["Tome Anima"])
    blocker = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[anima], library=[pool["Island"]] * 3)
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    assert game._can_block_attacker(blocker, anima), "no draws yet: blockable"
    game._draw_with_replacements(p1, 2)
    game._settle()
    assert not game._can_block_attacker(blocker, anima)
    assert game.is_unblockable(anima), "the UI tag tracks the same condition"


# --- Round 28: cast-type narrowing, filtered intervening-if, second draw ------


@pytest.mark.parametrize(
    "name", ["Spellgorger Weird", "Turret Ogre", "Mystic Skyfish"],
)
def test_round_28_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_spellgorger_weird_counts_only_noncreature_spells(set_pool):
    pool = set_pool("M21")
    weird = Permanent(card=pool["Spellgorger Weird"])
    p1 = PlayerState(
        name="P1", battlefield=[weird],
        hand=[pool["Shock"], pool["Concordia Pegasus"]],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Shock", target_player_index=1)
    assert result.supported, result.details
    game._settle()
    assert weird.metadata.get("plus_counters", 0) == 1, "an instant counts"

    result = game.cast_from_hand(0, "Concordia Pegasus")
    assert result.supported, result.details
    game._settle()
    assert weird.metadata.get("plus_counters", 0) == 1, "a creature spell does not"


def test_turret_ogre_needs_another_big_creature(set_pool):
    pool = set_pool("M21")
    # Alone, his own power 4 does not satisfy "another creature" (CR 109.5).
    p1 = PlayerState(name="P1", hand=[pool["Turret Ogre"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Turret Ogre")
    assert result.supported, result.details
    game._settle()
    assert p2.life == 20, "no other big creature, no damage"

    # With a 6/6 already out, the trigger's condition holds.
    big = Permanent(card=pool["Elder Gargaroth"])
    q1 = PlayerState(name="Q1", hand=[pool["Turret Ogre"]], battlefield=[big])
    q2 = PlayerState(name="Q2")
    game2 = Game(players=[q1, q2])
    result = game2.cast_from_hand(0, "Turret Ogre")
    assert result.supported, result.details
    game2._settle()
    assert q2.life == 18


def test_turret_ogre_counts_a_pumped_small_creature(set_pool):
    """The bound reads the layer-computed power, not the printed one."""
    pool = set_pool("M21")
    small = Permanent(card=pool["Concordia Pegasus"])  # 1/3 printed
    from engine.pt import add_pt_modifier

    add_pt_modifier(small, 3, 0)  # 4/3 while modified
    p1 = PlayerState(name="P1", hand=[pool["Turret Ogre"]], battlefield=[small])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Turret Ogre")
    assert result.supported, result.details
    game._settle()
    assert p2.life == 18


def test_mystic_skyfish_lifts_off_on_the_second_draw(set_pool):
    pool = set_pool("M21")
    skyfish = Permanent(card=pool["Mystic Skyfish"])
    p1 = PlayerState(
        name="P1", battlefield=[skyfish], library=[pool["Island"]] * 4,
    )
    p2 = PlayerState(name="P2", library=[pool["Island"]] * 4)
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    game._draw_with_replacements(p1, 1)
    game._settle()
    assert not game._has_keyword(skyfish, "flying"), "one draw is not two"

    game._draw_with_replacements(p1, 1)
    game._settle()
    assert game._has_keyword(skyfish, "flying"), "the second draw lifts it"

    # Once per turn: a third draw does not queue a second trigger.
    fired = len(game.second_draw_fired_this_turn)
    game._draw_with_replacements(p1, 1)
    game._settle()
    assert len(game.second_draw_fired_this_turn) == fired

    # CR 514.2: the grant wears off at cleanup, and the next turn's second
    # draw fires afresh.
    game.resolve_cleanup_step(0)
    assert not game._has_keyword(skyfish, "flying")
    game.begin_turn_bookkeeping(1)
    game._draw_with_replacements(p2, 2)
    game._settle()
    assert not game._has_keyword(skyfish, "flying"), (
        "an opponent's second draw is not 'you draw'"
    )


# --- Round 27: modal triggered abilities --------------------------------------


@pytest.mark.parametrize("name", ["Trufflesnout", "Elder Gargaroth"])
def test_round_27_modal_trigger_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason
    trig = next(t for t in program.triggered_abilities if t.supported)
    assert trig.instruction is not None and trig.instruction.kind == "choose_one"
    assert program.modes == (), "a trigger's modes are not cast-time modes"


def test_trufflesnout_default_takes_the_first_printed_mode(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Trufflesnout"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(0, "Trufflesnout")
    assert result.supported, result.details
    game._settle()

    snout = next(p for p in p1.battlefield if p.card.name == "Trufflesnout")
    assert snout.metadata.get("plus_counters", 0) == 1, "mode 0: the counter"
    assert (snout.effective_power, snout.effective_toughness) == (3, 3)
    assert p1.life == 20, "the life mode was not also taken"


def test_trufflesnout_interactive_controller_may_take_the_life_instead(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Trufflesnout"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}

    result = game.cast_from_hand(0, "Trufflesnout")
    assert result.supported, result.details
    game._settle()

    pending = game.pending_choices_of("mode_choice", 0)
    assert pending and pending[0].data["labels"] == [
        "Put a +1/+1 counter on this creature", "You gain 4 life",
    ]
    assert not game.resolve_pending_choice("mode_choice", 0, mode_index=5), (
        "an index outside the printed list is refused and the prompt stays owed"
    )
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    assert p1.life == 24
    snout = next(p for p in p1.battlefield if p.card.name == "Trufflesnout")
    assert snout.metadata.get("plus_counters", 0) == 0, "the counter mode was declined"


def test_elder_gargaroth_triggers_on_attack_and_on_block(set_pool):
    pool = set_pool("M21")
    gargaroth = Permanent(card=pool["Elder Gargaroth"])
    p1 = PlayerState(name="P1", battlefield=[gargaroth])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    beasts = [p for p in p1.battlefield if p.card.name == "Beast Token"]
    assert len(beasts) == 1, "attack half: default mode made the Beast"

    # The block half, from the defender's side of a fresh game.
    attacker = Permanent(card=pool["Pridemalkin"])
    blocker = Permanent(card=pool["Elder Gargaroth"])
    ap = PlayerState(name="AP", battlefield=[attacker])
    dp = PlayerState(name="DP", battlefield=[blocker])
    game2 = Game(players=[ap, dp])
    game2.start_turn(0)
    game2._close_current_priority_step()
    game2.advance_combat_phase()  # beginning_of_combat
    game2.advance_combat_phase()  # declare_attackers
    ok, msg = game2.declare_attackers(0, [0])
    assert ok, msg
    game2.advance_combat_phase()  # declare_blockers
    ok, msg = game2.declare_blockers(1, {0: 0})
    assert ok, msg
    game2._settle()
    beasts = [p for p in dp.battlefield if p.card.name == "Beast Token"]
    assert len(beasts) == 1, "block half: the union condition fires here too"


def test_lilianas_steward_feeds_herself_to_empty_an_opposing_hand(set_pool):
    pool = set_pool("M21")
    steward = Permanent(card=pool["Liliana's Steward"])
    p1 = PlayerState(name="P1", battlefield=[steward])
    p2 = PlayerState(name="P2", hand=[pool["Shock"], pool["Island"]])
    game = Game(players=[p1, p2])
    game.start_turn(0)  # "Activate only as a sorcery" needs the main phase

    result = game.activate_permanent_ability(
        0, "Liliana's Steward", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(steward), "the sacrifice was a cost"
    game.auto_resolve_pending_choices()
    assert len(p2.hand) == 1, "the targeted opponent discarded one card"


def test_lilianas_steward_cannot_point_at_her_own_controller(set_pool):
    pool = set_pool("M21")
    program = compile_card_oracle(pool["Liliana's Steward"])
    from engine.targeting import derive_activation_spec

    ability = next(a for a in program.activated_abilities if a.supported)
    spec = derive_activation_spec(ability)
    assert spec == {"kind": "player", "opponents_only": True}


def test_chandras_magmutt_pings_a_face_or_a_walker(set_pool):
    pool = set_pool("M21")
    magmutt = Permanent(card=pool["Chandra's Magmutt"])
    assert compile_card_oracle(magmutt.card).supported
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    p1 = PlayerState(name="P1", battlefield=[magmutt])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Chandra's Magmutt", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    assert p2.life == 19, "the player face is a legal target"

    magmutt.tapped = False
    result = game.activate_permanent_ability(
        0, "Chandra's Magmutt", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert walker.metadata["loyalty_counters"] == 2, "damage strips loyalty (CR 306.8)"
    assert p2.life == 19, "the walker soaked it, not the player"


def test_chandras_magmutt_never_offers_a_creature(set_pool):
    pool = set_pool("M21")
    magmutt = Permanent(card=pool["Chandra's Magmutt"])
    bear = Permanent(card=pool["Pridemalkin"])
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    game = Game(players=[
        PlayerState(name="P1", battlefield=[magmutt]),
        PlayerState(name="P2", battlefield=[bear, walker]),
    ])
    program = compile_card_oracle(magmutt.card)
    from engine.targeting import derive_activation_spec

    ability = next(a for a in program.activated_abilities if a.supported)
    spec = derive_activation_spec(ability)
    assert spec == {"kind": "player_or_planeswalker"}
    offered = game._enumerate_targets(
        0, magmutt.card, spec, for_cast=False,
        ability_instruction=ability.instruction, source_permanent=magmutt,
    )
    names = {t.get("name") for t in offered if t["kind"] == "permanent"}
    assert names == {"Basri Ket"}, "planeswalkers yes, creatures no"
    assert {t["seat"] for t in offered if t["kind"] == "player"} == {0, 1}


def test_tempered_veteran_tends_only_an_already_counted_creature(set_pool):
    pool = set_pool("M21")
    veteran = Permanent(card=pool["Tempered Veteran"])
    cat = Permanent(card=pool["Pridemalkin"])  # 2/1, no counter yet
    p1 = PlayerState(name="P1", battlefield=[veteran, cat])
    game = Game(players=[p1, PlayerState(name="P2")])
    program = compile_card_oracle(veteran.card)
    assert program.supported, program.reason

    from engine.targeting import derive_activation_spec

    cheap = program.activated_abilities[0]  # {W}, {T}: counter on a counted creature
    offered = game._enumerate_targets(
        0, veteran.card, derive_activation_spec(cheap), for_cast=False,
        ability_instruction=cheap.instruction, source_permanent=veteran,
    )
    assert offered == [], "with no counter anywhere, the cheap ability has no target"

    # The expensive ability seeds the counter; the cheap one can then grow it.
    result = game.activate_permanent_ability(
        0, "Tempered Veteran", ability_index=1,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert cat.metadata["plus_counters"] == 1, "the counter is recorded, not just P/T"
    assert (cat.effective_power, cat.effective_toughness) == (3, 2)

    veteran.tapped = False
    offered = game._enumerate_targets(
        0, veteran.card, derive_activation_spec(cheap), for_cast=False,
        ability_instruction=cheap.instruction, source_permanent=veteran,
    )
    assert [t.get("name") for t in offered] == ["Pridemalkin"]
    result = game.activate_permanent_ability(
        0, "Tempered Veteran", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert cat.metadata["plus_counters"] == 2
    assert (cat.effective_power, cat.effective_toughness) == (4, 3)


def test_azusa_grants_two_additional_land_plays(set_pool):
    pool = set_pool("M21")
    azusa = Permanent(card=pool["Azusa, Lost but Seeking"])
    assert compile_card_oracle(azusa.card).supported
    p1 = PlayerState(name="P1", battlefield=[azusa], hand=[pool["Forest"]] * 4)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True  # CR 305.2's count is enforced in this mode

    plays = [game.cast_from_hand(0, "Forest").supported for _ in range(4)]
    assert plays == [True, True, True, False], "one land plus Azusa's two"


def test_kaervek_shrinks_every_other_creature_and_not_himself(set_pool):
    pool = set_pool("M21")
    kaervek = Permanent(card=pool["Kaervek, the Spiteful"])
    own_bird = Permanent(card=pool["Concordia Pegasus"])    # 1/3, his own side
    frail = Permanent(card=pool["Speaker of the Heavens"])  # 1/1, opposing
    p1 = PlayerState(name="P1", battlefield=[kaervek, own_bird])
    p2 = PlayerState(name="P2", battlefield=[frail])
    game = Game(players=[p1, p2])

    program = compile_card_oracle(kaervek.card)
    assert program.supported, program.reason
    game._recalculate_lord_buffs()

    assert kaervek.effective_power == 3, "'Other creatures' excludes the source"
    assert own_bird.effective_power == 0, "his own side shrinks too"
    assert frail.effective_toughness == 0
    game.check_state_based_actions()
    assert not game.is_on_battlefield(frail), "a 1/1 dies under him (CR 704.5f)"
    assert game.is_on_battlefield(own_bird)


def test_vito_drains_for_exactly_the_life_that_arrived(set_pool):
    """The trigger's number is the event's, not a printed amount: Revitalize
    gains 3, so the opponent loses 3."""
    pool = set_pool("M21")
    vito = Permanent(card=pool["Vito, Thorn of the Dusk Rose"])
    p1 = PlayerState(
        name="P1", battlefield=[vito], hand=[pool["Revitalize"]],
        library=[pool["Swamp"]] * 3,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Revitalize")
    assert result.supported, result.details
    game._settle()

    assert p1.life == 23
    assert p2.life == 17, "target opponent loses that much life"


def test_vito_stays_silent_when_the_opponent_gains_the_life(set_pool):
    """"Whenever **you** gain life" is the ability's controller (CR 109.5). The
    event is announced game-wide and the narrowing is the trigger's own word,
    so this is what the event filter is for."""
    pool = set_pool("M21")
    vito = Permanent(card=pool["Vito, Thorn of the Dusk Rose"])
    p1 = PlayerState(name="P1", battlefield=[vito])
    p2 = PlayerState(
        name="P2", hand=[pool["Revitalize"]], library=[pool["Swamp"]] * 3
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Revitalize")
    assert result.supported, result.details
    game._settle()

    assert p2.life == 23
    assert p1.life == 20, "Vito's controller gained nothing, so nothing drained"


def test_vito_reads_the_life_a_replacement_left_and_not_the_life_intended(set_pool):
    """CR 614: a replaced life gain never happened. Lich replaces the whole
    gain with draws, so the event is not announced at all — which is why the
    emit is after the replacements rather than beside the intent."""
    from tests.helpers import CARDS_BY_NAME

    pool = set_pool("M21")
    vito = Permanent(card=pool["Vito, Thorn of the Dusk Rose"])
    lich = Permanent(card=CARDS_BY_NAME["Lich"])
    p1 = PlayerState(
        name="P1", battlefield=[vito, lich], library=[pool["Swamp"]] * 5
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    before = p1.life

    game._gain_life(p1, 3, "a test")
    game._settle()

    assert len(p1.hand) == 3, "Lich drew that many cards instead"
    assert p1.life == before, "the gain was replaced, so no life arrived"
    assert p2.life == 20, "no life was gained, so nothing triggered"


def test_vito_drains_off_his_own_lifelink_grant(set_pool):
    """His two lines meet: the {3}{B}{B} grant makes the team lifelink, combat
    damage gains life through the one seam, and the seam announces it."""
    pool = set_pool("M21")
    vito = Permanent(card=pool["Vito, Thorn of the Dusk Rose"])
    beater = _nosick(Permanent(card=pool["Alpine Watchdog"]))  # 2/2 vigilance
    p1 = PlayerState(name="P1", battlefield=[vito, beater])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(0, "Vito, Thorn of the Dusk Rose")
    assert result.supported, result.details
    game._settle()
    assert game._has_keyword(beater, "lifelink")

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [1])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert p1.life == 22, "lifelink gained 2"
    assert p2.life == 16, "2 combat damage, then Vito's 2"


# --- The subject-filtered trigger: "a creature you control with deathtouch" --


@pytest.mark.parametrize(
    "name", ["Hooded Blightfang", "Snarespinner", "Gloom Sower"],
)
def test_round_34_subject_filter_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def _attack(game, seat, attacker_indices, blocks=None):
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(seat, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    if blocks is not None:
        ok, msg = game.declare_blockers(1 - seat, blocks)
        assert ok, msg
    game._settle()


def test_hooded_blightfang_drains_once_for_each_deathtouch_attacker(set_pool):
    """Its own deathtouch counts it among the creatures it watches; the
    Watchdog attacking beside it does not."""
    pool = set_pool("M21")
    fang = _nosick(Permanent(card=pool["Hooded Blightfang"]))
    plain = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    p1 = PlayerState(name="P1", battlefield=[fang, plain])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _attack(game, 0, [0, 1])

    assert (p1.life, p2.life) == (21, 19), "one drain, not two and not none"


def test_hooded_blightfang_ignores_an_opponents_deathtouch_attacker(set_pool):
    """"A creature **you control**" is the ability's controller (CR 109.5), and
    the scope lives in the trigger's own noun phrase rather than in the event."""
    pool = set_pool("M21")
    fang = Permanent(card=pool["Hooded Blightfang"])
    theirs = _nosick(Permanent(card=pool["Ornery Dilophosaur"]))  # deathtouch
    p1 = PlayerState(name="P1", battlefield=[fang])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    _attack(game, 1, [0])

    assert (p1.life, p2.life) == (20, 20)


def test_hooded_blightfang_destroys_a_walker_its_deathtouch_creature_damaged(set_pool):
    """Any damage, not only combat damage — the emit sits on the one path every
    damage-to-a-permanent caller runs through, like lifelink and deathtouch."""
    pool = set_pool("M21")
    fang = _nosick(Permanent(card=pool["Hooded Blightfang"]))
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[fang])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])

    game._mark_damage_on_permanent(walker, 1, source=fang)
    game._settle()

    assert not game.is_on_battlefield(walker), "1 damage, then destroyed"


def test_hooded_blightfang_leaves_a_walker_alone_without_deathtouch(set_pool):
    pool = set_pool("M21")
    fang = Permanent(card=pool["Hooded Blightfang"])
    plain = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[fang, plain])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])

    game._mark_damage_on_permanent(walker, 1, source=plain)
    game._settle()

    assert game.is_on_battlefield(walker)
    assert walker.metadata["loyalty_counters"] == 3, "damage still removed loyalty"


def test_snarespinner_grows_only_against_a_flier(set_pool):
    """The rider used to be dropped: the condition matched "whenever this
    creature blocks" and "a creature with flying" went unread, so the Spider
    would have pumped against anything it blocked."""
    pool = set_pool("M21")
    base = Permanent(card=pool["Snarespinner"]).effective_power

    spider = Permanent(card=pool["Snarespinner"])
    ground = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    attackers = PlayerState(name="AP", battlefield=[ground])
    game = Game(players=[attackers, PlayerState(name="DP", battlefield=[spider])])
    _attack(game, 0, [0], blocks={0: 0})
    assert spider.effective_power == base, "a ground attacker gives it nothing"

    spider2 = Permanent(card=pool["Snarespinner"])
    flier = _nosick(Permanent(card=pool["Concordia Pegasus"]))
    game2 = Game(players=[
        PlayerState(name="AP", battlefield=[flier]),
        PlayerState(name="DP", battlefield=[spider2]),
    ])
    _attack(game2, 0, [0], blocks={0: 0})
    assert spider2.effective_power == base + 2


def test_gloom_sower_drains_once_per_blocker(set_pool):
    """CR 509.3d: "becomes blocked **by a creature**" triggers once for each
    creature that blocks it, where the bare wording would fire once."""
    pool = set_pool("M21")
    sower = _nosick(Permanent(card=pool["Gloom Sower"]))
    first = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    second = _nosick(Permanent(card=pool["Concordia Pegasus"]))
    p1 = PlayerState(name="P1", battlefield=[sower])
    p2 = PlayerState(name="P2", battlefield=[first, second])
    game = Game(players=[p1, p2])

    _attack(game, 0, [0], blocks={0: 0, 1: 0})

    assert (p1.life, p2.life) == (24, 16), "two blockers, 2 life each way apiece"


def test_garruks_uprising_third_line_is_no_longer_dropped(set_pool):
    """It reported *supported* with this line compiling to nothing — the
    partial-implementation class, on a card whose other two lines work. The
    power bound is what decides, and it reads the layer-computed power."""
    pool = set_pool("M21")
    uprising = Permanent(card=pool["Garruk's Uprising"])
    p1 = PlayerState(
        name="P1", battlefield=[uprising],
        hand=[pool["Alpine Watchdog"], pool["Elder Gargaroth"]],
        library=[pool["Forest"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    program = compile_card_oracle(uprising.card)
    assert any(
        t.condition.kind == "matching_permanent_enters" and t.supported
        for t in program.triggered_abilities
    ), "the line compiles to a real trigger"

    game.cast_from_hand(0, "Alpine Watchdog")   # 2/2 — below the bound
    game._settle()
    assert len(p1.hand) == 1, "no draw for a small creature"

    game.cast_from_hand(0, "Elder Gargaroth")   # 6/6
    game._settle()
    assert len(p1.hand) == 1, "cast one, drew one"


# --- Costs go down as well as up (CR 601.2f / 118.7) ------------------------


@pytest.mark.parametrize(
    "name", ["Vryn Wingmare", "Watcher of the Spheres", "Stormwing Entity"],
)
def test_round_35_cost_modifier_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def _casting_game(set_pool, battlefield, hand, **mana):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=pool[n]) for n in battlefield],
        hand=[pool[n] for n in hand],
        library=[pool["Island"]] * 6,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    p1.mana_pool = {sym: mana.get(sym, 0) for sym in ("W", "U", "B", "R", "G", "C")}
    return game, p1


def test_watcher_of_the_spheres_discounts_only_flying_creature_spells(set_pool):
    """"Creature spells with flying **you cast**": three narrowings, and each
    one has to hold or the discount is a different card's."""
    # Concordia Pegasus is {1}{W} with flying — one white mana is enough.
    game, _ = _casting_game(set_pool, ["Watcher of the Spheres"], ["Concordia Pegasus"], W=1)
    assert game.queue_from_hand(0, "Concordia Pegasus").supported

    # Without the Watcher, the same mana is not.
    bare, _ = _casting_game(set_pool, [], ["Concordia Pegasus"], W=1)
    assert not bare.queue_from_hand(0, "Concordia Pegasus").supported

    # Alpine Watchdog is {1}{W} without flying, so the keyword narrowing bites.
    grounded, _ = _casting_game(set_pool, ["Watcher of the Spheres"], ["Alpine Watchdog"], W=1)
    assert not grounded.queue_from_hand(0, "Alpine Watchdog").supported


def test_watcher_of_the_spheres_does_not_discount_an_opponents_spell(set_pool):
    """"You cast" is the Watcher's controller (CR 109.5) — the discount does not
    cross the table, which is the one narrowing a board-wide scan would lose."""
    pool = set_pool("M21")
    watcher = Permanent(card=pool["Watcher of the Spheres"])
    p1 = PlayerState(name="P1", battlefield=[watcher])
    p2 = PlayerState(
        name="P2", hand=[pool["Concordia Pegasus"]], library=[pool["Island"]] * 4
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    p2.mana_pool = {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    assert not game.queue_from_hand(1, "Concordia Pegasus").supported


def test_vryn_wingmare_taxes_noncreature_spells_only(set_pool):
    """"Non" is the printed negation of the same word: Shock pays {1} more and
    a creature spell pays nothing more."""
    game, _ = _casting_game(set_pool, ["Vryn Wingmare"], ["Shock"], R=1)
    assert not game.queue_from_hand(0, "Shock", target_player_index=1).supported

    paid, _ = _casting_game(set_pool, ["Vryn Wingmare"], ["Shock"], R=1, C=1)
    assert paid.queue_from_hand(0, "Shock", target_player_index=1).supported

    creature, _ = _casting_game(set_pool, ["Vryn Wingmare"], ["Alpine Watchdog"], W=1, C=1)
    assert creature.queue_from_hand(0, "Alpine Watchdog").supported


def test_stormwing_entity_discounts_itself_after_an_instant(set_pool):
    """{3}{U}{U} less {2}{U} is {1}{U} — the coloured half of the reduction
    takes a blue pip and the generic half takes two generic (CR 118.7a/c)."""
    # {1}{U} is not enough on its own.
    game, _ = _casting_game(set_pool, [], ["Stormwing Entity"], U=1, C=1)
    assert not game.queue_from_hand(0, "Stormwing Entity").supported

    # After an instant, it is.
    discounted, player = _casting_game(
        set_pool, [], ["Shock", "Stormwing Entity"], U=1, C=1, R=1
    )
    assert discounted.queue_from_hand(0, "Shock", target_player_index=1).supported
    discounted._settle()
    assert [c.name for c in player.spells_cast_this_turn] == ["Shock"]
    assert discounted.queue_from_hand(0, "Stormwing Entity").supported


def test_a_cast_is_recorded_even_when_the_spell_never_resolves(set_pool):
    """"You've **cast** an instant this turn" asks about the casting. A
    countered spell was cast (CR 601.2i finishes it before anyone responds), so
    the record is written where the cast is announced, not where it resolves."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Shock"]], library=[pool["Island"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])

    assert game.queue_from_hand(0, "Shock", target_player_index=1).supported
    assert [c.name for c in p1.spells_cast_this_turn] == ["Shock"]

    game.begin_turn_bookkeeping(1)
    assert p1.spells_cast_this_turn == [], "a 'this turn' record that never resets is a turn-two bug"


# --- Fight (CR 701.14), and the damage a creature reflects -------------------


def test_brash_taunter_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Brash Taunter"])
    assert program.supported, program.reason


def test_brash_taunter_fights_and_reflects_what_it_takes(set_pool):
    """Its two lines meet. The fight deals both halves (CR 701.14a), the
    Taunter survives its six because it is indestructible, and the "whenever
    this creature is dealt damage" trigger sends that six at the opponent."""
    pool = set_pool("M21")
    taunter = Permanent(card=pool["Brash Taunter"])       # 1/1 indestructible
    gargaroth = Permanent(card=pool["Elder Gargaroth"])   # 6/6
    p1 = PlayerState(name="P1", battlefield=[taunter])
    p2 = PlayerState(name="P2", battlefield=[gargaroth])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(
        0, "Brash Taunter", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    assert gargaroth.damage_marked == 1, "the Taunter's own power"
    assert taunter.damage_marked == 6
    assert game.is_on_battlefield(taunter), "indestructible"
    assert p2.life == 14, "the six it took, reflected"


def test_a_dealt_damage_trigger_is_not_gated_on_surviving(set_pool):
    """"Whenever this creature is dealt damage" triggers on the damage
    (CR 603.2); whether the creature dies is a state-based action that has not
    run yet. The guard that stood here read a rule that does not exist — it was
    harmless for a card whose trigger puts a counter on a dying creature, and
    wrong for one that is indestructible."""
    pool = set_pool("M21")
    taunter = Permanent(card=pool["Brash Taunter"])
    p1 = PlayerState(name="P1", battlefield=[taunter])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    from engine.handlers._common import apply_damage_to_creature

    # Nine damage to a 1/1: lethal by the numbers, and it still reflects.
    apply_damage_to_creature(game, taunter, 9, source=None)
    game._settle()

    assert p2.life == 11


def test_the_fight_needs_two_creatures_or_neither_deals(set_pool):
    """CR 701.14b, and the reason this is one instruction rather than two
    damage steps: written as two, the first would resolve and the second would
    not."""
    pool = set_pool("M21")
    taunter = Permanent(card=pool["Brash Taunter"])
    p1 = PlayerState(name="P1", battlefield=[taunter])
    p2 = PlayerState(name="P2")                     # nothing to fight
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Brash Taunter", target_player_index=1)
    game._settle()

    assert taunter.damage_marked == 0
    assert p2.life == 20
    assert any("neither deals damage" in line for line in game.log)


def test_a_fight_that_is_not_the_whole_effect_still_refuses():
    """Round 39's refusal, kept now that the card that motivated it has landed.

    "Then **it** fights…" after another sentence names that sentence's target —
    the fused pair is what reads it — so a bare `Fight` nested in a sequence
    must not lower onto the source-fights instruction, which would fight
    whichever creature the single picker offered. Primal Might proved it;
    this pins the rule after Primal Might stopped being the example.
    """
    from engine.grammar import compile_line

    whole = compile_line("This creature fights another target creature.")
    assert whole.lowered, whole.failure_reason

    nested = compile_line("Draw a card. Then it fights another target creature.")
    assert not nested.lowered


# --- What a sacrificed source is still worth ---------------------------------


def test_heartfire_immolator_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Heartfire Immolator"])
    assert program.supported, program.reason


def test_heartfire_immolator_deals_the_power_it_had_when_it_was_sacrificed(set_pool):
    """The source pays for its own ability by being sacrificed, so by
    resolution it is in a graveyard and its power is last-known information
    (CR 608.2). Prowess is what makes the distinction observable: a 2/1 that
    saw a noncreature spell this turn deals **three**, not two."""
    pool = set_pool("M21")
    immolator = Permanent(card=pool["Heartfire Immolator"])   # 2/1, prowess
    victim = Permanent(card=pool["Elder Gargaroth"])          # 6/6
    p1 = PlayerState(
        name="P1", battlefield=[immolator], hand=[pool["Shock"]],
        library=[pool["Mountain"]] * 4,
    )
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()
    assert immolator.effective_power == 3, "prowess"

    result = game.activate_permanent_ability(
        0, "Heartfire Immolator", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    assert not game.is_on_battlefield(immolator), "sacrificed to pay the cost"
    assert victim.damage_marked == 3, "the power it had, not the power it was printed with"


def test_heartfire_immolator_can_aim_at_a_planeswalker(set_pool):
    """"Target creature **or planeswalker**" — the union is the filter, and it
    is enforced at resolution as well as offered by the picker."""
    pool = set_pool("M21")
    immolator = Permanent(card=pool["Heartfire Immolator"])
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[immolator])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(
        0, "Heartfire Immolator", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert walker.metadata["loyalty_counters"] == 2, "damage to a walker is loyalty (CR 120.3c)"


# --- The sacrifice-seam round ------------------------------------------------


def test_havoc_jester_compiles_supported(set_pool):
    """"Whenever you sacrifice a permanent, this creature deals 1 damage to any
    target." The condition is the pool's first trigger on a *keyword action*
    rather than on a zone change or a step, and it is announced from
    ``Game.sacrifice_permanent`` — which is why it needed no fire site of its
    own: there are thirteen sacrifices in this engine and one transition."""
    assert compile_card_oracle(set_pool("M21")["Havoc Jester"]).supported


def test_havoc_jester_fires_when_a_cost_is_paid_by_sacrificing(set_pool):
    """The sacrifice that trips it is a *cost*, not an effect — Witch's Cauldron
    eats a creature to pay for its own ability. The Jester's ping is a separate
    ability on the stack, so both happen."""
    pool = set_pool("M21")
    jester = _nosick(Permanent(card=pool["Havoc Jester"]))
    cauldron = _nosick(Permanent(card=pool["Witch's Cauldron"]))
    food = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    p1 = PlayerState(name="P1", battlefield=[jester, cauldron, food],
                     library=[pool["Swamp"]] * 4)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    result = game.activate_permanent_ability(0, "Witch's Cauldron")
    assert result.supported, result.details
    game._settle()

    assert not game.is_on_battlefield(food), "eaten to pay the cost"
    assert p2.life == 19, "the Jester pinged for the sacrifice"


def test_havoc_jester_stays_silent_when_an_opponent_sacrifices(set_pool):
    """"Whenever **you** sacrifice" is the Jester's controller (CR 109.5). The
    event is announced once, game-wide, carrying the seat that sacrificed — the
    narrowing is the trigger's own word, not a second announcement."""
    pool = set_pool("M21")
    jester = _nosick(Permanent(card=pool["Havoc Jester"]))
    cauldron = _nosick(Permanent(card=pool["Witch's Cauldron"]))
    food = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    p1 = PlayerState(name="P1", battlefield=[jester])
    p2 = PlayerState(name="P2", battlefield=[cauldron, food],
                     library=[pool["Swamp"]] * 4)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 1

    game.activate_permanent_ability(1, "Witch's Cauldron")
    game._settle()

    assert not game.is_on_battlefield(food), "the opponent's own creature went"
    assert (p1.life, p2.life) == (20, 21), (
        "no ping: the opponent sacrificed, and they gained the Cauldron's life"
    )


# --- The additional-cost round ----------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Goremand",              # sacrifice cost // ETB: each opponent sacrifices
        "Sparkhunter Masticore", # discard cost // protection from planeswalkers
    ],
)
def test_additional_cost_creatures_compile_supported(set_pool, name):
    """Both were reported "creature text too complex" naming the *cost* line,
    which is the first line each prints — so nothing below it was ever read.
    A cost is not an effect, and the compiler now hands the line to
    engine/cast_costs.py instead of looking for an instruction in it."""
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_goremand_makes_each_opponent_sacrifice_when_it_enters(set_pool):
    """"When this creature enters, each opponent sacrifices a creature."

    The same prompt the controller-scoped form arms, owed by a different set of
    seats — one instruction with the payer named, never a second kind, because
    CR 701.21a already says the sacrificing player chooses.
    """
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Alpine Watchdog"])],
                     hand=[pool["Goremand"]])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pool["Concordia Pegasus"])])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.cast_from_hand(0, "Goremand")
    game._settle()

    assert [p.card.name for p in p2.battlefield] == [], "the opponent's creature went"
    assert [p.card.name for p in p1.battlefield] == ["Goremand"], (
        "and the Demon is not its own opponent (CR 102.3) — only the cost took one of ours"
    )


def test_sparkhunter_masticore_keeps_its_planeswalker_protection(set_pool):
    """The card the cost line was hiding. "Protection from planeswalkers" is a
    quality this engine models (CR 702.16), and the whole card was unsupported
    only because the compiler stopped at line one."""
    pool = set_pool("M21")
    masticore = _nosick(Permanent(card=pool["Sparkhunter Masticore"]))
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[masticore])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert ("card_type", "planeswalker") in game._protection_qualities(masticore)


# --- The trigger-timing round -----------------------------------------------


def test_deathbloom_thallid_leaves_a_saproling_behind(set_pool):
    """"When this creature dies, create a 1/1 green Saproling creature token."

    One of four M21 cards whose dies-trigger had no fire site: the loop that put
    them on the stack was keyed by instruction kind, one branch per card that
    had needed one, so ``create_token`` fell through.
    """
    pool = set_pool("M21")
    thallid = Permanent(card=pool["Deathbloom Thallid"])
    p1 = PlayerState(name="P1", battlefield=[thallid])
    p2 = PlayerState(name="P2", hand=[pool["Shock"]] * 3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 1

    while game.is_on_battlefield(thallid) and p2.hand:
        game.cast_from_hand(1, "Shock", target_player_index=0, target_permanent_index=0)
        game._settle()

    assert [p.card.name for p in p1.battlefield] == ["Saproling Token"]


def test_conclave_mentor_gains_the_life_it_had(set_pool):
    """"When this creature dies, you gain life equal to its power." The power is
    read as the permanent leaves (CR 603.10), which this fire site was already
    doing — it is the only dies-shape it *did* get right, and the reason the
    general case looked covered."""
    pool = set_pool("M21")
    mentor = Permanent(card=pool["Conclave Mentor"])   # 2/2
    p1 = PlayerState(name="P1", battlefield=[mentor], life=20)
    p2 = PlayerState(name="P2", hand=[pool["Shock"]] * 3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 1

    while game.is_on_battlefield(mentor) and p2.hand:
        game.cast_from_hand(1, "Shock", target_player_index=0, target_permanent_index=0)
        game._settle()

    assert p1.life == 22


# --- Round 55: a where-clause that counts a history --------------------------


def _death_board(set_pool):
    pool = set_pool("M21")
    p1, p2 = PlayerState(name="P1"), PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    p1.library = [pool["Swamp"]] * 12
    return game, p1, p2, pool


def test_lilianas_standard_bearer_draws_for_each_creature_that_died(set_pool):
    """"…where X is the number of creatures that **died under your control**
    this turn." The count is a history, so it is read off the per-seat tracker
    rather than by scanning a zone — the creatures it counts are exactly the
    ones no longer on the battlefield, and the bare filter "creature" would
    count the survivors instead."""
    game, p1, p2, pool = _death_board(set_pool)
    for owner in (p1, p1, p1):
        perm = Permanent(card=pool["Alpine Watchdog"])
        owner.battlefield.append(perm)
        game._permanent_to_graveyard(owner, perm)
    p1.hand = [pool["Liliana's Standard Bearer"]]

    game.queue_from_hand(0, "Liliana's Standard Bearer")
    game._settle()

    assert len([c for c in p1.hand if c.name == "Swamp"]) == 3


def test_the_death_count_is_the_controllers_own(set_pool):
    """The control, and what the tracker exists for: a creature that died under
    the *opponent's* control is not counted, which a game-wide tally could not
    tell apart."""
    game, p1, p2, pool = _death_board(set_pool)
    for owner in (p1, p2, p2):
        perm = Permanent(card=pool["Alpine Watchdog"])
        owner.battlefield.append(perm)
        game._permanent_to_graveyard(owner, perm)
    p1.hand = [pool["Liliana's Standard Bearer"]]

    game.queue_from_hand(0, "Liliana's Standard Bearer")
    game._settle()

    assert len([c for c in p1.hand if c.name == "Swamp"]) == 1


def test_a_variable_count_of_any_colour_mana_refuses(set_pool):
    """Found by round 54's "an X nothing reads" guard rather than by a card.
    "Add X mana of any one color" was read as **one** mana: the parser took
    ``count.value if isinstance(count, ast.Fixed) else 1``, so a card printing X
    would have added a single mana and reported success. Nothing in the pool
    reaches the grammar with that shape — both cards that print it keep their own
    fused handlers — which is exactly why it had to refuse rather than wait for
    the card that would have found it."""
    result = compile_line("Add X mana of any one color.")

    assert not result.parsed
    assert "variable count of any-colour mana" in (result.failure_reason or "")


# --- Round 57: a damage event that knows who dealt it -----------------------


def _pyreling_board(set_pool):
    pool = set_pool("M21")
    pyreling = Permanent(card=pool["Chandra's Pyreling"])
    p1 = PlayerState(name="P1", battlefield=[pyreling], hand=[pool["Shock"]])
    p2 = PlayerState(name="P2", hand=[pool["Shock"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2, pyreling


def test_chandras_pyreling_grows_when_your_spell_burns_an_opponent(set_pool):
    """"Whenever a source you control deals noncombat damage to an opponent…"
    The trigger reads the *source's* controller (CR 109.5), which is what a
    damage event could not answer until it carried a seat: a Shock arrives at
    the damage paths as its printed card."""
    game, p1, p2, pyreling = _pyreling_board(set_pool)

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()

    assert pyreling.effective_power == 2  # 1/3 printed, +1/+0
    assert game._has_keyword(pyreling, "double strike")


def test_chandras_pyreling_is_silent_when_the_opponent_burns_you(set_pool):
    """The control the seat exists for. Reading the *damaged* player's seat
    instead of the source's would fire on exactly this."""
    game, p1, p2, pyreling = _pyreling_board(set_pool)
    game.active_player_index = 1

    game.cast_from_hand(1, "Shock", target_player_index=0)
    game._settle()

    assert pyreling.effective_power == 1
    assert not game._has_keyword(pyreling, "double strike")


def test_chandras_pyreling_is_silent_on_combat_damage(set_pool):
    """"Noncombat" is a property of the fire site rather than a flag: the combat
    damage step reaches players by its own path, because it applies prevention
    where the event is recorded. Attacking with the Pyreling must not pump it."""
    game, p1, p2, pyreling = _pyreling_board(set_pool)
    game.start_turn(0)
    _nosick(pyreling)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert p2.life == 19, "the 1/3 connected"
    assert pyreling.effective_power == 1
    assert not game._has_keyword(pyreling, "double strike")


# --- Round 58: the condition that parsed on both sides and fired nowhere ----


def _draw_trigger_board(set_pool):
    pool = set_pool("M21")
    oak = Permanent(card=pool["Burlfist Oak"])
    coatl = Permanent(card=pool["Lorescale Coatl"])
    p1 = PlayerState(
        name="P1", battlefield=[oak, coatl], library=[pool["Island"]] * 8
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, p1, oak, coatl, pool


def test_a_draw_trigger_fires_at_all(set_pool):
    """Two cards that compiled supported, entered play and did nothing.

    "Whenever you draw a card" parsed in the oracle table *and* in the grammar's
    phrase table and had no dispatcher anywhere, so both cards produced a real
    instruction under a condition the game never announced. The support report
    counted them as working the whole time — the compiler can see that a
    condition parsed and cannot see whether anything says it happened."""
    game, p1, oak, coatl, pool = _draw_trigger_board(set_pool)

    game._draw_with_replacements(p1, 1)
    game._settle()

    assert (oak.effective_power, oak.effective_toughness) == (4, 5)
    assert coatl.metadata["plus_counters"] == 1


def test_a_draw_trigger_fires_once_per_card(set_pool):
    """CR 121.2: drawing N cards is N individual draws, so the sweep counts
    rather than flags — which is the whole difference between this and the
    "your second card each turn" trigger it sits beside."""
    game, p1, oak, coatl, pool = _draw_trigger_board(set_pool)

    game._draw_with_replacements(p1, 3)
    game._settle()

    assert coatl.metadata["plus_counters"] == 3
    assert oak.effective_power == 2 + 2 * 3


def test_an_opponents_draw_does_not_fire_your_trigger(set_pool):
    """"Whenever **you** draw a card" — the seat is the drawing player's, and
    the sweep is game-wide, so this is the narrowing that has to hold."""
    game, p1, oak, coatl, pool = _draw_trigger_board(set_pool)
    p2 = game.players[1]
    p2.library = [pool["Island"]] * 4

    game._draw_with_replacements(p2, 2)
    game._settle()

    assert coatl.metadata.get("plus_counters", 0) == 0
    assert oak.effective_power == 2

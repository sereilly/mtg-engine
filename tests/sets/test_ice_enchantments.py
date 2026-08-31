"""Ice Age (ICE) enchantment cards.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- Round 1: cumulative upkeep (CR 702.24) ---
def _cu_trigger(card):
    """The cumulative upkeep ability *card* compiles to, or None."""
    return next(
        (
            trig
            for trig in compile_card_oracle(card).triggered_abilities
            if trig.instruction is not None
            and trig.instruction.kind == "cumulative_upkeep"
        ),
        None,
    )
def test_mystic_remora_cumulative_upkeep_reaches_an_enchantment(set_pool):
    """The rewrite has to run on the **non-creature** front end too.

    Mystic Remora prints cumulative upkeep beside a trigger the engine cannot
    yet read. The creature loop and the permanent loop are different code, and
    with the rewrite in only the first one this card compiled *supported* with
    its upkeep silently dropped — a strictly better card than the one printed.
    """
    remora = set_pool("ICE")["Mystic Remora"]
    trigger = _cu_trigger(remora)

    assert trigger is not None
    assert trigger.condition.kind == "upkeep_self"
    assert trigger.instruction.payload["mana"] == {"generic": 1}
# --- Round 2: the Scarab cycle — a conditional static on an Aura's host ---
def _scarab_board(set_pool, scarab_name: str, opponent_permanent: str | None):
    """A 2/2 bear wearing *scarab_name*, with the opponent's board as named.

    The Aura is attached with ``attach_aura`` rather than cast, because what is
    under test is the continuous effect while attached (CR 611.3a) — recomputed
    on every read, never applied once at attachment.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])  # a vanilla 2/2, no text at all
    scarab = Permanent(card=pool[scarab_name])
    p1 = PlayerState(name="P1", battlefield=[bear, scarab], life=20)
    theirs = [Permanent(card=pool[opponent_permanent])] if opponent_permanent else []
    p2 = PlayerState(name="P2", battlefield=theirs, life=20)
    game = Game(players=[p1, p2])
    attach_aura(scarab, bear)
    game._settle()
    return game, bear, scarab
def test_black_scarab_grants_nothing_while_no_opponent_has_a_black_permanent(set_pool):
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", None)

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
def test_black_scarab_grants_plus_two_while_an_opponent_has_a_black_permanent(set_pool):
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", "Moor Fiend")  # a black creature

    assert (bear.effective_power, bear.effective_toughness) == (4, 4)
def test_black_scarab_reads_the_condition_on_every_recompute(set_pool):
    """CR 611.3a — the condition is asked continuously, not locked in when the
    Aura attached. Removing the opponent's black permanent removes the bonus
    with nothing to undo."""
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", "Moor Fiend")
    assert bear.effective_power == 4

    game.remove_from_battlefield(game.players[1].battlefield[0])
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
def test_scarab_condition_is_measured_from_the_auras_controller(set_pool):
    """CR 109.5: the ability is the Aura's, so "an opponent" is an opponent of
    whoever controls the Aura — not of whoever controls the creature.

    The cycle exists to be put on an opponent's creature, so this is the case
    the card is printed for rather than a corner: P1's Scarab on P1's own black
    creature must see P1's board as "you", find no *opponent* with a black
    permanent, and grant nothing.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    black_bear = Permanent(card=pool["Moor Fiend"])
    scarab = Permanent(card=pool["Black Scarab"])
    p1 = PlayerState(name="P1", battlefield=[black_bear, scarab], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(scarab, black_bear)
    game._settle()

    assert (black_bear.effective_power, black_bear.effective_toughness) == (3, 3)
def test_every_scarab_in_the_cycle_compiles_to_the_same_shape(set_pool):
    """Five cards, one sentence with the colour word changed — the reason this
    is a production rather than five entries."""
    pool = set_pool("ICE")
    colors = {
        "Black Scarab": "B", "Blue Scarab": "U", "Green Scarab": "G",
        "Red Scarab": "R", "White Scarab": "W",
    }
    for name, symbol in colors.items():
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        static = next(
            i for i in program.instructions if i.kind == "conditional_static"
        )
        assert static.payload["subject"] == "attached", name
        assert static.payload["power"] == 2 and static.payload["toughness"] == 2
        assert static.payload["condition"]["who"] == "opponent", name
        assert static.payload["condition"]["filter"]["color_filter"] == symbol, name
# --- Round 5: Aura keyword grants, from the engine's one keyword registry ---
def test_wings_of_aesthir_grants_both_keywords_and_the_bonus(set_pool):
    """"Enchanted creature gets +1/+0 and has flying **and first strike**."

    Two keywords on one line. The grant used to read one, so a card printing
    two would have shipped giving half of what it prints — and matched, so
    nothing would have said so.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    wings = Permanent(card=pool["Wings of Aesthir"])
    p1 = PlayerState(name="P1", battlefield=[bear, wings], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(wings, bear)
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (3, 2)
    assert bear.has_keyword("flying")
    assert bear.has_keyword("first strike")
def test_imposing_visage_grants_menace(set_pool):
    """A keyword the engine has implemented all along and the Aura reader did
    not list. `auras` kept a hand-written copy of the keyword registry; it is
    derived now, so what an Aura may grant and what the engine implements are
    one fact."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    visage = Permanent(card=pool["Imposing Visage"])
    p1 = PlayerState(name="P1", battlefield=[bear, visage], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(visage, bear)
    game._settle()

    assert compile_card_oracle(visage.card).supported
    assert bear.has_keyword("menace")
# --- Round 10: sweeps and grants over a set the sentence names ---
def test_jokulhaups_destroys_three_types_and_beats_regeneration(set_pool):
    """"Destroy all artifacts, creatures, and lands. They can't be regenerated."

    A type union no per-scope sweep kind names. The filtered sweep already
    answers it — `type_filter` takes a list and the matcher reads one as a
    union — so this routes rather than needing a fourth hand-written scope.
    """
    pool = set_pool("ICE")
    creature = Permanent(card=pool["Balduvian Bears"])
    land = Permanent(card=pool["Forest"])
    enchantment = Permanent(card=pool["Snowfall"])
    p1 = PlayerState(name="P1", battlefield=[creature, land, enchantment], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    program = compile_card_oracle(pool["Jokulhaups"])
    assert program.supported
    instruction = program.instructions[0]
    assert instruction.kind == "destroy_all_matching"
    assert set(instruction.payload["type_filter"]) == {"artifact", "creature", "land"}
    assert instruction.payload["bypass_regeneration"] is True
# --- Round 14: a hook that had a second card ---
def test_portent_and_elemental_augury_reorder_a_library(set_pool):
    """"Look at the top three cards of target player's library, then put them
    back in any order."

    The sentence Natural Selection prints, verbatim — and `card_hooks`' entry
    bar is that no second card, real or plausibly printable, shares the shape.
    Two did. Portent compiled *supported* on the strength of its cantrip line
    while its main effect was a bare whitelist marker; Elemental Augury has no
    second line and was unsupported outright.
    """
    pool = set_pool("ICE")
    for name in ("Portent", "Elemental Augury"):
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        assert "reorder_target_library_top" in {
            instruction.kind for instruction in program.instructions
        }, name
def test_portent_offers_the_shuffle_and_elemental_augury_does_not(set_pool):
    """The optional shuffle is a printed sentence, so it rides the payload —
    Portent prints it and Elemental Augury does not."""
    pool = set_pool("ICE")

    def _reorder(name):
        return next(
            instruction for instruction in compile_card_oracle(pool[name]).instructions
            if instruction.kind == "reorder_target_library_top"
        )

    assert _reorder("Portent").payload["may_shuffle"] is True
    assert _reorder("Elemental Augury").payload["may_shuffle"] is False
# --- Round 15: two Aura effect lines with a P/T half in front ---
def test_spectral_shield_grants_toughness_and_target_immunity(set_pool):
    """"Enchanted creature gets +0/+2 **and** can't be the target of spells."

    Two effects on one line, owned by two readers: the P/T grant is
    `aura_static_pt_grant`'s and the immunity is `target_immunity`'s. The
    immunity reader could not see past the P/T half, so the whole line went
    unclaimed — the same split `_KEYWORD_GRANT` already makes with its optional
    "gets ±N/±N and" prefix, and made in the one place both the support gate and
    the runtime reader go through.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    shield = Permanent(card=pool["Spectral Shield"])
    p1 = PlayerState(name="P1", battlefield=[bear, shield], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(shield, bear)
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (2, 4)
    assert not game._can_be_targeted(bear, 1)
def test_errantry_lets_its_creature_attack_only_alone(set_pool):
    """"Enchanted creature gets +3/+0 and **can only attack alone**." CR 506.5,
    read as a restriction on the *declaration* — a per-creature predicate has no
    way to say "and nobody else", which is why the attack cap beside it is
    checked over the declared set too."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    lone = Permanent(card=pool["Balduvian Bears"])
    friend = Permanent(card=pool["Balduvian Barbarians"])
    errantry = Permanent(card=pool["Errantry"])
    p1 = PlayerState(name="P1", battlefield=[lone, friend, errantry], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(errantry, lone)
    game._settle()

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert (lone.effective_power, lone.effective_toughness) == (5, 2)
    ok, message = game.declare_attackers(0, [0, 1])
    assert not ok and "alone" in message
    assert game.declare_attackers(0, [0])[0], "alone is legal"
# --- Round 16: a pay-or-else prompt aimed at the event's player ---
def test_soul_barrier_offers_the_pay_to_the_caster_not_its_controller(set_pool):
    """"Whenever an opponent casts a creature spell, this enchantment deals 2
    damage to **that player** unless **they** pay {2}."

    Both pay-or-else flows offered the cost to the ability's *controller*, so
    this card and Seizures were unsupported outright. The seat is the one the
    fire site froze into the trigger's context (CR 603.10) — the trigger has no
    target, so `context.caster` is the enchantment's controller and prompting
    them would charge and damage the wrong player.
    """
    pool = set_pool("ICE")
    barrier = Permanent(card=pool["Soul Barrier"])
    p1 = PlayerState(name="P1", battlefield=[barrier], life=20)
    p2 = PlayerState(name="P2", hand=[pool["Balduvian Bears"]], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(1, "Balduvian Bears")
    game._settle()

    offers = [choice for choice in game.pending_choices if choice.kind == "optional_pay"]
    assert len(offers) == 1
    assert offers[0].player_index == 1, "the spell's caster is offered the cost"
    assert offers[0].data["cost"] == {"generic": 2}
    assert offers[0].data["damage"] == 2
# --- Round 17: a keyword family named whole, and a negated supertype ---
def test_hallowed_ground_returns_only_a_nonsnow_land(set_pool):
    """"Return target **nonsnow** land you control to its owner's hand." A
    negated supertype (CR 205.4), which no layer computes — the matcher reads
    it off the effective type line, exactly as it reads the positive key."""
    pool = set_pool("ICE")
    program = compile_card_oracle(pool["Hallowed Ground"])
    assert program.supported

    ability = program.activated_abilities[0]
    described = ability.instruction.payload["filter"]
    assert described["exclude_supertypes"] == ["snow"]

    from engine.subject_filters import subject_matches

    plain = Permanent(card=pool["Forest"])
    snowy = Permanent(card=pool["Snow-Covered Forest"])
    p1 = PlayerState(name="P1", battlefield=[plain, snowy], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    assert subject_matches(game, plain, described, observer=0)
    assert not subject_matches(game, snowy, described, observer=0)
# --- Round 19: an offer whose action shares the printed subject ---
def test_thoughtleech_offers_the_life_when_an_opponents_island_taps(set_pool):
    """"Whenever an Island an opponent controls becomes tapped, **you may gain
    1 life**."

    The offer prints its subject once, in front of "may", and the action behind
    it is a bare verb — the same shared-subject shape a conjunction already
    handles ("Target player draws a card **and loses 1 life**"), one clause
    earlier. Without it "you may gain 1 life" refused while "you may draw a
    card" parsed, because "draw" is a bare imperative and "gain" is not.
    """
    pool = set_pool("ICE")
    leech = Permanent(card=pool["Thoughtleech"])
    island = Permanent(card=pool["Island"])
    p1 = PlayerState(name="P1", battlefield=[leech], life=20)
    p2 = PlayerState(name="P2", battlefield=[island], life=20)
    game = Game(players=[p1, p2])

    game.become_tapped(island)
    game._settle()

    offers = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert len(offers) == 1 and offers[0].player_index == 0
    assert offers[0].data["cost"] == {}, "the offer costs nothing; it is a may"

    game.auto_resolve_pending_optional_pays()
    game._settle()
    assert p1.life == 21
# --- Round 21: a regeneration rider on a subject nothing targets ---
def test_incinerate_kills_through_a_regeneration_shield(set_pool):
    """"Incinerate deals 3 damage to any target. **A creature dealt damage this
    way** can't be regenerated this turn."

    CR 701.19c printed as a sentence about the *effect* rather than about a
    pronoun — the damage twin of War Barge's "A creature destroyed this way
    can't be regenerated", and it exists for the same reason: by the time the
    rider is read there is no "it" left to point at, so the noun restates what
    the damage already named. The rider parser required the sentence to open
    with "it" or "if", so Incinerate refused its only line.
    """
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])  # 2/2
    bears.regeneration_shield = 1
    p1 = PlayerState(name="P1", hand=[pool["Incinerate"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[bears], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(
        0, "Incinerate", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert bears.metadata["cant_be_regenerated_this_turn"]
    assert bears not in p2.battlefield, "the shield cannot answer this damage"
    assert bears.regeneration_shield == 1, "and it was not spent"
def _combat(game: Game, attacker_indices: list[int]) -> None:
    """Advance seat 0's turn to the declare-blockers step with those attackers."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"
def test_lim_duls_cohort_denies_regeneration_to_what_it_blocks(set_pool):
    """"Whenever this creature blocks or becomes blocked by a creature, **that
    creature** can't be regenerated this turn."

    The third subject the rider can have, beside a chosen target (Hurr Jackal)
    and the ability's own source (Clergy of the Holy Nimbus): the other half of
    the blocking pair, which nothing on the board records and only the trigger
    knows. `_lower_cant_be` saw no event at all and refused every subject that
    was neither, so the card compiled with its only line lowering to nothing.

    Run in real combat rather than asserted on the payload, because the thing
    that could go wrong is *which* creature is marked: on the blocks half the
    stack item's target is the blocking creature itself, so a handler reading
    the target would deny regeneration to the Cohort and still look resolved.
    """
    pool = set_pool("ICE")
    attacker = Permanent(card=pool["Balduvian Bears"])  # 2/2
    attacker.regeneration_shield = 1
    cohort = Permanent(card=pool["Lim-Dûl's Cohort"])  # 2/2
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[cohort], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0])
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()

    assert attacker.metadata.get("cant_be_regenerated_this_turn")
    assert not cohort.metadata.get("cant_be_regenerated_this_turn"), (
        "the rider names the creature it blocked, not itself"
    )

    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert attacker not in p1.battlefield, "2 damage is lethal and unregenerable"
# --- Round 24: an attack cost printed on a permanent, scaled by the attack ---
def _woodlands_board(set_pool, attackers: int, lands: int, land: str = "Forest"):
    """Seat 0 attacking under seat 1's Flooded Woodlands, with *lands* to pay."""
    pool = set_pool("ICE")
    bears = [Permanent(card=pool["Balduvian Bears"]) for _ in range(attackers)]
    for bear in bears:
        _nosick(bear)
    holdings = [Permanent(card=pool[land]) for _ in range(lands)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[*bears, *holdings], life=20),
        PlayerState(
            name="P2", battlefield=[Permanent(card=pool["Flooded Woodlands"])], life=20
        ),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    return game
def test_flooded_woodlands_charges_one_land_per_attacking_green_creature(set_pool):
    """"Green creatures can't attack unless their controller sacrifices a land
    of their choice **for each green creature they control that's attacking**."

    CR 508.1g printed on a permanent that names a *class* rather than itself,
    with the payer being that class's controller. The "for each" tail is what
    makes it a per-attacker cost, which is the shape `_attack_costs_of` already
    returns — so the declaration sums it with no second adder to keep in step.
    """
    game = _woodlands_board(set_pool, attackers=2, lands=2)

    ok, message = game.declare_attackers(0, [0, 1])

    assert ok, message
    assert not [
        perm for perm in game.players[0].battlefield
        if perm.card.primary_type == "land"
    ], "two attackers, two lands"
def test_flooded_woodlands_keeps_the_whole_team_home_when_one_land_is_short(set_pool):
    """The cost is one payment over the declaration, and `can_attack` is a
    per-creature predicate: it can say "there is a land for this one" and not
    "and another for the next". Both Bears were gated as payable, declared, and
    then charged **once** — the card doing less than it prints on exactly the
    board it was printed to stop. The declaration is planned now, as the mana
    half of the same rule already was.
    """
    game = _woodlands_board(set_pool, attackers=2, lands=1)

    ok, message = game.declare_attackers(0, [0, 1])

    assert not ok
    assert "sacrifice" in message
    assert len(game.players[0].battlefield) == 3, "nothing was half-charged"

    # One attacker is still legal, and pays.
    assert game.declare_attackers(0, [0])[0]
    assert not [
        perm for perm in game.players[0].battlefield
        if perm.card.primary_type == "land"
    ]
def test_reclamation_is_flooded_woodlands_with_the_colour_changed(set_pool):
    """One sentence, two cards. The restricted class and the sacrifice are both
    payload, so the pair differs by a colour symbol — and a green creature walks
    past Reclamation untouched."""
    pool = set_pool("ICE")
    payloads = {
        name: compile_card_oracle(pool[name]).instructions[0].payload
        for name in ("Flooded Woodlands", "Reclamation")
    }

    assert payloads["Flooded Woodlands"] == {
        "subject": {"type_filter": "creature", "color_filter": "G"},
        "filter": {"type_filter": "land"},
        "count": 1,
    }
    assert payloads["Reclamation"] == {
        "subject": {"type_filter": "creature", "color_filter": "B"},
        "filter": {"type_filter": "land"},
        "count": 1,
    }

    green = _nosick(Permanent(card=pool["Balduvian Bears"]))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[green], life=20),
        PlayerState(
            name="P2", battlefield=[Permanent(card=pool["Reclamation"])], life=20
        ),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert game.declare_attackers(0, [0])[0], "a green creature owes Reclamation nothing"
# --- Round 27: a supertype is a computed characteristic (CR 205.4, layer 4) ---
def _board(set_pool, *names, opponent=()):
    """A board of ICE cards, mine and the opponent's, ready to activate."""
    pool = set_pool("ICE")
    mine = [Permanent(card=pool[n]) for n in names]
    theirs = [Permanent(card=pool[n]) for n in opponent]
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=mine, life=20),
            PlayerState(name="P2", battlefield=theirs, life=20),
        ]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    for perm in mine:
        _nosick(perm)
    return game, mine, theirs
def test_melting_thaws_every_land_and_gives_it_back(set_pool):
    """"All lands are no longer snow." A board-wide static, so it is a
    derivation-table entry beside "All Mountains are Plains" rather than a
    production: a continuous effect recomputed from the board, where the
    targeted spelling's one-shot lowering would fire once and never again.

    CR 611.3a/b: the lands are snow again the moment Melting leaves.
    """
    game, (melting, island), (their_forest,) = _board(
        set_pool, "Melting", "Snow-Covered Island",
        opponent=["Snow-Covered Forest"],
    )
    game._refresh_dynamic_creatures()

    assert not island.has_supertype("snow")
    assert not their_forest.has_supertype("snow"), "every land, not just yours"

    game.remove_from_battlefield(melting)
    game._refresh_dynamic_creatures()

    assert island.has_supertype("snow")
    assert their_forest.has_supertype("snow")
def test_meltings_contribution_does_not_accumulate(set_pool):
    """A derived channel is cleared and rebuilt on every continuous-effects
    refresh (CR 611.3a), which runs constantly. Recording it the way a resolved
    effect is recorded would leave one entry per pass, forever — the reason
    `land_types.py` has two channels and this one is the second."""
    game, (melting, island), _ = _board(
        set_pool, "Melting", "Snow-Covered Island"
    )

    for _ in range(5):
        game._refresh_dynamic_creatures()

    assert island.metadata.get("derived_lost_supertypes") == ["snow"]
def test_melting_does_not_stop_a_land_being_basic(set_pool):
    """The sentence names one supertype. A land Melting has thawed is still a
    basic land, so Blood Moon still passes it by (CR 205.4b)."""
    game, (melting, island), _ = _board(
        set_pool, "Melting", "Snow-Covered Island"
    )
    game._refresh_dynamic_creatures()

    assert island.has_supertype("basic")
    assert island.has_type("island"), "and still an Island"
# --- Round 31: a cumulative upkeep cost is a cost, not a mana cost ---
def test_infernal_darkness_charges_the_life_beside_the_mana(set_pool):
    """"Cumulative upkeep—Pay {B} and 1 life."

    The card was *supported* while charging only the {B}: the cost went to a
    symbol scanner, which found "{B}" and ignored "and 1 life". Both halves are
    the cost, and both escalate.
    """
    darkness = Permanent(card=set_pool("ICE")["Infernal Darkness"])
    p1 = PlayerState(
        name="P1", battlefield=[darkness], mana_pool={"B": 3}, life=20
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)

    assert darkness in p1.battlefield
    assert p1.life == 19
def test_infernal_darkness_life_escalates_with_the_age_counters(set_pool):
    darkness = Permanent(card=set_pool("ICE")["Infernal Darkness"])
    p1 = PlayerState(
        name="P1", battlefield=[darkness], mana_pool={"B": 3}, life=20
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)
    p1.mana_pool["B"] = 3
    game.resolve_upkeep(0)

    assert counters_on(darkness, "age") == 2
    assert p1.life == 17, "1 life then 2"
def test_infernal_darkness_unaffordable_life_pays_nothing_at_all(set_pool):
    """A player with the mana and not the life pays neither: CR 702.24a's last
    sentence, asked about the whole cost rather than one half of it."""
    darkness = Permanent(card=set_pool("ICE")["Infernal Darkness"])
    p1 = PlayerState(
        name="P1", battlefield=[darkness], mana_pool={"B": 3}, life=1
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)  # 1 life, affordable
    assert darkness in p1.battlefield
    assert p1.life == 0

    p1.life = 1
    p1.mana_pool["B"] = 3
    game.resolve_upkeep(0)  # 2 life, not affordable

    assert darkness not in p1.battlefield
    assert p1.life == 1, "nothing is paid when the whole cost cannot be"
def test_the_upkeep_prompt_quotes_a_cost_that_is_not_mana(set_pool):
    """The prompt is a label the server writes, because "{B} and 1 life" is
    not a run of symbols and the number in it is this upkeep's, not the
    printed one."""
    darkness = Permanent(card=set_pool("ICE")["Infernal Darkness"])
    p1 = PlayerState(name="P1", battlefield=[darkness], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    entry = next(
        c for c in game.get_upkeep_pay_triggers(0)
        if c["card_name"] == "Infernal Darkness"
    )

    assert entry["cost_label"] == "{B} and 1 life"
    assert entry["cost_pay_label"] == "Pay {B} and 1 life"
    assert entry["cost"] == {"mana": {"B": 1}, "life": 1}
# --- Round 32: a shield that narrows nothing, and one around the enchanted creature ---
def _fylgja_on_a_bear(set_pool, counters: int = 4):
    from engine.auras import attach_aura
    from engine.named_counters import add_counters

    bear = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    fylgja = Permanent(card=set_pool("ICE")["Fylgja"])
    p1 = PlayerState(name="P1", battlefield=[bear, fylgja], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(fylgja, bear)
    add_counters(fylgja, "healing", counters)
    return game, p1, fylgja, bear
def test_fylgja_shields_the_creature_it_enchants(set_pool):
    """"Remove a healing counter from this Aura: Prevent the next 1 damage that
    would be dealt to enchanted creature this turn."

    A CR 615.1 shield around the Aura's *host*, which is a fourth recipient
    beside "you", "this permanent" and a chosen target — and the one the pool
    had never printed.
    """
    from engine.named_counters import counters_on

    game, _p1, fylgja, bear = _fylgja_on_a_bear(set_pool)

    result = game.activate_permanent_ability(0, "Fylgja", ability_index=0)

    assert result.supported
    assert counters_on(fylgja, "healing") == 3, "the counter is the cost"
    assert bear.damage_prevention_pool == 1

    assert game._mark_damage_on_permanent(bear, 3) == 2
    assert bear.damage_marked == 2
def test_fylgja_does_not_shield_itself(set_pool):
    """The recipient is the Aura's *host*, not the Aura. Rock Hydra's
    "…dealt to this creature" is the neighbouring branch and shields the
    permanent the ability is on, so reusing it here would put the shield on
    an enchantment nothing ever deals damage to."""
    game, _p1, fylgja, bear = _fylgja_on_a_bear(set_pool)

    game.activate_permanent_ability(0, "Fylgja", ability_index=0)

    assert fylgja.damage_prevention_pool == 0
    assert bear.damage_prevention_pool == 1
def test_fylgja_spends_one_counter_per_point_and_runs_out(set_pool):
    """Four counters, four points — and the fifth activation has nothing to
    pay with, so the ability is not activated at all."""
    from engine.named_counters import counters_on

    game, _p1, fylgja, bear = _fylgja_on_a_bear(set_pool, counters=1)

    assert game.activate_permanent_ability(0, "Fylgja", ability_index=0).supported
    assert counters_on(fylgja, "healing") == 0
    assert bear.damage_prevention_pool == 1

    game.activate_permanent_ability(0, "Fylgja", ability_index=0)

    assert bear.damage_prevention_pool == 1, "no counter, no second shield"
def test_fylgjas_counter_cost_is_what_the_claim_used_to_refuse(set_pool):
    """The Aura gate asked for the *shape* of an activation line — a run of mana
    symbols, then a colon — standing in for the parser that reads one. CR 602.1
    admits any cost, and Fylgja's is a counter removal, so a card the compiler
    parses in full was reported unsupported for the shape of its cost.

    The claim asks `_parse_activated_ability` now, which is the reader it was
    describing.
    """
    from engine.auras import aura_activated_ability_claim

    line = (
        "remove a healing counter from this aura: prevent the next 1 damage "
        "that would be dealt to enchanted creature this turn"
    )
    assert aura_activated_ability_claim(line, "Fylgja") is not None
    assert compile_card_oracle(set_pool("ICE")["Fylgja"]).supported
def test_a_mana_cost_alone_no_longer_claims_a_line_the_compiler_refuses(set_pool):
    """The stand-in was wrong in both directions: a line matching the *shape* of
    an activation was claimed whether or not the compiler could read it, which
    is how an Aura reports supported carrying an ability that does nothing.

    The example expires every time the compiler learns the line it names, and
    it has now done so twice in one wave: Chromatic Armor's "{X}: Put a sleight
    counter on this Aura…" first, then Earthlore's tap-the-enchanted-land cost,
    implemented by a *parallel branch* in the same round. So it is re-pointed,
    not deleted — what the guard is about is the *claim reader*, not the card,
    and it needs some line the compiler genuinely still refuses to stay honest.
    Caribou Range's is the current one: a sacrifice cost naming a token.
    """
    from engine.auras import aura_activated_ability_claim

    line = "sacrifice a caribou token: you gain 1 life"
    assert aura_activated_ability_claim(line, "Caribou Range") is None
    assert not compile_card_oracle(set_pool("ICE")["Caribou Range"]).supported


# --- Round 38: the board is the cap, and an end-step gate with no seat in it ---
def _wisps_board(set_pool, swamps: int = 1, creatures: int = 0):
    """Withering Wisps out, with *swamps* snow Swamps and the mana to fire it."""
    from engine.card_loader import load_cards

    pool = set_pool("ICE")
    wisps = Permanent(card=pool["Withering Wisps"])
    board = [wisps] + [Permanent(card=pool["Snow-Covered Swamp"]) for _ in range(swamps)]
    board += [_nosick(Permanent(card=pool["Balduvian Bears"])) for _ in range(creatures)]
    p1 = PlayerState(name="P1", battlefield=board, mana_pool={"B": 9}, life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    return game, p1, wisps


def test_withering_wisps_is_capped_by_the_swamps_you_control(set_pool):
    """"Activate no more times each turn than the number of snow Swamps you
    control."

    The first cap in the pool whose number is printed nowhere on the card. One
    snow Swamp, one activation — and the second is refused with nothing spent.
    """
    game, _p1, _wisps = _wisps_board(set_pool, swamps=1)

    first = game.activate_permanent_ability(0, "Withering Wisps", ability_index=0)
    game.resolve_top_of_stack()
    assert first.supported
    assert game.players[1].life == 19

    second = game.activate_permanent_ability(0, "Withering Wisps", ability_index=0)

    assert not second.supported
    assert not game.stack, "a refused activation puts nothing on the stack"
    assert game.players[1].life == 19


def test_withering_wisps_cap_is_re_measured_on_the_board_it_is_asked_about(set_pool):
    """Two snow Swamps, two activations. The cap is a count, not a stamp taken
    when the permanent entered: it is asked again at each activation, so a
    Swamp that arrives between two raises it."""
    game, _p1, _wisps = _wisps_board(set_pool, swamps=2)

    assert game.activate_permanent_ability(0, "Withering Wisps", ability_index=0).supported
    game.resolve_top_of_stack()
    assert game.activate_permanent_ability(0, "Withering Wisps", ability_index=0).supported
    game.resolve_top_of_stack()
    assert not game.activate_permanent_ability(0, "Withering Wisps", ability_index=0).supported

    assert game.players[1].life == 18


def test_a_counted_cap_is_a_cap_even_though_no_number_is_printed(set_pool):
    """The tally asks whether the line is capped; the refusal asks what the cap
    is. Fused into one text-only reader — as they were while every cap in the
    pool printed its number — a counted cap can only answer "no cap", which is
    the value that stops the tally and leaves the ability uncapped on every
    board."""
    from engine.activation_restrictions import (
        activations_allowed_each_turn,
        printed_activation_caps,
    )

    line = (
        "{b}: this enchantment deals 1 damage to each creature and each player. "
        "activate no more times each turn than the number of snow swamps you control"
    )

    assert printed_activation_caps(line), "the line is capped"
    assert activations_allowed_each_turn(line) is None, "and not from the text alone"

    game, _p1, wisps = _wisps_board(set_pool, swamps=3)
    assert activations_allowed_each_turn(line, game, 0, wisps) == 3


def test_withering_wisps_sacrifices_itself_on_an_empty_board(set_pool):
    """"At the beginning of the end step, if no creatures are on the
    battlefield, sacrifice this enchantment" — Pestilence's line byte for byte,
    which reached a name-keyed hook and so reached this card not at all."""
    game, p1, wisps = _wisps_board(set_pool, swamps=1)

    game.resolve_end_step(0)
    while game.stack:
        game.resolve_top_of_stack()

    assert wisps not in p1.battlefield


def test_withering_wisps_stays_while_a_creature_is_on_the_battlefield(set_pool):
    """The gate counts the *battlefield*, not the controller's half of it: a
    creature anyone controls keeps the enchantment alive (CR 603.4)."""
    pool = set_pool("ICE")
    game, p1, wisps = _wisps_board(set_pool, swamps=1)
    game.players[1].battlefield.append(_nosick(Permanent(card=pool["Balduvian Bears"])))

    game.resolve_end_step(0)
    while game.stack:
        game.resolve_top_of_stack()

    assert wisps in p1.battlefield


# --- Round 40: an untap block is a noun phrase, not one field per card ---
def _r40_board(set_pool, source_name: str, others):
    board = [Permanent(card=set_pool("ICE")[source_name])]
    board.extend(others)
    p1 = PlayerState(name="P1", battlefield=board, life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    return game, p1


def test_curse_of_marit_lage_taps_every_island_as_it_enters(set_pool):
    """"When this enchantment enters, tap all Islands."

    The sweep's lowering listed the filter fields it honoured — card types,
    supertypes, colours, controller — and a subtype was not among them, so the
    line refused. The check behind that list already asked the right question
    (can the matcher test every key of the payload?); `subtype_filter` is a key
    it tests, through layer 4 like every other computed type.
    """
    island = Permanent(card=set_pool("ICE")["Snow-Covered Island"])
    forest = Permanent(card=set_pool("ICE")["Snow-Covered Forest"])
    game, _p1 = _r40_board(set_pool, "Curse of Marit Lage", [island, forest])

    curse = game.players[0].battlefield[0]
    game._apply_self_enters_battlefield_triggers(0, curse, None, None)
    game.resolve_stack()

    assert island.tapped
    assert not forest.tapped, "the narrowing narrows"


def test_curse_of_marit_lage_keeps_islands_tapped_through_the_untap_step(set_pool):
    """"Islands don't untap during their controllers' untap steps." The block
    used to be readable only for a power threshold, a colour word or the
    literal word "legendary" — three fields, one per card that had been
    printed, all of them read inside a creature-only branch."""
    island = Permanent(card=set_pool("ICE")["Snow-Covered Island"])
    island.tapped = True
    game, _p1 = _r40_board(set_pool, "Curse of Marit Lage", [island])

    game.resolve_untap_step(0)

    assert island.tapped


def test_blizzard_and_energy_storm_actually_hold_fliers_down(set_pool):
    """Both cards report supported since the ingest and both printed
    "Creatures with flying don't untap during their controllers' untap steps"
    into a table that could not read it. The line did nothing, nothing failed,
    and the cards played better than they are printed."""
    from engine.untap_restrictions import untap_restriction_for

    for name in ("Blizzard", "Energy Storm"):
        card = set_pool("ICE")[name]
        restriction = untap_restriction_for(card.oracle_text)

        assert restriction is not None, name
        assert restriction.blocked == {
            "type_filter": "creature", "with_keywords": ["flying"],
        }, name


def test_mudslide_reads_the_complement_of_the_same_phrase(set_pool):
    """"Creatures **without** flying don't untap…" — the polarity is printed
    into the noun phrase, so the same row reads it."""
    from engine.untap_restrictions import untap_restriction_for

    restriction = untap_restriction_for(set_pool("ICE")["Mudslide"].oracle_text)

    assert restriction is not None
    assert restriction.blocked == {
        "type_filter": "creature", "without_keywords": ["flying"],
    }


# --- W1G2: combat relations and end of combat ---
def _w1g2_earthlore(set_pool):
    """Earthlore on a Forest, with an attacker and a blocker in combat."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    forest = _nosick(Permanent(card=pool["Snow-Covered Forest"]))
    earthlore = _nosick(Permanent(card=pool["Earthlore"]))
    blocker = _nosick(Permanent(card=pool["Balduvian Bears"]))
    attacker = _nosick(Permanent(card=pool["Tor Giant"]))
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[forest, earthlore, blocker], life=20)
    game = Game(players=[p1, p2])
    attach_aura(earthlore, forest)

    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], 1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {2: 0})[0]
    return game, forest, earthlore, blocker


def test_earthlore_compiles_its_ability_with_the_cost_it_prints(set_pool):
    """"Tap enchanted land: Target blocking creature gets +1/+2 until end of
    turn. Activate only if enchanted land is untapped."

    Both riders are the point. The cost was read as *nothing* — the ability
    would have been free and repeatable — and the restriction had no row, so
    the effect clause carrying it refused and the Aura was unsupported.
    """
    program = compile_card_oracle(set_pool("ICE")["Earthlore"])

    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.cost.tap_attached is True
    assert ability.cost.requires_tap is False, "the {T} symbol taps the Aura"
    assert ability.instruction.kind == "pump_target_creature_until_eot"


def test_earthlore_taps_the_land_it_enchants_to_pay(set_pool):
    game, forest, earthlore, blocker = _w1g2_earthlore(set_pool)

    result = game.activate_permanent_ability(
        1, "Earthlore",
        target_permanent_ids=[blocker.permanent_id],
    )
    game._settle()

    assert result.supported, result.details
    assert forest.tapped, "the enchanted land pays the cost"
    assert not earthlore.tapped, "the Aura itself is not what is tapped"
    assert (blocker.effective_power, blocker.effective_toughness) == (3, 4)


def test_earthlore_cannot_be_activated_with_the_land_tapped(set_pool):
    """The printed restriction, enforced. Unenforced it is not a dead ability
    but one that works more often than the card allows."""
    game, forest, earthlore, blocker = _w1g2_earthlore(set_pool)
    forest.tapped = True
    before = (blocker.effective_power, blocker.effective_toughness)

    result = game.activate_permanent_ability(
        1, "Earthlore", target_permanent_ids=[blocker.permanent_id],
    )
    game._settle()

    assert not result.supported
    assert (blocker.effective_power, blocker.effective_toughness) == before


def test_earthlore_only_offers_a_blocking_creature(set_pool):
    """"Target **blocking** creature" — the attacker is not a legal target."""
    from engine.targeting import derive_activation_spec

    game, forest, earthlore, blocker = _w1g2_earthlore(set_pool)
    (ability,) = compile_card_oracle(earthlore.card).activated_abilities
    offered = game._enumerate_targets(
        1, earthlore.card, derive_activation_spec(ability), for_cast=False,
        ability_instruction=ability.instruction,
        source_permanent=earthlore, ability_source=earthlore,
    )
    named = {
        game.players[t["seat"]].battlefield[t["index"]].card.name
        for t in offered if t["kind"] == "permanent"
    }

    assert named == {"Balduvian Bears"}, named
# --- end W1G2 ---
# --- W1G5: statics, continuous effects, control changes ---
def _w1g5_brand_board(set_pool, catalog_by_name):
    """Brand of Ill Omen on a creature its **opponent** controls.

    Which is the arrangement the sentence is about: "enchanted creature's
    controller" is the controller of the *creature* (CR 109.5), not of the Aura,
    so the seat the Aura shuts down is not the seat that played it.
    """
    from engine.auras import attach_aura

    bear = catalog_by_name["Grizzly Bears"]
    host = Permanent(card=bear)
    aura = Permanent(card=set_pool("ICE")["Brand of Ill Omen"])
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[host],
            hand=[bear, catalog_by_name["Lightning Bolt"]],
        ),
        PlayerState(name="P2", battlefield=[aura]),
    ])
    game.enforce_mana_costs = False
    attach_aura(aura, host)
    return game, aura


def test_brand_of_ill_omen_compiles_with_both_of_its_lines_claimed(set_pool):
    """Cumulative upkeep is the keyword the engine already implements; the
    second line is the new one. The card was unsupported on that line alone."""
    from engine.auras import aura_controller_cast_ban, unclaimed_aura_lines
    from engine.oracle import normalize_creature_line

    brand = set_pool("ICE")["Brand of Ill Omen"]

    assert compile_card_oracle(brand).supported
    assert unclaimed_aura_lines(
        [normalize_creature_line(line) for line in brand.oracle_text.splitlines()],
        brand.name,
    ) == []
    assert aura_controller_cast_ban(
        "Enchanted creature's controller can't cast creature spells."
    ) == "creature"


def test_brand_of_ill_omen_stops_the_hosts_controller_casting_creatures(
    set_pool, catalog_by_name
):
    """A printed restriction is only done when something enforces it — so this
    asserts the *cast*, not the derivation."""
    game, _ = _w1g5_brand_board(set_pool, catalog_by_name)

    refused = game.cast_from_hand(0, "Grizzly Bears")

    assert not refused.supported
    assert "Brand of Ill Omen" in refused.details


def test_brand_of_ill_omen_leaves_every_other_spell_alone(
    set_pool, catalog_by_name
):
    """The card type is payload, and the ban is exactly the type printed."""
    game, _ = _w1g5_brand_board(set_pool, catalog_by_name)

    assert game.cast_from_hand(0, "Lightning Bolt").supported, game.log


def test_brand_of_ill_omen_stops_banning_when_it_leaves(
    set_pool, catalog_by_name
):
    """The attachment record *is* the restriction: an Aura that is no longer
    attached is no longer asked, so there is nothing to clear."""
    game, aura = _w1g5_brand_board(set_pool, catalog_by_name)
    game._destroy_swept_permanents(game.players[1], lambda perm: perm is aura)

    assert game.cast_from_hand(0, "Grizzly Bears").supported, game.log


def test_brand_of_ill_omen_does_not_touch_the_auras_own_controller(
    set_pool, catalog_by_name
):
    """"Enchanted creature's controller" is one seat, and it is the host's.
    Reading it as the Aura's would shut down the player who cast it."""
    game, _ = _w1g5_brand_board(set_pool, catalog_by_name)
    game.players[1].hand.append(catalog_by_name["Grizzly Bears"])

    assert game.cast_from_hand(1, "Grizzly Bears").supported, game.log


def _w1g5_winds_board(set_pool, catalog_by_name):
    """Freyalise's Winds under P1, with a permanent on each side."""
    winds = Permanent(card=set_pool("ICE")["Freyalise's Winds"])
    mine = Permanent(card=catalog_by_name["Grizzly Bears"])
    theirs = Permanent(card=catalog_by_name["Mountain"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[winds, mine]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    return game, mine, theirs


def _w1g5_tap(game, permanent):
    game.become_tapped(permanent)
    while game.stack:
        game.resolve_top_of_stack()


def test_freyalises_winds_counters_every_permanent_that_taps(
    set_pool, catalog_by_name
):
    """"Whenever **a permanent** becomes tapped" — every one, on either
    battlefield. The trigger read "permanent" as a card type and `has_type`
    answers False for it, so the ability fired on nothing at all."""
    game, mine, theirs = _w1g5_winds_board(set_pool, catalog_by_name)

    _w1g5_tap(game, mine)
    _w1g5_tap(game, theirs)

    assert counters_on(mine, "wind") == 1, game.log
    assert counters_on(theirs, "wind") == 1, game.log


def test_freyalises_winds_spends_a_counter_instead_of_untapping(
    set_pool, catalog_by_name
):
    """CR 614: the second line is a *replacement*, not an untap restriction —
    the permanent stays tapped and the counters go away, so it is free one turn
    later. A row in ``untap_restrictions`` would have locked it forever."""
    game, mine, _ = _w1g5_winds_board(set_pool, catalog_by_name)
    _w1g5_tap(game, mine)

    game.resolve_untap_step(0)
    assert mine.tapped, game.log
    assert counters_on(mine, "wind") == 0, game.log

    game.resolve_untap_step(0)
    assert not mine.tapped, game.log


def test_freyalises_winds_leaves_an_uncountered_permanent_alone(
    set_pool, catalog_by_name
):
    """The replacement's applicability is a *pure* predicate over the counters
    the permanent actually holds, so a permanent that tapped before the Winds
    arrived untaps normally."""
    game, mine, _ = _w1g5_winds_board(set_pool, catalog_by_name)
    mine.tapped = True

    game.resolve_untap_step(0)

    assert not mine.tapped, game.log


def test_freyalises_winds_claims_both_of_its_lines(set_pool):
    """The card compiles supported off its trigger alone, which is exactly the
    shape ``--hollow-lines`` exists to catch: the replacement is claimed by the
    file that implements it, so the second line is not a rider dropped in
    silence."""
    from engine.replacements import counters_instead_of_untap, replacement_claims_line

    winds = set_pool("ICE")["Freyalise's Winds"]
    replacement_line = winds.oracle_text.splitlines()[1]

    assert compile_card_oracle(winds).supported
    assert counters_instead_of_untap(replacement_line) == "wind"
    assert replacement_claims_line(replacement_line)
# --- end W1G5 ---
# --- W1G1: prevention and damage shields ---
def _w1g1_attach(set_pool, aura_name: str):
    """A game with *aura_name* on seat 1 attached to seat 0's creature."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    aura = Permanent(card=pool[aura_name])
    p0 = PlayerState(name="P0", battlefield=[bears], life=20)
    p1 = PlayerState(name="P1", battlefield=[aura], life=20)
    game = Game(players=[p0, p1])
    attach_aura(aura, bears)
    return game, p0, p1, bears, aura


def test_mind_whip_damages_and_taps_when_the_toll_is_not_paid(set_pool):
    """"At the beginning of the upkeep of enchanted creature's controller, that
    player may pay {3}. If they don't, this Aura deals 2 damage to that player
    and you tap that creature."

    Both halves of the penalty, in the branch the card prints them in: the
    conjunct reader used to take "and you" for a second damage recipient, which
    left the tap outside the offer and firing whether the toll was paid or not.
    """
    game, p0, _p1, bears, _whip = _w1g1_attach(set_pool, "Mind Whip")

    game.resolve_upkeep(0)
    game._settle()

    assert p0.life == 18
    assert bears.tapped


def test_mind_whip_offers_the_toll_to_the_creatures_controller(set_pool):
    """"That player" is the enchanted creature's controller, not the Aura's — so
    the decision, and the mana, are theirs."""
    game, p0, _p1, bears, _whip = _w1g1_attach(set_pool, "Mind Whip")
    p0.mana_pool["C"] = 5

    game.resolve_upkeep(0)

    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert len(owed) == 1
    assert owed[0].player_index == 0
    assert owed[0].data["cost"] == {"generic": 3}


def test_errant_minion_reduces_its_damage_by_the_mana_paid(set_pool):
    """"That player may pay any amount of mana. This Aura deals 2 damage to that
    player. Prevent X of that damage, where X is the amount of mana that player
    paid this way."

    Power Leak's sentence one noun over. It was a card hook keyed on Power
    Leak's whole printed line, so this card compiled *supported* with nothing at
    all behind its only ability.
    """
    game, p0, _p1, _bears, _minion = _w1g1_attach(set_pool, "Errant Minion")

    game.resolve_upkeep(0)
    game._settle()

    assert p0.life == 18, "nothing paid, so nothing prevented"


def test_errant_minions_payment_is_capped_at_the_damage(set_pool):
    """"Prevent X of that damage" — X is the mana paid, and there are only two
    points to prevent, so a larger offer spends only what it can use."""
    game, p0, _p1, _bears, _minion = _w1g1_attach(set_pool, "Errant Minion")
    p0.mana_pool["C"] = 5

    game.resolve_upkeep(0, mana_prevention={"Errant Minion": 5})
    game._settle()

    assert p0.life == 20
    assert any("paid 2 mana to prevent 2 damage" in line for line in game.log), (
        "the offer is unbounded, the damage is not — only what it can use is spent"
    )


def test_power_leak_still_reduces_its_damage_after_losing_its_hook(
    set_pool, catalog_by_name
):
    """The card the hook was written for, reading the same production now. Its
    condition names an enchantment rather than a creature, which is the only
    difference between the two printings."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    host = Permanent(card=pool["Errant Minion"])
    leak = Permanent(card=catalog_by_name["Power Leak"])
    p0 = PlayerState(name="P0", battlefield=[host], life=20, mana_pool={"C": 2})
    p1 = PlayerState(name="P1", battlefield=[leak], life=20)
    game = Game(players=[p0, p1])
    attach_aura(leak, host)

    game.resolve_upkeep(0, mana_prevention={"Power Leak": 1})
    game._settle()

    assert p0.life == 19, "one of the two points paid off"


def test_prismatic_ward_prevents_only_the_chosen_colour(set_pool):
    """"As this Aura enters, choose a color. Prevent all damage that would be
    dealt to enchanted creature by sources of the chosen color." (CR 615.9 —
    the recorded property is rechecked when the damage would be dealt.)

    The colour is the **Aura's**, recorded as it entered; the enchanted creature
    has none of its own.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    ward = Permanent(card=pool["Prismatic Ward"])
    red = Permanent(card=pool["Balduvian Barbarians"])
    green = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[bears, ward], life=20)
    p1 = PlayerState(name="P1", battlefield=[red, green], life=20)
    game = Game(players=[p0, p1])
    attach_aura(ward, bears)
    ward.metadata["chosen_color"] = "R"

    game._mark_damage_on_permanent(bears, 3, source=red)
    assert bears.damage_marked == 0

    game._mark_damage_on_permanent(bears, 2, source=green)
    assert bears.damage_marked == 2, "a source of another colour goes through"


def test_prismatic_ward_records_a_colour_as_it_enters(set_pool):
    """"As this **Aura** enters" is the same sentence Psychic Allergy prints
    about an enchantment — the noun is the card's own type word, so the reader
    holds it as data. Spelled out as a literal it read "enchantment" and
    nothing else, and this card reached nothing at all."""
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    red = Permanent(card=pool["Balduvian Barbarians"])
    p0 = PlayerState(
        name="P0", battlefield=[bears], hand=[pool["Prismatic Ward"]], life=20
    )
    p1 = PlayerState(name="P1", battlefield=[red], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(
        0, "Prismatic Ward", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    ward = next(p for p in p0.battlefield if p.card.name == "Prismatic Ward")
    assert ward.metadata["chosen_color"] == "R", (
        "the default names the colour the opponents hold most of"
    )
    assert ward.metadata["attached_to"] is bears


def test_a_ward_that_recorded_no_colour_shields_nothing(set_pool):
    """A property nobody recorded is not a property CR 615.9 can recheck, so the
    shield names no source — the opposite of the widest reading, which would
    stop every point of damage in the game."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    ward = Permanent(card=pool["Prismatic Ward"])
    red = Permanent(card=pool["Balduvian Barbarians"])
    p0 = PlayerState(name="P0", battlefield=[bears, ward], life=20)
    p1 = PlayerState(name="P1", battlefield=[red], life=20)
    game = Game(players=[p0, p1])
    attach_aura(ward, bears)
    ward.metadata.pop("chosen_color", None)

    game._mark_damage_on_permanent(bears, 3, source=red)

    assert bears.damage_marked == 3


def test_energy_storm_stops_a_burn_spell_but_not_a_creature(set_pool, catalog_by_name):
    """"Prevent all damage that would be dealt by instant and sorcery spells."

    A silent mis-play until now: the card reported *supported* on its cumulative
    upkeep and its untap restriction while this line did nothing at all — the
    census cannot see it, because a card is supported when any of its lines is.

    A permanent is not a spell however it is dealing the damage (CR 111.1), so
    the second half is the half that says the shield reads the source's kind
    rather than shielding everything.
    """
    pool = set_pool("ICE")
    storm = Permanent(card=pool["Energy Storm"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(
        name="P0", battlefield=[storm, bears], life=20,
        hand=[catalog_by_name["Lightning Bolt"]],
    )
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    game._settle()
    assert p1.life == 20

    game._deal_damage_to_player(p1, 2, source=bears)
    assert p1.life == 18


def test_energy_storm_covers_the_table_not_its_controller(set_pool, catalog_by_name):
    """The sentence names no recipient, so an opponent's Energy Storm shields
    this damage exactly as your own would — the scan is over every battlefield
    rather than the recipient's."""
    pool = set_pool("ICE")
    storm = Permanent(card=pool["Energy Storm"])
    p0 = PlayerState(
        name="P0", life=20, hand=[catalog_by_name["Lightning Bolt"]]
    )
    p1 = PlayerState(name="P1", battlefield=[storm], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    game._settle()

    assert p0.life == 20


def test_chromatic_armor_enters_with_a_counter_and_a_colour(set_pool):
    """Four printed lines and all four read: the enter-time colour, the sleight
    counter it enters with, the shield keyed to that colour, and the {X}
    ability that re-chooses."""
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    red = Permanent(card=pool["Balduvian Barbarians"])
    p0 = PlayerState(
        name="P0", battlefield=[bears], hand=[pool["Chromatic Armor"]], life=20
    )
    p1 = PlayerState(name="P1", battlefield=[red], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False

    assert game.cast_from_hand(
        0, "Chromatic Armor", target_player_index=0, target_permanent_index=0
    ).supported
    game._settle()

    armor = next(p for p in p0.battlefield if p.card.name == "Chromatic Armor")
    assert counters_on(armor, "sleight") == 1
    assert armor.metadata["chosen_color"] == "R"

    game._mark_damage_on_permanent(bears, 2, source=red)
    assert bears.damage_marked == 0, "the last chosen colour is the one recorded"


def test_chromatic_armors_x_is_the_counters_on_it(set_pool):
    """"X is the number of sleight counters on this **Aura**." The cost is one
    the board decides, not one the activator announces (CR 601.2b's exception)
    — and the noun the card calls itself by is data: the reader listed the card
    types and this printing reached nothing at all."""
    from engine.auras import attach_aura
    from engine.named_counters import add_counters

    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    armor = Permanent(card=pool["Chromatic Armor"])
    p0 = PlayerState(name="P0", battlefield=[bears, armor], life=20, mana_pool={"C": 1})
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = True
    attach_aura(armor, bears)
    add_counters(armor, "sleight", 3)

    refused = game.activate_permanent_ability(0, "Chromatic Armor", permanent_index=1)
    assert not refused.supported, "one mana cannot pay {X} where X is three"
    assert counters_on(armor, "sleight") == 3

    p0.mana_pool["C"] = 3
    allowed = game.activate_permanent_ability(0, "Chromatic Armor", permanent_index=1)
    game._settle()

    assert allowed.supported, allowed.details
    assert counters_on(armor, "sleight") == 4
    assert p0.mana_pool["C"] == 0


def test_chromatic_armors_ability_records_a_new_colour(set_pool):
    """"…and choose a color." The re-choice writes the same metadata key the
    entry state does — two keys would be a permanent with two chosen colours
    and a shield reading whichever one its author remembered."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    armor = Permanent(card=pool["Chromatic Armor"])
    green = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[bears, armor], life=20)
    p1 = PlayerState(name="P1", battlefield=[green], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    attach_aura(armor, bears)
    armor.metadata["chosen_color"] = "R"

    assert game.activate_permanent_ability(
        0, "Chromatic Armor", permanent_index=1
    ).supported
    game._settle()

    assert armor.metadata["chosen_color"] == "G", (
        "the default names the colour the opponents hold most of"
    )
    game._mark_damage_on_permanent(bears, 2, source=green)
    assert bears.damage_marked == 0
# --- end W1G1 ---


# --- W1G4: library, hand and graveyard ---
def _renewal_board(set_pool, library, opponent_library=()):
    pool = set_pool("ICE")
    renewal = Permanent(card=pool["Enduring Renewal"])
    p1 = PlayerState(
        name="P1", battlefield=[renewal],
        library=[pool[name] for name in library], life=20,
    )
    p2 = PlayerState(
        name="P2", library=[pool[name] for name in opponent_library], life=20
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    return pool, p1, p2, game


def test_enduring_renewal_bins_a_drawn_creature_card(set_pool):
    """"If you would draw a card, reveal the top card of your library instead.
    If it's a creature card, put it into your graveyard. Otherwise, draw a
    card." — CR 614, one draw at a time."""
    pool, p1, p2, game = _renewal_board(set_pool, ["Balduvian Bears", "Dark Ritual"])

    drawn = game._draw_with_replacements(p1, 1)

    assert drawn == 0, "the draw was replaced, not made"
    assert p1.hand == []
    assert [card.name for card in p1.graveyard] == ["Balduvian Bears"]
    assert [card.name for card in p1.library] == ["Dark Ritual"]


def test_enduring_renewal_draws_a_noncreature_card(set_pool):
    """"Otherwise, draw a card." — a new draw of the card just revealed, which
    is why it must not replace itself into a loop (CR 614.5)."""
    pool, p1, p2, game = _renewal_board(set_pool, ["Dark Ritual", "Balduvian Bears"])

    drawn = game._draw_with_replacements(p1, 1)

    assert drawn == 1
    assert [card.name for card in p1.hand] == ["Dark Ritual"]
    assert p1.graveyard == []


def test_enduring_renewal_replaces_each_draw_of_a_multi_card_draw(set_pool):
    """CR 121.2: "draw two cards" is two draws, each replaceable on its own."""
    pool, p1, p2, game = _renewal_board(
        set_pool, ["Balduvian Bears", "Dark Ritual", "Brown Ouphe"]
    )

    game._draw_with_replacements(p1, 2)

    assert [card.name for card in p1.graveyard] == ["Balduvian Bears"]
    assert [card.name for card in p1.hand] == ["Dark Ritual"]
    assert [card.name for card in p1.library] == ["Brown Ouphe"]


def test_enduring_renewal_does_not_replace_an_opponents_draw(set_pool):
    """"If **you** would draw a card" — the controller's own draws. A scan over
    every board would make a one-sided drawback symmetric."""
    pool, p1, p2, game = _renewal_board(
        set_pool, ["Dark Ritual"], opponent_library=["Balduvian Bears"]
    )

    drawn = game._draw_with_replacements(p2, 1)

    assert drawn == 1
    assert [card.name for card in p2.hand] == ["Balduvian Bears"]
    assert p2.graveyard == []


def test_enduring_renewal_returns_a_dead_creature_to_hand(set_pool):
    """"Whenever a creature is put into your graveyard from the battlefield,
    return it to your hand." — the loop the card is famous for: the creature
    comes back, and drawing it again bins it again."""
    pool, p1, p2, game = _renewal_board(set_pool, [])
    # Through the entry point, not by appending: CR 404.1 sends a permanent to
    # its *owner's* graveyard, and the owner is recorded as it enters.
    bear = Permanent(card=pool["Balduvian Bears"])
    game._put_permanent_onto_battlefield(0, bear, None)

    game.sacrifice_permanent(bear)
    game._settle()

    assert [card.name for card in p1.hand] == ["Balduvian Bears"]
    assert not any(c.name == "Balduvian Bears" for c in p1.graveyard)


def test_enduring_renewal_ignores_a_creature_dying_under_the_opponent(set_pool):
    """"…into **your** graveyard" — CR 404.1 sends a permanent to its owner's
    graveyard, so whose graveyard it landed in is a question about the owner
    and not about who controlled it. Dropping the word would hand this seat
    every creature that dies."""
    pool, p1, p2, game = _renewal_board(set_pool, [])
    theirs = Permanent(card=pool["Balduvian Bears"])
    game._put_permanent_onto_battlefield(1, theirs, None)

    game.sacrifice_permanent(theirs)
    game._settle()

    assert p1.hand == []
    assert [card.name for card in p2.graveyard] == ["Balduvian Bears"]


def test_enduring_renewal_reveals_only_its_controllers_hand(set_pool):
    """"Play with **your** hand revealed" is one seat's, where Revelation's
    "Players play with their hands revealed" is everyone's."""
    from engine.revealed_hands import hand_revealed_to

    pool, p1, p2, game = _renewal_board(set_pool, [])

    assert hand_revealed_to(game, owner_seat=0, viewer_seat=1)
    assert not hand_revealed_to(game, owner_seat=1, viewer_seat=0)
def _necro_board(set_pool, library=(), hand=()):
    pool = set_pool("ICE")
    necro = Permanent(card=pool["Necropotence"])
    p1 = PlayerState(
        name="P1",
        library=[pool[name] for name in library],
        hand=[pool[name] for name in hand],
        life=20,
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    # Past the first turn, whose draw step CR 103.8a skips anyway.
    game.turn = 3
    game._put_permanent_onto_battlefield(0, necro, None)
    return pool, p1, p2, game


def test_necropotence_skips_its_controllers_draw_step(set_pool):
    """"Skip your draw step." — CR 614.10's mandatory skip, which is not the
    optional one beside it in the table: nothing is offered and nothing is
    bought."""
    pool, p1, p2, game = _necro_board(set_pool, library=["Balduvian Bears"])

    drawn = game.resolve_draw_step(0)

    assert drawn == 0
    assert p1.hand == []
    assert [card.name for card in p1.library] == ["Balduvian Bears"]


def test_necropotence_does_not_skip_the_opponents_draw_step(set_pool):
    """"**Your** draw step" — the controller's own, so a scan over every seat
    would turn a one-sided drawback into a Stasis."""
    pool, p1, p2, game = _necro_board(set_pool)
    p2.library = [pool["Balduvian Bears"]]

    drawn = game.resolve_draw_step(1)

    assert drawn == 1
    assert [card.name for card in p2.hand] == ["Balduvian Bears"]


def test_necropotence_exiles_what_its_controller_discards(set_pool):
    """"Whenever you discard a card, exile that card from your graveyard."

    CR 701.9a's discard is an action abilities watch, and the card is located
    by identity: a graveyard is a list of card definitions and two copies of a
    card are the same object.
    """
    pool, p1, p2, game = _necro_board(set_pool, hand=["Balduvian Bears"])
    discarded = p1.hand[0]
    assert game.take_card_from_hand(p1, discarded)

    game._discard_card(p1, discarded)
    game._settle()

    assert p1.graveyard == []
    assert [card.name for card in p1.exile] == ["Balduvian Bears"]


def test_necropotence_ignores_an_opponents_discard(set_pool):
    """"…**you** discard a card" is CR 109.5's answer: the ability's
    controller. An opponent's discard stays in their graveyard."""
    pool, p1, p2, game = _necro_board(set_pool)
    theirs = pool["Balduvian Bears"]
    p2.hand.append(theirs)
    assert game.take_card_from_hand(p2, theirs)

    game._discard_card(p2, theirs)
    game._settle()

    assert [card.name for card in p2.graveyard] == ["Balduvian Bears"]
    assert p2.exile == []


def test_necropotence_pays_life_and_returns_the_card_at_its_next_end_step(set_pool):
    """"Pay 1 life: Exile the top card of your library face down. Put that card
    into your hand at the beginning of your next end step."

    Two steps and a delay: the exile is now, the hand is a delayed triggered
    ability (CR 603.7) that reads what this resolution recorded (CR 603.7d).
    """
    pool, p1, p2, game = _necro_board(set_pool, library=["Balduvian Bears", "Brown Ouphe"])

    result = game.activate_permanent_ability(0, "Necropotence")
    assert result.supported, result.details
    game._settle()

    assert p1.life == 19, "the life is the cost"
    assert [card.name for card in p1.exile] == ["Balduvian Bears"]
    assert p1.hand == [], "not yet — the card comes back at the end step"

    # An opponent's end step is not this seat's.
    game.resolve_end_step(1)
    game._settle()
    assert p1.hand == []

    game.resolve_end_step(0)
    game._settle()

    assert [card.name for card in p1.hand] == ["Balduvian Bears"]
    assert p1.exile == []
# --- end W1G4 ---


# --- W2G1: pay-or-consequence tolls ---
def test_cold_snap_damages_each_player_for_their_own_snow_lands(set_pool):
    """"At the beginning of each player's upkeep, this enchantment deals damage
    to that player equal to the number of snow lands they control."

    Recipient and counted board are the *same* frozen seat (CR 603.10), which
    is what separates this from Typhoon's per-seat loop: one number, taken on
    the player whose upkeep it is.
    """
    pool = set_pool("ICE")
    snap = Permanent(card=pool["Cold Snap"])
    p0 = PlayerState(name="P0", battlefield=[snap], life=20)
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=pool["Snow-Covered Plains"]),
            Permanent(card=pool["Snow-Covered Island"]),
        ],
        life=20,
    )
    game = Game(players=[p0, p1])
    game.active_player_index = 1

    game.resolve_upkeep(1)
    game._settle()

    assert p1.life == 18, "two snow lands, two damage"
    assert p0.life == 20, "it is not their upkeep"


def test_cold_snap_counts_only_snow_lands(set_pool):
    """A plain land is not a snow land, so it is not counted."""
    pool = set_pool("ICE")
    snap = Permanent(card=pool["Cold Snap"])
    p0 = PlayerState(
        name="P0",
        battlefield=[snap, Permanent(card=pool["Snow-Covered Swamp"])],
        life=20,
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Ice Floe"])], life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 1

    game.resolve_upkeep(1)
    game._settle()

    assert p1.life == 20, "Ice Floe is a land, but not a snow one"
    assert p0.life == 20


def test_a_permanents_second_upkeep_trigger_survives_the_first(set_pool):
    """CR 603.3: *every* ability that triggered goes on the stack.

    Cold Snap prints cumulative upkeep first and "each player's upkeep" second.
    The upkeep loop broke out of a permanent's ability list the moment it saw a
    "your upkeep" condition on somebody else's turn, so the second ability was
    never reached - the enchantment dealt nobody damage on any turn but its
    controller's while reporting itself supported. Maddening Wind prints the
    same pair and lost its damage the same way.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    wind = Permanent(card=pool["Maddening Wind"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[wind], life=20)
    p1 = PlayerState(name="P1", battlefield=[bears], life=20)
    game = Game(players=[p0, p1])
    attach_aura(wind, bears)
    game.active_player_index = 1

    game.resolve_upkeep(1)
    game._settle()

    assert p1.life == 18, "the Aura's second trigger fires on the host's upkeep"


def test_icy_prison_offers_the_toll_to_every_seat(set_pool):
    """"At the beginning of your upkeep, sacrifice this enchantment unless any
    player pays {3}."

    "Any player" is the whole table, the controller included - one offer the
    first acceptance ends (CR 601.2b), not one prompt per seat.
    """
    pool = set_pool("ICE")
    prison = Permanent(card=pool["Icy Prison"])
    p0 = PlayerState(name="P0", battlefield=[prison], life=20)
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 0

    game.resolve_upkeep(0)
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert not game.is_on_battlefield(prison), "nobody paid, so it is sacrificed"


def test_icy_prison_asks_the_next_seat_when_one_declines(set_pool):
    """The chain, not a batch: the controller is asked first (CR 101.4), and a
    decline moves the offer on rather than sacrificing the enchantment. Any one
    payment keeps it, and nobody after the payer is asked (CR 601.2b)."""
    pool = set_pool("ICE")
    prison = Permanent(card=pool["Icy Prison"])
    lands = [Permanent(card=pool["Snow-Covered Island"]) for _ in range(3)]
    p0 = PlayerState(name="P0", battlefield=[prison], life=20)
    p1 = PlayerState(name="P1", battlefield=lands, life=20)
    game = Game(players=[p0, p1])
    game.active_player_index = 0

    game.resolve_upkeep(0)
    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert [c.player_index for c in owed] == [0], "the controller is asked first"

    assert game.confirm_optional_pay(0, accept=False)
    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert [c.player_index for c in owed] == [1], "and the offer moves on"

    assert game.confirm_optional_pay(1, accept=True)
    game._settle()

    assert game.is_on_battlefield(prison), "an opponent bought it off"
    assert all(land.tapped for land in lands), "the {3} came off the board"


def test_earthlink_makes_the_dead_creatures_controller_sacrifice_a_land(set_pool):
    """"Whenever a creature dies, that creature's controller sacrifices a land
    of their choice."

    The seat is the one that controlled the creature that died - frozen by the
    fire site, because a graveyard card cannot say whose battlefield it left.
    """
    pool = set_pool("ICE")
    link = Permanent(card=pool["Earthlink"])
    bears = Permanent(card=pool["Balduvian Bears"])
    p0 = PlayerState(name="P0", battlefield=[link], life=20)
    p1 = PlayerState(
        name="P1",
        battlefield=[bears, Permanent(card=pool["Snow-Covered Forest"])],
        life=20,
    )
    game = Game(players=[p0, p1])

    game._destroy_target_permanent(p1, target_permanent_index=p1.battlefield.index(bears))
    game._settle()

    assert [c.name for c in p1.graveyard] == ["Balduvian Bears", "Snow-Covered Forest"]
    assert p0.battlefield == [link], "the Earthlink controller gives up nothing"


def test_mystic_remora_lets_the_caster_buy_off_the_draw(set_pool):
    """"Whenever an opponent casts a noncreature spell, you may draw a card
    unless that player pays {4}."

    The decision belongs to the caster, not to Remora's controller: the offer
    is theirs and the draw is the branch they decline into.
    """
    pool = set_pool("ICE")
    remora = Permanent(card=pool["Mystic Remora"])
    p0 = PlayerState(
        name="P0", battlefield=[remora], life=20,
        library=[pool["Balduvian Bears"], pool["Brown Ouphe"]],
    )
    p1 = PlayerState(name="P1", hand=[pool["Icy Prison"]], life=20)
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Icy Prison")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert len(p0.hand) == 1, "the toll went unpaid, so the card is drawn"


def test_mystic_remora_ignores_a_creature_spell(set_pool):
    """"a **noncreature** spell" - the narrowing the opponent-scoped cast head
    could not read at all until this round, which stranded the whole line."""
    pool = set_pool("ICE")
    remora = Permanent(card=pool["Mystic Remora"])
    p0 = PlayerState(
        name="P0", battlefield=[remora], life=20,
        library=[pool["Balduvian Bears"]],
    )
    p1 = PlayerState(name="P1", hand=[pool["Balduvian Bears"]], life=20)
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Balduvian Bears")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert p0.hand == []


def test_freyalise_charm_draws_when_the_controller_pays(set_pool):
    """"Whenever an opponent casts a black spell, you may pay {G}{G}. If you do,
    you draw a card."

    The colour narrowing was tested in one of the two cast dispatchers, so the
    opponent-scoped spelling had no colour test at all.
    """
    pool = set_pool("ICE")
    charm = Permanent(card=pool["Freyalise's Charm"])
    p0 = PlayerState(
        name="P0", battlefield=[charm], life=20, mana_pool={"G": 2},
        library=[pool["Balduvian Bears"]],
    )
    p1 = PlayerState(name="P1", hand=[pool["Dark Ritual"]], life=20)
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Dark Ritual")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert len(p0.hand) == 1
    assert p0.mana_pool.get("G", 0) == 0


def test_freyalise_charm_ignores_a_spell_of_another_colour(set_pool):
    pool = set_pool("ICE")
    charm = Permanent(card=pool["Freyalise's Charm"])
    p0 = PlayerState(
        name="P0", battlefield=[charm], life=20, mana_pool={"G": 2},
        library=[pool["Balduvian Bears"]],
    )
    p1 = PlayerState(name="P1", hand=[pool["Icy Prison"]], life=20)   # blue
    game = Game(players=[p0, p1])

    game.cast_from_hand(1, "Icy Prison")
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert p0.hand == []
    assert p0.mana_pool.get("G", 0) == 2, "nothing was offered, so nothing was paid"
# --- end W2G1 ---

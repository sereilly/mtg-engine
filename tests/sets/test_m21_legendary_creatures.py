"""Core Set 2021 (M21) legendary creatures.

Split out of ``test_m21_creatures.py`` when that file reached the size guard in
``tests/engine/test_set_test_convention.py``. The axis is the one the convention
names — the **printed type** of the card each test is about — taken one step
further into the type line: "Legendary Creature — Vampire Cleric" is a supertype
plus a card type (CR 205.4a), and M21 prints eleven of them, so this is a
division the set keeps filling rather than a bucket invented to make a number go
down. Only four are supported today; the other seven land here as they arrive,
and so will the "legend rule reads the printed name" work (ROADMAP round 49),
since every legendary creature in the pool is M21's.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- Barrin, Tolarian Archmage: a bounce, and the history it feeds ----------


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


# --- Azusa, Kaervek, Vito ---------------------------------------------------


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


# --- Round 100: a base P/T set over a whole team ----------------------------


def _jolrael_board(set_pool, hand=("Shock", "Island", "Forest")):
    pool = set_pool("M21")
    jolrael = _nosick(Permanent(card=pool["Jolrael, Mwonvuli Recluse"]))
    friend = _nosick(Permanent(card=pool["Gale Swooper"]))
    p1 = PlayerState(
        name="P1", battlefield=[jolrael, friend],
        hand=[pool[name] for name in hand],
    )
    theirs = Permanent(card=pool["Alpine Watchdog"])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, jolrael, friend, theirs


def test_jolrael_compiles_supported(set_pool):
    """A sweep rather than a target, so it is its own instruction kind: the
    targeted base-P/T handler asks a picker *which* permanent, and this one asks
    the board *which permanents*."""
    program = compile_card_oracle(set_pool("M21")["Jolrael, Mwonvuli Recluse"])
    assert program.supported, program.reason

    (ability,) = program.activated_abilities
    assert ability.instruction.kind == "set_team_base_pt_until_eot"


def test_every_creature_you_control_takes_the_new_base(set_pool):
    game, _p1, jolrael, friend, theirs = _jolrael_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Jolrael, Mwonvuli Recluse", permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    assert (jolrael.effective_power, jolrael.effective_toughness) == (3, 3)
    assert (friend.effective_power, friend.effective_toughness) == (3, 3)


def test_the_opponents_creatures_are_untouched(set_pool):
    game, _p1, _jolrael, _friend, theirs = _jolrael_board(set_pool)

    game.activate_permanent_ability(0, "Jolrael, Mwonvuli Recluse", permanent_index=0)
    game._settle()

    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)


def test_x_is_fixed_as_the_ability_resolves(set_pool):
    """CR 608.2: the value is calculated on resolution and does not track the
    hand afterwards. Drawing later in the turn does not grow the team — which is
    exactly what a continuous recompute of the count would have said."""
    game, p1, jolrael, _friend, _theirs = _jolrael_board(set_pool)
    game.activate_permanent_ability(0, "Jolrael, Mwonvuli Recluse", permanent_index=0)
    game._settle()

    p1.hand.append(set_pool("M21")["Mountain"])
    game._recompute_continuous_effects()

    assert (jolrael.effective_power, jolrael.effective_toughness) == (3, 3)


def test_the_base_reverts_at_cleanup(set_pool):
    game, _p1, jolrael, friend, _theirs = _jolrael_board(set_pool)
    game.activate_permanent_ability(0, "Jolrael, Mwonvuli Recluse", permanent_index=0)
    game._settle()

    game.resolve_cleanup_step(0)

    assert (jolrael.effective_power, jolrael.effective_toughness) == (1, 2)
    assert (friend.effective_power, friend.effective_toughness) == (3, 2)


def test_a_team_set_that_names_only_one_characteristic_refuses(set_pool):
    """The handler writes both. "Creatures you control have base power 0" would
    leave toughness tracking whatever else applies, which is a different effect
    and one nothing here performs."""
    from engine.grammar import compile_line

    result = compile_line(
        "Until end of turn, creatures you control have base power 0."
    )

    assert not result.lowered


# --- Niambi, Esteemed Speaker: a supertype is a restriction (round 108) -----


def _niambi_board(set_pool, hand=(), library_size=6):
    pool = set_pool("M21")
    niambi = Permanent(card=pool["Niambi, Esteemed Speaker"])
    p1 = PlayerState(
        name="P1", hand=list(hand), life=20,
        library=[pool["Mountain"]] * library_size,
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, niambi, None)
    _nosick(niambi)
    return game, p1, niambi


def test_niambi_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Niambi, Esteemed Speaker"])
    assert program.supported, program.reason


def test_niambi_gains_life_equal_to_the_returned_creatures_mana_value(set_pool):
    """"That creature's mana value" is a third referent, distinct from "its
    power" (the preceding step's object, computed by a fused handler) and from
    "that creature's power" (the trigger *event's* object). Here it is the
    creature the bounce in the same resolution returned — which by the time the
    life gain runs is a card in a hand, so the bounce has to have recorded the
    number (CR 202.3: mana value is read off the printed cost, and CR 400.7
    makes the card in the hand a new object)."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Niambi, Esteemed Speaker"]], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    # {3}{W}{W} - mana value 5, which is the number the life gain has to find.
    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Baneslayer Angel"]), None
    )

    game.cast_from_hand(
        0, "Niambi, Esteemed Speaker",
        target_player_index=0, target_permanent_index=0,
    )
    game._settle()
    game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert [c.name for c in p1.hand] == ["Baneslayer Angel"]
    assert p1.life == 25


def test_niambi_cannot_bounce_a_creature_you_do_not_control(set_pool):
    """"another target creature **you control**" — a controller narrowing the
    bounce path refused outright until this round, because its handler read no
    filter that could carry one. Refused rather than widened: a bounce that
    ignored the phrase would hand Niambi an opponent's blocker."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Niambi, Esteemed Speaker"]], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, Permanent(card=pool["Baneslayer Angel"]), None)

    game.cast_from_hand(
        0, "Niambi, Esteemed Speaker",
        target_player_index=1, target_permanent_index=0,
    )
    game._settle()
    # The trigger really did offer, and the offer really was accepted. Without
    # this the assertions below hold vacuously on any engine where the card is
    # unsupported and nothing fires at all.
    assert game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert [p.card.name for p in game.controlled_by(1)] == ["Baneslayer Angel"]
    assert p1.life == 20


def test_niambi_discards_the_legendary_card_and_not_another(set_pool):
    """The cost names what pays it. The hand holds three cards and exactly one
    answers the phrase, so the deterministic pick is that one — not hand
    position zero, which is what a dropped narrowing would take."""
    pool = set_pool("M21")
    game, p1, niambi = _niambi_board(
        set_pool,
        hand=[pool["Alpine Watchdog"], pool["Gadrak, the Crown-Scourge"], pool["Mountain"]],
    )

    result = game.activate_permanent_ability(0, "Niambi, Esteemed Speaker")
    game._settle()

    assert result.supported, result.details
    assert [c.name for c in p1.graveyard] == ["Gadrak, the Crown-Scourge"]
    assert niambi.tapped
    # Two drawn, one legendary card gone, the other two untouched.
    assert [c.name for c in p1.hand] == ["Alpine Watchdog", "Mountain", "Mountain", "Mountain"]


def test_niambi_cannot_activate_with_no_legendary_card_in_hand(set_pool):
    """CR 602.5c: an unpayable cost makes the ability unactivatable, not free.
    A hand of two cards is not "not enough cards" — the shortfall is the phrase,
    and the message says so."""
    pool = set_pool("M21")
    game, p1, niambi = _niambi_board(
        set_pool, hand=[pool["Alpine Watchdog"], pool["Mountain"]],
    )

    result = game.activate_permanent_ability(0, "Niambi, Esteemed Speaker")
    game._settle()

    assert not result.supported
    assert "no card in hand answers this cost" in result.details
    assert [c.name for c in p1.hand] == ["Alpine Watchdog", "Mountain"]
    assert not niambi.tapped
    assert p1.graveyard == []


# --- Rin and Seri: a cast trigger narrowed by tribe (round 116) -------------


def _rin_board(set_pool, hand=(), extra=()):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, hand=[pool[name] for name in hand])
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    rin = Permanent(card=pool["Rin and Seri, Inseparable"])
    game._put_permanent_onto_battlefield(0, rin, None)
    _nosick(rin)
    for name in extra:
        game._put_permanent_onto_battlefield(0, Permanent(card=pool[name]), None)
    return game, p1, pool


def test_rin_and_seri_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Rin and Seri, Inseparable"])
    assert program.supported, program.reason


def test_casting_a_dog_spell_makes_a_cat_and_a_cat_spell_makes_a_dog(set_pool):
    """A creature *subtype* narrowing on a cast trigger. The table narrowed by
    card type and explicitly refused a subtype, because the word list was
    exactly what the event filter tested — a subtype admitted there would have
    been dropped and the trigger would have fired on every spell."""
    game, _, _ = _rin_board(
        set_pool, hand=["Alpine Watchdog", "Pridemalkin", "Mountain"],
    )

    game.cast_from_hand(0, "Alpine Watchdog")
    game._settle()
    assert "Cat Token" in [p.card.name for p in game.controlled_by(0)]
    assert "Dog Token" not in [p.card.name for p in game.controlled_by(0)]

    game.cast_from_hand(0, "Pridemalkin")
    game._settle()
    assert "Dog Token" in [p.card.name for p in game.controlled_by(0)]


def test_casting_a_spell_of_neither_tribe_makes_nothing(set_pool):
    game, _, _ = _rin_board(set_pool, hand=["Mountain", "Alpine Watchdog"])
    before = sorted(p.card.name for p in game.controlled_by(0))

    game.cast_from_hand(0, "Mountain")
    game._settle()

    assert sorted(p.card.name for p in game.controlled_by(0)) == sorted(
        before + ["Mountain"]
    )
    # The control: a Dog spell on the same board *does* make a token. Without it
    # this holds on any engine where the card is unsupported and no trigger
    # fires at all.
    game.cast_from_hand(0, "Alpine Watchdog")
    game._settle()
    assert "Cat Token" in [p.card.name for p in game.controlled_by(0)]


def test_the_cast_narrowing_carries_the_subtype(set_pool):
    """The narrowing has to survive into the condition payload, because that is
    what the event filter tests. A subtype the table consumed and did not record
    would be a trigger that fires on every spell — which is precisely why the
    table refused a subtype until the filter could test one."""
    pool = set_pool("M21")
    program = compile_card_oracle(pool["Rin and Seri, Inseparable"])

    narrowings = sorted(
        t.condition.payload.get("cast_subtype") for t in program.triggered_abilities
    )
    assert narrowings == ["cat", "dog"]
    assert all(t.supported for t in program.triggered_abilities)


def test_the_subtype_is_read_off_the_printed_subtype_not_the_type_line(set_pool):
    """A substring search of the type line would let a tribe answer for a longer
    word, and would let a card *type* answer a tribe — which is the type
    narrowing's job, one row above. The filter asks the same printed-subtype
    reader the layer seed uses."""
    from engine.layer_bridge import printed_shape

    pool = set_pool("M21")
    _, dog = printed_shape(pool["Alpine Watchdog"])
    _, cat = printed_shape(pool["Pridemalkin"])
    _, land = printed_shape(pool["Mountain"])

    assert "dog" in dog and "dog" not in cat and "dog" not in land
    assert "cat" in cat and "cat" not in dog


def test_rin_and_seri_counts_each_tribe_separately(set_pool):
    """Two steps of one ability, each with its own count. Rin and Seri is a Dog
    Cat, so it answers both — three Dogs and two Cats on this board."""
    game, p1, _ = _rin_board(
        set_pool, extra=["Alpine Watchdog", "Bolt Hound", "Pridemalkin"],
    )
    opponent = game.players[1]

    result = game.activate_permanent_ability(
        0, "Rin and Seri, Inseparable", target_player_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert opponent.life == 17
    assert p1.life == 22


def test_a_counted_damage_goes_through_the_one_evaluator(set_pool):
    """The general form. Karma's fused kind stays, because its *recipient* is
    the upkeep's player rather than a chosen target — a shape this cannot
    express."""
    from engine.grammar import compile_line

    compiled = compile_line(
        "This creature deals damage to any target equal to the number of Dogs "
        "you control."
    )
    (instruction,) = compiled.instructions

    assert instruction.kind == "deal_damage"
    assert instruction.payload["x_from_count"] == {
        "zone": "battlefield", "owner": "you",
        "filter": {"type_filter": "creature", "subtype_filter": "dog"},
    }


# --- Subira: a delayed trigger with a narrowed subject (round 119) ----------


def _subira_board(set_pool, hand=("Mountain",)):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", life=20, hand=[pool[n] for n in hand],
        library=[pool["Island"]] * 8,
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    subira = Permanent(card=pool["Subira, Tulzidi Caravanner"])
    small = Permanent(card=pool["Alpine Watchdog"])      # 2/2 — power 2, matches
    big = Permanent(card=pool["Baneslayer Angel"])       # 5/5 — does not
    for perm in (subira, small, big):
        game._put_permanent_onto_battlefield(0, perm, None)
        _nosick(perm)
    game.active_player_index = 0
    return game, p1


def _swing(game):
    game._set_phase_and_step("combat", "beginning_of_combat")
    game.advance_combat_phase()
    game.declare_attackers(0, [1, 2])
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.advance_combat_phase()
    game.resolve_combat_damage(0)
    game._settle()


def test_subira_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Subira, Tulzidi Caravanner"])
    assert program.supported, program.reason


def test_discarding_your_hand_is_a_cost_with_nothing_to_choose(set_pool):
    """Not a count of "discard a card": there is no card for the payer to name
    and no filter to narrow, and CR 601.2h still makes it payable with an empty
    hand — discarding nothing is discarding your hand."""
    game, p1 = _subira_board(set_pool, hand=("Mountain", "Island"))

    result = game.activate_permanent_ability(
        0, "Subira, Tulzidi Caravanner", ability_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert p1.hand == []
    assert sorted(c.name for c in p1.graveyard) == ["Island", "Mountain"]


def test_an_empty_hand_still_pays(set_pool):
    game, p1 = _subira_board(set_pool, hand=())

    result = game.activate_permanent_ability(
        0, "Subira, Tulzidi Caravanner", ability_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert game.delayed_triggers


def test_the_delayed_trigger_fires_only_for_the_creatures_it_names(set_pool):
    """"Until end of turn, whenever a creature you control **with power 2 or
    less** deals combat damage to a player, draw a card." Both creatures
    connect; only the 2/2 answers the filter, so exactly one card is drawn."""
    game, p1 = _subira_board(set_pool)

    game.activate_permanent_ability(
        0, "Subira, Tulzidi Caravanner", ability_index=1,
    )
    game._settle()
    _swing(game)

    assert game.players[1].life == 13, "both creatures connected"
    assert [c.name for c in p1.hand] == ["Island"]


def test_without_the_activation_nothing_is_drawn(set_pool):
    game, p1 = _subira_board(set_pool)

    _swing(game)

    assert game.players[1].life == 13
    assert [c.name for c in p1.hand] == ["Mountain"]


def test_a_delayed_trigger_whose_event_has_no_fire_site_refuses(set_pool):
    """Arming a trigger nothing will ever announce is the defect rounds 93 and
    105 each found after the fact; asked here at the moment the trigger is
    *created* instead. An event outside the table has no site, so the clause is
    not read and the card refuses."""
    from engine.oracle import _parse_delayed_attack_trigger

    assert _parse_delayed_attack_trigger(
        "Until end of turn, whenever a creature you control with power 2 or "
        "less deals combat damage to a player, draw a card.",
        "Subira, Tulzidi Caravanner",
    ) is not None
    assert _parse_delayed_attack_trigger(
        "Until end of turn, whenever a creature you control with power 2 or "
        "less becomes tapped, draw a card.",
        "Invented Card",
    ) is None

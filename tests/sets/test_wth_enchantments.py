"""Weatherlight enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G2: dies, enters and leaves triggers ---
from engine import Game, PlayerState
from engine.models import Permanent


def _w1g2e_settle(game, limit=30):
    """Resolve the stack, stopping at an owed prompt.

    Never a bare ``while game.stack`` loop: an interactive seat that owes an
    answer holds the stack open (CR 608.2, CR 117.3b) and the loop would spin.
    """
    for _ in range(limit):
        if not game.stack or game.waiting_prompt():
            return
        game.resolve_top_of_stack()


def _w1g2e_names(zone):
    return sorted(getattr(entry, "card", entry).name for entry in zone)


def test_angelic_renewal_reanimates_under_the_seat_the_sentence_leaves_unsaid(
    set_pool, catalog_by_name
):
    """"Whenever a creature is put into your graveyard from the battlefield,
    you may sacrifice this enchantment. If you do, return that card to the
    battlefield."

    The sentence names no controller, and CR 110.2a settles it: an effect that
    puts an object onto the battlefield puts it under *that player's* control
    unless it says otherwise. The lowering used to refuse the line for saying
    nothing - it admitted only the explicit "under your control" - so a card
    was unsupported for printing the default.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    renewal = Permanent(card=set_pool("WTH")["Angelic Renewal"])
    game._put_permanent_onto_battlefield(0, renewal, None)
    victim = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, victim, None)
    _w1g2e_settle(game)

    victim.damage_marked = 999
    game.check_state_based_actions()
    _w1g2e_settle(game)

    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True) is True
    _w1g2e_settle(game)

    assert _w1g2e_names(alice.battlefield) == ["Grizzly Bears"]
    assert _w1g2e_names(alice.graveyard) == ["Angelic Renewal"]


def test_abduction_gives_the_creature_back_to_its_owner_when_it_dies(
    set_pool, catalog_by_name
):
    """Abduction's three lines are one card, and the last one is the whole
    reason it is not Control Magic.

    "You control enchanted creature" is a CR 613 layer-2 contribution while the
    Aura is attached; "When enchanted creature dies, return that card to the
    battlefield **under its owner's control**" gives it back. That seat is the
    one the reanimation could not say - the handler put every returned card
    under the resolving player's control, which here is the thief - so the card
    was refused rather than quietly stealing the creature twice.
    """
    victim = Permanent(card=catalog_by_name["Grizzly Bears"])
    victim.tapped = True
    owner = PlayerState(name="Bob", battlefield=[victim])
    thief = PlayerState(name="Alice", hand=[set_pool("WTH")["Abduction"]])
    game = Game(players=[thief, owner])
    game.enforce_mana_costs = False
    game._settle()

    game.cast_from_hand(0, "Abduction", target_player_index=1, target_permanent_index=0)
    _w1g2e_settle(game)

    assert game.controller_index_of(victim) == 0, "you control enchanted creature"
    assert not victim.tapped, "the Aura's own entry trigger untaps it"

    victim.damage_marked = 999
    game.check_state_based_actions()
    _w1g2e_settle(game)
    game.check_state_based_actions()

    assert _w1g2e_names(owner.battlefield) == ["Grizzly Bears"], (
        "the Bears come back to Bob, who never stopped owning them"
    )
    assert thief.battlefield == []
    assert _w1g2e_names(thief.graveyard) == ["Abduction"]


# --- W1G3: cumulative upkeep beyond a mana cost ---
from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _w1g3_solo_game(card, *, library=0, life=20, library_card=None):
    perm = Permanent(card=card)
    p1 = PlayerState(
        name="P1", battlefield=[perm], life=life,
        library=[library_card for _ in range(library)] if library_card else [],
    )
    p2 = PlayerState(name="P2", life=life)
    return Game(players=[p1, p2]), p1, perm


def test_psychic_vortex_draws_one_card_per_age_counter_each_upkeep(set_pool):
    """"Cumulative upkeep—Draw a card."

    The card was **supported before this round** — its end-step trigger claimed
    it — and its upkeep did nothing at all, which is the failure mode a support
    census cannot see. Three upkeeps draw one, then two, then three.
    """
    pool = set_pool("WTH")
    game, p1, perm = _w1g3_solo_game(
        pool["Psychic Vortex"], library=12, library_card=pool["Fog Elemental"]
    )

    drawn = []
    for _ in range(3):
        game.resolve_upkeep(0)
        drawn.append((counters_on(perm, "age"), len(p1.hand)))

    assert drawn == [(1, 1), (2, 3), (3, 6)]
    assert perm in p1.battlefield


def test_psychic_vortexs_upkeep_is_a_cumulative_upkeep_trigger(set_pool):
    program = compile_card_oracle(set_pool("WTH")["Psychic Vortex"])

    assert program.supported
    assert sorted(
        trig.instruction.kind for trig in program.triggered_abilities
        if trig.instruction is not None
    ) == ["cumulative_upkeep", "sequence"]


def _w1g3_settle(game):
    """Run the stack down, answering the announcement it now stops for.

    Never a bare ``while game.stack`` loop: a pay-or-sacrifice upkeep owes an
    interactive seat a prompt, and while one is owed the game waits (CR 608.2,
    CR 117.3b).
    """
    game.auto_resolve_pending_choices(kinds=("trigger_target",))
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game.auto_resolve_pending_choices(kinds=("trigger_target",))
        game._settle()


def test_wave_of_terror_kills_the_mana_value_its_age_counters_name(set_pool, cards):
    """"At the beginning of your draw step, destroy each creature with mana
    value equal to the number of age counters on this enchantment."

    The card was **supported before this round** on its keyword line alone, with
    this whole ability compiling to no instruction — a hollow line, and the one
    of the three silent failures an instrument can see.

    Both boards, because the sentence names no controller: a sweep narrowed to
    the caster's own creatures would be a strictly better card. Four draw steps,
    because a bound read as a constant, as "at most", or off the wrong pile all
    look identical on the first one.
    """
    wave = Permanent(card=set_pool("WTH")["Wave of Terror"])
    lands = [Permanent(card=cards["Swamp"]) for _ in range(12)]
    mine = {
        name: Permanent(card=cards[name])
        for name in ("Savannah Lions", "Grizzly Bears", "Gray Ogre", "Hill Giant")
    }
    theirs = {
        name: Permanent(card=cards[name])
        for name in ("Merfolk of the Pearl Trident", "Hurloon Minotaur")
    }
    p1 = PlayerState(name="P1", battlefield=[wave] + lands + list(mine.values()))
    p2 = PlayerState(name="P2", battlefield=list(theirs.values()))
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}

    survivors = []
    for _ in range(4):
        game.resolve_upkeep(0, human_choices={"Wave of Terror": True})
        _w1g3_settle(game)
        for land in lands:
            land.tapped = False
        game.resolve_draw_step(0)
        _w1g3_settle(game)
        survivors.append(sorted(
            perm.card.name
            for seat in (p1, p2) for perm in seat.battlefield
            if "Creature" in perm.card.type_line
        ))

    assert survivors == [
        # 1 age counter: both mana-value-1 creatures, one per seat
        ["Gray Ogre", "Grizzly Bears", "Hill Giant", "Hurloon Minotaur"],
        ["Gray Ogre", "Hill Giant", "Hurloon Minotaur"],
        ["Hill Giant"],
        [],
    ]
    assert wave in p1.battlefield, "the enchantment is not a creature"


def test_wave_of_terrors_sweep_carries_both_of_its_riders(set_pool):
    """The counted bound *and* "They can't be regenerated." A sweep that kept
    the first and dropped the second would be a card that works more often than
    it prints — and one that kept neither would take the whole board."""
    program = compile_card_oracle(set_pool("WTH")["Wave of Terror"])
    sweep = next(
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "draw_step_self"
    )

    assert sweep.instruction.kind == "destroy_all_matching"
    assert sweep.instruction.payload == {
        "type_filter": "creature",
        "mana_value_equals_source_counters": "age",
        "bypass_regeneration": True,
    }


def test_heart_of_bogardan_burns_the_target_and_that_players_board(set_pool, cards):
    """"When a player doesn't pay this enchantment's cumulative upkeep, this
    enchantment deals X damage to target player or planeswalker and each
    creature that player or that planeswalker's controller controls, where X is
    twice the number of age counters on this enchantment minus 2."

    The card was **supported before this round** on its keyword line, with the
    whole of this ability compiling to no instruction — a hollow line. Three
    separate things had to be true for it to work, and the assertions below
    check each: the unpaid-upkeep trigger has to fire at all, X has to be
    2N-2 rather than 2N or 2(N-1), and the swept half has to land on the
    **target's** board rather than on the board of the player who declined —
    who is the enchantment's own controller, and so the opposite seat.
    """
    pool = set_pool("WTH")
    heart = Permanent(card=pool["Heart of Bogardan"])
    lands = [Permanent(card=cards["Mountain"]) for _ in range(14)]
    mine = Permanent(card=cards["Hill Giant"])
    theirs = [
        Permanent(card=cards[name])
        for name in ("Gray Ogre", "Hurloon Minotaur", "Hill Giant")
    ]
    p1 = PlayerState(name="P1", battlefield=[heart] + lands + [mine], life=20)
    p2 = PlayerState(name="P2", battlefield=list(theirs), life=20)
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}

    for _ in range(4):
        game.resolve_upkeep(0, human_choices={"Heart of Bogardan": True})
        _w1g3_settle(game)
        for land in lands:
            land.tapped = False
    assert counters_on(heart, "age") == 4 and p2.life == 20

    game.resolve_upkeep(0, human_choices={"Heart of Bogardan": False})
    _w1g3_settle(game)

    # The fifth counter goes down before the payment is offered, so X is
    # 2 * 5 - 2 = 8.
    assert p2.life == 12
    assert [perm.card.name for perm in p2.battlefield] == []
    assert mine in p1.battlefield, (
        "the sweep is the target's board, not the declining player's"
    )
    assert p1.life == 20


def test_heart_of_bogardan_raises_one_picker_for_one_printed_target(set_pool):
    """"target player or planeswalker **and** each creature that player …
    controls" is one printed choice, not two: the second half is a description
    keyed to the object the first half named.

    So the sweep carries the seat key the matcher answers from the announced
    target — never ``that_player``, which for this trigger is the seat that
    failed to pay and is the enchantment's own controller.
    """
    program = compile_card_oracle(set_pool("WTH")["Heart of Bogardan"])
    unpaid = next(
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "cumulative_upkeep_unpaid"
    )
    steps = unpaid.instruction.payload["steps"]

    assert [step.kind for step in steps] == ["deal_damage", "deal_damage_each_matching"]
    assert steps[0].payload["targets"] == {
        "quantifier": "target", "kind": "player_or_planeswalker",
    }
    assert steps[1].payload["filter"] == {
        "type_filter": "creature", "controller": "target_player",
    }
    assert steps[1].payload["target_controller_if_permanent"] is True
    # Both halves read one X, taken off the counters as the ability resolves.
    for step in steps:
        assert step.payload["x_from_count"] == {
            "source_counters": "age", "multiplier": 2, "plus": -2,
        }


# --- W1G1: the top of a graveyard as a cost ---

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str) -> CardDefinition:
    """A vanilla card to stack a graveyard with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _w1g1_game(battlefield, graveyard):
    """A game whose active seat holds *battlefield* and *graveyard*.

    The graveyard is given bottom-first, the list order CR 404.1 produces: a
    card put into a graveyard goes on top, so the last element is the top card.
    """
    for perm in battlefield:
        perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(battlefield),
                    graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def test_alms_pays_with_the_top_card_whatever_it_is(set_pool):
    """"{1}, Exile the top card of your graveyard: Prevent the next 1 damage
    that would be dealt to target creature this turn."

    The *unnarrowed* half of the family: no characteristic is named, so the top
    card pays whatever it is — a land included. That is the difference between
    this and Necratog's "top **creature** card", and the reason the filter is
    optional rather than defaulted.
    """
    alms = Permanent(card=set_pool("WTH")["Alms"])
    bear = Permanent(card=_w1g1_card("Target Bear", "Creature — Bear"))
    game = _w1g1_game([alms, bear], [
        _w1g1_card("Deep Bear", "Creature — Bear"),
        _w1g1_card("Top Land", "Land"),
    ])
    me = game.players[0]
    result = game.activate_permanent_ability(
        0, "Alms", target_player_index=0, target_permanent_index=1
    )
    assert result.supported, result.details
    assert [card.name for card in me.exile] == ["Top Land"], (
        "the top card paid, not the topmost creature card"
    )
    assert [card.name for card in me.graveyard] == ["Deep Bear"]
    game.resolve_top_of_stack()
    assert bear.damage_prevention_pool == 1, "the shield reached the target"


def test_alms_cannot_be_activated_on_an_empty_graveyard(set_pool):
    """CR 118.3 again, for the unnarrowed spelling: an empty pile has no top
    card, so the ability is unactivatable rather than free."""
    alms = Permanent(card=set_pool("WTH")["Alms"])
    bear = Permanent(card=_w1g1_card("Target Bear", "Creature — Bear"))
    game = _w1g1_game([alms, bear], [])
    result = game.activate_permanent_ability(
        0, "Alms", target_player_index=0, target_permanent_index=1
    )
    assert not result.supported
    assert not game.stack, "the ability never reached the stack"


def test_natures_kiss_pumps_the_enchanted_creature_off_the_graveyard(set_pool):
    """"{1}, Exile the top card of your graveyard: Enchanted creature gets
    +1/+1 until end of turn." The same cost on an Aura, so the payment and the
    attachment are two independent facts about one activation.
    """
    host = Permanent(card=_w1g1_card("Host Bear", "Creature — Bear"))
    kiss = Permanent(card=set_pool("WTH")["Nature's Kiss"])
    game = _w1g1_game([host, kiss], [_w1g1_card("Top Land", "Land")])
    attach_aura(kiss, host)
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Nature's Kiss")
    assert result.supported, result.details
    assert [card.name for card in me.exile] == ["Top Land"]
    game.resolve_top_of_stack()
    assert (host.effective_power, host.effective_toughness) == (3, 3)


# --- W1G4: animation and printed prohibitions ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g4e_creature(name, power, toughness, keywords=()):
    """A creature whose only text is its keyword line, if any."""
    text = "\n".join(word.capitalize() for word in keywords)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4e_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g4e_combat(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def test_familiar_ground_is_its_own_kind_and_not_stalking_tigers(set_pool):
    """"Each creature you control can't be blocked by more than one creature."

    Stalking Tiger's ceiling printed on a *permanent* about somebody else's
    creatures. Its own kind, because the two are found differently: that one is
    read off the attacker's own compiled program and this one has to be scanned
    for over the board, so a payload flag on one kind would leave whichever
    enforcement site did not read it applying the ceiling to the wrong
    creatures.
    """
    program = compile_card_oracle(set_pool("WTH")["Familiar Ground"])
    assert program.supported, program.reason
    assert [(i.kind, i.payload) for i in program.instructions] == [
        (
            "matching_cant_be_blocked_by_more_than",
            {"count": 1, "subject": {"type_filter": "creature", "controller": "you"}},
        )
    ]


def test_familiar_ground_caps_its_controllers_attackers_at_one_blocker(set_pool):
    """CR 509.1b over a whole declaration, in a game.

    Two blockers on one attacker is refused and one is allowed, which is the
    pair a rig that simply refused every declaration could not produce.
    """
    ground = Permanent(card=set_pool("WTH")["Familiar Ground"])
    attacker = _w1g4e_nosick(Permanent(card=_w1g4e_creature("Footman", 2, 2)))
    first = _w1g4e_nosick(Permanent(card=_w1g4e_creature("Guard", 1, 1)))
    second = _w1g4e_nosick(Permanent(card=_w1g4e_creature("Sentry", 1, 1)))
    # The enchantment occupies battlefield slot 0 on its controller's side, so
    # the attacker is slot 1 — declaration is index-keyed.
    game = _w1g4e_combat([ground, attacker], [first, second])
    assert game.declare_attackers(0, [1])[0]
    game.advance_combat_phase()

    ok, _ = game.declare_blockers(1, {0: 1, 1: 1})
    assert not ok
    assert game.declare_blockers(1, {0: 1})[0]


def test_familiar_ground_does_not_cap_the_opponents_attackers(set_pool):
    """"You control" is relative to the permanent printing it (CR 109.5).

    Dropped, the enchantment would protect both seats' attackers — a narrowing
    the payload carries and the board scan has to honour, which is the direction
    this whole family refuses.
    """
    ground = Permanent(card=set_pool("WTH")["Familiar Ground"])
    attacker = _w1g4e_nosick(Permanent(card=_w1g4e_creature("Raider", 2, 2)))
    first = _w1g4e_nosick(Permanent(card=_w1g4e_creature("Guard", 1, 1)))
    second = _w1g4e_nosick(Permanent(card=_w1g4e_creature("Sentry", 1, 1)))
    # The Familiar Ground belongs to the *defending* seat, so its "you control"
    # names creatures that are not attacking at all.
    game = _w1g4e_combat([attacker], [ground, first, second])
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    # Slots 1 and 2 on the defending side; slot 0 is the enchantment.
    assert game.declare_blockers(1, {1: 0, 2: 0})[0]


def test_dense_foliage_stops_a_spell_targeting_any_creature(set_pool, catalog_by_name):
    """"Creatures can't be the targets of spells." — CR 115.1's narrowed shroud
    printed about a **described set**.

    The third subject this clause has: the other two are relations from the
    creature back to the line (its own text, or an Aura attached to it) and this
    one is nowhere near the creature it protects, so the answer comes from a
    board scan rather than from ``printed_about``.

    The sentence narrows by nothing, so it reaches both seats; and it says
    *spells*, so an ability still targets. Both are asserted, because a shroud
    grant would pass the first and fail the second.
    """
    foliage = Permanent(card=set_pool("WTH")["Dense Foliage"])
    mine = Permanent(card=_w1g4e_creature("Footman", 2, 2))
    theirs = Permanent(card=_w1g4e_creature("Raider", 2, 2))
    game = _w1g4e_combat([foliage, mine], [theirs])
    bolt = catalog_by_name["Lightning Bolt"]

    assert not game._can_be_targeted(mine, bolt, caster_index=0)
    assert not game._can_be_targeted(theirs, bolt, caster_index=0)
    # An *ability* is a separately targeted object (CR 115.1c), and the printed
    # word is "spells" — so the same creature is still a legal target for one.
    assert game._can_be_targeted(mine, None, ability_source=foliage)


def test_a_creature_is_targetable_again_once_the_foliage_is_gone(
    set_pool, catalog_by_name
):
    """A static ability ends with its source (CR 611.2) and the scan is made at
    the moment a target is chosen, so nothing has to be undone."""
    foliage = Permanent(card=set_pool("WTH")["Dense Foliage"])
    mine = Permanent(card=_w1g4e_creature("Footman", 2, 2))
    game = _w1g4e_combat([foliage, mine], [])
    bolt = catalog_by_name["Lightning Bolt"]

    assert not game._can_be_targeted(mine, bolt, caster_index=0)
    game.remove_from_battlefield(foliage)
    assert game._can_be_targeted(mine, bolt, caster_index=0)


def test_the_board_reader_refuses_the_two_subjects_the_relational_one_owns():
    """The refusal test, written before the gate is trusted.

    ``subject_filter_payload`` answers a bare ``{"type_filter": "creature"}`` for
    "this creature" and for "enchanted creature" — so a reader that took either
    would shroud every creature in the game off one Aura. ``plural=True`` is what
    refuses them, and a class this file does not name refuses too rather than
    being read as the bare "spells".
    """
    from engine.target_immunity import board_target_immunities

    assert board_target_immunities("Creatures can't be the targets of spells.")
    assert not board_target_immunities("This creature can't be the targets of spells.")
    assert not board_target_immunities(
        "Enchanted creature can't be the targets of spells."
    )
    assert not board_target_immunities(
        "Creatures can't be the targets of spells or abilities."
    )

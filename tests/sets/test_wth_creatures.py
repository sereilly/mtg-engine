"""Weatherlight creatures.

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


def _w1g2_rig(interactive=()):
    """A two-seat game with mana costs off.

    ``interactive`` names the seats that are *asked* their prompts. A
    non-interactive seat takes a prompt's default the moment it is armed, so a
    test written without this proves only that the default runs.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, alice, bob


def _w1g2_enters(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _w1g2_settle(game, limit=30):
    """Resolve the stack, stopping at an owed prompt.

    Never a bare ``while game.stack`` loop: an interactive seat that owes an
    answer holds the stack open (CR 608.2, CR 117.3b) and the loop would spin.
    """
    for _ in range(limit):
        if not game.stack or game.waiting_prompt():
            return
        game.resolve_top_of_stack()


def _w1g2_kill(game, permanent):
    """Lethal damage plus the CR 704.5g sweep - the real death path."""
    permanent.damage_marked = 999
    game.check_state_based_actions()


def _w1g2_names(zone):
    return sorted(getattr(entry, "card", entry).name for entry in zone)


def test_alabaster_dragon_shuffles_its_own_card_into_its_owners_library(
    set_pool, catalog_by_name
):
    """"When this creature dies, shuffle **it** into its owner's library."

    The card, not the permanent: by the time a death trigger resolves the
    Dragon is in a graveyard (CR 603.10), and the sentence names no source zone
    at all, so the handler has to reach whichever zone actually holds it. What
    proves the move happened is the graveyard being *empty* afterwards - a
    handler that appended to the library without removing it would leave two
    Dragons in the game.
    """
    game, alice, _ = _w1g2_rig()
    alice.library[:] = [catalog_by_name["Forest"]] * 3
    dragon = _w1g2_enters(game, 0, set_pool("WTH")["Alabaster Dragon"])

    _w1g2_kill(game, dragon)
    _w1g2_settle(game)

    assert alice.graveyard == []
    assert len(alice.library) == 4
    assert any(card.name == "Alabaster Dragon" for card in alice.library)


def test_barishi_exiles_itself_before_it_shuffles_the_rest_back(
    set_pool, catalog_by_name
):
    """"When this creature dies, exile it, **then** shuffle all creature cards
    from your graveyard into your library."

    The order is the card: exiled first, Barishi is not among the creature
    cards the second half sweeps up, so it does not shuffle itself back in.
    And the noun phrase is a real narrowing - the Lightning Bolt in the same
    graveyard stays there. A filter parsed and dropped would return the whole
    pile, which is a strictly better card.
    """
    game, alice, _ = _w1g2_rig()
    alice.library[:] = [catalog_by_name["Forest"]] * 2
    alice.graveyard[:] = [
        catalog_by_name["Grizzly Bears"],
        catalog_by_name["Lightning Bolt"],
        catalog_by_name["Hurloon Minotaur"],
    ]
    barishi = _w1g2_enters(game, 0, set_pool("WTH")["Barishi"])

    _w1g2_kill(game, barishi)
    _w1g2_settle(game)

    assert _w1g2_names(alice.exile) == ["Barishi"]
    assert _w1g2_names(alice.graveyard) == ["Lightning Bolt"]
    assert _w1g2_names(alice.library) == [
        "Forest", "Forest", "Grizzly Bears", "Hurloon Minotaur",
    ]


def test_timid_drake_does_not_bounce_itself_when_it_enters(set_pool, catalog_by_name):
    """"When **another** creature enters, return this creature to its owner's
    hand."

    The word is the whole card. ``engine/oracle.py``'s table read the line as
    ``enters_battlefield`` - the source's own entry - so the Drake bounced
    itself the turn it arrived and never fired again: an ability firing on the
    wrong event, which reads to every census as implemented. Both halves are
    asserted here because either alone passes on the broken reading.
    """
    game, alice, _ = _w1g2_rig()
    drake = _w1g2_enters(game, 0, set_pool("WTH")["Timid Drake"])
    _w1g2_settle(game)

    assert drake in alice.battlefield, "its own entry is not another creature's"
    assert alice.hand == []

    _w1g2_enters(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g2_settle(game)

    assert alice.battlefield == []
    assert _w1g2_names(alice.hand) == ["Timid Drake"]


def test_thundermare_leaves_itself_untapped(set_pool, catalog_by_name):
    """"When this creature enters, tap all **other** creatures."

    "Other" reaches the sweep as ``exclude_self`` and is tested against the
    ability's own source, which the handler already passes. Dropped, the
    Thundermare taps itself and attacks into nothing - the difference between
    the card and a strictly worse one. Both battlefields are swept: the phrase
    names no controller.
    """
    game, alice, bob = _w1g2_rig()
    mine = _w1g2_enters(game, 0, catalog_by_name["Grizzly Bears"])
    theirs = _w1g2_enters(game, 1, catalog_by_name["Hurloon Minotaur"])
    mare = _w1g2_enters(game, 0, set_pool("WTH")["Thundermare"])

    _w1g2_settle(game)

    assert mine.tapped and theirs.tapped
    assert not mare.tapped


def test_cinder_wall_destroys_itself_at_end_of_combat(set_pool, catalog_by_name):
    """"When this creature blocks, destroy **it** at end of combat."

    Under a trigger whose condition names no other object, "it" is the
    ability's own source - which is what the *immediate* destroy already read
    and only the delayed one refused. The Wall survives its block (3/3 against
    a 1/1) and dies to CR 603.7's delayed ability instead, which is the whole
    point of the card.
    """
    wall = Permanent(card=set_pool("WTH")["Cinder Wall"])
    attacker = Permanent(card=catalog_by_name["Mons's Goblin Raiders"])
    alice = PlayerState(name="Alice", battlefield=[attacker])
    bob = PlayerState(name="Bob", battlefield=[wall])
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game._settle()
    attacker.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: [0]})[0]
    _w1g2_settle(game)
    assert wall in bob.battlefield, "the destruction is delayed, not immediate"

    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    game.check_state_based_actions()
    assert wall in bob.battlefield, "a 1/1 does not kill a 3/3"

    game.end_combat()
    _w1g2_settle(game)
    game.check_state_based_actions()

    assert wall not in bob.battlefield
    assert _w1g2_names(bob.graveyard) == ["Cinder Wall"]


def test_sage_owl_rearranges_the_top_four_of_its_own_library(set_pool, catalog_by_name):
    """"When this creature enters, look at the top four cards of your library,
    then put them back in any order."

    Nothing is drawn and nothing is bottomed: the whole effect is the order,
    so the library's *size* is the check that no card moved zones and the
    order is the check that the prompt did anything at all. Seat 0 is
    interactive, or the default would answer for it.
    """
    game, alice, _ = _w1g2_rig(interactive={0})
    alice.library[:] = [
        catalog_by_name[name]
        for name in ("Forest", "Mountain", "Plains", "Island", "Swamp")
    ]
    _w1g2_enters(game, 0, set_pool("WTH")["Sage Owl"])
    _w1g2_settle(game)

    assert game.pending_reorder_library == {
        "target_index": 0, "top_count": 4, "may_shuffle": False,
        "_cause_seat": 0, "caster_index": 0,
    }
    assert game.confirm_reorder_library(0, [3, 2, 1, 0]) is True
    assert [card.name for card in alice.library] == [
        "Island", "Plains", "Mountain", "Forest", "Swamp",
    ]


def test_harvest_wurm_is_sacrificed_when_the_graveyard_has_no_basic_land(
    set_pool, catalog_by_name
):
    """"When this creature enters, sacrifice it **unless you return a basic
    land card** from your graveyard to your hand."

    Two narrowings, and the card is wrong without either. A Bayou is a land
    card and not a *basic* one, so the price cannot be paid - and an offer that
    could be accepted anyway would return nothing, count as paid and leave the
    Wurm on the battlefield for free, which is the shape CR 601.2h's "able to"
    exists to refuse.
    """
    game, alice, _ = _w1g2_rig(interactive={0})
    alice.graveyard[:] = [catalog_by_name["Bayou"]]
    _w1g2_enters(game, 0, set_pool("WTH")["Harvest Wurm"])
    _w1g2_settle(game)

    assert game.pending_choices == [], "an offer nobody can take is never made"
    assert alice.battlefield == []
    assert _w1g2_names(alice.graveyard) == ["Bayou", "Harvest Wurm"]


def test_harvest_wurm_pays_with_a_basic_land_from_the_graveyard(
    set_pool, catalog_by_name
):
    """The other half of the same sentence: with a Forest in the graveyard the
    price is payable, and paying it keeps the Wurm."""
    game, alice, _ = _w1g2_rig(interactive={0})
    alice.graveyard[:] = [catalog_by_name["Forest"], catalog_by_name["Grizzly Bears"]]
    wurm = _w1g2_enters(game, 0, set_pool("WTH")["Harvest Wurm"])
    _w1g2_settle(game)

    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True) is True
    _w1g2_settle(game)

    assert wurm in alice.battlefield
    assert _w1g2_names(alice.hand) == ["Forest"]
    assert _w1g2_names(alice.graveyard) == ["Grizzly Bears"]


# --- W1G3: cumulative upkeep beyond a mana cost ---
from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _w1g3_solo_game(card, *, library=0, life=20, library_card=None):
    """One permanent on P1's battlefield and nothing else in the way.

    Built here rather than through a fixture because the point of every test in
    this block is the *upkeep step*, and a shared deck would leave which cards
    are on the board to the shuffle.
    """
    perm = Permanent(card=card)
    p1 = PlayerState(
        name="P1", battlefield=[perm], life=life,
        library=[library_card for _ in range(library)] if library_card else [],
    )
    p2 = PlayerState(name="P2", life=life)
    return Game(players=[p1, p2]), p1, perm


def test_aboroth_pays_its_upkeep_in_minus_counters_and_shrinks_to_death(set_pool):
    """"Cumulative upkeep—Put a -1/-1 counter on this creature."

    CR 702.24a's cost is paid **once per age counter**, so the 9/9 loses one
    point on its first upkeep, two more on its second and three more on its
    third — and the fourth kills it. A cost that scaled the payload instead of
    the repetition would put a single counter down every turn and leave an
    8/8 standing forever.
    """
    game, p1, perm = _w1g3_solo_game(set_pool("WTH")["Aboroth"])
    assert (perm.effective_power, perm.effective_toughness) == (9, 9)

    seen = []
    for _ in range(4):
        game.resolve_upkeep(0)
        seen.append((counters_on(perm, "age"), perm.effective_power))
        if perm not in p1.battlefield:
            break

    assert seen == [(1, 8), (2, 6), (3, 3), (4, -1)]
    assert perm not in p1.battlefield
    assert [c.name for c in p1.graveyard] == ["Aboroth"]


def test_aboroths_upkeep_prompt_quotes_the_act_and_its_repetition(set_pool):
    """The offer is made before the trigger resolves, so the counter it is
    about to place is already in the quoted cost — the same rule the mana
    spelling follows, and the reason a player is not shown one cost and
    charged another."""
    game, p1, perm = _w1g3_solo_game(set_pool("WTH")["Aboroth"])

    first = next(c for c in game.get_upkeep_pay_triggers(0) if c["card_name"] == "Aboroth")
    assert first["cost_label"] == "put a -1/-1 counter on this creature"

    game.resolve_upkeep(0)
    second = next(c for c in game.get_upkeep_pay_triggers(0) if c["card_name"] == "Aboroth")
    assert second["cost_label"] == "put a -1/-1 counter on this creature 2 times"


def test_aboroth_compiles_its_keyword_into_one_upkeep_trigger(set_pool):
    """The keyword line is the *only* line on the card, so before this round it
    was refused outright and Aboroth was unsupported — not a permanent with a
    free upkeep, which is the direction a widened gate would have gone."""
    program = compile_card_oracle(set_pool("WTH")["Aboroth"])

    assert program.supported
    assert [
        (trig.condition.kind, trig.instruction.kind)
        for trig in program.triggered_abilities
    ] == [("upkeep_self", "cumulative_upkeep")]


def _w1g3_settle(game):
    """Run the stack down, answering the announcement it now stops for.

    Never a bare ``while game.stack`` loop: a pay-or-sacrifice upkeep owes an
    interactive seat a prompt, and while one is owed the game waits (CR 608.2,
    CR 117.3b) — so the bare loop spins. Drained with the registry's own
    defaults.
    """
    game.auto_resolve_pending_choices(kinds=("trigger_target",))
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game.auto_resolve_pending_choices(kinds=("trigger_target",))
        game._settle()


def test_revered_unicorn_gains_life_for_every_age_counter_it_had(set_pool, cards):
    """"When this creature leaves the battlefield, you gain life equal to the
    number of age counters on it."

    The counter is placed *before* the payment is offered (CR 702.24a), so the
    upkeep that kills the Unicorn is also the one that puts its fourth counter
    down — and the number the trigger reads is last-known information
    (CR 603.10), taken off a permanent already in the graveyard.
    """
    unicorn = Permanent(card=set_pool("WTH")["Revered Unicorn"])
    lands = [Permanent(card=cards["Plains"]) for _ in range(8)]
    p1 = PlayerState(name="P1", battlefield=[unicorn] + lands, life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.interactive_seats = {0}

    for _ in range(3):
        game.resolve_upkeep(0, human_choices={"Revered Unicorn": True})
        _w1g3_settle(game)
        for land in lands:
            land.tapped = False
    assert counters_on(unicorn, "age") == 3 and p1.life == 20

    game.resolve_upkeep(0, human_choices={"Revered Unicorn": False})
    _w1g3_settle(game)

    assert unicorn not in p1.battlefield
    assert p1.life == 24, "four age counters when it left, not three"


def test_revered_unicorns_leave_trigger_counts_through_the_shared_evaluator(set_pool):
    """The amount is the ``source_counters`` spec Malignant Growth's draw and
    Primordial Ooze's where-clause already write — one evaluator, so the three
    printed word orders cannot count differently."""
    program = compile_card_oracle(set_pool("WTH")["Revered Unicorn"])
    leave = next(
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "leaves_battlefield"
    )

    assert leave.supported
    assert leave.instruction.payload["x_from_count"] == {"source_counters": "age"}


def test_mwonvuli_ooze_is_one_plus_twice_its_age_counters(set_pool, cards):
    """"Mwonvuli Ooze's power and toughness are each equal to 1 plus twice the
    number of age counters on it." (CR 604.3 over CR 122.1's counters.)

    Three upkeeps, because the arithmetic is what is being checked: a dropped
    "twice" is a 1/1 that grows by one and a constant applied on the wrong side
    of the multiplier is a 2/2 that grows by two, and both look right for
    exactly one turn.
    """
    ooze = Permanent(card=set_pool("WTH")["Mwonvuli Ooze"])
    lands = [Permanent(card=cards["Forest"]) for _ in range(12)]
    p1 = PlayerState(name="P1", battlefield=[ooze] + lands, life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.interactive_seats = {0}

    assert (ooze.effective_power, ooze.effective_toughness) == (1, 1)
    sizes = []
    for _ in range(3):
        game.resolve_upkeep(0, human_choices={"Mwonvuli Ooze": True})
        _w1g3_settle(game)
        for land in lands:
            land.tapped = False
        sizes.append((ooze.effective_power, ooze.effective_toughness))

    assert sizes == [(3, 3), (5, 5), (7, 7)]
    assert counters_on(ooze, "age") == 3


def test_mwonvuli_ooze_counts_through_the_one_evaluator(set_pool):
    """The count is the ``source_counters`` spec every other reading of "the
    number of <kind> counters on it" writes — not a second counter in the
    characteristic-defining table, which is what a per-card row would have
    been."""
    program = compile_card_oracle(set_pool("WTH")["Mwonvuli Ooze"])
    cda = next(i for i in program.instructions if i.kind == "dynamic_pt_count")

    assert cda.payload == {
        "count_spec": {"source_counters": "age", "multiplier": 2, "plus": 1}
    }

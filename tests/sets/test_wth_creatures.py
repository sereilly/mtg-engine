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


# --- W1G1: the top of a graveyard as a cost ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str) -> CardDefinition:
    """A vanilla card to stack a graveyard with, invented so the only thing
    that varies between the halves of each pair below is the printed type."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    )


def _w1g1_board(set_pool, name: str, graveyard: list[CardDefinition]):
    """*name* on the battlefield with *graveyard* behind it, ready to activate.

    The graveyard is given **bottom-first**, which is the list order CR 404.1
    produces: a card put into a graveyard goes on top, so the last element is
    the top card and `engine/graveyard_order.py` reads it as such.
    """
    perm = Permanent(card=set_pool("WTH")[name])
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, perm


@pytest.mark.parametrize("name", ["Necratog", "Zombie Scavengers"])
def test_the_graveyard_cost_takes_the_creature_card_nearest_the_top(set_pool, name):
    """"Exile the top creature card of your graveyard: …"

    The creature card *nearest the top*, not "the top card if it is a
    creature": CR 404.3 orders the pile and the phrase scans it. Read the other
    way both cards would be unactivatable with a land on top of a graveyard
    full of creatures.
    """
    game, _perm = _w1g1_board(set_pool, name, [
        _w1g1_card("Deep Bear", "Creature — Bear"),
        _w1g1_card("Near Bear", "Creature — Bear"),
        _w1g1_card("Top Land", "Land"),
    ])
    me = game.players[0]
    result = game.activate_permanent_ability(0, name)
    assert result.supported, result.details
    assert [card.name for card in me.exile] == ["Near Bear"]
    assert [card.name for card in me.graveyard] == ["Deep Bear", "Top Land"], (
        "the land on top and the deeper creature both stayed"
    )


@pytest.mark.parametrize("name", ["Necratog", "Zombie Scavengers"])
def test_the_graveyard_cost_is_unpayable_with_no_creature_card(set_pool, name):
    """CR 118.3: a player can't pay a cost without the resources to pay it
    fully, and CR 602.5c makes an unpayable cost an *unactivatable* ability
    rather than a free one. A graveyard of lands pays nothing here — and the
    lands are still there afterwards."""
    game, _perm = _w1g1_board(set_pool, name, [_w1g1_card("Top Land", "Land")])
    me = game.players[0]
    result = game.activate_permanent_ability(0, name)
    assert not result.supported
    assert not game.stack, "the ability never reached the stack"
    assert [card.name for card in me.graveyard] == ["Top Land"]
    assert me.exile == []


def test_necratog_grows_by_eating_its_graveyard(set_pool):
    """"Exile the top creature card of your graveyard: this creature gets +2/+2
    until end of turn." The cost is paid on activation (CR 601.2h/602.2b) and
    the pump arrives when the ability resolves."""
    game, perm = _w1g1_board(
        set_pool, "Necratog", [_w1g1_card("Snack", "Creature — Bear")]
    )
    printed = (perm.effective_power, perm.effective_toughness)
    result = game.activate_permanent_ability(0, "Necratog")
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert (perm.effective_power, perm.effective_toughness) == (
        printed[0] + 2, printed[1] + 2
    )


def test_zombie_scavengers_regenerates_off_its_graveyard(set_pool):
    """"Exile the top creature card of your graveyard: Regenerate this
    creature." (CR 701.15.)"""
    game, perm = _w1g1_board(
        set_pool, "Zombie Scavengers", [_w1g1_card("Snack", "Creature — Bear")]
    )
    result = game.activate_permanent_ability(0, "Zombie Scavengers")
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert perm.regeneration_shield == 1


def _w1g1_ghoul_board(set_pool, name: str, graveyard: list[CardDefinition]):
    """*name* on the battlefield with *graveyard* behind it, its upkeep trigger
    about to fire.

    ``auto_resolve_pending_choices`` rather than a bare stack drain: the offer
    is an ``optional_pay`` prompt on the pending-choice queue, and the game
    correctly waits until it is answered (CR 608.2, CR 117.3b).
    """
    perm = Permanent(card=set_pool("WTH")[name])
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.auto_resolve_pending_choices(kinds=("optional_pay",))
    return game, perm


def test_barrow_ghoul_pays_its_upkeep_with_the_topmost_creature_card(set_pool):
    """"At the beginning of your upkeep, sacrifice this creature unless you
    exile the top creature card of your graveyard."

    The same phrase Necratog charges as an activation cost, priced here as the
    alternative of a CR 118.8 offer — so the "unless" decomposes to a ``May``
    and the payment, the offer and the penalty all come from machinery that
    already works.
    """
    game, ghoul = _w1g1_ghoul_board(set_pool, "Barrow Ghoul", [
        _w1g1_card("Deep Bear", "Creature — Bear"),
        _w1g1_card("Top Land", "Land"),
    ])
    me = game.players[0]
    assert ghoul in me.battlefield, "the price was paid, so nothing was sacrificed"
    assert [card.name for card in me.exile] == ["Deep Bear"]
    assert [card.name for card in me.graveyard] == ["Top Land"]


def test_barrow_ghoul_is_sacrificed_when_the_price_cannot_be_paid(set_pool):
    """A graveyard with no creature card in it is a real "nothing to give", so
    the offer is never made and the printed penalty stands — the same gate
    Mold Demon's "unless you sacrifice two Swamps" runs through."""
    game, ghoul = _w1g1_ghoul_board(
        set_pool, "Barrow Ghoul", [_w1g1_card("Top Land", "Land")]
    )
    me = game.players[0]
    assert ghoul not in me.battlefield
    assert "Barrow Ghoul" in [card.name for card in me.graveyard]
    assert [card.name for card in me.exile] == [], "nothing was exiled"


# --- W1G4: animation and printed prohibitions ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _w1g4c_creature(name, power, toughness, keywords=()):
    """A creature whose only text is its keyword line, if any."""
    text = "\n".join(word.capitalize() for word in keywords)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4c_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g4c_combat(mine, theirs) -> Game:
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


def test_phantom_warrior_compiles_the_kind_two_sites_already_enforced(set_pool):
    """"This creature can't be blocked." — CR 509.1b, and no new behaviour.

    ``cant_be_blocked`` had two readers and no producer: the blockers step
    refuses every blocker on it and ``legality.is_unblockable`` reads it for the
    client's fade. The card's refusal said the sentence "needs the CR 613 layers
    engine", which was false twice over — the layers are live and this is not a
    layers question.
    """
    program = compile_card_oracle(set_pool("WTH")["Phantom Warrior"])
    assert program.supported, program.reason
    assert [(i.kind, i.payload) for i in program.instructions] == [
        ("cant_be_blocked", {})
    ]


def test_phantom_warrior_cannot_be_blocked_in_a_game(set_pool):
    """The Rock Hydra test: a compiled kind is not an enforced one."""
    warrior = _w1g4c_nosick(Permanent(card=set_pool("WTH")["Phantom Warrior"]))
    ordinary = _w1g4c_nosick(Permanent(card=_w1g4c_creature("Footman", 2, 2)))
    blocker = _w1g4c_nosick(Permanent(card=_w1g4c_creature("Guard", 2, 2)))
    game = _w1g4c_combat([warrior, ordinary], [blocker])
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()

    assert not game._can_block_attacker(blocker, warrior)
    # The control: the same blocker against a creature with no such line, so a
    # rig that refused every block would fail here rather than passing.
    assert game._can_block_attacker(blocker, ordinary)
    assert game.is_unblockable(warrior)
    assert not game.is_unblockable(ordinary)


def test_peacekeeper_grounds_every_creature_including_its_own_side(set_pool):
    """"Creatures can't attack." — the unnarrowed member of Moat's family.

    The sentence names no controller, so CR 109.5 leaves it reaching every
    seat's creatures; the Peacekeeper's own controller is stopped too, which is
    the whole of what makes the card symmetrical.

    It is put onto the battlefield **after** the upkeep rather than before it,
    because the card's other line sacrifices it unless {1}{W} is paid and a
    non-interactive seat takes the default — a rig that starts the turn with the
    Peacekeeper already there is a rig with no Peacekeeper in it, and every
    assertion below would pass against an engine that enforced nothing.
    """
    mine = _w1g4c_nosick(Permanent(card=_w1g4c_creature("Footman", 2, 2)))
    theirs = _w1g4c_nosick(Permanent(card=_w1g4c_creature("Raider", 2, 2)))
    game = _w1g4c_combat([mine], [theirs])
    assert game.can_attack(mine, 1)

    keeper = _w1g4c_nosick(Permanent(card=set_pool("WTH")["Peacekeeper"]))
    game.players[0].battlefield.append(keeper)
    assert not game.can_attack(mine, 1)
    assert not game.can_attack(keeper, 1)
    # The other seat's creature, asked of the same board: the sentence narrows
    # by nothing, so an implementation that scoped it to its controller would
    # pass the two assertions above and fail this one.
    assert not game.can_attack(theirs, 0)


def test_a_creature_can_attack_once_the_peacekeeper_is_gone(set_pool):
    """The control for the test above — the restriction is read off the board on
    every declaration, so removing its source restores the attack with nothing
    swept."""
    mine = _w1g4c_nosick(Permanent(card=_w1g4c_creature("Footman", 2, 2)))
    game = _w1g4c_combat([mine], [])
    keeper = _w1g4c_nosick(Permanent(card=set_pool("WTH")["Peacekeeper"]))
    game.players[0].battlefield.append(keeper)
    assert not game.can_attack(mine, 1)
    game.remove_from_battlefield(keeper)
    assert game.can_attack(mine, 1)


def test_steel_golem_stops_only_its_own_controllers_creature_spells(set_pool):
    """"You can't cast creature spells." — CR 601.3a, and CR 109.5 for "you".

    The third scope this prohibition is printed in, beside Aether Storm's
    board-wide "Creature spells can't be cast" and Brand of Ill Omen's "enchanted
    creature's controller". A ban read at the wrong scope is not a card doing
    less — it is a card doing something else, so both halves are asserted: the
    Golem's controller is stopped and the opponent is not.
    """
    golem = _w1g4c_nosick(Permanent(card=set_pool("WTH")["Steel Golem"]))
    spell = _w1g4c_creature("Footman", 2, 2)
    game = _w1g4c_combat([golem], [])
    game.players[0].hand.append(spell)
    game.players[1].hand.append(spell)

    result = game.cast_from_hand(0, "Footman")
    assert not result.supported
    assert "Steel Golem" in result.details

    # The opponent controls no Steel Golem, so the same card is castable — a
    # gate scoped to every battlefield would fail here and pass above.
    assert game.cast_from_hand(1, "Footman").supported


def test_steel_golem_lets_its_controller_cast_a_noncreature_spell(set_pool):
    """The type is payload, so the ban has to *stop at* the type it names."""
    golem = _w1g4c_nosick(Permanent(card=set_pool("WTH")["Steel Golem"]))
    artifact = CardDefinition(
        name="Test Sphere", mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Test Sphere", "type_line": "Artifact"},
    )
    game = _w1g4c_combat([golem], [])
    game.players[0].hand.append(artifact)
    assert game.cast_from_hand(0, "Test Sphere").supported


def test_roc_hatchling_grows_only_once_its_shell_counters_are_gone(set_pool):
    """"As long as this creature has no shell counters on it, it gets +3/+2 and
    has flying." — CR 613 layer 7c with a CR 122.1 counter store as its
    condition, driven through four upkeeps rather than read off the payload.

    The engine could already read the *existential* spelling of the zero ("as
    long as there are no time counters on this Aura", Tourach's Gate) and the
    possessive spelling of every count **but** zero ("if it has five or more
    hunger counters on it", Fasting). This card is the possessive zero, which
    was the one corner of that production nobody had printed yet.

    The comparison matters more than the number: read as "at least zero" the
    condition always holds, which is a 3/3 flier on the turn the Hatchling
    lands. The first three upkeeps are what prove it does not.
    """
    hatchling = Permanent(card=set_pool("WTH")["Roc Hatchling"])
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.players[0].battlefield.append(hatchling)
    game._initialize_permanent_state(hatchling, 0, 0)
    assert counters_on(hatchling, "shell") == 4

    seen = []
    for _ in range(4):
        game.start_turn(0)
        game._recompute_continuous_effects()
        seen.append((
            counters_on(hatchling, "shell"),
            hatchling.effective_power,
            hatchling.effective_toughness,
            game._has_keyword(hatchling, "flying"),
        ))

    assert seen == [
        (3, 0, 1, False),
        (2, 0, 1, False),
        (1, 0, 1, False),
        (0, 3, 3, True),
    ]


# --- W1G5: each player, in parallel ---
from engine import Game, PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5c_compile


def _w1g5c_game(interactive=()):
    game = Game(players=[
        PlayerState(name="P1", battlefield=[]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g5c_kill(game, perm, lea):
    """Bolt *perm* until it dies and let its dies-trigger resolve.

    A loop rather than one Bolt, because the three creatures this block tests
    are 1/1, 2/2 and 3/4 — sized to the toughness by asking the board rather
    than by a number written here, which is the same reason nothing else in
    this repo addresses a permanent by a count it kept itself.
    """
    for _ in range(4):
        if not game.is_on_battlefield(perm):
            break
        game.players[0].hand = [lea["Lightning Bolt"]]
        game.cast_from_hand(
            0, "Lightning Bolt", target_player_index=0,
            target_permanent_index=game.battlefield_index_of(perm),
        )
        game.resolve_stack()
        game._settle()
    assert not game.is_on_battlefield(perm), game.log
    game.resolve_stack()


def test_veteran_explorer_gives_every_seat_two_basics_off_its_own_library(set_pool):
    """"When this creature dies, each player may search their library for up to
    two basic land cards, put them onto the battlefield, then shuffle."

    The whole per-seat machinery was already here — `may` loops the seats
    through `run_resumable` and `_offer_to_seat` rebinds ``caster``, so the
    search inside opens the *offered* seat's library. What refused the card was
    one word: the search production expected "your" and the card prints
    "their", which is the pronoun agreeing with the subject the offer above it
    already named.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5c_compile(wth["Veteran Explorer"])
    assert program.supported, program.reason
    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may" and offer.payload["actor"] == "each_player"
    (search,) = offer.payload["action"]
    assert search.kind == "search_library"
    assert search.payload["destinations"] == ["battlefield", "battlefield"]
    assert search.payload["restrictions"] == {"supertypes": ["basic"]}

    game = _w1g5c_game()
    explorer = _W1G5Permanent(card=wth["Veteran Explorer"])
    game.players[0].battlefield.append(explorer)
    game._sync_control()
    game.players[0].library = [lea["Forest"], lea["Grizzly Bears"], lea["Plains"]] * 4
    game.players[1].library = [lea["Mountain"], lea["Lightning Bolt"], lea["Island"]] * 4

    _w1g5c_kill(game, explorer, lea)
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    # Each seat's own basics, off its own library — and the nonland cards in
    # both libraries are untouched.
    assert sorted(p.card.name for p in game.players[0].battlefield) == [
        "Forest", "Plains",
    ], game.log
    assert sorted(p.card.name for p in game.players[1].battlefield) == [
        "Island", "Mountain",
    ], game.log


def test_noble_benefactor_shuffles_only_the_seats_that_searched(set_pool):
    """"…each player may search their library for a card and put that card into
    their hand. Then each player who searched their library this way shuffles."

    The second sentence is CR 701.23c's shuffle, printed as a following
    sentence because the search it ends was offered to a *set* of seats and the
    words have to say which of them shuffle. This engine performs the shuffle
    inside the search prompt, so the set the sentence names is exactly the set
    the offer armed a prompt for — a seat that declines the "may" never
    searched, is never prompted, and its library is left alone.

    Natural Balance prints the same sentence word for word, which is why it is
    a production rather than a hook.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5c_compile(wth["Noble Benefactor"])
    assert program.supported, program.reason
    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may" and offer.payload["actor"] == "each_player"
    (search,) = offer.payload["action"]
    assert search.kind == "search_library"
    assert search.payload == {"count": 1, "card_type": "any"}

    game = _w1g5c_game(interactive={1})
    benefactor = _W1G5Permanent(card=wth["Noble Benefactor"])
    game.players[0].battlefield.append(benefactor)
    game._sync_control()
    game.players[0].library = [lea["Forest"], lea["Grizzly Bears"]] * 4
    ordered = [lea["Mountain"], lea["Island"], lea["Plains"]] * 3
    game.players[1].library = list(ordered)

    _w1g5c_kill(game, benefactor, lea)
    # P1 takes the default offer and searches; P2 is asked and declines.
    game.auto_resolve_pending_choices(only_player_index=0)
    owed = game.pending_choice_of("optional_pay")
    assert owed is not None and owed.player_index == 1, game.pending_choices
    assert game.confirm_optional_pay(1, accept=False), game.log
    game.auto_resolve_pending_choices()

    assert len(game.players[0].hand) == 1, game.log
    assert game.players[1].hand == [], game.log
    # The declining seat never searched, so nothing shuffled its library.
    assert [c.name for c in game.players[1].library] == [
        c.name for c in ordered
    ], game.log


def test_liege_of_the_hollows_gives_each_seat_a_squirrel_per_mana_it_paid(set_pool):
    """"When this creature dies, each player may pay any amount of mana. Then
    each player creates a number of 1/1 green Squirrel creature tokens equal to
    the amount of mana they paid this way."

    Both halves are per seat and the second reads the first. "Any amount"
    prints no ceiling, so the range comes from the *board* — pool plus untapped
    lands, through `mana_payment.plan_payment`, the same reader every other
    "you may pay" goes through because an effect that says "may pay" gives its
    player no priority window in which to tap. An answer the board cannot cover
    is rejected rather than clamped.

    The "may" collapses into the prompt, exactly as Mind Bomb's ceiling
    collapses the offer above its discard: zero is already a legal answer, and
    the sentence behind the offer has to run after every seat has answered
    (CR 608.2), which an `optional_pay` offer would not wait for.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5c_compile(wth["Liege of the Hollows"])
    assert program.supported, program.reason
    sequence = program.triggered_abilities[0].instruction
    offer, tokens = sequence.payload["steps"]
    assert offer.kind == "each_player_pays_any_mana"
    assert offer.payload == {"actor": "each_player"}
    assert tokens.kind == "create_token"
    assert tokens.payload["recipient_players"] == "each_player"
    assert tokens.payload["count"] == {"seat_record": "mana_paid_by_seat"}

    game = _w1g5c_game(interactive={0, 1})
    game.active_player_index = 0
    liege = _W1G5Permanent(card=wth["Liege of the Hollows"])
    game.players[0].battlefield.append(liege)
    forests = [_W1G5Permanent(card=lea["Forest"]) for _ in range(4)]
    game.players[0].battlefield.extend(forests)
    mountains = [_W1G5Permanent(card=lea["Mountain"]) for _ in range(2)]
    game.players[1].battlefield.extend(mountains)
    game._sync_control()

    _w1g5c_kill(game, liege, lea)

    # Every seat is asked at once, and the token sentence has not run.
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("pay_any_amount", 0), ("pay_any_amount", 1),
    ]
    assert not any(
        p.card.name == "Squirrel Token"
        for p in game.players[0].battlefield + game.players[1].battlefield
    )

    assert game.confirm_pay_any_amount(0, 3), game.log
    # Two untapped Mountains cannot cover five: a rejection, not a clamp.
    assert not game.confirm_pay_any_amount(1, 5)
    assert game.confirm_pay_any_amount(1, 2), game.log

    squirrels = lambda seat: sum(
        1 for p in game.players[seat].battlefield if p.card.name == "Squirrel Token"
    )
    assert squirrels(0) == 3, game.log
    assert squirrels(1) == 2, game.log
    # The mana really came off the board.
    assert sum(1 for land in forests if land.tapped) == 3
    assert sum(1 for land in mountains if land.tapped) == 2
    assert game.stack == [] and game.resume_stack == []


def test_liege_of_the_hollows_makes_nothing_for_a_seat_that_pays_nothing(set_pool):
    """A seat nobody asks pays nothing — the printed "may", and the only answer
    a default can take honestly. The record is a zero for every seat rather
    than a missing key, so no player reads another's answer."""
    wth, lea = set_pool("WTH"), set_pool("LEA")
    game = _w1g5c_game()
    game.active_player_index = 0
    liege = _W1G5Permanent(card=wth["Liege of the Hollows"])
    game.players[0].battlefield.append(liege)
    game.players[0].battlefield.extend(
        _W1G5Permanent(card=lea["Forest"]) for _ in range(4)
    )
    game._sync_control()

    _w1g5c_kill(game, liege, lea)
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    assert not any(
        p.card.name == "Squirrel Token"
        for p in game.players[0].battlefield + game.players[1].battlefield
    ), game.log
    assert all(not p.tapped for p in game.players[0].battlefield), game.log


# --- W2G1: costs charged and permissions granted ---
from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine.enter_effects import ENTERED_BATTLEFIELD_TURN
from engine.models import Permanent as _W2G1Permanent


def _w2g1_turn_one_board():
    p1, p2 = _W2G1PlayerState(name="A"), _W2G1PlayerState(name="B")
    game = _W2G1Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.turn = 1
    return game, p1, p2


def test_fungus_elemental_grows_only_on_the_turn_it_arrived(
    set_pool, catalog_by_name
):
    """"{G}, Sacrifice a Forest: Put a +2/+2 counter on this creature. Activate
    only if this creature entered this turn."

    The restriction is the card. Unenforced it is a +2/+2 every turn for the
    rest of the game on a card that offers exactly one — an ability working
    more often than the card allows, wrong in the player's favour and silent.
    """
    pool = set_pool("WTH")
    game, p1, _p2 = _w2g1_turn_one_board()
    elemental = _W2G1Permanent(card=pool["Fungus Elemental"])
    elemental.metadata[ENTERED_BATTLEFIELD_TURN] = game.turn
    p1.battlefield.append(elemental)
    p1.battlefield.append(_W2G1Permanent(card=catalog_by_name["Forest"]))

    result = game.activate_permanent_ability(0, "Fungus Elemental")
    resolve_stack(game)

    assert result.supported, result.details
    assert (elemental.effective_power, elemental.effective_toughness) == (5, 5)
    assert [c.name for c in p1.graveyard] == ["Forest"], "the Forest paid for it"


def test_fungus_elemental_refuses_on_a_later_turn(set_pool, catalog_by_name):
    """The same board one turn on. CR 602.5's clause is checked before any cost
    is paid, so the Forest is still there afterwards."""
    pool = set_pool("WTH")
    game, p1, _p2 = _w2g1_turn_one_board()
    game.turn = 2
    elemental = _W2G1Permanent(card=pool["Fungus Elemental"])
    elemental.metadata[ENTERED_BATTLEFIELD_TURN] = 1
    p1.battlefield.append(elemental)
    p1.battlefield.append(_W2G1Permanent(card=catalog_by_name["Forest"]))

    result = game.activate_permanent_ability(0, "Fungus Elemental")

    assert not result.supported
    assert "enter the battlefield this turn" in result.details
    assert (elemental.effective_power, elemental.effective_toughness) == (3, 3)
    assert [p.card.name for p in p1.battlefield] == [
        "Fungus Elemental", "Forest",
    ], "nothing was spent"


def test_circling_vultures_may_be_discarded_as_a_special_action(
    set_pool, catalog_by_name
):
    """"You may discard this card any time you could cast an instant."

    CR 116.2e names this card, and CR 116.1 is why it needed a seam rather than
    a production: a special action does not use the stack, so there is no
    instruction to compile — and the card reported *unsupported* for the one
    sentence that produces none by rule, while its flying and its upkeep
    trigger both worked.
    """
    from engine.special_actions import (available_special_actions,
                                        take_special_action)

    pool = set_pool("WTH")
    vultures = pool["Circling Vultures"]
    game, p1, _p2 = _w2g1_turn_one_board()
    p1.hand = [vultures, catalog_by_name["Grizzly Bears"]]
    game.priority_player_index = 0

    assert [entry["kind"] for entry in available_special_actions(game, 0)] == [
        "discard_from_hand"
    ]
    assert take_special_action(game, 0, vultures, "discard_from_hand") is None

    assert [c.name for c in p1.hand] == ["Grizzly Bears"]
    assert [c.name for c in p1.graveyard] == ["Circling Vultures"]
    assert game.stack == [], "CR 116.1: it never touches the stack"


def test_circling_vultures_upkeep_still_costs_a_creature_card(
    set_pool, catalog_by_name
):
    """"At the beginning of your upkeep, sacrifice this creature unless you
    exile the top creature card of your graveyard."

    The other half of the card, and the reason the special action had to make
    the *card* supported rather than merely be implemented: this trigger
    already compiled and already worked, and the card was refused anyway.
    """
    pool = set_pool("WTH")
    game, p1, _p2 = _w2g1_turn_one_board()
    game.interactive_seats = {0}
    vultures = _W2G1Permanent(card=pool["Circling Vultures"])
    p1.battlefield.append(vultures)
    p1.graveyard = [catalog_by_name["Grizzly Bears"]]

    game.resolve_upkeep(0)
    # The trigger is a "may … unless", so an interactive seat is *asked*
    # (CR 608.2, CR 117.3b: the game waits while a prompt is owed). A test
    # written without the prompt proves only that the default runs.
    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    game.confirm_optional_pay(0, accept=True)

    assert [c.name for c in p1.exile] == ["Grizzly Bears"], "the price was paid"
    assert [p.card.name for p in p1.battlefield] == ["Circling Vultures"]

    game.resolve_upkeep(0)
    game.confirm_optional_pay(0, accept=True)

    assert [p.card.name for p in p1.battlefield] == [], (
        "and with no creature card left, it is sacrificed"
    )
    assert [c.name for c in p1.graveyard] == ["Circling Vultures"]


# --- W2G5: enforcement, entry replacement and the last statics ---

from engine.oracle import compile_card_oracle as _w2g5_compile  # noqa: E402
from tests.helpers import _mk_card as _w2g5_mk_card, resolve_stack
from tests.helpers import _nosick as _w2g5_nosick  # noqa: E402


def test_serrated_biskelion_shrinks_itself_and_its_target(set_pool):
    """"{T}: Put a -1/-1 counter on this creature **and a -1/-1 counter on
    target creature**."

    One sentence, two placements, two different subjects — so it is neither a
    rider on the first placement nor a repetition of it, and the trailing half
    was unconsumed text that refused the whole ability. Both counters land, and
    on the two permanents the card names rather than twice on either.
    """
    biskelion = set_pool("WTH")["Serrated Biskelion"]
    source = _w2g5_nosick(Permanent(card=biskelion))
    bear = Permanent(card=_w2g5_mk_card("Plain Bear", "Creature - Bear"))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[source]),
        PlayerState(name="P1", battlefield=[bear]),
    ])

    result = game.activate_permanent_ability(
        0, "Serrated Biskelion", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()
    game._settle()

    assert result.supported, result.details
    assert (source.effective_power, source.effective_toughness) == (1, 1), game.log
    assert (bear.effective_power, bear.effective_toughness) == (1, 1), game.log


def test_serrated_biskelion_offers_a_creature_picker(set_pool):
    """The ability targets, so the activation derivation has to say so — an
    ability that names a target and offers no picker is refused by the engine
    the moment the client sends a bare activation."""
    from engine.targeting import derive_activation_spec

    biskelion = set_pool("WTH")["Serrated Biskelion"]
    ability = _w2g5_compile(biskelion).activated_abilities[0]

    assert derive_activation_spec(ability).get("kind") == "creature"

# --- end W2G5 ---


# --- W2G3: phasing and end of combat ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g3c_creature(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g3c_nosick(perm: Permanent) -> Permanent:
    perm.summoning_sick = False
    return perm


def _w2g3c_combat(*seats) -> Game:
    game = Game(players=[
        PlayerState(name=f"P{i + 1}", battlefield=list(board))
        for i, board in enumerate(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def _w2g3c_resolve(game: Game) -> None:
    for _ in range(40):
        if not game.stack:
            return
        game.resolve_top_of_stack()


def test_tolarian_entrancer_delays_the_steal_to_end_of_combat(set_pool):
    """"Whenever this creature becomes blocked by a creature, gain control of
    that creature **at end of combat**." (CR 511.1, CR 603.7.)

    The compiled shape carries the whole of the card: a delayed ability at
    ``next_end_of_combat`` whose effect addresses the delay's *bound* object.
    Routed through the ordinary indefinite steal it would have needed a target
    the card never printed; routed through the recorded-permanents spelling it
    would have read a scratchpad that is a combat step gone.
    """
    program = compile_card_oracle(set_pool("WTH")["Tolarian Entrancer"])
    assert program.supported, program.reason
    (trig,) = program.triggered_abilities
    assert trig.condition.kind == "creature_becomes_blocked"
    payload = trig.instruction.payload
    assert payload["event"] == "next_end_of_combat"
    assert payload["instruction"].kind == "gain_control_of_bound_permanent"
    # ``binds_block_pair`` rather than ``binds_target``, for the reason MIR's
    # Basalt Golem test records: a delay created by *either* half of a block now
    # binds through ``block_pair_permanents``, because on the blocks half the
    # stack item's target is the ability's own creature. Same permanent here.
    assert payload["binds_target"] is False
    assert payload["binds_block_pair"] is True


def test_tolarian_entrancer_takes_the_blocker_after_damage(set_pool):
    """The blocker changes hands at end of combat and not before.

    Ordering is the assertion: a steal that happened on the block would have
    removed the creature from combat (CR 506.4) and cancelled the damage the
    card is printed to take. So the Wall is still blocking through the damage
    step and only then moves — and it moves as a CR 613 layer-2 contribution,
    which is why the bystander beside it is the control on "the trigger bound
    exactly one creature".
    """
    entrancer = _w2g3c_nosick(Permanent(card=set_pool("WTH")["Tolarian Entrancer"]))
    wall = _w2g3c_nosick(Permanent(card=_w2g3c_creature("Wall", 0, 6)))
    bystander = _w2g3c_nosick(Permanent(card=_w2g3c_creature("Bystander", 1, 1)))
    game = _w2g3c_combat([entrancer], [wall, bystander])
    assert game.declare_attackers(0, [0])[0]
    _w2g3c_resolve(game)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    _w2g3c_resolve(game)

    (entry,) = game.delayed_triggers
    assert entry.bound_permanent_id == wall.permanent_id
    # Still the defender's while the damage is dealt.
    assert game.controller_index_of(wall) == 1

    game.advance_combat_phase()   # combat damage
    _w2g3c_resolve(game)
    game.advance_combat_phase()   # end of combat
    _w2g3c_resolve(game)

    assert game.controller_index_of(wall) == 0, game.log
    assert wall in game.players[0].battlefield
    assert game.controller_index_of(bystander) == 1
    # CR 108.3 / CR 613 layer 2: the change is a contribution, so the seat the
    # permanent entered under is untouched and the Wall would revert if the
    # contribution ever ended. An untimed steal has no end, which is CR 611.2a.
    assert wall.metadata.get("base_controller_index", 1) == 1


def _w2g3c_familiar(set_pool, set_cards):
    """Ertai's Familiar on an empty board, both seats with a library to mill."""
    mountain = set_pool("LEA")["Mountain"]
    fam = _w2g3c_nosick(Permanent(card=set_pool("WTH")["Ertai's Familiar"]))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[fam], library=[mountain] * 20),
        PlayerState(name="P2", library=[mountain] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, fam


def _w2g3c_turn(game: Game, seat: int) -> None:
    game.start_turn(seat)
    game._close_current_priority_step()
    _w2g3c_resolve(game)


def test_ertais_familiar_reads_one_ability_with_two_trigger_events(set_pool):
    """"When this creature **phases out or leaves the battlefield**, mill three
    cards." (CR 603.1b.)

    One condition kind, not two entries and not the bare leave. The generic
    leaves-the-battlefield row in `oracle.py` matches `when (?:this|.+)
    leaves…`, whose `.+` swallows "this creature phases out or" — so without a
    longer row above it this card would have compiled supported while watching
    only a departure it almost never makes.
    """
    program = compile_card_oracle(set_pool("WTH")["Ertai's Familiar"])
    assert program.supported, program.reason
    (trig,) = program.triggered_abilities
    assert trig.condition.kind == "phases_out_or_leaves_battlefield"
    assert trig.instruction.kind == "mill_target_player"
    assert trig.instruction.payload["amount"] == 3


def test_ertais_familiar_mills_when_its_own_phasing_takes_it_out(set_pool):
    """The phase-out half, fired by CR 702.26a's alternation.

    The Familiar has phasing, so this is the event it actually meets — and it
    is *not* a zone change (CR 702.26d), which is why the leave half cannot
    stand in for it. Exactly three cards: one announcement, not one per half.
    """
    game, _fam = _w2g3c_familiar(set_pool, None)
    _w2g3c_turn(game, 0)

    assert [p.card.name for p in game.players[0].phased_out] == [
        "Ertai's Familiar"
    ], game.log
    assert len(game.players[0].graveyard) == 3, game.log


def test_ertais_familiar_mills_when_it_leaves_the_battlefield(set_pool):
    """The other half of the same ability, from the removal transition.

    Run to a turn where the Familiar has phased back in, so the departure is a
    real one — a permanent already phased out is on no battlefield to leave.
    """
    game, fam = _w2g3c_familiar(set_pool, None)
    _w2g3c_turn(game, 0)          # phases out, mills 3
    _w2g3c_turn(game, 1)
    _w2g3c_turn(game, 0)          # phases in
    assert fam in game.players[0].battlefield

    before = len(game.players[0].graveyard)
    game.remove_from_battlefield(fam)
    _w2g3c_resolve(game)

    assert len(game.players[0].graveyard) - before == 3, game.log


def test_ertais_familiar_lock_stops_the_next_untap_steps_phase_out(set_pool):
    """"{U}: Until your next upkeep, this creature can't phase out."
    (CR 702.26a's alternation, refused.)

    The whole of the card's value is that the phase-out **does not happen**, so
    the assertion is an absence plus the mill that would have come with it. A
    restriction nothing enforces is an ability that works more often than the
    card allows, and this one would be silent: the Familiar would phase out on
    schedule and mill three, exactly as it does without the ability.

    The window ends at the controller's *upkeep*, which is one step after the
    untap step it protects — so the creature survives that turn's alternation
    and phases out on the next one.
    """
    game, fam = _w2g3c_familiar(set_pool, None)
    _w2g3c_turn(game, 0)          # phases out
    _w2g3c_turn(game, 1)
    _w2g3c_turn(game, 0)          # phases in
    result = game.activate_permanent_ability(0, "Ertai's Familiar")
    assert result.supported, result
    _w2g3c_resolve(game)
    assert fam.metadata["cant_phase_out"] == [
        {"duration": "your_next_upkeep", "seat": 0}
    ]
    milled = len(game.players[0].graveyard)

    _w2g3c_turn(game, 1)
    _w2g3c_turn(game, 0)          # the protected untap step

    assert game.players[0].phased_out == [], game.log
    assert fam in game.players[0].battlefield
    assert len(game.players[0].graveyard) == milled, game.log
    # The upkeep of that same turn is what ends it (CR 611.2's stated duration).
    assert "cant_phase_out" not in fam.metadata

    _w2g3c_turn(game, 1)
    _w2g3c_turn(game, 0)

    assert [p.card.name for p in game.players[0].phased_out] == [
        "Ertai's Familiar"
    ], game.log
    assert len(game.players[0].graveyard) - milled == 3


def _w2g3c_bone_dancer(set_pool, defender_graveyard, interactive=(0,)):
    """Bone Dancer attacking unblocked into a seat whose graveyard holds
    *defender_graveyard*, stopped with the offer owed.

    The seat is interactive on purpose: a non-interactive one *declines* the
    offer by default, so a test written without this proves only that the
    decline branch runs.
    """
    dancer = _w2g3c_nosick(Permanent(card=set_pool("WTH")["Bone Dancer"]))
    defender = PlayerState(name="P2")
    defender.graveyard = list(defender_graveyard)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[dancer]), defender,
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare blockers
    # CR 509.1h: a creature becomes unblocked as blocks are declared, so the
    # trigger is announced when this step *ends*.
    game.advance_combat_phase()
    _w2g3c_settle(game)
    return game, dancer, defender


def _w2g3c_settle(game: Game) -> None:
    """Resolve until the stack is empty **or** a seat is owed a decision.

    Never a bare ``while game.stack`` — a prompt armed part-way through a
    resolution holds the object on the stack (CR 608.2), so that loop spins.
    """
    for _ in range(40):
        if not game.stack or game.waiting_prompt:
            break
        game.resolve_top_of_stack()
    game._settle()


def test_bone_dancer_reanimates_the_top_creature_card_under_your_control(set_pool):
    """"…you may put **the top creature card of defending player's graveyard**
    onto the battlefield **under your control**."

    Three things at once, and each is a way the sentence could be read smaller.
    The pile is the *defending player's* (CR 506.2), frozen by the combat fire
    site. The card is the creature card **nearest the top**, not the top card if
    it happens to be a creature — so the artifact sitting above it is skipped
    rather than blocking the ability. And the creature arrives on the
    **attacker's** side: CR 404.1 puts a card in its owner's graveyard, so the
    default arrival under CR 400.3 would hand it straight back.
    """
    program = compile_card_oracle(set_pool("WTH")["Bone Dancer"])
    assert program.supported, program.reason
    (trig,) = program.triggered_abilities
    assert trig.condition.kind == "attacks_unblocked"
    (action,) = trig.instruction.payload["action"]
    assert action.kind == "reanimate_graveyard_position"
    assert action.payload["graveyard_owner"] == "defending_player"
    assert action.payload["position"] == "top"

    land = CardDefinition(
        name="Dead Land", mana_cost="", cmc=0.0, type_line="Land",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Dead Land", "type_line": "Land"},
    )
    rock = CardDefinition(
        name="Dead Rock", mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Dead Rock", "type_line": "Artifact"},
    )
    game, dancer, defender = _w2g3c_bone_dancer(
        set_pool, [land, _w2g3c_creature("Dead Ogre", 3, 3), rock],
    )
    assert game.confirm_optional_pay(0, "Bone Dancer", accept=True), game.log
    _w2g3c_settle(game)

    assert [p.card.name for p in game.players[0].battlefield] == [
        "Bone Dancer", "Dead Ogre",
    ], game.log
    assert [c.name for c in defender.graveyard] == ["Dead Land", "Dead Rock"]
    assert not defender.battlefield


def test_bone_dancer_assigns_no_combat_damage_after_it_reanimates(set_pool):
    """"If you do, this creature assigns no combat damage this turn."

    The half that is a *restriction*, and the only kind of thing this engine
    calls a bug when nothing enforces it: unenforced, Bone Dancer would
    reanimate a creature **and** connect for two, which is a strictly better
    card than the one printed and nothing anywhere would look wrong.

    Asserted through the defender's life rather than through the marker alone,
    because a marker nothing reads is exactly the failure being tested for.
    """
    game, dancer, defender = _w2g3c_bone_dancer(
        set_pool, [_w2g3c_creature("Dead Ogre", 3, 3)],
    )
    assert game.confirm_optional_pay(0, "Bone Dancer", accept=True), game.log
    _w2g3c_settle(game)
    assert dancer.metadata.get("assigns_no_combat_damage_until_eot")

    life = defender.life
    game.advance_combat_phase()   # combat damage
    _w2g3c_settle(game)

    assert defender.life == life, game.log


def test_bone_dancer_that_declines_deals_its_damage(set_pool):
    """The other branch, and the control on the one above: the restriction is
    the *consequence* of the reanimation, not a property of the attack."""
    game, dancer, defender = _w2g3c_bone_dancer(
        set_pool, [_w2g3c_creature("Dead Ogre", 3, 3)],
    )
    assert game.confirm_optional_pay(0, "Bone Dancer", accept=False), game.log
    _w2g3c_settle(game)

    assert [p.card.name for p in game.players[0].battlefield] == ["Bone Dancer"]
    assert not dancer.metadata.get("assigns_no_combat_damage_until_eot")

    life = defender.life
    game.advance_combat_phase()   # combat damage
    _w2g3c_settle(game)

    assert defender.life == life - 2, game.log


def test_bone_dancer_finds_nothing_in_a_graveyard_with_no_creature_card(set_pool):
    """The printed noun narrows the pile, and a dropped narrowing is a card
    reanimating a land.

    **The offer is not made at all**, which is what changed at EXO wave 1 and
    is why this test now asserts a refusal where it used to accept. When this
    was written, taking the offer over a pile with nothing in it reanimated
    nothing *and* still set ``assigns_no_combat_damage_until_eot`` — the
    "if you do" rider firing on an action that did not happen, which the round
    recorded in SET_PLAYBOOK.md's Known gaps rather than fixing.
    ``control_flow._action_is_takeable`` now answers for this kind, so CR 601.2
    never offers a choice nobody could take and ``confirm_optional_pay`` finds
    no prompt to answer. The subject of the test is unchanged: the narrowing is
    read, and the land stays where it is.
    """
    land = CardDefinition(
        name="Dead Land", mana_cost="", cmc=0.0, type_line="Land",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Dead Land", "type_line": "Land"},
    )
    game, dancer, defender = _w2g3c_bone_dancer(set_pool, [land, land])
    assert not game.confirm_optional_pay(0, "Bone Dancer", accept=True)
    _w2g3c_settle(game)

    assert [p.card.name for p in game.players[0].battlefield] == ["Bone Dancer"]
    assert len(defender.graveyard) == 2
    assert not dancer.metadata.get("assigns_no_combat_damage_until_eot")

"""Urza's Legacy artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: combat restrictions — who may attack, who may block ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _g4_body(
    name: str, power: int = 1, toughness: int = 1,
    type_line: str = "Creature - Test",
) -> CardDefinition:
    """A vanilla prop. Its own name and its own ending, per this file's header:
    a helper whose last lines match another block's helper is what a mechanical
    union splices."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
        # Keyword-free and text-free on purpose: what these tests measure is the
        # restriction printed on somebody else's permanent.
    )


def _g4_three_seat_combat(set_pool, *, crawlspaces_on: tuple[int, ...] = ()):
    """Seat 0 attacks; seats 1 and 2 defend. Four attackers, and a Crawlspace on
    each seat named. Stops at declare_attackers."""
    attackers = [Permanent(card=_g4_body(f"Attacker {i}")) for i in range(4)]
    seats = [PlayerState(name="P1", battlefield=attackers)]
    for index in (1, 2):
        board = []
        if index in crawlspaces_on:
            board.append(Permanent(card=set_pool("ULG")["Crawlspace"]))
        seats.append(PlayerState(name=f"P{index + 1}", battlefield=board))
    game = Game(players=seats)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    return game


def test_crawlspace_caps_the_attackers_aimed_at_its_controller(set_pool):
    """"No more than two creatures can attack you each combat." Three attackers
    at the Crawlspace's seat is illegal; two is not."""
    game = _g4_three_seat_combat(set_pool, crawlspaces_on=(1,))

    ok, msg = game.declare_attackers(
        0, [0, 1, 2], attacker_targets={0: 1, 1: 1, 2: 1}
    )
    assert not ok
    assert "no more than 2 creature(s) can attack P2" in msg

    ok, msg = game.declare_attackers(0, [0, 1], attacker_targets={0: 1, 1: 1})
    assert ok, msg


def test_crawlspace_is_per_defender_and_not_a_cap_on_the_declaration(set_pool):
    """The whole of what separates this card from Caverns of Despair, and the
    only board that can tell them apart: three attackers, two at the Crawlspace's
    seat and one at the other. Caverns' cap counts the declaration entire and
    would refuse this; Crawlspace counts one seat's attackers and must not."""
    game = _g4_three_seat_combat(set_pool, crawlspaces_on=(1,))

    ok, msg = game.declare_attackers(
        0, [0, 1, 2], attacker_targets={0: 1, 1: 1, 2: 2}
    )
    assert ok, msg


def test_crawlspace_protects_only_the_seat_that_controls_it(set_pool):
    """CR 109.5: "you" is the permanent's controller. Three attackers at the
    seat *without* one are unaffected."""
    game = _g4_three_seat_combat(set_pool, crawlspaces_on=(1,))

    ok, msg = game.declare_attackers(
        0, [0, 1, 2], attacker_targets={0: 2, 1: 2, 2: 2}
    )
    assert ok, msg


def test_two_crawlspaces_on_one_seat_take_the_smaller_cap(set_pool):
    """Both print two, so the pair is still two — the point being that the cap
    is read off the board rather than counted per permanent, which a sum would
    turn into four."""
    game = _g4_three_seat_combat(set_pool, crawlspaces_on=(1,))
    game.players[1].battlefield.append(
        Permanent(card=set_pool("ULG")["Crawlspace"])
    )

    ok, msg = game.declare_attackers(
        0, [0, 1, 2], attacker_targets={0: 1, 1: 1, 2: 1}
    )
    assert not ok, msg


def test_crawlspace_does_not_count_an_attack_on_a_planeswalker(set_pool):
    """CR 508.1b: attacking a planeswalker its controller has is not attacking
    them, and the card says "attack **you**". Two creatures at the player plus
    one at their planeswalker is three attackers and two attacks on the seat."""
    game = _g4_three_seat_combat(set_pool, crawlspaces_on=(1,))
    walker = Permanent(
        card=_g4_body("Test Walker", type_line="Legendary Planeswalker - Test")
    )
    walker.metadata["loyalty_counters"] = 4
    game.players[1].battlefield.append(walker)

    ok, msg = game.declare_attackers(
        0, [0, 1, 2],
        attacker_targets={0: 1, 1: 1},
        attacker_planeswalker_ids={2: walker.permanent_id},
    )
    assert ok, msg


def test_a_required_attacker_is_not_owed_where_every_seat_is_capped(set_pool):
    """CR 508.1d obeys requirements *subject to* the restrictions. With a
    Crawlspace on both defenders and two attackers aimed at each, a creature
    that "attacks each combat if able" is under no obligation the declaration
    could satisfy — enforcing it anyway would make every declaration illegal."""
    game = _g4_three_seat_combat(set_pool, crawlspaces_on=(1, 2))
    compelled = Permanent(card=CardDefinition(
        name="Eager Ox", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="This creature attacks each combat if able.",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Eager Ox", "type_line": "Creature - Test",
             "power": "1", "toughness": "1"},
    ))
    game.players[0].battlefield.append(compelled)

    ok, msg = game.declare_attackers(
        0, [0, 1, 2, 3], attacker_targets={0: 1, 1: 1, 2: 2, 3: 2}
    )
    assert ok, msg


# --- W1G1: a quantity the sentence that spends it produced ---
#
# Angel's Trumpet — "All creatures have vigilance. At the beginning of each
# player's end step, tap all untapped creatures that player controls that
# didn't attack this turn. This artifact deals damage to the player equal to
# the number of creatures tapped this way."
#
# The card read *supported* before this round on its vigilance line alone: the
# trigger compiled an ability part with no instruction behind it, which is what
# `support_report --hollow-lines` and `parse_coverage --set ULG` were both
# reporting about the same sentence.

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack as _g1a_resolve


def _g1a_table(set_pool, *, mine=(), theirs=()):
    """Angel's Trumpet under seat 0, the named creatures on each board.

    ``_g1a_`` prefixed and ending on ``return game, game.players[0], game.players[1]``
    — SET_PLAYBOOK.md's note about a union splicing one helper onto another.
    """
    seat0 = PlayerState(
        name="G1A-A",
        battlefield=[Permanent(card=set_pool("ULG")["Angel's Trumpet"])] + list(mine),
    )
    seat1 = PlayerState(name="G1A-B", battlefield=list(theirs))
    game = Game(players=[seat0, seat1])
    game.enforce_mana_costs = False
    return game, game.players[0], game.players[1]


def _g1a_bear(set_pool, *, tapped=False, attacked=False):
    """One Grizzly Bears in the state the sentence's two narrowings care about.
    Ends on ``return bear`` so no union can graft another helper onto it."""
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    bear.tapped = tapped
    if attacked:
        bear.metadata["attacked_this_turn"] = True
    return bear


def test_g1_angels_trumpet_damages_for_what_it_tapped(set_pool):
    """CR 603.10 freezes whose end step this is; the damage is the count the tap
    in front of it recorded, not the board's tally of tapped creatures."""
    game, mine, theirs = _g1a_table(
        set_pool,
        mine=[_g1a_bear(set_pool)],
        theirs=[_g1a_bear(set_pool), _g1a_bear(set_pool)],
    )
    game.active_player_index = 1

    game.resolve_end_step(1)
    _g1a_resolve(game)
    game._settle()

    assert theirs.life == 18, "two untapped creatures tapped, two damage"
    assert mine.life == 20, "it is not their end step"
    assert all(p.tapped for p in game.controlled_by(1))
    assert not any(
        p.tapped for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"
    )


def test_g1_angels_trumpet_counts_only_the_creatures_it_tapped(set_pool):
    """"…tapped **this way**." One of the three was already tapped and one
    attacked, so the board holds three tapped creatures afterwards and the
    damage is one — the board's count is the wrong number, always the larger."""
    game, mine, theirs = _g1a_table(
        set_pool,
        theirs=[
            _g1a_bear(set_pool),
            _g1a_bear(set_pool, tapped=True),
            _g1a_bear(set_pool, attacked=True),
        ],
    )
    game.active_player_index = 1

    game.resolve_end_step(1)
    _g1a_resolve(game)
    game._settle()

    assert theirs.life == 19
    assert len([p for p in game.controlled_by(1) if p.tapped]) == 2, (
        "the attacker keeps its vigilance-untapped state and is not tapped here"
    )


def test_g1_angels_trumpet_deals_nothing_when_it_taps_nothing(set_pool):
    """A seat whose only creature attacked has nothing the sweep may turn, so
    the count is zero and CR 120.8 makes that no damage at all."""
    game, mine, theirs = _g1a_table(
        set_pool, theirs=[_g1a_bear(set_pool, attacked=True)],
    )
    game.active_player_index = 1

    game.resolve_end_step(1)
    _g1a_resolve(game)
    game._settle()

    assert theirs.life == 20


def test_g1_angels_trumpet_still_grants_vigilance(set_pool):
    """The card's other line, asserted because it was the only reason the card
    reported supported before this round — a change to the trigger must not have
    taken it with it."""
    game, _mine, _theirs = _g1a_table(set_pool, mine=[_g1a_bear(set_pool)])
    game._settle()

    bear = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert game._has_keyword(bear, "vigilance"), (
        "CR 613 layer 6, which is the only accessor that sees a board-wide grant"
    )


# --- W1G5: zones — hands, graveyards, libraries ---
from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack


def _g5_jar_board(pool, lea, first_hand, second_hand) -> Game:
    """Memory Jar on seat 0's battlefield, both seats holding what is named.

    The libraries are deep enough for two sevens; the artifact is unsick because
    its ability taps. Its own tail (the `_sync_control` and the return of the
    permanent) so a mechanical union cannot splice another group's helper body
    onto this signature.
    """
    p1 = PlayerState(name="P1", library=[lea["Mountain"]] * 20, hand=list(first_hand))
    p2 = PlayerState(name="P2", library=[lea["Forest"]] * 20, hand=list(second_hand))
    board = Game(players=[p1, p2])
    board.enforce_mana_costs = False
    board.interactive_seats = set()
    jar = Permanent(card=pool["Memory Jar"])
    jar.metadata["summoning_sickness_turn"] = -99
    board.players[0].battlefield.append(jar)
    board._sync_control()
    return board


def test_w1g5_memory_jar_exiles_every_hand_and_deals_seven(set_pool):
    """"Each player exiles all cards from their hand face down and draws seven
    cards." One act per seat, not the caster's hand alone — the printed subject
    is the whole difference and a dropped one would empty one hand where the
    card empties the table's."""
    pool, lea = set_pool("ULG"), set_pool("LEA")
    game = _g5_jar_board(
        pool, lea, [lea["Black Lotus"], lea["Mox Jet"]], [lea["Healing Salve"]],
    )

    result = game.activate_permanent_ability(0, "Memory Jar", ability_index=0)
    resolve_stack(game)

    assert result.supported is True
    assert len(game.players[0].hand) == 7
    assert len(game.players[1].hand) == 7
    assert [c.name for c in game.players[0].exile] == ["Black Lotus", "Mox Jet"]
    assert [c.name for c in game.players[1].exile] == ["Healing Salve"]
    # The sacrifice was a cost, so the artifact is gone before anything resolved.
    assert game.players[0].battlefield == []
    assert [t.event for t in game.delayed_triggers] == ["next_end_step"]


def test_w1g5_memory_jar_gives_each_seat_back_its_own_pile_at_the_next_end_step(
    set_pool,
):
    """CR 603.7's delayed ability, and the half that could only go wrong one
    way: "each card **they** exiled this way" is asked once per player, so a
    flat record read once per seat would hand each of them the whole table's
    hands.

    The record survives the delay because the creating resolution's scratchpad
    is frozen onto the entry (CR 603.7d) — which is what makes this reachable at
    all, since the artifact was sacrificed as a cost and no permanent is left to
    hang a linked pile on.
    """
    pool, lea = set_pool("ULG"), set_pool("LEA")
    game = _g5_jar_board(
        pool, lea, [lea["Black Lotus"], lea["Mox Jet"]], [lea["Healing Salve"]],
    )
    game.activate_permanent_ability(0, "Memory Jar", ability_index=0)
    resolve_stack(game)

    game.resolve_end_step(0)
    resolve_stack(game)

    assert [c.name for c in game.players[0].hand] == ["Black Lotus", "Mox Jet"]
    assert [c.name for c in game.players[1].hand] == ["Healing Salve"]
    assert game.players[0].exile == []
    assert game.players[1].exile == []
    # The seven drawn cards were discarded, and Memory Jar itself is in the
    # graveyard it was sacrificed into.
    assert len(game.players[0].graveyard) == 8
    assert len(game.players[1].graveyard) == 7


def test_w1g5_memory_jar_still_deals_seven_to_a_seat_that_held_nothing(set_pool):
    """An empty hand exiles nothing and draws seven anyway — CR 608.2 does as
    much as it can, and the two halves of the sentence are not conditional on
    each other."""
    pool, lea = set_pool("ULG"), set_pool("LEA")
    game = _g5_jar_board(pool, lea, [lea["Black Lotus"]], [])

    game.activate_permanent_ability(0, "Memory Jar", ability_index=0)
    resolve_stack(game)

    assert len(game.players[1].hand) == 7
    assert game.players[1].exile == []

    game.resolve_end_step(0)
    resolve_stack(game)

    # Nothing came back for the seat that exiled nothing; its hand is empty.
    assert game.players[1].hand == []
    assert [c.name for c in game.players[0].hand] == ["Black Lotus"]


# --- W2G2: three artifacts that change what everyone may do ---
#
# Thran Lens     CR 613 layer 5 with no colour in it (CR 105.2c)
# Defense Grid   a CR 601.2f tax with a timing condition on it
# Damping Engine CR 601.3a over a seat the board names, plus CR 116.2d's way out
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import CardDefinition, Permanent
from engine.special_actions import (available_permanent_special_actions,
                                    take_permanent_special_action)


def _w2g2_prop(name: str, type_line: str = "Artifact") -> CardDefinition:
    """A text-free permanent to make up a permanent count with. Its own name
    and its own ending, per this file's header."""
    return CardDefinition(
        name=name, mana_cost="{0}", cmc=0.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": type_line},
    )


def _w2g2_pool():
    """Every card in both manifest roles, for the handful of props these tests
    borrow from other sets (a Bad Moon to read a colour, a Lightning Bolt to
    pay a tax with). `set_pool("ULG")` stays the source of the ULG cards."""
    return {c.name: c for c in load_cards(manifest_set_paths(include_measured=True))}


# --- Thran Lens: "All permanents are colorless." ---------------------------


def test_w2g2_thran_lens_takes_the_colour_off_every_permanent(set_pool):
    """CR 613 layer 5, and CR 105.2c: colourless is not a sixth colour, it is
    the absence of all five — so the answer is an empty set and not a word."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    zombies = Permanent(card=catalog["Scathe Zombies"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[zombies]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game._sync_control()
    game.start_turn(0)
    assert zombies.effective_colors == {"B"}

    game.players[1].battlefield.append(Permanent(card=pool["Thran Lens"]))
    game._sync_control()
    game._recompute_continuous_effects()

    assert zombies.effective_colors == set()


def test_w2g2_thran_lens_makes_a_colour_narrowed_anthem_stop_applying(set_pool):
    """The colour has to be *read*, not merely stored. Bad Moon buffs black
    creatures through `subject_matches`, which asks layer 5 — so a Lens on the
    board is the difference between a 3/3 and a 2/2, and a colour change
    nothing consulted would leave the Zombies buffed."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    zombies = Permanent(card=catalog["Scathe Zombies"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[
            Permanent(card=catalog["Bad Moon"]), zombies,
        ]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game._sync_control()
    game.start_turn(0)
    assert (zombies.effective_power, zombies.effective_toughness) == (3, 3)

    game.players[0].battlefield.append(Permanent(card=pool["Thran Lens"]))
    game._sync_control()
    game._recompute_continuous_effects()

    assert (zombies.effective_power, zombies.effective_toughness) == (2, 2)


def test_w2g2_thran_lens_says_nothing_about_a_card_off_the_battlefield(set_pool):
    """"All **permanents**" — CR 109.2's noun is about the battlefield, so a
    card in a hand keeps its printed colour. Celestial Dawn is the card that
    reaches further, and it says so in a second printed sentence; reading this
    one that way would recolour a hand on the strength of a sentence about the
    board."""
    from engine.object_colors import card_colors

    pool, catalog = set_pool("ULG"), _w2g2_pool()
    bolt = catalog["Lightning Bolt"]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[Permanent(card=pool["Thran Lens"])],
                    hand=[bolt]),
        PlayerState(name="P2"),
    ])
    game._sync_control()
    game.start_turn(0)

    assert card_colors(game, bolt, game.players[0]) == ("R",)


def test_w2g2_thran_lens_reaches_its_own_controller_and_the_opponent(set_pool):
    """The sentence names no seat, so it binds every battlefield — its own
    included. A scope skipping the source is what
    `_apply_global_statics` records having been wrong before."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    lens = Permanent(card=pool["Thran Lens"])
    mine = Permanent(card=catalog["Bad Moon"])
    theirs = Permanent(card=catalog["Scathe Zombies"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[lens, mine]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game._sync_control()
    game.start_turn(0)

    assert lens.effective_colors == set()
    assert mine.effective_colors == set()
    assert theirs.effective_colors == set()


# --- Defense Grid: a tax with a timing condition ---------------------------


def _w2g2_grid_board(pool, catalog, *, grid: bool, active: int, pool_mana: dict):
    """P2 holds a Lightning Bolt; *active* takes the turn. Mana is put in the
    pool rather than on lands because casting spends the pool (CR 601.2g/h) —
    a land is not a payment until it is tapped."""
    board = [Permanent(card=pool["Defense Grid"])] if grid else []
    game = Game(players=[
        PlayerState(name="P1", battlefield=board),
        PlayerState(name="P2", hand=[catalog["Lightning Bolt"]]),
    ])
    game._sync_control()
    game.start_turn(active)
    game.enforce_mana_costs = True
    game.players[1].mana_pool.update(pool_mana)
    return game


def test_w2g2_defense_grid_taxes_a_spell_cast_on_somebody_elses_turn(set_pool):
    """CR 601.2f. {R} alone no longer pays for a Bolt on P1's turn, and the
    Grid is named in the log so the charge is attributable."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_grid_board(pool, catalog, grid=True, active=0,
                            pool_mana={"R": 1, "C": 2})

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert result.supported is False
    assert "insufficient mana" in result.details
    assert any("taxed by Defense Grid" in line for line in game.log)
    assert any(c.name == "Lightning Bolt" for c in game.players[1].hand)


def test_w2g2_defense_grid_charges_exactly_three_generic(set_pool):
    """CR 118.7: the tax is generic, so one more colourless pays it — and the
    pool is emptied to the symbol, which is what says the {3} was really
    charged rather than waived."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_grid_board(pool, catalog, grid=True, active=0,
                            pool_mana={"R": 1, "C": 3})

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert result.supported is True, result.details
    assert game.players[1].mana_pool["C"] == 0
    assert game.players[1].mana_pool["R"] == 0


def test_w2g2_defense_grid_leaves_a_spell_alone_on_its_controllers_turn(set_pool):
    """"…except during **its controller's** turn" is CR 109.5's controller of
    the *spell*, which at CR 601.2f is the caster — not the Grid's own
    controller. Read the other way round this card is backwards."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_grid_board(pool, catalog, grid=True, active=1,
                            pool_mana={"R": 1})

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert result.supported is True, result.details
    assert not any("taxed by Defense Grid" in line for line in game.log)


def test_w2g2_defense_grid_taxes_its_own_controller_too(set_pool):
    """"**Each** spell" names no seat, so the Grid's own player pays it on
    everybody else's turn. A tax scoped to opponents would be a different and
    much better card."""
    from engine.cost_modifiers import spell_cost_tax

    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = Game(players=[
        PlayerState(name="P1", battlefield=[Permanent(card=pool["Defense Grid"])]),
        PlayerState(name="P2"),
    ])
    game._sync_control()
    game.start_turn(1)

    assert spell_cost_tax(game, 0, catalog["Lightning Bolt"]) == (
        3, ["Defense Grid"]
    )
    assert spell_cost_tax(game, 1, catalog["Lightning Bolt"]) == (0, [])


def test_w2g2_the_each_spell_quantifier_needs_its_verb_to_agree():
    """"Each spell costs" and "spells cost" are two printed spellings of one
    set (CR 109.2); "**this** spell costs {1} more to cast for each target
    beyond the first" is a sentence about one object, and Fireball's surcharge
    is charged in `mixins/stack/` instead. Widening the noun to `spells?` makes
    the second *match* this pattern part-way through, so the agreement check is
    the only thing between it and a tax on every spell in the game."""
    from engine.cost_modifiers import cost_modifiers_for

    assert cost_modifiers_for(
        "this spell costs {1} more to cast for each target beyond the first"
    ) == ()
    assert cost_modifiers_for("each spells cost {3} more to cast") == ()
    assert cost_modifiers_for("each spell cost {3} more to cast") == ()
    (unquantified,) = cost_modifiers_for("spells cost {1} more to cast")
    assert unquantified.amount == 1 and not unquantified.off_controllers_turn


# --- Damping Engine: CR 601.3a over a derived seat, and CR 116.2d ----------


def _w2g2_engine_board(pool, catalog, *, spare_for_p1: int, engine_seat: int = 0):
    """Seat 0 holds `spare_for_p1` props beyond the Engine; seat 1 holds one
    Forest. Seat 0 is active and has a creature, a land and an instant in hand.
    Its own ending, per this file's header."""
    engine = [Permanent(card=pool["Damping Engine"])]
    props = [Permanent(card=_w2g2_prop(f"Prop {i}")) for i in range(spare_for_p1)]
    first = (engine if engine_seat == 0 else []) + props
    second = ([] if engine_seat == 0 else engine) + [
        Permanent(card=catalog["Forest"])
    ]
    game = Game(players=[
        PlayerState(name="P1", battlefield=first,
                    hand=[catalog["Grizzly Bears"], catalog["Forest"],
                          catalog["Lightning Bolt"]]),
        PlayerState(name="P2", battlefield=second,
                    hand=[catalog["Grizzly Bears"]]),
    ])
    game._sync_control()
    game.start_turn(0)
    return game


def test_w2g2_damping_engine_stops_the_leader_casting_and_playing_lands(set_pool):
    """CR 601.3a for the cast half and CR 305.1 for the land half — one printed
    sentence, so claiming only one of them would ship an artifact that stops a
    Grizzly Bears and lets the same player's Forest through."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_engine_board(pool, catalog, spare_for_p1=2)

    result = game.cast_from_hand(0, "Grizzly Bears")

    assert result.supported is False
    assert "Damping Engine" in result.details
    refusal = game._land_play_refusal(0)
    assert refusal is not None and "Damping Engine" in refusal
    # The seat that is behind is untouched by either half.
    assert game._land_play_refusal(1) is None


def test_w2g2_damping_engine_names_only_the_printed_types(set_pool):
    """"artifact, creature, or enchantment spells" — an instant is not on the
    list, and the types are payload rather than part of the template."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_engine_board(pool, catalog, spare_for_p1=2)

    result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

    assert result.supported is True, result.details


def test_w2g2_damping_engine_names_nobody_on_a_tie(set_pool):
    """"**more** permanents than each other player" is strict, so a level board
    is a board the Engine does nothing on — the same reading `most_life_seat`
    already makes of the identical superlative."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_engine_board(pool, catalog, spare_for_p1=0)

    assert [sum(1 for _ in game.controlled_by(i)) for i in range(2)] == [1, 1]
    assert game._land_play_refusal(0) is None
    assert game.cast_from_hand(0, "Grizzly Bears").supported is True
    # …and the Bears breaks the tie, so the next question is answered the other
    # way. The comparison is asked of the board every time, not frozen at the
    # start of the turn.
    assert [sum(1 for _ in game.controlled_by(i)) for i in range(2)] == [2, 1]
    refusal = game._land_play_refusal(0)
    assert refusal is not None and "Damping Engine" in refusal


def test_w2g2_damping_engine_binds_the_seat_that_does_not_control_it(set_pool):
    """The sentence names nobody's side, so the Engine stops whichever player
    is ahead — its controller included, and an opponent just as readily."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_engine_board(pool, catalog, spare_for_p1=3, engine_seat=1)

    assert [sum(1 for _ in game.controlled_by(i)) for i in range(2)] == [3, 2]
    result = game.cast_from_hand(0, "Grizzly Bears")

    assert result.supported is False
    assert "Damping Engine" in result.details


def test_w2g2_damping_engine_offers_its_escape_hatch_only_to_the_leader(set_pool):
    """CR 116.2d: "Some effects from static abilities allow a player to take an
    action to ignore the effect from that ability for a duration." The offer is
    made to the player the *first* sentence described, not to the Engine's
    controller — so the seat that is behind is offered nothing."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_engine_board(pool, catalog, spare_for_p1=3, engine_seat=1)

    offers = available_permanent_special_actions(game, 0)
    assert [entry["kind"] for entry in offers] == [
        "ignore_board_static_until_eot"
    ]
    assert offers[0]["name"] == "Damping Engine"
    assert available_permanent_special_actions(game, 1) == []


def test_w2g2_damping_engine_escape_hatch_costs_a_permanent_and_lasts_a_turn(
    set_pool,
):
    """The sacrifice is a cost paid by the seam (CR 116.2d), the relief lasts
    until end of turn, and it is offered once: a second purchase would buy a
    turn already bought."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_engine_board(pool, catalog, spare_for_p1=2)
    engine = next(p for p in game.all_permanents()
                  if p.card.name == "Damping Engine")
    victim = next(p for p in game.controlled_by(0) if p.card.name == "Prop 0")

    refusal = take_permanent_special_action(
        game, 0, engine, "ignore_board_static_until_eot", sacrificed=victim,
    )

    assert refusal is None, refusal
    assert not any(p is victim for p in game.all_permanents())
    assert game.cast_from_hand(0, "Grizzly Bears").supported is True
    assert game._land_play_refusal(0) is None
    assert available_permanent_special_actions(game, 0) == []


def test_w2g2_damping_engine_relief_ends_at_the_cleanup_step(set_pool):
    """CR 514.2. "Until end of turn" is one moment however the offer was
    shaped, which is why the record is swept beside Volrath's Curse's."""
    pool, catalog = set_pool("ULG"), _w2g2_pool()
    game = _w2g2_engine_board(pool, catalog, spare_for_p1=3)
    engine = next(p for p in game.all_permanents()
                  if p.card.name == "Damping Engine")
    victim = next(p for p in game.controlled_by(0) if p.card.name == "Prop 0")
    take_permanent_special_action(
        game, 0, engine, "ignore_board_static_until_eot", sacrificed=victim,
    )
    assert game._land_play_refusal(0) is None

    game.resolve_cleanup_step(0)

    refusal = game._land_play_refusal(0)
    assert refusal is not None and "Damping Engine" in refusal


def test_w2g2_damping_engines_two_sentences_are_read_together(set_pool):
    """One line, two tables. The offer half is read by the table that
    *performs* it rather than by a copy of its sentence in the prohibition's
    reader, so the claim and the offer cannot come to describe different words
    — and a trailing sentence neither table reads takes the whole line with it,
    which is what stops a longer printing being admitted on its first half."""
    from engine.cast_restrictions import most_permanents_play_ban_line
    from engine.special_actions import permanent_special_action_sentence

    printed = set_pool("ULG")["Damping Engine"].oracle_text
    assert most_permanents_play_ban_line(printed) == (
        "artifact", "creature", "enchantment",
    )
    prohibition, offer = [s.strip() for s in printed.split(".") if s.strip()]
    assert permanent_special_action_sentence(offer) == (
        "ignore_board_static_until_eot", {},
    )
    assert most_permanents_play_ban_line(
        prohibition + ". This artifact enters the battlefield tapped."
    ) is None


def test_w2g2_the_escape_hatch_is_not_inferred_from_the_prohibition(set_pool):
    """A printing of the first sentence alone is a complete, harsher effect and
    is enforced as one — but it makes no CR 116.2d offer, because the offer is
    a printed sentence and not a consequence of the restriction. Inferred, this
    module would hand back what such a card took."""
    from engine.cast_restrictions import most_permanents_play_ban_line

    pool, catalog = set_pool("ULG"), _w2g2_pool()
    printed = pool["Damping Engine"].oracle_text
    prohibition = printed.split(".")[0].strip() + "."
    assert most_permanents_play_ban_line(prohibition) == (
        "artifact", "creature", "enchantment",
    )
    harsher = CardDefinition(
        name="Damping Engine Prototype", mana_cost="{4}", cmc=4.0,
        type_line="Artifact", oracle_text=prohibition, colors=(),
        color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Damping Engine Prototype", "type_line": "Artifact"},
    )
    game = Game(players=[
        PlayerState(name="P1", battlefield=[
            Permanent(card=harsher), Permanent(card=_w2g2_prop("Prop A")),
        ], hand=[catalog["Grizzly Bears"]]),
        PlayerState(name="P2", battlefield=[Permanent(card=catalog["Forest"])]),
    ])
    game._sync_control()
    game.start_turn(0)

    assert game.cast_from_hand(0, "Grizzly Bears").supported is False
    assert available_permanent_special_actions(game, 0) == []

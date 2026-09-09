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

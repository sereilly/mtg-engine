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

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

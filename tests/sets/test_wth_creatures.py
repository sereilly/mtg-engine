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

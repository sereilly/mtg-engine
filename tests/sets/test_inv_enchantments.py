"""Invasion enchantments.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: colour relations ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import CardDefinition as _W1G5Card, Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import _damage_dealt as _w1g5_damage_dealt
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_creature(name, power, toughness, colors=(), text="", type_line="Creature - Test"):
    """A bare creature of the given colours — the only thing these cards ask
    of the objects around them."""
    cost = "".join("{%s}" % symbol for symbol in colors) or "{2}"
    return _W1G5Card(
        name=name, mana_cost=cost, cmc=float(max(1, len(colors))),
        type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )  # W1G5 enchantments: a coloured test creature


def _w1g5_table(mine, theirs, *, hand0=(), hand1=()):
    """Seat 0 active in its precombat main phase; both boards placed, nothing
    summoning sick. Returns the game and the two boards' permanents."""
    board0 = [_W1G5Permanent(card=card) for card in mine]
    board1 = [_W1G5Permanent(card=card) for card in theirs]
    island = _W1G5Card(
        name="Island", mana_cost="", cmc=0.0, type_line="Basic Land - Island",
        oracle_text="({T}: Add {U}.)", colors=(), color_identity=("U",),
        keywords=(), produced_mana=("U",),
        raw={"name": "Island", "type_line": "Basic Land - Island"},
    )
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="P0", battlefield=board0, hand=list(hand0),
                         library=[island] * 10),
        _W1G5PlayerState(name="P1", battlefield=board1, hand=list(hand1),
                         library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, board0, board1  # W1G5 enchantments: the table


def _w1g5_fight(game, attacker_slot, blocker_slot=None):
    """Seat 0 attacks with *attacker_slot*; seat 1 blocks it with
    *blocker_slot* (or not at all); combat runs to the second main phase."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(0, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocks = {} if blocker_slot is None else {blocker_slot: attacker_slot}
    blocked = game.declare_blockers(1, blocks)
    assert blocked[0], blocked
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G5: combat over


# --- Well-Laid Plans -------------------------------------------------------
# "Prevent all damage that would be dealt to a creature by another creature if
# they share a color." A static blanket whose narrowing is a relation between
# the two ends of the damage event, held to each printed word in turn.


def test_w1g5_well_laid_plans_stops_two_white_creatures_trading(set_pool):
    """A real combat: white attacker, white blocker, both 2/2. Each would kill
    the other; under the Plans neither is touched (CR 615.1), in both
    directions of the one fight."""
    plans = set_pool("INV")["Well-Laid Plans"]
    assert _w1g5_compile(plans).supported
    game, (_plans, attacker), (blocker,) = _w1g5_table(
        [plans, _w1g5_creature("Knight", 2, 2, ("W",))],
        [_w1g5_creature("Squire", 2, 2, ("W",))],
    )
    _w1g5_fight(game, attacker_slot=1, blocker_slot=0)

    assert game.is_on_battlefield(attacker) and game.is_on_battlefield(blocker)
    assert attacker.damage_marked == 0 and blocker.damage_marked == 0
    assert any("they share a color (Well-Laid Plans)" in line for line in game.log)


def test_w1g5_well_laid_plans_lets_differently_coloured_creatures_fight(set_pool):
    """The condition is the card: a white attacker and a red blocker share
    nothing, so the same combat kills both."""
    game, (_plans, attacker), (blocker,) = _w1g5_table(
        [set_pool("INV")["Well-Laid Plans"], _w1g5_creature("Knight", 2, 2, ("W",))],
        [_w1g5_creature("Raider", 2, 2, ("R",))],
    )
    _w1g5_fight(game, attacker_slot=1, blocker_slot=0)

    assert not game.is_on_battlefield(attacker)
    assert not game.is_on_battlefield(blocker)


def test_w1g5_well_laid_plans_reads_each_printed_word(set_pool):
    """One event per narrowing. A multicoloured creature shares with either of
    its colours (CR 105.2b); a colourless one shares with nothing, another
    colourless one included (CR 105.2c); a player is not a creature; a spell
    is not "another creature"; and the Plans' controller is nobody special —
    an opponent's creatures are covered too."""
    game, (_plans, white, gold, golem), (blue, rock) = _w1g5_table(
        [
            set_pool("INV")["Well-Laid Plans"],
            _w1g5_creature("Knight", 2, 2, ("W",)),
            _w1g5_creature("Envoy", 2, 2, ("W", "U")),
            _w1g5_creature("Golem", 2, 2, (), type_line="Artifact Creature - Golem"),
        ],
        [
            _w1g5_creature("Drake", 2, 2, ("U",)),
            _w1g5_creature("Rock", 2, 2, (), type_line="Artifact Creature - Golem"),
        ],
    )
    # gold shares white with the Knight and blue with the Drake
    assert _w1g5_damage_dealt(game, white, 3, source=gold) == 0
    assert _w1g5_damage_dealt(game, blue, 3, source=gold) == 0
    assert _w1g5_damage_dealt(game, gold, 3, source=blue) == 0
    # white and blue share nothing
    assert _w1g5_damage_dealt(game, blue, 3, source=white) == 3
    # colourless shares with nothing, another colourless creature included
    assert _w1g5_damage_dealt(game, rock, 3, source=golem) == 3
    assert _w1g5_damage_dealt(game, white, 3, source=golem) == 3
    # "to a creature": the face still takes it
    assert _w1g5_damage_dealt(game, game.players[1], 3, source=white) == 3
    # "by another creature": a white spell is not a creature
    bolt = _W1G5Card(
        name="Smite", mana_cost="{W}", cmc=1.0, type_line="Instant",
        oracle_text="", colors=("W",), color_identity=("W",), keywords=(),
        produced_mana=(), raw={"name": "Smite", "type_line": "Instant"},
    )
    assert _w1g5_damage_dealt(game, white, 3, source=bolt) == 3
    # …and the same creature is not "another" one
    assert _w1g5_damage_dealt(game, white, 3, source=white) == 3


def test_w1g5_well_laid_plans_ends_with_the_enchantment(set_pool):
    game, (plans, white, other), _ = _w1g5_table(
        [set_pool("INV")["Well-Laid Plans"],
         _w1g5_creature("Knight", 2, 2, ("W",)),
         _w1g5_creature("Squire", 2, 2, ("W",))],
        [],
    )
    assert _w1g5_damage_dealt(game, white, 2, source=other) == 0
    game.remove_from_battlefield(plans)
    assert _w1g5_damage_dealt(game, white, 2, source=other) == 2


# --- Spirit of Resistance --------------------------------------------------
# "As long as you control a permanent of each color, prevent all damage that
# would be dealt to you." Glacial Chasm's blanket behind CR 611.2's condition.


def _w1g5_rainbow(*, without=()):
    return [
        _w1g5_creature(f"{symbol}-mage", 1, 1, (symbol,))
        for symbol in ("W", "U", "B", "R", "G") if symbol not in without
    ]  # W1G5: one permanent per colour


def test_w1g5_spirit_of_resistance_shields_only_behind_all_five_colours(set_pool):
    """Four colours is no shield at all; the fifth arriving arms it; one of
    them leaving disarms it again — rechecked per event, never latched."""
    spirit = set_pool("INV")["Spirit of Resistance"]
    assert _w1g5_compile(spirit).supported
    # The Spirit itself is white, so the board needs the other four.
    game, board, (raider,) = _w1g5_table(
        [spirit] + _w1g5_rainbow(without=("W", "G")),
        [_w1g5_creature("Raider", 3, 3, ("R",))],
    )
    me = game.players[0]
    assert _w1g5_damage_dealt(game, me, 5, source=raider) == 5

    green = _W1G5Permanent(card=_w1g5_creature("G-mage", 1, 1, ("G",)))
    game._put_permanent_onto_battlefield(0, green, None)
    assert _w1g5_damage_dealt(game, me, 5, source=raider) == 0
    assert _w1g5_damage_dealt(game, me, 5, source=raider, combat=True) == 0
    # "to you": the opponent, and my own creatures, are not shielded
    assert _w1g5_damage_dealt(game, game.players[1], 5, source=raider) == 5
    assert _w1g5_damage_dealt(game, green, 1, source=raider) == 1

    game.remove_from_battlefield(green)
    assert _w1g5_damage_dealt(game, me, 5, source=raider) == 5


def test_w1g5_spirit_of_resistance_counts_a_gold_permanent_for_each_colour(set_pool):
    """CR 105.2b: one multicoloured permanent is each of its colours, so a
    black-red-green creature and a blue one complete the white Spirit's set —
    and an opponent's permanents never count toward "you control"."""
    game, _mine, _theirs = _w1g5_table(
        [set_pool("INV")["Spirit of Resistance"],
         _w1g5_creature("Hydra", 4, 4, ("B", "R", "G"))],
        _w1g5_rainbow(),
    )
    me = game.players[0]
    assert _w1g5_damage_dealt(game, me, 4) == 4  # no blue of my own
    game._put_permanent_onto_battlefield(
        0, _W1G5Permanent(card=_w1g5_creature("Drake", 1, 1, ("U",))), None
    )
    assert _w1g5_damage_dealt(game, me, 4) == 0


def test_w1g5_spirit_of_resistance_holds_through_a_real_attack(set_pool):
    """Through the combat damage step rather than a bare event: a 3/3 attacks
    the rainbow's controller unblocked and no life is lost."""
    game, _theirs, _mine = _w1g5_table(
        [_w1g5_creature("Raider", 3, 3, ("R",))],
        [set_pool("INV")["Spirit of Resistance"]] + _w1g5_rainbow(without=("W",)),
    )
    _w1g5_fight(game, attacker_slot=0)
    assert game.players[1].life == 20


def test_w1g5_of_each_color_is_a_condition_any_noun_can_carry():
    """The relation is read behind the noun, so "a **creature** of each color"
    (Coalition Victory's half) is the same clause with a narrower set — and a
    wording nothing evaluates refuses rather than lowering to presence."""
    from engine.grammar import condition_payload_for

    permanent = condition_payload_for("you control a permanent of each color")
    creature = condition_payload_for("you control a creature of each color")
    assert permanent["of_each_color"] is True and creature["of_each_color"] is True
    assert creature["filter"] != permanent["filter"]
    assert condition_payload_for("an opponent controls a permanent of each color") is None
    assert condition_payload_for("you control no permanent of each color") is None


# --- Divine Presence -------------------------------------------------------
# "If a source would deal 4 or more damage to a permanent or player, that
# source deals 3 damage to that permanent or player instead." Forethought
# Amulet's cap with both narrowings taken off — a CR 614 replacement.


def test_w1g5_divine_presence_caps_every_large_event_at_three(set_pool):
    """Players and permanents, both seats', any source — and three or less is
    not this card's business."""
    presence = set_pool("INV")["Divine Presence"]
    assert _w1g5_compile(presence).supported
    game, (_presence, mine), (theirs,) = _w1g5_table(
        [presence, _w1g5_creature("Wall", 0, 7, ("W",))],
        [_w1g5_creature("Giant", 7, 7, ("R",))],
    )
    assert _w1g5_damage_dealt(game, game.players[0], 9, source=theirs) == 3
    assert _w1g5_damage_dealt(game, game.players[1], 9, source=mine) == 3
    assert _w1g5_damage_dealt(game, mine, 4, source=theirs) == 3
    assert _w1g5_damage_dealt(game, theirs, 20) == 3
    assert _w1g5_damage_dealt(game, game.players[0], 3, source=theirs) == 3
    assert _w1g5_damage_dealt(game, theirs, 2, source=mine) == 2


def test_w1g5_divine_presence_caps_a_real_attack_and_a_real_block(set_pool):
    """Through combat: a 7/7 hits the face for 3, and blocked by a 0/4 Wall it
    marks 3 on the Wall rather than killing it."""
    board = [_w1g5_creature("Giant", 7, 7, ("R",))]
    defence = [set_pool("INV")["Divine Presence"], _w1g5_creature("Wall", 0, 4, ("W",))]
    game, _mine, _theirs = _w1g5_table(board, defence)
    _w1g5_fight(game, attacker_slot=0)
    assert game.players[1].life == 17

    game, _mine, (_presence, wall) = _w1g5_table(board, defence)
    _w1g5_fight(game, attacker_slot=0, blocker_slot=1)
    assert game.is_on_battlefield(wall) and wall.damage_marked == 3


def test_w1g5_divine_presence_is_a_replacement_not_a_prevention(set_pool):
    """CR 614.1a, and the difference is rules-visible: damage that "can't be
    prevented" (the lock Whippoorwill arms) is capped all the same, where a
    shield would be switched off."""
    from engine.damage_events import DAMAGE_LOCK

    game, (_presence, wall), (giant,) = _w1g5_table(
        [set_pool("INV")["Divine Presence"], _w1g5_creature("Wall", 0, 7, ("W",))],
        [_w1g5_creature("Giant", 7, 7, ("R",))],
    )
    wall.metadata[DAMAGE_LOCK] = True
    assert _w1g5_damage_dealt(game, wall, 7, source=giant) == 3

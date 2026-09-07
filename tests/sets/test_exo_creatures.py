"""Exodus creatures.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: combat ---

from engine import Game, PlayerState
from engine.combat_permissions import MUST_BLOCK_ATTACKERS_UNTIL_EOT
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g3_creature(name, power, toughness, subtype="Beast", keywords=()):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=f"Creature - {subtype}",
        oracle_text="\n".join(word.capitalize() for word in keywords),
        colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": f"Creature - {subtype}",
             "power": str(power), "toughness": str(toughness)},
    )


def _g3_land(name="Forest"):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Basic Land - Forest",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("G",),
        raw={"name": name, "type_line": "Basic Land - Forest"},
    )


def _g3_ready(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g3_table(mine, theirs) -> Game:
    """A two-seat board with seat 0 active and nobody interactive."""
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _g3_into_declare_attackers(game: Game) -> Game:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def test_reckless_ogre_pumps_only_when_it_is_the_only_attacker(set_pool):
    """CR 506.5: "attacks alone" is a fact about the *declaration*.

    Both halves are the assertion. The narrowing rides the condition's payload,
    so a reading that dropped it would pump on every attack - the trigger firing
    more often than the card prints, which is the silent direction. The solo
    case is what proves the row is not simply refusing.
    """
    ogre = _g3_ready(Permanent(card=set_pool("EXO")["Reckless Ogre"]))
    program = compile_card_oracle(ogre.card)
    assert program.supported, program.reason
    assert program.triggered_abilities[0].condition.payload.get(
        "attacks_alone"
    ) == "", "the narrowing has to reach the dispatcher as payload"

    friend = _g3_ready(Permanent(card=_g3_creature("Straggler", 1, 1)))
    game = _g3_into_declare_attackers(_g3_table([ogre, friend], []))
    assert game.declare_attackers(0, [0, 1])[0]
    resolve_stack(game)
    assert ogre.effective_power == 3, (
        "two attackers were declared, so nothing attacked alone"
    )

    solo_ogre = _g3_ready(Permanent(card=set_pool("EXO")["Reckless Ogre"]))
    solo = _g3_into_declare_attackers(_g3_table([solo_ogre], []))
    assert solo.declare_attackers(0, [0])[0]
    resolve_stack(solo)
    assert solo_ogre.effective_power == 6


def test_cinder_crawler_can_only_pump_while_it_is_blocked(set_pool):
    """CR 602.5's clause, enforced rather than parsed and dropped.

    An unenforced restriction is not a dead ability - it is one that works more
    often than the card allows, so the refusal is the half worth asserting first.
    """
    crawler = _g3_ready(Permanent(card=set_pool("EXO")["Cinder Crawler"]))
    program = compile_card_oracle(crawler.card)
    assert program.supported, program.reason

    blocker = _g3_ready(Permanent(card=_g3_creature("Guard", 2, 2)))
    game = _g3_into_declare_attackers(_g3_table([crawler], [blocker]))
    refused = game.activate_permanent_ability(0, "Cinder Crawler", permanent_index=0)
    assert not refused.supported, refused.details
    assert "blocked" in refused.details, refused.details
    assert crawler.effective_power == 1

    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    allowed = game.activate_permanent_ability(0, "Cinder Crawler", permanent_index=0)
    assert allowed.supported, allowed.details
    resolve_stack(game)
    assert crawler.effective_power == 2


def test_monstrous_hound_counts_both_boards_before_attacking(set_pool):
    """"...unless you control **more lands than** defending player."

    A comparison between two boards, which is what separates it from the
    "controls a Swamp" clause beside it in `engine/combat_restrictions.py`: the
    equal-lands board is the one a dropped comparison would let through.
    """
    hound = _g3_ready(Permanent(card=set_pool("EXO")["Monstrous Hound"]))
    program = compile_card_oracle(hound.card)
    assert program.supported, program.reason

    game = _g3_table([hound, Permanent(card=_g3_land())], [])
    game.start_turn(0)
    assert game.can_attack(hound, 1), "one land against none"

    game.players[1].battlefield.append(Permanent(card=_g3_land()))
    assert not game.can_attack(hound, 1), "equal boards is not *more*"

    game.players[0].battlefield.append(Permanent(card=_g3_land()))
    assert game.can_attack(hound, 1)


def test_monstrous_hound_counts_both_boards_before_blocking(set_pool):
    """The second printed line, at the other step and against the other seat."""
    hound = _g3_ready(Permanent(card=set_pool("EXO")["Monstrous Hound"]))
    raider = _g3_ready(Permanent(card=_g3_creature("Raider", 2, 2)))
    game = _g3_table([raider, Permanent(card=_g3_land())], [hound])
    game.start_turn(0)
    assert not game._can_block_attacker(hound, raider), "no lands against one"

    game.players[1].battlefield.append(Permanent(card=_g3_land()))
    assert not game._can_block_attacker(hound, raider), "equal boards is not *more*"

    game.players[1].battlefield.append(Permanent(card=_g3_land()))
    assert game._can_block_attacker(hound, raider)


def test_pit_spawn_exiles_the_creature_it_damaged(set_pool):
    """"...deals damage to a creature, exile **that creature**."

    A `damage_dealt` event has two objects in it and the sentence names one with
    a bare pronoun. The damager here is the source, so the words can only mean
    the creature it hit - asserted against a creature big enough to survive the
    damage, which is the only board where the exile is observable at all.
    """
    spawn = _g3_ready(Permanent(card=set_pool("EXO")["Pit Spawn"]))
    program = compile_card_oracle(spawn.card)
    assert program.supported, program.reason

    survivor = _g3_ready(Permanent(card=_g3_creature("Bulwark", 0, 20)))
    game = _g3_table([spawn], [survivor])
    game._mark_damage_on_permanent(survivor, 6, source=spawn)
    resolve_stack(game)
    assert [p.card.name for p in game.players[1].battlefield] == []
    assert [c.name for c in game.players[1].exile] == ["Bulwark"]


def test_wall_of_nets_exiles_what_it_blocked_and_gives_it_back(set_pool):
    """Both printed lines, and the link between them (CR 610.3).

    The end-of-combat exile has to resolve while the block still exists: the
    ability determines what it affects when it *resolves* (CR 608.2), and
    CR 511.3 removes creatures from combat only as the step ends. The return is
    the linked twin, so nothing is remembered twice.
    """
    wall = _g3_ready(Permanent(card=set_pool("EXO")["Wall of Nets"]))
    program = compile_card_oracle(wall.card)
    assert program.supported, program.reason

    raider = _g3_ready(Permanent(card=_g3_creature("Raider", 1, 1)))
    bystander = _g3_ready(Permanent(card=_g3_creature("Bystander", 1, 1)))
    game = _g3_into_declare_attackers(_g3_table([raider, bystander], [wall]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    for _ in range(6):
        game.advance_combat_phase()
        resolve_stack(game)
        if game.current_turn_phase != "combat":
            break
    assert [c.name for c in game.players[0].exile] == ["Raider"]
    assert [p.card.name for p in game.players[0].battlefield] == ["Bystander"], (
        "the creature it never blocked is untouched"
    )

    game.remove_from_battlefield(wall)
    resolve_stack(game)
    assert [c.name for c in game.players[0].exile] == []
    assert sorted(p.card.name for p in game.players[0].battlefield) == [
        "Bystander", "Raider",
    ]


def test_crashing_boars_makes_the_defender_pick_its_own_blocker(set_pool):
    """CR 509.1c aimed at one attacker, on a creature nobody targeted.

    Three assertions, because three things could be silently dropped: the
    chooser (the *defending* player, not the boars' controller), the printed
    "untapped" narrowing, and the requirement itself.
    """
    boars = _g3_ready(Permanent(card=set_pool("EXO")["Crashing Boars"]))
    program = compile_card_oracle(boars.card)
    assert program.supported, program.reason

    guard = _g3_ready(Permanent(card=_g3_creature("Guard", 1, 1)))
    sleeper = _g3_ready(Permanent(card=_g3_creature("Sleeper", 1, 1)))
    sleeper.tapped = True
    mine = _g3_ready(Permanent(card=_g3_creature("Ally", 1, 1)))
    game = _g3_into_declare_attackers(_g3_table([boars, mine], [guard, sleeper]))
    assert game.declare_attackers(0, [0])[0]
    resolve_stack(game)

    assert guard.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) == [
        boars.permanent_id
    ]
    assert sleeper.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) is None, (
        "the printed 'untapped' is the whole of what keeps a tapped creature out"
    )
    assert mine.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) is None, (
        "the defending player chooses from their own battlefield"
    )

    game.advance_combat_phase()
    refused, why = game.declare_blockers(1, {})
    assert not refused and "must block" in why, why
    assert game.declare_blockers(1, {0: 0})[0]

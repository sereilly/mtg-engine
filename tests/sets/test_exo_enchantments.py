"""Exodus enchantments.

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
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g3e_creature(name, power, toughness, subtype="Beast"):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=f"Creature - {subtype}",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": f"Creature - {subtype}",
             "power": str(power), "toughness": str(toughness)},
    )


def _g3e_plain_aura(name="Test Charm"):
    """An Aura with no effect of its own, so "that are enchanted" is the only
    thing under test - Maniacal Rage would supply a `cant_block` of its own and
    the block half would pass whether or not the relative clause was read."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Enchantment - Aura",
        oracle_text="Enchant creature", colors=(), color_identity=(),
        keywords=("Enchant",), produced_mana=(),
        raw={"name": name, "type_line": "Enchantment - Aura"},
    )


def _g3e_ready(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g3e_table(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def test_high_ground_lets_your_team_block_one_more_each(set_pool):
    """CR 509.1b's ceiling, granted board-wide.

    The sentence is appended to each affected creature's effective card, so the
    printed-grant counter in `_max_blocks_for` reads it exactly as it reads
    Two-Headed Giant of Foriys' own line - which is what makes the ceilings add
    rather than replace. "You control" is the half a dropped narrowing would
    lose, so the opponent's creature is asserted too.
    """
    ground = Permanent(card=set_pool("EXO")["High Ground"])
    program = compile_card_oracle(ground.card)
    assert program.supported, program.reason

    mine = _g3e_ready(Permanent(card=_g3e_creature("Guard", 1, 3)))
    theirs = _g3e_ready(Permanent(card=_g3e_creature("Foe", 1, 3)))
    game = _g3e_table([mine], [theirs])
    assert game._max_blocks_for(mine) == 1

    game.players[0].battlefield.append(ground)
    game._recompute_continuous_effects()
    assert game._max_blocks_for(mine) == 2
    assert game._max_blocks_for(theirs) == 1, (
        "'you control' is relative to the enchantment's controller (CR 109.5)"
    )

    game.remove_from_battlefield(ground)
    game._recompute_continuous_effects()
    assert game._max_blocks_for(mine) == 1, "nothing is materialised on the creature"


def test_song_of_serenity_grounds_only_the_enchanted_creatures(set_pool):
    """"Creatures **that are enchanted** can't attack or block."

    The narrowing is printed as a relative clause behind the head noun, so it is
    the noun phrase the restriction carries rather than the sentence's subject -
    and a dropped one is a board-wide ban on attacking, which is a different
    card. Both directions are asserted for that reason.
    """
    song = Permanent(card=set_pool("EXO")["Song of Serenity"])
    program = compile_card_oracle(song.card)
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == [
        "creatures_cant_attack", "creatures_cant_block",
    ]
    assert program.instructions[0].payload["subject"]["enchanted_only"] is True

    bare = _g3e_ready(Permanent(card=_g3e_creature("Free", 2, 2)))
    bound = _g3e_ready(Permanent(card=_g3e_creature("Bound", 2, 2)))
    aura = Permanent(card=_g3e_plain_aura())
    raider = _g3e_ready(Permanent(card=_g3e_creature("Raider", 1, 1)))
    game = _g3e_table([bare, bound, aura, song], [raider])
    attach_aura(aura, bound)
    game._recompute_continuous_effects()

    assert not game.can_attack(bound, 1)
    assert game.can_attack(bare, 1), (
        "the relative clause is the whole of what keeps an unenchanted "
        "creature attacking"
    )
    assert not game._can_block_attacker(bound, raider)
    assert game._can_block_attacker(bare, raider), (
        "both prohibitions are enforced at their own step, over the same phrase"
    )


def test_maniacal_rage_grants_both_halves_of_its_one_line(set_pool):
    """"Enchanted creature gets +2/+2 **and** can't block."

    One printed line carrying two effects in two channels. The Aura used to lose
    the whole line to the conjunction, so both halves are the assertion: the
    numbers through the P/T grant and the restriction through the blockers step.
    """
    aura = Permanent(card=set_pool("EXO")["Maniacal Rage"])
    program = compile_card_oracle(aura.card)
    assert program.supported, program.reason

    host = _g3e_ready(Permanent(card=_g3e_creature("Berserker", 2, 2)))
    raider = _g3e_ready(Permanent(card=_g3e_creature("Raider", 1, 1)))
    game = _g3e_table([raider], [host, aura])
    attach_aura(aura, host)
    game._recompute_continuous_effects()

    assert (host.effective_power, host.effective_toughness) == (4, 4)
    assert not game._can_block_attacker(host, raider)


def test_reconnaissance_pulls_an_attacker_out_of_combat_and_untaps_it(set_pool):
    """"{0}: Remove target attacking creature you control from combat and untap
    it."

    The removal is the step that chooses and the pronoun behind it reads what
    the removal recorded - the mirror of Disharmony, where the untap chooses and
    the removal reads. Both halves are asserted, because a pronoun resolved to
    the ability's own source (which is what a bare "it" means everywhere else)
    would untap the enchantment and leave the creature tapped.
    """
    recon = Permanent(card=set_pool("EXO")["Reconnaissance"])
    program = compile_card_oracle(recon.card)
    assert program.supported, program.reason

    scout = _g3e_ready(Permanent(card=_g3e_creature("Scout", 2, 2)))
    game = _g3e_table([scout, recon], [_g3e_ready(Permanent(card=_g3e_creature("Guard", 2, 2)))])
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    assert scout.attacking and scout.tapped

    result = game.activate_permanent_ability(
        0, "Reconnaissance", target_player_index=0, permanent_index=1,
        target_permanent_index=0,
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert not scout.attacking
    assert not scout.tapped
    assert game.combat_attackers == {}
    assert not recon.tapped, "the enchantment is not what 'it' names"

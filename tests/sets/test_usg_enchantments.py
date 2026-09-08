"""Urza's Saga enchantments.

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

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: the Auras ---
#
# Eleven cards, and every one of them is given a game rather than a compile
# check: "it reports supported" is what the hollow-lines and parse-coverage
# instruments exist to catch, and this set already ships nine supported cards
# carrying a line nothing implements.
import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack


def _g4_creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}{G}", cmc=2.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _g4_board(*, mine: list, theirs: list | None = None, life: int = 20):
    """A two-seat game with mana costs off and control synced.

    Returns ``(game, seat0, seat1)`` - never a bare ``game``, so no mechanical
    union can splice a different group's helper body onto this signature.
    """
    g4_seat0 = PlayerState(name="P1", battlefield=list(mine), life=life)
    g4_seat1 = PlayerState(name="P2", battlefield=list(theirs or []), life=life)
    g4_game = Game(players=[g4_seat0, g4_seat1])
    g4_game.enforce_mana_costs = False
    g4_game._sync_control()
    return g4_game, g4_seat0, g4_seat1


@pytest.mark.parametrize(
    "aura_name",
    ["Brilliant Halo", "Despondency", "Fiery Mantle", "Fortitude", "Launch",
     "Spreading Algae"],
)
def test_w1g4_the_self_returning_auras_compile_a_real_trigger(set_pool, aura_name):
    """All six print "When this Aura is put into a graveyard from the
    battlefield, return it to its owner's hand".

    The compiled trigger is asserted, not just ``supported``: the card is
    supported on the strength of its *other* lines, and the whole defect this
    round fixed was a sentence that read fine on one front end and produced no
    ability at all on the one that dispatches.
    """
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("USG")[aura_name])
    assert program.supported, program.reason
    assert any(
        trig.condition.kind == "dies"
        and trig.instruction is not None
        and trig.instruction.kind == "return_source_card_to_owners_hand"
        for trig in program.triggered_abilities
    ), [trig.condition.kind for trig in program.triggered_abilities]


def test_w1g4_brilliant_halo_returns_itself_when_its_host_dies(set_pool):
    """The CR 704.5m path: the host leaves, the sweep bins the Aura, and the
    Aura's own death trigger hands it back."""
    host = Permanent(card=_g4_creature("Host"))
    aura = Permanent(card=set_pool("USG")["Brilliant Halo"])
    game, mine, _ = _g4_board(mine=[host, aura])
    attach_aura(aura, host)

    game._destroy_swept_permanents(mine, lambda perm: perm is host)
    game.check_state_based_actions()
    resolve_stack(game)

    assert [card.name for card in mine.hand] == ["Brilliant Halo"]
    assert [card.name for card in mine.graveyard] == ["Host"]


def test_w1g4_launch_returns_itself_when_the_aura_alone_is_destroyed(set_pool):
    """The other path - the host survives - because the trigger is on the
    Aura's own death and not on its host's."""
    host = Permanent(card=_g4_creature("Host"))
    aura = Permanent(card=set_pool("USG")["Launch"])
    game, mine, _ = _g4_board(mine=[host, aura])
    attach_aura(aura, host)

    game._destroy_swept_permanents(mine, lambda perm: perm is aura)
    resolve_stack(game)

    assert [card.name for card in mine.hand] == ["Launch"]
    assert [perm.card.name for perm in mine.battlefield] == ["Host"]
    assert mine.graveyard == []


def test_w1g4_spreading_algae_only_enchants_a_swamp(set_pool):
    """Both halves of the Roots lesson: the picker offers Swamps alone, and the
    attach check refuses anything else rather than taking the permissive
    fallback that a noun with no matcher row would reach."""
    from engine.auras import aura_attach_refusal
    from engine.mixins.stack.casting import permanent_matches_enchant_noun
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    pool = set_pool("USG")
    algae = pool["Spreading Algae"]
    swamp = Permanent(card=pool["Swamp"])
    mountain = Permanent(card=pool["Mountain"])
    game, _, _ = _g4_board(mine=[swamp, mountain])

    spec = derive_cast_spec(algae, compile_card_oracle(algae))
    assert spec == {"kind": "land", "enchant_land_type": "swamp"}
    offered = game._enumerate_targets(0, algae, spec, for_cast=True)
    assert [entry["name"] for entry in offered] == ["Swamp"]

    assert permanent_matches_enchant_noun(swamp, "swamp")
    assert not permanent_matches_enchant_noun(mountain, "swamp")
    aura = Permanent(card=algae)
    assert aura_attach_refusal(game, aura, swamp) is None
    assert aura_attach_refusal(game, aura, mountain) is not None


def test_w1g4_spreading_algae_destroys_its_swamp_and_comes_back(set_pool):
    pool = set_pool("USG")
    swamp = Permanent(card=pool["Swamp"])
    aura = Permanent(card=pool["Spreading Algae"])
    game, mine, _ = _g4_board(mine=[swamp, aura])
    attach_aura(aura, swamp)

    game.become_tapped(swamp)
    resolve_stack(game)
    game.check_state_based_actions()
    resolve_stack(game)

    assert [card.name for card in mine.graveyard] == ["Swamp"]
    assert [card.name for card in mine.hand] == ["Spreading Algae"]
    assert mine.battlefield == []


def test_w1g4_pariah_moves_its_controllers_damage_onto_the_host(set_pool):
    host = Permanent(card=_g4_creature("Wall", 0, 6))
    aura = Permanent(card=set_pool("USG")["Pariah"])
    game, mine, _ = _g4_board(mine=[host, aura])

    game._deal_damage_to_player(mine, 3, source=aura)
    assert mine.life == 17, "unattached, the Aura moves nothing"

    attach_aura(aura, host)
    game._deal_damage_to_player(mine, 3, source=aura)
    assert mine.life == 17
    assert host.damage_marked == 3


def test_w1g4_pariah_stops_the_moment_the_host_is_gone(set_pool):
    """CR 614.9's liveness half, and the reason the redirection is derived from
    the Aura's text rather than armed as a record: the Aura falls off with its
    host and there is nothing left to undo."""
    host = Permanent(card=_g4_creature("Wall", 0, 4))
    aura = Permanent(card=set_pool("USG")["Pariah"])
    game, mine, _ = _g4_board(mine=[host, aura])
    attach_aura(aura, host)

    game._deal_damage_to_player(mine, 4, source=aura)
    game.check_state_based_actions()
    assert mine.life == 20
    assert sorted(card.name for card in mine.graveyard) == ["Pariah", "Wall"]

    game._deal_damage_to_player(mine, 3, source=aura)
    assert mine.life == 17


def test_w1g4_cloak_of_mists_makes_its_host_unblockable(set_pool):
    attacker = Permanent(card=_g4_creature("Attacker"))
    blocker = Permanent(card=_g4_creature("Blocker"))
    aura = Permanent(card=set_pool("USG")["Cloak of Mists"])
    game, _, _ = _g4_board(mine=[attacker, aura], theirs=[blocker])
    attacker.attacking = True

    assert game._can_block_attacker(blocker, attacker)
    assert not game.is_unblockable(attacker)

    attach_aura(aura, attacker)
    assert not game._can_block_attacker(blocker, attacker)
    assert game.is_unblockable(attacker), (
        "the UI's fade and the blocker gate have to agree, or the client "
        "promises a block the step then rejects"
    )

    detach_aura(aura, attacker)
    assert game._can_block_attacker(blocker, attacker)


def test_w1g4_fertile_ground_adds_a_mana_of_the_colour_asked_for(set_pool):
    pool = set_pool("USG")
    forest = Permanent(card=pool["Forest"])
    aura = Permanent(card=pool["Fertile Ground"])
    game, mine, _ = _g4_board(mine=[forest, aura])
    attach_aura(aura, forest)

    game.tap_land_for_mana(0, "Forest", chosen_color="U")
    assert {sym: n for sym, n in mine.mana_pool.items() if n} == {"G": 1, "U": 1}

    forest.tapped = False
    game.clear_mana_pools()
    detach_aura(aura, forest)
    game.tap_land_for_mana(0, "Forest", chosen_color="U")
    assert {sym: n for sym, n in mine.mana_pool.items() if n} == {"G": 1}


def test_w1g4_venomous_fangs_destroys_what_its_host_damaged(set_pool):
    host = Permanent(card=_g4_creature("Host", 1, 5))
    victim = Permanent(card=_g4_creature("Victim", 1, 9))
    aura = Permanent(card=set_pool("USG")["Venomous Fangs"])
    game, mine, theirs = _g4_board(mine=[host, aura], theirs=[victim])
    attach_aura(aura, host)

    game._mark_damage_on_permanent(victim, 1, source=host, combat=True)
    resolve_stack(game)
    game.check_state_based_actions()

    assert [card.name for card in theirs.graveyard] == ["Victim"], (
        "'the other creature' is the one that took the damage, not the host"
    )
    assert [perm.card.name for perm in mine.battlefield] == [
        "Host", "Venomous Fangs",
    ]


def test_w1g4_vampiric_embrace_grows_the_enchanted_creature(set_pool):
    """"That creature" is the **enchanted** one - Sengir Vampire's ability
    granted by an Aura, with the counter on the killer."""
    host = Permanent(card=_g4_creature("Host"))
    victim = Permanent(card=_g4_creature("Victim", 1, 2))
    aura = Permanent(card=set_pool("USG")["Vampiric Embrace"])
    game, _, theirs = _g4_board(mine=[host, aura], theirs=[victim])
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    assert (host.effective_power, host.effective_toughness) == (4, 4)
    assert game._has_keyword(host, "flying")

    game._mark_damage_on_permanent(victim, 2, source=host, combat=True)
    game.check_state_based_actions()
    resolve_stack(game)
    game._recompute_continuous_effects()

    assert [card.name for card in theirs.graveyard] == ["Victim"]
    assert (host.effective_power, host.effective_toughness) == (5, 5)


def test_w1g4_a_creature_the_host_did_not_damage_grows_nothing(set_pool):
    """The narrowing the fire site enforces: the condition is about a creature
    *this Aura's host* damaged, and an unrelated death is not one."""
    host = Permanent(card=_g4_creature("Host"))
    bystander = Permanent(card=_g4_creature("Bystander", 1, 1))
    aura = Permanent(card=set_pool("USG")["Vampiric Embrace"])
    game, _, theirs = _g4_board(mine=[host, aura], theirs=[bystander])
    attach_aura(aura, host)

    game._destroy_swept_permanents(theirs, lambda perm: perm is bystander)
    resolve_stack(game)

    assert host.metadata.get("plus_counters", 0) == 0

"""Core Set 2021 (M21) artifacts.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- Exiling a whole zone ---------------------------------------------------


def test_tormods_crypt_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Tormod's Crypt"])
    assert program.supported, program.reason


def test_tormods_crypt_exiles_the_whole_graveyard_and_sacrifices_itself(set_pool):
    """A whole *zone*, not a card in one — so there is nothing to filter and
    nothing to target among the cards. A graveyard is its owner's (CR 404.1) and
    so is the exile zone, which is why no CR 400.3 lookup is needed."""
    pool = set_pool("M21")
    crypt = Permanent(card=pool["Tormod's Crypt"])
    p1 = PlayerState(name="P1", battlefield=[crypt])
    p2 = PlayerState(
        name="P2",
        graveyard=[pool["Shock"], pool["Alpine Watchdog"], pool["Island"]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(0, "Tormod's Crypt", target_player_index=1)
    assert result.supported, result.details
    game._settle()

    assert p2.graveyard == []
    assert len(p2.exile) == 3
    assert not game.is_on_battlefield(crypt), "sacrificed as part of the cost"


def test_tormods_crypt_leaves_the_other_graveyard_alone(set_pool):
    """One player's, named by the target — the card says "target player's", not
    "each"."""
    pool = set_pool("M21")
    crypt = Permanent(card=pool["Tormod's Crypt"])
    p1 = PlayerState(name="P1", battlefield=[crypt], graveyard=[pool["Shock"]])
    p2 = PlayerState(name="P2", graveyard=[pool["Island"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Tormod's Crypt", target_player_index=1)
    game._settle()

    # The Crypt itself joins its controller's graveyard — it was sacrificed to
    # pay the cost — and everything that was already there stays.
    assert [c.name for c in p1.graveyard] == ["Shock", "Tormod's Crypt"]
    assert p2.graveyard == []


# --- Artifact creatures ----------------------------------------------------


def test_epitaph_golem_bottoms_a_chosen_graveyard_card(set_pool):
    pool = set_pool("M21")
    golem = Permanent(card=pool["Epitaph Golem"])
    p1 = PlayerState(
        name="P1", battlefield=[golem],
        graveyard=[pool["Shock"], pool["Concordia Pegasus"]],
        library=[pool["Island"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.activate_permanent_ability(
        0, "Epitaph Golem", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert [c.name for c in p1.graveyard] == ["Shock"]
    assert [c.name for c in p1.library] == ["Island", "Concordia Pegasus"]


def test_sparkhunter_masticore_keeps_its_planeswalker_protection(set_pool):
    """The card the cost line was hiding. "Protection from planeswalkers" is a
    quality this engine models (CR 702.16), and the whole card was unsupported
    only because the compiler stopped at line one."""
    pool = set_pool("M21")
    masticore = _nosick(Permanent(card=pool["Sparkhunter Masticore"]))
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[masticore])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert ("card_type", "planeswalker") in game._protection_qualities(masticore)

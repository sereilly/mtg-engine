"""A **roles** spell weighed where it lies is weighed with its roles.

``ai_scoring._score_spell_target`` is how a spell is valued in the abstract —
a library search's pick, a scry, the top of a library (``_score_tutor_choice``
→ ``_score_cast`` with no rehearsal). It rehearsed a seat-only announcement,
and the engine fills no role a cast leaves unnamed
(``engine/bare_announcements.py`` refuses a role announcement, CR 601.2c), so
every roles spell — Donate, Fumarole, Decimate, Withdraw, Plague Spores… — was
refused there and scored -SWING_CAP whatever it would have done: the seat
bottomed it under a scry and passed it over in a search. Found by kg/slots
(Primal Might, made a roles spell there, bottomed by an Opt in M21 seed 3).

The census asks every roles spell in the shipped pool on one rich mirrored
board, with the chain the cast path itself would announce
(``ai_slot_targets._choose_role_targets``). On the base tree (``c42aec75``) 13 of
the 18 that had a chain scored -SWING_CAP (the five that did not are kicker
cards whose unkicked cast names one target).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_actions import _cast_spec
from engine.ai_scoring import SWING_CAP, _score_spell_target
from engine.ai_slot_targets import _choose_role_targets
from engine.ai_weighed_cast import SPELL_TYPES
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import spec_roles
from tests.helpers import _nosick

_BOARD = ("Grizzly Bears", "Serra Angel", "Ornithopter", "Llanowar Elves",
          "Hill Giant", "Plains", "Island", "Swamp", "Mountain", "Forest",
          "Sol Ring", "Jayemdae Tome", "Castle")
_GRAVEYARD = ("Grizzly Bears", "Lightning Bolt", "Giant Growth", "Forest")
_HAND = ("Island", "Grizzly Bears")


@pytest.fixture(scope="module")
def pool():
    catalog = load_catalog()
    by_name = {card.name: card for card in catalog}
    roles = []
    for unit in compilation_units(catalog):
        if unit.primary_type not in SPELL_TYPES:
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        spec = _cast_spec(unit, program)
        if isinstance(spec, dict) and spec_roles(spec):
            roles.append(unit)
    return by_name, sorted(roles, key=lambda card: card.name)


def _mirrored_board(by_name):
    game = Game(players=[
        PlayerState(
            name=f"P{seat}", library=[by_name["Island"]] * 20,
            graveyard=[by_name[name] for name in _GRAVEYARD],
            hand=[by_name[name] for name in _HAND],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    for seat in range(2):
        for name in _BOARD:
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game._recompute_continuous_effects()
    return game


def test_every_roles_spell_with_a_chain_is_weighed_as_the_cast_it_would_be(pool):
    by_name, roles = pool
    # The floor: the census is about a population, and an empty one passes.
    assert len(roles) >= 20, [card.name for card in roles]
    weighed, refused = [], []
    for card in roles:
        game = _mirrored_board(by_name)
        chain = _choose_role_targets(game, 0, card)
        if not chain:
            continue  # no chain on this board: the cast would be refused too
        score = _score_spell_target(card, 0, chain[0], game)
        (refused if score == -SWING_CAP else weighed).append((card.name, score))
    assert len(weighed) + len(refused) >= 15, (weighed, refused)
    assert not refused, refused


def test_a_roles_spell_with_no_chain_is_still_scored_as_refused(pool):
    """The other half: where the board offers no chain the cast path would
    not cast it (CR 601.2c), and the abstract weighing says the same."""
    by_name, _roles = pool
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    fumarole = by_name["Fumarole"]
    assert _choose_role_targets(game, 0, fumarole) == ()
    assert _score_spell_target(fumarole, 0, 1, game) == -SWING_CAP

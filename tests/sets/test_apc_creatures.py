"""Apocalypse creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

import pytest as _w1g8_pytest

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import _mk_card as _w1g8_mk_card
from tests.helpers import resolve_stack as _w1g8_resolve_stack

# Where the cards these tests borrow from other sets were first printed. Every
# other name is Apocalypse's.
_W1G8_HOMES = {
    "Forest": "LEA", "Island": "LEA", "Swamp": "LEA", "Terror": "LEA",
    "Grizzly Bears": "LEA", "Hill Giant": "LEA", "Wall of Wood": "LEA",
    "Sol Ring": "LEA", "Megrim": "STH",
}
_W1G8_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}


def _w1g8_card(set_pool, name: str):
    return set_pool(_W1G8_HOMES.get(name, "APC"))[name]


def _w1g8_table(set_pool, *, seats: int = 2, hand=(), opp_hand=(), library=(),
                interactive=()) -> _w1g8_Game:
    """*seats* players with costs enforced and mana to pay them. Seat 0 holds
    *hand*, seat 1 holds *opp_hand*."""
    forest = _w1g8_card(set_pool, "Forest")
    players = [
        _w1g8_PlayerState(name=f"P{seat}", library=[forest] * 12)
        for seat in range(seats)
    ]
    players[0].hand = [_w1g8_card(set_pool, n) for n in hand]
    players[1].hand = [_w1g8_card(set_pool, n) for n in opp_hand]
    if library:
        players[0].library = [_w1g8_card(set_pool, n) for n in library]
    game = _w1g8_Game(players=players)
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    for player in players:
        player.mana_pool.update(_W1G8_RICH)
    return game


def _w1g8_put(game, set_pool, seat: int, name: str) -> _w1g8_Permanent:
    perm = _w1g8_Permanent(card=_w1g8_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g8_names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _w1g8_lives(game) -> list[int]:
    return [player.life for player in game.players]


def _w1g8_settle(game) -> None:
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)


def _w1g8_attack(game, attacker, *, blocker=None, defender: int = 1) -> None:
    """Step the real combat phase: *attacker* (seat 0's) attacks seat
    *defender*, *blocker* blocks it or nobody does, and combat damage is
    dealt. Stops there — a trigger the damage raised is on the stack."""
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.current_step == "declare_attackers", game.current_step
    assert game.declare_attackers(
        0, [game.battlefield_index_of(attacker)], defending_player_index=defender,
    )[0]
    game.advance_combat_phase()
    blocks = {} if blocker is None else {game.battlefield_index_of(blocker): 0}
    assert game.declare_blockers(defender, blocks)[0]
    game.advance_combat_phase()


def _w1g8_finish_combat(game) -> None:
    for _ in range(8):
        if game.current_turn_phase != "combat":
            return
        game.advance_combat_phase()
    raise AssertionError(f"combat never ended: {game.current_step}")


# --- Haunted Angel ----------------------------------------------------------------


def test_w1g8_haunted_angel_dying_is_exiled_and_gives_the_opponent_an_angel(set_pool):
    """"When this creature dies, exile it and each other player creates a 3/3
    black Angel creature token with flying." The card leaves the graveyard for
    exile, and the token is the *other* player's."""
    game = _w1g8_table(set_pool, hand=["Terror"])
    angel = _w1g8_put(game, set_pool, 0, "Haunted Angel")

    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[angel.permanent_id]).supported
    game.resolve_top_of_stack()
    assert _w1g8_names(game.players[0].graveyard) == ["Haunted Angel", "Terror"]
    assert _w1g8_names(game.stack) == ["Haunted Angel"], "the trigger is a stack object"
    _w1g8_settle(game)

    assert _w1g8_names(game.players[0].exile) == ["Haunted Angel"]
    assert _w1g8_names(game.players[0].graveyard) == ["Terror"]
    assert list(game.controlled_by(0)) == []
    (token,) = game.controlled_by(1)
    assert (token.effective_power, token.effective_toughness) == (3, 3)
    assert token.effective_colors == {"B"}
    assert token.has_type("creature") and "angel" in token.effective_card.type_line.lower()
    assert game._has_keyword(token, "flying")
    assert token.metadata.get("is_token")


def test_w1g8_haunted_angel_gives_every_other_player_a_token_and_its_controller_none(
    set_pool,
):
    """"Each **other** player" at three seats: both opponents of the Angel's
    controller get one, whoever killed it — here the controller did."""
    game = _w1g8_table(set_pool, seats=3, hand=["Terror"])
    angel = _w1g8_put(game, set_pool, 0, "Haunted Angel")

    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[angel.permanent_id]).supported
    _w1g8_settle(game)

    assert [_w1g8_names(game.controlled_by(seat)) for seat in range(3)] == [
        [], ["Angel Token"], ["Angel Token"],
    ]


def test_w1g8_haunted_angel_gone_from_the_graveyard_still_makes_the_tokens(set_pool):
    """CR 608.2: as much as possible. With the card already moved out of the
    graveyard in response, "exile it" finds nothing and the rest of the
    sentence happens anyway."""
    game = _w1g8_table(set_pool, hand=["Terror"])
    angel = _w1g8_put(game, set_pool, 0, "Haunted Angel")
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[angel.permanent_id]).supported
    game.resolve_top_of_stack()
    card = game.players[0].graveyard.pop(0)
    game.put_card_into_library(game.players[0], card, "top")
    _w1g8_settle(game)

    assert game.players[0].exile == []
    assert game.players[0].library[0].name == "Haunted Angel"
    assert _w1g8_names(game.controlled_by(1)) == ["Angel Token"]


def test_w1g8_each_other_player_is_read_where_each_opponent_is(set_pool):
    """The recipient in front of "creates" is a row beside "each opponent", so
    the two spellings compile to one program — and a recipient the table does
    not hold still refuses rather than making the token for the controller."""
    def program(text):
        return _w1g8_compile(_w1g8_mk_card(
            name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text,
        ))

    other = program("Each other player creates a 3/3 black Angel creature token with flying.")
    opponent = program("Each opponent creates a 3/3 black Angel creature token with flying.")
    assert other.supported and other.instructions == opponent.instructions
    assert not program(
        "Each other creature creates a 3/3 black Angel creature token with flying."
    ).supported


# --- Fungal Shambler (driven) -------------------------------------------------------


def test_w1g8_fungal_shambler_draws_for_its_controller_and_the_opponent_picks_a_discard(
    set_pool,
):
    """"Whenever this creature deals damage to an opponent, you draw a card and
    that opponent discards a card." The draw is mine; the discard is theirs to
    choose (CR 701.9b), so the trigger waits on them."""
    game = _w1g8_table(
        set_pool, opp_hand=["Forest", "Island"], library=["Swamp"] * 5,
        interactive=(0, 1),
    )
    shambler = _w1g8_put(game, set_pool, 0, "Fungal Shambler")

    _w1g8_attack(game, shambler)
    assert game.players[1].life == 14
    assert _w1g8_names(game.stack) == ["Fungal Shambler"]
    game.resolve_top_of_stack()
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]
    assert game.confirm_discard(1, [1])
    _w1g8_settle(game)
    _w1g8_finish_combat(game)

    assert _w1g8_names(game.players[1].hand) == ["Forest"]
    assert _w1g8_names(game.players[1].graveyard) == ["Island"]
    assert _w1g8_names(game.players[0].hand) == ["Swamp"], "drew exactly once"


def test_w1g8_fungal_shambler_needs_damage_to_reach_the_opponent(set_pool):
    """Trample over a 2/2 still hits the player for 4 and triggers; a blocker
    that soaks all six does not — damage to a creature is not damage to an
    opponent."""
    game = _w1g8_table(set_pool, opp_hand=["Forest"], library=["Swamp"] * 5)
    shambler = _w1g8_put(game, set_pool, 0, "Fungal Shambler")
    bears = _w1g8_put(game, set_pool, 1, "Grizzly Bears")
    _w1g8_attack(game, shambler, blocker=bears)
    _w1g8_settle(game)
    _w1g8_finish_combat(game)
    assert game.players[1].life == 16
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]
    assert game.players[1].hand == []

    game = _w1g8_table(set_pool, opp_hand=["Forest"], library=["Swamp"] * 5)
    shambler = _w1g8_put(game, set_pool, 0, "Fungal Shambler")
    walls = [_w1g8_put(game, set_pool, 1, "Wall of Wood") for _ in range(2)]
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0, 1: 0})[0]
    game.advance_combat_phase()
    if not game.combat_damage_resolved:
        assert game.resolve_combat_damage(0, attacker_damage={0: {0: 3, 1: 3}})[0]
    _w1g8_settle(game)
    _w1g8_finish_combat(game)
    assert game.players[1].life == 20, game.log
    assert game.players[0].hand == [] and _w1g8_names(game.players[1].hand) == ["Forest"]
    assert all(wall.damage_marked == 0 or not game.is_on_battlefield(wall) for wall in walls)


# --- Putrid Warrior (driven) ---------------------------------------------------------


@_w1g8_pytest.mark.parametrize("seats, mode, expected", [
    (2, 0, [19, 17]),
    (2, 1, [21, 19]),
    (3, 0, [19, 17, 19]),
    (3, 1, [21, 19, 21]),
])
def test_w1g8_putrid_warrior_changes_every_players_life_by_one(
    set_pool, seats, mode, expected,
):
    """"Whenever this creature deals damage, choose one — • Each player loses
    1 life. • Each player gains 1 life." **Each** player, both ways. The gain
    used to reach one seat: the quantifier fell through to a single target, so
    the prompt read "…targeting P0" and the opponent's life did not move."""
    game = _w1g8_table(set_pool, seats=seats, interactive=(0,))
    warrior = _w1g8_put(game, set_pool, 0, "Putrid Warrior")

    _w1g8_attack(game, warrior)
    (choice,) = game.pending_choices
    assert choice.kind == "mode_choice"
    assert choice.data["labels"] == [
        "Each player loses 1 life", "Each player gains 1 life",
    ]
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=mode)
    _w1g8_settle(game)
    _w1g8_finish_combat(game)

    assert _w1g8_lives(game) == expected, game.log
    assert not any("targeting" in line for line in game.log if "chose" in line)


def test_w1g8_putrid_warrior_triggers_on_damage_to_a_creature_too(set_pool):
    """"Deals damage", not "to a player": blocked by a Wall it deals its 2 to
    the Wall and the ability still triggers."""
    game = _w1g8_table(set_pool)
    warrior = _w1g8_put(game, set_pool, 0, "Putrid Warrior")
    wall = _w1g8_put(game, set_pool, 1, "Wall of Wood")

    _w1g8_attack(game, warrior, blocker=wall)
    _w1g8_settle(game)
    _w1g8_finish_combat(game)

    assert wall.damage_marked == 2 and game.is_on_battlefield(wall)
    assert _w1g8_lives(game) == [19, 19], game.log


# --- Quagmire Druid (driven) ----------------------------------------------------------


def test_w1g8_quagmire_druid_trades_a_creature_for_an_enchantment(set_pool):
    """"{G}, {T}, Sacrifice a creature: Destroy target enchantment." The
    picker offers enchantments and nothing else; the cost offers the Druid's
    own creatures, the Druid among them."""
    game = _w1g8_table(set_pool)
    druid = _w1g8_put(game, set_pool, 0, "Quagmire Druid")
    bears = _w1g8_put(game, set_pool, 0, "Grizzly Bears")
    megrim = _w1g8_put(game, set_pool, 1, "Megrim")
    _w1g8_put(game, set_pool, 1, "Sol Ring")

    spec = game.activation_target_spec(0, game.battlefield_index_of(druid))
    assert [t["name"] for t in spec["valid_targets"]] == ["Megrim"]
    assert {t["name"] for t in spec["cost_spec"]["valid_targets"]} == {
        "Quagmire Druid", "Grizzly Bears",
    }
    assert game.activate_permanent_ability(
        0, "Quagmire Druid", target_permanent_ids=[megrim.permanent_id],
        cost_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].graveyard) == ["Megrim"]
    assert _w1g8_names(game.players[0].graveyard) == ["Grizzly Bears"]
    assert druid.tapped and game.is_on_battlefield(druid)
    assert _w1g8_names(game.controlled_by(1)) == ["Sol Ring"]


def test_w1g8_quagmire_druid_refuses_a_target_that_is_not_an_enchantment(set_pool):
    """An artifact named as the target, and no target at all: both refused
    before any cost is paid (CR 602.2b) — the creature is still there, the
    Druid is untapped and the mana is unspent."""
    game = _w1g8_table(set_pool)
    druid = _w1g8_put(game, set_pool, 0, "Quagmire Druid")
    bears = _w1g8_put(game, set_pool, 0, "Grizzly Bears")
    ring = _w1g8_put(game, set_pool, 1, "Sol Ring")
    before = dict(game.players[0].mana_pool)

    for target in ([ring.permanent_id], None):
        result = game.activate_permanent_ability(
            0, "Quagmire Druid", target_permanent_ids=target,
            cost_permanent_ids=[bears.permanent_id],
        )
        assert not result.supported, result
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(ring)
    assert not druid.tapped and dict(game.players[0].mana_pool) == before


def test_w1g8_quagmire_druid_may_be_the_creature_it_sacrifices(set_pool):
    game = _w1g8_table(set_pool)
    druid = _w1g8_put(game, set_pool, 0, "Quagmire Druid")
    megrim = _w1g8_put(game, set_pool, 1, "Megrim")

    assert game.activate_permanent_ability(
        0, "Quagmire Druid", target_permanent_ids=[megrim.permanent_id],
        cost_permanent_ids=[druid.permanent_id],
    ).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[0].graveyard) == ["Quagmire Druid"]
    assert _w1g8_names(game.players[1].graveyard) == ["Megrim"]


# --- Savage Gorilla (driven) -----------------------------------------------------------


def test_w1g8_savage_gorilla_shrinks_a_creature_and_draws(set_pool):
    """"{U}{B}, {T}, Sacrifice this creature: Target creature gets -3/-3 until
    end of turn. Draw a card." A Hill Giant dies to it, and the Gorilla is in
    the graveyard as the cost."""
    game = _w1g8_table(set_pool, library=["Swamp"] * 5)
    _w1g8_put(game, set_pool, 0, "Savage Gorilla")
    giant = _w1g8_put(game, set_pool, 1, "Hill Giant")

    assert game.activate_permanent_ability(
        0, "Savage Gorilla", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[0].graveyard) == ["Savage Gorilla"]
    assert _w1g8_names(game.players[1].graveyard) == ["Hill Giant"]
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]


def test_w1g8_savage_gorilla_only_weakens_a_bigger_creature_until_end_of_turn(set_pool):
    game = _w1g8_table(set_pool, library=["Swamp"] * 5)
    _w1g8_put(game, set_pool, 0, "Savage Gorilla")
    shambler = _w1g8_put(game, set_pool, 1, "Fungal Shambler")

    assert game.activate_permanent_ability(
        0, "Savage Gorilla", target_permanent_ids=[shambler.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert (shambler.effective_power, shambler.effective_toughness) == (3, 1)

    game.resolve_cleanup_step(0)
    assert (shambler.effective_power, shambler.effective_toughness) == (6, 4)


# --- Mournful Zombie (driven) -----------------------------------------------------------


def test_w1g8_mournful_zombie_gives_the_named_player_one_life(set_pool):
    """"{W}, {T}: Target player gains 1 life." Either player may be named;
    tapped, it cannot be activated again, and it wants white mana."""
    for target, expected in ((0, [21, 20]), (1, [20, 21])):
        game = _w1g8_table(set_pool)
        zombie = _w1g8_put(game, set_pool, 0, "Mournful Zombie")
        spec = game.activation_target_spec(0, game.battlefield_index_of(zombie))
        assert [t["seat"] for t in spec["valid_targets"]] == [0, 1]
        assert game.activate_permanent_ability(
            0, "Mournful Zombie", target_player_index=target,
        ).supported
        _w1g8_settle(game)
        assert _w1g8_lives(game) == expected
        assert not game.activate_permanent_ability(
            0, "Mournful Zombie", target_player_index=target,
        ).supported, "it is tapped"
        assert _w1g8_lives(game) == expected

    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool, 0, "Mournful Zombie")
    game.players[0].mana_pool.update({"W": 0})
    assert not game.activate_permanent_ability(
        0, "Mournful Zombie", target_player_index=0,
    ).supported
    assert _w1g8_lives(game) == [20, 20]

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================

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


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from engine.named_counters import counters_on as _w1g8_counters_on
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_enchantment_duel(set_pool, *, active: int = 0, library: int = 10):
    """Two non-interactive seats, costs off, on *active*'s turn."""
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[island] * library)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(active)
    return game


def _w1g8_enchantment_put(game, set_pool, seat: int, name: str, code: str = "LEA"):
    """*name* on *seat*'s battlefield, clear of summoning sickness."""
    permanent = _W1G8Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_temporal_distortion_marks_a_land_tapped_on_a_board_with_no_creature(set_pool):
    """"Whenever a creature or land becomes tapped, put an hourglass counter
    on it." Nothing is targeted — the object is the one that became tapped —
    so the trigger resolves on a board holding no creature at all, and an
    artifact that becomes tapped gets nothing."""
    game = _w1g8_enchantment_duel(set_pool, active=1)
    _w1g8_enchantment_put(game, set_pool, 0, "Temporal Distortion", "INV")
    forest = _w1g8_enchantment_put(game, set_pool, 1, "Forest")
    mox = _w1g8_enchantment_put(game, set_pool, 1, "Mox Emerald")

    game.become_tapped(forest)
    game.become_tapped(mox)
    assert game.pending_choices == []
    _w1g8_resolve_stack(game)

    assert _w1g8_counters_on(forest, "hourglass") == 1
    assert _w1g8_counters_on(mox, "hourglass") == 0


def test_temporal_distortion_keeps_marked_permanents_tapped(set_pool):
    """"Each permanent with an hourglass counter on it doesn't untap during
    its controller's untap step." The marked Forest and Grizzly Bears stay
    tapped; the unmarked Mox Emerald untaps."""
    game = _w1g8_enchantment_duel(set_pool, active=1)
    _w1g8_enchantment_put(game, set_pool, 0, "Temporal Distortion", "INV")
    forest = _w1g8_enchantment_put(game, set_pool, 1, "Forest")
    bears = _w1g8_enchantment_put(game, set_pool, 1, "Grizzly Bears")
    mox = _w1g8_enchantment_put(game, set_pool, 1, "Mox Emerald")
    for permanent in (forest, bears, mox):
        game.become_tapped(permanent)
    _w1g8_resolve_stack(game)

    game.resolve_untap_step(1)

    assert forest.tapped and bears.tapped
    assert not mox.tapped


def test_temporal_distortion_clears_only_that_players_counters_at_upkeep(set_pool):
    """"At the beginning of each player's upkeep, remove all hourglass counters
    from permanents **that player** controls." Seat 1's upkeep frees seat 1's
    Forest (it untaps a turn later) and leaves the counter on seat 0's
    Island."""
    game = _w1g8_enchantment_duel(set_pool, active=1)
    _w1g8_enchantment_put(game, set_pool, 0, "Temporal Distortion", "INV")
    island = _w1g8_enchantment_put(game, set_pool, 0, "Island")
    forest = _w1g8_enchantment_put(game, set_pool, 1, "Forest")
    game.become_tapped(island)
    game.become_tapped(forest)
    _w1g8_resolve_stack(game)

    game.resolve_untap_step(1)
    assert forest.tapped
    game.resolve_upkeep(1)
    _w1g8_resolve_stack(game)

    assert _w1g8_counters_on(forest, "hourglass") == 0
    assert _w1g8_counters_on(island, "hourglass") == 1
    game.resolve_untap_step(1)
    assert not forest.tapped
    game.resolve_untap_step(0)
    assert island.tapped


def _w1g8_agenda_table(set_pool):
    """Seat 0 controls Yawgmoth's Agenda on its own turn; both seats hold two
    Healing Salves and have a Lightning Bolt in the graveyard."""
    pool = set_pool("LEA")
    game = _w1g8_enchantment_duel(set_pool)
    agenda = _w1g8_enchantment_put(game, set_pool, 0, "Yawgmoth's Agenda", "INV")
    game.players[0].graveyard = [
        pool["Lightning Bolt"], pool["Forest"], pool["Grizzly Bears"],
    ]
    game.players[1].graveyard = [pool["Lightning Bolt"]]
    for player in game.players:
        player.hand = [pool["Healing Salve"], pool["Healing Salve"]]
    return game, agenda


def test_yawgmoths_agenda_opens_its_controllers_graveyard_and_nobody_elses(set_pool):
    """"You may play lands and cast spells from your graveyard." A static
    permission of the permanent: every card in the controller's pile is
    offered, the opponent's pile is not, and it ends when the Agenda leaves."""
    from engine.cast_permissions import playable_from_zones

    game, agenda = _w1g8_agenda_table(set_pool)

    assert [
        (entry["owner_seat"], entry["name"]) for entry in playable_from_zones(game, 0)
    ] == [(0, "Lightning Bolt"), (0, "Forest"), (0, "Grizzly Bears")]
    assert playable_from_zones(game, 1) == []
    assert not game.cast_from_hand(
        1, "Lightning Bolt", from_zone="graveyard", target_player_index=0,
    ).supported

    game.remove_from_battlefield(agenda)

    assert playable_from_zones(game, 0) == []
    assert not game.cast_from_hand(
        0, "Grizzly Bears", from_zone="graveyard",
    ).supported
    assert "Grizzly Bears" in [card.name for card in game.players[0].graveyard]


def test_yawgmoths_agenda_plays_a_land_and_casts_one_spell_from_the_graveyard(set_pool):
    """Both verbs driven: the Forest is played out of the graveyard (a land is
    not a spell, so it does not spend the cap), the Lightning Bolt is cast out
    of it for 3 — and the Bolt is exiled as it resolves, by the card's third
    line."""
    game, _agenda = _w1g8_agenda_table(set_pool)

    assert game.cast_from_hand(0, "Forest", from_zone="graveyard").supported
    assert game.cast_from_hand(
        0, "Lightning Bolt", from_zone="graveyard", target_player_index=1,
    ).supported
    _w1g8_resolve_stack(game)

    assert "Forest" in [
        permanent.card.name for permanent in game.controlled_by(game.players[0])
    ]
    assert game.players[1].life == 17
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears"]
    assert [card.name for card in game.players[0].exile] == ["Lightning Bolt"]


def test_yawgmoths_agenda_caps_its_controller_at_one_spell_a_turn(set_pool):
    """"**You** can't cast more than one spell each turn." The second spell is
    refused from the hand and from the graveyard alike with its card where it
    was, the opponent casts two unhindered, and the cap resets next turn."""
    game, _agenda = _w1g8_agenda_table(set_pool)

    assert game.cast_from_hand(0, "Healing Salve", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert not game.cast_from_hand(0, "Healing Salve", target_player_index=0).supported
    assert not game.cast_from_hand(0, "Grizzly Bears", from_zone="graveyard").supported
    assert [card.name for card in game.players[0].hand] == ["Healing Salve"]
    assert "Grizzly Bears" in [card.name for card in game.players[0].graveyard]

    for _ in range(2):
        assert game.cast_from_hand(1, "Healing Salve", target_player_index=1).supported
        _w1g8_resolve_stack(game)
    assert game.players[1].hand == []

    game.resolve_cleanup_step(0)
    game.begin_turn_bookkeeping(1)
    assert game.cast_from_hand(0, "Healing Salve", target_player_index=0).supported


def test_yawgmoths_agenda_exiles_what_would_reach_its_controllers_graveyard(set_pool):
    """"If a card would be put into your graveyard from anywhere, exile it
    instead." The controller's resolved Healing Salve is exiled; the
    opponent's reaches their graveyard."""
    game, _agenda = _w1g8_agenda_table(set_pool)

    assert game.cast_from_hand(0, "Healing Salve", target_player_index=0).supported
    assert game.cast_from_hand(1, "Healing Salve", target_player_index=1).supported
    _w1g8_resolve_stack(game)

    assert [card.name for card in game.players[0].exile] == ["Healing Salve"]
    assert "Healing Salve" not in [card.name for card in game.players[0].graveyard]
    assert [card.name for card in game.players[1].graveyard] == [
        "Lightning Bolt", "Healing Salve",
    ]

"""Darksteel instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from tests.helpers import settle as _w1g4_settle


def _w1g4_card(set_pool, name):
    """A card by name: Darksteel first, then Alpha, Mirrodin and Core Set 2021."""
    for code in ("DST", "LEA", "MRD", "M21"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), their_hand=(),
                life=(20, 20), interactive=()):
    """Seat 0 to act in its first main phase, mana off, each named
    permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState("A", hand=[card(n) for n in hand],
                          library=[card("Forest")] * 12),
        _w1g4_PlayerState("B", hand=[card(n) for n in their_hand],
                          library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g4_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    game.players[0].life, game.players[1].life = life
    return game, placed[0], placed[1]


def _w1g4_where(game, name):
    """Every zone holding a card called *name*, as ``"<seat>.<zone>"``."""
    return sorted(
        f"{seat}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "graveyard", "library", "exile")
        for held in getattr(player, zone)
        if held.name == name
    )


def test_w1g4_pulse_of_the_fields_returns_while_an_opponent_stays_ahead(set_pool):
    """"You gain 4 life. Then if an opponent has more life than you, return
    Pulse of the Fields to its owner's hand." Compared after the gain, as the
    spell resolves: 10 + 4 is still behind 20, so the card comes back."""
    game, _mine, _theirs = _w1g4_table(set_pool, ["Pulse of the Fields"], life=(10, 20))
    assert game.cast_from_hand(0, "Pulse of the Fields").supported
    _w1g4_settle(game)
    assert game.players[0].life == 14
    assert _w1g4_where(game, "Pulse of the Fields") == ["0.hand"]
    assert any("returned to its owner's hand" in line for line in game.log)


def test_w1g4_pulse_of_the_fields_stays_in_the_graveyard_on_a_tie(set_pool):
    """"More life" is strict: the gain brings 16 level with 20 and the card
    goes to the graveyard like any other instant."""
    game, _mine, _theirs = _w1g4_table(set_pool, ["Pulse of the Fields"], life=(16, 20))
    game.cast_from_hand(0, "Pulse of the Fields")
    _w1g4_settle(game)
    assert game.players[0].life == 20
    assert _w1g4_where(game, "Pulse of the Fields") == ["0.graveyard"]


def test_w1g4_pulse_of_the_forge_compares_the_damaged_players_life(set_pool):
    """"…deals 4 damage to target player or planeswalker. Then if that player
    … has more life than you, return Pulse of the Forge to its owner's hand."
    The damage lands first: 20 - 4 = 16 is still ahead of 5, the card returns;
    16 - 4 = 12 is not ahead of 16, it does not."""
    game, _mine, _theirs = _w1g4_table(set_pool, ["Pulse of the Forge"], life=(5, 20))
    assert game.cast_from_hand(0, "Pulse of the Forge", target_player_index=1).supported
    _w1g4_settle(game)
    assert game.players[1].life == 16
    assert _w1g4_where(game, "Pulse of the Forge") == ["0.hand"]

    game, _mine, _theirs = _w1g4_table(set_pool, ["Pulse of the Forge"], life=(16, 16))
    game.cast_from_hand(0, "Pulse of the Forge", target_player_index=1)
    _w1g4_settle(game)
    assert game.players[1].life == 12
    assert _w1g4_where(game, "Pulse of the Forge") == ["0.graveyard"]


def test_w1g4_pulse_of_the_forge_at_a_planeswalker_asks_its_controller(set_pool):
    """"…or that planeswalker's controller": a planeswalker the opponent
    controls asks the opponent's life (20 against 5, the card returns); the
    caster's own planeswalker asks the caster's — nobody has more life than
    themselves, so the card stays in the graveyard. A spell that chose a
    permanent carries the default opposing seat as its player, which would
    have returned the card both times."""
    game, _mine, theirs = _w1g4_table(
        set_pool, ["Pulse of the Forge"], theirs=["Ugin, the Spirit Dragon"], life=(5, 20),
    )
    assert game.cast_from_hand(
        0, "Pulse of the Forge", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g4_settle(game)
    assert any("dealt 4 damage to Ugin" in line for line in game.log)
    assert game.players[1].life == 20
    assert _w1g4_where(game, "Pulse of the Forge") == ["0.hand"]

    game, mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Forge"], mine=["Ugin, the Spirit Dragon"], life=(5, 20),
    )
    game.cast_from_hand(0, "Pulse of the Forge", target_permanent_ids=[mine[0].permanent_id])
    _w1g4_settle(game)
    assert _w1g4_where(game, "Pulse of the Forge") == ["0.graveyard"]


def test_w1g4_a_forked_pulse_of_the_forge_returns_one_card(set_pool):
    """A copy has no card (CR 707.10a): Fork's copy deals its 4 and its
    "return Pulse of the Forge" moves nothing, while the original, resolving
    after it, returns the one card there is."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Forge", "Fork"], life=(5, 20),
    )
    assert game.queue_from_hand(0, "Pulse of the Forge", target_player_index=1).supported
    assert game.queue_from_hand(0, "Fork", target_player_index=1).supported
    _w1g4_settle(game)
    assert game.players[1].life == 12
    assert _w1g4_where(game, "Pulse of the Forge") == ["0.hand"]
    assert _w1g4_where(game, "Fork") == ["0.graveyard"]


def test_w1g4_pulse_of_the_grid_returns_when_the_opponent_holds_more(set_pool):
    """Drive list (supported on arrival, and it never returned: the handler
    looked for the card in a graveyard while it was still resolving). Draw
    two, discard one: one card in hand against the opponent's three."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Grid"], their_hand=["Forest", "Forest", "Forest"],
    )
    assert game.cast_from_hand(0, "Pulse of the Grid").supported
    _w1g4_settle(game)
    assert len(game.players[0].graveyard) == 1  # the discarded card
    assert _w1g4_where(game, "Pulse of the Grid") == ["0.hand"]

    game, _mine, _theirs = _w1g4_table(set_pool, ["Pulse of the Grid"], their_hand=["Forest"])
    game.cast_from_hand(0, "Pulse of the Grid")
    _w1g4_settle(game)
    assert _w1g4_where(game, "Pulse of the Grid") == ["0.graveyard"]

def _w1g4_creatures(game, seat):
    """Seat *seat*'s creatures as ``(name, power, toughness)``, sorted."""
    return sorted(
        (p.card.name, p.effective_power, p.effective_toughness)
        for p in game.controlled_by(seat) if p.is_creature
    )


def test_w1g4_echoing_truth_returns_every_permanent_sharing_the_targets_name(set_pool):
    """"Return target nonland permanent and all other permanents with the same
    name as that permanent to their owners' hands." Both sides' Grizzly Bears
    go to their owners' hands; the Ornithopter beside them stays."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Echoing Truth"], mine=["Grizzly Bears", "Ornithopter"],
        theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Echoing Truth", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g4_settle(game)
    assert _w1g4_creatures(game, 0) == [("Ornithopter", 0, 2)]
    assert _w1g4_creatures(game, 1) == []
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears", "Grizzly Bears"]


def test_w1g4_echoing_truth_on_a_token_takes_every_token_named_alike(set_pool):
    """A token's name is its subtypes plus "Token" (the card's 2022-06-10
    ruling on Echoing Courage, CR 111.4): two Beast Tokens share a name, and
    both leave — a token in a hand ceases to exist (CR 704.5d)."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Echoing Truth", "Pulse of the Tangle", "Pulse of the Tangle"],
        mine=["Ornithopter"],
    )
    for _ in range(2):
        game.cast_from_hand(0, "Pulse of the Tangle")
        _w1g4_settle(game)
    beasts = [p for p in game.controlled_by(0) if p.card.name == "Beast Token"]
    assert len(beasts) == 2
    game.cast_from_hand(0, "Echoing Truth", target_permanent_ids=[beasts[0].permanent_id])
    _w1g4_settle(game)
    assert _w1g4_creatures(game, 0) == [("Ornithopter", 0, 2)]
    assert [c.name for c in game.players[0].hand] == []


def test_w1g4_echoing_courage_pumps_each_namesake_once(set_pool):
    """Every Grizzly Bears gets +2/+2 — the target once, not again as one of
    "all other creatures" — and the Ornithopter gets nothing."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Echoing Courage"],
        mine=["Grizzly Bears", "Grizzly Bears", "Ornithopter"], theirs=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Echoing Courage", target_permanent_ids=[mine[0].permanent_id],
    ).supported
    _w1g4_settle(game)
    assert _w1g4_creatures(game, 0) == [
        ("Grizzly Bears", 4, 4), ("Grizzly Bears", 4, 4), ("Ornithopter", 0, 2),
    ]
    assert _w1g4_creatures(game, 1) == [("Grizzly Bears", 4, 4)]


def test_w1g4_echoing_courage_reaches_a_namesake_with_protection(set_pool):
    """The 2018-03-16 ruling: "Echoing Courage has only one target. Other
    creatures with that name are not targeted … a creature with protection
    from green will still get +2/+2." A Bears under Green Ward cannot be the
    target, and is pumped anyway as the target's namesake."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Green Ward", "Echoing Courage", "Echoing Courage"],
        mine=["Grizzly Bears"], theirs=["Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Green Ward", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g4_settle(game)
    refused = game.cast_from_hand(
        0, "Echoing Courage", target_permanent_ids=[theirs[0].permanent_id],
    )
    assert not refused.supported
    assert game.cast_from_hand(
        0, "Echoing Courage", target_permanent_ids=[mine[0].permanent_id],
    ).supported
    _w1g4_settle(game)
    assert _w1g4_creatures(game, 0) == [("Grizzly Bears", 4, 4)]
    assert _w1g4_creatures(game, 1) == [("Grizzly Bears", 4, 4)]


def test_w1g4_echoing_courage_with_its_target_gone_pumps_nobody(set_pool):
    """The 2018-03-16 ruling: "If the target creature is an illegal target by
    the time Echoing Courage tries to resolve, the spell doesn't resolve. No
    creatures get +2/+2." The target leaves in response; its namesake stays
    2/2."""
    game, mine, _theirs = _w1g4_table(
        set_pool, ["Echoing Courage"], mine=["Grizzly Bears", "Grizzly Bears"],
    )
    assert game.queue_from_hand(
        0, "Echoing Courage", target_permanent_ids=[mine[0].permanent_id],
    ).supported
    game.remove_from_battlefield(mine[0])
    _w1g4_settle(game)
    assert _w1g4_creatures(game, 0) == [("Grizzly Bears", 2, 2)]
    assert any("every target is illegal" in line for line in game.log)


def test_w1g4_echoing_decay_kills_every_two_toughness_namesake(set_pool):
    """-2/-2 to the target and to every other Grizzly Bears: all of them die
    to the state-based check (CR 704.5f); the Ornithopter (0/2, a different
    name) is untouched."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Echoing Decay"], mine=["Grizzly Bears"],
        theirs=["Grizzly Bears", "Ornithopter"],
    )
    assert game.cast_from_hand(
        0, "Echoing Decay", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g4_settle(game)
    assert _w1g4_creatures(game, 0) == []
    assert _w1g4_creatures(game, 1) == [("Ornithopter", 0, 2)]
    # The spell is binned as it resolves (CR 608.2n), the Bears after it.
    assert [c.name for c in game.players[0].graveyard] == ["Echoing Decay", "Grizzly Bears"]


def test_w1g4_echoing_calm_destroys_the_enchantment_and_its_namesakes(set_pool):
    """Drive list (supported on arrival). Two Crusades go, the Bad Moon
    beside them stays."""
    game, mine, theirs = _w1g4_table(
        set_pool, ["Echoing Calm"], mine=["Crusade"], theirs=["Crusade", "Bad Moon"],
    )
    assert game.cast_from_hand(
        0, "Echoing Calm", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g4_settle(game)
    assert [p.card.name for p in game.all_permanents()] == ["Bad Moon"]

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================

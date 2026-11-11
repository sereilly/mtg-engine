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
#
# Stand Together, from the drive list: supported on arrival and placing all
# four counters on the first creature named.

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from engine.oracle import compile_card_oracle as _w1g1_compile
from engine.targeting import derive_cast_spec as _w1g1_cast_spec
from tests.helpers import settle as _w1g1_settle


def test_w1g1_stand_together_puts_two_counters_on_each_of_two_creatures(set_pool):
    """"Put two +1/+1 counters on target creature and two +1/+1 counters on
    another target creature." Two announcements (the printed "another", CR
    601.2c), so the picker asks for two distinct creatures, one creature named
    twice is refused, and each takes two counters — the conjunction used to
    lower as two one-target steps, one picker, and four counters on the first
    creature."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    card = dst["Stand Together"]
    spec = _w1g1_cast_spec(card, _w1g1_compile(card))
    assert spec["kind"] == "roles"
    assert [role["role"] for role in spec["roles"]] == ["creature", "another creature"]

    game = _W1G1Game(players=[
        _W1G1PlayerState(name="P0", hand=[card, card], library=[lea["Island"]] * 5),
        _W1G1PlayerState(name="P1", library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g1_settle(game)
    bears, ogre = (_W1G1Permanent(card=lea["Grizzly Bears"]), _W1G1Permanent(card=lea["Gray Ogre"]))
    game._put_permanent_onto_battlefield(0, bears, None)
    game._put_permanent_onto_battlefield(1, ogre, None)
    _w1g1_settle(game)

    twice = game.cast_from_hand(
        0, "Stand Together", target_permanent_ids=[bears.permanent_id, bears.permanent_id]
    )
    assert not twice.supported

    cast = game.cast_from_hand(
        0, "Stand Together", target_permanent_ids=[bears.permanent_id, ogre.permanent_id]
    )
    assert cast.supported, cast
    _w1g1_settle(game)

    assert _w1g1_counters_on(bears, "+1/+1") == 2 and bears.effective_power == 4
    assert _w1g1_counters_on(ogre, "+1/+1") == 2 and ogre.effective_power == 4

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

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_cast_spec as _w1g5_derive_cast_spec
from tests.helpers import settle as _w1g5_settle


def _w1g5_burden_table(set_pool, mine=(), theirs=()):
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", hand=[set_pool("DST")["Burden of Greed"]],
                         library=[lea["Plains"]] * 10),
        _W1G5PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = {0: [], 1: []}
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G5Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g5_settle(game)
    return game, placed[0], placed[1]


def test_w1g5_burden_of_greed_counts_the_targets_tapped_artifacts(set_pool):
    """"Target player loses 1 life for each tapped artifact they control."
    "They" is the target, and "tapped" is a narrowing the count enforces: of
    Bob's three artifacts two are tapped, so he loses 2; Alice's own tapped
    artifact and Bob's untapped one count for nothing. The picker offers a
    player."""
    lea = set_pool("LEA")
    card = set_pool("DST")["Burden of Greed"]
    assert _w1g5_derive_cast_spec(card, _w1g5_compile(card)) == {"kind": "player"}
    game, mine, theirs = _w1g5_burden_table(
        set_pool,
        mine=[lea["Sol Ring"]],
        theirs=[lea["Sol Ring"], lea["Mox Pearl"], lea["Mox Jet"], lea["Grizzly Bears"]],
    )
    mine[0].tapped = True
    theirs[0].tapped = theirs[1].tapped = theirs[3].tapped = True
    game.cast_from_hand(0, "Burden of Greed", target_player_index=1)
    _w1g5_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 18)
    assert "Burden of Greed: Bob lost 2 life (20 -> 18)" in game.log


def test_w1g5_burden_of_greed_aimed_at_its_caster_counts_the_casters_board(set_pool):
    """Aimed at its own caster the count follows the target: Alice's two
    tapped artifacts, not Bob's three."""
    lea = set_pool("LEA")
    game, mine, theirs = _w1g5_burden_table(
        set_pool,
        mine=[lea["Sol Ring"], lea["Mox Pearl"]],
        theirs=[lea["Sol Ring"], lea["Mox Pearl"], lea["Mox Jet"]],
    )
    for permanent in mine + theirs:
        permanent.tapped = True
    game.cast_from_hand(0, "Burden of Greed", target_player_index=0)
    _w1g5_settle(game)
    assert (game.players[0].life, game.players[1].life) == (18, 20)

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Turn the Tables (a CR 614.9 redirect of every source's combat damage onto
# an announced attacker) and Hallow (Hidden Retreat's spell shield with CR
# 615.5's life gain, carried onto a permanent spell's permanent by CR 400.7c).
from engine import Game as _W1G6Game
from engine.models import Permanent as _W1G6Permanent
from engine.models import PlayerState as _W1G6PlayerState
from engine.oracle import compile_card_oracle as _w1g6_compile
from engine.targeting import derive_cast_spec as _w1g6_derive_cast_spec

from tests.helpers import declare_attack as _w1g6_declare_attack
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), opponent_hand=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G6PlayerState(
            name="Bob", hand=list(opponent_hand), library=[lea["Island"]] * 8,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    return game


def _w1g6_put(game, seat, card, *, tapped=False):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    game._sync_control()
    return permanent


def test_w1g6_turn_the_tables_sends_the_attack_back_onto_one_attacker(set_pool):
    """"All combat damage that would be dealt to you this turn is dealt to
    target attacking creature instead." Bob attacks with a Grizzly Bears and
    a Hill Giant; Turn the Tables on the Giant moves both attackers' damage
    onto it — 5 damage, and it dies — and Alice takes none. The picker offers
    attacking creatures."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    tables = dst["Turn the Tables"]
    assert _w1g6_derive_cast_spec(tables, _w1g6_compile(tables)) == {
        "kind": "creature", "attacking_only": True,
    }
    game = _w1g6_table(set_pool, hand=[tables])
    bear = _w1g6_put(game, 1, lea["Grizzly Bears"])
    giant = _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 1)
    result = game.cast_from_hand(0, "Turn the Tables", target_permanent_ids=[giant.permanent_id])
    assert result.supported, result.details
    _w1g6_settle(game)
    _w1g6_drive_combat(game)
    assert game.players[0].life == 20
    assert not game.is_on_battlefield(giant)
    assert game.is_on_battlefield(bear)
    assert sum("damage to Alice is dealt to Hill Giant instead" in line for line in game.log) == 2


def test_w1g6_turn_the_tables_targets_only_an_attacker_and_moves_only_combat_damage(set_pool):
    """A creature that is not attacking is no legal target; and the record
    moves combat damage alone — a Lightning Bolt at Alice later in the turn
    still hits her."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[dst["Turn the Tables"]], opponent_hand=[lea["Lightning Bolt"]],
    )
    attacker = _w1g6_put(game, 1, lea["Grizzly Bears"])
    home = _w1g6_put(game, 1, lea["Hill Giant"], tapped=True)
    _w1g6_declare_attack(game, 1)
    refused = game.cast_from_hand(0, "Turn the Tables", target_permanent_ids=[home.permanent_id])
    assert not refused.supported
    assert game.cast_from_hand(
        0, "Turn the Tables", target_permanent_ids=[attacker.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_settle(game)
    assert game.players[0].life == 17
    _w1g6_drive_combat(game)
    assert game.players[0].life == 17
    assert not game.is_on_battlefield(attacker)


def test_w1g6_turn_the_tables_does_nothing_once_its_target_is_gone(set_pool):
    """Ruling (2004-12-01): "If the targeted creature isn't on the
    battlefield when the combat damage would be dealt, the damage isn't
    redirected." The Giant is Terrored after Turn the Tables resolves; the
    Bears' 2 then land on Alice."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[dst["Turn the Tables"], lea["Terror"]])
    _w1g6_put(game, 1, lea["Grizzly Bears"])
    giant = _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 1)
    assert game.cast_from_hand(
        0, "Turn the Tables", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[giant.permanent_id]).supported
    _w1g6_settle(game)
    assert not game.is_on_battlefield(giant)
    _w1g6_drive_combat(game)
    assert game.players[0].life == 18


def test_w1g6_hallow_prevents_a_spells_damage_and_pays_its_caster(set_pool):
    """"Prevent all damage target spell would deal this turn. You gain life
    equal to the damage prevented this way." Bob's Lightning Bolt at Alice is
    on the stack; Hallow on it: the 3 is prevented and Alice gains 3. Aimed
    at Alice's creature instead, the creature lives and Alice still gains 3.
    The picker offers the stack."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    hallow = dst["Hallow"]
    assert _w1g6_derive_cast_spec(hallow, _w1g6_compile(hallow)) == {"kind": "stack"}
    game = _w1g6_table(set_pool, hand=[hallow], opponent_hand=[lea["Lightning Bolt"]])
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    result = game.cast_from_hand(0, "Hallow", target_stack_index=0)
    assert result.supported, result.details
    _w1g6_settle(game)
    assert [player.life for player in game.players] == [23, 20]

    game = _w1g6_table(set_pool, hand=[hallow], opponent_hand=[lea["Lightning Bolt"]])
    bear = _w1g6_put(game, 0, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bear.permanent_id],
    ).supported
    assert game.cast_from_hand(0, "Hallow", target_stack_index=0).supported
    _w1g6_settle(game)
    assert game.is_on_battlefield(bear) and bear.damage_marked == 0
    assert [player.life for player in game.players] == [23, 20]


def test_w1g6_hallow_follows_a_creature_spell_onto_the_battlefield(set_pool):
    """CR 400.7c: "Prevention effects that apply to damage from a permanent
    spell on the stack continue to apply to damage from the permanent that
    spell becomes." Hallow on Bob's Flametongue Kavu spell: the Kavu's entry
    trigger's 4 damage to Alice's Hill Giant is prevented, and the rider comes
    with it — Alice gains 4."""
    dst, lea, pls = set_pool("DST"), set_pool("LEA"), set_pool("PLS")
    game = _w1g6_table(
        set_pool, hand=[dst["Hallow"]], opponent_hand=[pls["Flametongue Kavu"]],
    )
    giant = _w1g6_put(game, 0, lea["Hill Giant"])
    assert game.queue_from_hand(
        1, "Flametongue Kavu", target_permanent_ids=[giant.permanent_id],
    ).supported
    assert game.cast_from_hand(0, "Hallow", target_stack_index=0).supported
    _w1g6_settle(game)
    assert game.is_on_battlefield(giant) and giant.damage_marked == 0
    assert [player.life for player in game.players] == [24, 20]


def test_w1g6_shriveling_rot_first_mode_destroys_each_creature_dealt_damage(set_pool):
    """"Until end of turn, whenever a creature is dealt damage, destroy it."
    A Lightning Bolt on a Wall of Stone (0/8) destroys it; then a Grizzly
    Bears blocked by a Hill Giant: the Bears die of their damage and the Giant
    is destroyed for the 2 it took. The ability is gone with the turn: next
    turn a damaged creature survives."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[dst["Shriveling Rot"], lea["Lightning Bolt"]])
    bear = _w1g6_put(game, 0, lea["Grizzly Bears"])
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])
    giant = _w1g6_put(game, 1, lea["Hill Giant"])
    result = game.cast_from_hand(0, "Shriveling Rot", mode_choices=[{"index": 0}])
    assert result.supported, result.details
    _w1g6_settle(game)
    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[wall.permanent_id]).supported
    _w1g6_settle(game)
    assert not game.is_on_battlefield(wall)
    _w1g6_declare_attack(game, 0, blocks={0: 0})
    _w1g6_drive_combat(game)
    assert not game.is_on_battlefield(bear) and not game.is_on_battlefield(giant)
    assert sorted(card.name for card in game.players[1].graveyard) == [
        "Hill Giant", "Wall of Stone",
    ]

    game = _w1g6_table(set_pool, hand=[dst["Shriveling Rot"]])
    survivor = _w1g6_put(game, 1, lea["Wall of Stone"])
    assert game.cast_from_hand(0, "Shriveling Rot", mode_choices=[{"index": 0}]).supported
    _w1g6_settle(game)
    game.resolve_cleanup_step(0)
    assert not game.delayed_triggers
    game.start_turn(1)
    game._settle()
    game.players[1].hand.append(lea["Lightning Bolt"])
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[survivor.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert game.is_on_battlefield(survivor) and survivor.damage_marked == 3


def test_w1g6_shriveling_rot_second_mode_charges_the_dead_creatures_toughness(set_pool):
    """"Until end of turn, whenever a creature dies, that creature's
    controller loses life equal to its toughness." The toughness is the
    creature's last-known one (CR 603.10a, 608.2h): a Hill Giant killed by a Bolt costs
    Bob 3."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[dst["Shriveling Rot"], lea["Lightning Bolt"]])
    giant = _w1g6_put(game, 1, lea["Hill Giant"])
    assert game.cast_from_hand(0, "Shriveling Rot", mode_choices=[{"index": 1}]).supported
    _w1g6_settle(game)
    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[giant.permanent_id]).supported
    _w1g6_settle(game)
    assert not game.is_on_battlefield(giant)
    assert [player.life for player in game.players] == [20, 17]


def test_w1g6_shriveling_rot_entwined_destroys_and_then_charges(set_pool):
    """Entwined (CR 702.42): both abilities are created. A Bolt on a Wall of
    Stone destroys it through the first, and its death costs Bob its
    toughness of 8 through the second."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[dst["Shriveling Rot"], lea["Lightning Bolt"]])
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])
    result = game.cast_from_hand(
        0, "Shriveling Rot", optional_cost_payments={"{2}{B}": 1},
        mode_choices=[{"index": 0}, {"index": 1}],
    )
    assert result.supported, result.details
    _w1g6_settle(game)
    assert sorted(entry.event for entry in game.delayed_triggers) == [
        "creature_dealt_damage", "creature_dies",
    ]
    assert game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[wall.permanent_id]).supported
    _w1g6_settle(game)
    assert not game.is_on_battlefield(wall)
    assert [player.life for player in game.players] == [20, 12]


def test_w1g6_savage_beating_only_in_its_casters_combat(set_pool):
    """Drive list. "Cast this spell only during combat on your turn." Refused
    in the main phase and in the opponent's combat — the clause used to be
    read as the bare "during combat" it begins with, lifting the seat — and
    cast in the caster's own: double strike on the attacker (2 + 2 damage),
    and entwined, an additional combat phase after this one."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, opponent_hand=[dst["Savage Beating"]])
    _w1g6_put(game, 0, lea["Grizzly Bears"])
    _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 0)
    refused = game.cast_from_hand(1, "Savage Beating", mode_choices=[{"index": 0}])
    assert not refused.supported
    assert "on your turn" in refused.details

    game = _w1g6_table(set_pool, hand=[dst["Savage Beating"]])
    assert not game.cast_from_hand(0, "Savage Beating", mode_choices=[{"index": 0}]).supported
    bear = _w1g6_put(game, 0, lea["Grizzly Bears"])
    _w1g6_declare_attack(game, 0)
    result = game.cast_from_hand(
        0, "Savage Beating", optional_cost_payments={"{1}{R}": 1},
        mode_choices=[{"index": 0}, {"index": 1}],
    )
    assert result.supported, result.details
    _w1g6_settle(game)
    _w1g6_drive_combat(game)
    assert game.players[1].life == 16
    assert not bear.tapped
    assert game.current_turn_phase == "combat", "the additional combat phase"

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

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
#
# Unforge and Murderous Spoils: what a single-target destroy finds attached,
# either way round, read after the destroy (CR 608.2h).

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.equipment import (attach_equipment as _w1g2_attach,
                              equipped_creature as _w1g2_equipped)
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool):
    island = set_pool("LEA")["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[island] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_cast(game, seat, card, target, *, queue=False):
    game.players[seat].hand.append(card)
    cast = game.queue_from_hand if queue else game.cast_from_hand
    result = cast(seat, card.name, target_permanent_ids=[target.permanent_id])
    assert result.supported, result
    return result


def test_w1g2_unforge_damages_the_creature_it_was_attached_to(set_pool):
    """"Destroy target Equipment. If that Equipment was attached to a creature,
    Unforge deals 2 damage to that creature." The Equipment goes, its creature
    takes 2 (the Bears die); an unattached Equipment hurts nobody."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 1)
    loose = _w1g2_put(game, dst["Leonin Bola"], 1)
    ogre = _w1g2_put(game, lea["Gray Ogre"], 1)
    _w1g2_attach(game, star, bears)
    _w1g2_cast(game, 0, dst["Unforge"], star)
    _w1g2_settle(game)
    assert star not in game.controlled_by(1)
    assert bears not in game.controlled_by(1)
    assert "Grizzly Bears died (704.5g: lethal damage)" in game.log

    _w1g2_cast(game, 0, dst["Unforge"], loose)
    _w1g2_settle(game)
    assert loose not in game.controlled_by(1)
    assert ogre.damage_marked == 0


def test_w1g2_unforge_reads_where_the_equipment_was_as_it_was_destroyed(set_pool):
    """2004-12-01: "Unforge deals damage only to the creature that the
    Equipment was attached to when the Equipment was destroyed. It doesn't
    deal damage to creatures that the Equipment had previously equipped."
    Moved in response, the new host takes the damage and the first does not."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
    first = _w1g2_put(game, lea["Grizzly Bears"], 1)
    second = _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_attach(game, star, first)
    _w1g2_cast(game, 0, dst["Unforge"], star, queue=True)
    assert [item.card.name for item in game.stack] == ["Unforge"]
    _w1g2_attach(game, star, second)  # in response
    _w1g2_settle(game)
    assert star not in game.controlled_by(1)
    assert first.damage_marked == 0
    assert second.damage_marked == 2


def test_w1g2_unforge_on_an_indestructible_equipment_still_deals_damage(set_pool):
    """The condition asks where the Equipment was, not whether it died: Shield
    of Kaldra survives the destroy (indestructible), and the creature it is
    attached to is still dealt 2 — it survives too, wearing the Shield's
    indestructible."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    shield = _w1g2_put(game, dst["Shield of Kaldra"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 1)
    _w1g2_attach(game, shield, bears)
    _w1g2_cast(game, 0, dst["Unforge"], shield)
    _w1g2_settle(game)
    assert shield in game.controlled_by(1) and _w1g2_equipped(shield) is bears
    assert bears in game.controlled_by(1)
    assert bears.damage_marked == 2


def test_w1g2_murderous_spoils_takes_the_equipment_that_were_attached(set_pool):
    """"Destroy target nonblack creature. It can't be regenerated. You gain
    control of all Equipment that were attached to it. (This effect lasts
    indefinitely.)" Both Equipment on the creature change hands for good, now
    unattached (CR 704.5n); an Equipment on another creature does not; a black
    creature is no target."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
    seeker = _w1g2_put(game, dst["Heartseeker"], 1)
    elsewhere = _w1g2_put(game, dst["Leonin Bola"], 1)
    giant = _w1g2_put(game, lea["Hill Giant"], 1)
    ogre = _w1g2_put(game, lea["Gray Ogre"], 1)
    knight = _w1g2_put(game, lea["Black Knight"], 1)
    _w1g2_attach(game, star, giant)
    _w1g2_attach(game, elsewhere, ogre)

    game.players[0].hand.append(dst["Murderous Spoils"])
    refused = game.cast_from_hand(0, "Murderous Spoils", target_permanent_ids=[knight.permanent_id])
    assert not refused.supported
    game.players[0].hand.clear()

    _w1g2_attach(game, seeker, giant)
    _w1g2_cast(game, 0, dst["Murderous Spoils"], giant)
    _w1g2_settle(game)
    assert giant not in game.controlled_by(1)
    assert star in game.controlled_by(0) and seeker in game.controlled_by(0)
    assert _w1g2_equipped(star) is None and _w1g2_equipped(seeker) is None
    assert elsewhere in game.controlled_by(1) and _w1g2_equipped(elsewhere) is ogre

    # Indefinitely: still ours on the opponent's turn and after.
    game.start_turn(1)
    _w1g2_settle(game)
    game.start_turn(0)
    _w1g2_settle(game)
    assert star in game.controlled_by(0) and seeker in game.controlled_by(0)


def test_w1g2_murderous_spoils_ignores_regeneration(set_pool):
    """"It can't be regenerated." A regeneration shield does not save it."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
    ape = _w1g2_put(game, set_pool("2ED")["Wall of Brambles"], 1)
    _w1g2_attach(game, star, ape)
    result = game.activate_permanent_ability(
        1, ape.card.name, permanent_index=game.battlefield_index_of(ape),
    )
    assert result.supported, result
    _w1g2_settle(game)
    _w1g2_cast(game, 0, dst["Murderous Spoils"], ape)
    _w1g2_settle(game)
    assert ape not in game.controlled_by(1)
    assert star in game.controlled_by(0)

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
#
# Second Sight, on W1G3's drive list (supported on arrival): a look and a
# reorder on a real library, which the mode-chooser census cannot build (its
# library is ten Forests).

from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from tests.helpers import settle as _w1g3_settle


def test_w1g3_second_sight_reorders_the_library_its_mode_names(set_pool):
    """"Choose one — • Look at the top five cards of target opponent's
    library, then put them back in any order. • Look at the top five cards of
    your library, then put them back in any order." Each mode rearranges the
    library it names, in the order the caster chooses, and leaves the other
    alone."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    names = ["Forest", "Island", "Swamp", "Mountain", "Plains", "Grizzly Bears"]
    for mode, seat in ((0, 1), (1, 0)):
        alice = _W1G3PlayerState(
            name="Alice", hand=[dst["Second Sight"]], library=[lea[n] for n in names],
        )
        bob = _W1G3PlayerState(name="Bob", library=[lea[n] for n in names])
        game = _W1G3Game(players=[alice, bob])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game.active_player_index = game.priority_player_index = 0
        game._set_phase_and_step("precombat_main", None)
        extra = {"target_player_index": 1} if mode == 0 else {}
        assert game.cast_from_hand(0, "Second Sight", mode_index=mode, **extra).supported
        pick = _w1g3_settle(game, defaults=False)
        assert pick is not None and pick.kind == "reorder_library"
        assert game.confirm_reorder_library(0, [4, 3, 2, 1, 0])
        _w1g3_settle(game)
        looked = game.players[seat].library
        other = game.players[1 - seat].library
        assert [c.name for c in looked] == [
            "Plains", "Mountain", "Swamp", "Island", "Forest", "Grizzly Bears",
        ]
        assert [c.name for c in other] == names

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
#
# Purge's union of two whole noun phrases, read into the filter "a black or
# artifact creature" already builds; Tears of Rage below.
from engine import Game as _W1G9Game
from engine.models import Permanent as _W1G9Permanent
from engine.models import PlayerState as _W1G9PlayerState
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_cast_spec as _w1g9_derive_cast_spec

from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    alice = _W1G9PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8)
    bob = _W1G9PlayerState(name="Bob", library=[lea["Swamp"]] * 8)
    game = _W1G9Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g9_put(game, seat, card):
    permanent = _W1G9Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g9_purge_destroys_an_artifact_creature_or_a_black_creature_only(set_pool):
    """"Destroy target artifact creature or black creature." The picker offers
    exactly the union — an artifact creature of any colour and a black
    creature of any type — and refuses a green creature and a noncreature
    artifact."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    purge = dst["Purge"]
    assert _w1g9_compile(purge).supported
    spec = _w1g9_derive_cast_spec(purge, _w1g9_compile(purge))
    assert spec.get("filter", spec).get("type_filter", spec.get("kind")) is not None, spec

    for name, legal in (
        ("Juggernaut", True), ("Scathe Zombies", True),
        ("Grizzly Bears", False), ("Sol Ring", False),
    ):
        game, alice, bob = _w1g9_table(set_pool, hand=[purge])
        victim = _w1g9_put(game, 1, lea[name])
        result = game.cast_from_hand(0, "Purge", target_permanent_ids=[victim.permanent_id])
        if not legal:
            assert not result.supported or not game.stack, (name, result.details)
            assert game.is_on_battlefield(victim), name
            continue
        assert result.supported, (name, result.details)
        _w1g9_settle(game)
        assert not game.is_on_battlefield(victim), name
        assert lea[name] in bob.graveyard, name


def test_w1g9_purge_ignores_a_regeneration_shield(set_pool):
    """"It can't be regenerated." Drudge Skeletons regenerates in response;
    the shield does not save it (CR 701.19c)."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool, hand=[dst["Purge"]])
    skeletons = _w1g9_put(game, 1, lea["Drudge Skeletons"])
    shield = game.activate_permanent_ability(1, "Drudge Skeletons")
    assert shield.supported, shield.details
    _w1g9_settle(game)
    result = game.cast_from_hand(0, "Purge", target_permanent_ids=[skeletons.permanent_id])
    assert result.supported, result.details
    _w1g9_settle(game)
    assert not game.is_on_battlefield(skeletons)
    assert lea["Drudge Skeletons"] in bob.graveyard



def _w1g9_attackers_table(set_pool):
    """Alice in her declare attackers step with Grizzly Bears and Scathe
    Zombies attacking and Llanowar Elves at home; Tears of Rage in hand."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool, hand=[dst["Tears of Rage"]])
    bears = _w1g9_put(game, 0, lea["Grizzly Bears"])
    zombies = _w1g9_put(game, 0, lea["Scathe Zombies"])
    elves = _w1g9_put(game, 0, lea["Llanowar Elves"])
    return game, alice, bob, (bears, zombies, elves)


def test_w1g9_tears_of_rage_pumps_the_attackers_by_their_number_then_sacrifices_them(set_pool):
    """"Attacking creatures you control get +X/+0 until end of turn, where X is
    the number of attacking creatures. Sacrifice those creatures at the
    beginning of the next end step." Two attackers: each gets +2/+0, the Elves
    at home get nothing; at the end step exactly those two are sacrificed."""
    game, alice, bob, (bears, zombies, elves) = _w1g9_attackers_table(set_pool)
    refused = game.cast_from_hand(0, "Tears of Rage")
    assert not refused.supported, "only during the declare attackers step"
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [alice.battlefield.index(bears), alice.battlefield.index(zombies)]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why
    result = game.cast_from_hand(0, "Tears of Rage")
    assert result.supported, result.details
    _w1g9_settle(game)
    assert (bears.effective_power, zombies.effective_power) == (4, 4)
    assert elves.effective_power == 1
    _w1g9_drive_combat(game)
    assert bob.life == 12
    game.resolve_end_step(0)
    _w1g9_settle(game)
    assert [p.card.name for p in alice.battlefield] == ["Llanowar Elves"]
    assert {"Grizzly Bears", "Scathe Zombies"} <= {c.name for c in alice.graveyard}
    assert any("Tears of Rage: sacrificed Grizzly Bears, Scathe Zombies" in line
               for line in game.log)


def test_w1g9_tears_of_rage_sacrifices_the_set_it_pumped_not_the_attackers_by_then(set_pool):
    """"Those creatures" is the set the first sentence reached (CR 611.2c), so
    the Bears, no longer attacking once combat is over, are still sacrificed,
    and the Zombies, already gone, are skipped (CR 608.2b)."""
    game, alice, bob, (bears, zombies, elves) = _w1g9_attackers_table(set_pool)
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [alice.battlefield.index(bears), alice.battlefield.index(zombies)]
    assert game.declare_attackers(0, slots, defending_player_index=1)[0]
    assert game.cast_from_hand(0, "Tears of Rage").supported
    _w1g9_settle(game)
    game.sacrifice_permanent(zombies)
    _w1g9_drive_combat(game)
    assert not bears.attacking
    game.resolve_end_step(0)
    _w1g9_settle(game)
    assert [p.card.name for p in alice.battlefield] == ["Llanowar Elves"]

# ==== end W1G9 ======================================================


# ==== W2G2 ==========================================================
# The AI's policy on Darksteel's cards (wave 2): a cast that adds a combat
# phase is priced through the fight it adds (CR 500.8).

from engine import Game as _W2G2Game
from engine.ai_actions import cast_announcement as _w2g2_cast_announcement
from engine.ai_combat import run_ai_combat_phase as _w2g2_run_ai_combat_phase
from engine.ai_policy import (
    choose_combat_instant_cast_action as _w2g2_choose_combat_instant_cast_action,
)
from engine.models import Permanent as _W2G2Permanent
from engine.models import PlayerState as _W2G2PlayerState
from tests.helpers import _mk_creature_card as _w2g2_creature
from tests.helpers import declare_attack as _w2g2_declare_attack
from tests.helpers import settle as _w2g2_settle


def _w2g2_attacking_table(set_pool, attacker, mana: int):
    """The AI seat's own combat, blocks declared: *attacker* unblocked,
    Savage Beating in hand, *mana* red in its pool and nothing across the
    table."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _W2G2Game(players=[
        _W2G2PlayerState(name="AI", hand=[dst["Savage Beating"]], library=[lea["Mountain"]] * 8),
        _W2G2PlayerState(name="Opp", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    permanent = _W2G2Permanent(card=attacker)
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    _w2g2_declare_attack(game, 0)
    assert game.current_step == "declare_blockers"
    game.players[0].mana_pool.update({"R": mana})
    return game


def _w2g2_cast_and_fight(game, action) -> None:
    result = game.cast_from_hand(0, action.card_name, **_w2g2_cast_announcement(action))
    assert result.supported, result.details
    _w2g2_settle(game)
    _w2g2_run_ai_combat_phase(game, 0)


def test_w2g2_savage_beating_extra_combat_is_cast_where_it_is_the_only_bullet(set_pool):
    """"Untap all creatures you control. After this phase, there is an
    additional combat phase." The attacker already has double strike, so
    the first bullet does nothing; the second is a second attack. A
    rehearsal that ran the combat out declaring nothing read that bullet as
    nothing that lasts (its untapped attacker is worth the same, attacking,
    tapped or not), and the AI held the card. Read through the fight it
    adds, it is the second attack's four damage, and the seat casts it
    without the entwine it cannot pay for."""
    striker = _w2g2_creature("Test Striker", 2, 2, "Double strike")
    game = _w2g2_attacking_table(set_pool, striker, mana=5)
    action = _w2g2_choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Savage Beating"
    assert action.mode_index == 1 and not action.mode_choices
    _w2g2_cast_and_fight(game, action)
    assert any("Additional phases this turn" in line for line in game.log)
    assert game.players[1].life == 20 - 4 - 4


def test_w2g2_savage_beating_is_entwined_for_both_combats(set_pool):
    """With the entwine cost in the pool, both bullets: double strike on the
    2/2 in this combat and in the one the second bullet adds — eight damage,
    where double strike alone is four. Before the added combat was fought by
    any reading, the entwined cast measured what double strike alone did and
    lost to it on printed order."""
    game = _w2g2_attacking_table(set_pool, set_pool("LEA")["Grizzly Bears"], mana=7)
    action = _w2g2_choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Savage Beating"
    assert sorted(choice["index"] for choice in action.mode_choices) == [0, 1]
    _w2g2_cast_and_fight(game, action)
    assert game.players[1].life == 20 - 8


def _w2g2_tears_table(set_pool, opponent_life: int):
    """Two Grizzly Bears attacking an empty board, Tears of Rage in hand and
    its mana in the pool: the attacker's declare-attackers step, the blocks
    still to come — the one step its window opens."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _W2G2Game(players=[
        _W2G2PlayerState(name="AI", hand=[dst["Tears of Rage"]], library=[lea["Swamp"]] * 8),
        _W2G2PlayerState(name="Opp", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    for _ in range(2):
        permanent = _W2G2Permanent(card=lea["Grizzly Bears"])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.players[1].life = opponent_life
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    assert game.declare_attackers(0, [0, 1], defending_player_index=1)[0]
    game.players[0].mana_pool.update({"R": 4})
    return game


def test_w2g2_tears_of_rage_is_cast_before_the_blocks_where_it_is_lethal(set_pool):
    """"Cast this spell only during the declare attackers step." The
    attacker's tricks wait for the declare-blockers step, where the blocks
    are known — and this one's window is shut by then, so it was never
    weighed at all (W1G9: no cast in any simulated game). Read through the
    fight from the step it can be cast in, two unblocked 2/2s at +2/+0 each
    are eight damage at eight life: the game."""
    game = _w2g2_tears_table(set_pool, opponent_life=8)
    action = _w2g2_choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Tears of Rage"
    result = game.cast_from_hand(0, action.card_name, **_w2g2_cast_announcement(action))
    assert result.supported, result.details
    _w2g2_settle(game)
    _w2g2_run_ai_combat_phase(game, 0)
    assert game.players[1].life <= 0


def test_w2g2_tears_of_rage_is_held_where_the_sacrifice_costs_more(set_pool):
    """The same attack at twenty life: four more damage, and both Bears
    sacrificed at the next end step. The rehearsal through the fight is the
    judge, and it holds the card."""
    game = _w2g2_tears_table(set_pool, opponent_life=20)
    assert _w2g2_choose_combat_instant_cast_action(game, 0) is None

# ==== end W2G2 ======================================================

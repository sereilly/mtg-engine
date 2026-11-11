"""Darksteel enchantments, Auras included.

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
#
# Carry Away: an Aura on an Equipment, its entry trigger's unattach, and the
# layer-2 control change while attached.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.equipment import (attach_equipment as _w1g2_attach,
                              equipped_creature as _w1g2_equipped)
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, interactive=()):
    island = set_pool("LEA")["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[island] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def test_w1g2_carry_away_takes_and_unattaches_an_equipment(set_pool):
    """"Enchant Equipment / When this Aura enters, unattach enchanted
    Equipment. / You control enchanted Equipment." Only an Equipment is a
    legal host (CR 303.4a); on entry it comes off the creature it was on and
    stays on the battlefield (CR 701.3d), under the Aura's controller (CR 613
    layer 2), who may then equip it (2004-12-01). The Aura gone, control goes
    back — and the Equipment stays where its new controller put it (gaining or
    losing control moves nothing)."""
    from engine.targeting import derive_cast_spec
    from engine.oracle import compile_card_oracle

    dst, lea = set_pool("DST"), set_pool("LEA")
    for interactive in ((), (0, 1)):
        game = _w1g2_table(set_pool, interactive=interactive)
        ogre = _w1g2_put(game, lea["Gray Ogre"], 0)
        star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
        bears = _w1g2_put(game, lea["Grizzly Bears"], 1)
        _w1g2_attach(game, star, bears)
        carry = dst["Carry Away"]
        assert derive_cast_spec(carry, compile_card_oracle(carry)) == {
            "kind": "artifact", "filter": {"subtype_filter": "equipment"},
        }
        game.players[0].hand = [carry]
        refused = game.cast_from_hand(0, "Carry Away", target_permanent_ids=[bears.permanent_id])
        assert not refused.supported
        result = game.cast_from_hand(0, "Carry Away", target_permanent_ids=[star.permanent_id])
        assert result.supported, result
        _w1g2_settle(game)
        aura = next(p for p in game.controlled_by(0) if p.card.name == "Carry Away")
        assert aura.metadata.get("attached_to") is star
        assert game.controller_index_of(star) == 0
        assert _w1g2_equipped(star) is None
        assert (bears.effective_power, bears.effective_toughness) == (2, 2)
        assert "Vulshok Morningstar became unattached (Carry Away)" in game.log

        equip = game.activate_permanent_ability(
            0, "Vulshok Morningstar", permanent_index=game.battlefield_index_of(star),
            target_permanent_ids=[ogre.permanent_id],
        )
        assert equip.supported, equip
        _w1g2_settle(game)
        assert _w1g2_equipped(star) is ogre
        assert (ogre.effective_power, ogre.effective_toughness) == (4, 4)

        game.remove_from_battlefield(aura)
        _w1g2_settle(game)
        assert game.controller_index_of(star) == 1
        assert _w1g2_equipped(star) is ogre

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

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

#
# Screams from Within, from the drive list: its "return this card from your
# graveyard" functions on the battlefield (CR 113.6m's Aura exception), and
# never fired before this group.
from engine import Game as _W1G9Game
from engine.models import Permanent as _W1G9Permanent
from engine.models import PlayerState as _W1G9PlayerState

from tests.helpers import settle as _w1g9_settle


def _w1g9_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    alice = _W1G9PlayerState(name="Alice", hand=list(hand), library=[lea["Swamp"]] * 8)
    bob = _W1G9PlayerState(name="Bob", library=[lea["Forest"]] * 8)
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


def _w1g9_screams(game):
    return next(
        (p for p in game.all_permanents() if p.card.name == "Screams from Within"), None,
    )


def test_w1g9_screams_from_within_returns_onto_another_creature_as_its_host_dies(set_pool):
    """"Enchanted creature gets -1/-1. When enchanted creature dies, return this
    card from your graveyard to the battlefield." On Bob's Llanowar Elves it
    kills them (CR 704.5f), goes to the graveyard (704.5m), and its trigger —
    collected from the battlefield as the Elves died (CR 113.6m, 603.10a) —
    brings it back. Alice chooses what it enchants (the 2005-08-01 ruling); a
    headless Alice puts it on one of Bob's creatures, never her own Bears."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool, hand=[dst["Screams from Within"]])
    first = _w1g9_put(game, 1, lea["Llanowar Elves"])
    _w1g9_put(game, 1, lea["Llanowar Elves"])
    _w1g9_put(game, 1, lea["Grizzly Bears"])
    own = _w1g9_put(game, 0, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Screams from Within", target_permanent_ids=[first.permanent_id]).supported
    _w1g9_settle(game)
    assert "Llanowar Elves" in [c.name for c in bob.graveyard]
    screams = _w1g9_screams(game)
    assert screams is not None
    host = screams.metadata.get("attached_to")
    assert host is not None and game.controller_index_of(host) == 1
    assert host is not first and game.is_on_battlefield(host)
    assert host.effective_toughness == int(host.card.printed_toughness) - 1
    assert (own.effective_power, own.effective_toughness) == (2, 2)
    assert game.controller_index_of(screams) == 0
    assert "Screams from Within" not in [c.name for c in alice.graveyard]


def test_w1g9_screams_from_within_asks_an_interactive_controller(set_pool):
    """An interactive Alice is asked which creature it enchants and may name
    her own (the ruling: "If your opponent doesn't control any creatures, you
    must choose one of your creatures" — any creature it can enchant is
    legal)."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool, hand=[dst["Screams from Within"]])
    elves = _w1g9_put(game, 1, lea["Llanowar Elves"])
    bears = _w1g9_put(game, 1, lea["Grizzly Bears"])
    own = _w1g9_put(game, 0, lea["Grizzly Bears"])
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Screams from Within", target_permanent_ids=[elves.permanent_id]).supported
    owed = _w1g9_settle(game, defaults=False)
    assert owed is not None and owed.kind == "permanent_choice" and owed.player_index == 0
    assert game.confirm_permanent_choice(0, own.permanent_id)
    _w1g9_settle(game)
    screams = _w1g9_screams(game)
    assert screams is not None and screams.metadata.get("attached_to") is own
    assert (own.effective_power, own.effective_toughness) == (1, 1)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g9_screams_from_within_with_nothing_to_enchant_stays_in_the_graveyard(set_pool):
    """CR 303.4g and the same ruling: "If there's nothing at all that Screams
    from Within can enchant, it remains in your graveyard.\""""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game, alice, bob = _w1g9_table(set_pool, hand=[dst["Screams from Within"]])
    elves = _w1g9_put(game, 1, lea["Llanowar Elves"])
    assert game.cast_from_hand(0, "Screams from Within", target_permanent_ids=[elves.permanent_id]).supported
    _w1g9_settle(game)
    assert _w1g9_screams(game) is None
    assert [c.name for c in alice.graveyard] == ["Screams from Within"]

# ==== end W1G9 ======================================================


# ==== W2G2 ==========================================================
# The AI's policy on Darksteel's cards (wave 2): the host a seat nobody asks
# returns Screams from Within onto.

from engine import Game as _W2G2Game
from engine.models import Permanent as _W2G2Permanent
from engine.models import PlayerState as _W2G2PlayerState
from tests.helpers import settle as _w2g2_settle


def _w2g2_put(game, seat, card):
    permanent = _W2G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w2g2_screams_from_within_returns_onto_the_creature_it_kills(set_pool):
    """W1G9: a headless controller returned Screams onto an opponent's
    creature, but onto the Grizzly Bears it shrinks rather than the second
    Llanowar Elves it kills (the dearer one, first on the board). The
    returning-Aura pick (``ai_targets.choose_returning_aura_host``) now
    takes the host its own -1/-1 kills: the Elves die, Screams comes back
    again, and ends on the Bears."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    alice = _W2G2PlayerState(name="Alice", hand=[dst["Screams from Within"]], library=[lea["Swamp"]] * 8)
    bob = _W2G2PlayerState(name="Bob", library=[lea["Forest"]] * 8)
    game = _W2G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None
    bears = _w2g2_put(game, 1, lea["Grizzly Bears"])
    first = _w2g2_put(game, 1, lea["Llanowar Elves"])
    second = _w2g2_put(game, 1, lea["Llanowar Elves"])
    assert game.cast_from_hand(
        0, "Screams from Within", target_permanent_ids=[first.permanent_id],
    ).supported
    _w2g2_settle(game)
    assert not game.is_on_battlefield(first) and not game.is_on_battlefield(second)
    assert [c.name for c in bob.graveyard].count("Llanowar Elves") == 2
    screams = next(p for p in game.all_permanents() if p.card.name == "Screams from Within")
    assert screams.metadata.get("attached_to") is bears
    assert (bears.effective_power, bears.effective_toughness) == (1, 1)

# ==== end W2G2 ======================================================

"""Scourge creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Typecycling (CR 702.29e-f): Scourge's seven creatures that search for a land
# type instead of drawing. The keyword's own rules tests are in
# tests/rules/test_scg_w1g2_typecycling.py; these drive each printed card.
import pytest as _w1g2_pytest
from fastapi.testclient import TestClient as _W1G2TestClient

from engine import Game as _W1G2Game
from engine.activation_zones import HAND as _W1G2_HAND
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState
from engine.oracle import compile_card_oracle as _w1g2_compile
from engine.targeting import usable_activated_abilities as _w1g2_usable

from tests.helpers import resolve_stack as _w1g2_resolve_stack

#: Each typecycler and the land type its search names.
_W1G2_TYPECYCLERS = {
    "Chartooth Cougar": "Mountain",
    "Elvish Aberration": "Forest",
    "Eternal Dragon": "Plains",
    "Noble Templar": "Plains",
    "Shoreline Ranger": "Island",
    "Twisted Abomination": "Swamp",
    "Wirewood Guardian": "Forest",
}


def _w1g2_table(set_pool, hand, library, *, interactive=False, mana=None):
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=list(library))
    bob = _W1G2PlayerState(name="Bob", library=[set_pool("LEA")["Island"]] * 5)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_phase = "main"
    alice.mana_pool.update(mana or {"C": 2})
    return game, alice, bob


def _w1g2_put(game, seat, card):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g2_basics(set_pool):
    lea = set_pool("LEA")
    return [lea["Grizzly Bears"]] + [
        lea[name] for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")
    ]


@_w1g2_pytest.mark.parametrize("name", sorted(_W1G2_TYPECYCLERS))
def test_w1g2_each_typecycler_finds_a_card_of_its_type(set_pool, name):
    """"[Type]cycling {2}": pay {2}, discard the card, search for a card of the
    type, reveal it, put it into the hand, shuffle (CR 702.29e). The card is
    cycled (CR 702.29f), so the log says so."""
    wanted = _W1G2_TYPECYCLERS[name]
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")[name]], _w1g2_basics(set_pool),
    )

    result = game.activate_from_hand(0, name)
    assert result.supported, result.details
    assert [c.name for c in alice.graveyard] == [name]
    assert not any(alice.mana_pool.values()), "the {2} was paid"
    assert f"Alice cycled {name}" in game.log
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [c.name for c in alice.hand] == [wanted]
    assert len(alice.library) == 5 and wanted not in [c.name for c in alice.library]
    assert any(f"revealed {wanted}" in line for line in game.log)


def test_w1g2_a_typecycle_can_be_stifled_and_the_card_stays_cycled(set_pool):
    """2009-02-01: "Mountaincycling is an activated ability. Effects that
    interact with activated abilities (such as Stifle …) will interact with
    Mountaincycling." The search is countered; the discard was the cost, so
    the card stays in the graveyard and nothing is found."""
    scg = set_pool("SCG")
    game, alice, bob = _w1g2_table(
        set_pool, [scg["Chartooth Cougar"]], _w1g2_basics(set_pool),
    )
    bob.hand.append(scg["Stifle"])
    bob.mana_pool["U"] = 1

    assert game.activate_from_hand(0, "Chartooth Cougar").supported
    (search,) = game.stack
    assert game.queue_from_hand(1, "Stifle", target_stack_index=0).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert not any(item is search for item in game.stack)
    assert alice.hand == [] and len(alice.library) == 6
    assert [c.name for c in alice.graveyard] == ["Chartooth Cougar"]
    assert [c.name for c in bob.graveyard] == ["Stifle"]


def test_w1g2_a_typecycler_cannot_be_activated_without_its_two(set_pool):
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Noble Templar"]], _w1g2_basics(set_pool),
        mana={"W": 1},
    )
    result = game.activate_from_hand(0, "Noble Templar")
    assert not result.supported
    assert [c.name for c in alice.hand] == ["Noble Templar"]
    assert alice.graveyard == [] and game.stack == []


def test_w1g2_shoreline_ranger_offers_a_person_only_island_cards(set_pool):
    """2009-02-01 rulings on the cycle: "You can choose to find any card with
    the … land type, including nonbasic lands." Tundra is a Plains Island; a
    Plains alone is not an answer."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Shoreline Ranger"]],
        [lea["Plains"], lea["Tundra"], lea["Island"]], interactive=True,
    )
    assert game.activate_from_hand(0, "Shoreline Ranger").supported
    game.resolve_top_of_stack()
    search = game.pending_choice_of("search_library", 0)
    assert search is not None
    assert search.data["restrictions"] == {"subtypes": ["island"]}

    names = [c.name for c in alice.library]
    assert not game.resolve_pending_choice(
        "search_library", 0, library_index=names.index("Plains"), zone="library",
    )
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=names.index("Tundra"), zone="library",
    )
    _w1g2_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Tundra"]


def test_w1g2_eternal_dragon_plainscycles_and_comes_back_in_your_upkeep(set_pool):
    """"{3}{W}{W}: Return this card from your graveyard to your hand. Activate
    only during your upkeep." The cycle puts it in the graveyard (CR 702.29e),
    the upkeep brings it back, and outside the upkeep it stays."""
    lea = set_pool("LEA")
    game, alice, _bob = _w1g2_table(
        set_pool, [set_pool("SCG")["Eternal Dragon"]], [lea["Plains"], lea["Swamp"]],
    )
    assert game.activate_from_hand(0, "Eternal Dragon").supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Plains"]
    assert [c.name for c in alice.graveyard] == ["Eternal Dragon"]

    alice.mana_pool.update({"W": 2, "C": 3})
    game.current_step = "draw"
    refused = game.activate_from_graveyard(0, "Eternal Dragon")
    assert not refused.supported, "only during your upkeep"
    assert [c.name for c in alice.graveyard] == ["Eternal Dragon"]

    game.current_step = "upkeep"
    assert game.activate_from_graveyard(0, "Eternal Dragon").supported
    _w1g2_resolve_stack(game)
    assert sorted(c.name for c in alice.hand) == ["Eternal Dragon", "Plains"]
    assert alice.graveyard == []


def test_w1g2_twisted_abomination_regenerates_and_cannot_swampcycle_from_play(set_pool):
    """On the battlefield the swampcycling ability exists but cannot be
    activated (CR 702.29b, 113.6j); "{B}: Regenerate this creature" can."""
    scg = set_pool("SCG")
    program = _w1g2_compile(scg["Twisted Abomination"])
    assert [a.instruction.kind for a in _w1g2_usable(program, zone=_W1G2_HAND)] == [
        "search_library"
    ]
    game, alice, bob = _w1g2_table(set_pool, [], _w1g2_basics(set_pool), mana={"B": 1})
    abomination = _w1g2_put(game, 0, scg["Twisted Abomination"])
    assert [a.instruction.kind for a in game.usable_abilities_of(abomination)] == [
        "grant_regeneration_to_self"
    ]
    assert game.activate_permanent_ability(
        0, "Twisted Abomination",
        permanent_index=game.battlefield_index_of(abomination), ability_index=0,
    ).supported
    _w1g2_resolve_stack(game)
    died = game._destroy_swept_permanents(alice, lambda perm: perm is abomination)
    assert died == [] and game.is_on_battlefield(abomination)
    assert abomination.tapped, "regeneration taps it (CR 701.19a)"


def test_w1g2_the_wire_labels_a_typecycling_button_with_its_printed_line(set_pool):
    """The hand-ability offer names the line as printed — "Plainscycling {2}",
    not the search the rewrite made of it — so the client's existing cycling
    button reads it; the search is the existing ``search_library`` prompt."""
    from web.app import app as _w1g2_app
    from web.app import store as _w1g2_store

    client = _W1G2TestClient(_w1g2_app)
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H",
        "host_colors": 2, "guest_colors": 2, "seed": 11,
    }).json()
    sid = created["session_id"]
    game = _w1g2_store.get(sid).game
    game.active_player_index = 0
    game.priority_player_index = 0
    templar = set_pool("SCG")["Noble Templar"]
    game.players[0].hand.append(templar)
    game.players[0].mana_pool["W"] = 2

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    (entry,) = [e for e in state["hand_abilities"] if e["name"] == "Noble Templar"]
    assert entry["text"].startswith("Plainscycling {2}")
    assert entry["payable"] is True and entry["prohibited"] is None

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
#
# Xantid Swarm: "Whenever this creature attacks, defending player can't cast
# spells this turn." The seat the attack froze (CR 506.2, 603.10), through
# the cast-prohibition table every cast path asks.
from engine import Game as _W1G8Game
from engine.cast_prohibitions import cast_prohibition as _w1g8_cast_prohibition
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_combat(set_pool, attackers, *, seats=2, hands=None):
    """*attackers* on seat 0, every seat holding *hands*[seat], at seat 0's
    declare-attackers step."""
    lea = set_pool("LEA")
    players = [
        _W1G8PlayerState(
            name=f"P{seat}", hand=list((hands or {}).get(seat, ())),
            library=[lea["Plains"]] * 5,
        )
        for seat in range(seats)
    ]
    game = _W1G8Game(players=players)
    game.enforce_mana_costs = False
    mine = []
    for card in attackers:
        perm = _W1G8Permanent(card=card)
        game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        mine.append(perm)
    _w1g8_resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    return game, mine


def test_w1g8_xantid_swarm_stops_the_defending_player_casting_this_turn(set_pool):
    """Before the trigger resolves the defender may still cast (2016-06-08:
    "The defending player may cast spells before Xantid Swarm's triggered
    ability resolves."); once it has, every spell is refused — an instant in
    combat and a creature later — while the attacker casts freely."""
    lea = set_pool("LEA")
    growth = lea["Giant Growth"]
    game, (swarm,) = _w1g8_combat(
        set_pool, [set_pool("SCG")["Xantid Swarm"]],
        hands={0: [growth], 1: [growth, growth, lea["Grizzly Bears"]]},
    )
    bears = _W1G8Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    assert game.declare_attackers(0, [0], 1)[0]
    assert [item.card.name for item in game.stack] == ["Xantid Swarm"]
    # In response: allowed.
    assert game.cast_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)
    assert any("P1 can't cast any spells this turn (Xantid Swarm)" in line for line in game.log)

    refused = game.cast_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported
    assert "can't cast any spells this turn" in refused.details
    prohibited = _w1g8_cast_prohibition(game, 1, lea["Grizzly Bears"])
    assert prohibited is not None and prohibited.kind == "casting_forbidden_this_turn"
    assert len(game.players[1].hand) == 2
    # The attacker is not bound.
    assert _w1g8_cast_prohibition(game, 0, growth) is None
    assert game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[swarm.permanent_id]).supported


def test_w1g8_xantid_swarm_binds_only_the_player_it_attacked(set_pool):
    """2016-06-08: "In a multiplayer game, only the player Xantid Swarm
    attacked is affected. Other defending players may cast spells." Swarm at
    P2, a Bear at P1: only P2 is stopped."""
    lea = set_pool("LEA")
    game, _mine = _w1g8_combat(
        set_pool, [set_pool("SCG")["Xantid Swarm"], lea["Grizzly Bears"]], seats=3,
    )
    ok, why = game.declare_attackers(0, [0, 1], attacker_targets={0: 2, 1: 1})
    assert ok, why
    _w1g8_resolve_stack(game)
    growth = lea["Giant Growth"]
    assert _w1g8_cast_prohibition(game, 2, growth) is not None
    assert _w1g8_cast_prohibition(game, 1, growth) is None
    assert _w1g8_cast_prohibition(game, 0, growth) is None


def test_w1g8_xantid_swarm_ban_ends_with_the_turn(set_pool):
    lea = set_pool("LEA")
    game, _mine = _w1g8_combat(set_pool, [set_pool("SCG")["Xantid Swarm"]])
    assert game.declare_attackers(0, [0], 1)[0]
    _w1g8_resolve_stack(game)
    assert _w1g8_cast_prohibition(game, 1, lea["Giant Growth"]) is not None
    game.start_next_turn()
    assert game.active_player_index == 1
    assert _w1g8_cast_prohibition(game, 1, lea["Giant Growth"]) is None

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================

"""Mirrodin enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
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

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_cast_spec as _w1g9_derive_cast_spec
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_domineer_board(set_pool, theirs):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(name="P0", hand=[mrd["Domineer"]]),
        _w1g9_PlayerState(
            name="P1", battlefield=[_w1g9_Permanent(card=lea[n]) for n in theirs]
        ),
    ])
    game.enforce_mana_costs = False
    return game


def _w1g9_named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def test_w1g9_domineer_offers_only_artifact_creatures(set_pool):
    """"Enchant artifact creature": the ruling (2004-12-01) — "The enchanted
    permanent must be both an artifact and a creature." The picker offers the
    Juggernaut and neither the Bears (a creature) nor the Sol Ring (an
    artifact)."""
    game = _w1g9_domineer_board(set_pool, ["Juggernaut", "Grizzly Bears", "Sol Ring"])
    domineer = set_pool("MRD")["Domineer"]
    spec = _w1g9_derive_cast_spec(domineer, _w1g9_compile(domineer))
    offered = game._enumerate_targets(0, domineer, spec, for_cast=True)
    assert sorted(t["name"] for t in offered) == ["Juggernaut"]


def test_w1g9_domineer_takes_control_of_the_artifact_creature(set_pool):
    """"You control enchanted artifact creature." The Juggernaut changes
    sides as Domineer attaches (CR 613 layer 2, the attachment sweep), and a
    cast aimed at the Bears is refused."""
    game = _w1g9_domineer_board(set_pool, ["Juggernaut", "Grizzly Bears"])
    bears = _w1g9_named(game, "Grizzly Bears")
    refused = game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert not getattr(refused, "supported", True) or not game.stack
    assert [c.name for c in game.players[0].hand] == ["Domineer"]
    juggernaut = _w1g9_named(game, "Juggernaut")
    game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[juggernaut.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(juggernaut) == 0
    assert _w1g9_named(game, "Domineer").metadata.get("attached_to") is juggernaut


def test_w1g9_domineer_falls_off_an_artifact_that_stops_being_a_creature(set_pool):
    """The ruling (2004-12-01): "Domineer 'falls off' and is put into the
    graveyard if the artifact creature it's enchanting stops being an artifact
    or stops being a creature." A Sol Ring animated by Animate Artifact is
    stolen; destroying Animate Artifact ends the creature type, the CR 704.5m
    sweep bins Domineer, and the Sol Ring goes home."""
    lea = set_pool("LEA")
    game = _w1g9_domineer_board(set_pool, ["Sol Ring"])
    ring = _w1g9_named(game, "Sol Ring")
    game.players[1].hand.append(lea["Animate Artifact"])
    game.cast_from_hand(
        1, "Animate Artifact", target_player_index=1,
        target_permanent_ids=[ring.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert ring.is_creature
    game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[ring.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(ring) == 0
    game._destroy_target_permanent(
        game.players[1], described={"named": "Animate Artifact"}
    )
    game._settle()
    assert not ring.is_creature
    assert [c.name for c in game.players[0].graveyard] == ["Domineer"]
    assert game.controller_index_of(ring) == 1


def _w1g9_loyalty_board(set_pool):
    """Fractured Loyalty (seat 0's) on seat 1's Grizzly Bears, two Giant
    Growths in each hand."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P0", hand=[mrd["Fractured Loyalty"], lea["Giant Growth"]]
        ),
        _w1g9_PlayerState(
            name="P1", hand=[lea["Giant Growth"]],
            battlefield=[_w1g9_Permanent(card=lea["Grizzly Bears"])],
        ),
    ])
    game.enforce_mana_costs = False
    bears = _w1g9_named(game, "Grizzly Bears")
    game.cast_from_hand(
        0, "Fractured Loyalty", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    return game, bears


def test_w1g9_fractured_loyalty_hands_the_creature_to_whoever_targets_it(set_pool):
    """"Whenever enchanted creature becomes the target of a spell or ability,
    that spell or ability's controller gains control of that creature." P0's
    Giant Growth on P1's Bears hands them to P0 (the trigger resolves first,
    above the spell); P1 targeting them back takes them home."""
    game, bears = _w1g9_loyalty_board(set_pool)
    assert game.controller_index_of(bears) == 1
    game.queue_from_hand(
        0, "Giant Growth", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert [item.card.name for item in game.stack] == [
        "Giant Growth", "Fractured Loyalty",
    ]
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(bears) == 0
    assert "P0 gains control of Grizzly Bears" in game.log
    assert bears.effective_power == 5

    game.cast_from_hand(
        1, "Giant Growth", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(bears) == 1


def test_w1g9_fractured_loyalty_change_lasts_after_the_aura_is_gone(set_pool):
    """"(This effect lasts indefinitely.)" CR 611.2a: the trigger's control
    change has no duration, so neither the Aura leaving *in response* — the
    trigger resolves without its source (CR 113.7a) and still names the
    creature it fired on — nor the Aura being gone afterwards sends the Bears
    back."""
    game, bears = _w1g9_loyalty_board(set_pool)
    game.queue_from_hand(
        0, "Giant Growth", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert len(game.stack) == 2
    # In response to the trigger, the Aura is destroyed.
    game._destroy_target_permanent(
        game.players[0], described={"named": "Fractured Loyalty"}
    )
    assert [c.name for c in game.players[0].graveyard] == ["Fractured Loyalty"]
    assert len(game.stack) == 2
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(bears) == 0
    assert bears.effective_power == 5


def test_w1g9_fractured_loyalty_own_controller_targeting_changes_nothing(set_pool):
    game, bears = _w1g9_loyalty_board(set_pool)
    game.cast_from_hand(
        1, "Giant Growth", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(bears) == 1
    assert "Grizzly Bears is already controlled by P1" in game.log


def _w1g9_confusion_game(set_pool, *, mine=(), theirs=(), hands=((), ())):
    """Confusion in the Ranks on seat 0's battlefield beside *mine*; *theirs*
    on seat 1's; LEA cards in each hand."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P0",
            battlefield=[_w1g9_Permanent(card=mrd["Confusion in the Ranks"])]
            + [_w1g9_Permanent(card=lea[n]) for n in mine],
            hand=[lea[n] for n in hands[0]],
        ),
        _w1g9_PlayerState(
            name="P1",
            battlefield=[_w1g9_Permanent(card=lea[n]) for n in theirs],
            hand=[lea[n] for n in hands[1]],
        ),
    ])
    game.enforce_mana_costs = False
    return game


def _w1g9_seats(game):
    return {p.card.name: game.controller_index_of(p) for p in game.all_permanents()}


def test_w1g9_confusion_in_the_ranks_exchanges_the_entering_creature(set_pool):
    """"Whenever an artifact, creature, or enchantment enters, its controller
    chooses target permanent another player controls that shares a card type
    with it. Exchange control of those permanents." P0's Bears enter and are
    traded for P1's Hill Giant — the creature, not the Sol Ring, which shares
    no type with them."""
    game = _w1g9_confusion_game(
        set_pool, theirs=["Hill Giant", "Sol Ring"], hands=(["Grizzly Bears"], ())
    )
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_seats(game) == {
        "Confusion in the Ranks": 0, "Hill Giant": 0, "Grizzly Bears": 1,
        "Sol Ring": 1,
    }


def test_w1g9_confusion_in_the_ranks_entering_permanents_controller_chooses(set_pool):
    """"**Its controller** chooses": when P1's Elves enter, the choice is
    P1's — an interactive P1 is asked, offered P0's creatures only (not the
    enchantment, which shares no type with the Elves), and the trigger waits
    on the stack until the answer."""
    game = _w1g9_confusion_game(
        set_pool, mine=["Grizzly Bears", "Hill Giant"],
        hands=((), ["Llanowar Elves"]),
    )
    game.interactive_seats = {1}
    game.active_player_index = 1
    game.cast_from_hand(1, "Llanowar Elves")
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("permanent_choice", 1)
    ]
    offered = game.live_permanent_choices(game.pending_choices[0])
    assert sorted(p.card.name for p in offered) == ["Grizzly Bears", "Hill Giant"]
    assert [item.card.name for item in game.stack] == ["Confusion in the Ranks"]
    giant = _w1g9_named(game, "Hill Giant")
    assert game.confirm_permanent_choice(1, giant.permanent_id) is True
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_seats(game) == {
        "Confusion in the Ranks": 0, "Grizzly Bears": 0, "Llanowar Elves": 0,
        "Hill Giant": 1,
    }


def test_w1g9_confusion_in_the_ranks_trades_itself_for_an_enchantment(set_pool):
    """The ruling (2004-12-01): "Confusion in the Ranks triggers on itself
    entering. If an opponent controls an enchantment, exchange Confusion in the
    Ranks for that enchantment." And the exchange is not optional (2004-10-04)
    — a seat nobody asks takes the one legal choice."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(name="P0", hand=[mrd["Confusion in the Ranks"]]),
        _w1g9_PlayerState(
            name="P1",
            battlefield=[
                _w1g9_Permanent(card=lea["Crusade"]),
                _w1g9_Permanent(card=lea["Grizzly Bears"]),
            ],
        ),
    ])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Confusion in the Ranks")
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_seats(game) == {
        "Confusion in the Ranks": 1, "Crusade": 0, "Grizzly Bears": 1,
    }


def test_w1g9_confusion_in_the_ranks_needs_both_on_the_battlefield(set_pool):
    """The ruling (2004-12-01): "The permanents are exchanged only if they're
    both on the battlefield when the ability resolves." The entering Bears
    leave with the trigger on the stack, and nothing changes hands."""
    game = _w1g9_confusion_game(
        set_pool, theirs=["Hill Giant"], hands=(["Grizzly Bears"], ())
    )
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Grizzly Bears")
    assert [item.card.name for item in game.stack] == ["Confusion in the Ranks"]
    bears = _w1g9_named(game, "Grizzly Bears")
    game.remove_from_battlefield(bears)
    _w1g9_resolve_stack(game)
    game._settle()
    assert _w1g9_seats(game) == {"Confusion in the Ranks": 0, "Hill Giant": 1}


# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================

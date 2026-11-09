"""Mirrodin creatures (legendary ones too).

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

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def test_w1g1_loxodon_punisher_grows_with_each_equipment_and_shrinks_when_one_moves(set_pool):
    """'This creature gets +2/+2 for each Equipment attached to it.' Equipped
    twice through the real equip ability, then one Equipment moves away."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    island = lea["Island"]
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", library=[island] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)

    def put(card):
        permanent = _W1G1Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        game._settle()
        return permanent

    def equip(gear, creature):
        result = game.activate_permanent_ability(
            0, gear.card.name, permanent_index=game.battlefield_index_of(gear),
            target_permanent_ids=[creature.permanent_id],
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        game._settle()

    punisher = put(mrd["Loxodon Punisher"])
    bears = put(lea["Grizzly Bears"])
    scimitar = put(mrd["Leonin Scimitar"])
    splitter = put(mrd["Bonesplitter"])
    assert (punisher.effective_power, punisher.effective_toughness) == (2, 2)
    equip(scimitar, punisher)
    assert (punisher.effective_power, punisher.effective_toughness) == (5, 5)
    equip(splitter, punisher)
    assert (punisher.effective_power, punisher.effective_toughness) == (9, 7)
    equip(scimitar, bears)
    assert (punisher.effective_power, punisher.effective_toughness) == (6, 4)

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
import pytest
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_game(set_pool, mine=(), hand=(), theirs=(), their_hand=(), interactive=(),
               library=None):
    pool = set_pool("MRD")
    other = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else other[name]

    p1 = _w1g7_PlayerState(
        name="P1",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in mine],
        hand=[card(n) for n in hand],
        library=(
            [card(n) for n in library] if library is not None
            else [other["Island"]] * 10
        ),
    )
    p2 = _w1g7_PlayerState(
        name="P2",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in theirs],
        hand=[card(n) for n in their_hand], library=[other["Island"]] * 10,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _w1g7_until_owed(game, kind, seat=0):
    """Resolve the top of the stack until *kind* is owed by *seat* — the
    interactive seat's turn to answer, which ``resolve_stack`` would answer by
    default."""
    for _ in range(10):
        if game.pending_choice_of(kind, seat) is not None:
            return game.pending_choice_of(kind, seat)
        if not game.stack:
            break
        game.resolve_top_of_stack()
    return game.pending_choice_of(kind, seat)


def _w1g7_settle(game):
    """Drain the stack and answer, as a headless seat, what a bare table left
    on the queue (an offer made by a trigger that resolved with nobody held)."""
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)


def test_w1g7_leonin_elder_gains_on_any_artifact_entering(set_pool):
    """"Whenever **an** artifact enters, you may gain 1 life." The condition
    table read only "a"/"another", so the line was no trigger and the Elder
    refused as text too complex. An opponent's artifact counts (no "you
    control"); a nonartifact creature does not."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Leonin Elder"], hand=["Grizzly Bears"],
        their_hand=["Ornithopter"],
    )
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert p1.life == 21
    assert "P1 gained 1 life from Leonin Elder (20 -> 21)" in game.log

    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert p1.life == 21, "a nonartifact creature is not an artifact"


def test_w1g7_leonin_elder_may_decline(set_pool):
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Leonin Elder"], hand=["Ornithopter"], interactive=(0,),
    )
    game.cast_from_hand(0, "Ornithopter")
    assert _w1g7_until_owed(game, "optional_pay") is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    _w1g7_resolve(game)
    assert p1.life == 20


def test_w1g7_vermiculos_grows_per_artifact_this_turn(set_pool):
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Vermiculos"], hand=["Ornithopter", "Ornithopter"],
    )
    vermiculos = p1.battlefield[0]
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert (vermiculos.effective_power, vermiculos.effective_toughness) == (5, 5)
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert (vermiculos.effective_power, vermiculos.effective_toughness) == (9, 9)


def test_w1g7_lumengrid_sentinel_taps_on_its_controllers_artifact_only(set_pool):
    """"…an artifact **you control** enters": the narrowing is enforced — the
    opponent's artifact fires nothing — and the seat chooses the target as the
    trigger goes on the stack (CR 603.3d)."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Lumengrid Sentinel"], hand=["Ornithopter"],
        theirs=["Grizzly Bears"], their_hand=["Ornithopter"], interactive=(0,),
    )
    bears = p2.battlefield[0]
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert game.pending_choices == [] and not bears.tapped

    game.cast_from_hand(0, "Ornithopter")
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None, game.log
    assert "Grizzly Bears" in [t["name"] for t in prompt.data["targets"]]
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id, seat=1)
    assert _w1g7_until_owed(game, "optional_pay") is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g7_resolve(game)
    assert bears.tapped
    assert "Tapped Grizzly Bears" in game.log


def test_w1g7_vedalken_archmage_draws_for_artifact_spells_only(set_pool):
    """"Whenever you cast **an** artifact spell, draw a card." The table's type
    row carried "artifact" and read "a" before it, so no card could reach it."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Vedalken Archmage"],
        hand=["Ornithopter", "Grizzly Bears"], their_hand=["Ornithopter"],
    )
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert len(p1.hand) == 2, "cast one, drew one"
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert len(p1.hand) == 1, "a creature spell is not an artifact spell"
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert len(p1.hand) == 1, "an opponent's artifact spell is not yours"

@pytest.mark.parametrize(
    "top,zone",
    [("Ornithopter", "hand"), ("Leonin Elder", "graveyard"), ("Island", "graveyard")],
)
def test_w1g7_neurok_familiar_sorts_the_revealed_card(set_pool, top, zone):
    """"…reveal the top card of your library. If it's an artifact card, put it
    into your hand. **Otherwise, put it into your graveyard.**" The reveal-top
    template knew one "otherwise" (the library's bottom). Ornithopter is an
    *artifact creature* card, which is an artifact card (CR 205.2) — the handler
    asked ``primary_type``, which answers "creature" for it."""
    game, p1, _p2 = _w1g7_game(
        set_pool, hand=["Neurok Familiar"], library=[top, "Island", "Island"],
    )
    game.cast_from_hand(0, "Neurok Familiar")
    _w1g7_settle(game)
    names = {
        "hand": [c.name for c in p1.hand],
        "graveyard": [c.name for c in p1.graveyard],
    }
    assert names[zone] == [top], game.log
    assert len(p1.library) == 2
    put = "hand" if zone == "hand" else "graveyard"
    assert f"P1 revealed {top} and put it into their {put}" in game.log

@pytest.mark.parametrize("pick,untapped", [("Ornithopter", True), ("Mountain", False)])
def test_w1g7_lumengrid_augur_untaps_when_the_target_discards_an_artifact(
    set_pool, pick, untapped
):
    """"{1}, {T}: Target player draws a card, then discards a card. **If that
    player discards an artifact card this way**, untap this creature." The
    record condition read the narrowed question with "you" as the subject
    only. The target picks (an interactive seat), and the untap waits for the
    answer: it reads which card went, not whether one did."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Lumengrid Augur"], their_hand=["Ornithopter", "Mountain"],
        interactive=(1,),
    )
    augur = game.players[0].battlefield[0]
    result = game.activate_permanent_ability(0, "Lumengrid Augur", target_player_index=1)
    assert result.supported, result.details
    assert augur.tapped
    prompt = _w1g7_until_owed(game, "discard", 1)
    assert prompt is not None, game.log
    assert len(p2.hand) == 3, "drew first"
    index = [c.name for c in p2.hand].index(pick)
    assert game.resolve_pending_choice("discard", 1, hand_indices=[index], to_library=False)
    _w1g7_resolve(game)
    assert [c.name for c in p2.graveyard] == [pick]
    assert augur.tapped is not untapped
    assert ("Lumengrid Augur untapped" in game.log) is untapped

# ==== end W1G7 ======================================================

"""Torment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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
#
# Linked exile and leaving the battlefield (CR 607.2a): "return the exiled
# cards" in three destinations (Gravegouger, Hypnox, Petradon), Mesmeric
# Fiend's chosen card, and Chainer's reanimation. Each card is driven through
# the real cast / activation / response path, and each "old-style O-Ring"
# card is also killed with its entry trigger on the stack: the leave trigger
# resolves first and returns nothing, then the entry trigger exiles for good
# (Mesmeric Fiend's ruling, 2018-03-16).

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.linked_exile import linked_entries as _w1g3_linked_entries
from engine.models import Permanent as _W1G3Permanent
from engine.object_colors import object_colors as _w1g3_object_colors
from engine.layer_bridge import computed_types as _w1g3_computed_types
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_card(set_pool, name):
    for code in ("TOR", "LEA", "ODY"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g3_game(set_pool, *, hand=(), opp_hand=(), opp_graveyard=(), graveyard=()):
    card = lambda name: _w1g3_card(set_pool, name)  # noqa: E731
    p0 = _W1G3PlayerState(
        name="P0", hand=[card(n) for n in hand],
        graveyard=[card(n) for n in graveyard],
        library=[card("Swamp")] * 5,
    )
    p1 = _W1G3PlayerState(
        name="P1", hand=[card(n) for n in opp_hand],
        graveyard=[card(n) for n in opp_graveyard],
        library=[card("Forest")] * 5,
    )
    game = _W1G3Game(players=[p0, p1])
    game.enforce_mana_costs = False
    return game


def _w1g3_put(game, set_pool, seat, name):
    permanent = _W1G3Permanent(card=_w1g3_card(set_pool, name))
    permanent.metadata["summoning_sickness_turn"] = -5
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g3_resolve_stack(game)
    return permanent


def _w1g3_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g3_drain(game):
    for _ in range(4):
        _w1g3_resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _w1g3_swords_in_response(game, victim):
    """Exile *victim* with Swords to Plowshares while its entry trigger is
    still on the stack — the response CR 603.3 made possible."""
    result = game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log[-5:]
    _w1g3_drain(game)


# --- Gravegouger: "return the exiled cards to their owner's graveyard" -----


def test_w1g3_gravegouger_exiles_two_cards_and_returns_them_when_it_leaves(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Gravegouger", "Swords to Plowshares"],
        opp_graveyard=["Lightning Bolt", "Grizzly Bears", "Giant Growth"],
    )
    p1 = game.players[1]
    game.cast_from_hand(0, "Gravegouger")
    _w1g3_drain(game)

    assert len(p1.exile) == 2, game.log[-5:]
    assert len(p1.graveyard) == 1
    gouger = _w1g3_named(game, 0, "Gravegouger")
    # CR 607.2a: the two cards are recorded as exiled *with* the Gravegouger.
    assert sorted(e["card"].name for e in _w1g3_linked_entries(gouger)) == sorted(
        c.name for c in p1.exile
    )

    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[gouger.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.graveyard) == [
        "Giant Growth", "Grizzly Bears", "Lightning Bolt",
    ]


def test_w1g3_gravegouger_killed_in_response_exiles_for_good(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Gravegouger", "Swords to Plowshares"],
        opp_graveyard=["Lightning Bolt", "Grizzly Bears"],
    )
    p1 = game.players[1]
    game.queue_from_hand(0, "Gravegouger")
    game.resolve_top_of_stack()
    gouger = _w1g3_named(game, 0, "Gravegouger")
    assert game.stack, "the entry trigger is a stack object (CR 603.3)"

    _w1g3_swords_in_response(game, gouger)

    # The leave trigger resolved first and found nothing; the entry trigger
    # then exiled both cards, and nothing is left to bring them back.
    assert sorted(c.name for c in p1.exile) == ["Grizzly Bears", "Lightning Bolt"]
    assert p1.graveyard == []


# --- Petradon: "…to the battlefield under their owners' control" -----------


def test_w1g3_petradon_exiles_two_lands_and_returns_them_to_their_owners(set_pool):
    game = _w1g3_game(set_pool, hand=["Petradon", "Swords to Plowshares"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    mountain = _w1g3_put(game, set_pool, 1, "Mountain")
    game.cast_from_hand(
        0, "Petradon", target_player_index=1,
        target_permanent_ids=[forest.permanent_id, mountain.permanent_id],
    )
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Mountain"]

    petradon = _w1g3_named(game, 0, "Petradon")
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[petradon.permanent_id],
    )
    _w1g3_drain(game)

    # Under their owner's control (CR 110.2a), and as new objects (CR 400.7).
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Forest", "Mountain"]
    assert game.players[1].exile == []
    assert all(p.permanent_id not in (forest.permanent_id, mountain.permanent_id)
               for p in game.controlled_by(1))


def test_w1g3_petradon_killed_in_response_keeps_the_lands_exiled(set_pool):
    game = _w1g3_game(set_pool, hand=["Petradon", "Swords to Plowshares"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    mountain = _w1g3_put(game, set_pool, 1, "Mountain")
    game.queue_from_hand(
        0, "Petradon", target_player_index=1,
        target_permanent_ids=[forest.permanent_id, mountain.permanent_id],
    )
    game.resolve_top_of_stack()
    petradon = _w1g3_named(game, 0, "Petradon")

    _w1g3_swords_in_response(game, petradon)

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Mountain"]


def test_w1g3_petradon_owes_two_targets_or_none(set_pool):
    """"Exile **two** target lands": a printed count with no "up to" is owed
    whole (CR 601.2c). A one-land board offers no legal announcement, so
    CR 603.3d takes the trigger off the stack — it does not exile the one land
    it could reach. A cast naming one land is set aside the same way."""
    game = _w1g3_game(set_pool, hand=["Petradon"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    game.cast_from_hand(
        0, "Petradon", target_player_index=1, target_permanent_ids=[forest.permanent_id],
    )
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(1)] == ["Forest"]
    assert game.players[1].exile == []
    assert any("needs 2 targets" in line for line in game.log), game.log[-4:]


def test_w1g3_petradon_asked_for_its_targets_takes_exactly_two(set_pool):
    """Put onto the battlefield (nothing announced), a human controller is
    asked: one land is refused, two are the announcement."""
    game = _w1g3_game(set_pool)
    game.interactive_seats = {0}
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    island = _w1g3_put(game, set_pool, 1, "Island")
    permanent = _W1G3Permanent(card=_w1g3_card(set_pool, "Petradon"))
    game._put_permanent_onto_battlefield(0, permanent, None)

    (asked,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert asked.data["max_targets"] == 2 and asked.data.get("exact_targets")
    assert not game.confirm_trigger_target(0, permanent_id=forest.permanent_id)
    assert not game.confirm_trigger_target(0, permanent_ids=[forest.permanent_id])
    assert game.confirm_trigger_target(
        0, permanent_ids=[forest.permanent_id, island.permanent_id]
    )
    game.interactive_seats = set()
    _w1g3_drain(game)

    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Island"]


# --- Hypnox: "if you cast it from your hand" and the whole hand --------------


def test_w1g3_hypnox_cast_from_hand_exiles_the_hand_and_gives_it_back(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Hypnox", "Swords to Plowshares"],
        opp_hand=["Lightning Bolt", "Island", "Grizzly Bears"],
    )
    p1 = game.players[1]
    game.cast_from_hand(0, "Hypnox", target_player_index=1)
    _w1g3_drain(game)

    assert p1.hand == []
    assert sorted(c.name for c in p1.exile) == ["Grizzly Bears", "Island", "Lightning Bolt"]

    hypnox = _w1g3_named(game, 0, "Hypnox")
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[hypnox.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.hand) == ["Grizzly Bears", "Island", "Lightning Bolt"]


def test_w1g3_hypnox_put_onto_the_battlefield_does_not_trigger(set_pool):
    """CR 603.4: a permanent that was never cast was not cast from a hand."""
    game = _w1g3_game(set_pool, opp_hand=["Lightning Bolt", "Island"])
    _w1g3_put(game, set_pool, 0, "Hypnox")

    assert sorted(c.name for c in game.players[1].hand) == ["Island", "Lightning Bolt"]
    assert any("didn't trigger" in line for line in game.log), game.log[-3:]


def test_w1g3_hypnox_killed_in_response_exiles_the_hand_for_good(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Hypnox", "Swords to Plowshares"],
        opp_hand=["Lightning Bolt", "Island"],
    )
    game.queue_from_hand(0, "Hypnox", target_player_index=1)
    game.resolve_top_of_stack()
    hypnox = _w1g3_named(game, 0, "Hypnox")

    _w1g3_swords_in_response(game, hypnox)

    # The condition is still true as the trigger resolves (it *was* cast from
    # a hand), so the hand is exiled — after the leave trigger found nothing.
    assert game.players[1].hand == []
    assert sorted(c.name for c in game.players[1].exile) == ["Island", "Lightning Bolt"]


# --- Mesmeric Fiend: the chosen card, linked --------------------------------


def test_w1g3_mesmeric_fiend_exiles_a_nonland_card_and_returns_it(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Mesmeric Fiend", "Swords to Plowshares"],
        opp_hand=["Island", "Lightning Bolt"],
    )
    game.interactive_seats = {0}
    p1 = game.players[1]
    game.cast_from_hand(0, "Mesmeric Fiend", target_player_index=1)
    game._settle()
    (choice,) = [c for c in game.pending_choices if c.kind == "revealed_hand_pick"]
    # Only the nonland card is offered.
    assert [p1.hand[i].name for i in choice.data["legal_indices"]] == ["Lightning Bolt"]
    assert game.confirm_revealed_hand_pick(0, choice.data["legal_indices"][0])

    assert [c.name for c in p1.exile] == ["Lightning Bolt"]
    fiend = _w1g3_named(game, 0, "Mesmeric Fiend")
    assert [e["card"].name for e in _w1g3_linked_entries(fiend)] == ["Lightning Bolt"]

    game.interactive_seats = set()
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[fiend.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.hand) == ["Island", "Lightning Bolt"]


def test_w1g3_mesmeric_fiend_killed_in_response_exiles_indefinitely(set_pool):
    """The card's ruling (2018-03-16): "its second ability will trigger and do
    nothing. Then its first ability will resolve and exile a nonland card from
    the target opponent's hand indefinitely.\""""
    game = _w1g3_game(
        set_pool, hand=["Mesmeric Fiend", "Swords to Plowshares"],
        opp_hand=["Island", "Lightning Bolt"],
    )
    game.queue_from_hand(0, "Mesmeric Fiend", target_player_index=1)
    game.resolve_top_of_stack()
    fiend = _w1g3_named(game, 0, "Mesmeric Fiend")

    _w1g3_swords_in_response(game, fiend)

    assert [c.name for c in game.players[1].exile] == ["Lightning Bolt"]
    assert [c.name for c in game.players[1].hand] == ["Island"]


# --- Chainer, Dementia Master -------------------------------------------------


def _w1g3_chainer(set_pool, opp_graveyard=("Grizzly Bears",)):
    game = _w1g3_game(set_pool, opp_graveyard=list(opp_graveyard))
    chainer = _w1g3_put(game, set_pool, 0, "Chainer, Dementia Master")
    return game, chainer


def test_w1g3_chainer_reanimates_a_black_nightmare_under_your_control(set_pool):
    game, _chainer = _w1g3_chainer(set_pool)
    life = game.players[0].life
    result = game.activate_permanent_ability(
        0, "Chainer, Dementia Master", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, game.log[-3:]
    _w1g3_drain(game)

    assert game.players[0].life == life - 3, "Pay 3 life"
    bears = _w1g3_named(game, 0, "Grizzly Bears")
    # The ruling (2022-12-08): "black only, not black in addition to its other
    # colors … a Nightmare in addition to its other creature types".
    assert set(_w1g3_object_colors(game, bears)) == {"B"}
    _card_types, subtypes = _w1g3_computed_types(bears)
    assert {"bear", "nightmare"} <= set(subtypes)
    # "All Nightmares get +1/+1." — the Nightmares include the reanimated one.
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    # CR 108.3: still its owner's card.
    assert game.owner_index_of(bears) == 1


def test_w1g3_chainer_leaving_exiles_every_nightmare(set_pool):
    game, chainer = _w1g3_chainer(set_pool)
    game.activate_permanent_ability(
        0, "Chainer, Dementia Master", target_player_index=1, target_permanent_index=0,
    )
    _w1g3_drain(game)
    _w1g3_put(game, set_pool, 1, "Gravegouger")  # a printed Nightmare
    _w1g3_put(game, set_pool, 1, "Grizzly Bears")  # not one

    game.remove_from_battlefield(chainer)
    game._permanent_to_graveyard(game.players[0], chainer)
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(0)] == []
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    # Each to its owner's exile (CR 400.3).
    assert sorted(c.name for c in game.players[1].exile) == ["Gravegouger", "Grizzly Bears"]

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

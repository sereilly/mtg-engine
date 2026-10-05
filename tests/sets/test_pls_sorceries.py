"""Planeshift sorceries.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: non-mana kicker ---
#
# "Kicker—Sacrifice two lands." (Bog Down), "Kicker—Sacrifice a creature."
# (Primal Growth), and Diabolic Intent's mandatory twin of the same cost.
# Imports are in this block, per the header's parallel-authorship convention.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.ai_policy import choose_cast_action as _w1g1_choose_cast_action
from engine.cast_costs import kicker_cost as _w1g1_kicker_cost
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _w1g1_duel(set_pool, hand, *, library=None, their_hand=()):
    """A two-seat game that **charges mana**, seat 0 holding *hand* (PLS names)
    over *library* (LEA names, top first is the last entry's reverse — it is
    only ever searched here)."""
    pls, lea = set_pool("PLS"), set_pool("LEA")
    mine = _W1G1PlayerState(
        "Kicker",
        library=[lea[name] for name in (library or ["Forest"] * 10)],
        hand=[pls[name] for name in hand],
    )
    theirs = _W1G1PlayerState(
        "Bystander", library=[lea["Forest"]] * 10,
        hand=[lea[name] for name in their_hand],
    )
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH)
    return game  # _w1g1_duel (sorceries)


def _w1g1_put(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (sorceries)


def _w1g1_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))  # _w1g1_names (sorceries)


def _w1g1_key(set_pool, name):
    return _w1g1_kicker_cost(set_pool("PLS")[name].oracle_text)  # _w1g1_key (sorceries)


# -- Bog Down ----------------------------------------------------------------


def _w1g1_bog_table(set_pool, swamps=3):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Bog Down"], their_hand=["Grizzly Bears"] * 5)
    lands = [_w1g1_put(game, 0, lea["Swamp"]) for _ in range(swamps)]
    return game, lands  # _w1g1_bog_table


def _w1g1_discard_owed(game) -> int:
    (choice,) = [c for c in game.pending_choices if c.kind == "discard"]
    assert choice.player_index == 1
    return choice.data["count"]  # _w1g1_discard_owed


def test_w1g1_bog_down_unkicked_makes_the_target_discard_two(set_pool):
    game, lands = _w1g1_bog_table(set_pool)
    assert game.cast_from_hand(0, "Bog Down", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert _w1g1_discard_owed(game) == 2
    assert len(_w1g1_names(game, 0)) == 3, "no kicker, no lands"


def test_w1g1_bog_down_kicked_is_three_cards_instead_not_two_then_three(set_pool):
    """"…that player discards three cards **instead**." Kicked, the target owes
    three — one prompt for three, not a prompt for two and another for three —
    and the two lands the caster **named** are the two that go."""
    game, lands = _w1g1_bog_table(set_pool)
    key = _w1g1_key(set_pool, "Bog Down")
    assert key == "sacrifice two lands"

    result = game.cast_from_hand(
        0, "Bog Down", target_player_index=1, optional_cost_payments={key: 1},
        cost_permanent_ids=[lands[0].permanent_id, lands[2].permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    assert _w1g1_discard_owed(game) == 3
    assert [p.permanent_id for p in game.controlled_by(0)] == [lands[1].permanent_id]

    assert game.confirm_discard(1, [0, 1, 2])
    assert len(game.players[1].hand) == 2 and len(game.players[1].graveyard) == 3


def test_w1g1_bog_down_cannot_be_kicked_with_one_land(set_pool):
    """One land is no more a payment of "sacrifice two lands" than none
    (CR 601.2h): refused with the land kept and the mana unspent, and the
    browser's offer says so from the same gate."""
    game, lands = _w1g1_bog_table(set_pool, swamps=1)
    key = _w1g1_key(set_pool, "Bog Down")
    [offer] = game.cast_cost_offers(0, set_pool("PLS")["Bog Down"])
    assert (offer["label"], offer["max_times"]) == ("kicker", 0)

    refused = game.cast_from_hand(
        0, "Bog Down", target_player_index=1, optional_cost_payments={key: 1}
    )
    assert not refused.supported and "601.2h" in refused.details
    assert game.is_on_battlefield(lands[0])
    assert sum(game.players[0].mana_pool.values()) == sum(_W1G1_RICH.values())


def test_w1g1_the_kicked_bog_down_asks_for_two_lands_and_the_plain_one_for_none(set_pool):
    game, lands = _w1g1_bog_table(set_pool)
    card = set_pool("PLS")["Bog Down"]
    key = _w1g1_key(set_pool, "Bog Down")
    assert "cost_spec" not in game.cast_target_spec(0, card, optional_cost_payments={})
    kicked = game.cast_target_spec(0, card, optional_cost_payments={key: 1})
    cost = kicked["cost_spec"]
    assert (cost["kind"], cost["sacrifice_cost"], cost["count"]) == ("land", True, 2)
    assert len(cost["valid_targets"]) == 3
    assert kicked["kind"] == "player", "the target is still a player either way"


# -- Primal Growth -----------------------------------------------------------

#: Two basics, a nonbasic land and two non-lands: what "a basic land card" may
#: and may not find.
_W1G1_GROWTH_LIBRARY = ["Forest", "Grizzly Bears", "Island", "Sol Ring", "Bayou"]


def test_w1g1_primal_growth_unkicked_fetches_one_basic_land(set_pool):
    game = _w1g1_duel(set_pool, ["Primal Growth"], library=_W1G1_GROWTH_LIBRARY)
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    assert game.cast_from_hand(0, "Primal Growth").supported
    _w1g1_resolve_stack(game)

    prompt = game.pending_search_library
    assert prompt["count"] == 1 and not prompt["up_to"]
    assert not game.confirm_search_library(0, 4), "Bayou is a land, and not basic"
    assert game.confirm_search_library(0, 2)
    game._settle()
    assert _w1g1_names(game, 0) == ["Grizzly Bears", "Island"]
    assert game.is_on_battlefield(bears), "no kicker, no sacrifice"
    assert game.pending_search_library is None


def test_w1g1_primal_growth_kicked_fetches_up_to_two_instead(set_pool):
    """"If this spell was kicked, **instead** search your library for up to two
    basic land cards…" The fronted spelling of the "instead" pair: one search
    for up to two, in place of the search for one — and the creature the
    caster named is the price."""
    game = _w1g1_duel(set_pool, ["Primal Growth"], library=_W1G1_GROWTH_LIBRARY)
    lea = set_pool("LEA")
    kept = _w1g1_put(game, 0, lea["Hill Giant"])
    named = _w1g1_put(game, 0, lea["Grizzly Bears"])
    key = _w1g1_key(set_pool, "Primal Growth")
    assert key == "sacrifice a creature"

    result = game.cast_from_hand(
        0, "Primal Growth", optional_cost_payments={key: 1},
        cost_permanent_ids=[named.permanent_id],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(named) and game.is_on_battlefield(kept)
    _w1g1_resolve_stack(game)

    prompt = game.pending_search_library
    assert prompt["count"] == 2 and prompt["up_to"]
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 0}, {"zone": "library", "index": 2}]
    )
    game._settle()
    assert _w1g1_names(game, 0) == ["Forest", "Hill Giant", "Island"]
    assert game.pending_search_library is None, "one search, not one and then two"
    assert sorted(c.name for c in game.players[0].library) == [
        "Bayou", "Grizzly Bears", "Sol Ring",
    ]


def test_w1g1_primal_growth_cannot_be_kicked_without_a_creature(set_pool):
    game = _w1g1_duel(set_pool, ["Primal Growth"], library=_W1G1_GROWTH_LIBRARY)
    key = _w1g1_key(set_pool, "Primal Growth")
    refused = game.cast_from_hand(0, "Primal Growth", optional_cost_payments={key: 1})
    assert not refused.supported and "601.2h" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Primal Growth"]

    # …and a kicked cast with one raises a sacrifice picker over the caster's
    # own creatures, which the plain cast does not.
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    _w1g1_put(game, 1, set_pool("LEA")["Hill Giant"])
    card = set_pool("PLS")["Primal Growth"]
    assert game.cast_target_spec(0, card, optional_cost_payments={})["kind"] == "none"
    kicked = game.cast_target_spec(0, card, optional_cost_payments={key: 1})
    assert kicked["sacrifice_cost"] and kicked["kind"] == "creature"
    assert [
        game.permanent_at(t["seat"], t["index"]).permanent_id
        for t in kicked["valid_targets"]
    ] == [bears.permanent_id]


# -- Diabolic Intent ---------------------------------------------------------


def test_w1g1_diabolic_intent_sacrifices_a_creature_and_tutors(set_pool):
    """"As an additional cost to cast this spell, sacrifice a creature." The
    mandatory twin of the kicker's cost: paid as the spell is cast, then a
    search for any card into hand."""
    game = _w1g1_duel(
        set_pool, ["Diabolic Intent"], library=["Forest", "Black Lotus", "Island"]
    )
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    before = sum(game.players[0].mana_pool.values())

    result = game.queue_from_hand(
        0, "Diabolic Intent", cost_permanent_ids=[bears.permanent_id]
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(bears), "paid on the way to the stack"
    assert before - sum(game.players[0].mana_pool.values()) == 2
    _w1g1_resolve_stack(game)

    assert game.confirm_search_library(0, 1)
    game._settle()
    assert [c.name for c in game.players[0].hand] == ["Black Lotus"]


def test_w1g1_diabolic_intent_is_refused_unpaid_with_no_creature(set_pool):
    """CR 601.2h: no creature, no cast — the mana stays, the card stays, and
    the AI does not propose it."""
    game = _w1g1_duel(set_pool, ["Diabolic Intent"])
    refused = game.cast_from_hand(0, "Diabolic Intent")
    assert not refused.supported and "601.2h" in refused.details
    assert sum(game.players[0].mana_pool.values()) == sum(_W1G1_RICH.values())
    assert [c.name for c in game.players[0].hand] == ["Diabolic Intent"]
    assert _w1g1_choose_cast_action(game, 0) is None


def test_w1g1_diabolic_intent_resolves_when_its_payer_was_also_named_as_a_target(set_pool):
    """A spell with no target is not countered for an illegal one. Diabolic
    Intent's whole spec is its cost picker, so an id on the *target* channel
    names nothing the spell targets — but CR 608.2b's gate judged it as a
    target, found the sacrificed creature gone, and removed the spell with its
    cost paid. That is how the AI announced it, in a simulated game."""
    game = _w1g1_duel(
        set_pool, ["Diabolic Intent"], library=["Forest", "Black Lotus", "Island"]
    )
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    result = game.cast_from_hand(
        0, "Diabolic Intent", target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    assert not any("every target is illegal" in line for line in game.log)
    assert game.pending_search_library is not None, "it resolved: the search is owed"


def test_w1g1_the_ai_casts_diabolic_intent_without_naming_its_payer_a_target(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Diabolic Intent"])
    game.players[0].mana_pool.clear()
    for _ in range(2):
        _w1g1_put(game, 0, lea["Swamp"])
    _w1g1_put(game, 0, lea["Grizzly Bears"])
    game.active_player_index = 0
    game.current_phase = "main"

    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Diabolic Intent"
    assert not action.target_permanent_ids

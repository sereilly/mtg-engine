"""When a seat nobody asks taps its lands for a mana-priced "you may pay".

``_default_optional_pay``'s mana half read "never tap a land", and the offers
it answers arrive where the pool is empty — an upkeep, a combat damage step,
the opponent's turn. So the AI declined every mana-priced offer it was made:
Vaporous Djinn's "phases out unless you pay {U}{U}" phased it out with two
Islands untapped, and Rootwater Thief never paid its {2}.
``ai_policy.optional_pay_may_tap_lands`` is the weight now: a toll is paid
from the board whenever it can be, a gift only with mana nothing else this
turn would spend. The payment itself was always the plan ``_pay_optional``
spends, lands included.
"""
from __future__ import annotations

from engine.ai_combat import run_ai_combat_phase
from engine.ai_policy import optional_pay_may_tap_lands
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack


def _duel(set_pool, mine, *, hand=(), opp_library=None):
    lea = set_pool("LEA")
    me = PlayerState(
        name="AI", hand=list(hand), library=[lea["Island"]] * 10,
        battlefield=[_nosick(Permanent(card=card)) for card in mine],
    )
    them = PlayerState(name="Opp", library=list(opp_library or [lea["Island"]] * 10))
    game = Game(players=[me, them])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game._sync_control()
    return game


def test_an_upkeep_toll_is_paid_by_tapping_lands(set_pool):
    lea = set_pool("LEA")
    djinn = set_pool("MIR")["Vaporous Djinn"]
    game = _duel(set_pool, [djinn, lea["Island"], lea["Island"]])

    game.start_turn(0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    board = list(game.controlled_by(0))
    assert any(p.card.name == "Vaporous Djinn" for p in board), "it did not phase out"
    assert all(p.tapped for p in board if p.card.name == "Island"), "{U}{U} came from the Islands"


def test_a_toll_the_lands_cannot_cover_is_still_declined(set_pool):
    lea = set_pool("LEA")
    djinn = set_pool("MIR")["Vaporous Djinn"]
    game = _duel(set_pool, [djinn, lea["Island"], lea["Forest"]])

    game.start_turn(0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert not any(p.card.name == "Vaporous Djinn" for p in game.controlled_by(0))
    assert not any(p.tapped for p in game.controlled_by(0)), "nothing was spent on a half payment"


def _connect_with_rootwater_thief(set_pool, hand):
    lea = set_pool("LEA")
    thief = set_pool("NEM")["Rootwater Thief"]
    game = _duel(
        set_pool, [thief, lea["Island"], lea["Island"]], hand=hand,
        opp_library=[lea["Black Lotus"]] + [lea["Island"]] * 5,
    )
    game.start_turn(0)
    run_ai_combat_phase(game, 0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game


def test_a_gift_is_paid_with_lands_nothing_else_would_spend(set_pool):
    """Rootwater Thief connects; the seat's hand holds nothing it could cast,
    so the two Islands would sit untapped until next turn."""
    game = _connect_with_rootwater_thief(set_pool, hand=())
    assert [card.name for card in game.players[1].exile] == ["Black Lotus"]
    assert all(p.tapped for p in game.controlled_by(0) if p.card.name == "Island")


def test_a_gift_on_the_seats_own_turn_keeps_mana_a_spell_could_use(set_pool):
    """The same connection holding a spell those Islands could cast: the gift
    waits for idle mana, because the lands are what the seat casts with."""
    merfolk = set_pool("LEA")["Merfolk of the Pearl Trident"]
    game = _connect_with_rootwater_thief(set_pool, hand=(merfolk,))
    assert game.players[1].exile == []
    assert not any(p.tapped for p in game.controlled_by(0) if p.card.name == "Island")


def test_the_weight_reads_toll_turn_and_offerer_not_card(set_pool):
    """The answers the weight gives, asked directly: any toll; a gift the
    seat's own object offers, on another seat's turn; never a gift another
    seat's spell offers it (Chain Lightning's copy, whose default keeps the
    payer's own creature as the target)."""
    from types import SimpleNamespace

    game = _duel(set_pool, [])
    own = SimpleNamespace(caster=game.players[0])
    theirs = SimpleNamespace(caster=game.players[1])
    game.active_player_index = 1
    assert optional_pay_may_tap_lands(game, 0, {"cost": {"generic": 1}, "_context": own})
    assert not optional_pay_may_tap_lands(
        game, 0, {"cost": {"R": 2}, "_context": theirs}
    )
    game.active_player_index = 0
    assert optional_pay_may_tap_lands(
        game, 0,
        {"cost": {"generic": 1}, "_on_decline": ("penalty",), "_context": theirs},
    )


def test_fade_aways_toll_is_paid_from_an_untapped_land(set_pool):
    """"For each creature, its controller sacrifices a permanent of their
    choice unless they pay {1}." A toll: the seat with an untapped Mountain
    pays it, and keeps the Hill Giant."""
    lea = set_pool("LEA")
    alice = PlayerState(name="Alice", hand=[set_pool("EXO")["Fade Away"]])
    bob = PlayerState(
        name="Bob",
        battlefield=[_nosick(Permanent(card=lea["Hill Giant"])), Permanent(card=lea["Mountain"])],
    )
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set()
    game._sync_control()

    assert game.cast_from_hand(0, "Fade Away").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.controlled_by(bob)] == ["Hill Giant", "Mountain"]
    assert all(p.tapped for p in game.controlled_by(bob) if p.card.name == "Mountain")

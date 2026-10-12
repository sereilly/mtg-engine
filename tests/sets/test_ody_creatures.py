"""Odyssey creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
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

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack

_W1G2_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9, "C": 9}

#: The six creatures whose last ability is "Threshold — <cost>: <effect>.
#: Activate only if there are seven or more cards in your graveyard.", with
#: the mana that ability's cost spends.
_W1G2_THRESHOLD_CREATURES = [
    ("Cabal Inquisitor", 2),
    ("Chainflinger", 3),
    ("Hallowed Healer", 0),
    ("Infected Vermin", 4),
    ("Krosan Avenger", 2),
    ("Nomad Decoy", 2),
]


def _w1g2_duel(set_pool, *, graveyard=0, opponent_hand=0):
    """A two-seat game that **charges mana**, seat 0's main phase, with
    *graveyard* cards in seat 0's graveyard. Costs are enforced because the
    refusal these tests are about is "nothing was paid": a rig that waives
    mana cannot tell a refused activation from a free one."""
    lea = set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState("Caster", library=[lea["Forest"]] * 10),
        _w1g2_PlayerState(
            "Bystander", library=[lea["Forest"]] * 10,
            hand=[lea["Island"]] * opponent_hand,
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G2_RICH)
    game.players[0].graveyard.extend([lea["Grizzly Bears"]] * graveyard)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game  # _w1g2_duel


def _w1g2_put(game, seat, card):
    """*card* onto *seat*'s battlefield without being cast, untapped and
    ready to act."""
    permanent = _w1g2_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put


def _w1g2_floating(game, seat=0) -> int:
    return sum(game.players[seat].mana_pool.values())  # _w1g2_floating


def _w1g2_threshold_index(card) -> int:
    """Which of *card*'s activated abilities prints the threshold clause."""
    abilities = _w1g2_compile(card).activated_abilities
    (index,) = [
        position for position, ability in enumerate(abilities)
        if "seven or more cards in your graveyard" in ability.source_line
    ]
    return index  # _w1g2_threshold_index


def _w1g2_aim(name, bears):
    """The announcement each threshold creature's ability needs."""
    if name in ("Chainflinger", "Cabal Inquisitor"):
        return {"target_player_index": 1}
    if name == "Hallowed Healer":
        return {"target_player_index": 0}
    if name == "Nomad Decoy":
        return {"target_permanent_ids": [bear.permanent_id for bear in bears]}
    return {}  # _w1g2_aim


@_w1g2_pytest.mark.parametrize("name, price", _W1G2_THRESHOLD_CREATURES)
def test_a_threshold_ability_is_refused_at_six_cards_and_nothing_is_paid(
    set_pool, name, price,
):
    """"Activate only if there are seven or more cards in your graveyard."
    With six the activation is refused before it begins (CR 602.5): no mana
    leaves the pool, the creature is not tapped, no card is exiled, and nothing
    reaches the stack. With seven the same announcement is accepted and its
    printed mana is spent."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    card = ody[name]
    assert _w1g2_compile(card).supported
    index = _w1g2_threshold_index(card)

    for graveyard, allowed in ((6, False), (7, True)):
        game = _w1g2_duel(set_pool, graveyard=graveyard, opponent_hand=2)
        source = _w1g2_put(game, 0, card)
        bears = [_w1g2_put(game, 1, lea["Grizzly Bears"]) for _ in range(2)]
        before = _w1g2_floating(game)

        result = game.queue_permanent_ability(
            0, name, ability_index=index, **_w1g2_aim(name, bears),
        )

        assert result.supported is allowed, (graveyard, result.details)
        if allowed:
            assert before - _w1g2_floating(game) == price
            assert len(game.stack) == 1
            continue
        assert "seven or more cards in your graveyard" in result.details
        assert _w1g2_floating(game) == before
        assert not source.tapped and game.stack == []
        assert len(game.players[0].graveyard) == 6
        assert game.players[0].exile == []


def test_chainflinger_pings_for_one_and_for_two_only_at_threshold(set_pool):
    """"{1}{R}, {T}: This creature deals 1 damage to any target." has no
    clause and works with an empty graveyard; the threshold ability deals 2."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, graveyard=0)
    _w1g2_put(game, 0, ody["Chainflinger"])
    assert game.activate_permanent_ability(
        0, "Chainflinger", ability_index=0, target_player_index=1,
    ).supported
    assert game.players[1].life == 19

    game = _w1g2_duel(set_pool, graveyard=7)
    _w1g2_put(game, 0, ody["Chainflinger"])
    assert game.activate_permanent_ability(
        0, "Chainflinger", ability_index=1, target_player_index=1,
    ).supported
    assert game.players[1].life == 18


def test_threshold_is_asked_as_the_ability_is_activated_not_as_it_resolves(set_pool):
    """A restriction gates *beginning* to activate (CR 602.5). Once
    Chainflinger's threshold ability is on the stack, a graveyard emptied in
    response does not take it back — and neither does the creature leaving
    (CR 113.7a: an ability on the stack is independent of its source)."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, graveyard=7)
    flinger = _w1g2_put(game, 0, ody["Chainflinger"])
    assert game.queue_permanent_ability(
        0, "Chainflinger", ability_index=1, target_player_index=1,
    ).supported

    game.players[0].graveyard.clear()
    game.remove_from_battlefield(flinger)
    _w1g2_resolve_stack(game)

    assert game.players[1].life == 18


def test_hallowed_healer_prevents_two_and_four_at_threshold(set_pool):
    """"{T}: Prevent the next 2 damage that would be dealt to any target this
    turn." / "Threshold — {T}: Prevent the next 4 damage …". Five damage dealt
    through each shield: three gets past the first, one past the second."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    for graveyard, ability, lost in ((0, 0, 3), (7, 1, 1)):
        game = _w1g2_duel(set_pool, graveyard=graveyard)
        _w1g2_put(game, 0, ody["Hallowed Healer"])
        assert game.activate_permanent_ability(
            0, "Hallowed Healer", ability_index=ability, target_player_index=0,
        ).supported
        game._deal_damage_to_player(game.players[0], 5, source=lea["Lightning Bolt"])
        assert game.players[0].life == 20 - lost, (graveyard, ability)


def test_hallowed_healers_threshold_shield_can_cover_a_creature(set_pool):
    """"…to **any target**": the shield is as happy on a creature as on a
    face, and the picker offers both."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=7)
    healer = _w1g2_put(game, 0, ody["Hallowed Healer"])
    wurm = _w1g2_put(game, 0, lea["Craw Wurm"])
    spec = game.activation_target_spec(
        0, game.battlefield_index_of(healer), ability_index=1,
    )
    assert spec["kind"] == "any" and spec["requires_target"]
    assert game.activate_permanent_ability(
        0, "Hallowed Healer", ability_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    game._mark_damage_on_permanent(wurm, 7, source=lea["Lightning Bolt"])
    game._settle()
    assert game.is_on_battlefield(wurm), "7 less 4 prevented is not lethal to a 6/4"


def test_infected_vermin_sweeps_for_one_and_for_three_at_threshold(set_pool):
    """"{2}{B}: This creature deals 1 damage to each creature and each
    player." / "Threshold — {3}{B}: … 3 damage …". The Vermin is a creature
    too, so either one kills it; the big one takes the Bears with it."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=0)
    vermin = _w1g2_put(game, 0, ody["Infected Vermin"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.activate_permanent_ability(0, "Infected Vermin", ability_index=0).supported
    assert [p.life for p in game.players] == [19, 19]
    assert not game.is_on_battlefield(vermin), "a 1/1 dealt 1"
    assert game.is_on_battlefield(bears)

    game = _w1g2_duel(set_pool, graveyard=7)
    vermin = _w1g2_put(game, 0, ody["Infected Vermin"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    wurm = _w1g2_put(game, 1, lea["Craw Wurm"])
    assert game.activate_permanent_ability(0, "Infected Vermin", ability_index=1).supported
    assert [p.life for p in game.players] == [17, 17]
    assert not game.is_on_battlefield(vermin) and not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(wurm), "a 6/4 survives 3"


def test_krosan_avenger_regenerates_only_at_threshold(set_pool):
    """"Threshold — {1}{G}: Regenerate this creature." The shield it buys
    replaces the next destruction: lethal damage leaves it tapped and alive."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=7)
    avenger = _w1g2_put(game, 0, ody["Krosan Avenger"])
    assert game._has_keyword(avenger, "trample")
    assert game.activate_permanent_ability(0, "Krosan Avenger").supported

    game._mark_damage_on_permanent(avenger, 3, source=lea["Lightning Bolt"])
    game._settle()

    assert game.is_on_battlefield(avenger) and avenger.tapped


def test_nomad_decoy_taps_one_and_exactly_two_at_threshold(set_pool):
    """"{W}, {T}: Tap target creature." / "Threshold — {W}{W}, {T}: Tap **two**
    target creatures." A printed count is a count (CR 601.2c): the threshold
    ability named at one creature is refused with nothing paid."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=7)
    decoy = _w1g2_put(game, 0, ody["Nomad Decoy"])
    first, second = (_w1g2_put(game, 1, lea["Grizzly Bears"]) for _ in range(2))
    before = _w1g2_floating(game)

    short = game.queue_permanent_ability(
        0, "Nomad Decoy", ability_index=1, target_permanent_ids=[first.permanent_id],
    )
    assert not short.supported, short.details
    assert _w1g2_floating(game) == before and not decoy.tapped

    assert game.activate_permanent_ability(
        0, "Nomad Decoy", ability_index=1,
        target_permanent_ids=[first.permanent_id, second.permanent_id],
    ).supported
    assert first.tapped and second.tapped and decoy.tapped
    assert before - _w1g2_floating(game) == 2

    game = _w1g2_duel(set_pool, graveyard=0)
    _w1g2_put(game, 0, ody["Nomad Decoy"])
    lone = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.activate_permanent_ability(
        0, "Nomad Decoy", ability_index=0, target_permanent_ids=[lone.permanent_id],
    ).supported
    assert lone.tapped


def test_cabal_inquisitor_may_pay_its_way_below_threshold(set_pool):
    """"Threshold — {1}{B}, {T}, Exile two cards from your graveyard: Target
    player discards a card." With exactly seven cards the clause holds when the
    activation begins; the cost then exiles two of them, and the ability still
    resolves with five in the graveyard — nothing re-asks the clause."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, graveyard=7, opponent_hand=2)
    inquisitor = _w1g2_put(game, 0, ody["Cabal Inquisitor"])

    assert game.queue_permanent_ability(
        0, "Cabal Inquisitor", target_player_index=1,
    ).supported
    assert len(game.players[0].graveyard) == 5 and len(game.players[0].exile) == 2
    assert inquisitor.tapped

    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 1


def test_cabal_inquisitor_is_sorcery_speed_as_well_as_threshold(set_pool):
    """"Activate only as a sorcery **and only if** there are seven or more
    cards in your graveyard." Two restrictions in one sentence, both required:
    with seven cards it is still refused on the opponent's turn and with
    something on the stack, and nothing is exiled for either refusal."""
    ody, lea = set_pool("ODY"), set_pool("LEA")

    game = _w1g2_duel(set_pool, graveyard=7, opponent_hand=2)
    _w1g2_put(game, 0, ody["Cabal Inquisitor"])
    game.active_player_index = 1
    theirs = game.queue_permanent_ability(0, "Cabal Inquisitor", target_player_index=1)
    assert not theirs.supported and "sorcery" in theirs.details
    assert len(game.players[0].graveyard) == 7

    game = _w1g2_duel(set_pool, graveyard=7, opponent_hand=2)
    _w1g2_put(game, 0, ody["Cabal Inquisitor"])
    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    stacked = game.queue_permanent_ability(0, "Cabal Inquisitor", target_player_index=1)
    assert not stacked.supported and "sorcery" in stacked.details
    assert len(game.players[0].graveyard) == 7 and game.players[0].exile == []

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

# ==== end W1G9 ======================================================

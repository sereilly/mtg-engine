"""Regression: a division is announced only by a spell that divides (CR 601.2d).

"If the spell requires the player to **divide or distribute** an effect (such
as damage or counters) among one or more targets, the player announces the
division." The cast path's division gate ran only for a spell that *has* a
divided step, so a ``divided_targets`` list on any other spell was looked at
by nobody on the way in — while every damage handler reads
``choices["divided_targets"]`` whenever it is present. So::

    game.cast_from_hand(0, "Lightning Bolt", divided_targets=[(1, None), (0, None)])

split one target's 3 damage between two faces and left both players at 19.
Neither the client nor the AI sends such a list, so this is the engine's
announcement API being laxer than the rule rather than a defect a player could
reach — and exactly the kind nothing measures, because no compiled program
moves and every card involved is "supported".

Census: of 942 instants and sorceries in both manifest roles whose announced
steps divide nothing, 496 accepted a two-face division before the gate. 44 of
them then damaged both faces; 16 of those are sweeps that do so however they
are announced (Earthquake, Hurricane), and **28** split their one amount
because of the list — which is the number that says what the laxity cost. The
21 spells that do divide still accept the AI's own lawful division.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_policy import choose_divided_targets
from engine.card_loader import load_cards, manifest_set_paths
from engine.divided_damage import divided_instruction
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, instructions_as_announced
from tests.helpers import _mk_card, resolve_stack


def _w2g2_division_pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


_POOL = _w2g2_division_pool()


def _w2g2_division_table(card, *, creatures: bool = False) -> Game:
    forest = _POOL["Forest"]

    def side() -> list:
        if not creatures:
            return []
        return [
            Permanent(card=_mk_card(
                name=f"Bait {n}", type_line="Creature - Beast", colors=("G",),
                power=2, toughness=6,
            ))
            for n in range(3)
        ]

    game = Game(players=[
        PlayerState("Me", library=[forest] * 10, hand=[card], battlefield=side()),
        PlayerState("Opp", library=[forest] * 10, battlefield=side()),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _w2g2_x(card):
    return 4 if "{X}" in (card.mana_cost or "") else None


def test_w2g2_lightning_bolt_does_not_take_a_division():
    bolt = _POOL["Lightning Bolt"]
    game = _w2g2_division_table(bolt)

    split = game.cast_from_hand(0, bolt.name, divided_targets=[(1, None), (0, None)])

    assert not split.supported, "a one-target spell accepted a two-face division"
    assert "601.2d" in split.details
    assert [player.life for player in game.players] == [20, 20]
    assert [card.name for card in game.players[0].hand] == [bolt.name]

    plain = game.cast_from_hand(0, bolt.name, target_player_index=1)
    assert plain.supported, plain.details
    assert [player.life for player in game.players] == [20, 17], game.log


def test_w2g2_an_empty_division_is_no_division():
    """``divided_targets=[]`` is what a caller with nothing to divide sends,
    and it must stay a plain cast."""
    bolt = _POOL["Lightning Bolt"]
    game = _w2g2_division_table(bolt)

    plain = game.cast_from_hand(0, bolt.name, target_player_index=1, divided_targets=[])

    assert plain.supported, plain.details
    assert game.players[1].life == 17


def test_w2g2_a_division_printed_in_one_arm_belongs_to_that_cast_alone():
    """CR 702.33g: Magma Burst divides only when kicked ("…it deals 3 damage
    to another target"). The gate reads the steps the *announcement* will run,
    so the unkicked cast takes no division and the kicked one still does."""
    burst = _POOL["Magma Burst"]
    program = compile_card_oracle(burst)
    assert divided_instruction(instructions_as_announced(burst, program, {})) is None
    game = _w2g2_division_table(burst)

    unkicked = game.cast_from_hand(0, burst.name, divided_targets=[(1, None), (0, None)])

    assert not unkicked.supported, "an unkicked Magma Burst accepted a division"
    assert [player.life for player in game.players] == [20, 20]


def _divides(card) -> bool:
    """Whether the cast the census makes — every optional cost declined —
    divides anything, read through the view the cast gate itself reads."""
    program = compile_card_oracle(card)
    return divided_instruction(instructions_as_announced(card, program, {})) is not None


_SPELLS = [
    name for name, card in sorted(_POOL.items())
    if card.face_of is None
    and card.primary_type in ("instant", "sorcery")
    and compile_card_oracle(card).supported
    and not compile_card_oracle(card).modes
]
_DIVIDING = [name for name in _SPELLS if _divides(_POOL[name])]
_PLAIN = [name for name in _SPELLS if not _divides(_POOL[name])]


def test_w2g2_the_division_census_examines_what_it_claims_to():
    assert len(_PLAIN) >= 900, len(_PLAIN)
    assert len(_DIVIDING) >= 20, len(_DIVIDING)
    assert "Lightning Bolt" in _PLAIN and "Fireball" in _DIVIDING


def test_w2g2_the_picker_and_the_gate_agree_on_which_spells_divide():
    """A spell the picker calls divided is one the gate finds a division in,
    and the other way round — or the browser would offer a division prompt the
    gate now refuses."""
    wrong = []
    for name in _SPELLS:
        card = _POOL[name]
        spec = derive_cast_spec(
            card, compile_card_oracle(card), optional_cost_payments={}
        ) or {}
        says = spec.get("kind") == "divided" or bool(spec.get("division"))
        if says != (name in _DIVIDING):
            wrong.append(f"{name}: picker {spec.get('kind')}/{spec.get('division')}")
    assert not wrong, wrong


def test_w2g2_no_spell_that_divides_nothing_takes_a_division():
    """The whole pool, one cast each. A refused cast changes nothing, so the
    life totals are the second half of the assertion."""
    accepted = []
    for name in _PLAIN:
        card = _POOL[name]
        game = _w2g2_division_table(card)
        try:
            result = game.queue_from_hand(
                0, card.name, divided_targets=[(1, None), (0, None)], x_value=_w2g2_x(card),
            )
        except Exception as exc:  # pragma: no cover - a crash is a finding
            accepted.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        if result.supported:
            accepted.append(name)
    assert not accepted, (
        f"{len(accepted)} of {len(_PLAIN)} spells that divide nothing accepted "
        f"a division: {accepted[:20]}"
    )


def test_w2g2_a_spell_that_divides_still_takes_its_division():
    """The gate must not have closed the door it guards: a divided spell is
    still castable with the division the AI's own chooser announces. The
    policy finds no lawful division for some of them on this plain board (a
    division among lands, among attackers), so the count examined is asserted
    rather than assumed."""
    examined, refused = 0, []
    for name in _DIVIDING:
        card = _POOL[name]
        game = _w2g2_division_table(card, creatures=True)
        chosen = choose_divided_targets(game, 0, card, _w2g2_x(card))
        if not chosen:
            continue
        examined += 1
        result = game.cast_from_hand(
            0, card.name, divided_targets=list(chosen), x_value=_w2g2_x(card),
        )
        if not result.supported:
            refused.append(f"{name}: {result.details}")
            continue
        resolve_stack(game)

    assert not refused, refused
    assert examined >= 12, examined

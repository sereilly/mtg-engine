"""Regression: an exact target count is a count (CR 601.2c).

"The player announces their choice of an appropriate object or player for
**each** target the spell requires." A printed "two target creatures" requires
two; "up to two" and "any number of" make fewer legal. The grammar has told
the two apart since it parsed them (``quantifier: "exactly"``) and the spec
carries it to the picker (``exact_targets``), where the browser's confirm has
always waited for the printed number — but the engine's own gate treated every
count as a ceiling. ``legality.cast_target_refusal`` said so in its docstring:
"there is no ``min_targets`` in this engine".

So an announcement that fell short was a legal cast that did less:

* "Return **two** target creatures to their owners' hands" (Undo) naming one
  bounced one — and with a single creature on the table, was castable at all;
* "Tap **X** target artifacts, creatures, and/or lands. You lose X life."
  (Malicious Advice) at X=3 naming two tapped two and charged three, and at
  X=2 naming nobody tapped nothing and charged two;
* named **by id**, one more than the count was accepted too — the ceiling read
  the index list alone.

The census below is the ratchet: every instant and sorcery in both manifest
roles whose target slot prints an exact count. Before the fix: 19 of 19
printed counts accepted one target short and 19 of 19 naming none, 15 accepted
with fewer legal targets than the count in existence, 15 one over; 17 of 18
"X target" spells accepted two targets at X=3 and 18 of 18 none at X=2.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_cast_action, tap_planned_lands
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.legality import exact_target_count
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import cast_target_slot
from tests.helpers import _mk_card


def _w2g2_count_pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


_POOL = _w2g2_count_pool()


def _w2g2_count_perm(card) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w2g2_bear(name: str) -> Permanent:
    return _w2g2_count_perm(
        _mk_card(name=name, type_line="Creature - Bear", colors=("G",), power=2, toughness=2)
    )


def _w2g2_count_table(spell, *, mine=(), theirs=()) -> Game:
    forest = _POOL["Forest"]
    game = Game(players=[
        PlayerState(name="P0", hand=[spell], library=[forest] * 10, battlefield=list(mine)),
        PlayerState(name="P1", library=[forest] * 10, battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


# ---------------------------------------------------------------------------
# The two shapes, one card each
# ---------------------------------------------------------------------------


def test_w2g2_undo_names_two_creatures_or_is_not_cast():
    undo = _POOL["Undo"]
    one, two, three = _w2g2_bear("One"), _w2g2_bear("Two"), _w2g2_bear("Three")
    game = _w2g2_count_table(undo, theirs=[one, two, three])

    short = game.cast_from_hand(0, undo.name, target_permanent_ids=[one.permanent_id])
    assert not short.supported, "one creature named for 'two target creatures'"
    bare = game.cast_from_hand(0, undo.name)
    assert not bare.supported, "nobody named for 'two target creatures'"
    over = game.cast_from_hand(
        0, undo.name,
        target_permanent_ids=[one.permanent_id, two.permanent_id, three.permanent_id],
    )
    assert not over.supported, "three creatures named for 'two target creatures'"
    assert [c.name for c in game.players[0].hand] == [undo.name]
    assert all(game.is_on_battlefield(p) for p in (one, two, three))

    cast = game.cast_from_hand(
        0, undo.name, target_permanent_ids=[one.permanent_id, two.permanent_id]
    )
    assert cast.supported, cast.details
    assert not game.is_on_battlefield(one) and not game.is_on_battlefield(two), game.log
    assert game.is_on_battlefield(three)


def test_w2g2_a_printed_count_needs_that_many_legal_targets_to_exist():
    """With one creature on the table "two target creatures" has no legal
    announcement, so the spell cannot be cast (CR 601.2c) — and the castable
    highlight and the AI ask this same predicate."""
    undo = _POOL["Undo"]
    lonely = _w2g2_bear("Lonely")
    game = _w2g2_count_table(undo, theirs=[lonely])

    refusal = game.no_legal_cast_target_refusal(0, undo)
    assert refusal is not None and "2" in refusal, refusal
    assert not game.cast_from_hand(
        0, undo.name, target_permanent_ids=[lonely.permanent_id]
    ).supported
    assert game.is_on_battlefield(lonely)
    assert choose_cast_action(game, 0) is None, "the AI proposed a cast the gate refuses"


def test_w2g2_malicious_advice_taps_x_targets_for_x_life():
    advice = _POOL["Malicious Advice"]
    bears = [_w2g2_bear(f"Bear {n}") for n in range(4)]
    game = _w2g2_count_table(advice, theirs=bears)
    ids = [bear.permanent_id for bear in bears]

    short = game.cast_from_hand(0, advice.name, x_value=3, target_permanent_ids=ids[:2])
    assert not short.supported, "X=3 naming two targets"
    bare = game.cast_from_hand(0, advice.name, x_value=2)
    assert not bare.supported, "X=2 naming no target"
    over = game.cast_from_hand(0, advice.name, x_value=2, target_permanent_ids=ids[:3])
    assert not over.supported, "X=2 naming three targets"
    assert game.players[0].life == 20, "a refused cast charged life"
    assert not any(bear.tapped for bear in bears)

    cast = game.cast_from_hand(0, advice.name, x_value=3, target_permanent_ids=ids[:3])
    assert cast.supported, cast.details
    assert [bear.tapped for bear in bears] == [True, True, True, False], game.log
    assert game.players[0].life == 17, game.log


def test_w2g2_an_x_of_zero_names_nobody():
    """X may be zero, and then there is nothing to target (CR 601.2b before
    601.2c): the count gate must not turn that into a refusal."""
    advice = _POOL["Malicious Advice"]
    game = _w2g2_count_table(advice, theirs=[_w2g2_bear("Bear")])

    cast = game.cast_from_hand(0, advice.name, x_value=0)

    assert cast.supported, cast.details
    assert game.players[0].life == 20


def test_w2g2_up_to_two_still_names_fewer():
    """The other quantifier is untouched: "up to two" is a ceiling."""
    card = next(
        card for card in _POOL.values()
        if card.primary_type in ("instant", "sorcery")
        and compile_card_oracle(card).supported
        and not compile_card_oracle(card).modes
        and (slot := cast_target_slot(card, compile_card_oracle(card))) is not None
        and slot[0].get("kind") == "creature"
        and not slot[0].get("own_only") and not slot[0].get("filter")
        and (slot[1].payload.get("targets") or {}).get("quantifier") == "up_to"
        and (slot[1].payload.get("targets") or {}).get("count") == 2
    )
    program = compile_card_oracle(card)
    slot = cast_target_slot(card, program)
    assert exact_target_count(slot[0], slot[1], None) is None
    bear = _w2g2_bear("Bear")
    game = _w2g2_count_table(card, mine=[_w2g2_bear("Mine")], theirs=[bear])

    queued = game.queue_from_hand(0, card.name, target_permanent_ids=[bear.permanent_id])

    assert queued.supported, f"{card.name}: {queued.details}"


def test_w2g2_the_ai_sizes_x_to_the_targets_it_names():
    """The proposal side. X was sized as the most the lands could pay before
    any target existed, so the seat announced a large X and named one
    creature — which the count gate would now refuse every turn."""
    advice = _POOL["Malicious Advice"]
    bears = [_w2g2_bear(f"Bear {n}") for n in range(2)]
    lands = [_w2g2_count_perm(_POOL["Swamp"]) for _ in range(6)]
    lands += [_w2g2_count_perm(_POOL["Island"]) for _ in range(2)]
    game = _w2g2_count_table(advice, mine=lands, theirs=bears)
    game.enforce_mana_costs = True

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == advice.name
    # Six lands could pay for X=6; two opposing creatures are what there is to
    # tap, so X is two — and it is the opponent's board, not the caster's own.
    assert action.target_player_index == 1, action
    assert action.target_permanent_index == [0, 1], action
    assert action.x_value == 2, action
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(
        0, action.card_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
        x_value=action.x_value,
    )
    assert result.supported, result.details
    assert all(bear.tapped for bear in bears), game.log
    assert game.players[0].life == 18, game.log


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------


def _census_bait() -> list:
    cards = []
    for n in range(3):
        cards += [
            _mk_card(name=f"Bait White {n}", type_line="Creature - Human Soldier", colors=("W",), power=2, toughness=2),
            _mk_card(name=f"Bait Red {n}", type_line="Creature - Goblin", colors=("R",), power=2, toughness=2),
            _mk_card(name=f"Bait Green {n}", type_line="Creature - Beast", colors=("G",), power=4, toughness=4),
            _mk_card(name=f"Bait Golem {n}", type_line="Artifact Creature - Golem", power=3, toughness=3),
            _mk_card(name=f"Bait Artifact {n}", type_line="Artifact"),
            _mk_card(name=f"Bait Enchantment {n}", type_line="Enchantment", colors=("W",)),
            _mk_card(name=f"Bait Nonbasic {n}", type_line="Land"),
            _mk_card(name=f"Bait Snow {n}", type_line="Snow Land"),
        ]
    cards += [_POOL["Plains"], _POOL["Island"], _POOL["Swamp"], _POOL["Forest"]]
    cards += [_POOL["Mountain"]] * 3
    return cards


def _census_grave() -> list:
    return [
        _mk_card(name=f"Dead Creature {n}", type_line="Creature - Zombie", colors=("B",), power=2, toughness=2)
        for n in range(4)
    ] + [_mk_card(name="Dead Artifact", type_line="Artifact")]


def _census_board(card, scene) -> Game:
    """A mirrored board. *scene* is "main", "attack" (seat 1 has declared four
    attackers) or "blocks" (and seat 0 has blocked three of them) — a count
    printed on "X target blocked creatures" has to be censused somewhere it
    has legal targets."""
    forest = _POOL["Forest"]
    game = Game(players=[
        PlayerState(
            name="P0", hand=[card, forest, forest] + _census_grave()[:3],
            library=[forest] * 10,
            battlefield=[Permanent(card=c) for c in _census_bait()],
            graveyard=_census_grave(),
        ),
        PlayerState(
            name="P1", library=[forest] * 10,
            battlefield=[Permanent(card=c) for c in _census_bait()],
            graveyard=_census_grave(),
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in game.all_permanents():
        perm.metadata["summoning_sickness_turn"] = -99
    if scene == "main":
        game.start_turn(0)
        game._close_current_priority_step()
        return game
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    game.declare_attackers(1, [0, 1, 2, 3], defending_player_index=0)
    if scene == "blocks":
        game._close_current_priority_step()
        game.advance_combat_phase()
        assert game.current_step == "declare_blockers", game.current_step
        ok, why = game.declare_blockers(0, {0: 0, 1: 1, 2: 2})
        assert ok, why
    return game


def _census_count(card):
    """``(kind, N | "x")`` for a slot printing an exact count, else None —
    read off the slot's own printed quantifier, so the census does not ask the
    function under test which cards to examine."""
    program = compile_card_oracle(card)
    if not program.supported or program.modes:
        return None
    slot = cast_target_slot(card, program)
    if slot is None:
        return None
    spec, instruction = slot
    if spec.get("roles") or spec.get("cost_targets") or spec.get("kind") == "divided":
        return None
    described = (instruction.payload or {}).get("targets")
    if not isinstance(described, dict) or described.get("quantifier") != "exactly":
        return None
    count = described.get("count")
    if isinstance(count, int) and count >= 2:
        return spec.get("kind"), count
    if count == "x":
        return spec.get("kind"), "x"
    return None


_COUNTED = {
    name: found
    for name, card in sorted(_POOL.items())
    if card.primary_type in ("instant", "sorcery")
    and (found := _census_count(card)) is not None
}


def _census_legal(game, card):
    spec = game.cast_target_spec(0, card)
    wanted = "graveyard" if spec.get("kind") == "graveyard_creature" else "permanent"
    by_seat: dict = {}
    for entry in spec.get("valid_targets") or []:
        if entry.get("kind") == wanted:
            by_seat.setdefault(entry["seat"], []).append(entry["index"])
    return wanted, by_seat


def _census_announce(game, card, wanted, seat, indices, x_value=None):
    kwargs: dict = {"x_value": x_value}
    if indices and wanted == "permanent":
        kwargs["target_player_index"] = seat
        kwargs["target_permanent_ids"] = [game.permanent_at(seat, i).permanent_id for i in indices]
    elif indices:
        kwargs["target_player_index"] = seat
        kwargs["target_permanent_index"] = list(indices)
    return game.queue_from_hand(0, card.name, **kwargs)


def _census_scene(card, count):
    """The first scene on which the complete announcement is castable."""
    need = 3 if count == "x" else count + 1
    exact = 2 if count == "x" else count
    for scene in ("main", "attack", "blocks"):
        if scene != "main" and card.primary_type != "instant":
            continue
        game = _census_board(card, scene)
        wanted, by_seat = _census_legal(game, card)
        seats = [seat for seat, slots in by_seat.items() if len(slots) >= need]
        if not seats:
            continue
        slots = by_seat[seats[0]]
        if _census_announce(
            game, card, wanted, seats[0], slots[:exact], 2 if count == "x" else None
        ).supported:
            return scene, wanted, seats[0], slots
    return None


def test_w2g2_the_count_census_examines_what_it_claims_to():
    printed = [name for name, (_kind, count) in _COUNTED.items() if count != "x"]
    by_x = [name for name, (_kind, count) in _COUNTED.items() if count == "x"]

    assert len(printed) >= 19, printed
    assert len(by_x) >= 18, by_x
    for name in ("Undo", "Dust to Dust", "Rain of Salt", "Ashes to Ashes", "Plow Under", "Reckless Spite"):
        assert name in printed
    assert "Malicious Advice" in by_x and "Winter Blast" in by_x


@pytest.mark.parametrize("name", sorted(_COUNTED))
def test_w2g2_an_exact_count_is_announced_exactly(name):
    card = _POOL[name]
    kind, count = _COUNTED[name]
    ready = _census_scene(card, count)
    assert ready is not None, (
        f"{name}: no census board on which {count} {kind} target(s) can be "
        "named and cast — the census would pass over this card unexamined"
    )
    scene, wanted, seat, slots = ready

    def accepted(indices, x_value=None) -> bool:
        game = _census_board(card, scene)
        return bool(_census_announce(game, card, wanted, seat, indices, x_value).supported)

    problems = []
    if count != "x":
        if accepted(slots[:count - 1]):
            problems.append(f"needs {count}, {count - 1} named: accepted")
        if accepted([]):
            problems.append(f"needs {count}, none named: accepted")
        if accepted(slots[:count + 1]):
            problems.append(f"needs {count}, {count + 1} named: accepted")
        if not accepted(slots[:count]):
            problems.append(f"needs {count}, {count} named: refused")
        if wanted == "permanent":
            game = _census_board(card, scene)
            _wanted, by_seat = _census_legal(game, card)
            keep = [game.permanent_at(seat, index) for index in slots[:count - 1]]
            game.remove_all_from_battlefield([
                game.permanent_at(s, i) for s, indices in by_seat.items() for i in indices
                if not any(game.permanent_at(s, i) is kept for kept in keep)
            ])
            scarce = game.queue_from_hand(
                0, card.name, target_player_index=seat,
                target_permanent_ids=[perm.permanent_id for perm in keep],
            )
            if scarce.supported:
                problems.append(f"needs {count}, only {count - 1} legal anywhere: accepted")
    else:
        if accepted(slots[:2], 3):
            problems.append("X=3, two named: accepted")
        if accepted([], 2):
            problems.append("X=2, none named: accepted")
        if accepted(slots[:3], 2):
            problems.append("X=2, three named: accepted")
        if not accepted(slots[:2], 2):
            problems.append("X=2, two named: refused")
    assert not problems, f"{name}: " + "; ".join(problems)

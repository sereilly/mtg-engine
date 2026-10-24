"""Census: every damage sweep asks CR 616.1e's question.

Judgment's wave 1 (W1G2) measured Phantom Centaur under Pestilence: two
effects apply to the same damage event — protection from black prevents it,
and the Phantom's own "If damage would be dealt to this creature, prevent that
damage. Remove a +1/+1 counter" prevents it too — so the affected object's
controller chooses which applies first (CR 616.1, 616.1e; the card's
2004-10-04 ruling: "you can choose to apply Protection from Black's damage
prevention ability prior to applying this card's built-in ability. This means
you don't have to remove a counter."). ``handlers/damage_sweeps.py`` called the
damage entry points without ``asks``, so an interactive seat was never asked
and got the default.

The census is every sweep kind in that module, each driven with every card
in the pool that carries it until one reaches the recipient: a Phantom (its
counter shield) with a "prevent the next 3 damage" shield on it as well — two
applicable prevention effects whatever colour the source is, and an order
that matters (the pool first leaves the counter; the Phantom first spends the
counter and leaves the pool). On the base every kind dealt its damage without
asking.

Each run also checks the half the brief named as the work: the answer comes
back to a **resumable** sweep, so the recipients behind the one that asked are
still dealt to and the sweep's summary is written once, after them.
"""

from __future__ import annotations

import random

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import OracleInstruction, compiled_units
from engine.shields import (PREVENT_NEXT_N, add_shield, make_numeric_pool,
                            shields_of_kind)
from tests.helpers import resolve_stack

#: Every effect kind ``engine/handlers/damage_sweeps.py`` registers.
_SWEEP_KINDS = (
    "deal_damage_each_creature_and_player", "earthquake_damage",
    "hurricane_damage", "deal_damage_to_random_creatures",
    "deal_damage_each_attacking_creature", "deal_damage_each_matching",
)


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


_POOL = _pool()


def _instructions(value):
    if isinstance(value, OracleInstruction):
        yield value
        for sub in (value.payload or {}).values():
            yield from _instructions(sub)
    elif isinstance(value, (tuple, list)):
        for sub in value:
            yield from _instructions(sub)
    elif isinstance(value, dict):
        for sub in value.values():
            yield from _instructions(sub)


def _sweeps_by_kind() -> dict[str, list]:
    found: dict[str, list] = {kind: [] for kind in _SWEEP_KINDS}
    for card, program in compiled_units(_POOL.values()):
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [a.instruction for a in program.activated_abilities if a.instruction]
        roots += [t.instruction for t in program.triggered_abilities if t.instruction]
        for root in roots:
            for instruction in _instructions(root):
                if instruction.kind in found:
                    found[instruction.kind].append((card, instruction))
    return found


def _counters(permanent) -> int:
    return int(permanent.metadata.get("plus_counters", 0))


def _table(kind: str, *, interactive: bool):
    """Seat 0 holds the Phantom and the extra shield; seat 1 sweeps and holds a
    Phantom of its own (one applicable effect, nothing to ask) that comes after
    seat 0's in every sweep's order."""
    game = Game(players=[
        PlayerState("Defender", library=[_POOL["Island"]] * 5),
        PlayerState("Sweeper", library=[_POOL["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(1)
    phantom_name = "Phantom Flock" if kind == "hurricane_damage" else "Phantom Centaur"
    phantom = Permanent(card=_POOL[phantom_name])
    game._put_permanent_onto_battlefield(0, phantom, None)
    behind = Permanent(card=_POOL["Phantom Tiger"])
    game._put_permanent_onto_battlefield(1, behind, None)
    resolve_stack(game)
    game.pending_choices.clear()
    for creature in (phantom, behind):
        creature.metadata["summoning_sickness_turn"] = -99
        if kind == "deal_damage_each_attacking_creature":
            creature.attacking = True
    add_shield(phantom, make_numeric_pool(3))
    return game, phantom, behind


def _sweep(game, card, instruction):
    source = None
    if not ("Instant" in card.type_line or "Sorcery" in card.type_line):
        source = Permanent(card=card)
        game._put_permanent_onto_battlefield(1, source, None)
        game.stack.clear()
        game.pending_choices.clear()
    game._execute_oracle_instruction(instruction, OracleExecutionContext(
        caster=game.players[1], target=game.players[0], card=card,
        source_permanent=source, x_value=2,
    ))


def _state(game, phantom, behind) -> tuple:
    pool = sum(s.amount or 0 for s in shields_of_kind(phantom, PREVENT_NEXT_N))
    return (
        _counters(phantom), pool, phantom.damage_marked,
        _counters(behind), behind.damage_marked,
        tuple(player.life for player in game.players),
    )


def _run(kind, card, instruction, *, interactive: bool, seed: int):
    """One sweep. Seeded, because Falling Star's "lands on" is drawn from the
    module-level ``random`` (``engine/dexterity.py``): the reference run and
    the asked run must land on the same creatures."""
    game, phantom, behind = _table(kind, interactive=interactive)
    before = _state(game, phantom, behind)
    random.seed(seed)
    _sweep(game, card, instruction)
    return game, phantom, behind, before


def test_every_damage_sweep_asks_which_prevention_applies_first():
    """Each kind, each card carrying it until one reaches the Phantom. A run
    where nobody is asked (the default, CR 616.1e's first option) is the
    reference; the run where seat 0 is asked must stop at the Phantom, and
    answering with that same first option must leave exactly the reference's
    board — every recipient behind the one that asked dealt to, the summary
    written, nothing left owing."""
    by_kind = _sweeps_by_kind()
    unreached, unasked, unfinished = [], [], []
    for kind in _SWEEP_KINDS:
        rows = by_kind[kind]
        assert rows, f"no card in the pool carries {kind!r} — the census is blind to it"
        for card, instruction in rows:
            # A seed under which the sweep reaches the Phantom (every seed, for
            # all but the random one).
            for seed in range(8):
                ref_game, ref_phantom, ref_behind, before = _run(
                    kind, card, instruction, interactive=False, seed=seed,
                )
                reference = _state(ref_game, ref_phantom, ref_behind)
                if reference[:3] != before[:3]:
                    break
            else:
                continue  # this card's sweep does not reach the Phantom
            game, phantom, behind, _ = _run(
                kind, card, instruction, interactive=True, seed=seed,
            )
            asked = [c for c in game.pending_choices if c.kind == "effect_order"]
            if not asked:
                unasked.append(f"{kind} ({card.name})")
                break
            assert asked[0].player_index == 0
            assert _state(game, phantom, behind)[:3] == before[:3], (
                f"{kind} ({card.name}): the Phantom was dealt to before the answer"
            )
            assert game.resolve_pending_choice("effect_order", 0, option_index=0)
            after = _state(game, phantom, behind)
            if after != reference:
                unfinished.append(f"{kind} ({card.name}): {after} != {reference}")
            if game.resume_stack or game.pending_choices:
                unfinished.append(
                    f"{kind} ({card.name}): {len(game.resume_stack)} step(s) owed, "
                    f"{[c.kind for c in game.pending_choices]} queued"
                )
            if ref_game.log[-1] != game.log[-1]:
                unfinished.append(
                    f"{kind} ({card.name}): ended on {game.log[-1]!r}, "
                    f"not {ref_game.log[-1]!r}"
                )
            break
        else:
            unreached.append(kind)

    assert not unreached, f"no card carrying these kinds reached the Phantom: {unreached}"
    assert not unasked, (
        "a sweep dealt damage to a creature with two applicable prevention "
        f"effects without asking its controller (CR 616.1e): {unasked}"
    )
    assert not unfinished, f"the sweep did not finish after the answer: {unfinished}"


def test_phantom_centaur_under_pestilence_is_asked_and_the_answer_is_honoured():
    """The measured card, on the real activation path: protection first keeps
    the counter (the 2004-10-04 ruling's choice); the Phantom's own shield
    first spends one. Either way the sweep goes on to both players and the
    other creature, and its summary is the last thing it writes."""
    for pick, kept in (("protection", 3), ("remove a counter", 2)):
        game = Game(players=[
            PlayerState("Alice", library=[_POOL["Island"]] * 5),
            PlayerState("Bob", library=[_POOL["Island"]] * 5),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game.start_turn(1)
        centaur = Permanent(card=_POOL["Phantom Centaur"])
        game._put_permanent_onto_battlefield(0, centaur, None)
        bears = Permanent(card=_POOL["Grizzly Bears"])
        game._put_permanent_onto_battlefield(1, bears, None)
        game._put_permanent_onto_battlefield(1, Permanent(card=_POOL["Pestilence"]), None)
        resolve_stack(game)
        assert _counters(centaur) == 3

        assert game.queue_permanent_ability(1, "Pestilence").supported
        game.resolve_top_of_stack(pause_for_choices=True)
        choice = game.pending_choice_of("effect_order")
        assert choice is not None and choice.player_index == 0
        labels = [str(option) for option in choice.data["options"]]
        assert len(labels) == 2
        assert bears.damage_marked == 0, "nothing behind the question has happened"

        index = next(i for i, label in enumerate(labels) if pick in label.lower())
        assert game.resolve_pending_choice("effect_order", 0, option_index=index)
        resolve_stack(game)

        assert _counters(centaur) == kept
        assert centaur.damage_marked == 0
        assert bears.damage_marked == 1
        assert [p.life for p in game.players] == [19, 19]
        summary = "Pestilence dealt 1 damage to each creature and each player"
        assert game.log.count(summary) == 1
        assert game.resume_stack == [] and game.pending_choices == []

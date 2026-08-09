"""CR 613 — the continuous-effect layer system.

Characteristics are not stored; they are *computed*. Starting from an object's
printed (copiable) values, every applicable continuous effect is applied in a
fixed series of layers, and within a layer in timestamp order — except where
one effect depends on another, which overrides timestamps.

    613.1  layers 1..7
    613.3  within layers 2–6: characteristic-defining abilities first,
           then everything else in timestamp order
    613.4  within layer 7: sublayers 7a (CDAs) → 7b (set) → 7c (modify) →
           7d (switch), each in timestamp order
    613.7  timestamps
    613.8  dependency, which overrides timestamp order

The engine previously approximated this with per-effect metadata flags applied
in a hand-ordered sequence. That works while every effect commutes, and stops
working the moment two effects disagree about order — which is exactly what
layers and dependency exist to settle. The order is a property of the *rules*
here, not of the order code happens to run in.

This module is pure: it computes characteristics from a set of effects and
never touches game state. ``engine/mixins/permanent_state.py`` collects the
effects and writes the results back.
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

# 613.7: timestamps only need a total order, so a monotonic counter is enough.
# Module-level rather than per-game so a helper can stamp an effect without
# being handed the game; deterministic, because it advances only when game
# operations create effects, and those are already seed-reproducible.
_TIMESTAMP = itertools.count(1)


def next_timestamp() -> int:
    """The next timestamp (613.7b: an effect is stamped when it is created)."""
    return next(_TIMESTAMP)

# Layer numbers, named so call sites read as the rule does.
LAYER_COPY = 1
LAYER_CONTROL = 2
LAYER_TEXT = 3
LAYER_TYPE = 4
LAYER_COLOR = 5
LAYER_ABILITY = 6
LAYER_PT = 7

# 613.4: layer 7's sublayers, in application order.
PT_SUBLAYERS = ("a", "b", "c", "d")


@dataclass
class Characteristics:
    """One object's derived characteristics, mutated as layers are applied.

    ``power``/``toughness`` are ``None`` until a layer sets them: a
    characteristic-defining ability (7a) or the printed value seeded before
    layer 1. Keeping them optional is what stops a variable "*" P/T from
    silently reading as 0.
    """

    card_types: set[str] = field(default_factory=set)
    subtypes: set[str] = field(default_factory=set)
    supertypes: set[str] = field(default_factory=set)
    colors: set[str] = field(default_factory=set)
    abilities: set[str] = field(default_factory=set)
    power: int | None = None
    toughness: int | None = None
    controller_index: int | None = None
    # 7d is recorded rather than applied immediately: a switch must act on the
    # values as they stand after 7c, and two switches cancel.
    switched: bool = False

    def snapshot(self) -> tuple:
        """A hashable value used to compare states when probing dependency."""
        return (
            tuple(sorted(self.card_types)),
            tuple(sorted(self.subtypes)),
            tuple(sorted(self.supertypes)),
            tuple(sorted(self.colors)),
            tuple(sorted(self.abilities)),
            self.power,
            self.toughness,
            self.controller_index,
            self.switched,
        )

    def copy(self) -> "Characteristics":
        return copy.deepcopy(self)


# The whole board's characteristics, keyed by object id. Effects read it
# because their scope can depend on other objects ("creatures you control",
# "as long as you control a Swamp"), which is what makes dependency real.
State = dict[int, Characteristics]


@dataclass(frozen=True)
class ContinuousEffect:
    """One continuous effect, placed in the layer system.

    ``applies_to`` is re-evaluated against the *current* state each time the
    effect is considered, not fixed when the effect is created — that is what
    makes "creatures you control get +1/+1" follow a control-change applied in
    an earlier layer.

    **``modify`` and ``applies_to`` must be pure.** Detecting dependency means
    asking what an effect *would* do, so both are applied speculatively to
    throwaway copies of the state and may run many times per recompute. Any
    side effect outside the ``Characteristics`` passed in will fire spuriously.
    """

    layer: int
    modify: Callable[[Characteristics], None]
    applies_to: Callable[[int, State], bool]
    sublayer: str = ""
    # 613.7: earlier timestamps apply first.
    timestamp: int = 0
    # 613.3 / 613.8a: CDAs apply before other effects in layers 2–6, and an
    # effect never depends on one unless both are CDAs.
    from_cda: bool = False
    # Diagnostics only — makes an ordering bug readable in a failure message.
    label: str = ""

    @property
    def order_key(self) -> tuple:
        # Within layers 2–6 CDAs come first (613.3); within layer 7 the
        # sublayers already separate them, so the flag is inert there.
        return (0 if self.from_cda else 1, self.timestamp)


def _targets(effect: ContinuousEffect, state: State) -> tuple[int, ...]:
    return tuple(sorted(oid for oid in state if effect.applies_to(oid, state)))


def _apply_one(effect: ContinuousEffect, state: State) -> None:
    for oid in _targets(effect, state):
        effect.modify(state[oid])


def _signature(effect: ContinuousEffect, state: State) -> tuple:
    """What *effect* would do to *state*, without committing it.

    Used to detect dependency: 613.8a asks whether applying another effect
    would change this one's existence, what it applies to, or what it does to
    what it applies to. Probing all three by trial application answers the
    question generally, rather than enumerating known card interactions.
    """
    trial = {oid: char.copy() for oid, char in state.items()}
    targets = _targets(effect, trial)
    for oid in targets:
        effect.modify(trial[oid])
    return (targets, tuple(trial[oid].snapshot() for oid in targets))


def _depends_on(
    first: ContinuousEffect, second: ContinuousEffect, state: State
) -> bool:
    """613.8a: does *first* depend on *second*?"""
    # (c) neither effect is from a CDA, or both are.
    if first.from_cda != second.from_cda:
        return False
    before = _signature(first, state)
    trial = {oid: char.copy() for oid, char in state.items()}
    _apply_one(second, trial)
    return _signature(first, trial) != before


def _apply_group(effects: Sequence[ContinuousEffect], state: State) -> None:
    """Apply one layer/sublayer's effects, honoring dependency (613.8).

    Timestamp order is the default; an effect that depends on others waits
    until they have been applied (613.8b). The remaining order is re-evaluated
    after every application, because applying one effect can create or remove a
    dependency among those left (613.8c). A dependency loop falls back to
    timestamp order, as the rule requires.
    """
    remaining = sorted(effects, key=lambda e: e.order_key)
    while remaining:
        chosen = 0
        for index, candidate in enumerate(remaining):
            others = [e for i, e in enumerate(remaining) if i != index]
            if not any(_depends_on(candidate, other, state) for other in others):
                chosen = index
                break
        else:
            # Every remaining effect depends on another: a loop. 613.8b says
            # ignore dependency and use timestamp order, which `remaining`
            # already is.
            chosen = 0
        _apply_one(remaining.pop(chosen), state)


def apply_layers(effects: Iterable[ContinuousEffect], state: State) -> State:
    """Apply every effect to *state* in CR 613 order, returning it.

    *state* should already hold each object's copiable values (printed
    characteristics, or those of whatever it copies — layer 1 is applied by the
    caller when it seeds this).
    """
    pending = list(effects)

    for layer in (LAYER_CONTROL, LAYER_TEXT, LAYER_TYPE, LAYER_COLOR, LAYER_ABILITY):
        group = [e for e in pending if e.layer == layer]
        if group:
            _apply_group(group, state)

    for sublayer in PT_SUBLAYERS:
        group = [e for e in pending if e.layer == LAYER_PT and e.sublayer == sublayer]
        if not group:
            continue
        if sublayer == "d":
            # 613.4d: a switch acts on the values as they stand after 7c.
            # Recorded as a flag through the group so two switches cancel,
            # then resolved once below.
            _apply_group(group, state)
            continue
        _apply_group(group, state)

    for char in state.values():
        if char.switched:
            char.power, char.toughness = char.toughness, char.power
            char.switched = False

    return state


# ---------------------------------------------------------------------------
# Constructors for the common effect shapes
# ---------------------------------------------------------------------------


def scope_only(target_id: int) -> Callable[[int, State], bool]:
    """An effect that applies to exactly one object."""
    return lambda oid, state: oid == target_id


def set_pt(
    target: Callable[[int, State], bool],
    power: int | None,
    toughness: int | None,
    *,
    timestamp: int,
    from_cda: bool = False,
    label: str = "",
) -> ContinuousEffect:
    """Layer 7a (CDA) or 7b (set to a value).

    ``None`` for a stat leaves it alone — "has base power 0" sets power only
    and lets toughness keep tracking whatever else applies.
    """

    def modify(char: Characteristics) -> None:
        if power is not None:
            char.power = power
        if toughness is not None:
            char.toughness = toughness

    return ContinuousEffect(
        layer=LAYER_PT,
        sublayer="a" if from_cda else "b",
        modify=modify,
        applies_to=target,
        timestamp=timestamp,
        from_cda=from_cda,
        label=label,
    )


def modify_pt(
    target: Callable[[int, State], bool],
    power: int,
    toughness: int,
    *,
    timestamp: int,
    label: str = "",
) -> ContinuousEffect:
    """Layer 7c: +N/+N, counters, anthems."""

    def modify(char: Characteristics) -> None:
        char.power = (char.power or 0) + power
        char.toughness = (char.toughness or 0) + toughness

    return ContinuousEffect(
        layer=LAYER_PT, sublayer="c", modify=modify, applies_to=target,
        timestamp=timestamp, label=label,
    )


def switch_pt(
    target: Callable[[int, State], bool], *, timestamp: int, label: str = ""
) -> ContinuousEffect:
    """Layer 7d: switch power and toughness. Two switches cancel."""

    def modify(char: Characteristics) -> None:
        char.switched = not char.switched

    return ContinuousEffect(
        layer=LAYER_PT, sublayer="d", modify=modify, applies_to=target,
        timestamp=timestamp, label=label,
    )


def add_types(
    target: Callable[[int, State], bool],
    *,
    card_types: Iterable[str] = (),
    subtypes: Iterable[str] = (),
    supertypes: Iterable[str] = (),
    replace_subtypes: bool = False,
    timestamp: int,
    label: str = "",
) -> ContinuousEffect:
    """Layer 4: type-changing. ``replace_subtypes`` covers "is a Swamp"-style
    effects, which replace the land's types rather than adding to them."""
    card_types, subtypes, supertypes = tuple(card_types), tuple(subtypes), tuple(supertypes)

    def modify(char: Characteristics) -> None:
        char.card_types.update(card_types)
        if replace_subtypes:
            char.subtypes = set(subtypes)
        else:
            char.subtypes.update(subtypes)
        char.supertypes.update(supertypes)

    return ContinuousEffect(
        layer=LAYER_TYPE, modify=modify, applies_to=target,
        timestamp=timestamp, label=label,
    )


def set_colors(
    target: Callable[[int, State], bool],
    colors: Iterable[str],
    *,
    timestamp: int,
    label: str = "",
) -> ContinuousEffect:
    """Layer 5: colour-changing ("becomes red", the laces)."""
    colors = tuple(colors)

    def modify(char: Characteristics) -> None:
        char.colors = set(colors)

    return ContinuousEffect(
        layer=LAYER_COLOR, modify=modify, applies_to=target,
        timestamp=timestamp, label=label,
    )


def grant_abilities(
    target: Callable[[int, State], bool],
    abilities: Iterable[str],
    *,
    timestamp: int,
    label: str = "",
) -> ContinuousEffect:
    """Layer 6: ability-adding."""
    abilities = tuple(abilities)

    def modify(char: Characteristics) -> None:
        char.abilities.update(abilities)

    return ContinuousEffect(
        layer=LAYER_ABILITY, modify=modify, applies_to=target,
        timestamp=timestamp, label=label,
    )


def remove_abilities(
    target: Callable[[int, State], bool],
    abilities: Iterable[str],
    *,
    timestamp: int,
    label: str = "",
) -> ContinuousEffect:
    """Layer 6: ability-removing. Shares the layer with granting, so which one
    wins is decided by timestamp (or dependency) rather than by which code path
    happens to run last."""
    abilities = tuple(abilities)

    def modify(char: Characteristics) -> None:
        char.abilities.difference_update(abilities)

    return ContinuousEffect(
        layer=LAYER_ABILITY, modify=modify, applies_to=target,
        timestamp=timestamp, label=label,
    )


def change_control(
    target: Callable[[int, State], bool],
    controller_index: int,
    *,
    timestamp: int,
    label: str = "",
) -> ContinuousEffect:
    """Layer 2: control-changing."""

    def modify(char: Characteristics) -> None:
        char.controller_index = controller_index

    return ContinuousEffect(
        layer=LAYER_CONTROL, modify=modify, applies_to=target,
        timestamp=timestamp, label=label,
    )


__all__ = [
    "Characteristics", "ContinuousEffect", "LAYER_ABILITY", "LAYER_COLOR",
    "LAYER_CONTROL", "LAYER_COPY", "LAYER_PT", "LAYER_TEXT", "LAYER_TYPE",
    "PT_SUBLAYERS", "State", "add_types", "apply_layers", "change_control",
    "grant_abilities", "modify_pt", "remove_abilities", "scope_only",
    "set_colors", "set_pt", "switch_pt",
]

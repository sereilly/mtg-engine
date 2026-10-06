"""Census: a player who cannot be a target is not one a spell resolves on.

Two more doors onto the defect ``test_player_target_census.py`` closes at the
announcement, each of which needs no illegal announcement at all:

* **a cast that names nobody.** The engine's headless convention lets a spell
  that owes a target name none and resolve at the default seat — the opposing
  one. The default is a target like any other, and nothing asked whether it was
  a legal one: with the opponent behind an Ivory Mask, 101 of 119 bare casts
  resolved on them anyway. Such a cast is refused now, and says who it could
  not choose (``legality._cast_player_target_refusal``).
* **CR 608.2b.** "If the spell or ability specifies targets, it checks whether
  the targets are still legal. … If all its targets, for every instance of the
  word 'target,' are now illegal, the spell or ability doesn't resolve."
  ``illegal_targets_refusal`` declined every spell whose target may be a
  player, because a seat and a chosen player ride one field of a stack item;
  ``stack_targets`` tells them apart, and the gate asks it now. Of 119 spells
  aimed legally at a player who then gained shroud, 118 resolved on them.

Both sweeps have a control arm on the plain table — the spell must be accepted
there and must change the opposing seat — so a spell is examined only where
"it did nothing" is evidence rather than the card's ordinary behaviour.
"""

from __future__ import annotations

from engine.models import Permanent
from tests.helpers import resolve_stack

from .test_player_target_census import (
    cast_keywords, offered_seats, player_spell_rows, pool, table,
)

# 119 spells reach each sweep's control arm (October 2026).
_MIN_EXAMINED = 105


def _seat_state(game, seat: int) -> tuple:
    """Everything a spell aimed at a player's face can change about them."""
    player = game.players[seat]
    return (
        player.life, len(player.hand), len(player.library), len(player.graveyard),
        len(player.exile), dict(player.mana_pool),
        tuple(sorted(
            (permanent.card.name, permanent.tapped, permanent.damage_marked)
            for permanent in game.controlled_by(seat)
        )),
    )


def _finish(game) -> None:
    resolve_stack(game)
    game.auto_resolve_pending_choices()


def _undivided_rows():
    # A division naming nothing is CR 601.2d's own refusal, and one naming a
    # face is swept entry by entry in the announcement census.
    return [row for row in player_spell_rows() if row[2] != "divided"]


def test_h1_a_cast_naming_nobody_never_resolves_on_a_seat_its_picker_does_not_offer():
    examined = 0
    resolved_on_the_mask: list[str] = []
    for card, mode, _kind in _undivided_rows():
        keywords = cast_keywords(card, mode, {})
        probe = table("opponent_shroud", card)
        if 1 in offered_seats(probe.cast_target_spec(0, card, mode_index=mode)):
            continue
        control = table("plain", card)
        before = _seat_state(control, 1)
        result = control.cast_from_hand(0, card.name, **keywords)
        control.auto_resolve_pending_choices()
        if not result.supported or _seat_state(control, 1) == before:
            continue  # its unnamed default is not the opposing seat's face
        examined += 1
        game = table("opponent_shroud", card)
        before = _seat_state(game, 1)
        result = game.cast_from_hand(0, card.name, **keywords)
        game.auto_resolve_pending_choices()
        if result.supported and _seat_state(game, 1) != before:
            resolved_on_the_mask.append(card.name if mode is None else f"{card.name} #{mode}")

    assert examined >= _MIN_EXAMINED, examined
    assert not resolved_on_the_mask, (len(resolved_on_the_mask), resolved_on_the_mask[:20])


def test_h1_a_spell_whose_only_target_gained_shroud_in_response_does_not_resolve():
    """CR 608.2b for a player target, over every spell that names one."""
    mask = pool()["Ivory Mask"]
    examined = 0
    resolved_on_the_mask: list[str] = []
    not_countered: list[str] = []
    for card, mode, _kind in _undivided_rows():
        keywords = dict(cast_keywords(card, mode, {}), target_player_index=1)
        control = table("plain", card)
        before = _seat_state(control, 1)
        if not control.queue_from_hand(0, card.name, **keywords).supported:
            continue
        _finish(control)
        if _seat_state(control, 1) == before:
            continue
        examined += 1
        game = table("plain", card)
        assert game.queue_from_hand(0, card.name, **keywords).supported, card.name
        # In response: the named player gains shroud (CR 702.18a).
        game._put_permanent_onto_battlefield(1, Permanent(card=mask), None)
        before = _seat_state(game, 1)
        _finish(game)
        label = card.name if mode is None else f"{card.name} #{mode}"
        if _seat_state(game, 1) != before:
            resolved_on_the_mask.append(label)
        if not any("every target is illegal (608.2b)" in line for line in game.log):
            not_countered.append(label)

    assert examined >= _MIN_EXAMINED, examined
    assert not resolved_on_the_mask, (len(resolved_on_the_mask), resolved_on_the_mask[:20])
    # One spell is not countered and is right not to be: Arc Lightning-style
    # divisions are out of this sweep, and a spell with a second, still-legal
    # target resolves (CR 608.2b is all-or-nothing). Anything listed here has
    # a single player target and resolved past the rule.
    assert not not_countered, not_countered


# 532 one-target announcements over the pool's instants and sorceries, each
# cast unkicked and — where the card offers one — kicked (October 2026).
_MIN_UNDISTURBED = 500


def test_h1_a_spell_whose_announced_target_is_undisturbed_is_never_countered():
    """The control arm of CR 608.2b as a whole: a target that was legal as the
    spell was announced, on a table nobody touches, is legal as it resolves.

    Owed by the change above it. The rule is "the announcement's question,
    asked again", so it is only as right as the two askings are alike — and the
    resolution's was not asked under the kicker the cast paid (CR 702.33g). It
    was made to be, for a player target's sake, and one of the two readers
    behind it was missed: an unkicked Rushing River ("If this spell was kicked,
    return **another** target nonland permanent…") had its one legal target
    judged by a two-target spell's probe, and was countered by the rules in a
    seeded Planeshift game. Nothing in the suite cast one.
    """
    from engine.oracle import compile_card_oracle

    from .test_player_target_census import kickers

    examined = 0
    countered: list[str] = []
    for card in sorted(pool().values(), key=lambda entry: entry.name):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if program.modes and program.mode_chooser is not None:
            continue
        for mode in (range(len(program.modes)) if program.modes else (None,)):
            taken = kickers(table("plain", card), card)
            for payments in ([{}, taken] if taken else [{}]):
                game = table("plain", card)
                spec = game.cast_target_spec(
                    0, card, mode_index=mode, optional_cost_payments=payments,
                )
                if spec.get("kind") in ("none", "modal", "faces", "roles", "divided"):
                    continue
                if spec.get("exact_targets") or spec.get("cost_targets"):
                    continue
                if spec.get("cost_spec"):
                    # A cost that eats a permanent may eat the one named
                    # (Scapegoat sacrifices a creature and returns creatures):
                    # that target *was* disturbed, by the cast itself.
                    continue
                targets = [
                    entry for entry in spec.get("valid_targets") or ()
                    if entry.get("kind") in ("permanent", "player")
                ]
                if not targets:
                    continue
                first = sorted(
                    targets,
                    key=lambda entry: (entry.get("kind") != "permanent", entry.get("seat") != 1),
                )[0]
                keywords = cast_keywords(card, mode, payments)
                if first["kind"] == "player":
                    keywords["target_player_index"] = first["seat"]
                else:
                    keywords["target_permanent_ids"] = [
                        game.players[first["seat"]].battlefield[first["index"]].permanent_id
                    ]
                if not game.queue_from_hand(0, card.name, **keywords).supported:
                    continue
                examined += 1
                _finish(game)
                if any("(608.2b)" in line for line in game.log):
                    label = card.name if mode is None else f"{card.name} #{mode}"
                    countered.append(f"{label}{' kicked' if payments else ''}")

    assert examined >= _MIN_UNDISTURBED, examined
    assert not countered, (len(countered), countered[:20])

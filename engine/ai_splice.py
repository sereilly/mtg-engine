"""Whether an AI seat splices cards onto an Arcane spell (CR 702.47), and the
cast it makes if it does.

CR 702.47a: "'Splice onto [quality] [cost]' means 'You may reveal this card
from your hand as you cast a [quality] spell. If you do, that spell gains the
text of this card's rules text and you pay [cost] as an additional cost to cast
that spell.'" The seat never did: it cast every splice card alone, spending the
card, and never once added one to the Arcane spell it was casting anyway —
the card that keeps its text in the hand for the next Arcane spell, which is
the whole of what the keyword sells.

So a splice is weighed **one level out**, after the host's own candidate is
built (``ai_casts._best_of_the_modes``), as an entwine is
(``ai_entwine.entwined_cast``): the host's announcement stands — its mode, its
targets, its X — and each card ``splice.splice_candidates`` offers is added to
it as one more announcement. The gained text's targets (CR 702.47d) are chosen
out of the engine's own list for that text — ``splice.spliced_text_card``, the
spell as the gained text reads (a blue host's Glacial Ray may target a
creature with protection from red) — on the side its effect wants
(``ai_target_sides.spell_target_side``), each one **rehearsed as the combined
cast** (``ai_rehearsal.rehearse`` through ``ai_scoring._rehearse_announcement``)
— never as the gained text alone: the spell it reads as carries the host's
name, and a cast by that name is the host's. A splice is kept only when that
rehearsal, finished where the host's was (``ai_cast_score``), scores above the
cast without it; the seat then tries the next card on top.

**The splice cost is mana the hand might want** (CR 601.2f: an additional
cost). A seat that splices whenever it can spends the turn's mana on a second
text while a creature waits in its hand, so a splice is taken only with mana
no other spell in the hand needs — the buyback rule
(``ai_casts._buyback_mana_is_spare``) for the same reason, the spliced cards
themselves set aside: casting one alone later costs what splicing it does now,
and splicing keeps it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from . import ai_cast_trace as cast_trace
from .oracle import compile_card_oracle
from .splice import (_X_WORD, splice_candidates, splice_cost_symbols,
                     spliced_text_card)
from .cost_pickers import spec_is_a_cost
from .targeting import derive_cast_spec, spec_roles

if TYPE_CHECKING:
    from .ai_actions import CastAction
    from .game import Game
    from .models import CardDefinition


#: The most splice cards weighed onto one spell. Each is a rehearsal per
#: target it could name, and a limited hand holds two at the most.
SPLICES_WEIGHED = 3

#: The most graveyard cards a spliced text's target is weighed among (Soulless
#: Revival's "target creature card from your graveyard"), after look-alikes by
#: name are dropped.
GRAVEYARD_TARGETS_WEIGHED = 4


def spliced_cast(
    game: "Game", player_index: int, card: "CardDefinition", best: "CastAction",
    *, from_zone: str = "hand", extra_generic: int = 0,
) -> "CastAction | None":
    """*best* — the cast of the Arcane spell *card* this seat would make —
    with every card in its hand worth splicing onto it (CR 702.47a), scored by
    the combined cast's rehearsal; or None when no splice beats *best*.

    Asked inside the permission *best* was weighed under
    (``ai_weighed_cast.casting_under``, held by the caller), so the price and
    the zone's bonus are read as *best*'s were and the two scores compare.
    """
    if best is None:
        return None
    spell_hand_index = best.hand_index if from_zone == "hand" else None
    offered = splice_candidates(
        game, player_index, card, spell_hand_index=spell_hand_index,
    )[:SPLICES_WEIGHED]
    if not offered:
        return None
    if best.optional_cost_payments or best.alternative_cost:
        # The host's plan was drawn for an offer's mana or an alternative
        # price; the splice's mana is planned on the mana cost alone.
        with cast_trace.attempt(
            game, player_index, card, variant="spliced",
            from_zone=from_zone, zone_index=best.hand_index,
        ):
            return cast_trace.dropped(
                "built with an offer or an alternative cost: a splice's mana is"
                " planned beside the mana cost only"
            )
    chosen: list[dict] = []
    current = best
    for hand_index, spliced, offer in offered:
        found = _best_splice_of(
            game, player_index, card, current, chosen, hand_index, spliced, offer,
            offered=offered, from_zone=from_zone, extra_generic=extra_generic,
        )
        if found is not None and found.score > current.score:
            current = found
            chosen = list(found.splice_cards or ())
    return current if chosen else None


def _best_splice_of(
    game: "Game", player_index: int, card: "CardDefinition",
    current: "CastAction", chosen: "list[dict]", hand_index: int,
    spliced: "CardDefinition", offer, *, offered, from_zone: str,
    extra_generic: int,
) -> "CastAction | None":
    """*current* with *spliced* (at *hand_index*) spliced on after *chosen*,
    at whichever of the gained text's targets its rehearsal measures most —
    or None when it cannot be spliced, paid for, or is worth nothing.

    Each target weighed is one candidate of the decision's trace
    (``ai_cast_trace.attempt``, variant "spliced"), finished or dropped on its
    own, so an explanation names the one the seat would cast."""
    heading = f"splicing {spliced.name} (hand #{hand_index})" + (
        f" after {len(chosen)} already spliced" if chosen else ""
    )
    weighed = _splice_answers_and_plan(
        game, player_index, card, current, chosen, hand_index, spliced, offered,
        extra_generic=extra_generic,
    )
    if isinstance(weighed, str):
        with cast_trace.attempt(
            game, player_index, card, variant="spliced",
            from_zone=from_zone, zone_index=current.hand_index,
        ):
            cast_trace.note(heading)
            return cast_trace.dropped(weighed)
    answers, (tap_indices, tap_colors) = weighed
    best_found: "CastAction | None" = None
    for answer in answers:
        action = replace(
            current,
            splice_cards=[*chosen, {"hand_index": hand_index, **answer}],
            land_tap_indices=tap_indices,
            land_tap_colors=tap_colors,
            score=0.0,
        )
        with cast_trace.attempt(
            game, player_index, card, variant="spliced",
            from_zone=from_zone, zone_index=current.hand_index,
        ):
            cast_trace.note(f"{heading}, its text aimed at {answer or 'no target'}")
            scored = _rehearsed(game, player_index, card, action)
            if isinstance(scored, str):
                cast_trace.dropped(scored)
                continue
        if best_found is None or scored.score > best_found.score:
            best_found = scored
    return best_found


def _splice_answers_and_plan(
    game: "Game", player_index: int, card: "CardDefinition",
    current: "CastAction", chosen: "list[dict]", hand_index: int,
    spliced: "CardDefinition", offered, *, extra_generic: int,
) -> "tuple[list[dict], tuple] | str":
    """``(target answers, (taps, colours))`` for splicing *spliced* onto
    *current* after *chosen* — or why it is not weighed."""
    text_card = spliced_text_card(card, spliced)
    program = compile_card_oracle(text_card)
    if not program.supported or program.modes or _X_WORD.search(text_card.oracle_text or ""):
        # `splice.announce_splices` refuses these three; asked first so a
        # refused cast is never rehearsed.
        return f"{spliced.name}'s gained text is unsupported, modal or has an X"
    answers = _splice_target_answers(
        game, player_index, text_card, named=_named_ids(current, chosen),
    )
    if answers is None:
        return (
            f"{spliced.name}'s gained text names targets of a shape this chooser"
            " does not weigh (roles, or a cost)"
        )
    if not answers:
        return (
            f"{spliced.name}'s gained text has no legal target on the side its"
            " effect wants (CR 702.47b)"
        )
    splicing = {hand_index, *(entry["hand_index"] for entry in chosen)}
    priced = _splice_plan(
        game, player_index, card, current, splicing, offered,
        extra_generic=extra_generic,
    )
    if isinstance(priced, str):
        return priced
    return answers, priced


def _named_ids(current: "CastAction", chosen: "list[dict]") -> "set[int]":
    """The permanents *current* — the spell and the texts already spliced
    onto it — names as targets, by id."""
    named = {each for each in (current.target_permanent_ids or ()) if isinstance(each, int)}
    for entry in chosen:
        named.update(
            each for each in (entry.get("target_permanent_ids") or ())
            if isinstance(each, int)
        )
    return named


def _rehearsed(
    game: "Game", player_index: int, card: "CardDefinition", action: "CastAction",
) -> "CastAction | str":
    """*action* finished and scored by the rehearsal of the whole cast, read
    as the host's own candidate was — or why it is not proposed."""
    from .ai_actions import cast_announcement, weighed_at_instant_speed
    from .ai_cast_score import finished_cast_candidate, kept_above_the_floor
    from .ai_scoring import (_rehearse_announcement, _weighed_through_the_fight,
                             held_at_instant_speed, not_worth_proposing,
                             read_at_instant_speed)

    announcement = cast_announcement(action)
    rehearsal = _rehearse_announcement(
        game, player_index, card, announcement, planned=action,
    )
    rehearsal = _weighed_through_the_fight(
        game, player_index, card, announcement, rehearsal, planned=action,
    )
    instant = weighed_at_instant_speed()
    if instant:
        rehearsal, held = read_at_instant_speed(
            game, player_index, card, action, rehearsal,
        )
        if held is not None:
            return held
    if rehearsal is None:
        return "no rehearsal could be run"
    if (refused := not_worth_proposing(rehearsal)) is not None:
        return refused
    if instant and (held := held_at_instant_speed(rehearsal)) is not None:
        return held
    finished = kept_above_the_floor(
        finished_cast_candidate(game, player_index, card, action, rehearsal)
    )
    if finished is None:
        return "scored under the floor"
    return finished


def _splice_plan(
    game: "Game", player_index: int, card: "CardDefinition",
    current: "CastAction", splicing: "set[int]", offered, *, extra_generic: int,
) -> "tuple[tuple, tuple] | str":
    """``(taps, colours)`` paying for *current* with the cards at *splicing*
    spliced on (CR 601.2f: each splice cost an additional cost, before the
    reductions — Long-Forgotten Gohei's ruling), or why not."""
    from .ai_payment import _cost_for, _plan_land_taps

    if not game.enforce_mana_costs:
        return current.land_tap_indices, current.land_tap_colors
    player = game.players[player_index]
    splice_cost: dict[str, int] = {}
    for hand_index, _spliced, offer in offered:
        if hand_index in splicing:
            for symbol, amount in splice_cost_symbols(offer).items():
                splice_cost[symbol] = splice_cost.get(symbol, 0) + amount
    required = _cost_for(
        game, player, card, current.x_value,
        extra_generic=extra_generic + splice_cost.get("generic", 0),
        extra_pips={s: n for s, n in splice_cost.items() if s != "generic"},
    )
    plan = _plan_land_taps(game, player, required)
    if plan is None:
        return "unaffordable with the splice costs on top (CR 601.2f)"
    without = _cost_for(game, player, card, current.x_value, extra_generic=extra_generic)
    if not _splice_mana_is_spare(
        game, player_index, current, without, required, splicing,
    ):
        return (
            "the splice costs spend mana another spell in hand needs this turn"
            " (the buyback rule)"
        )
    return plan


def _splice_mana_is_spare(
    game: "Game", player_index: int, current: "CastAction",
    without: "dict[str, int]", required: "dict[str, int]", splicing: "set[int]",
) -> bool:
    """Whether paying *required* (the spell with its splices) rather than
    *without* (the spell alone) costs this seat no other spell this turn —
    `ai_casts._buyback_mana_is_spare`'s question: some other spell in hand
    castable beside the spell alone and not beside it spliced. The spliced
    cards are not such spells (casting one alone costs what splicing it
    does, and splicing keeps it), nor is the spell itself; at instant speed
    only what can be cast now counts (``cast_timing.casts_at_instant_speed``)."""
    from .ai_actions import hand_spells, weighed_at_instant_speed
    from .ai_payment import _cost_for, _plan_land_taps
    from .ai_weighed_cast import casting_under
    from .cast_costs import cast_announces_x
    from .cast_timing import casts_at_instant_speed

    player = game.players[player_index]
    at_instant_speed = weighed_at_instant_speed()
    for other_index, other in hand_spells(player):
        if other_index in splicing or (
            current.from_zone == "hand" and other_index == current.hand_index
        ):
            continue
        if other.primary_type == "land" or cast_announces_x(other, from_zone="hand"):
            continue
        if at_instant_speed and not casts_at_instant_speed(other, game, player_index):
            continue
        with casting_under(None):
            beside = _cost_for(game, player, other, None)
        both = dict(without)
        every = dict(required)
        for symbol, amount in beside.items():
            both[symbol] = both.get(symbol, 0) + amount
            every[symbol] = every.get(symbol, 0) + amount
        if (
            _plan_land_taps(game, player, both) is not None
            and _plan_land_taps(game, player, every) is None
        ):
            return False
    return True


def _splice_target_answers(
    game: "Game", player_index: int, text_card: "CardDefinition",
    *, named: "set[int]" = frozenset(),
) -> "list[dict] | None":
    """The target keywords to weigh for the text *text_card* adds (CR
    702.47d), one dict per answer: ``[{}]`` for a text naming no target, an
    empty list when it has no legal target on the side its effect wants, and
    None for a shape this chooser does not weigh.

    Out of the engine's own list for the spell as the text reads
    (``Game._enumerate_targets`` over ``text_card``, the list a person's
    picker offers), the side read off the text
    (``ai_target_sides.spell_target_side``), look-alike permanents dropped and
    at most ``ai_targets.TARGETS_WEIGHED`` kept (``_distinct_targets``). A
    permanent the spell already names (*named*: the host's target, an earlier
    splice's) is weighed apart from the look-alike collapse, so a second Glacial
    Ray is offered the other Grizzly Bears as well as the one the first hit."""
    from .ai_scoring import choose_attack_target
    from .ai_target_sides import spell_target_side
    from .ai_targets import _distinct_targets, _target_candidates

    program = compile_card_oracle(text_card)
    # No mode: a modal gained text is refused before this is asked (as
    # `splice.announce_splices` refuses it), and the host's mode is the
    # host's announcement, not the gained text's.
    spec = derive_cast_spec(text_card, program, from_zone="hand", mode_index=None)
    if not isinstance(spec, dict) or spec.get("kind") == "none":
        return [{}]
    if spec.get("kind") == "modal" or spec_roles(spec) or spec_is_a_cost(spec):
        return None
    legal = game._enumerate_targets(
        player_index, text_card, spec, for_cast=True, mode_index=None,
    )
    if not legal:
        return []
    side = spell_target_side(text_card)
    others = [seat for seat in range(len(game.players)) if seat != player_index]
    if side == "you":
        seats = [player_index]
    elif side == "opponent":
        first = choose_attack_target(game, player_index)
        seats = [first] + [seat for seat in others if seat != first]
    else:
        seats = [*others, player_index]
    answers: list[dict] = []
    for seat in seats:
        if any(entry.get("kind") == "player" and entry.get("seat") == seat for entry in legal):
            answers.append({"target_player_index": seat})
    permanents = _target_candidates(
        game, [entry for entry in legal if entry.get("kind") == "permanent"], seats,
    )
    fresh = [each for each in permanents if each[2][0] not in named]
    again = [each for each in permanents if each[2][0] in named]
    for seat, _index, ids in [*_distinct_targets(game, fresh), *again]:
        answers.append({"target_player_index": seat, "target_permanent_ids": list(ids)})
    seen: set = set()
    for entry in legal:
        if entry.get("kind") != "graveyard" or entry.get("seat") not in seats:
            continue
        look = (entry["seat"], entry.get("name"))
        if look in seen or len(seen) >= GRAVEYARD_TARGETS_WEIGHED:
            continue
        seen.add(look)
        answers.append({
            "target_player_index": entry["seat"],
            "target_graveyard_indices": [entry["index"]],
        })
    for entry in legal:
        if entry.get("kind") == "stack" and isinstance(entry.get("stack_index"), int):
            answers.append({"target_stack_index": entry["stack_index"]})
    return answers


__all__ = [
    "GRAVEYARD_TARGETS_WEIGHED",
    "SPLICES_WEIGHED",
    "spliced_cast",
]

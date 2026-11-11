"""The answers an AI seat gives part-way through a resolution, where the
prompt's default (``engine/pending_choices.py``) asks for a weighed one.

The registry's defaults (``mixins/stack/choices``) state the policy — take
gifts, pay tolls, make no trades — and ask these wherever an answer is worth
weighing rather than stating:

* **a library** — which card a search finds (:func:`choose_search_card`,
  :func:`choose_search_cards`), how a scry or a rearrangement leaves the top,
  which finds of a pile bought back a card at a time are kept
  (:func:`slow_pile_picks`) and which card a Wish brings in from outside the
  game (:func:`choose_outside_game_card`) — each card weighed by what casting
  it would be worth (``ai_scoring._score_tutor_choice``);
* **a choice** — a modal trigger's mode (:func:`choose_trigger_mode`,
  CR 700.2b, rehearsed), where a spell copy is re-aimed
  (:func:`choose_copy_target`, :func:`choose_copy_new_targets`, CR 707.10c),
  a number named in secret (Goblin Game), whether to change a spell's targets
  (:func:`choose_target_change`), and the order a hand pick takes cards in
  (:func:`order_hand_pick`).

The answer to an **offer** — a toll, a "you may A. If you do, B." trade, a
copy offer, a chain link, a mana-priced "you may pay" — is
``ai_offer_answers``'. What each pile and chosen value *does* is
``ai_prompt_readers``'. The resolution paths import these from here, inside
the function that asks.
"""

from __future__ import annotations

from .ai_target_sides import ability_target_side, spell_seat_side, spell_target_side
from .ai_rehearsal import deliberating, rehearse, rehearsing
from .ai_standing import permanent_worth
from .game import Game
from .models import CardDefinition, Permanent
from .search_filters import search_matches, searched_seat
from .ai_scoring import _score_tutor_choice, choose_attack_target


def choose_trigger_mode(game: Game, choice, stated: int) -> int:
    """Which offered mode of a **modal triggered ability** a seat nobody asks
    takes (CR 700.2b): the one measured to do most, or *stated* — the
    registry's standing answer, the first mode that is not a price — when
    nothing measures more than it or no rehearsal can be run.

    The valuation the cast chooser weighs a spell's bullets with, asked of a
    trigger's: each offered mode is answered on a scratch copy of the game
    (``Game._resolve_mode_choice``, which records the mode and its default
    target on the ability), the ability resolves there, and the swings are
    compared (``ai_rehearsal.rehearse``). So Trufflesnout takes four life at
    three life and the counter at twenty, and Elder Gargaroth draws when a
    Beast is worth less to it than a card — where each took its first bullet
    whatever the board.

    The choice is made as the ability goes on the stack (CR 603.3c), which
    for an entry trigger is while the permanent's own spell is still
    resolving; the copy is cut loose from that (``detach``) and carries out
    the ability alone. "Nothing done" is the ability taken off the stack,
    which is what CR 700.2b does to one with no mode chosen.
    """
    item = choice.data.get("_trigger_item")
    options = tuple(choice.data.get("_options") or ())
    if item is None or len(options) < 2 or rehearsing():
        return stated

    def without(table, prompt) -> None:
        ability = prompt.data.get("_trigger_item")
        table.stack = [queued for queued in table.stack if queued is not ability]

    class _Answered:
        def __init__(self, supported: bool) -> None:
            self.supported = supported
            self.details = "" if supported else "the mode could not be chosen"

    best, best_swing = stated, None
    with deliberating():
        order = [stated, *(index for index in range(len(options)) if index != stated)]
        for index in order:
            rehearsal = rehearse(
                game, choice.player_index,
                lambda table, prompt, index=index: _Answered(
                    bool(table._resolve_mode_choice(prompt, index))
                ),
                leaves_hand=False, carried=choice, detach=True, without=without,
                label=(
                    f"{getattr(getattr(item, 'card', None), 'name', None) or 'a trigger'}"
                    f" (its triggered ability's mode {index})"
                ),
            )
            if rehearsal is None:
                return stated
            if not rehearsal.accepted:
                continue
            if best_swing is None or rehearsal.swing > best_swing + 1e-9:
                best, best_swing = index, rehearsal.swing
    return best


class _Answered:
    """The shape a rehearsal reads off what it carried out (``supported``,
    ``details``) for an answer that is not a cast."""

    def __init__(self, supported: bool) -> None:
        self.supported = supported
        self.details = "" if supported else "the answer was not taken"


#: Under this, a re-aimed copy is no better than one left where it was: the
#: standings are sums of floats.
_COPY_GAIN = 1e-9


def _best_rehearsed_answer(game: Game, seat: int, carried, answers, answer, label: str):
    """The answer out of *answers* whose rehearsal leaves *seat* furthest
    ahead of leaving the copy as it is, or None where none does better.

    Each answer is carried out on a scratch copy cut loose from the
    resolution that offered it (``detach="abstract"``: the rest of that
    resolution — the copies still to be made — is not made there), by
    ``answer(table, held, choice)`` with *carried* copied into the table as
    *held*; the copy and everything below it on the stack resolve, and the
    table is compared with the same copy left untouched — the copy keeping
    its original's target. One copy at a time: the next copy's offer is
    weighed with this one already aimed."""
    if rehearsing():
        return None
    best, best_swing = None, _COPY_GAIN
    with deliberating():
        for choice in answers:
            rehearsal = rehearse(
                game, seat,
                lambda table, held, choice=choice: _Answered(bool(answer(table, held, choice))),
                leaves_hand=False, carried=carried, detach="abstract", label=label,
            )
            if rehearsal is None:
                return None
            if rehearsal.accepted and rehearsal.swing > best_swing:
                best, best_swing = choice, rehearsal.swing
    return best


def choose_copy_target(game: Game, choice, kept: dict) -> dict:
    """Where a seat nobody asks aims a spell copy it may re-aim (CR 707.10c:
    "you may choose new targets for the copy") at **a permanent or a
    player** (the ``copy_spell_target`` prompt): the offered target whose
    rehearsal leaves the seat furthest ahead, or *kept* — the original's, the
    prompt's stated answer — where none does better than keeping it.

    Every copy kept its original's target, so storm's copies stacked on one
    creature: Scattershot's three copies each dealt their 1 to the same
    1/1, and two were countered by the rules once it died (CR 608.2b), with
    two other creatures to hit (W1G1)."""
    targets = list(choice.data.get("targets") or ())
    if choice.data.get("_copy") is None or not targets:
        return kept
    answers = [
        {"seat": target.get("seat")} if target.get("kind") == "player"
        else {"permanent_id": target.get("permanent_id")}
        for target in targets
    ]
    answers = [response for response in answers if response != kept]
    if rehearsing():
        # No rehearsal inside a rehearsal — so a copy offered there (the
        # rehearsal of casting a Fork, the copy's own resolution on the
        # scratch table) was kept where its original pointed, and a Fork of
        # an opponent's Bolt aimed at the copier's own creature read as a
        # second Bolt on that creature: a cast worth nothing, never proposed
        # (kg4). The answer there is the side's (:func:`_copy_target_by_side`),
        # cheap and only ever a move off the wrong side; the real one is
        # measured when the copy is made.
        return _copy_target_by_side(game, choice, kept, answers)
    picked = _best_rehearsed_answer(
        game, choice.player_index, choice, answers,
        lambda table, prompt, response: table._resolve_copy_spell_target(prompt, response),
        label=f"{choice.data.get('card_name') or 'a copy'} (the copy's new target)",
    )
    return kept if picked is None else picked


def _answer_seat(game: Game, answer: dict) -> "int | None":
    """The seat a ``copy_spell_target`` answer is on: the player it names, or
    the controller of the permanent it names."""
    if "seat" in answer:
        return answer.get("seat")
    permanent = game.permanent_by_id(answer.get("permanent_id"))
    return None if permanent is None else game.controller_index_of(permanent)


def _copy_target_by_side(game: Game, choice, kept: dict, answers: list) -> dict:
    """Where a seat nobody asks aims a copy **inside a rehearsal**, where no
    answer can be measured: *kept*, unless *kept* is gone or on the wrong
    side of the table for what the copy does (``ai_target_sides.spell_target_side``, else
    ``spell_seat_side`` where a player may be named) — then the first answer on the right side: the
    opponent the seat attacks (``ai_scoring.choose_attack_target``) where a
    player is offered, else the dearest permanent there
    (``ai_standing.permanent_worth``); for a gift, the seat's own dearest
    permanent, else its own face.

    A floor rather than a choice: the scratch table this answers for is
    reading whether the copy is worth making at all, and the copy's real
    target is measured when it is made (:func:`choose_copy_target`). A copy
    already on the right side is never moved here."""
    seat = choice.player_index
    copy = choice.data.get("_copy")
    card = getattr(copy, "card", None)
    if card is None:
        return kept
    wanted = spell_target_side(card)
    if wanted is None and ("seat" in kept or any("seat" in answer for answer in answers)):
        # A target that may be a player ("any target"): what the spell does
        # to the player it names says whose side it is for.
        wanted = spell_seat_side(card)
    kept_seat = _answer_seat(game, kept)
    if wanted is None:
        return kept
    # A kept target that has gone (the permanent its original destroyed:
    # "Destroy target noncreature permanent. Then that permanent's controller
    # may copy this spell", Chain of Acid) is no side at all — the copy kept
    # there is countered (CR 608.2b) — so any answer on the right side beats
    # it.
    if kept_seat is not None and (kept_seat == seat) == (wanted == "you"):
        return kept
    hostile = wanted == "opponent"
    right = [
        answer for answer in answers
        if (seat_of := _answer_seat(game, answer)) is not None
        and (seat_of != seat) == hostile
    ]
    players = [answer for answer in right if "seat" in answer]
    permanents = sorted(
        (answer for answer in right if "seat" not in answer),
        key=lambda answer: -permanent_worth(game.permanent_by_id(answer["permanent_id"])),
    )
    if hostile and players:
        attacked = choose_attack_target(game, seat)
        return next(
            (answer for answer in players if answer["seat"] == attacked), players[0]
        )
    if permanents:
        return permanents[0]
    return players[0] if players else kept


def choose_copy_new_targets(game: Game, seat: int, copy, slots) -> list:
    """Where a seat nobody asks re-aims each slot of a spell copy it "may
    choose new targets" for (CR 707.10c) when the copy is not one permanent
    or player (``copy_spell_target``'s, :func:`choose_copy_target`): one
    entry per slot of *slots* (``stack_targets.change_slots``), the new
    target or None to keep that slot's.

    **Slot by slot** (CR 115.7d: "The player may leave any number of the
    targets unchanged"): each slot's options (``new_target_options``, given
    the slots already answered) are rehearsed with the earlier answers
    applied, beside keeping this one, and the best taken where it beats
    keeping by more than nothing. One target at a time is what the rule
    lets a player decide, and it keeps the rehearsals to one per option
    rather than one per combination. A card in a graveyard or a spell is
    one slot of this shape: Reaping the Graves' storm copies each kept its
    original's card, so the first copy to resolve returned it and every other
    one was countered by the rules (W1G1). A copy of a spell with several
    targets or a mode kept all of them, on every road, until kg5.

    **Inside a rehearsal** nothing can be measured (``rehearsing``), and the
    answer is the side's (:func:`_copy_new_targets_by_side`) — the floor
    :func:`_copy_target_by_side` is for a one-slot copy, so a Fork of an
    opponent's Reckless Spite aimed at the forker's creatures reads as the
    removal it becomes, not as a second one on its own board.
    """
    from .stack_targets import apply_target_change, may_keep_target, new_target_options

    picks: list = [None] * len(slots)
    if rehearsing():
        return _copy_new_targets_by_side(game, seat, copy, slots)
    label = f"{copy.card.name} (the copy's new target)"

    def answer(table, held, choice) -> bool:
        held_copy, held_slots, held_options, held_earlier, position = held
        trial = list(held_earlier)
        if choice is not None:
            trial[position] = held_options[choice]
        changed = [(slot, pick) for slot, pick in zip(held_slots, trial) if pick is not None]
        if not changed:
            return True
        return apply_target_change(
            table, held_copy, [slot for slot, _ in changed], [pick for _, pick in changed],
        )

    with deliberating():
        for position in range(len(slots)):
            options = new_target_options(slots, picks, position)
            if not options:
                continue
            carried = (copy, slots, tuple(options), tuple(picks), position)
            answers = list(range(len(options)))
            # Keeping this slot is worth what the answers so far are: nothing
            # at all with none given, and otherwise their own rehearsal — and
            # it is no answer where an earlier slot took what this one names.
            keeps = may_keep_target(slots, picks, position)
            best, best_swing = None, 0.0
            if not keeps:
                best_swing = None
            elif any(pick is not None for pick in picks):
                answers.insert(0, None)
                best_swing = None
            for choice in answers:
                rehearsal = rehearse(
                    game, seat,
                    lambda table, held, choice=choice: _Answered(bool(answer(table, held, choice))),
                    leaves_hand=False, carried=carried, detach="abstract", label=label,
                )
                if rehearsal is None:
                    return picks
                if not rehearsal.accepted:
                    continue
                if best_swing is None or rehearsal.swing > best_swing + _COPY_GAIN:
                    best, best_swing = choice, rehearsal.swing
            if best is not None:
                picks[position] = options[best]
            elif not keeps:
                picks[position] = options[0]
    return picks


def _copy_slot_side(game: Game, copy, slot) -> "str | None":
    """Whose side the effect spending *slot* of *copy* wants its target on —
    the division's (``ai_slot_sides.divided_shape``), the chosen mode's own
    instruction for a slot one of ``chosen_modes`` holds, else the object's
    (:func:`_target_change_side`, which reads a lone chosen mode itself)."""
    from .ai_target_sides import activation_target_side
    from .oracle import compile_card_oracle
    from .text_changes import spell_text_card

    if slot.current.channel == "divided":
        from .ai_slot_sides import divided_shape

        shape = divided_shape(compile_card_oracle(spell_text_card(copy)))
        return None if shape is None else shape.side
    if slot.current.mode is not None:
        modes = tuple(getattr(copy, "chosen_modes", ()) or ())
        printed = compile_card_oracle(spell_text_card(copy)).modes
        if not 0 <= slot.current.mode < len(modes):
            return None
        index = modes[slot.current.mode].index
        if not 0 <= index < len(printed) or printed[index].instruction is None:
            return None
        instruction = printed[index].instruction
        return ability_target_side(instruction) or activation_target_side(instruction)
    return _target_change_side(game, copy)


def _chosen_target_seat(game: Game, target) -> "int | None":
    """The seat a slot's target is on: the player it names, or the
    controller of the permanent it names (None for anything else, or a
    permanent that has gone)."""
    if target.kind == "player":
        return target.seat
    if target.kind != "permanent":
        return None
    permanent = game.permanent_by_id(target.permanent_id)
    return None if permanent is None else game.controller_index_of(permanent)


def _copy_new_targets_by_side(game: Game, seat: int, copy, slots) -> list:
    """:func:`choose_copy_new_targets` **inside a rehearsal**: each slot kept,
    unless what it names is gone or on the wrong side of the table for the
    effect spending it (:func:`_copy_slot_side`) — then the first answer on
    the right side, as :func:`_copy_target_by_side` orders a one-slot copy's:
    the opponent the seat attacks where a player is offered for harm, else
    the dearest permanent there, else a player. A floor, never a choice: the
    copy's real targets are measured when it is made."""
    from .stack_targets import may_keep_target, new_target_options

    picks: list = [None] * len(slots)
    for position, slot in enumerate(slots):
        if not may_keep_target(slots, picks, position):
            # An earlier slot took what this one names: it must move.
            options = new_target_options(slots, picks, position)
            picks[position] = options[0] if options else None
            continue
        if slot.current.kind not in ("permanent", "player"):
            continue
        wanted = _copy_slot_side(game, copy, slot)
        if wanted is None:
            continue
        now = _chosen_target_seat(game, slot.current)
        if now is not None and (now == seat) == (wanted == "you"):
            continue
        hostile = wanted == "opponent"
        right = [
            candidate for candidate in new_target_options(slots, picks, position)
            if (where := _chosen_target_seat(game, candidate)) is not None
            and (where != seat) == hostile
        ]
        if not right:
            continue
        players = [candidate for candidate in right if candidate.kind == "player"]
        permanents = sorted(
            (candidate for candidate in right if candidate.kind == "permanent"),
            key=lambda candidate: -permanent_worth(game.permanent_by_id(candidate.permanent_id)),
        )
        if hostile and players:
            attacked = choose_attack_target(game, seat)
            picks[position] = next(
                (candidate for candidate in players if candidate.seat == attacked), players[0],
            )
        elif permanents:
            picks[position] = permanents[0]
        else:
            picks[position] = players[0]
    return picks


def choose_search_card(
    game: Game, player_index: int, data: dict
) -> tuple[str, int] | None:
    """Pick the ``(zone, index)`` of the best card a search may find, or None to
    fail to find (CR 701.23b).

    Both the zones and the restriction come from the armed choice rather than
    from a second reading of the card: the AI is then offered exactly the cards
    a human seat is offered, and ``search_matches`` is the only thing deciding
    what is findable. An AI that filtered differently would be a second opinion
    about what the effect finds — the same bug class as a second parse.
    """
    picks = choose_search_cards(game, player_index, data, 1)
    if not picks:
        return None
    return picks[0]["zone"], picks[0]["index"]


def choose_search_cards(
    game: Game, player_index: int, data: dict, count: int
) -> list[dict]:
    """The counted search's answer: up to *count* distinct picks, best first,
    each ``{"zone": ..., "index": ...}`` the way the resolver reads them.

    A printed name is consumed by the find that used it, exactly as the
    resolver will consume it — an AI that kept offering a used name would
    submit an answer the engine then refuses, which is the fail-to-find.
    """
    from .permanent_cards import is_permanent_card
    from .search_filters import (landing_seat, name_key, search_slots,
                                 search_zone_cards, slot_assignment)

    # The zone the search looks in, which is not always the chooser's own —
    # see `searched_seat`. An AI reading its own graveyard for a card the
    # effect takes from someone else's would answer with an index the resolver
    # then refuses, which is the fail-to-find.
    player = game.players[searched_seat(data, player_index)]
    working = dict(data)
    picks: list[dict] = []
    taken: set[tuple[str, int]] = set()
    # **Whose hand the finds are for.** A seat choosing cards that go to
    # somebody else's hand (Guided Passage: "an opponent chooses … you put the
    # chosen cards into your hand"; Jester's Mask's refilled hand) is choosing
    # what its opponent gets, and wants the *least* of what the phrase admits.
    # Read off the prompt's own seats rather than off a card: the finds land
    # where `landing_seat` says, and that is the whole of the question. A find
    # taken out of another seat's library for any other place — exile (Jester's
    # Cap), the chooser's own battlefield (Bribery) — is still the best card.
    destinations = list(working.get("destinations") or ()) or [
        working.get("destination", "hand")
    ]
    handing_over = (
        landing_seat(working, player_index) != player_index
        and all(place == "hand" for place in destinations)
    )
    sign = -1.0 if handing_over else 1.0
    # **A find the battlefield cannot take is no find.** Where every find is
    # bound for the battlefield, a card CR 400.4a leaves where it was found (a
    # Kindred instant a "Goblin card" names, ``permanent_cards``) is a legal
    # answer that puts nothing down — so a seat choosing for itself passes it
    # over, as it would a card it could not use.
    to_battlefield = all(place == "battlefield" for place in destinations)

    def findable(card) -> bool:
        if to_battlefield and not is_permanent_card(card):
            return False
        return search_matches(card, working, game=game, owner=player_index)

    if search_slots(working):
        # "a land card **of each basic land type**" (Gaea's Balance): one find
        # per printed description. Best card first, each kept only while the
        # cards kept so far can still all be given a description of their own
        # — `slot_assignment`, the resolver's own question, so this is an
        # answer it admits. Taking the best that still fits is exact here (the
        # sets that can be assigned are a matroid), so it is also as many
        # finds as the zones allow, which is what a floor asks for.
        entries = [
            (zone, index, card)
            for zone in tuple(working.get("zones", ("library",)))
            for index, card in enumerate(search_zone_cards(player, zone))
            if findable(card)
        ]
        entries.sort(
            key=lambda entry: -sign * _score_tutor_choice(game, player_index, entry[2])
        )
        kept: list[tuple] = []
        for entry in entries:
            if len(kept) >= count:
                break
            trial = kept + [entry]
            if None not in slot_assignment(
                [card for _zone, _index, card in trial], working,
                game=game, owner=player_index,
            ):
                kept = trial
        return [{"zone": zone, "index": index} for zone, index, _card in kept]
    for _ in range(count):
        best: tuple[str, int] | None = None
        best_score = float("-inf")
        for zone in tuple(working.get("zones", ("library",))):
            cards = search_zone_cards(player, zone)
            for index, card in enumerate(cards):
                if (zone, index) in taken or not findable(card):
                    continue
                score = sign * _score_tutor_choice(game, player_index, card)
                if best is None or score > best_score:
                    best = (zone, index)
                    best_score = score
        if best is None:
            break
        zone, index = best
        card = search_zone_cards(player, zone)[index]
        taken.add(best)
        picks.append({"zone": zone, "index": index})
        among = list((working.get("restrictions") or {}).get("named_among") or ())
        if among:
            working["restrictions"] = {
                **(working.get("restrictions") or {}),
                "named_among": [n for n in among if name_key(n) != name_key(card.name)],
            }
    return picks


def choose_outside_game_card(
    game: Game, player_index: int, candidates: list[int]
) -> int | None:
    """The sideboard position of the card a seat nobody asks brings in from
    outside the game (the Wishes, CR 400.11b), or None with nothing to offer.

    *candidates* is the engine's own list (``handlers.cards.
    outside_game_candidates``), never a second reading of the card: the AI is
    offered exactly what a person is. Weighed as a library search's find is
    (``_score_tutor_choice``) — a sideboard is a pile its owner looks through
    in full, which is the search's situation — the best first, the earliest
    position between equals so a seed reproduces the pick.
    """
    if not candidates:
        return None
    sideboard = game.players[player_index].sideboard
    return max(
        candidates,
        key=lambda index: (
            _score_tutor_choice(game, player_index, sideboard[index]), -index,
        ),
    )


def choose_exiled_card_to_return(
    game: Game, player_index: int, offered: list,
) -> int | None:
    """Which of *offered* — ``(position, card)`` pairs, the engine's own list
    (``handlers.exiled_returns.returnable_exiled_records``) — a seat nobody
    asks puts onto the battlefield (Dimensional Breach's "returns one of the
    exiled cards they own"), as its position; None with nothing offered.

    The card is going straight onto the battlefield, so it is weighed as the
    permanent it will be (``ai_standing.permanent_worth`` over the card as
    printed, read for what lasts) rather than as a card to cast. One card
    comes back per upkeep, so the order is the whole decision and the biggest
    permanent first is the plain reading; the earliest position between equals,
    so a seed reproduces the pick.
    """
    if not offered:
        return None
    best_position, best_worth = None, float("-inf")
    for position, card in offered:
        worth = permanent_worth(Permanent(card=card), now=False)
        if worth > best_worth + 1e-9:
            best_position, best_worth = position, worth
    return best_position


#: How many cards a seat nobody asks exiles into a pile that returns **one card
#: per activation** (`ai_prompt_readers.exiled_search_pile_comes_back_one_at_a_time`).
#: A weight: one activation a turn is the most such a pile gives back, and three
#: is about what the rest of a game has turns for.
SLOW_RETURN_PILE_SIZE = 3


def slow_pile_picks(game: Game, player_index: int, picks: list[dict]) -> list[dict]:
    """The picks a headless seat keeps of *picks* — every card an "any number"
    exile-search matched, as ``{"zone", "index"}`` — when the pile is bought
    back a card at a time: the `SLOW_RETURN_PILE_SIZE` it would most want to
    tutor for (`_score_tutor_choice`), in the order it was offered between
    equals.

    For ``_default_search_exile``. Skyship Weatherlight's default exiled every
    artifact and creature in the seat's library and then returned them at
    random for {4} each, which over a game is most of a deck's threats gone
    for good.
    """
    player = game.players[player_index]

    def card_at(pick: dict) -> CardDefinition:
        zone = player.library if pick.get("zone") == "library" else player.graveyard
        return zone[pick["index"]]

    ranked = sorted(
        enumerate(picks),
        key=lambda entry: (
            -_score_tutor_choice(game, player_index, card_at(entry[1])), entry[0],
        ),
    )
    kept = sorted(position for position, _pick in ranked[:SLOW_RETURN_PILE_SIZE])
    return [picks[position] for position in kept]


def choose_search_library_index(game: Game, player_index: int, card_type: str = "any") -> int | None:
    """Pick the library index of the best card to tutor for (e.g. Demonic Tutor).

    Returns None when no library card matches card_type (fail to find). The
    library-only view of ``choose_search_card``, kept because a caller that only
    ever searches a library should not have to spell out a zone list."""
    found = choose_search_card(game, player_index, {"card_type": card_type})
    return None if found is None else found[1]


def choose_reorder_library_order(
    game: Game, caster_index: int, target_index: int, top_count: int
) -> list[int]:
    """Decide how to rearrange the top cards of a library (e.g. Natural Selection).

    Returns a permutation of ``range(top_count)`` where element 0 is the original
    index of the card that should end up on top (the next card drawn).

    When reordering our own library we surface the most valuable card first so we
    draw it next; when reordering an opponent's library we bury their best cards by
    putting the least valuable one on top.
    """
    target = game.players[target_index]
    top = target.library[:top_count]

    # Score each card from the library owner's perspective — how good drawing it
    # would be for them.
    scored = [
        (index, _score_tutor_choice(game, target_index, card))
        for index, card in enumerate(top)
    ]
    surface_best_first = caster_index == target_index
    scored.sort(key=lambda item: item[1], reverse=surface_best_first)
    return [index for index, _ in scored]


def choose_secret_number(
    game: Game, player_index: int, minimum: int = 1, card=None,
) -> int:
    """The number a seat names in secret (Goblin Game): "Each player hides at
    least one item … Each player loses life equal to the number of items they
    revealed. The player who revealed the fewest items then loses half their
    life, rounded up."

    **Where the highest number is what pays** (Menacing Ogre: "Each player
    with the highest number loses that much life. If you are one of those
    players, put two +1/+1 counters on this creature.") the seat names the
    floor. Any number above it is lost life the moment it is the highest, and
    nothing the sentences offer a seat buys it back except the Ogre's
    counters — which its controller also gets by naming the floor whenever
    every other seat does. So the floor is the answer that never loses life it
    did not have to; read off the compiled program
    (``ai_prompt_readers.secret_number_highest_pays``), never off a name.

    Every point named is a point of life, and the least pays half of what it
    has left. So there are two lines and the policy picks between them from
    the life totals, which are all a seat may know — **it never reads another
    seat's number**, and is asked before any exists:

    * **the quiet line** — name the floor. It costs the floor and, as the
      fewest or tied for it, half the rest: ``(life - floor) // 2`` is left.
    * **outbidding** — name the weakest rival's whole life total. That rival
      can only match it by naming all the life it has, so it is either the
      fewest or dead, and this seat keeps ``life - bid`` unhalved.

    Outbidding is taken only when it leaves strictly more than the quiet line
    does, which is the seat far enough ahead on life to afford it (roughly: the
    weakest rival is at half this seat's life or less). That inequality is also
    the ceiling: the answer is always below the seat's own life total wherever
    any such answer is legal, the rule ``default_sacrifice_pick`` states for
    every default here — one never picks the answer that loses the game.

    Deterministic, and a function of public state alone.
    """
    floor = max(0, int(minimum))
    if card is not None:
        from .ai_prompt_readers import secret_number_highest_pays

        if secret_number_highest_pays(card):
            return floor
    life = int(game.players[player_index].life)
    rivals = [
        int(player.life)
        for seat, player in enumerate(game.players)
        if seat != player_index and not player.lost
    ]
    if not rivals:
        return floor
    bid = max(floor, min(rivals))
    quiet = max(0, life - floor) // 2
    if life - bid > quiet:
        return bid
    return floor


def choose_scry_arrangement(
    game: Game, caster_index: int, top_count: int,
    library_index: int | None = None,
) -> tuple[list[int], int]:
    """Decide a scry (CR 701.22a): the arrangement, and how many go to the bottom.

    Returns ``(card_order, bottom_count)`` in the shape ``_resolve_scry`` takes —
    a permutation of ``range(top_count)`` reading top-first, and how many of its
    trailing entries go to the bottom.

    Scored by ``_score_tutor_choice`` unchanged, because "how good would drawing
    this be for me" is exactly the scry question and a second scoring function
    would be a second opinion about the same thing. A card scoring below zero is
    worse than an unknown card, so those go to the bottom; the rest are ordered
    best-first so the best one is drawn next. Deterministic given the library,
    which the AI-behaviour regression tests require.
    """
    # Whose library is being looked through, which is not always the chooser's
    # (Coral Fighters looks at the defending player's). The score below asks
    # "how good would drawing this be **for its owner**", so over somebody
    # else's pile the answer is negated: a card that would help them is one to
    # bury, and keeping the scoring function and flipping its sign is what
    # stops this becoming a second opinion about the same question.
    owner_index = caster_index if library_index is None else int(library_index)
    sign = 1.0 if owner_index == caster_index else -1.0
    owner = game.players[owner_index]
    scored = [
        (index, sign * _score_tutor_choice(game, owner_index, card))
        for index, card in enumerate(owner.library[:top_count])
    ]
    kept = sorted((s for s in scored if s[1] >= 0.0), key=lambda item: item[1], reverse=True)
    bottomed = sorted((s for s in scored if s[1] < 0.0), key=lambda item: item[1], reverse=True)
    return [index for index, _ in kept] + [index for index, _ in bottomed], len(bottomed)


def _target_change_side(game: Game, item) -> str | None:
    """Whose side the object's controller wanted its target on — "opponent"
    for an effect that hampers what it targets, "you" for one that helps —
    or None where the compiled program does not say.

    The same readers every other aiming decision here uses
    (``spell_target_side`` for a spell, ``ability_target_side`` /
    ``activation_target_side`` for an ability), so "which way does this effect
    cut" has one answer whether the seat is choosing the target or changing it.
    """
    from .ai_target_sides import activation_target_side

    instruction = getattr(item, "ability_instruction", None)
    if instruction is not None:
        return ability_target_side(instruction) or activation_target_side(instruction)
    if getattr(item, "is_ability", False):
        return None
    from .text_changes import spell_text_card

    spell = spell_text_card(item)
    side = spell_target_side(spell)
    if side is not None:
        return side
    # A spell whose steps carry no ``targets`` description for that reader
    # ("any target", Lightning Bolt) is still read by its instruction's family,
    # exactly as an ability of the same effect is one branch up. An instant or
    # sorcery only: a permanent spell's instructions are a mirror of what the
    # permanent does, not a program the spell runs.
    printed_types = (spell.type_line or "").lower()
    if "instant" not in printed_types and "sorcery" not in printed_types:
        return None
    executed = game._select_executable_instruction(
        spell, getattr(item, "chosen_mode_index", None)
    )
    if executed is None:
        return None
    return ability_target_side(executed) or activation_target_side(executed)


def choose_target_change(game: Game, seat: int, item, slots) -> "list | None":
    """What a non-interactive *seat* does when it "may change the target or
    targets" of *item* (Psychic Battle): the picks, one per slot, or None to
    leave them as they are.

    The stated policy, and it is one sentence: **move harm off my side, move
    help onto it, and otherwise leave it.**

    * an effect its controller aimed to *hurt* (the program's side is
      "opponent") that points at this seat or something it controls is moved —
      to the controller's own side where a legal target is there, else to any
      target that is not this seat's;
    * an effect aimed to *help* (side "you") that somebody else controls and
      that is not already on this seat's side is moved onto it;
    * everything else — an effect with no derivable side, a harmful one
      already pointing elsewhere, this seat's own helpful one — is left alone.

    **One target only.** CR 115.7a makes a change all-or-nothing, so moving a
    several-target effect means accepting a new target for every slot, and
    whether that is a gain is a trade this policy does not price — "make no
    trades", the rule ``_default_optional_pay`` already keeps.

    Deterministic: candidates are taken in the order the enumeration lists
    them, which is board order.
    """
    if len(slots) != 1:
        return None
    slot = slots[0]
    if slot.current.kind not in ("player", "permanent"):
        return None
    side = _target_change_side(game, item)
    if side is None:
        return None

    def controller_of(target) -> int | None:
        if target.kind == "player":
            return target.seat
        if target.kind != "permanent":
            return None
        permanent = game.permanent_by_id(target.permanent_id)
        return None if permanent is None else game.controller_index_of(permanent)

    candidates = [
        candidate for candidate in slot.candidates
        if candidate.kind in ("player", "permanent")
    ]
    mine = controller_of(slot.current) == seat
    if side == "opponent":
        if not mine:
            return None
        elsewhere = [c for c in candidates if controller_of(c) != seat]
        back_at_them = [c for c in elsewhere if controller_of(c) == item.caster_index]
        pick = (back_at_them or elsewhere or [None])[0]
        return None if pick is None else [pick]
    if side == "you":
        if mine or item.caster_index == seat:
            return None
        onto_mine = [c for c in candidates if controller_of(c) == seat]
        return [onto_mine[0]] if onto_mine else None
    return None


def exchange_picks(game: Game, player_index: int, candidates, payload: dict, context) -> list:
    """What a seat nobody asks names for one side of an **exchange of
    control** — "Choose any number of creatures target player controls.
    Choose the same number of creatures another target player controls.
    Those players exchange control of those creatures." (Cultural Exchange,
    CR 701.12) — out of *candidates* (the permanents that side may name).

    Read off the program, as ``order_discard`` reads Strongarm Tactics': the
    first pick carries the next one as ``matched_by`` and the second carries
    ``same_number_as``. A side the seat controls is given away **cheapest
    first**, a side another seat controls is taken **dearest first**
    (``ai_standing.permanent_worth``, the board as it will be once the turn
    is over). The first pick's count is how many pairs gain the seat — its
    dearest take against its cheapest gift, then the next pair, while each
    gains; none where it is a party to neither side, or nothing gains. The
    second pick's count is the first's, which the step itself fixes.

    The prompt's standing answer to "any number" here was none, so a seat
    nobody asks resolved a cast that exchanged nothing — and the rehearsal,
    reading that, never proposed one (kg3).
    """
    from .ai_standing import permanent_worth

    def worth(permanent) -> float:
        return permanent_worth(permanent, now=False)

    def ordered(side) -> list:
        side = list(side)
        mine = bool(side) and all(game.controls(player_index, perm) for perm in side)
        return sorted(side, key=worth) if mine else sorted(side, key=lambda perm: -worth(perm))

    if payload.get("same_number_as") is not None:
        wanted = len((getattr(context, "results", None) or {}).get(str(payload["same_number_as"])) or ())
        return ordered(candidates)[:wanted]
    matched = payload.get("matched_by")
    if not isinstance(matched, dict):
        return []
    from .handlers.permanent_choices import _matched_candidates

    first = list(candidates)
    second = list(_matched_candidates(game, matched, context))
    own_first = bool(first) and all(game.controls(player_index, perm) for perm in first)
    own_second = bool(second) and all(game.controls(player_index, perm) for perm in second)
    if own_first == own_second:
        return []
    gifts, takes = (ordered(first), ordered(second)) if own_first else (ordered(second), ordered(first))
    count = 0
    for gift, take in zip(gifts, takes):
        if worth(take) <= worth(gift):
            break
        count += 1
    return ordered(first)[:count]


def order_discard(game: Game, player_index: int, slots, source_card) -> list[int]:
    """*slots* (hand positions) in the order a seat nobody asks discards them.

    The order given — the worth order ``ai_prompt_picks.discard_order``
    hands it — **except** where the sentence behind the discard tests which
    card went (``ai_prompt_readers.discard_spares_a_penalty``): "…each player
    who didn't discard a creature card this way loses 4 life" (Strongarm
    Tactics) puts the cards that spare the penalty first, and the plain test
    puts the cards that incur it last. Stable, so the given order still
    breaks every tie — a preference, never a filter: a seat holding no such
    card still discards.
    """
    from .ai_prompt_readers import discard_spares_a_penalty
    from .handlers._filters import _card_matches_filter

    order = list(slots)
    tested = discard_spares_a_penalty(source_card)
    if tested is None:
        return order
    described, negated = tested
    player = game.players[player_index]

    def spares(slot: int) -> bool:
        matches = bool(_card_matches_filter(
            player.hand[slot], described, game=game, owner=player,
        ))
        return matches == negated

    return sorted(order, key=lambda slot: not spares(slot))


def order_hand_pick(
    game: Game, player_index: int, candidates, payload: dict, source_card
) -> list[int]:
    """*candidates* (hand slots) in the order a seat nobody asked should pick
    them for a "choose a card in your hand" (`_default_choose_cards_in_hand`).

    Unchanged — hand order, the stated default — unless the program behind the
    pick puts the picked card onto the battlefield for its owner
    (``ai_valuation.hand_pick_entry_consumer``). Then the cards that sentence
    admits come first, and among them the one at its superlative's extreme:
    "with the **lowest** mana value" enters only the lowest, so the cheapest
    admitted card is the pick that can win the comparison. Everything else
    keeps its hand order behind them.
    """
    from .ai_valuation import hand_pick_entry_consumer
    from .handlers._filters import _card_matches_filter

    order = list(candidates)
    if (payload or {}).get("shown_to_opponent"):
        # "Target player reveals three cards from their hand and you choose
        # one of them. That player discards that card." (Blackmail.) The cards
        # shown are the ones an opponent then picks among for a discard, so a
        # seat nobody asks shows its least costly — mana value, the ranking
        # that opponent's own default pick reads (the costliest legal card).
        hand = game.players[player_index].hand
        return sorted(order, key=lambda slot: (int(hand[slot].cmc or 0), slot))
    key = str((payload or {}).get("result_key") or "chosen_hand_cards")
    consumer = hand_pick_entry_consumer(source_card, key) if source_card else None
    if consumer is None:
        return order
    player = game.players[player_index]
    admitted = [
        slot for slot in order
        if _card_matches_filter(
            player.hand[slot], consumer["card_filter"], game=game, owner=player
        )
    ]
    guard = consumer.get("guard")
    if guard:
        # "…then put that card onto the battlefield **if it has the same name
        # as a permanent**" (Retraced Image): a pick the guard refuses enters
        # nothing, so the ones it admits go first. Asked of the engine's own
        # evaluator with the pick as the record the guard reads — the policy
        # and the resolution cannot disagree about what the guard means.
        from .game_types import OracleExecutionContext
        from .handlers.control_flow import evaluate_condition

        def holds(slot: int) -> bool:
            context = OracleExecutionContext(
                caster=player, target=player, card=source_card,
                results={key: [player.hand[slot]]},
            )
            return bool(evaluate_condition(game, context, guard))

        admitted = [slot for slot in admitted if holds(slot)]
    superlative = consumer["superlative"]
    if superlative.get("characteristic") == "mana_value":
        sign = 1 if superlative.get("extreme") == "least" else -1
        admitted.sort(key=lambda slot: (sign * int(player.hand[slot].cmc or 0), slot))
    return admitted + [slot for slot in order if slot not in admitted]


def choose_amount_paid(game: Game, choice) -> int:
    """How much mana a seat nobody asks pays into "you may pay {X}" (Hollow
    Specter, CR 107.3f) or "may pay any amount of mana" (Liege of the
    Hollows) — the ``pay_any_amount`` prompt *choice*.

    **The most the board can pay, up to what the amount can buy**
    (:func:`_amount_worth_paying`), read off the sentence that spends the
    record the payment writes (``MANA_PAID_BY_SEAT``): "that player reveals X
    cards from their hand and you choose one of them" buys one more card to
    choose from per mana up to the size of that hand — public information
    (CR 402.3), whatever its cards are — and "creates a number of … tokens
    equal to the amount of mana they paid" buys a token per mana, and "search
    your library for an Equipment card with mana value X or less" (Taj-Nar
    Swordsmith) a wider search per mana. A sentence
    this does not read buys nothing it can price, so it pays nothing, the
    prompt's stated default. Always 0 where the board pays nothing.

    The prompt is answered part-way through the resolution that armed it,
    where no rehearsal can be run (``ai_scratch_copy.mid_resolution``), so the
    answer is read, not measured. Mana spent here is not kept for the rest
    of the turn; a seat holding a spell for its second main phase is the
    case this does not weigh.
    """
    from .mana_payment import generic_cost

    worth = _amount_worth_paying(game, choice)
    if worth == 0:
        return 0
    seat = choice.player_index
    player = game.players[seat]
    lands = game.payment_lands(seat)
    # Walked up, as the browser's renderer of this prompt walks it: the
    # resolver accepts exactly what `plan_payment` can pay.
    limit = sum(max(0, int(v)) for v in player.mana_pool.values()) + 2 * len(lands)
    if worth is not None:
        limit = min(limit, worth)
    if isinstance(choice.data.get("maximum"), int):
        limit = min(limit, choice.data["maximum"])  # the printed ceiling (Well of Lost Dreams)
    affordable = 0
    for amount in range(1, limit + 1):
        if game.effect_payment_plan(player, generic_cost(amount), lands=lands) is None:
            break
        affordable = amount
    return affordable


def _amount_worth_paying(game: Game, choice) -> "int | None":
    """What the amount paid into *choice* can buy at most: a number, None
    for no ceiling but the board's, or 0 for nothing this policy can price.

    Read off the steps of the resolving object that take their number from
    the payment's record: an X (``x_from_count``'s ``own_seat_record``,
    Hollow Specter) or a count (``count``'s ``seat_record``, Liege of the
    Hollows' Squirrels)."""
    from .ai_weighed_cast import _effect_steps
    from .oracle_types import MANA_PAID_BY_SEAT

    # The prompt's own stamp, or — for a seat nobody asks, whose default is
    # taken as the prompt is armed, before anything is stamped on it — the
    # object resolving now (`Game.resolving_items`, pushed for every
    # resolution; `resolving_stack_item` only for one that may pause).
    item = choice.data.get("_stack_item") or game.resolving_stack_item or (
        game.resolving_items[-1] if getattr(game, "resolving_items", None) else None
    )
    instruction = getattr(item, "ability_instruction", None)
    if instruction is None:
        return 0
    seat = choice.player_index
    worth: "int | None" = 0
    for step in _effect_steps(instruction):
        payload = step.payload or {}
        count = payload.get("count")
        records = {
            (payload.get("x_from_count") or {}).get("own_seat_record"),
            count.get("seat_record") if isinstance(count, dict) else None,
        }
        if MANA_PAID_BY_SEAT not in records:
            continue
        if step.kind == "reveal_hand_and_choose" and payload.get("revealer_shows") == "x":
            # "…that player reveals X cards from their hand and you choose one
            # of them. That player discards that card." Worth a card per mana
            # up to the size of an opponent's hand; nothing aimed at the payer.
            victim = _revealing_seat(item, payload)
            if (
                victim is None or victim == seat
                or payload.get("fate") != "discard"
            ):
                continue
            return len(game.players[victim].hand)
        if step.kind == "search_library" and (
            ((payload.get("restrictions") or {}).get("mana_value") or {}).get("value")
            == "x"
        ):
            # "…you may pay {X}. If you do, search your library for an
            # Equipment card with mana value X or less…" (Taj-Nar Swordsmith).
            # Each mana widens the search; the library is hidden (CR 401.2),
            # so the policy reads no card in it and puts no ceiling on the
            # amount but the board's.
            worth = None
            continue
        if step.kind == "draw_controller_cards":
            # "…you may pay {X}. If you do, draw X cards." (Well of Lost
            # Dreams.) A card per mana for the payer, short of emptying the
            # library it draws from.
            return max(0, len(game.players[seat].library) - 1)
        if step.kind == "create_token" and payload.get("recipient_players") in (
            None, "each_player",
        ):
            # A token per mana, made for the seat that paid it ("each player
            # creates a number of … tokens equal to the amount of mana they
            # paid"): no ceiling but the board's.
            worth = None
    return worth


def _revealing_seat(item, payload: dict) -> "int | None":
    """The seat a ``reveal_hand_and_choose`` step's "that player" names on
    *item*: the player the triggering damage was dealt to, frozen on the
    trigger (``trigger_context``), as the handler reads it."""
    if payload.get("victim") != "damaged_player":
        return None
    seat = (getattr(item, "trigger_context", None) or {}).get("defending_player_index")
    return seat if isinstance(seat, int) else None

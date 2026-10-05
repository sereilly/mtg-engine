"""What mana a board "could produce" (CR 106.7).

Printed cards ask this question of a *set* of permanents rather than of one
named object:

* "Add one mana of any **type that a land you control** could produce."
  (Reflecting Pool.)
* "Add one mana of any **color that a land an opponent controls** could
  produce." (Fellwar Stone, Quirion Explorer, Exotic Orchard's mirror.)
* "Add one mana of any color that a **basic** land you control could produce."
  (Star Compass.)

The naive reading is a union of ``Permanent.effective_produced_mana`` over the
lands, and it is wrong in the direction that makes the card strictly better than
the one printed. Scryfall records Reflecting Pool's own ``produced_mana`` as all
five colours, so a lone Reflecting Pool would tap for anything. CR 106.7 says
the opposite: a permanent's "could produce" set is what an ability of *that*
permanent would produce if it resolved now, and "if that permanent wouldn't
produce any mana under these conditions, or no type of mana can be defined this
way, there's no type of mana it could produce." The rule's own example is this
family:

    Exotic Orchard has the ability "{T}: Add one mana of any color that a land
    an opponent controls could produce." If your opponent controls no lands,
    activating Exotic Orchard's mana ability will produce no mana. The same is
    true if you and your opponent each control no lands other than Exotic
    Orchards. However, if you control a Forest and an Exotic Orchard, and your
    opponent controls an Exotic Orchard, then each Exotic Orchard could produce
    {G}.

So the answer is a **fixpoint**, not a scan: a derived land contributes whatever
the lands it reads contribute, and two derived lands reading each other
contribute nothing. :func:`lands_could_produce` computes it once for every land
on the battlefield, and every printed phrase reads it through
:func:`mana_lands_could_produce` — one reader, so two cards cannot disagree
about a board they can both see.

**Three words of the phrase are data, and each used to be a sentence.** *Whose*
lands (the board), *which* of them (a narrowing: "basic"), and *what of theirs*
(a colour, or CR 106.1b's wider "type"). This module matched two literal
sentences and its grammar twin matched the same two, so a card differing by one
adjective refused its whole line. The phrase is read once now — by the grammar,
into the instruction's payload — and what a *land* reads is taken off its
compiled program (:func:`derived_productions`) rather than off a second regex
that would have to learn every narrowing the noun reader already knows.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The payload key under which an add-mana instruction carries *which* of the
#: board's lands its "could produce" phrase names — a subject-filter payload
#: (``{"supertypes": ["basic"]}``), absent when the phrase names them all.
#: Written by ``engine/grammar/lowering/mana.py`` and read here and by the
#: handler through here; named once so the three cannot come to disagree.
LANDS_FILTER_KEY = "could_produce_lands"

#: The boards a "could produce" phrase can name. The two payload keys that carry
#: one — ``any_color_from`` and ``any_type_from_lands`` — hold one of these.
BOARDS: frozenset[str] = frozenset({"controlled_lands", "opponent_lands"})

#: CR 106.1b's six types: the five colours and colourless. "Colour" is the
#: subset a phrase printing the word *color* names, and the difference is the
#: whole reason Reflecting Pool and Fellwar Stone cannot share a branch — a land
#: tapping for {C} answers the first and not the second.
COLORS = frozenset("WUBRG")


@dataclass(frozen=True)
class DerivedProduction:
    """One printed "…that a land … could produce" clause, as the question it
    asks: *whose* lands, *which* of them, and whether the answer is narrowed to
    the five colours (the printed word was "color") or is all six of CR
    106.1b's types (it was "type")."""

    board: str
    colors_only: bool
    narrowing: "dict | None" = None


def derived_production(instruction) -> DerivedProduction | None:
    """The "could produce" clause *instruction* carries, or None.

    Read off the payload of one add-mana step. Both board keys are looked at
    because the two printed words put the board under different ones, and a
    value outside :data:`BOARDS` is no clause this can answer.
    """
    payload = getattr(instruction, "payload", None) or {}
    narrowing = payload.get(LANDS_FILTER_KEY) or None
    board = payload.get("any_color_from")
    if board in BOARDS:
        return DerivedProduction(str(board), True, narrowing)
    board = payload.get("any_type_from_lands")
    if board in BOARDS:
        return DerivedProduction(str(board), False, narrowing)
    return None


def derived_productions(card) -> tuple[DerivedProduction, ...]:
    """Every "could produce" clause among *card*'s mana abilities.

    Empty is the ordinary permanent, whose ``produced_mana`` says what it
    makes. Asked of the **compiled program**, wrappers opened, so a derived
    production behind a drawback ("Add …. This land deals 1 damage to you.")
    is still one, and so the narrowing a phrase prints is the grammar's
    reading of it rather than a second one made here.
    """
    from .mana_payment import _every_nested_step
    from .oracle import compile_card_oracle

    found: list[DerivedProduction] = []
    for ability in compile_card_oracle(card).activated_abilities:
        instruction = ability.instruction
        if instruction is None or not ability.supported:
            continue
        for step in (instruction, *_every_nested_step(instruction)):
            production = derived_production(step)
            if production is not None:
                found.append(production)
    return tuple(found)


def _stated_symbols(card) -> set[str]:
    """The symbols *card*'s mana abilities name outright — every add-mana step
    that is not itself a "could produce" clause."""
    from .ai_valuation import mana_ability_symbols
    from .mana_payment import _every_nested_step, is_mana_ability
    from .oracle import compile_card_oracle

    stated: set[str] = set()
    for ability in compile_card_oracle(card).activated_abilities:
        instruction = ability.instruction
        if instruction is None or not ability.supported:
            continue
        if not is_mana_ability(ability):
            continue
        for step in (instruction, *_every_nested_step(instruction)):
            if step.kind == "add_mana_from_text" and derived_production(step) is None:
                stated |= {
                    str(symbol).upper()
                    for symbol in mana_ability_symbols(step)
                }
    return stated


def _color_choice_amongs(card) -> tuple[dict, ...]:
    """The ``among`` filters of every narrowed colour choice *card*'s mana
    abilities make for their own controller — "Choose a color **of a permanent
    you control**. Add one mana of that color." (Meteor Crater.)

    The other shape whose colours the board defines, and not a "could produce"
    clause: it reads permanents' *colours*, never another land's production,
    so it takes no part in the fixpoint and is answered outright.
    """
    from .mana_payment import _every_nested_step, is_mana_ability
    from .oracle import compile_card_oracle

    found: list[dict] = []
    for ability in compile_card_oracle(card).activated_abilities:
        instruction = ability.instruction
        if instruction is None or not ability.supported or not is_mana_ability(ability):
            continue
        for step in (instruction, *_every_nested_step(instruction)):
            payload = step.payload or {}
            if step.kind == "choose_color" and payload.get("among") and not payload.get("chooser"):
                found.append(payload["among"])
    return tuple(found)


def _colors_chosen_among(game, seat: int, source, amongs) -> set[str]:
    """Every colour the narrowed choices *amongs* would offer *seat* now."""
    from .object_colors import colors_among_described

    offered: set[str] = set()
    for described in amongs:
        offered.update(
            colors_among_described(game, described, observer=seat, source=source)
        )
    return offered


def derived_producer_board(card) -> str | None:
    """Which board *card*'s own mana production is derived from, or None.

    None is the ordinary land, whose ``produced_mana`` says what it makes. The
    first clause's board where a card prints several; the fixpoint below reads
    every one.
    """
    productions = derived_productions(card)
    return productions[0].board if productions else None


def _on_board(game, board: str, seat: int, land_seat: int) -> bool:
    """Whether a land *land_seat* controls is on the *board* a clause read by
    *seat* names. CR 109.5: "you" and "an opponent" are relative to the
    controller of the permanent whose ability this is."""
    if board == "controlled_lands":
        return land_seat == seat
    return land_seat in game.opponents_of(seat)


def lands_could_produce(game) -> dict[int, frozenset[str]]:
    """CR 106.7's answer for every land on the battlefield: the mana types it
    could produce, as upper-case symbols, keyed by ``permanent_id``.

    Through the control seam, because "controls" is a seat question (CR 109.5)
    and ``player.battlefield`` is only a projection of it — and through
    ``has_type``, so an animated land still counts and a permanent that stopped
    being one does not (CR 613 layer 4).

    The loop is the fixpoint the rule's example describes. A derived land
    contributes the union of the lands it *reads*; recomputing until nothing
    changes is what makes "you control a Forest and an Orchard, your opponent
    controls an Orchard" come out at {G} for both Orchards, and what makes two
    Orchards facing each other with no other land come out empty. It terminates
    because the sets only grow and there are six types.

    **A land whose type an effect has set is not derived, whatever it prints**
    (CR 305.7): it has lost the ability that read a board and gained the basic
    one, which ``effective_produced_mana`` already answers — a Reflecting Pool
    under Blood Moon could produce {R}, and reads nobody.
    """
    from .land_types import lost_abilities_to_type_change
    from .subject_filters import subject_matches

    lands: list[tuple[int, object]] = []
    answer: dict[int, set[str]] = {}
    derived: dict[int, tuple[int, object, tuple[DerivedProduction, ...]]] = {}
    for seat in range(len(game.players)):
        for perm in game.controlled_by(seat):
            if not perm.has_type("land"):
                continue
            lands.append((seat, perm))
            productions = (
                () if lost_abilities_to_type_change(perm)
                else derived_productions(perm.effective_card)
            )
            if productions:
                derived[perm.permanent_id] = (seat, perm, productions)
                # What the land says outright, beside what it derives: a land
                # printing "{T}: Add {C}." above a derived clause could produce
                # {C} on an empty board. Read off its other mana abilities
                # rather than off ``produced_mana``, which for a derived land
                # is Scryfall's list of everything the clause could ever name.
                answer[perm.permanent_id] = _stated_symbols(perm.effective_card)
                continue
            amongs = (
                () if lost_abilities_to_type_change(perm)
                else _color_choice_amongs(perm.effective_card)
            )
            if amongs:
                # Meteor Crater's shape: what it could produce is a colour of a
                # permanent its controller has *now*, and with none it could
                # produce nothing — where its printed summary says all five,
                # which an opponent's Quirion Explorer or Fellwar Stone would
                # then read as five colours on offer.
                answer[perm.permanent_id] = _stated_symbols(
                    perm.effective_card
                ) | _colors_chosen_among(game, seat, perm, amongs)
            else:
                answer[perm.permanent_id] = {
                    str(symbol).upper() for symbol in perm.effective_produced_mana
                }

    changed = bool(derived)
    while changed:
        changed = False
        for land_id, (seat, perm, productions) in derived.items():
            for production in productions:
                contributed: set[str] = set()
                for other_seat, other in lands:
                    if not _on_board(game, production.board, seat, other_seat):
                        continue
                    if production.narrowing and not subject_matches(
                        game, other, production.narrowing,
                        observer=seat, source=perm,
                    ):
                        continue
                    contributed |= answer[other.permanent_id]
                if production.colors_only:
                    contributed &= COLORS
                if not contributed <= answer[land_id]:
                    answer[land_id] |= contributed
                    changed = True
    return {land_id: frozenset(types) for land_id, types in answer.items()}


def could_produce_by_seat(game) -> dict[int, frozenset[str]]:
    """:func:`lands_could_produce` folded per seat: the mana types the lands
    that seat controls could produce."""
    by_land = lands_could_produce(game)
    return {
        seat: frozenset().union(
            *(
                by_land.get(perm.permanent_id, frozenset())
                for perm in game.controlled_by(seat)
            )
        )
        for seat in range(len(game.players))
    }


def mana_lands_could_produce(
    game,
    seat: int,
    board: str,
    *,
    colors_only: bool,
    narrowing: "dict | None" = None,
    source=None,
) -> frozenset[str]:
    """What a "…that a land … could produce" clause offers *seat*: the union,
    over the lands on *board* that *narrowing* admits, of what each could
    produce — narrowed to the five colours when the printed word was "color".

    The one reader every printed spelling goes through. *narrowing* is asked of
    ``subject_matches``, so "basic" is the supertype the layers give the land
    now (CR 205.4a) and not the word on its card; *source* is the permanent
    whose ability this is, for a narrowing that names it.

    Empty is a real answer and the card's own: no land on the board, or none
    the phrase admits, and the ability produces no mana (CR 106.7).
    """
    from .subject_filters import subject_matches

    by_land = lands_could_produce(game)
    types: set[str] = set()
    for land_seat in range(len(game.players)):
        if not _on_board(game, board, seat, land_seat):
            continue
        for perm in game.controlled_by(land_seat):
            if not perm.has_type("land"):
                continue
            if narrowing and not subject_matches(
                game, perm, narrowing, observer=seat, source=source
            ):
                continue
            types |= by_land.get(perm.permanent_id, frozenset())
    return frozenset(types & COLORS if colors_only else types)


#: The order an offered list is returned in: CR 105.1's WUBRG, then colourless.
_OFFER_ORDER: tuple[str, ...] = ("W", "U", "B", "R", "G", "C")


def ability_colors_on_offer(game, permanent, instruction) -> "tuple[str, ...] | None":
    """What a mana ability of *permanent* could add **right now**, where the
    board decides — or None for an ability nothing about the board narrows.

    Two printed shapes have a colour set the rest of the battlefield defines:
    a "could produce" clause (Reflecting Pool, Exotic Orchard's family), and a
    colour chosen from "a color **of a permanent you control**" (Meteor
    Crater). For both, Scryfall's ``produced_mana`` is every colour the card
    could *ever* make, so a reader that planned a payment or offered a colour
    picker off the summary counted the land as five-colour: the optional-pay
    planner tapped a Reflecting Pool "for" a {B} its board could not define,
    and a Crater beside one red creature offered green.

    Empty is a real answer — the ability is activatable and adds nothing (CR
    106.7) — and is **not** None: a caller must be able to tell "this land
    makes nothing here" from "ask the land itself".

    The seat is the permanent's controller, through the control seam (CR 109.5).
    """
    from .mana_payment import _every_nested_step

    seat = game.controller_index_of(permanent)
    if seat is None or instruction is None:
        return None
    offered: "set[str] | None" = None
    for step in (instruction, *_every_nested_step(instruction)):
        production = derived_production(step)
        if production is not None:
            found = mana_lands_could_produce(
                game, seat, production.board,
                colors_only=production.colors_only,
                narrowing=production.narrowing, source=permanent,
            )
        elif step.kind == "choose_color" and (step.payload or {}).get("among") and not (
            step.payload.get("chooser")
        ):
            found = frozenset(
                _colors_chosen_among(game, seat, permanent, (step.payload["among"],))
            )
        else:
            continue
        offered = set(found) if offered is None else offered | set(found)
    if offered is None:
        return None
    return tuple(symbol for symbol in _OFFER_ORDER if symbol in offered)


def types_a_land_you_control_could_produce(game, seat: int) -> frozenset[str]:
    """"…any type that a land you control could produce." (Reflecting Pool.)"""
    return mana_lands_could_produce(
        game, seat, "controlled_lands", colors_only=False
    )


def colors_a_land_an_opponent_controls_could_produce(
    game, seat: int
) -> frozenset[str]:
    """"…any color that a land an opponent controls could produce." (Fellwar
    Stone.)

    The same fixpoint narrowed to CR 106.1b's five colours, because the printed
    word is *color*: an opponent whose only land taps for {C} offers this card
    nothing.
    """
    return mana_lands_could_produce(
        game, seat, "opponent_lands", colors_only=True
    )


__all__ = [
    "BOARDS",
    "COLORS",
    "DerivedProduction",
    "LANDS_FILTER_KEY",
    "ability_colors_on_offer",
    "colors_a_land_an_opponent_controls_could_produce",
    "could_produce_by_seat",
    "derived_production",
    "derived_productions",
    "derived_producer_board",
    "lands_could_produce",
    "mana_lands_could_produce",
    "types_a_land_you_control_could_produce",
]

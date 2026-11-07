"""Which of the offered things a seat nobody asks picks, by what each is worth.

The prompt defaults in ``mixins/stack/choices`` answer for every seat that is
not asked (``engine/pending_choices.py``'s third part), and sixteen of them
took the first thing offered — the first card in a hand, the first seat, the
first printed mode, the first permanent on a board — with nothing weighed
(kg3's census, ``tests/regressions/test_kg3_choosers_unasked_defaults.py``).
Each reader here is the one a default asks instead, named for its prompt kind,
and each weighs the offer from the seat choosing:

* **a card** — what it is worth to hold (``ai_scoring._score_tutor_choice``,
  the reading a search's find is weighed by: a card put back, discarded,
  found or returned to a hand), what it is worth on the battlefield
  (``ai_rehearsal.permanent_worth`` over the card as printed, read for what
  lasts: a card put onto the battlefield, face down or up), or its mana value
  where the chooser must not read what the card is worth to somebody else's
  hand (a divider's piles);
* **a permanent** — ``permanent_worth`` / ``permanent_loss``, on the side the
  effect wants (``ai_target_sides``);
* **a seat** — which one the sentence behind the choice harms or hands
  something, read off the compiled program;
* **a mode or a vocabulary** — rehearsed (``ai_rehearsal.rehearse``), each
  answer carried out on a scratch copy and compared from the chooser's seat.

Every reader breaks ties in the order offered, so a seed still reproduces a
run, and each returns the stated answer's shape — a slot, an id, a seat, an
index — for the default to hand its own resolver. Nothing here moves a card.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from .ai_rehearsal import (deliberating, permanent_loss, permanent_worth,
                           rehearse, rehearsing, seat_standing)
from .ai_scoring import _score_tutor_choice
from .models import CardDefinition, Permanent
from .oracle import compile_card_oracle

#: Under this, two rehearsed answers are the same answer: the standings are
#: sums of floats.
_SAME = 1e-9


class _Answered:
    """The shape a rehearsal reads off an answer that is not a cast."""

    def __init__(self, supported: bool) -> None:
        self.supported = supported
        self.details = "" if supported else "the answer was not taken"


def held_worth(game, seat: int, card: CardDefinition) -> float:
    """What *card* is worth to *seat* to hold: the reading a search's find is
    weighed by (``ai_scoring._score_tutor_choice``) — a spell by what casting
    it would be worth, a land by whether the seat is short of them."""
    return _score_tutor_choice(game, seat, card)


def battlefield_worth(card: CardDefinition) -> float:
    """What *card* is worth as a permanent: ``permanent_worth`` over the card as
    printed, read for what lasts (the reading Dimensional Breach's return
    takes, ``ai_prompts.choose_exiled_card_to_return``)."""
    return permanent_worth(Permanent(card=card), now=False)


def _first_best(candidates, worth):
    """The candidate *worth* ranks highest, the first offered between equals."""
    best, best_worth = None, None
    for candidate in candidates:
        value = worth(candidate)
        if best_worth is None or value > best_worth + _SAME:
            best, best_worth = candidate, value
    return best


# -- Cards out of a hand ------------------------------------------------------


def hand_to_library_picks(game, seat: int, count: int) -> list[int]:
    """The *count* hand slots a seat puts back onto its library ("put two cards
    from your hand on top of your library", Brainstorm; "target player puts
    three cards from their hand on top", Stunted Growth) — the ones it least
    wants to hold — named in the order the answer takes them: the first named
    ends up on top, so of the cards going back the one worth most is drawn
    first. Hand order between equals."""
    hand = game.players[seat].hand
    ranked = sorted(
        range(len(hand)), key=lambda slot: (held_worth(game, seat, hand[slot]), slot),
    )
    going = ranked[:max(0, count)]
    return sorted(going, key=lambda slot: (-held_worth(game, seat, hand[slot]), slot))


def put_from_hand_pick(game, seat: int, live: list[int]) -> int | None:
    """Which eligible hand slot a seat puts onto the battlefield ("…may put an
    artifact, creature, enchantment, or land card from their hand onto the
    battlefield", Metamorphose; Elvish Piper; Eureka): the card worth most as a
    permanent. The first eligible card took a Forest over a Craw Wurm."""
    hand = game.players[seat].hand
    return _first_best(live, lambda slot: battlefield_worth(hand[slot]))


def face_down_cast_pick(game, seat: int, max_cmc: int) -> int | None:
    """Which creature card a seat puts onto the battlefield face down under
    Illusionary Mask ("…a creature card in your hand whose mana value is X or
    less"): the one worth most once it is turned up, which the X already paid
    for. The first creature in hand was the default."""
    hand = game.players[seat].hand
    eligible = [
        slot for slot, card in enumerate(hand)
        if card.primary_type == "creature" and int(card.cmc or 0) <= max_cmc
    ]
    return _first_best(eligible, lambda slot: battlefield_worth(hand[slot]))


def balance_discards(game, seat: int, owed: int) -> list[int]:
    """The *owed* hand slots a seat discards to Balance: the cards it least
    wants to hold, the later slot between equals (the stated policy gave up
    the last slots)."""
    hand = game.players[seat].hand
    ranked = sorted(
        range(len(hand)), key=lambda slot: (held_worth(game, seat, hand[slot]), -slot),
    )
    return sorted(ranked[:max(0, owed)])


def hand_size_discards(game, seat: int, excess: int) -> list[int]:
    """The *excess* hand slots the active player discards down to its maximum
    hand size (CR 514.1) when nobody asks it: first a card with **madness**
    whose madness cost the seat's board can pay (CR 702.35a: discarded, it is
    offered for that cost rather than lost — the card a discard costs least,
    the weight ``ai_abilities._madness_discard_index`` gives a discard cost),
    then the cards it least wants to hold, hand order between equals. The
    first cards in hand were the discard (``hand.pop(0)``), so an AI kept a
    seventh land over a spell."""
    hand = game.players[seat].hand

    def rank(slot: int) -> tuple:
        return (not _madness_is_payable(game, seat, hand[slot]),
                held_worth(game, seat, hand[slot]), slot)

    return sorted(sorted(range(len(hand)), key=rank)[:max(0, excess)])


def _madness_is_payable(game, seat: int, card: CardDefinition) -> bool:
    from .board_payment import board_can_pay
    from .madness import printed_madness_cost
    from .mana_payment import mana_cost_from_symbols

    madness = printed_madness_cost(card)
    if madness is None:
        return False
    if not game.enforce_mana_costs:
        return True
    return board_can_pay(game, seat, mana_cost_from_symbols(madness) or {})


def balance_sacrifices(game, seat: int, candidates, owed: int) -> list[int]:
    """The *owed* slots of *candidates* — ``(slot, permanent)`` pairs a Balance
    round counts — a seat sacrifices: the ones whose loss costs it least
    (``ai_rehearsal.permanent_loss``), then the land that makes fewest
    colours (:func:`mana_breadth`), the later slot between equals."""
    ranked = sorted(
        candidates,
        key=lambda pair: (
            permanent_loss(game, seat, pair[1]), mana_breadth(game, pair[1]), -pair[0],
        ),
    )
    return sorted(slot for slot, _perm in ranked[:max(0, owed)])


def mana_breadth(game, permanent) -> int:
    """How many different symbols tapping *permanent* can put in its
    controller's pool when it is a land — the payment planner's own answer
    (``Game._land_payment_colors``) — what tells a dual land from a basic,
    which ``permanent_worth`` prices alike; 0 for anything else."""
    if not permanent.has_type("land"):
        return 0
    return len(set(game._land_payment_colors(permanent) or ()))


# -- Cards out of a pile ------------------------------------------------------


#: Where a looked-at card a chooser names goes that is a **loss** to the pile's
#: owner — the card put out of reach rather than kept.
_LOOK_TOP_LOSSES = frozenset({"exile", "graveyard", "library_bottom"})


def look_top_pick(
    game, chooser: int, pile_seat: int, pile: list, eligible: list[int], destination: str,
) -> int | None:
    """Which looked-at position a chooser names for *destination* ("look at
    the top four cards … put one of them into your hand", Impulse; "…exile one
    of those cards", Sealed Fate; "you choose two of those cards and put them
    into their graveyard", Bamboozle; "…puts one of them back on top",
    Ashnod's Cylix; "…put one of those cards on the bottom", Preferred
    Selection).

    Out of the chooser's own library, into its hand or back on top: the card
    it most wants to hold; out of reach (a graveyard, an exile, the bottom):
    the one it least wants. Out of **another** seat's library the choice is
    made against that seat: the dearest card put out of its reach, the
    cheapest left in its hand or on its top — dearest by what the card is on
    a battlefield (:func:`battlefield_worth`), not by what it is worth in a
    hand the chooser cannot see. The first eligible card was the answer."""
    if not eligible:
        return None
    lost = destination in _LOOK_TOP_LOSSES
    if pile_seat == chooser:
        sign = -1.0 if lost else 1.0
        return _first_best(eligible, lambda index: sign * held_worth(game, chooser, pile[index]))
    sign = 1.0 if lost else -1.0
    return _first_best(eligible, lambda index: sign * battlefield_worth(pile[index]))


def pile_search_pick(game, seat: int, pile: list) -> int | None:
    """Which card of the kept pile a seat takes into its hand (Phyrexian
    Portal's search): the one it most wants to hold, as a library search's
    find is chosen (``ai_prompts.choose_search_card``)."""
    return _first_best(range(len(pile)), lambda index: held_worth(game, seat, pile[index]))


def library_pile_split(cards: list) -> list[int]:
    """How a divider splits *cards* — the top of **another** seat's library —
    into the two face-down piles of which that seat exiles one and searches the
    other (Phyrexian Portal): the positions of the first pile.

    Even sizes, so the searcher, who sees only how many cards each pile holds,
    learns nothing from them; and the dearer half together, so that whichever
    pile it keeps, half the time it is choosing among the weakest cards rather
    than always among a random half — never worse for the divider than the
    split in library order, and against a searcher that exiles the first of
    two equal piles (``_default_pile_exile_choice``) the dearer half is the
    pile exiled. Dearer by mana value, the one ranking a card answers without
    the divider reading what it is worth in a hand it cannot see."""
    half = len(cards) // 2
    ranked = sorted(range(len(cards)), key=lambda index: (-int(cards[index].cmc or 0), index))
    return sorted(ranked[:half])


def linked_exile_return_pick(game, seat: int, entries, live: list[int], zone: str) -> int | None:
    """Which entry of a permanent's linked-exile pile a seat returns ("Return a
    card you own exiled with Gustha's Scepter to your hand"; "…return a card
    exiled with Purgatory to the battlefield"): to a hand, the card it most
    wants to hold; to the battlefield, the card worth most as a permanent."""
    if zone == "battlefield":
        return _first_best(live, lambda index: battlefield_worth(entries[index]["card"]))
    return _first_best(live, lambda index: held_worth(game, seat, entries[index]["card"]))


# -- Word of Command ----------------------------------------------------------


def word_of_command_pick(game, target_index: int) -> int | None:
    """Which card in the target's hand the caster of Word of Command makes it
    play: the one that does the target least good.

    The forced spell names its own caster where it names a player
    (``_finish_word_of_command`` queues it with ``target_player_index`` the
    target's own seat), so a spell that harms the player it names
    (``ai_target_sides.spell_seat_side``: a burn, a discard) is turned on the
    target — those first, the dearest first. Then a land, a land drop at
    most. Then everything else, the cheapest first: the least the target can
    be handed. The first card in the hand was the default."""
    from .ai_target_sides import spell_seat_side
    from .targeting import derive_cast_spec, spec_offers_a_player

    hand = game.players[target_index].hand

    def rank(slot: int) -> tuple:
        card = hand[slot]
        if card.primary_type == "land":
            return (1, 0, slot)
        # The forced play is a cast from the hand announcing no mode
        # (``queue_from_hand`` names none).
        spec = derive_cast_spec(
            card, compile_card_oracle(card), from_zone="hand", mode_index=None,
        )
        if spec_offers_a_player(spec) and spell_seat_side(card) == "opponent":
            return (0, -int(card.cmc or 0), slot)
        return (2, int(card.cmc or 0), slot)

    return min(range(len(hand)), key=rank) if hand else None


# -- Permanents ---------------------------------------------------------------


def untap_up_to_order(game, seat: int, permanents: list) -> list:
    """*permanents* — a seat's own tapped permanents an "untap up to N" may name
    (Frantic Search's lands, Mudslide's creatures) — in the order it untaps
    them: the dearest first, read for what lasts (a tapped creature is worth
    less only until it untaps), then the land that makes the most colours
    (:func:`mana_breadth`: a Tundra before a Plains), board order between
    equals."""
    return sorted(
        permanents,
        key=lambda perm: (-permanent_worth(perm, now=False), -mana_breadth(game, perm)),
    )


def _wanted_side(game, chooser: int, side: str | None) -> set:
    if side == "opponent":
        return set(game.opponents_of(chooser))
    if side == "you":
        return {chooser}
    return set()


def reflexive_target_order(game, chooser: int, steps, offered: list) -> list:
    """*offered* — a reflexive trigger's candidates, ``{seat, permanent_id, …}``
    — in the order a seat nobody asks aims it ("When you do, you may tap or
    untap target creature", Tolarian Kraken).

    A toggle by the state it changes (``ai_target_sides.toggle_target_order``:
    an opponent's untapped creature, then one of the chooser's own tapped
    ones); any other effect on the side it wants (``ability_target_side``),
    the dearest permanent there first; the offer's order where the effect
    says nothing."""
    from .ai_target_sides import (ability_target_side, toggle_target_order,
                                  toggles_its_target)
    from .oracle_types import OracleInstruction

    wrapped = OracleInstruction("sequence", "", {"steps": tuple(steps or ())})
    by_id = {
        entry.get("permanent_id"): game.permanent_by_id(entry.get("permanent_id"))
        for entry in offered
    }
    live = [entry for entry in offered if by_id.get(entry.get("permanent_id")) is not None]
    if toggles_its_target(wrapped):
        order = toggle_target_order(game, chooser, [by_id[e["permanent_id"]] for e in live])
        position = {id(perm): place for place, perm in enumerate(order)}
        return sorted(live, key=lambda e: position[id(by_id[e["permanent_id"]])])
    wanted = _wanted_side(game, chooser, ability_target_side(wrapped))
    if not wanted:
        return list(offered)
    return sorted(
        live,
        key=lambda e: (
            e.get("seat") not in wanted,
            -permanent_worth(by_id[e["permanent_id"]]),
        ),
    )


def modal_mode_target_picks(game, chooser: int, item, offered: list, ceiling: int) -> list[int]:
    """The ids a caster names for the mode an opponent chose for its spell (CR
    700.2e, 601.2c: Fatal Lore's "you destroy up to two target creatures that
    player controls"): on the side the mode's effect wants, the dearest first,
    up to the printed ceiling — and none where the mode would hurt the
    caster's own and "up to" lets it name nothing. The candidates in board
    order were the default, so Fatal Lore destroyed whichever two came
    first."""
    from .ai_target_sides import ability_target_side
    from .text_changes import spell_text_card

    # The mode as the spell now reads (CR 612.1: a text change on the stack).
    program = compile_card_oracle(spell_text_card(item))
    index = getattr(item, "chosen_mode_index", None)
    instruction = (
        program.modes[index].instruction
        if isinstance(index, int) and 0 <= index < len(program.modes) else None
    )
    side = ability_target_side(instruction)
    live = [
        entry for entry in offered
        if game.permanent_by_id(entry.get("permanent_id")) is not None
    ]
    if side is None:
        return [entry["permanent_id"] for entry in offered[:ceiling]]
    wanted = _wanted_side(game, chooser, side)
    on_side = [entry for entry in live if entry.get("seat") in wanted]
    ranked = sorted(
        on_side,
        key=lambda entry: -permanent_worth(game.permanent_by_id(entry["permanent_id"])),
    )
    return [entry["permanent_id"] for entry in ranked[:ceiling]]


# -- Seats and casts ----------------------------------------------------------


def _damage_steps(card) -> list:
    """Every ``deal_damage`` step *card*'s program carries, wrappers opened."""
    from .ai_weighed_cast import _walk_program

    if card is None:
        return []
    return [
        step for step in _walk_program(compile_card_oracle(card))
        if step.kind == "deal_damage"
    ]


def result_is_damaged(card, result_key: str) -> bool:
    """Whether a later step of *card* deals damage to the seat its program
    records under *result_key* ("Backdraft deals damage to **that player**")."""
    return any(
        (step.payload or {}).get("recipient") == result_key for step in _damage_steps(card)
    )


def result_is_damage_dealt(card, result_key: str) -> bool:
    """Whether a later step of *card* deals the number its program records
    under *result_key* as damage ("…equal to half the damage dealt by one of
    those sorcery spells")."""
    return any(
        ((step.payload or {}).get("x_from_count") or {}).get("back_reference") == result_key
        for step in _damage_steps(card)
    )


def cast_choice_pick(game, chooser: int, options: list[int]) -> int | None:
    """Which of this turn's casts (ledger positions) a chooser names when the
    damage that cast dealt becomes damage to its caster (Backdraft: "…deals
    damage to that player equal to half the damage dealt by one of those
    sorcery spells"): the one that dealt most where its caster is somebody
    else, the one that dealt least where it is the chooser. The first cast
    was the default."""
    from .damage_ledger import cast_by_index, damage_dealt_by_cast

    if not options:
        return None

    def dealt(index: int) -> int:
        entry = cast_by_index(game, index)
        return damage_dealt_by_cast(game, entry.item) if entry is not None else 0

    def sign(index: int) -> int:
        entry = cast_by_index(game, index)
        return -1 if entry is not None and entry.seat == chooser else 1

    return _first_best(options, lambda index: sign(index) * dealt(index))


def player_choice_pick(game, choice, live: list[int]) -> int | None:
    """Which offered seat a chooser names.

    * **A seat the card then damages** (Backdraft's "choose a player who cast
      one or more sorcery spells this turn" behind "deals damage to that
      player equal to half the damage dealt by one of those sorcery
      spells"): an opponent before the chooser itself, and among them the
      one whose casts would hand it the most damage.
    * **"Which opponent"** — an unnamed "an opponent" at a table of three or
      more (CR 601.7a / 608.2d, ``handlers/player_choices.ask_which_opponent``):
      what that opponent then gets or decides is done for the chooser's
      opponent, so the one least ahead (``ai_rehearsal.seat_standing``) is
      named — a permanent handed over, a token made or a pile chosen by the
      seat least able to turn it against the chooser.

    The first seat offered was the default."""
    from .damage_ledger import cast_options, damage_dealt_by_cast

    if not live:
        return None
    chooser = choice.player_index
    context = choice.data.get("_context")
    card = getattr(context, "card", None)
    result_key = str(choice.data.get("result_key") or "")
    if card is not None and result_is_damaged(card, result_key):
        card_type = _counted_cast_type(card, result_key)

        def harm(seat: int) -> tuple:
            most = max(
                (
                    damage_dealt_by_cast(game, entry.item)
                    for _index, entry in cast_options(game, seat=seat, card_type=card_type)
                ),
                default=0,
            )
            return (seat != chooser, most)

        return _first_best(live, harm)
    return _first_best(live, lambda seat: -seat_standing(game, seat))


def _counted_cast_type(card, result_key: str) -> str | None:
    """The printed type of the casts a "one of those spells" step after a
    seat chosen under *result_key* reads, or None for any cast."""
    from .ai_weighed_cast import _walk_program

    for step in _walk_program(compile_card_oracle(card)):
        if step.kind == "choose_cast_this_turn" and (step.payload or {}).get("by_result") == result_key:
            return (step.payload or {}).get("card_type") or None
    return None


# -- Rehearsed answers --------------------------------------------------------


def _rehearsed_best(game, seat: int, carried, answers, answer, label: str, *, detach):
    """The answer of *answers* whose rehearsal leaves *seat* furthest ahead, the
    first offered between equals — or None where no rehearsal can be run, for
    the caller's stated answer to stand. ``ai_prompts._best_rehearsed_answer``
    asks whether an answer beats doing nothing; this asks which of several
    answers, one of which must be given, is best."""
    if rehearsing() or not answers:
        return None
    best, best_swing = None, None
    with deliberating():
        for candidate in answers:
            rehearsal = rehearse(
                game, seat,
                lambda table, held, candidate=candidate: _Answered(
                    bool(answer(table, held, candidate))
                ),
                leaves_hand=False, carried=carried, detach=detach, label=label,
            )
            if rehearsal is None:
                return None
            if not rehearsal.accepted:
                continue
            if best_swing is None or rehearsal.swing > best_swing + _SAME:
                best, best_swing = candidate, rehearsal.swing
    return best


def opponent_mode_pick(game, choice, stated: int) -> int:
    """Which mode the opponent CR 700.2e hands a spell's mode choice to names
    ("An opponent chooses one —": Fatal Lore, Misfortune, Library of Lat-Nam):
    each printed mode rehearsed from the chooser's seat — recorded on the
    spell, its targets named by the caster's own default, the spell resolved —
    and the one that leaves the chooser best off, which is the one worst for
    the caster. *stated* (the first printed mode) where no rehearsal can be
    run. The first printed mode was the default, so Fatal Lore always drew
    its caster three cards."""
    labels = list(choice.data.get("labels") or ())
    if choice.data.get("_item") is None or len(labels) < 2:
        return stated
    with _one_level_deeper():
        picked = _rehearsed_best(
            game, choice.player_index, choice, list(range(len(labels))),
            lambda table, prompt, index: table._resolve_opponent_mode_choice(prompt, index),
            label=f"{choice.data.get('card_name') or 'a spell'} (an opponent's mode)",
            detach=True,
        )
    return stated if picked is None else picked


#: Whether :func:`_one_level_deeper` is already open: a second level is never
#: opened, so the depth is bounded at two.
_DEEPER: ContextVar[bool] = ContextVar("ai_prompt_picks_deeper", default=False)


@contextmanager
def _one_level_deeper():
    """Let one prompt's answer be rehearsed **inside a rehearsal**, once.

    The caster weighs an "An opponent chooses one —" spell by rehearsing its
    cast (``ai_rehearsal.rehearse``), and on that copy the opponent's mode is
    answered by this module's default — which a rehearsal may not rehearse
    again (``rehearsing``), so it fell back to the first printed mode and the
    caster predicted a Fatal Lore that drew it three cards on a board where
    the opponent, asked for real, takes the cards itself (the idle-cast
    census read the cast as a loss). The opponent's answer is the one thing
    the caster's rehearsal cannot price without, so it is rehearsed one level
    down: a fresh deliberation (its readings belong to that copy, and a cache
    keyed by ``id()`` must not hand them to another), and never a third
    level — the rehearsals opened here answer every prompt of theirs as a
    rehearsal does. Outside a rehearsal this does nothing."""
    from . import ai_rehearsal

    if not rehearsing() or _DEEPER.get():
        yield
        return
    deeper = _DEEPER.set(True)
    allowed = ai_rehearsal._REHEARSING.set(False)
    fresh = ai_rehearsal._DELIBERATION.set(None)
    try:
        yield
    finally:
        ai_rehearsal._DELIBERATION.reset(fresh)
        ai_rehearsal._REHEARSING.reset(allowed)
        _DEEPER.reset(deeper)


def text_change_vocabulary_pick(game, choice, stated: str) -> str:
    """Which vocabulary a text change rewrites where a permanent's text holds
    both a colour word and a basic land type for the symbols chosen ("…one
    color word with another or one basic land type with another", Mind Bend,
    Crystal Spray): each rewrite rehearsed and the one leaving the chooser best
    off taken, *stated* (the colour word) between equals or where nothing can
    be rehearsed."""
    options = list(choice.data.get("options") or ())
    if len(options) < 2:
        return stated
    ordered = [stated, *(option for option in options if option != stated)]
    picked = _rehearsed_best(
        game, choice.player_index, choice, ordered,
        lambda table, prompt, mode: table._resolve_text_change_vocabulary(prompt, mode),
        label=f"{choice.data.get('card_name') or 'a text change'} (which words)",
        detach="abstract",
    )
    return stated if picked is None else picked


__all__ = [
    "balance_discards",
    "balance_sacrifices",
    "battlefield_worth",
    "cast_choice_pick",
    "face_down_cast_pick",
    "hand_to_library_picks",
    "hand_size_discards",
    "held_worth",
    "library_pile_split",
    "linked_exile_return_pick",
    "look_top_pick",
    "mana_breadth",
    "modal_mode_target_picks",
    "opponent_mode_pick",
    "pile_search_pick",
    "player_choice_pick",
    "put_from_hand_pick",
    "reflexive_target_order",
    "result_is_damage_dealt",
    "result_is_damaged",
    "text_change_vocabulary_pick",
    "untap_up_to_order",
    "word_of_command_pick",
]

"""CR 116 special actions — what a player may do with priority without the stack.

CR 116.1: "Special actions are actions a player may take when they have priority
that don't use the stack." There are twelve, and this engine implements five of
them: the land drop (116.2a), turning a face-down creature face up (116.2b —
morph, registered by ``engine/face_down.py`` on the permanent seam below), the
two offers a permanent makes (116.2c, 116.2d) and Circling Vultures' discard
(116.2e). The land drop (CR 116.2a) is the older one and lives where it has always
lived — `Game._land_play_refusal` plus the play path — because moving it is a
refactor over every land in the pool rather than a card's work; this module is
the seam every *other* special action arrives on, and the land drop's home is
named here so the pair is findable.

The one it opens with is CR 116.2e, which is the only rule in the CR that names
a card:

    One card (Circling Vultures) has the ability "You may discard Circling
    Vultures any time you could cast an instant." Doing so is a special action.
    A player can take such an action any time they have priority.

**Text-keyed rather than name-keyed**, even though the rule itself names the
card. What the entry bar in `card_hooks.py` asks is whether a second card, real
or plausibly printable, could share the *shape* — and a sentence of the form
"you may <do this> any time you could cast an instant" is a shape, not a card.
The name in the CR is a fact about the printing history; the sentence is the
thing the engine reads.

Three properties follow, and each is load-bearing:

* **It does not use the stack** (CR 116.1), so there is no instruction to
  compile and no handler to dispatch. That is why the support gate reads this
  table directly (`derived_static_claims._derived_static_claims`) — without the row, a card
  whose only other text is a keyword and an upkeep trigger reports unsupported
  however well the action works.
* **It needs priority and nothing else** (CR 116.2e). "Any time you could cast
  an instant" is the printed spelling of exactly that, and it is *not*
  `cast_timing.casts_at_instant_speed`: that function answers about a card
  being cast, and nothing here is cast. What it means is CR 117.1's priority,
  which is what :func:`special_action_refusal` asks.
* **The player receives priority afterward** (CR 116.3), so the action neither
  passes priority nor advances a step. A caller that treated it as a play would
  hand the turn on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .alternative_costs import AlternativeCost
    from .game import Game
    from .models import CardDefinition, Permanent


#: The kind of special action a printed sentence grants, keyed by the sentence.
#: One row today; a second goes here beside it rather than in a branch, for the
#: reason every derivation table in this engine is a table.
#:
#: The pattern reads "this card", which is how Oracle prints the self-reference
#: and therefore how the ingest carries it. The CR quotes the older wording with
#: the card's name in it, and that spelling is deliberately **not** an
#: alternative here: no card file contains it, so the arm would be dead — and a
#: name in a comparison is dispatch, which `tests/engine/test_card_name_reads.py`
#: allows only in `card_hooks.py`. A card whose printing did spell its own name
#: would arrive through `self_reference._collapse_self_references` like every other
#: self-naming card in the pool.
_SPECIAL_ACTION_LINES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^you may discard this card any time you could cast an instant$"
        ),
        "discard_from_hand",
    ),
)


def _normalize(text: str) -> str:
    return " ".join((text or "").replace("’", "'").split()).lower().rstrip(".")


def special_action_line(line: str) -> str | None:
    """The special action *line* grants, as its kind, or None.

    Matched on the whole sentence rather than as a substring, for the reason
    `cast_cost_clauses.additional_cost_for_line` is: a substring match is how a
    whitelist comes to claim text it does not implement.

    Read by the support gate **and** by `scripts/parse_coverage.py`, so what
    the engine implements and what it claims to have read cannot drift — the
    same seam `enter_effects.enter_effect_line` is.
    """
    normalized = _normalize(line)
    for pattern, kind in _SPECIAL_ACTION_LINES:
        if pattern.match(normalized):
            return kind
    return None


def special_actions_for(card: "CardDefinition") -> tuple[str, ...]:
    """Every special action *card*'s own text grants, in printed order."""
    return tuple(
        kind
        for line in (getattr(card, "oracle_text", "") or "").splitlines()
        if (kind := special_action_line(line)) is not None
    )


def special_action_refusal(
    game: "Game", seat: int, card: "CardDefinition", kind: str
) -> str | None:
    """Why *seat* may not take *kind* with *card* right now, or None.

    One gate, asked by the engine before it acts and by the web layer before it
    offers — the same arrangement `legality_abilities.activation_target_refusal` makes,
    and for the same reason: an action the client offers and the engine refuses
    is a button that does nothing.

    The timing is CR 116.2e's "any time they have priority", which is CR 117.1's
    priority and not CR 307.1's sorcery window. A seat with no priority at all
    (`priority_player_index is None`) is refused: that is a turn-based action
    running or the game not started, and neither is a moment a player may act.
    """
    if kind not in special_actions_for(card):
        return f"{card.name} has no such special action"
    if not any(held is card for held in game.players[seat].hand):
        return f"{card.name} is not in {game.players[seat].name}'s hand"
    if not game.has_priority(seat):
        return f"{game.players[seat].name} does not have priority"
    return None


def take_special_action(
    game: "Game", seat: int, card: "CardDefinition", kind: str
) -> str | None:
    """Perform *kind* with *card* for *seat*; returns a refusal, or None on
    success.

    CR 116.3 gives the player priority again afterwards, which here means the
    action does **not** touch `priority_player_index`, advance a step or pass —
    a caller treating this as a play would hand the turn on. What it *does*
    mean is :func:`_priority_returns`: a player is about to receive priority,
    so CR 704.3 checks state-based actions first.
    """
    refusal = special_action_refusal(game, seat, card, kind)
    if refusal is not None:
        return refusal
    player = game.players[seat]
    if kind == "discard_from_hand":
        # Two seams, and both are load-bearing. ``take_card_from_hand`` removes
        # exactly **one** copy by identity: a deck repeats one immutable
        # ``CardDefinition`` per copy, so an identity *filter* over the hand
        # would delete every copy where this then files one.
        # ``put_card_into_graveyard`` is CR 614's event ("if a card would be
        # put into your graveyard from anywhere", Forbidden Crypt) — a bare
        # append would skip every replacement over it, which is the class
        # `tests/engine/test_graveyard_seam.py` exists to catch and did catch
        # here.
        game.take_card_from_hand(player, card)
        arrived = game.put_card_into_graveyard(player, card)
        game.log.append(
            f"{player.name} discarded {card.name} (CR 116.2e special action)"
            if arrived
            else f"{player.name} discarded {card.name}, and it was diverted"
        )
        # …and it is still CR 701.9a's discard, so the board's watchers hear of
        # it: the move alone was a discard nothing could see, and "whenever an
        # opponent discards a card" (Megrim) did nothing. Announced rather than
        # run through ``_discard_card``, because the two replacements that seam
        # asks are both about a discard something *caused* — "if an effect
        # causes you to discard" (Library of Leng), "a spell or ability an
        # opponent controls causes" (Dodecapod) — and a special action is the
        # player's own (CR 116.1), caused by nothing.
        game.announce_discard(player, card)
        _priority_returns(game)
        return None
    return f"no special action named {kind!r}"


def _priority_returns(game: "Game") -> None:
    """CR 116.3 then CR 704.3: the taker receives priority, so state-based
    actions are checked before they do.

    Here rather than at each caller, because "a special action was taken" has
    exactly two entry points and thirty consequences. The one that found it is
    a Licid: "You may pay {U} to end this effect" undoes the type change at
    once, but *who controls the enchanted creature* is a CR 613 layer-2
    contribution the sweep in ``mixins/game_ending`` derives from the
    attachment — so with no check here the Aura stopped being an Aura and the
    stolen creature stayed stolen until something else happened to resolve.
    ``phase_steps.pass_priority`` checks after a **resolution**, and a special
    action is by definition not one (CR 116.1), so nothing else was going to.
    """
    game.check_state_based_actions()


def available_special_actions(game: "Game", seat: int) -> list[dict]:
    """What *seat* may currently do as a special action, one entry per (card,
    kind) — the shape `cast_permissions.playable_from_zones` has, and for the
    same reason: the client needs to know which hand card to badge, and asking
    the same gate the action asks is what stops the two disagreeing.
    """
    entries: list[dict] = []
    for index, card in enumerate(game.players[seat].hand):
        for kind in special_actions_for(card):
            if special_action_refusal(game, seat, card, kind) is None:
                entries.append(
                    {"hand_index": index, "name": card.name, "kind": kind}
                )
    return entries



# ---------------------------------------------------------------------------
# CR 116.2c / 116.2d — an offer a *permanent* makes, taken from the battlefield
# ---------------------------------------------------------------------------
#
# The row above is about a card in a **hand**. These two subrules are about
# something already on the battlefield, and they are why this file is a seam
# rather than one card's exception:
#
#   116.2c  Some effects allow a player to take an action at a later time,
#           usually to end a continuous effect … Doing so is a special action.
#   116.2d  Some effects from static abilities allow a player to take an action
#           to ignore the effect from that ability for a duration.
#
# Tempest prints both. Every Licid ends its own type change with "You may pay
# {C} to end this effect" (116.2c) and Volrath's Curse lets the *enchanted*
# creature's controller buy a turn off its restriction (116.2d) — two cards,
# one rule, and neither of them a trigger, an activated ability or anything
# else that uses the stack. A `PendingChoice` is the wrong shape for both: that
# queue is a decision somebody **owes**, and this is a decision that simply
# stands, for as long as the effect does, and may never be taken at all.

#: CR 116.2d's offer an Aura makes **to its host's controller**, and the one
#: reading of it: the table below claims the sentence with it and
#: ``aura_restrictions`` builds the offer from it, so what the support gate
#: says it read and what the offer charges are one pattern — there were two
#: copies of the Volrath's Curse spelling before Lost in Thought needed a
#: second price.
#:
#: Two printed ways to name the seat — "**That creature's** controller"
#: (Volrath's Curse) and "**Its** controller" (Lost in Thought), the
#: possessive pointing back at the enchanted creature the sentence before it
#: restricted — and two prices:
#:
#: * ``sacrifice`` — "sacrifice a permanent of their choice" (Volrath's Curse);
#: * ``exile`` — "exile three cards from their graveyard" (Lost in Thought), a
#:   count of cards out of the taker's own graveyard, of their choice.
#:
#: Anything else — another price, another seat, another duration — matches
#: neither and leaves its card unsupported naming the sentence.
IGNORE_ATTACHED_STATIC_OFFER = re.compile(
    r"^(?:that (?P<noun>[a-z]+)'s|its) controller may "
    r"(?:(?P<sacrifice>sacrifice a permanent of their choice)"
    r"|exile (?P<exile>[a-z]+|\d+) cards from their graveyard) "
    r"for that player to ignore this effect until end of turn$"
)


def ignore_offer_price(sentence: str) -> "dict[str, object] | None":
    """What one CR 116.2d Aura offer charges, as :class:`SpecialActionOffer`
    keyword arguments — or None when *sentence* is not one.

    The count is a printed number word read through the grammar's vocabulary
    (``NUMBER_WORDS``), so "three" means here what it means in any sentence;
    a word that is not a number is no offer at all rather than an offer of
    nothing.
    """
    match = IGNORE_ATTACHED_STATIC_OFFER.match(_normalize(sentence).rstrip("."))
    if match is None:
        return None
    if match.group("sacrifice"):
        # "…**a permanent** of their choice", which is CR 110.1's whole noun:
        # an empty filter is every permanent.
        return {"sacrifice": {}}
    from .grammar.vocabulary import NUMBER_WORDS

    printed = match.group("exile")
    count = int(printed) if printed.isdigit() else NUMBER_WORDS.get(printed)
    if not isinstance(count, int) or count <= 0:
        return None
    return {"exile_from_graveyard": count}


#: The sentence a permanent prints to make one of these offers, and the kind of
#: offer it is. Matched against a whole **sentence** rather than a whole line,
#: because a Licid prints its offer as the third sentence of an activated
#: ability's line — where the two before it are the effect the offer undoes.
_PERMANENT_ACTION_SENTENCES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^you may pay (?P<cost>(?:\{[^}]+\})+) to end this effect$"),
        "end_own_continuous_effect",
    ),
    # CR 116.2d. "That creature's controller may sacrifice a permanent of their
    # choice for that player to ignore this effect until end of turn."
    # (Volrath's Curse; Lost in Thought's "Its controller may exile three cards
    # from their graveyard …" is the same offer at another price.) The offer is
    # made to somebody who is *not* the permanent's controller and its price is
    # not mana, which is why the two rows above and below this comment need a
    # richer answer than a cost: see :class:`SpecialActionOffer`.
    (IGNORE_ATTACHED_STATIC_OFFER, "ignore_attached_static_until_eot"),
    # CR 116.2d again, with the offer made to a player the sentence in front of
    # it *described* rather than to the controller of a permanent it named:
    # "A player who controls more permanents than each other player can't play
    # lands or cast artifact, creature, or enchantment spells. **That player
    # may sacrifice a permanent of their choice for that player to ignore this
    # effect until end of turn.**" (Damping Engine.)
    #
    # Its own row and its own kind rather than an alternation on the one above,
    # for the reason that one is not an alternation on the Licids': what
    # differs is who is offered and by what, and the two are answered by two
    # registered offers — an Aura asks its host who controls it, and this asks
    # the board who is ahead. One kind with two answers would be a branch
    # inside the offer, which is the shape this file is a registry instead of.
    (
        re.compile(
            r"^that player may sacrifice a permanent of their choice for that "
            r"player to ignore this effect until end of turn$"
        ),
        "ignore_board_static_until_eot",
    ),
)


@dataclass(frozen=True)
class SpecialActionOffer:
    """One offer a permanent is currently making: to whom, and for what.

    ``seat`` is who may take it, and it is on the offer rather than derived from
    the permanent because CR 116.2d's is not the permanent's controller: "**That
    creature's** controller may sacrifice a permanent" is an offer an Aura makes
    to the player it is punishing.

    ``mana``, ``sacrifice`` and ``exile_from_graveyard`` are the three prices
    the CR 116.2c/d offers print — a mana cost (CR 116.2c, the Licids), one
    permanent of the taker's choice described by a subject filter (CR 116.2d,
    Volrath's Curse), and a number of cards of the taker's choice out of their
    own graveyard (CR 116.2d, Lost in Thought) — and ``clauses`` is a printed
    cost's every other clause (a morph cost, CR 702.37e). All are paid by the
    seam below rather than by the offer's own ``take``, because a cost is a
    cost wherever it appears: paying it is not part of what the action
    *does*.

    ``x_symbols`` is how many ``{X}`` the mana price prints beyond ``mana``
    (Legions' "Morph {X}{X}{R}", Warbreak Trumpeter). CR 107.3d: "the value
    of X is chosen by the player taking the special action immediately before
    they pay that cost" — so the taker names X
    (:func:`take_permanent_special_action`'s ``x_value``), each symbol is that
    much generic mana, and an offer carrying any is taken as
    ``take(game, seat, permanent, x_value=X)`` so what the action does may
    read the number (CR 702.37f). 0 for every price without one, which leaves
    every other offer's shape and call unchanged.
    """

    seat: int
    mana: "dict[str, int] | None" = None
    sacrifice: "dict[str, object] | None" = None
    exile_from_graveyard: int = 0
    x_symbols: int = 0
    #: A price's clauses that are **not** mana, as the record every printed
    #: alternative cost is read into (``alternative_costs._read_cost_clauses``
    #: through an :class:`~engine.alternative_costs.AlternativeCost`): "Pay 5
    #: life", "Sacrifice two Mountains", "Return a Bird you control to its
    #: owner's hand", "Discard a Zombie card" — Scourge's morph costs
    #: (CR 702.37e: "pay that cost", whatever it is). Gated by the Game's
    #: alternative-cost gate (``_unpayable_alternative_cost``) and paid by its
    #: payer (``_pay_alternative_cost``), so what "sacrifice two Mountains"
    #: charges is one answer whether Fireblast or Skirk Volcanist prints it.
    #: None for every price without one.
    clauses: "AlternativeCost | None" = None
    #: What a refusal and a log line say the price is for, when it has
    #: :attr:`clauses` — "turn a face-down creature face up" — worded so it
    #: names no hidden card (CR 708.5). Empty for every other offer.
    purpose: str = ""


@dataclass(frozen=True)
class PermanentSpecialAction:
    """One kind of battlefield offer, and the two questions it answers.

    ``offer`` is what *permanent* is offering **right now**, as the mana cost of
    taking it, or None when it is making no such offer. One question rather than
    a separate "is it open?" and "what does it cost?", because CR 116.2c's offer
    is made by an **effect** and not by a card: the sentence table above says
    which sentence *creates* one, and by the time a Licid's offer can be taken
    the sentence has gone from the permanent's text — CR 613 layer 6 took the
    whole ability away, which is the other half of what the ability did. The
    effect outlives its ability (CR 611.2a), and so does the offer.

    ``take`` performs it, with the cost already paid — and, for an offer
    whose price prints ``{X}`` (``SpecialActionOffer.x_symbols``), with the X
    the taker chose as the keyword ``x_value``.

    A registration rather than a branch, for this file's own stated reason: the
    sentence table says what a card *offers* and this says what the engine
    *does about it*, and a kind in one without the other is either an offer
    nothing performs or a performance nothing offers.
    """

    kind: str
    offer: "Callable[[Game, Permanent], SpecialActionOffer | None]"
    take: "Callable[[Game, int, Permanent], None]"
    #: What else the offer's entry in :func:`available_permanent_special_actions`
    #: tells a client, beyond the shape every entry has — the morph cost a
    #: face-down permanent would be turned face up for (CR 702.37e), which the
    #: seat taking it has to see before it pays. None for every kind that has
    #: nothing to add, so their entries are unchanged.
    entry_extras: "Callable[[Game, Permanent], dict] | None" = None


#: Registered by the modules that create the effects these offers end — never
#: here, because whether an offer still stands is a question only the module
#: owning that effect's record can answer. `engine/auras.py` registers the two
#: attached ones, and each offer lives with the record it reads: the one a
#: became-an-Aura permanent carries in `engine/aura_attachment.py`, the turn
#: bought off an Aura's restriction in `engine/aura_restrictions.py`, the only
#: places that can say whether the effect is still running or take it back.
#: `engine/cast_bans.py` holds the board-wide one (Damping
#: Engine), for the same reason one zone out: it owns the prohibition and the
#: record of who has bought a turn off it. `engine/face_down.py` holds CR
#: 702.37e's (turning a face-down permanent with morph face up, CR 116.2b),
#: because whether a permanent is face down and what it hides is its record.
PERMANENT_SPECIAL_ACTIONS: dict[str, PermanentSpecialAction] = {}


def register_permanent_special_action(spec: PermanentSpecialAction) -> None:
    """Register *spec*. A duplicate kind raises at import, as every other
    registry in this engine does."""
    if spec.kind in PERMANENT_SPECIAL_ACTIONS:
        raise ValueError(f"duplicate permanent special action {spec.kind!r}")
    PERMANENT_SPECIAL_ACTIONS[spec.kind] = spec


def _load_registrations() -> None:
    """Import the modules that register the offers above.

    Function-level and idempotent: this module imports nothing from the engine
    at module scope (which is what lets `engine/line_classification.py` import it from the
    top), and the registry would otherwise be empty for any caller that had not
    happened to import `engine/auras.py` first — an offer that exists or not
    depending on import order.
    """
    from . import auras  # noqa: F401
    from . import cast_bans  # noqa: F401
    # CR 702.37e / 116.2b: ``face_down`` registers turning a face-down
    # permanent with a morph ability face up.
    from . import face_down  # noqa: F401


def _split_sentences(line: str) -> list[str]:
    """*line* split on the full stops that end its sentences.

    Naive on purpose: a mana symbol carries no full stop and neither does any
    number in this pool, so splitting on "." is exact for the sentences the
    table above reads. A printing that broke that would fail to match and leave
    its card unsupported, which is the direction every reader in this file
    fails in.
    """
    return [part.strip() for part in (line or "").split(".") if part.strip()]


def permanent_special_action_sentence(
    sentence: str,
) -> "tuple[str, dict[str, int]] | None":
    """The ``(kind, mana cost)`` one printed *sentence* offers, or None.

    Matched whole, for :func:`special_action_line`'s reason: a substring match
    is how a whitelist comes to claim text it does not implement.

    Read by the support gate, by `scripts/parse_coverage.py` and by the offer
    enumerator below — so what the engine claims to have read and what it
    actually offers are one table.
    """
    from .mana_payment import mana_cost_from_symbols

    normalized = _normalize(sentence).rstrip(".")
    for pattern, kind in _PERMANENT_ACTION_SENTENCES:
        match = pattern.match(normalized)
        if match is None:
            continue
        # Not every offer names a price in mana — CR 116.2d's is a sacrifice —
        # so the group is optional and its absence is "no mana", never a
        # refusal. The rest of the price is the offer's business
        # (:class:`SpecialActionOffer`); this table reads only the sentence.
        printed = match.groupdict().get("cost")
        if printed is None:
            return kind, {}
        cost = mana_cost_from_symbols(printed.upper())
        if cost is None:
            return None
        return kind, cost
    return None


def permanent_special_action_in_line(
    line: str,
) -> "tuple[str, dict[str, int]] | None":
    """The offer one printed *line* carries, or None.

    A Licid's offer is the last sentence of an activated ability's line, so the
    line is split here and every sentence asked. The reader the *effect* uses
    when it records what it will let its controller pay to end
    (``handlers/types``), so what the sentence table says and what the
    offer costs cannot describe different words.
    """
    for sentence in _split_sentences(line):
        found = permanent_special_action_sentence(sentence)
        if found is not None:
            return found
    return None


def _payment_plan(game: "Game", seat: int, cost: "dict[str, int]"):
    """How *seat* would pay *cost*, or None.

    Over the pool **and** the seat's untapped lands. CR 116.2c gives the player
    priority for this, so they could have tapped for mana first — which is
    exactly what this plan does on their behalf, through the one reader every
    other "you may pay" in this engine goes through
    (``mana_payment.plan_payment``).
    """
    if not any(cost.values()):
        return {}
    return game.effect_payment_plan(seat, cost)


def _offer_price(
    offer: "SpecialActionOffer", x_value: "int | None",
) -> "dict[str, int] | None":
    """The mana *offer* charges with X = *x_value* (CR 107.3d): its fixed part
    plus X generic per ``{X}`` it prints. An X nobody named is 0 — the
    cheapest price, which is what "can this be taken at all?" asks."""
    x = max(0, int(x_value or 0))
    if not offer.x_symbols or not x:
        return offer.mana
    price = dict(offer.mana or {})
    price["generic"] = int(price.get("generic", 0)) + offer.x_symbols * x
    return price


def _x_refusal(offer: "SpecialActionOffer", x_value: "int | None") -> str | None:
    """Why *x_value* is no X this offer may be taken with, or None. A price
    printing no ``{X}`` has no X to choose, so a non-zero one is refused
    rather than ignored; a negative one is no number CR 107.3d lets a player
    choose (CR 107.1b)."""
    if x_value is None:
        return None
    if isinstance(x_value, bool) or not isinstance(x_value, int) or x_value < 0:
        return f"X = {x_value!r} is not a number of mana"
    if x_value and not offer.x_symbols:
        return "that price has no X to choose"
    return None


def special_action_max_x(
    game: "Game", seat: int, offer: "SpecialActionOffer", *, ceiling: int = 30,
) -> int:
    """The largest X *seat* could pay *offer*'s price with right now — its
    pool and untapped lands, through the same plan the take pays by — or 0.
    For a client's X box and the AI's sizing; never a bound the take relies
    on (the take plans the announced X itself)."""
    if not offer.x_symbols:
        return 0
    best = 0
    for x in range(1, ceiling + 1):
        price = _offer_price(offer, x) or {}
        if _payment_plan(game, seat, price) is None:
            break
        best = x
    return best


def permanent_special_action_refusal(
    game: "Game", seat: int, permanent: "Permanent", kind: str,
    x_value: "int | None" = None,
) -> str | None:
    """Why *seat* may not take *kind* with *permanent* right now, or None.

    The battlefield twin of :func:`special_action_refusal`, asked by the engine
    before it acts and by the web layer before it offers — the same arrangement,
    and the same reason.

    Four questions, and the first is what a hand card has no equivalent of: the
    permanent must still be making the offer (CR 116.2c's "for as long as the
    effect allows it"), which is asked of the registered offer rather than of
    the card's text — see :class:`PermanentSpecialAction`.

    *x_value* is the X the taker names for a price printing ``{X}``
    (CR 107.3d); None asks at X = 0, the cheapest price, which is what an
    offer's listing asks.
    """
    _load_registrations()
    spec = PERMANENT_SPECIAL_ACTIONS.get(kind)
    if spec is None:
        return f"no special action named {kind!r}"
    if not game.is_on_battlefield(permanent):
        return f"{permanent.card.name} is no longer on the battlefield"
    offer = spec.offer(game, permanent)
    if offer is None:
        return f"{permanent.card.name} is not making that offer"
    if offer.seat != seat:
        return f"{permanent.card.name} is not offering that to {game.players[seat].name}"
    if not game.has_priority(seat):
        return f"{game.players[seat].name} does not have priority"
    x_refusal = _x_refusal(offer, x_value)
    if x_refusal is not None:
        return x_refusal
    price = _offer_price(offer, x_value)
    if price and _payment_plan(game, seat, price) is None:
        return f"{game.players[seat].name} can't pay for it"
    if offer.sacrifice is not None and not _sacrificeable(game, seat, offer):
        return f"{game.players[seat].name} has nothing to sacrifice for it"
    if len(game.players[seat].graveyard) < offer.exile_from_graveyard:
        # "…may exile **three** cards from their graveyard" (Lost in Thought).
        # CR 116.2d's action is the whole price or none of it: with two cards
        # there is no way to exile three, so the offer cannot be taken.
        return (
            f"{game.players[seat].name} has fewer than "
            f"{offer.exile_from_graveyard} cards in their graveyard"
        )
    if offer.clauses is not None:
        # CR 601.2h's question asked of the clauses that are not mana (CR
        # 118.3: a cost is paid only in full), by the gate every printed
        # alternative cost is asked through — the payer's life against "Pay 5
        # life", the Mountains they control against "Sacrifice two Mountains".
        return game._unpayable_alternative_cost(
            seat, permanent.card, offer.clauses, spell_hand_index=None,
            refused_as=f"{game.players[seat].name} can't pay to {offer.purpose}",
        )
    return None


def _clause_payers(
    game: "Game", seat: int, offer: "SpecialActionOffer",
    cost_permanent_ids: "list[int] | None",
    cost_hand_index: "int | None",
) -> "tuple[list, CardDefinition | None] | str":
    """Which permanents and which card in hand pay *offer*'s
    :attr:`~SpecialActionOffer.clauses`: ``(permanents, card)``, or a refusal.

    "Return **a Bird** you control", "Sacrifice **two Mountains**", "Discard
    **a Zombie card**" are each a choice of the taker's, made as the price is
    paid (CR 601.2h, through CR 702.37e's "pay that cost"). Named ones are
    held to the price — by id for a permanent (CR 400.7), by hand position for
    a card (two copies of a card in hand are one ``CardDefinition``) — out of
    the very candidate lists the gate counted
    (``Game._additional_cost_candidates``, ``Game._alternative_cost_payers``):
    a named object that cannot pay, an id named twice, or fewer or more than
    the price takes is refused with nothing spent, never slid onto a legal
    neighbour (CR 601.2h: "Partial payments are not allowed"). Nothing named is
    the deterministic pick every other cost's default makes.
    """
    clauses = offer.clauses
    named: list = []
    if cost_permanent_ids:
        payment = game.alternative_cost_permanent_payment(clauses)
        if payment is None:
            return "that price names no permanent to choose"
        verb, count = payment
        if len(set(cost_permanent_ids)) != len(cost_permanent_ids) or (
            len(cost_permanent_ids) != count
        ):
            return f"that price takes {count} permanent(s) to {verb}, each named once"
        candidates = game._additional_cost_candidates(seat, clauses, giving_up=verb)
        for permanent_id in cost_permanent_ids:
            found = game.permanent_by_id(permanent_id)
            if found is None or not any(found is held for held in candidates):
                return f"the permanent named to {verb} cannot pay that price"
            named.append(found)
    chosen = None
    takes_a_card = (
        clauses.discard_from_hand is not None or clauses.exile_from_hand is not None
    )
    if cost_hand_index is not None and not takes_a_card:
        return "that price takes no card from the hand"
    if takes_a_card:
        hand = game.players[seat].hand
        payers = game._alternative_cost_payers(seat, clauses, spell_hand_index=None)
        if cost_hand_index is None:
            chosen = payers[0] if payers else None
        elif not (0 <= cost_hand_index < len(hand)) or not any(
            hand[cost_hand_index] is payer for payer in payers
        ):
            return f"the card at hand position {cost_hand_index} cannot pay that price"
        else:
            chosen = hand[cost_hand_index]
    return named, chosen


def _clause_entry(game: "Game", seat: int, offer: "SpecialActionOffer") -> dict:
    """What a client needs to ask for *offer*'s clauses before it sends the
    action: the life it costs, which permanents may pay its sacrifice /
    return / tap and how many (by id), and which cards in hand may pay its
    discard or exile (by hand position) — the lists :func:`_clause_payers`
    holds a named answer to. Empty for a price with none."""
    clauses = offer.clauses
    if clauses is None:
        return {}
    extras: dict = {"cost_text": clauses.describe()}
    if clauses.pay_life:
        extras["pay_life"] = clauses.pay_life
    payment = game.alternative_cost_permanent_payment(clauses)
    if payment is not None:
        verb, count = payment
        extras["cost_permanents"] = {
            "verb": verb,
            "count": count,
            "choices": [
                {"permanent_id": held.permanent_id, "name": held.card.name}
                for held in game._additional_cost_candidates(
                    seat, clauses, giving_up=verb,
                )
            ],
        }
    if clauses.discard_from_hand is not None or clauses.exile_from_hand is not None:
        hand = game.players[seat].hand
        payers = game._alternative_cost_payers(seat, clauses, spell_hand_index=None)
        extras["cost_hand_choices"] = [
            {"hand_index": position, "name": held.name}
            for position, held in enumerate(hand)
            if any(held is payer for payer in payers)
        ]
        extras["cost_hand_verb"] = (
            "discard" if clauses.discard_from_hand is not None else "exile"
        )
    return extras


def _sacrificeable(game: "Game", seat: int, offer: "SpecialActionOffer") -> list:
    """The permanents *seat* could give up to take *offer*.

    Through ``subject_filters.subject_matches``, the one reader of a printed
    noun phrase, so "a permanent" and any narrower phrase a later card prints
    are the same question asked with different data.
    """
    from .subject_filters import subject_matches

    return [
        permanent
        for permanent in game.controlled_by(seat)
        if subject_matches(game, permanent, offer.sacrifice or {}, observer=seat)
    ]


def _graveyard_slots_paying(
    game: "Game", seat: int, offer: "SpecialActionOffer",
    named: "list[int] | None",
) -> "list[int] | str":
    """The slots of *seat*'s graveyard that pay *offer*'s exile price, or a
    refusal.

    "…exile three cards from their graveyard" is a choice of the taker's
    (CR 116.2d's action, CR 601.2b's "of their choice" in spirit), so a slot
    list the taker names is that choice and is held to it: the printed count
    exactly, each slot a card that is there, no slot twice. A caller naming
    none gets the stated order every other graveyard price in this engine is
    paid in (``ai_prompt_readers.graveyard_price_order``), so a seat nobody
    asks gives up the cards its own valuation misses least.

    By slot because a card in a graveyard has no id, and two copies of one
    card in one pile are one ``CardDefinition`` — the same reason the
    activation path's ``cost_graveyard_indices`` is a slot list.
    """
    wanted = offer.exile_from_graveyard
    pile = game.players[seat].graveyard
    if named is None:
        from .ai_prompt_readers import graveyard_price_order

        return list(graveyard_price_order(game, seat, list(range(len(pile)))))[:wanted]
    slots = list(named)
    if len(slots) != wanted:
        return f"{len(slots)} cards named for a price of {wanted}"
    if len(set(slots)) != len(slots):
        return f"graveyard position {slots} names one card more than once"
    for slot in slots:
        if not (isinstance(slot, int) and not isinstance(slot, bool) and 0 <= slot < len(pile)):
            return f"no card at graveyard position {slot}"
    return slots


def take_permanent_special_action(
    game: "Game", seat: int, permanent: "Permanent", kind: str,
    sacrificed: "Permanent | None" = None,
    exiled_slots: "list[int] | None" = None,
    x_value: "int | None" = None,
    cost_permanent_ids: "list[int] | None" = None,
    cost_hand_index: "int | None" = None,
) -> str | None:
    """Perform *kind* with *permanent* for *seat*; a refusal, or None on success.

    *cost_permanent_ids* and *cost_hand_index* name what pays a price's
    clauses that are not mana (:attr:`SpecialActionOffer.clauses` — "Return a
    Bird you control …", "Discard a Zombie card", Scourge's morph costs): the
    permanents by id, the card by hand position, held to the price by
    :func:`_clause_payers`. None is the deterministic pick.

    *x_value* is the X the taker chooses for a price printing ``{X}`` — CR
    107.3d's "chosen by the player taking the special action immediately
    before they pay that cost" — paid as that much generic per symbol and
    handed to the offer's ``take`` (CR 702.37f). None is X = 0. A non-zero X
    for a price that prints none is refused (:func:`_x_refusal`).

    CR 116.3 again: the player receives priority afterwards, so nothing here
    passes, advances a step or touches ``priority_player_index`` — and
    :func:`_priority_returns` runs CR 704.3's check before they get it.

    *sacrificed* is which permanent pays a CR 116.2d offer's price — "a
    permanent **of their choice**", so the taker names it. A caller that names
    none gets ``Game.default_sacrifice_pick``, the one rule every other
    deterministic sacrifice in this engine goes through; naming one that does
    not satisfy the offer is a refusal rather than a silent substitution, for
    the reason every targeted effect here refuses: a cost paid with something
    the player did not choose is the quiet wrongness this repo does not ship.

    *exiled_slots* is the same choice for a price paid out of the taker's own
    graveyard ("…may exile three cards from their graveyard", Lost in
    Thought): graveyard positions, held to the printed count
    (:func:`_graveyard_slots_paying`).
    """
    refusal = permanent_special_action_refusal(
        game, seat, permanent, kind, x_value=x_value,
    )
    if refusal is not None:
        return refusal
    spec = PERMANENT_SPECIAL_ACTIONS[kind]
    offer = spec.offer(game, permanent)
    assert offer is not None  # the refusal above already asked
    price = _offer_price(offer, x_value)
    exiled: list = []
    if offer.exile_from_graveyard:
        slots = _graveyard_slots_paying(game, seat, offer, exiled_slots)
        if isinstance(slots, str):
            return slots
        exiled = slots
    victim = None
    if offer.sacrifice is not None:
        candidates = _sacrificeable(game, seat, offer)
        if sacrificed is not None:
            if not any(candidate is sacrificed for candidate in candidates):
                return f"{sacrificed.card.name} can't be sacrificed for that"
            victim = sacrificed
        else:
            victim = game.default_sacrifice_pick(candidates)
    clause_payers: "tuple[list, CardDefinition | None]" = ([], None)
    if offer.clauses is not None:
        resolved = _clause_payers(
            game, seat, offer, cost_permanent_ids, cost_hand_index,
        )
        if isinstance(resolved, str):
            return resolved
        clause_payers = resolved
    elif cost_permanent_ids or cost_hand_index is not None:
        return "that price names nothing to choose"
    plan = _payment_plan(game, seat, price) if price else None
    if plan:
        # The planned lands are tapped for mana through the one payer
        # (``Game._pay_planned_cost``, CR 605.3a).
        if not game._pay_planned_cost(
            game.players[seat], lambda: _payment_plan(game, seat, price),
            paying_for=permanent,
        ):
            return "that cost can't be paid"
    if victim is not None:
        game.sacrifice_permanent(victim)
        game.log.append(
            f"{game.players[seat].name} sacrificed {victim.card.name} "
            f"({permanent.card.name}, CR 116.2d)"
        )
    if exiled:
        # Out of the taker's own pile into their own exile (CR 404.1, 406.1):
        # the move ``activation_charges._pay_exile_cost`` makes for the same
        # printed price on an activated ability — highest slot first, because
        # every pop renumbers the slots behind it.
        taker = game.players[seat]
        cards = [taker.graveyard[slot] for slot in exiled]
        for slot in sorted(exiled, reverse=True):
            taker.graveyard.pop(slot)
        cards = game.put_cards_into_exile(taker, cards)
        game.log.append(
            f"{taker.name} exiled "
            + ", ".join(card.name for card in cards)
            + f" from their graveyard ({permanent.card.name}, CR 116.2d)"
        )
    if offer.clauses is not None:
        # The rest of the price, at the moment the mana was paid (CR 601.2h
        # pays every part at once), through the payer every printed
        # alternative cost is paid by — the discard as a cost through
        # ``_discard_card`` (CR 701.9a), the return through the bounce seam,
        # the counted sacrifice re-enumerated per permanent.
        named, chosen = clause_payers
        game._pay_alternative_cost(
            seat, permanent.card, offer.clauses, chosen,
            named_permanents=named, paying_for=offer.purpose,
        )
    if offer.x_symbols:
        spec.take(game, seat, permanent, x_value=max(0, int(x_value or 0)))
    else:
        spec.take(game, seat, permanent)
    _priority_returns(game)
    return None


def available_permanent_special_actions(game: "Game", seat: int) -> list[dict]:
    """What *seat* may currently do with a permanent, one entry per
    (permanent, kind) — the battlefield half of
    :func:`available_special_actions`.

    Addressed by ``permanent_id`` rather than by a battlefield slot, for the
    reason every other wire-borne permanent reference in this engine is: a slot
    renumbers the moment anything leaves (CR 400.7).

    Over the **whole board**, not the seat's own permanents: CR 116.2d's offer
    is made by an Aura to the player it is punishing, so the permanent making it
    is one this seat does not control. Which seat may take it is the offer's own
    answer (``SpecialActionOffer.seat``), asked through the same refusal the
    action asks.
    """
    _load_registrations()
    entries: list[dict] = []
    for permanent in game.all_permanents():
        for kind in PERMANENT_SPECIAL_ACTIONS:
            if permanent_special_action_refusal(game, seat, permanent, kind) is None:
                entry = {
                    "permanent_id": permanent.permanent_id,
                    "name": permanent.card.name,
                    "kind": kind,
                }
                # How many graveyard cards the price takes, so a client can ask
                # which ones before it sends the action (Lost in Thought's
                # three). Only on an offer that charges one: every other
                # entry's shape is unchanged.
                spec = PERMANENT_SPECIAL_ACTIONS[kind]
                offer = spec.offer(game, permanent)
                if spec.entry_extras is not None:
                    entry.update(spec.entry_extras(game, permanent))
                if offer is not None and offer.exile_from_graveyard:
                    entry["exile_from_graveyard"] = offer.exile_from_graveyard
                # A price printing {X} (CR 107.3d: the taker chooses X just
                # before paying): how many X symbols, and the largest X the
                # seat could pay now, so a client asks for X — bounded — and
                # sends it as the action's ``x_value``. Only on such an offer:
                # every other entry's shape is unchanged.
                if offer is not None and offer.x_symbols:
                    entry["x_symbols"] = offer.x_symbols
                    entry["max_x"] = special_action_max_x(game, seat, offer)
                # …and which permanents a "sacrifice a permanent **of their
                # choice**" price may be paid with (Volrath's Curse), by id —
                # the list the action's ``sacrificed`` is checked against, so a
                # client offers exactly what the engine will take. Without it
                # a person could only take the engine's default pick.
                if offer is not None and offer.sacrifice is not None:
                    entry["sacrifice_choices"] = [
                        {"permanent_id": candidate.permanent_id, "name": candidate.card.name}
                        for candidate in _sacrificeable(game, seat, offer)
                    ]
                # …and a price's clauses that are not mana (a morph cost, CR
                # 702.37e): the life, and which permanents and hand cards may
                # pay it, so a client asks before it sends the action's
                # ``cost_permanent_ids`` / ``cost_hand_index``. Only on such
                # an offer: every other entry's shape is unchanged.
                if offer is not None and offer.clauses is not None:
                    entry.update(_clause_entry(game, seat, offer))
                entries.append(entry)
    return entries


__all__ = [
    "PERMANENT_SPECIAL_ACTIONS",
    "PermanentSpecialAction",
    "SpecialActionOffer",
    "available_permanent_special_actions",
    "available_special_actions",
    "permanent_special_action_in_line",
    "permanent_special_action_refusal",
    "permanent_special_action_sentence",
    "register_permanent_special_action",
    "special_action_max_x",
    "take_permanent_special_action",
    "special_action_line",
    "special_action_refusal",
    "special_actions_for",
    "take_special_action",
]

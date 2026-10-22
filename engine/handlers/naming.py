"""A card **name** chosen as an effect resolves, and the sentences checking it.

The handler twin of ``engine/grammar/naming.py``'s paragraphs. Foreshadow's bare
"choose a card name", and the printed paragraphs whose later sentences read the
name back: Necromentia strips it out of a player's zones, Petra Sphinx reveals
the top card against it, Demonic Consultation reveals until it turns up,
Nebuchadnezzar reveals at random and discards the matches. A seat nobody asks
names the commonest name it can see (:func:`_commonest_visible_name`), ties
broken by name so a seed replays.

Split out of ``zones.py`` at the 2,000-line cap's split round. A search a name
drives ("search … for all cards with the same name", Lobotomy) is
``search.py``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._amounts import resolve_amount
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("choose_card_name")
def choose_card_name(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"**Choose a card name**, then target opponent mills a card…"
    (Foreshadow.)

    A step that produces a *value* and no effect, exactly as "choose a color"
    does. The name is chosen as the spell resolves (CR 608.2) and CR 202.1 lets
    a player name any card at all, so nothing is offered and nothing is
    validated — whatever the seat types is the name.

    Its own prompt kind rather than a fused whole-effect handler like the three
    naming paragraphs beside it (Demonic Consultation, Nebuchadnezzar,
    Necromentia). Those three read *what the name is for* in the same handler
    because their sentences share one pile; this one's name is read by an
    ordinary condition two sentences later, so the choice is a step and the
    reading is a condition.

    The prompt suspends the resolution (CR 608.2, CR 117.3b): the mill behind
    it must not run while the name is still owed, because a seat that saw the
    milled card before naming would be choosing with information the card does
    not give them.

    ``card_type`` is the printed bound on CR 202.1's freedom — "Choose a
    **creature** card name" (Wood Sage). It is carried to the prompt and the
    default is taken *within* it, because a headless game has to obey the same
    restriction the prompt does; the answer is checked against the catalog when
    it comes back, which is the only place a named card can be looked up at
    all.
    """
    seat = game.players.index(context.caster)
    card_type = instruction.payload.get("card_type") or None
    # "…other than a basic land card name" (Desperate Research): the other
    # printed bound, carried to the prompt and obeyed by the default exactly as
    # the type is.
    no_basics = bool(instruction.payload.get("exclude_basic_land_names"))
    # A non-interactive seat names the commonest card it may legally know of
    # **in the place the name will be looked for**. That place is the
    # sentence behind the choice, and three of the four cards printing one
    # look among the chooser's own cards: Wood Sage and Desperate Research
    # reveal the top of *your* library — a player built the deck, so what the
    # library still holds is theirs to work out, and CR 401.2 hides only which
    # card is where — and Cursed Scroll reveals a card from *your* hand. Named from the opponents' graveyards — the default for all
    # four — a Scroll activated with one card in hand missed it eleven times
    # running.
    #
    # Everything else (Foreshadow mills an opponent) keeps that default: the
    # opponents' graveyards, which CR 400.2 makes public, are the evidence a
    # player has of what an opponent's library holds, and naming out of that
    # library itself would be the AI reading hidden information. Nothing to
    # see names nothing, which is legal and simply misses.
    #
    # **And the fifth card looks wherever it is aimed.** "Choose a card name,
    # then **target player** mills a card. If a card with the chosen name was
    # milled this way, you draw two cards." (Predict.) The milled library is
    # the announcement's, and a seat that aims it at itself — which is where
    # this policy aims it — is asking about its own deck: the commonest name
    # its own library still holds. It was named out of the opponent's
    # graveyard all the same, so the seat milled its own library looking for
    # a card from somebody else's, and with that graveyard empty it named
    # nothing: one card drawn, every time, for a spell whose whole text is
    # the second one. Aimed at another seat it keeps the public evidence —
    # *that* seat's graveyard — and never reads the library it is milling.
    from ..ai_valuation import (chosen_name_is_read_off_the_targets_library,
                                chosen_name_own_zone)

    own_zone = (
        chosen_name_own_zone(context.card, instruction)
        if context.card is not None else None
    )
    milled_seat = None
    if (
        own_zone is None
        and context.card is not None
        and chosen_name_is_read_off_the_targets_library(context.card, instruction)
    ):
        milled_seat = next(
            (index for index, player in enumerate(game.players)
             if player is context.target),
            None,
        )
    if own_zone is not None:
        default_name = _commonest_visible_name(
            game, seat, (own_zone,), exclude_basics=no_basics, card_type=card_type,
        )
    elif milled_seat == seat:
        default_name = _commonest_visible_name(
            game, seat, ("library",), exclude_basics=no_basics, card_type=card_type,
        )
    else:
        default_name = _commonest_visible_name(
            game,
            milled_seat if milled_seat is not None
            else next(iter(game.opponents_of(seat)), seat),
            ("graveyard",), exclude_basics=no_basics, card_type=card_type,
        )
    game.arm_pending_choice(
        "choose_card_name", seat,
        card_name=context.card.name if context.card is not None else "",
        card_type=card_type,
        **({"exclude_basic_land_names": True} if no_basics else {}),
        default_name=default_name,
        record=context.results,
    )
    return True, "pending_choose_card_name"


@effect_handler("name_and_strip")
def name_and_strip(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Necromentia: name a card, strip every copy from an opponent's three
    zones, then pay them a Zombie for each one taken from their **hand**.

    One handler for the whole effect because the three printed sentences share
    one choice and one pile — "each card exiled from their hand this way" counts
    exactly the subset the search took from one of the zones, and split apart
    the last sentence would count a pile nobody recorded.

    The name is chosen as the spell resolves (CR 608.2), and CR 202.1 lets a
    player name any card — bounded here only by the printed restriction, which
    is that it may not be a basic land's name. A seat that names nothing strips
    nothing, which is legal and useless; the default names the commonest card
    among what it can see, which is the choice a player would actually make.
    """
    caster = context.caster
    target = context.target
    if target is None or target is caster:
        game.log.append(f"{context.card.name}: no opponent to search")
        return True, "resolved"
    seat = game.players.index(target)
    game.arm_pending_choice(
        "name_and_strip", game.players.index(caster),
        card_name=context.card.name,
        target_seat=seat,
        zones=list(instruction.payload.get("zones") or ()),
        token_zone=instruction.payload.get("token_zone", "hand"),
        token=dict(instruction.payload.get("token") or {}),
        default_name=_commonest_visible_name(
            game, seat, instruction.payload.get("zones") or ()
        ),
    )
    return True, "pending_name_and_strip"


def _commonest_visible_name(
    game, seat: int, zones, *, exclude_basics: bool = True,
    card_type: str | None = None,
) -> str:
    """The name a non-interactive seat picks: the one appearing most often in
    *zones* of *seat*'s cards, ties broken by name so a seed replays exactly.

    Whether basic land names count is the *card's* restriction, not this
    helper's: Necromentia forbids them and a headless game must obey the same
    rule its prompt does, while Petra Sphinx's guess may name anything (CR
    202.1) and excluding them there would refuse a name a player would happily
    pick. So it is a parameter, and the zone list is passed rather than dug out
    of a payload key only one caller has.

    ``card_type`` is the same fact in the other direction — "Choose a
    **creature** card name" (Wood Sage) bounds what may legally be named, and a
    default outside the bound is a headless game breaking a rule the prompt
    enforces. Nothing matching leaves the name empty, which is what a seat with
    no legal answer it can see actually has.
    """
    from collections import Counter

    player = game.players[seat]
    counts: Counter = Counter()
    for zone in zones or ():
        for card in getattr(player, zone, []):
            if exclude_basics and "basic" in (card.type_line or "").lower():
                continue
            if card_type and card.primary_type != card_type:
                continue
            counts[card.name] += 1
    if not counts:
        return ""
    best = max(counts.values())
    return sorted(name for name, n in counts.items() if n == best)[0]


@effect_handler("name_then_reveal_top")
def name_then_reveal_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Petra Sphinx: "Target player chooses a card name, then reveals the top
    card of their library. If that card has the chosen name, that player puts
    it into their hand. If it doesn't, the player puts it into their
    graveyard."

    One handler because the three sentences are one procedure: the name decides
    where the card goes, and neither the name nor the revealed card exists
    before this resolution begins (CR 608.2). The choosing seat is the targeted
    player's, and so is the library, the hand and the graveyard — the card
    never says "you" anywhere.

    The card is **not** turned over here. It is revealed as part of answering
    the prompt, because a reveal before the name is chosen would show the
    chooser what to name.
    """
    target = context.target
    if target is None:
        game.log.append(f"{context.card.name}: no player to ask")
        return True, "resolved"
    seat = game.players.index(target)
    if not target.library:
        # CR 701.20a: there is nothing to reveal, so nothing is named either —
        # the choice would decide the destination of a card that does not
        # exist. An empty library is not a loss here; the draw step is.
        game.log.append(f"{context.card.name}: {target.name} has no library to reveal")
        return True, "resolved"
    game.arm_pending_choice(
        "name_then_reveal_top", seat,
        card_name=context.card.name,
        match_zone=instruction.payload.get("match_zone", "hand"),
        miss_zone=instruction.payload.get("miss_zone", "graveyard"),
        # A player knows what is in their own library, only not its order
        # (CR 400.2), so naming its commonest remaining card is a choice a
        # human at the table could make — and it is deterministic, which is
        # what a seeded replay needs. Basic lands are in: this card prints no
        # restriction, and CR 202.1 lets a player name any card.
        default_name=_commonest_visible_name(
            game, seat, ("library",), exclude_basics=False
        ),
        # "…and this artifact deals 2 damage to them" (Vexing Arcanix): the
        # miss branch's second half. The source travels with it because by the
        # time the prompt is answered this resolution has returned, and a
        # damage event needs to know what dealt it (colour-scoped prevention,
        # CR 702.16i protection, "a source you control").
        miss_damage=int(instruction.payload.get("miss_damage", 0) or 0),
        _damage_source=context.source_permanent or context.card,
    )
    return True, "pending_name_then_reveal_top"


@effect_handler("name_then_consult")
def name_then_consult(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Demonic Consultation: "Choose a card name. Exile the top six cards of
    your library, then reveal cards from the top of your library until you
    reveal a card with the chosen name. Put that card into your hand and exile
    all other cards revealed this way."

    Nothing happens here but the question. **The order is the card**: the six
    cards are exiled after the name is fixed and without being looked at, so
    the name may be among them — which is why the exile lives in the answer
    rather than here, where it would happen before the chooser had spoken.

    Unlike Petra Sphinx's guess, an empty library is not a reason to skip the
    prompt: exiling nothing and revealing nothing is a legal outcome of this
    spell, and the player has still cast it.
    """
    caster = context.caster
    seat = game.players.index(caster)
    game.arm_pending_choice(
        "name_then_consult", seat,
        card_name=context.card.name if context.card is not None else "",
        exile_count=int(instruction.payload.get("exile_count", 0) or 0),
        # A player knows what is in their own library, only not its order
        # (CR 400.2), so naming its commonest remaining card is a choice a human
        # at the table could make — and it is deterministic, which is what a
        # seeded replay needs.
        default_name=_commonest_visible_name(
            game, seat, ("library",), exclude_basics=False
        ),
    )
    return True, "pending_name_then_consult"


@effect_handler("name_and_random_reveal")
def name_and_random_reveal(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Nebuchadnezzar: name a card, make an opponent reveal N cards at random
    from a hidden zone, then discard every revealed card with that name.

    One handler for the whole effect because the three printed sentences share
    one choice and one pile: "all cards with that name **revealed this way**"
    is the subset the random reveal turned up, not every copy in the hand.
    Split apart, the discard would take the whole hand's worth and the
    randomness would mean nothing.

    The name is chosen as the ability resolves (CR 608.2), and the reveal is
    taken from the pile that exists *then* — which is why the count is resolved
    here rather than at activation: X was announced, but how many cards the
    opponent holds is a fact about this moment.
    """
    caster = context.caster
    target = context.target
    if target is None or target is caster:
        game.log.append(f"{context.card.name}: no opponent to reveal from")
        return True, "resolved"
    seat = game.players.index(target)
    count = resolve_amount(instruction.payload.get("count", 0), context.x_value)
    game.arm_pending_choice(
        "name_and_random_reveal", game.players.index(caster),
        card_name=context.card.name,
        target_seat=seat,
        count=max(0, int(count)),
        zone=str(instruction.payload.get("zone", "hand")),
        # A non-interactive seat names the commonest card in the opponent's
        # **graveyard**, which is the only zone bearing on this it may look at
        # (CR 400.2) — naming from the hand it is about to reveal from would be
        # the AI reading hidden information. An empty graveyard names nothing,
        # which reveals and discards nothing: legal, and the honest answer for a
        # seat with no information. Basics are not excluded, because this card
        # prints no restriction on the name (CR 202.1).
        default_name=_commonest_visible_name(
            game, seat, ("graveyard",), exclude_basics=False
        ),
    )
    return True, "pending_name_and_random_reveal"

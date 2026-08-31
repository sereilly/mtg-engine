"""The game and its players: tokens, life, turns, and outcomes.

Token creation, life gain and loss, extra turns, and the three CR 104 outcomes.

Grouped as "the game" rather than "the board", the same way the lowering side
groups it: none of these changes what a permanent is, and all of them change the
state a player or the game is in. `DrawGame` carries no player because CR 104.4
is a third outcome, not a win with an asterisk.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._core import (
    Amount,
    PlayerRef,
    TargetSpec,
)


@dataclass(frozen=True)
class GainLife:
    player: PlayerRef
    amount: Amount
    # "…for each creature you control with flying" (Aven Gagglemaster) — a
    # battlefield-count multiplier, mirroring LoseLife's graveyard one.
    per_each: object | None = None


@dataclass(frozen=True)
class LoseLife:
    player: PlayerRef
    amount: Amount
    # "…for each creature card in their graveyard" (Liliana, Death Mage) — the
    # amount is multiplied by a count of matching objects. None for the plain
    # sentence; the field is additive (this AST is append-only).
    per_each: object | None = None
    # "Each opponent who can't loses 3 life." (Liliana, Waker of the Dead) —
    # this loss applies only to opponents who could not perform the named
    # action of the preceding step ("discard"). Attached by the rider fold in
    # the sentence loop, never parsed on its own.
    who_could_not: str | None = None


@dataclass(frozen=True)
class SetLifeTotal:
    """"That player's life total becomes 20." (Rebirth.)

    CR 119.5: setting a life total is a gain or a loss of the difference, not a
    third kind of life change — but the printed number is the *result*, not the
    delta, so it cannot be lowered as a gain of a fixed amount. The node carries
    the target total and the handler works out which way it moves.
    """
    player: PlayerRef
    amount: Amount


@dataclass(frozen=True)
class ExchangeLifeTotals:
    """"Exchange life totals with target opponent." (Mirror Universe.)

    CR 701.12c: an exchange of life totals is each player *gaining or losing*
    the difference, not an assignment of two numbers — so replacement effects
    apply and life-gain triggers fire, exactly as :class:`SetLifeTotal` is
    written to for the same reason. CR 701.12a makes it atomic: if either half
    cannot happen, no part of it does.

    The other party is a player reference like any other, so "target opponent"
    and a card that printed "target player" are the same production.
    """
    player: PlayerRef


@dataclass(frozen=True)
class CoinFlipStakesLoop:
    """"Flip a coin. If you win the flip, you gain N life and target opponent
    loses N life, and you decide whether to flip again. If you lose the flip,
    you lose N life and that opponent gains N life, and that player decides
    whether to flip again. Double the life stakes with each flip." (Game of
    Chaos.)

    One node for the whole paragraph, like Mana Clash's flip loop: every
    sentence after the first reads a flip only the first produces, and the
    offer that repeats it is answered by whichever player the *result* names.
    Read as separate statements it would be four effects, and the one that
    decides whether there is a next round would have nothing to repeat.

    ``stake`` is the printed life total on the first flip — one number, because
    the four printed amounts are one quantity and a production that let them
    differ would compile a card nobody printed.

    ``doubling`` is the last sentence, and it is a field rather than a required
    word so that reading it changes what happens: without it the stake is
    constant, which is a real card one word shorter, and with it the words are
    load-bearing rather than consumed and dropped.
    """
    stake: Amount
    doubling: bool = False


@dataclass(frozen=True)
class Ante:
    """"Ante the top card of your library." (CR 407.)

    ``player`` is who antes, which is a different question from who the effect's
    controller is: Demonic Attorney prints "each player antes …", so every seat
    antes a card off its own library (CR 407.4 — a card is anted by its owner).

    Only the top-of-library ante is a node: it is the one the pool prints, and
    "ante a card from your hand" would choose differently and needs a prompt
    this has no field for.
    """
    player: PlayerRef


@dataclass(frozen=True)
class CreateToken:
    count: Amount
    # None for a **noncreature** token (a Treasure): CR 208.1 gives P/T only to
    # creatures, and 0/0 is a different answer that would die to state-based
    # actions the moment anything animated it.
    power: int | None
    toughness: int | None
    name: str
    colors: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    # "a **legendary** 3/4 red and green Human Warrior creature token"
    # (Stangg). CR 205.4 supertypes, recorded in the order printed and rendered
    # in front of the card types — a token can be legendary, and the legend
    # rule (CR 704.5j) reads the type line, so dropping the word would let two
    # copies coexist.
    supertypes: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    # "…that are tapped and attacking" (Basri Ket) — the tokens' entry state.
    tapped: bool = False
    attacking: bool = False
    # "**Its controller** creates a 4/4 white Angel creature token." (Angelic
    # Ascension, Secure the Scene) — the token goes to the exiled permanent's
    # controller, read back from the exile step of the same resolution. None
    # means the effect's own controller, which every earlier token card is.
    recipient: str | None = None
    # "…**for each nontoken creature that died this turn**" (Gadrak). A
    # multiplier over a history, exactly as on a counter placement or a life
    # gain — the set counted is the one no battlefield still holds.
    per_death: object | None = None
    # "Create an **X/X** blue and red Weird creature token, where X is the
    # number of instant and sorcery cards in your graveyard." (Experimental
    # Overload.) The P/T is a *count*, taken as the token is created (CR 608.2)
    # and then fixed — a token is not a characteristic-defining ability, so a
    # card later leaving the graveyard does not shrink it. ``power`` and
    # ``toughness`` stay None when this is set, because there is no printed
    # number for them to hold.
    counted_pt: object | None = None
    #: Printed abilities the token has, each as its own quoted line — "…with
    #: **"This token can't block"** and **"Creatures you control attack each
    #: combat if able."**" (the Pirate Pursued Whale makes). Text rather than
    #: parsed nodes, because the token's card is built at resolution and the
    #: compiler reads it then: one reading of one text, and a token ability
    #: therefore works exactly as the same words on a printed card do.
    granted_lines: tuple[str, ...] = ()
    #: "**Each opponent** creates …" — who gets the tokens. None is the effect's
    #: own controller, which every earlier token card is.
    recipient_players: str | None = None
    # The printed text a *predefined* token carries (CR 111.10). Transcribed
    # from `engine/tokens.py`'s table at parse time rather than left for the
    # handler to look up again, so the AST says everything the token is.
    oracle_text: str | None = None


@dataclass(frozen=True)
class CreateCopyToken:
    """``Create a token that's a copy of target creature you control.``
    (Sublime Epiphany.)

    Its own node rather than a field on :class:`CreateToken`, because none of
    that node's fields apply: a copy has no printed P/T, colour, type line,
    name or keyword list of its own — CR 707.2 gives it the copied permanent's
    *copiable* values, and every one of those fields would be a second,
    disagreeing answer to a question the copy effect already settles.
    """
    count: Amount
    subject: TargetSpec


@dataclass(frozen=True)
class CreateEmblem:
    """"You get an emblem with "<ability>"." (CR 114.2, the planeswalker
    ultimates.) The quoted ability rides as raw text: an emblem's ability is
    compiled when it fires, through the same compiler every card goes through,
    and the support gate in engine/oracle.py refuses the walker when that text
    cannot be read — so the string here is never a silent promise."""
    text: str


@dataclass(frozen=True)
class FlipCoin:
    """"Flip a coin." (CR 705.1.)

    The flip and nothing else. Its consequences are the ordinary conditional
    sentences that follow it, because how many there are is a property of the
    card and not of the flip: Tavern Swindler reads only the win, Mijae Djinn
    only the loss, Bottle of Suleiman both.
    """


@dataclass(frozen=True)
class ChooseNumber:
    """``Choose a number between 0 and 7.`` (Shapeshifter.)

    The bounds are the card's, so they ride the node rather than being baked
    into it: a card printed "between 1 and 5" is the same sentence. Nothing
    about *what the number is for* is here — Shapeshifter's P/T reads it back
    through a characteristic-defining line, which is a separate sentence and a
    separate rule (CR 604.3).
    """
    minimum: int
    maximum: int


@dataclass(frozen=True)
class ChooseColor:
    """``Choose a color.`` (Chromatic Armor's activated ability.)

    Beside :class:`ChooseNumber` and for the same reason: the sentence produces
    a *value* and no effect of its own, and what reads the value is a separate
    sentence on the card — here the Aura's static shield, which answers to
    "sources of the last chosen color".

    Nothing rides the node. The colour is not printed, the chooser is the
    ability's controller by CR 601.2b's default, and the permanent it is
    recorded on is the ability's own source — the same place the CR 614.1c
    entry-state version records it, which is what lets one reader answer both.
    """


@dataclass(frozen=True)
class ChoosePlayerWhoCast:
    """``Choose a player who cast one or more sorcery spells this turn.``
    (Backdraft.)

    A choice of a *player*, which this grammar had no node for at all: every
    other player a sentence names is targeted, is the caster, or is derived
    from an event. This one is chosen at resolution out of a set the turn's
    history defines, and the sentence after it says "that player".

    ``card_type`` is payload — a card printed "instant spells" is the same
    sentence — and so is ``minimum``, the "one or more" the clause spells out.
    Both are read rather than assumed, because a clause narrowing the set in a
    way this could not carry must refuse rather than choose from a wider one.
    """
    card_type: str
    minimum: int = 1


@dataclass(frozen=True)
class EndTheTurn:
    """``End the turn.`` (Discontinuity, Time Stop, Sundial of the Infinite.)

    Not an effect on any object, and not a duration: CR 724.1 is an *expedited
    process* that replaces the rest of resolution — the stack is exiled, state-
    based actions are checked, the current step ends and the game skips to the
    cleanup step with no player receiving priority. So it lowers to one
    instruction whose handler is that process, and there is nothing for it to
    target or count.

    The node carries no fields on purpose. "End the turn" has one printed form
    and no parameters; a card that ends a *phase* (Mandate of Peace, CR 724.2)
    is a different process with a different endpoint and would be its own node
    rather than a flag here.
    """


@dataclass(frozen=True)
class ExtraTurn:
    player: PlayerRef
    # "Take two extra turns after this one." (Teferi, Master of Time.)
    count: int = 1


@dataclass(frozen=True)
class WinGame:
    """"You win the game." (CR 104.2b.)"""
    player: PlayerRef


@dataclass(frozen=True)
class LoseGame:
    """"Target player loses the game." / "You lose the game." (CR 104.3e.)"""
    player: PlayerRef


@dataclass(frozen=True)
class DrawGame:
    """"The game is a draw." (CR 104.4c.)

    No player field: the sentence has no subject, and the effect ends the game
    for everyone. Its own node rather than a ``WinGame`` with a flag, because
    104.4 is a third outcome and not a win with an asterisk.
    """


@dataclass(frozen=True)
class PayLife:
    """"pay 4 life" (Sylvan Library) — CR 119.4.

    Not a :class:`LoseLife` with a different verb. Paying is something a player
    must be *able* to do (CR 119.4: only with a life total at least the amount),
    so it is an act that can be unofferable — which is exactly the question
    ``handlers/control_flow._action_is_takeable`` asks of every alternative
    before it is offered. A loss is never refused and never chosen; a payment is
    both. Folding them together would put "pay 4 life" in front of a player at
    2 life as a mode they could pick.
    """
    player: PlayerRef
    amount: Amount

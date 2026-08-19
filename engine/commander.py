"""CR 903 — the Commander variant, and CR 903.12's Brawl option.

Commander is "all the normal rules for a Magic game, with the following
additions" (CR 903.1), and this module is those additions. Like
``engine/ante.py`` it is opt-in: a game is a Commander game only when
``Game.commander_variant`` is set, and every seam below is inert otherwise, so
nothing here changes an ordinary duel.

Three concerns live here:

* **The designation** (CR 903.3). A commander is not a characteristic of the
  object — it is an attribute of the *card*, kept "even when it changes zones".
  So it cannot be a flag on a :class:`~engine.models.Permanent`, which is a new
  object every time it enters the battlefield (CR 400.7), and it cannot be
  identity on the :class:`~engine.models.CardDefinition`, which is immutable and
  **shared by every deck in the process** (the catalog dedupes reprints to one
  object, so two decks running the same card hold the same instance). It is a
  per-seat name: ``PlayerState.commanders`` holds the cards a seat began with in
  the command zone, and "is this card that seat's commander?" is asked by owner
  *and* name. CR 903.5b makes every non-basic name in a Commander deck unique,
  so within one seat a name names one card.

* **Colour identity** (CR 903.4), which is what a deck may contain. Derived from
  printed characteristics here rather than read off the ingested Scryfall field,
  because a token, a test fixture and a card the engine invents have no ingested
  field and would silently come back colourless — the value that passes every
  deck check. ``tests/rules/test_commander.py`` holds the derivation to
  Scryfall's answer over the whole pool, which is the direction that catches a
  drift: one derivation, checked against the authority, rather than two answers
  to one question.

* **The zone operations** — :class:`CommanderMixin`, composed onto ``Game``.
  Seeding the command zone (903.6), the starting life total (903.7 / 903.12f),
  casting from the command zone with the tax (903.8), the two ways a commander
  returns to it (903.9a's state-based action and 903.9b's replacement), and the
  21-damage loss (903.10a, which Brawl does not use — 903.12h).

The zone itself is ``PlayerState.command_zone`` (CR 408). Per-player, like the
ante zone and for the same reason: every rule about it is about the cards a
player *owns* there (CR 903.9a's "its owner may", 903.8's "a commander they
own").

**Both of 903.9's returns are optional** ("its owner may"), and both are offered
through :mod:`engine.replacement_choices` — an interactive seat is asked, every
other seat takes the default (the command zone) at once, through the same
resolver. 903.9b is a replacement by the rule's own words; 903.9a is a
state-based action, but the *decision* has the identical shape, so it is one
prompt kind rather than two.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

# The basic-land-type → mana-symbol table, imported rather than re-spelled:
# CR 305.6 gives a land with a basic land type an intrinsic mana ability, whose
# symbol is rules text for CR 903.4's purposes (it is why Badlands has a
# black-red identity while its printed text is nothing but reminder text, which
# 903.4c throws away). A second copy of that table is how one of the two goes
# stale.
from .models import _LAND_TYPE_MANA, CardDefinition, PlayerState
from .replacement_choices import (
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
)

# ---------------------------------------------------------------------------
# The variants (CR 903, CR 903.12a)
# ---------------------------------------------------------------------------

COMMANDER = "commander"
BRAWL = "brawl"
#: Every variant this module implements. ``Game.commander_variant`` is one of
#: these or None; nothing else is a Commander game.
VARIANTS: tuple[str, ...] = (COMMANDER, BRAWL)

#: CR 903.5a / 903.12d — deck size *including* the commander, minimum and
#: maximum both.
DECK_SIZE: dict[str, int] = {COMMANDER: 100, BRAWL: 60}

#: CR 903.8 — the commander tax, per previous cast from the command zone.
COMMANDER_TAX = 2

#: CR 903.10a — combat damage from one commander that makes its victim lose.
LETHAL_COMMANDER_DAMAGE = 21

#: CR 903.3 / 903.12c — the printed card types a commander may have. Brawl adds
#: planeswalkers. (Vehicles and Spacecraft are listed by the rule too; they are
#: artifact subtypes, so they are admitted by the subtype test in
#: :func:`commander_type_problem` rather than by a card type here.)
_COMMANDER_TYPES: dict[str, tuple[str, ...]] = {
    COMMANDER: ("creature",),
    BRAWL: ("creature", "planeswalker"),
}

#: CR 903.3a — "This card can be your commander." The ability that lets a card
#: outside 903.3's list lead a deck. Matched against oracle text so the rule is
#: one line rather than a list of card names.
CAN_BE_COMMANDER_TEXT = "can be your commander"


def normalize_variant(value: Any) -> str | None:
    """The variant *value* names, or None for "not a Commander game"."""
    if isinstance(value, str) and value.lower() in VARIANTS:
        return value.lower()
    return None


def deck_size(variant: str) -> int:
    """CR 903.5a / 903.12d — the exact deck size, commander included."""
    return DECK_SIZE[normalize_variant(variant) or COMMANDER]


def starting_life(variant: str, player_count: int) -> int:
    """CR 903.7 / 903.12f — the starting life total.

    Commander is 40 however many players there are; Brawl is 25 in a two-player
    game and 30 in a multiplayer one, which is why the seat count is an argument
    rather than something the caller folds in.
    """
    if normalize_variant(variant) == BRAWL:
        return 25 if player_count <= 2 else 30
    return 40


def uses_commander_damage(variant: str) -> bool:
    """CR 903.10a, and CR 903.12h's exception: Brawl games do not use it."""
    return normalize_variant(variant) == COMMANDER


def free_first_mulligan(variant: str) -> bool:
    """CR 903.12g — in any Brawl game a player's first mulligan is free, in a
    two-player game as much as a multiplayer one. (CR 103.5c already gives that
    to every multiplayer game; this is what makes a two-player Brawl differ from
    a two-player Commander game.)"""
    return normalize_variant(variant) == BRAWL


# ---------------------------------------------------------------------------
# Colour identity (CR 903.4)
# ---------------------------------------------------------------------------

# CR 903.4c: reminder text is ignored. It is parenthesized by CR 207.2, which is
# what makes this a rule rather than a heuristic.
_REMINDER_TEXT = re.compile(r"\([^)]*\)")
# One mana symbol, braces and all: {G}, {R/G}, {2/W}, {W/P}, {X}, {T}.
_MANA_SYMBOL = re.compile(r"\{([^}]*)\}")
_COLORS = "WUBRG"
#: The five colours in the order every payload and message spells them.
COLOR_ORDER: tuple[str, ...] = tuple(_COLORS)
#: The basic land types, taken from the one table rather than re-listed. Read by
#: CR 903.5d's test and by CR 903.12e's chosen type.
BASIC_LAND_TYPES: tuple[str, ...] = tuple(_LAND_TYPE_MANA)


def _card_field(card: Any, field: str) -> str:
    """Read *field* off a CardDefinition or a catalog/deck payload mapping.

    Deck construction validates plain dicts (the catalog payload the browser
    also holds) and the engine holds CardDefinitions; CR 903.4 is one rule and
    both callers get the same answer out of it.
    """
    if isinstance(card, Mapping):
        value = card.get(field)
    else:
        value = getattr(card, field, None)
    return "" if value is None else str(value)


def _card_faces(card: Any) -> list[tuple[str, str]]:
    """``(mana_cost, oracle_text)`` for every face of *card* (CR 903.4d/e).

    The back face of a double-faced card counts (903.4d, an explicit exception
    to 712.8a) and so do alternative characteristics such as an adventure's
    (903.4e) — both of which live in ``faces`` here.
    """
    faces = [(_card_field(card, "mana_cost"), _card_field(card, "oracle_text"))]
    raw_faces = card.get("faces") if isinstance(card, Mapping) else getattr(card, "faces", ())
    for face in raw_faces or ():
        faces.append((_card_field(face, "mana_cost"), _card_field(face, "oracle_text")))
    return faces


def _declared_colors(card: Any) -> Iterable[str]:
    """The card's own colours — CR 204's colour indicator and CR 604.3's
    characteristic-defining abilities, both of which 903.4 folds in and neither
    of which is a mana symbol anywhere in the text."""
    colors = card.get("colors") if isinstance(card, Mapping) else getattr(card, "colors", ())
    return (str(c).upper() for c in colors or ())


def color_identity(card: Any) -> frozenset[str]:
    """CR 903.4 — the colour identity of *card*.

    "The color or colors of any mana symbols in that card's mana cost or rules
    text, plus any colors defined by its characteristic-defining abilities or
    color indicator", with reminder text ignored (903.4c), every face included
    (903.4d/e), and the intrinsic mana ability of a basic land type counted
    (CR 305.6 — a Badlands is black-red because of its types, not because of the
    reminder text that restates them).

    A hybrid or Phyrexian symbol contributes every colour in it: ``{R/G}`` is red
    *and* green, which is what makes a Wort deck's identity two colours rather
    than none.
    """
    identity: set[str] = {c for c in _declared_colors(card) if c in _COLORS}
    for land_type, symbol in _LAND_TYPE_MANA.items():
        if land_type in _card_field(card, "type_line").lower():
            identity.add(symbol)
    for mana_cost, oracle_text in _card_faces(card):
        for text in (mana_cost, _REMINDER_TEXT.sub(" ", oracle_text)):
            for symbol in _MANA_SYMBOL.findall(text):
                identity.update(ch for ch in symbol.upper() if ch in _COLORS)
    return frozenset(identity)


def format_identity(identity: Iterable[str]) -> str:
    """A colour identity as a stable, readable string — "WUB", or "colorless"
    for the empty one. Used in the deck-construction messages, so a player is
    told which colour offended rather than that one did."""
    ordered = [c for c in COLOR_ORDER if c in set(identity)]
    return "".join(ordered) if ordered else "colorless"


def produced_mana_colors(card: Any) -> frozenset[str]:
    """The colours of mana a land could produce, for CR 903.5d.

    Read from the ingested ``produced_mana`` when there is one and derived from
    the basic land types otherwise — a Mountain produces red whether or not
    anything recorded it.
    """
    produced = (
        card.get("produced_mana") if isinstance(card, Mapping)
        else getattr(card, "produced_mana", ())
    )
    colors = {str(c).upper() for c in produced or ()}
    for land_type, symbol in _LAND_TYPE_MANA.items():
        if land_type in _card_field(card, "type_line").lower():
            colors.add(symbol)
    return frozenset(c for c in colors if c in _COLORS)


def has_basic_land_type(card: Any) -> bool:
    """Whether *card* has a basic land type (CR 903.5d's subject)."""
    lowered = _card_field(card, "type_line").lower()
    return any(land_type in lowered for land_type in _LAND_TYPE_MANA)


# ---------------------------------------------------------------------------
# Deck construction (CR 903.5, CR 903.12c-e)
# ---------------------------------------------------------------------------


def commander_type_problem(card: Any, variant: str = COMMANDER) -> str | None:
    """Why *card* may not be a commander in *variant*, or None if it may.

    CR 903.3: a legendary creature card, a Vehicle, or a Spacecraft with a
    power/toughness box. CR 903.12c adds planeswalkers for Brawl. CR 903.3a's
    "this card can be your commander" overrides the type requirement outright —
    it "modifies the rules for deck construction", so it is checked first.
    """
    variant = normalize_variant(variant) or COMMANDER
    name = _card_field(card, "name") or "card"
    if CAN_BE_COMMANDER_TEXT in _card_field(card, "oracle_text").lower():
        return None  # CR 903.3a
    type_line = _card_field(card, "type_line").lower()
    if "legendary" not in type_line:
        return f"{name} is not legendary and cannot be a commander (CR 903.3)."
    allowed = _COMMANDER_TYPES[variant]
    if any(card_type in type_line for card_type in allowed):
        return None
    # CR 903.3(b)/(c): Vehicles and Spacecraft are artifact subtypes, so they
    # are named on the type line rather than being card types of their own. A
    # Spacecraft qualifies only with a power/toughness box.
    if "vehicle" in type_line:
        return None
    if "spacecraft" in type_line and _card_field(card, "power"):
        return None
    wanted = " or ".join(allowed)
    return f"{name} is not a legendary {wanted} and cannot be a commander (CR 903.3)."


def can_be_commander(card: Any, variant: str = COMMANDER) -> bool:
    """Whether *card* may be designated a commander in *variant* (CR 903.3)."""
    return commander_type_problem(card, variant) is None


def deck_card_problem(
    card: Any,
    identity: frozenset[str],
    variant: str = COMMANDER,
    *,
    brawl_basic_type: str | None = None,
) -> str | None:
    """Why *card* may not be in a deck led by a commander of *identity*.

    CR 903.5c: every colour in the card's colour identity must be in the
    commander's. CR 903.5d holds a card with a basic land type to a differently
    worded test — *each colour of mana it could produce* must be in the identity
    — which is the same answer for a Mountain and a different one for a land
    whose types and production disagree.

    CR 903.12e is Brawl's exception to 903.5d: a colourless commander lets the
    deck run any number of basic lands of **one** chosen basic land type, named
    by *brawl_basic_type*.
    """
    variant = normalize_variant(variant) or COMMANDER
    name = _card_field(card, "name") or "card"
    if has_basic_land_type(card):
        produced = produced_mana_colors(card)
        if variant == BRAWL and not identity and brawl_basic_type:
            chosen = brawl_basic_type.lower()
            allowed = {_LAND_TYPE_MANA[chosen]} if chosen in _LAND_TYPE_MANA else set()
            if produced <= allowed:
                return None  # CR 903.12e
        outside = produced - identity
        if outside:
            return (
                f"{name} could produce {format_identity(outside)} mana, which is outside "
                f"the commander's colour identity ({format_identity(identity)}) "
                f"(CR 903.5d)."
            )
        return None
    outside = color_identity(card) - identity
    if outside:
        return (
            f"{name}'s colour identity ({format_identity(color_identity(card))}) is "
            f"outside the commander's ({format_identity(identity)}) (CR 903.5c)."
        )
    return None


def deck_identity(commanders: Iterable[Any]) -> frozenset[str]:
    """The colour identity a deck is built to — the union of its commanders'
    (CR 903.5c, read across a partner pair)."""
    identity: set[str] = set()
    for card in commanders:
        identity |= color_identity(card)
    return frozenset(identity)


# ---------------------------------------------------------------------------
# The game operations
# ---------------------------------------------------------------------------

#: Where a commander was headed when CR 903.9 offered its owner the command
#: zone. The prompt names it, so a player declining knows what they are taking.
_DESTINATION_LABEL = {
    "hand": "hand",
    "library": "library",
    "graveyard": "graveyard",
    "exile": "exile",
}

#: The zones CR 903.9a watches. Ordered, because a commander is only ever in one
#: of them and the first hit is the answer.
DEAD_ZONES: tuple[str, ...] = ("graveyard", "exile")


class CommanderMixin:
    """The Commander variant's operations (CR 903). Composed onto ``Game``."""

    # -- the variant itself --------------------------------------------------

    @property
    def is_commander_game(self) -> bool:
        """CR 903.1 — whether these additions apply at all."""
        return normalize_variant(getattr(self, "commander_variant", None)) is not None

    @property
    def uses_commander_damage(self) -> bool:
        """CR 903.10a, less CR 903.12h's Brawl exception."""
        return uses_commander_damage(getattr(self, "commander_variant", None))

    def commander_starting_life(self) -> int:
        """CR 903.7 / 903.12f for this game's seat count."""
        return starting_life(getattr(self, "commander_variant", None), len(self.players))

    # -- the designation (CR 903.3) -----------------------------------------

    def designate_commander(self, player_index: int, card: CardDefinition) -> bool:
        """Designate *card* as ``player_index``'s commander (CR 903.3).

        The designation is recorded before the game begins and is never removed:
        "the card retains this designation even when it changes zones". Returns
        False when the card is already designated for that seat, so a caller run
        twice does not give one seat two of the same commander.
        """
        player = self.players[player_index]
        if any(existing.name == card.name for existing in player.commanders):
            return False
        player.commanders.append(card)
        return True

    def commanders_of(self, player_index: int) -> list[CardDefinition]:
        """The cards designated as ``player_index``'s commanders (CR 903.3)."""
        return list(self.players[player_index].commanders)

    def is_commander_card(self, player_index: int, card: Any) -> bool:
        """Whether *card* is ``player_index``'s commander, in any zone.

        By owner and name rather than by object identity: one
        :class:`CardDefinition` is shared by every deck in the process, so
        identity alone would make an opponent's copy of the same card a
        commander too. CR 903.5b makes the name unique within the seat's deck.
        """
        if card is None or not (0 <= player_index < len(self.players)):
            return False
        name = _card_field(card, "name")
        return any(
            existing.name == name for existing in self.players[player_index].commanders
        )

    def commander_owner_index(self, card: Any) -> int | None:
        """The seat whose commander *card* is, or None. For the callers that do
        not already know the owner (a card sitting in a graveyard)."""
        for seat in range(len(self.players)):
            if self.is_commander_card(seat, card):
                return seat
        return None

    def is_commander_permanent(self, permanent) -> bool:
        """CR 903.3d — "if an effect refers to controlling a commander, it refers
        to a permanent on the battlefield that is a commander".

        Read from the *printed* card, not the effective one: a permanent copying
        a commander is not a commander, and a commander copying something else
        still is (CR 903.3's example). Ownership decides whose it is, so a
        stolen commander is still its owner's.
        """
        if permanent is None or not self.is_commander_game:
            return False
        owner = self.owner_index_of(permanent)
        if owner is None:
            return False
        return self.is_commander_card(owner, permanent.card)

    def commander_color_identity(self, player_index: int) -> frozenset[str]:
        """CR 903.4f — the colour identity of a seat's commander(s). Empty when
        that player has no commander, which is that rule's "undefined"."""
        return deck_identity(self.commanders_of(player_index))

    # -- starting the game (CR 903.6, 903.7) --------------------------------

    def begin_commander_game(self) -> None:
        """CR 903.6 and 903.7: put each designated commander from its deck into
        the command zone, and set each player's starting life total.

        Called before hands are dealt, which is the order the rules put these
        in: 903.6 takes the commander out of the deck *before* the shuffle and
        before 903.7's draw, so a commander can never be in an opening hand.
        """
        if not self.is_commander_game:
            return
        life = self.commander_starting_life()
        for player in self.players:
            player.life = life
            for card in player.commanders:
                # The designated card is pulled out of the library wherever the
                # deck put it; a designation with no copy in the library (a test
                # rig, or a deck built commander-first) still starts in the zone.
                for index, held in enumerate(player.library):
                    if held.name == card.name:
                        player.library.pop(index)
                        break
                if not any(held.name == card.name for held in player.command_zone):
                    player.command_zone.append(card)
            self.log.append(
                f"{player.name} starts at {life} life with "
                f"{len(player.command_zone)} card(s) in the command zone "
                f"(CR 903.6/903.7)"
            )

    def record_starting_decks(self) -> None:
        """Remember the card names each seat started the game with (CR 903.11a).

        Nothing else can answer "was this in your starting deck?" once the game
        has moved cards around, and CR 903.11a bars a card from outside the game
        by exactly that question.
        """
        if not self.is_commander_game:
            return
        for player in self.players:
            player.starting_deck_names = frozenset(
                [card.name for card in player.library]
                + [card.name for card in player.hand]
                + [card.name for card in player.command_zone]
            )

    def outside_the_game_problem(self, player_index: int, card: Any) -> str | None:
        """CR 903.11a — why *card* may not be brought into this Commander game
        from outside it, or None when it may.

        Three bars: a card sharing a name with one in the player's starting deck,
        a card sharing a name with one that player already owns in the game, and
        a card whose colour identity leaves the commander's.
        """
        if not self.is_commander_game:
            return None
        name = _card_field(card, "name")
        player = self.players[player_index]
        if name in player.starting_deck_names:
            return (
                f"{name} has the same name as a card in {player.name}'s starting "
                f"deck (CR 903.11a)."
            )
        # "A card that player **owns** in the current game" — so the
        # battlefield is asked through the control seam and then filtered by
        # ownership (CR 108.3), not read off this player's own battlefield
        # list: a commander of theirs that an opponent has stolen is still a
        # card they own in this game.
        owned = (
            list(player.hand) + list(player.library) + list(player.graveyard)
            + list(player.exile) + list(player.command_zone)
            + [
                perm.card for perm in self.all_permanents()
                if self.owner_index_of(perm) == player_index
            ]
        )
        if any(held.name == name for held in owned):
            return (
                f"{name} has the same name as a card {player.name} owns in this "
                f"game (CR 903.11a)."
            )
        identity = self.commander_color_identity(player_index)
        outside = color_identity(card) - identity
        if outside:
            return (
                f"{name}'s colour identity ({format_identity(color_identity(card))}) "
                f"is outside {player.name}'s commander's "
                f"({format_identity(identity)}) (CR 903.11a)."
            )
        return None

    # -- casting from the command zone (CR 903.8) ---------------------------

    def commander_tax(self, player_index: int, card: Any) -> int:
        """CR 903.8 — the additional generic mana this cast costs: {2} for each
        previous time this player has cast this commander from the command
        zone."""
        if not self.is_commander_game:
            return 0
        name = _card_field(card, "name")
        casts = self.players[player_index].commander_casts.get(name, 0)
        return COMMANDER_TAX * casts

    def may_cast_from_command_zone(self, player_index: int, card: Any) -> bool:
        """CR 903.8 — "a player may cast a commander they own from the command
        zone". Only their own, and only a commander that is actually there."""
        if not self.is_commander_game:
            return False
        name = _card_field(card, "name")
        return self.is_commander_card(player_index, card) and any(
            held.name == name for held in self.players[player_index].command_zone
        )

    def record_commander_cast(self, player_index: int, card: Any) -> None:
        """Count one cast from the command zone, which is what the *next* one's
        tax reads (CR 903.8: "each previous time")."""
        name = _card_field(card, "name")
        casts = self.players[player_index].commander_casts
        casts[name] = casts.get(name, 0) + 1

    # -- returning to the command zone (CR 903.9) ---------------------------

    def commander_zone_change(self, owner_index: int, card: Any, destination: str) -> bool:
        """CR 903.9b — "if a commander would be put into its owner's hand or
        library from anywhere, its owner may put it into the command zone
        instead".

        Returns True when the caller must **not** carry out the move: either the
        card went to the command zone, or the decision is suspended on an
        interactive seat and the card is in no zone until it is answered (the
        same shape as Library of Leng's discard, CR 614).

        Only hand and library are offered. A commander headed for a graveyard or
        exile is *not* replaced — it goes there, and 903.9a's state-based action
        picks it up at the next check. That is the difference between 903.9's two
        halves, and the reason a dying commander's death triggers still fire.

        The rule is an explicit exception to CR 614.5, so it may apply more than
        once to the same event; nothing here consumes a one-shot.
        """
        if not self.is_commander_game or destination not in ("hand", "library"):
            return False
        if not (0 <= owner_index < len(self.players)):
            return False
        if not self.is_commander_card(owner_index, card):
            return False
        return self._offer_command_zone(owner_index, card, destination, rule="903.9b")

    def _offer_command_zone(
        self, owner_index: int, card: Any, destination: str, *, rule: str
    ) -> bool:
        """Put CR 903.9's optional return to its owner. Returns True when the
        caller must not carry out the ordinary move.

        A non-interactive seat answers at once with the default — the command
        zone — so AI and headless play never queue. An interactive seat gets the
        prompt and the card waits in the choice's payload, in no zone.
        """
        player = self.players[owner_index]
        label = _DESTINATION_LABEL.get(destination, destination)
        suspended, _ = offer_replacement_choice(
            self,
            ReplacementChoice(
                kind="commander_zone_change",
                player_index=owner_index,
                options=("command zone", label),
                default_option=0,
                data={"card": card, "destination": destination, "rule": rule},
            ),
        )
        if suspended:
            self.log.append(
                f"{player.name} may put {_card_field(card, 'name')} into the command "
                f"zone instead of their {label} (CR {rule})"
            )
        return True

    def put_into_command_zone(self, owner_index: int, card: CardDefinition) -> None:
        """Put *card* into its owner's command zone (CR 408, CR 903.9)."""
        player = self.players[owner_index]
        player.command_zone.append(card)
        # CR 903.9a is scoped to a card put into a graveyard or exile "since the
        # last time state-based actions were checked". Leaving those zones is
        # what makes the *next* arrival a new one, so the memory is dropped here
        # rather than swept: a commander that comes back and dies again is asked
        # about again.
        player.commander_zone_offered.discard(card.name)
        self.log.append(
            f"{player.name} put {card.name} into the command zone (CR 903.9)"
        )

    def commander_declines_zone_change(
        self, owner_index: int, card: CardDefinition, destination: str
    ) -> None:
        """The other half of CR 903.9's choice: the card goes where it was
        headed after all. Called by the resolver, which is the one completion
        path both an answered prompt and a defaulted seat run through."""
        player = self.players[owner_index]
        if destination == "hand":
            player.hand.append(card)
        elif destination == "library":
            player.library.append(card)
        else:
            getattr(player, destination).append(card)
        self.log.append(
            f"{player.name} kept {card.name} in their "
            f"{_DESTINATION_LABEL.get(destination, destination)} (CR 903.9)"
        )

    def _commander_zone_state_based_actions(self) -> bool:
        """CR 903.9a — a commander in a graveyard or in exile that was put there
        since the last state-based check may be moved to the command zone by its
        owner. Returns True when anything changed.

        The "since the last check" clause is what stops a declined offer being
        re-asked forever: the offer is remembered per commander name and
        forgotten the moment the card leaves those two zones (see
        :meth:`put_into_command_zone` and the sweep below).
        """
        if not self.is_commander_game:
            return False
        changed = False
        for seat, player in enumerate(self.players):
            for commander in list(player.commanders):
                if self._commander_zone_offer_pending(seat, commander.name):
                    # The card is in no zone at all: an interactive owner is
                    # part-way through answering this very offer. Skipping is
                    # what keeps the fixpoint below from reading "not in a
                    # graveyard" as "it left" and forgetting that it was already
                    # asked about — which would re-ask the moment a declining
                    # answer put it back.
                    continue
                zone = self._commander_dead_zone(player, commander)
                if zone is None:
                    # No longer in a graveyard or in exile: a later arrival is a
                    # new event and gets a fresh offer.
                    player.commander_zone_offered.discard(commander.name)
                    continue
                if commander.name in player.commander_zone_offered:
                    continue
                player.commander_zone_offered.add(commander.name)
                held = getattr(player, zone)
                index = next(
                    (i for i, card in enumerate(held) if card.name == commander.name),
                    None,
                )
                if index is None:  # pragma: no cover - _commander_dead_zone found it
                    continue
                card = held.pop(index)
                self._offer_command_zone(seat, card, zone, rule="903.9a")
                changed = True
        return changed

    def _commander_zone_offer_pending(self, seat: int, name: str) -> bool:
        """Whether a CR 903.9 offer for this commander is still waiting on its
        owner — which is also "the card is currently in no zone"."""
        return any(
            choice.kind == "commander_zone_change"
            and choice.player_index == seat
            and _card_field(choice.data.get("card"), "name") == name
            for choice in self.pending_replacement_choices
        )

    @staticmethod
    def _commander_dead_zone(player: PlayerState, commander: CardDefinition) -> str | None:
        """"graveyard" / "exile" if that commander card is in one of them, else
        None. The two zones CR 903.9a names, asked as one question."""
        for zone in DEAD_ZONES:
            if any(card.name == commander.name for card in getattr(player, zone)):
                return zone
        return None

    # -- commander damage (CR 903.10a) --------------------------------------

    def record_commander_combat_damage(self, victim, source, amount: int) -> None:
        """CR 903.10a — tally combat damage dealt to a player by a commander.

        Only combat damage, and only from a commander, counts; the tally is per
        *commander*, not per opponent, because "the same commander" is what the
        rule adds up. Keyed by ``(owner seat, name)`` so two players leading the
        same legend keep separate tallies.
        """
        if amount <= 0 or not self.uses_commander_damage:
            return
        if source is None or not self.is_commander_permanent(source):
            return
        owner = self.owner_index_of(source)
        if owner is None:  # pragma: no cover - is_commander_permanent found one
            return
        key = (owner, source.card.name)
        victim.commander_damage_taken[key] = (
            victim.commander_damage_taken.get(key, 0) + amount
        )

    def commander_damage_dealt(self, victim_index: int, owner_index: int, name: str) -> int:
        """How much combat damage one commander has dealt to one player so far
        (CR 903.10a's running total)."""
        return self.players[victim_index].commander_damage_taken.get((owner_index, name), 0)

    def _commander_damage_state_based_actions(self) -> bool:
        """CR 903.10a — a player who has been dealt 21 or more combat damage by
        the same commander over the course of the game loses. Returns True when
        a player lost here."""
        if not self.uses_commander_damage:
            return False
        changed = False
        for player in self.players:
            if player.lost:
                continue
            for (owner, name), dealt in player.commander_damage_taken.items():
                if dealt < LETHAL_COMMANDER_DAMAGE:
                    continue
                player.lost = True
                self.log.append(
                    f"{player.name} lost the game (903.10a: {dealt} combat damage from "
                    f"{name}, {self.players[owner].name}'s commander)"
                )
                changed = True
                break
        return changed


@replacement_choice("commander_zone_change")
def _resolve_commander_zone_change(game, choice: ReplacementChoice, option_index: int) -> int:
    """Finish CR 903.9's optional return, whichever way it was answered.

    One completion path for both halves of the rule and for both kinds of seat:
    an interactive player's answer and a non-interactive seat's default arrive
    here alike, so "the card is in no zone until this runs" has exactly one
    place that ends.
    """
    card = choice.data["card"]
    destination = choice.data["destination"]
    if option_index == 0:
        game.put_into_command_zone(choice.player_index, card)
    else:
        game.commander_declines_zone_change(choice.player_index, card, destination)
    return 0

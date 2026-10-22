"""The cast the AI is weighing: which mode, under which permission — and the
steps it resolves as.

The floor of the valuation modules (``ai_valuation`` and its family): every
other one reads it, and it reads none of them.

**Two facts about one candidate**, each a context variable rather than a
parameter, set around the single call that builds the candidate and read
where a spell's steps come from: the **mode** of a modal spell
(:func:`considering_mode`, CR 700.2a — every reader answered for mode 0, so
an AI seat cast every modal spell as its first bullet), and the
**permission** a cast out of a zone other than the hand is made under
(:func:`casting_under`, CR 601.3). Both are held with the card, so a
question about some other card asked meanwhile is answered for that card as
printed. :func:`_spell_instructions` and :func:`spell_text` are the seam: a
reader that goes through them cannot forget the mode. (The policy's twins —
the candidate's offers, its mode and its zone as an announcement — are
``ai_actions``'.)

**Which casts a seat may weigh at all** beyond its hand:
:func:`permitted_casts` (every cast an effect allows from outside the hand,
one entry per spell and per price), :func:`hand_waiver` (a cast from the
hand without paying the mana cost) and :func:`castable_commanders`
(CR 903.8).

And the two walkers the readers open a program with: :func:`_effect_steps`
(an instruction's leaf steps, wrappers opened) and :func:`_walk_program`
(every instruction on a program).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .models import CardDefinition
from .oracle import OracleInstruction, compile_card_oracle


# Card types whose *resolution* carries out ``OracleProgram.instructions``.
#
# A permanent's activated ability is mirrored into ``instructions`` as well as
# into ``activated_abilities`` — Royal Assassin's "{T}: Destroy target creature"
# compiles to ``instructions=['destroy_target_permanent']`` — so reading that
# list unguarded would value a creature *in hand* as a removal spell and aim it
# at an opponent it cannot touch until it has been on the battlefield a turn.
SPELL_TYPES = frozenset({"instant", "sorcery"})


#: The mode of a modal spell the policy is weighing right now (CR 601.2b,
#: CR 700.2a), as ``(card, mode index)`` -- or None, which is every moment no
#: modal spell is being weighed.
#:
#: **Why it is here and why it is a context variable.** "What does this spell
#: do?" is asked of a *card* by two dozen functions in this module and by every
#: cast chooser in ``ai_policy``, and for a "Choose one —" spell the answer is
#: a different one per mode: Crosis's Charm is a bounce, a kill or a Shatter.
#: Every one of those readers answered for **mode 0** -- the compiled program's
#: ``instructions`` *are* mode 0's -- so an AI seat cast every modal spell as
#: its first bullet, 34 of 88 modes, and held the card whenever that one bullet
#: had nothing to point at. A parameter would have had to be threaded through
#: every reader and remembered by every later one; this is one fact about one
#: candidate, set around the single call that builds it
#: (:func:`considering_mode`) and read at the two places a spell's steps come
#: from: :func:`_spell_instructions` here and ``ai_actions._announced_mode``
#: there. A reader that goes through either cannot forget the mode.
#:
#: Held **with the card**, so a question about some *other* card asked while
#: this one is being weighed (the spell on top of the stack, the rest of the
#: hand) is answered for that card as printed and never for "its mode 2".
_MODE_CONSIDERED: ContextVar["tuple[CardDefinition, int] | None"] = ContextVar(
    "ai_mode_considered", default=None
)


@contextmanager
def considering_mode(card: CardDefinition, mode_index: "int | None"):
    """Weigh *card* as cast in *mode_index* for the length of the block.

    None is "no mode named" -- a spell that is not modal, or one whose mode an
    opponent chooses (CR 700.2e) -- and reads exactly what every reader read
    before modes were weighed at all.
    """
    token = _MODE_CONSIDERED.set(None if mode_index is None else (card, mode_index))
    try:
        yield
    finally:
        _MODE_CONSIDERED.reset(token)


def mode_considered(card: CardDefinition) -> "int | None":
    """The mode *card* is being weighed in (:func:`considering_mode`), or None."""
    held = _MODE_CONSIDERED.get()
    if held is None:
        return None
    considered, mode_index = held
    return mode_index if considered is card or considered == card else None


def caster_chooses_a_mode(card: CardDefinition) -> bool:
    """Whether casting *card* means choosing one of its modes (CR 601.2b):
    an instant or sorcery printing a "Choose one —" head its **caster**
    answers. Not a spell whose mode an opponent picks (CR 700.2e: Fatal Lore,
    Misfortune, Library of Lat-Nam) -- that cast names no mode, by rule.

    The test ``web/state_view`` makes for the castable highlight, and the one
    ``Game.announceable_modes`` makes before listing anything.
    """
    if card.primary_type not in SPELL_TYPES:
        return False
    program = compile_card_oracle(card)
    return bool(program.modes) and program.mode_chooser is None


def spell_text(card: CardDefinition) -> str:
    """The lower-cased words *card* resolves as: the bullet being weighed for
    a modal spell (:func:`considering_mode`), its whole text otherwise.

    For the one weight in ``ai_policy`` that still probes a text — the
    tutor's reading of printed damage, `ai_scoring._extract_damage`. The cast scorer's
    probes ("draw", "gain … life", "target opponent"), which this was written
    for, are gone: a cast is scored by what a rehearsal of it measures.
    """
    mode_index = mode_considered(card)
    if mode_index is not None:
        modes = compile_card_oracle(card).modes
        if 0 <= mode_index < len(modes):
            return (modes[mode_index].label or "").lower()
    return (card.oracle_text or "").lower()


def _spell_instructions(card: CardDefinition) -> tuple[OracleInstruction, ...]:
    """The instructions resolving *card* **as a spell** carries out.

    Empty for a permanent card; see ``SPELL_TYPES``. For a modal spell being
    weighed in one of its modes (:func:`considering_mode`), that mode's own --
    through ``targeting.announced_mode_instructions``, the reader the cast
    gates and the resolution share, so what the policy values is the steps
    the announcement will run.
    """
    from .targeting import announced_mode_instructions

    if card.primary_type not in SPELL_TYPES:
        return ()
    return tuple(
        announced_mode_instructions(compile_card_oracle(card), mode_considered(card))
    )


def _first(card: CardDefinition, kind: str) -> OracleInstruction | None:
    return next((item for item in _spell_instructions(card) if item.kind == kind), None)


def castable_commanders(game, player_index: int):
    """Each ``(zone_index, card, tax)`` the seat may cast from its command zone
    right now — CR 903.8's grant, with CR 903.8's tax beside it.

    Asked of the engine's own commander seam (``may_cast_from_command_zone``,
    ``commander_tax``) rather than derived a second time, so the AI is offered
    exactly the casts the browser's zone badge offers a human seat
    (``cast_permissions.playable_from_zones``) and the tax it must price is the
    one the cast path will charge. Empty outside a Commander game — the zone is
    empty and the seam answers False — so an ordinary duel never reads it.
    """
    player = game.players[player_index]
    return tuple(
        (index, card, game.commander_tax(player_index, card))
        for index, card in enumerate(player.command_zone)
        if game.may_cast_from_command_zone(player_index, card)
    )


@dataclass(frozen=True)
class PermittedCast:
    """One cast a seat may make because an **effect** allows it (CR 601.3):
    a card outside its hand it may cast or play, or a card in its hand it may
    cast without paying its mana cost.

    What the policy needs to build a candidate that the cast path will accept,
    and none of it is derivable from the card alone:

    * **where the card is** — ``zone``, ``owner_seat`` and ``index``. The pile
      is the grantee's own on every grant but the cross-seat one (Grinning
      Totem leaves the card in the *searched* player's exile pile);
    * **what it is cast as** — ``spell``, the half for a split card (CR 709.3)
      and ``held`` itself otherwise;
    * **what the cast is charged** — ``permission``: its required alternative
      cost (CR 118.9b; flashback, CR 702.34a), its waiver, or neither;
    * **the announcement that selects that permission** — ``alternative_cost``,
      CR 601.2b's choice, in the cast path's own spelling. A card may be
      covered twice (a flashback card under Yawgmoth's Will) and those are two
      casts at two prices.
    """

    zone: str
    owner_seat: int
    index: int
    held: CardDefinition
    spell: CardDefinition
    permission: object
    alternative_cost: bool = False

    @property
    def cost(self):
        """The alternative cost the permission requires, or None."""
        return getattr(self.permission, "cost", None)

    @property
    def waives_mana_cost(self) -> bool:
        """Whether the cast is made "without paying its mana cost".

        A grant's ``free`` flag — and **every** permission over the hand,
        which is the cast path's own reading (``cast_permissions.permission_for``
        answers the hand zone for cost waivers alone, and ``_cast_onto_stack``
        takes whatever it answers as one)."""
        return self.cost is None and (
            bool(getattr(self.permission, "free", False)) or self.zone == "hand"
        )

    @property
    def expires(self) -> bool:
        """Whether the permission has a stated duration (CR 611.2a) — "until
        end of turn", "until your next turn" — as opposed to lasting for as
        long as the card stays where it is (flashback, a static ability of a
        permanent)."""
        return getattr(self.permission, "duration", None) is not None


def permitted_casts(game, player_index: int) -> "tuple[PermittedCast, ...]":
    """Every cast *player_index* may make from **outside its hand** right now
    (CR 601.3), one entry per spell and per price.

    The list is the engine's: ``cast_permissions.playable_from_zones``, the
    one the browser's zone badges are built from, so an AI seat is offered
    exactly the cards a human seat is. The command zone is left to
    :func:`castable_commanders` — CR 903.8 is a rule rather than a permission,
    and it carries a tax where these carry a price.

    **Which permission a cast will be made under is the cast path's answer,
    mirrored rather than re-decided.** ``_cast_onto_stack`` finds a card *by
    name*, in the caster's own pile first and then the others', and takes the
    first permission that covers it — the first that *requires an alternative
    cost* when the caster announced one (CR 601.2b, ``permission_for``'s
    ``costed``). So for each spell name in each zone:

    * the **bare** cast is the first covered copy in that scan order, under the
      first permission that answers for it — and a later copy is not offered
      again, because the cast could not reach it;
    * where that permission asks no alternative cost and another one does (a
      flashback card under Yawgmoth's Will, an opened graveyard), the cast
      **announcing an alternative cost** is offered beside it.

    Lands are included (``mode="play"``): the land-drop chooser reads them.
    """
    from .cast_permissions import permission_for, playable_from_zones
    from .faces import castable_faces

    found: list[PermittedCast] = []
    bare_seen: set[tuple[str, str]] = set()
    costed_seen: set[tuple[str, str]] = set()
    for entry in playable_from_zones(game, player_index):
        zone = entry["zone"]
        if zone == "command":
            continue
        owner = entry["owner_seat"]
        index = entry["index"]
        pile = getattr(game.players[owner], zone)
        if not 0 <= index < len(pile):
            continue
        held = pile[index]
        as_land = held.primary_type == "land"
        for spell in castable_faces(held):
            key = (zone, spell.name)
            first = permission_for(
                game, player_index, held, zone, as_land=as_land, spell=spell,
            )
            if first is None or first.zone_seat != owner:
                continue
            if key not in bare_seen:
                bare_seen.add(key)
                found.append(PermittedCast(
                    zone=zone, owner_seat=owner, index=index, held=held,
                    spell=spell, permission=first,
                    alternative_cost=first.cost is not None,
                ))
                if first.cost is not None:
                    costed_seen.add(key)
            if key in costed_seen:
                continue
            costed = permission_for(
                game, player_index, held, zone, as_land=as_land, spell=spell,
                costed=True,
            )
            if costed is None or costed.zone_seat != owner:
                continue
            costed_seen.add(key)
            found.append(PermittedCast(
                zone=zone, owner_seat=owner, index=index, held=held,
                spell=spell, permission=costed, alternative_cost=True,
            ))
    return tuple(found)


def hand_waiver(
    game, player_index: int, held: CardDefinition, spell: CardDefinition,
    hand_index: int,
) -> "PermittedCast | None":
    """The waiver a cast of *spell* out of *player_index*'s hand will be made
    under ("Any player may cast creature spells with mana value 3 or less
    without paying their mana costs", Aluren; "you may cast spells from your
    hand without paying their mana costs", Chandra, Flame's Catalyst), or None.

    The cast path's own default, mirrored: a cast that announces nothing takes
    a hand waiver whenever one covers the card, **except for an {X} spell** —
    a waived {X} is locked to 0 (CR 107.3b), so that one defaults to paying.
    Never a land, which is played rather than cast.
    """
    from .cast_permissions import permission_for

    if spell.primary_type == "land" or "{X}" in (spell.mana_cost or "").upper():
        return None
    permission = permission_for(game, player_index, held, "hand", spell=spell)
    if permission is None:
        return None
    return PermittedCast(
        zone="hand", owner_seat=player_index, index=hand_index, held=held,
        spell=spell, permission=permission,
    )


#: The permission the cast being weighed would be made under (CR 601.3), as a
#: :class:`PermittedCast` -- or None, which is every ordinary cast from hand.
#:
#: The zone's twin of :data:`_MODE_CONSIDERED`, a context variable for its
#: reason: *where a spell is cast from* and *what that cast is charged* are
#: asked by a dozen choosers underneath the candidate builder -- the spec (a
#: spell leaving a graveyard is not a card in it, CR 601.2a), the prohibitions
#: (a row may bind one zone), the price, the X -- and each took a card. Held
#: with the spell, by identity, so a question about another card asked while
#: this one is weighed is answered for a cast from hand.
_CAST_WEIGHED: ContextVar["PermittedCast | None"] = ContextVar(
    "ai_cast_weighed", default=None
)


@contextmanager
def casting_under(permitted: "PermittedCast | None"):
    """Weigh a cast as made under *permitted* for the length of the block.
    None is an ordinary cast from hand, which reads what every reader read
    before a seat could cast from anywhere else."""
    token = _CAST_WEIGHED.set(permitted)
    try:
        yield
    finally:
        _CAST_WEIGHED.reset(token)


def cast_weighed(card: CardDefinition) -> "PermittedCast | None":
    """The permission *card* is being weighed under (:func:`casting_under`),
    or None."""
    held = _CAST_WEIGHED.get()
    if held is None or held.spell is not card:
        return None
    return held


def _effect_steps(instruction: OracleInstruction) -> tuple[OracleInstruction, ...]:
    """*instruction*'s leaf steps, wrappers (``sequence``, ``if_then``,
    ``may``) opened and themselves left out."""
    found: list[OracleInstruction] = []

    def walk(item) -> None:
        payload = getattr(item, "payload", None) or {}
        nested = [
            payload.get(key)
            for key in ("steps", "then", "else", "action", "otherwise", "effect")
            if isinstance(payload.get(key), (list, tuple))
        ]
        if not nested:
            found.append(item)
            return
        for group in nested:
            for child in group:
                if hasattr(child, "kind"):
                    walk(child)

    walk(instruction)
    return tuple(found)


def _walk_program(program):
    """Every instruction on a program, wrappers opened."""
    def walk(instructions):
        for instruction in instructions:
            yield instruction
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = (instruction.payload or {}).get(key)
                if isinstance(nested, (list, tuple)):
                    yield from walk(nested)

    yield from walk(program.instructions)
    for ability in program.activated_abilities:
        if ability.instruction is not None:
            yield from walk([ability.instruction])
    for trigger in program.triggered_abilities:
        if trigger.instruction is not None:
            yield from walk([trigger.instruction])


__all__ = [
    "SPELL_TYPES",
    "PermittedCast",
    "cast_weighed",
    "castable_commanders",
    "casting_under",
    "hand_waiver",
    "permitted_casts",
]

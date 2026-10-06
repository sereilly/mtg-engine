"""Which targets did this stack object choose? (CR 115.1, CR 601.2c.)

One reader, because the question had four partial ones and each declined a
different half of it:

* ``targeting.single_spell_target`` answers "what is this object's *only*
  target?" and refuses everything modal, divided, graveyard-borne or aimed at
  the stack;
* ``targeting.spell_targets`` answers for a spell and never for an ability;
* ``legality.illegal_targets_refusal`` has to know an object's targets to say
  they are all illegal, and declined every object that may target a player
  (it asks this module now: :func:`announcement_targets`);
* ``mixins/helpers._announce_targeting`` reads the stamped ids and believes a
  seat only when the derived spec is a player kind.

A :class:`~engine.game_types.StackItem` records an announcement across several
channels — two scalar fields that double as a *battlefield* beside a permanent
index, a list of stamped ids, graveyard stamps, a stack reference, a divided
list in ``choices`` and one :class:`~engine.game_types.ChosenMode` per chosen
mode. None of them says on its own whether what it holds is a **target**: the
same fields carry a cost a spell sacrificed, a "source of your choice"
(CR 609.7a), the object a Clone copies, and the slot a combat trigger threads
its own source through. So the answer is built from two pieces of evidence that
must agree:

1. **the compiled program** says the object announces a picker of some kind
   (``derive_cast_spec`` for a spell, the instruction for an ability, the
   chosen mode for either), and that picker is not a cost, a chosen source or
   an optional copy; and
2. **the printed words** say "target" about a choice this object makes
   (CR 115.1a/c/d), or the object is an Aura spell (CR 115.1b).

Either alone over-answers. The spec comes from a kind table that fills in a
picker where the line said "that creature"; the word appears in "becomes the
target of", in "spells that target", and in the quoted ability a card grants to
something else.

**None is a refusal, never "no targets".** It is returned where this engine
cannot say — a hook-keyed ability with no compiled instruction — and every
caller must treat it as "do nothing", for ``single_spell_target``'s stated
reason: an under-answer is a narrower card, an over-answer is a card acting on
objects it was never allowed to touch.

**What this cannot see, stated rather than hidden.** A target the engine itself
picks *at resolution* — a handler's fallback scan behind a triggered ability
that announced nothing, a reflexive ability that never becomes a stack object —
is not recorded on any stack item, so it is not here. That is CR 603.3d not
being modelled for those abilities, and it is measured by
``tests/engine/test_stack_targets.py`` rather than papered over.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from .divided_damage import DIVIDED_TARGETS, divided_entry, divided_entry_id
from .modal_triggers import ENTRY_TRIGGER_CONDITIONS, modal_trigger_modes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .game_types import StackItem


#: The trigger-context key the object rides under when "a player chooses one
#: or more targets" is announced (``Game.announce_targets_chosen``). The
#: ``StackItem`` itself, by identity: CR 603.10's look-back for this event is at
#: the object the targets were chosen for, and a stack item compares by value,
#: so two copies of one spell aimed at one creature are *equal* and only ``is``
#: tells them apart. The reader re-checks that it is still on the stack.
TARGETS_CHOSEN_ITEM = "targets_chosen_item"

#: …and the key present when the choice was a change that "doesn't trigger
#: abilities of permanents named <name>" (Psychic Battle's last sentence). The
#: value is that name — the changing permanent's **effective** name, read at
#: the moment of the change — and ``events._player_chooses_targets_filter``
#: compares each observer's effective name against it.
TARGETS_CHANGED_SILENTLY_FOR = "targets_changed_silently_for"


@dataclass(frozen=True)
class ChosenTarget:
    """One target of one stack object, with where the object records it.

    ``kind`` is what was chosen — ``"permanent"`` (by ``permanent_id``),
    ``"player"`` (by ``seat``), ``"graveyard"`` (a
    :class:`~engine.game_types.GraveyardTarget` stamp) or ``"stack"`` (another
    stack object, by identity).

    ``channel`` and ``position`` are the write-back address: which field of the
    item holds this target and which slot of it, so a change (CR 115.7) rewrites
    the announcement it read rather than a second copy of it. ``mode`` is the
    position in ``StackItem.chosen_modes`` for a target a "choose one or more"
    mode chose, else None.
    """

    kind: str
    permanent_id: int | None = None
    seat: int | None = None
    stamp: object = None
    stack_item: object = None
    channel: str = "item"
    position: int = 0
    mode: int | None = None

    def same_object(self, other: "ChosenTarget") -> bool:
        """Whether two descriptors name the same object or player (CR 115.3)."""
        if self.kind != other.kind:
            return False
        if self.kind == "permanent":
            return self.permanent_id == other.permanent_id
        if self.kind == "player":
            return self.seat == other.seat
        if self.kind == "stack":
            return self.stack_item is other.stack_item
        return self.stamp == other.stamp


# ---------------------------------------------------------------------------
# Evidence 2: the printed words
# ---------------------------------------------------------------------------

_REMINDER_TEXT = re.compile(r"\([^)]*\)")
_TARGET_WORD = re.compile(r"\btargets?\b")
#: Both quote pairs, for ``targeting._QUOTED_ABILITY``'s reason: ingested oracle
#: text prints the curly ones and a hand-written fixture the straight.
_QUOTED_ABILITY = re.compile("[\"“][^\"”]*[\"”]")

#: Printed uses of the word that are **not** a choice this object makes. Each
#: is erased rather than vetoing the line, because a sentence may use the word
#: both ways ("Whenever this creature becomes the target of a spell, it deals 2
#: damage to target player").
#:
#: * "can't be the target(s) of …" — a prohibition on somebody else's object;
#: * "becomes the target of …" — a trigger condition (CR 603.2);
#: * "(spells|abilities) … that target(s) …" / "that targets only …" — a
#:   description of somebody else's object;
#: * "chooses one or more targets" — Psychic Battle's own condition;
#: * "for each target [beyond the first]" — a cost counted off the targets the
#:   sentence behind it chooses (Fireball, Phyrexian Purge), not a second
#:   choice;
#: * "the target or targets" / "change the target of" / "changing targets" /
#:   "that spell's target" / "that target" / "the new target" / "a single
#:   target" / "only one target" / "a new target" / "new targets" — CR 115.7's
#:   vocabulary for the targets of the object being re-aimed. The object doing
#:   the re-aiming says "target spell" for its own choice, which none of these
#:   erase.
_NOT_A_CHOICE = re.compile(
    r"can't be the targets? of[^.;]*"
    r"|becomes? the targets? of[^,.;]*"
    r"|(?:spells?|abilit(?:y|ies))[^.,;]*? that (?:can )?targets?(?: only)?[^.,;]*"
    r"|that targets? only[^.,;]*"
    r"|chooses? one or more targets"
    r"|for each target(?: beyond the first)?\b"
    r"|the target or targets"
    r"|change (?:the|a) target of"
    r"|changing targets"
    r"|(?:that|this) (?:spell|ability)'s targets?"
    r"|(?:that|the new|a new|a single|only one|its) target\b"
    r"|new targets"
)


def names_a_target(text: str | None) -> bool:
    """Whether printed *text* uses "target" about a choice its own object makes.

    The word-level half of this module's two-evidence rule. Deliberately the
    *weak* question — it does not say which noun phrase, how many, or whether
    the engine models the choice — because the strong one is the compiled
    spec's, and the two are only ever read together.
    """
    return bool(text) and _target_instances(text) > 0


@lru_cache(maxsize=None)
def _target_instances(text: str) -> int:
    """How many times *text* prints the word about a choice of its own.

    Cached on the line: this is asked every time an object is put on the stack
    (``Game.announce_targets_chosen``), the lines are a few thousand immutable
    strings, and three regex passes per push is the whole cost of the reader.
    """
    line = _REMINDER_TEXT.sub("", text.lower())
    line = _QUOTED_ABILITY.sub("", line)
    line = _NOT_A_CHOICE.sub("", line)
    return len(_TARGET_WORD.findall(line))


# ---------------------------------------------------------------------------
# Evidence 1: the compiled program
# ---------------------------------------------------------------------------

#: Spec flags under which the picker is not a target at all: CR 609.7a's
#: "source of your choice" is chosen, not targeted, and ``optional`` is Clone's
#: copy-on-enter choice. A cost is asked through ``targeting.spec_is_a_cost``.
#:
#: ``requires_source`` is deliberately **not** here although
#: ``legality._UNTARGETED_SPEC_FLAGS`` lists it: that flag sits on a spec whose
#: own picker *is* a target ("the next time a source of your choice would deal
#: damage to **any target**", Honorable Passage) and says a source is asked for
#: beside it. The source rides ``choices["chosen_source"]``, never these fields.
_UNTARGETED_SPEC_FLAGS = ("source_of_choice", "optional")


def _spec_targets(spec: dict | None) -> bool:
    """Whether *spec* describes a picker that is a CR 115.1 target."""
    from .targeting import spec_is_a_cost

    if not spec or spec.get("kind") in (None, "none", "modal", "hand_card", "faces"):
        return False
    if spec_is_a_cost(spec):
        return False
    return not any(spec.get(flag) for flag in _UNTARGETED_SPEC_FLAGS)


@dataclass(frozen=True)
class _Announcement:
    """One spec's worth of an object's announcement: what it may choose and
    which fields hold what it chose.

    ``holder`` is the item itself, or one of its ``chosen_modes`` — both carry
    the same three target fields under the same names, which is what lets one
    reader serve both. ``mode`` is that entry's position, or None.
    ``instruction`` is the step the spec was derived from where there is one
    (an ability, or a mode), for the enumeration that needs its narrowing.
    """

    spec: dict
    holder: object
    mode: int | None = None
    instruction: object = None


def announcements(item: "StackItem") -> "tuple[_Announcement, ...] | None":
    """Every targeted announcement *item* made, or None when this engine cannot
    say (see the module docstring).

    Empty means the object targets nothing: Wrath of God, a creature spell, a
    modal spell whose chosen mode names no target, an unkicked spell whose only
    target is kicked-only (CR 702.33g).
    """
    from .oracle import compile_card_oracle
    from .targeting import _from_instructions, derive_cast_spec

    card = getattr(item, "card", None)
    if card is None:
        return None
    if getattr(item, "is_ability", False):
        instruction = getattr(item, "ability_instruction", None)
        if instruction is None:
            # A hook-keyed object has no compiled program to ask.
            return None
        modes = modal_trigger_modes(instruction)
        if modes:
            # CR 700.2b: the mode is chosen as the ability goes on the stack,
            # and until it is, no target has been either.
            index = getattr(item, "chosen_mode_index", None)
            if not isinstance(index, int) or not 0 <= index < len(modes):
                return ()
            mode = modes[index]
            spec = _from_instructions((mode["instruction"],))
            if not _spec_targets(spec) or not names_a_target(mode.get("label")):
                return ()
            return (_Announcement(spec, item, instruction=mode["instruction"]),)
        spec = _from_instructions((instruction,))
        if not _spec_targets(spec) or not names_a_target(getattr(item, "ability_text", None)):
            return ()
        return (_Announcement(spec, item, instruction=instruction),)

    program = compile_card_oracle(card)
    type_line = (card.type_line or "").lower()
    if "instant" in type_line or "sorcery" in type_line:
        if program.modes:
            found: list[_Announcement] = []
            chosen = tuple(getattr(item, "chosen_modes", ()) or ())
            if chosen:
                entries = [(mode.index, mode, position) for position, mode in enumerate(chosen)]
            else:
                # The legacy single-mode spelling, and a cast that named no
                # mode at all resolves mode 0 (``_select_executable_instruction``).
                index = getattr(item, "chosen_mode_index", None)
                entries = [(index if isinstance(index, int) else 0, item, None)]
            for index, holder, position in entries:
                if not 0 <= index < len(program.modes):
                    continue
                option = program.modes[index]
                if option.instruction is None:
                    continue
                spec = _from_instructions((option.instruction,))
                if _spec_targets(spec) and names_a_target(option.label):
                    found.append(
                        _Announcement(spec, holder, mode=position, instruction=option.instruction)
                    )
            return tuple(found)
        spec = derive_cast_spec(
            card, program,
            # CR 702.33g: a kicked-only target is a target only of a spell that
            # was kicked, and the announcement is the only record of that.
            optional_cost_payments=(getattr(item, "choices", None) or {}).get(
                "additional_costs_paid"
            ) or {},
        )
        if not _spec_targets(spec) or not _spell_names_a_target(card):
            return ()
        return (_Announcement(spec, item),)

    # A permanent spell. CR 115.1b: an Aura spell is always targeted, by its
    # enchant ability — the one case with no printed "target" at all.
    spec = derive_cast_spec(
        card, program,
        optional_cost_payments=(getattr(item, "choices", None) or {}).get(
            "additional_costs_paid"
        ) or {},
    )
    if not _spec_targets(spec):
        return ()
    if "aura" in type_line:
        # Either enchant spelling: a permanent on the battlefield, or "enchant
        # creature card in a graveyard" (Animate Dead) — the spec's kind says
        # which channel the target is in.
        return (_Announcement(spec, item),)
    # Any other permanent spell targets nothing by the rules — and in this
    # engine **carries its entry trigger's target**, announced as it is cast
    # (``targeting._cast_target_spec``'s last branch; the standing
    # approximation ``_apply_self_enters_battlefield_triggers`` documents).
    # That announcement is the only moment the choice exists as a stack
    # object's, so it is reported here, on the evidence of the trigger's own
    # printed line.
    for trig in program.triggered_abilities:
        if (
            trig.condition.kind in ENTRY_TRIGGER_CONDITIONS
            and trig.supported
            and trig.instruction is not None
            and names_a_target(trig.source_line)
        ):
            return (_Announcement(spec, item),)
    return ()


def _spell_names_a_target(card) -> bool:
    """Whether an instant or sorcery's own effect lines say "target".

    ``targeting.line_names_a_cast_target`` over ``legality._cast_lines`` — the
    forward ratchet's own probe, so "this card targets as it is cast" has one
    reading here and in ``tests/engine/test_targeting.py``.
    """
    from .legality import _cast_lines
    from .targeting import line_names_a_cast_target

    return any(
        line_names_a_cast_target(_REMINDER_TEXT.sub("", line))
        for line in _cast_lines(card)
    )


# ---------------------------------------------------------------------------
# The fields
# ---------------------------------------------------------------------------


def _ids(holder) -> list:
    ids = getattr(holder, "target_permanent_id", None)
    if ids is None:
        return []
    return list(ids) if isinstance(ids, (list, tuple)) else [ids]


def _stamps(holder) -> list:
    stamps = getattr(holder, "target_graveyard_card", None)
    if stamps is None:
        return []
    return list(stamps) if isinstance(stamps, (list, tuple)) else [stamps]


def _seat(game: "Game", holder) -> int | None:
    seat = getattr(holder, "target_player_index", None)
    if isinstance(seat, int) and 0 <= seat < len(game.players):
        return seat
    return None


def _permanents(holder, mode) -> list[ChosenTarget]:
    return [
        ChosenTarget("permanent", permanent_id=int(permanent_id), position=position, mode=mode)
        for position, permanent_id in enumerate(_ids(holder))
        if isinstance(permanent_id, int)
    ]


def _read(game: "Game", item: "StackItem", announcement: _Announcement) -> list[ChosenTarget]:
    """The targets one announcement recorded, read off the channel its spec
    says they are in.

    The spec decides *which* channel is a target, and that is the whole point:
    ``target_player_index`` beside a permanent index is a battlefield, and
    beside a player-kind spec with no permanent it is a face.
    """
    from .targeting import (
        GRAVEYARD_TARGET_KIND, ROLES_TARGET_KIND, _PLAYER_TARGET_SPEC_KINDS,
        role_is_seat, spec_roles,
    )

    spec, holder, mode = announcement.spec, announcement.holder, announcement.mode
    kind = spec.get("kind")

    if kind == ROLES_TARGET_KIND:
        # One object per role, positional in role order across the id list and
        # the graveyard-stamp list; a **player** role answers with the scalar
        # seat instead (``activation._role_announcement_stamps``).
        found: list[ChosenTarget] = []
        ids, stamps = _ids(holder), _stamps(holder)
        for position, role in enumerate(spec_roles(spec)):
            if role_is_seat(role):
                seat = _seat(game, holder)
                if seat is not None:
                    found.append(ChosenTarget("player", seat=seat, channel="role", position=position, mode=mode))
                continue
            if position < len(ids) and isinstance(ids[position], int):
                found.append(ChosenTarget(
                    "permanent", permanent_id=int(ids[position]),
                    channel="role", position=position, mode=mode,
                ))
            elif position < len(stamps) and stamps[position] is not None:
                found.append(ChosenTarget(
                    "graveyard", stamp=stamps[position],
                    channel="role", position=position, mode=mode,
                ))
        return found

    if kind == GRAVEYARD_TARGET_KIND:
        return [
            ChosenTarget("graveyard", stamp=stamp, channel="graveyard", position=position, mode=mode)
            for position, stamp in enumerate(_stamps(holder))
            if stamp is not None
        ]

    stack_target = getattr(holder, "target_stack_item", None)
    if kind == "stack":
        if stack_target is None:
            return []
        return [ChosenTarget("stack", stack_item=stack_target, channel="stack", mode=mode)]
    if kind == "spell_or_permanent":
        if stack_target is not None:
            return [ChosenTarget("stack", stack_item=stack_target, channel="stack", mode=mode)]
        return _permanents(holder, mode)

    divided = (getattr(item, "choices", None) or {}).get(DIVIDED_TARGETS) if holder is item else None
    if divided:
        # A divided announcement records each target separately and takes
        # precedence over the scalar fields (``CHOICE_KEYS``).
        found = []
        for position, entry in enumerate(divided):
            seat, permanent_index, _share = divided_entry(entry)
            if permanent_index is None:
                if isinstance(seat, int) and 0 <= seat < len(game.players):
                    found.append(ChosenTarget("player", seat=int(seat), channel="divided", position=position))
                continue
            permanent_id = divided_entry_id(entry)
            if permanent_id is None:
                # An entry written before the id stamp existed: resolved once
                # through the seam's bridge, as ``_lone_permanent_target`` does.
                permanent = game.permanent_at(int(seat), permanent_index)
                permanent_id = None if permanent is None else permanent.permanent_id
            if isinstance(permanent_id, int):
                found.append(ChosenTarget(
                    "permanent", permanent_id=permanent_id, channel="divided", position=position,
                ))
        return found

    permanents = _permanents(holder, mode)
    if kind in _PLAYER_TARGET_SPEC_KINDS and not spec.get("land_filter"):
        # A face *or* an object ("any target", "player or planeswalker"): the
        # permanent ids decide, and only without any is the seat a chosen
        # player rather than a battlefield.
        #
        # A spec that is a **player and nothing else** never reads an id. One
        # can be there all the same — a combat fire site threads the trigger's
        # own source through the target fields so the resolution can find it
        # again ("target opponent gains control of **it**", Goblin Cadets) —
        # and that is a reference, not something "target opponent" chose.
        if permanents and kind != "player":
            return permanents
        seat = _seat(game, holder)
        if seat is None:
            return []
        return [ChosenTarget("player", seat=seat, channel="player", mode=mode)]
    return permanents


def announcement_targets(
    game: "Game", item: "StackItem", spec: dict, holder, *, mode: int | None = None,
) -> "tuple[ChosenTarget, ...]":
    """The targets **one** announcement of *item* recorded, read off the
    channel *spec* says they are in.

    :func:`chosen_targets` for a caller that already holds the announcement —
    ``legality.illegal_targets_refusal`` walks a spell one chosen mode at a
    time, each with the spec the cast gate derived for it, and has to read
    each mode's targets against **that** spec rather than re-derive one. It
    is the same reader (:func:`_read`), which is the point: whether
    ``target_player_index`` is a chosen player or the battlefield a permanent
    sits on is decided in one place, and the rule that re-asks a target's
    legality must not hold a second opinion about which targets there are.
    """
    return tuple(_read(game, item, _Announcement(spec, holder, mode=mode)))


def chosen_targets(game: "Game", item: "StackItem") -> "tuple[ChosenTarget, ...] | None":
    """Every target *item* chose (CR 601.2c / 602.2b / 603.3d), in announcement
    order, or None when this engine cannot say.

    ``()`` is a real answer: the object targets nothing, or it may target and
    named nobody ("up to one target creature" at zero — CR 115.6: "targeted
    only if one or more targets have been chosen for it").

    A target that has since left its zone is **still listed**: CR 115.9a counts
    what was chosen as the object was put on the stack, and CR 115.7a lets a
    target be changed "even if the original target is itself illegal by then".
    """
    announced = announcements(item)
    if announced is None:
        return None
    found: list[ChosenTarget] = []
    for announcement in announced:
        found.extend(_read(game, item, announcement))
    return tuple(found)


def has_targets(game: "Game", item: "StackItem") -> bool:
    """Whether *item* chose one or more targets (CR 115.6) — False where the
    engine cannot say, which is the safe direction for a trigger."""
    return bool(chosen_targets(game, item))


# ---------------------------------------------------------------------------
# CR 115.7 — changing the targets an object chose
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeSlot:
    """One target of an object being re-aimed, with what it may be changed to.

    ``candidates`` are the **other** legal targets for this slot (CR 115.7a:
    "each target can be changed only to another legal target"), each carrying
    the same write-back address as ``current`` so applying a pick needs nothing
    but the pick.
    """

    current: ChosenTarget
    candidates: tuple[ChosenTarget, ...]


def target_label(game: "Game", target: ChosenTarget) -> str:
    """How a target reads in a log line or a prompt."""
    if target.kind == "player":
        return game.players[target.seat].name if target.seat is not None else "a player"
    if target.kind == "permanent":
        permanent = game.permanent_by_id(target.permanent_id)
        if permanent is None:
            return "a permanent that has left"
        # Whose it is, because a re-aim is usually between two look-alikes and
        # "from Grizzly Bears to Grizzly Bears" says nothing.
        seat = game.controller_index_of(permanent)
        name = permanent.effective_card.name
        return name if seat is None else f"{game.players[seat].name}'s {name}"
    if target.kind == "stack":
        card = getattr(target.stack_item, "card", None)
        return card.name if card is not None else "a spell"
    card = getattr(target.stamp, "card", None)
    if card is None:
        return "a card in a graveyard"
    seat = getattr(target.stamp, "seat", None)
    if isinstance(seat, int) and 0 <= seat < len(game.players):
        return f"{card.name} in {game.players[seat].name}'s graveyard"
    return f"{card.name} in a graveyard"


def _printed_target_instances(item: "StackItem") -> int | None:
    """How many times the object's own text prints the word "target" about a
    choice it makes, or None for an Aura spell (CR 115.1b prints none).

    CR 115.3 keys everything on the *instance* of the word: one instance may
    not name the same object twice, two instances may. This engine keeps one
    spec per announcement, so an object printing two instances ("Choose target
    opponent … destroy target creature that player controls", Keeper of the
    Dead) has a second slot the spec in hand does not describe — and offering
    that slot the first one's candidates would re-aim it at something the card
    never let it choose.
    """
    from .legality import _cast_lines
    from .oracle import compile_card_oracle
    from .targeting import line_names_a_cast_target

    def count(text: str | None) -> int:
        return _target_instances(text) if text else 0

    if getattr(item, "is_ability", False):
        modes = modal_trigger_modes(getattr(item, "ability_instruction", None))
        if modes:
            index = getattr(item, "chosen_mode_index", None)
            if isinstance(index, int) and 0 <= index < len(modes):
                return count(modes[index].get("label"))
            return 0
        return count(getattr(item, "ability_text", None))
    card = item.card
    type_line = (card.type_line or "").lower()
    if "instant" in type_line or "sorcery" in type_line:
        # Only the lines that name a *cast* target: an instant's own triggered
        # line ("When a spell or ability an opponent controls causes you to
        # discard this card, … deals 4 damage to any target", Guerrilla
        # Tactics) is another object's choice, made if it ever triggers.
        return sum(
            count(line) for line in _cast_lines(card)
            if line_names_a_cast_target(_REMINDER_TEXT.sub("", line))
        )
    if "aura" in type_line:
        return None
    program = compile_card_oracle(card)
    return sum(
        count(trig.source_line)
        for trig in program.triggered_abilities
        if trig.condition.kind in ENTRY_TRIGGER_CONDITIONS
        and trig.supported and trig.instruction is not None
    )


def _is_triggered(item: "StackItem") -> bool:
    """Whether *item* is a triggered ability — the split ``web/serialization``
    draws from the same label prefix."""
    return str(getattr(item, "ability_effect_kind", "") or "").startswith("triggered")


def _candidates(
    game: "Game", item: "StackItem", announcement: _Announcement, current: ChosenTarget,
) -> "list[ChosenTarget] | None":
    """Every target *current*'s slot could legally have been (CR 115.7a), read
    through ``_enumerate_targets`` — the one list the picker and the two
    announcement gates already share — or None where that list cannot be built
    for this object.

    An **ability** is enumerated the way its own announcement was: against its
    instruction's printed restriction, with the seats its firing event froze
    ("defending player controls", "that player controls") supplied on the spec
    exactly as ``_choose_trigger_targets`` supplies them. A narrowing that
    announcement declined to enumerate is one this declines too — a printed
    controller the spec does not carry as a flag is a phrase the enumerator
    would ignore, and a list wider than the card prints is the one thing a
    change must never be offered from.
    """
    from .legality import targeting_instruction
    from .mixins.stack.resolution import _controller_narrowing_is_in

    spec = dict(announcement.spec)
    instruction = announcement.instruction
    is_ability = bool(getattr(item, "is_ability", False))
    triggered = is_ability and _is_triggered(item)
    if is_ability:
        frozen = getattr(item, "trigger_context", None) or {}
        defending = frozen.get("trigger_defending_player_index")
        if isinstance(defending, int):
            spec["defending_player_index"] = defending
        that_player = game._that_player_seat(item)
        if that_player is not None:
            spec["that_player_index"] = that_player
        elif spec.get("that_player_only"):
            return None
        if triggered and not _controller_narrowing_is_in(spec, instruction):
            return None
    entries = game._enumerate_targets(
        item.caster_index, item.card, spec,
        for_cast=not is_ability,
        ability_instruction=(
            targeting_instruction(instruction) if is_ability and instruction is not None else None
        ),
        source_permanent=getattr(item, "source_permanent", None),
        ability_source=getattr(item, "source_permanent", None) if is_ability else None,
        triggered=triggered,
    )
    depth = len(game.stack)
    address = {"channel": current.channel, "position": current.position, "mode": current.mode}
    found: list[ChosenTarget] = []
    for entry in entries:
        kind = entry.get("kind")
        if kind == "player":
            seat = entry.get("seat")
            if isinstance(seat, int) and 0 <= seat < len(game.players) and not game.players[seat].lost:
                found.append(ChosenTarget("player", seat=seat, **address))
        elif kind == "permanent":
            permanent = game.permanent_at(entry.get("seat"), entry.get("index"))
            if permanent is not None:
                found.append(ChosenTarget("permanent", permanent_id=permanent.permanent_id, **address))
        elif kind == "graveyard":
            stamp = game.graveyard_target_at(entry.get("seat"), entry.get("index"))
            if stamp is not None:
                found.append(ChosenTarget("graveyard", stamp=stamp, **address))
        elif kind == "stack":
            index = entry.get("stack_index")
            # The picker indexes the stack top-first (``_enumerate_stack_targets``).
            if isinstance(index, int) and 0 <= depth - 1 - index < depth:
                other = game.stack[depth - 1 - index]
                # CR 115.5: a spell or ability on the stack is an illegal
                # target for itself.
                if other is not item:
                    found.append(ChosenTarget("stack", stack_item=other, **address))
    return found


#: The channels :func:`apply_target_change` can rewrite. A **role** (two
#: different descriptions in one announcement — Donate, Goblin Welder) is not
#: among them: each role has its own candidate walk and relation test
#: (``legality._role_target_walk``), and a flat re-enumeration would compare the
#: second role's target against the first role's list.
_CHANGEABLE_CHANNELS = frozenset({"item", "player", "divided", "graveyard", "stack"})


def change_slots(game: "Game", item: "StackItem") -> "list[ChangeSlot] | str":
    """*item*'s targets as slots that may be changed (CR 115.7a), or the reason
    this engine cannot offer a change at all.

    **A refusal here is "the targets remain unchanged"**, which is always a
    legal outcome of "may change the target or targets" — an under-offer, never
    a change to something the object could not have chosen. The shapes refused:

    * an object whose targets the engine cannot enumerate (see
      :func:`chosen_targets`), or that has none;
    * a **modal spell** — its legal targets are the chosen mode's (CR 115.8),
      and the cast gate this enumeration runs through reads the card's first
      mode; a modal *triggered ability* is enumerated from its own mode's
      instruction and is offered;
    * an object printing **more than one instance** of "target", or a
      **roles** announcement — see :func:`_printed_target_instances`;
    * a slot whose candidates cannot be enumerated.
    """
    from .oracle import compile_card_oracle

    announced = announcements(item)
    if announced is None:
        return "its targets are not recorded as a stack object's"
    targeted = [(announcement, _read(game, item, announcement)) for announcement in announced]
    targeted = [(announcement, targets) for announcement, targets in targeted if targets]
    if not targeted:
        return "it has no targets"
    if len(targeted) != 1:
        return "it chose targets for more than one mode"
    announcement, targets = targeted[0]
    if not getattr(item, "is_ability", False) and compile_card_oracle(item.card).modes:
        return "a modal spell's targets belong to its chosen mode"
    instances = _printed_target_instances(item)
    if instances is not None and instances != 1:
        return "it uses the word \"target\" more than once"
    if any(target.channel not in _CHANGEABLE_CHANNELS for target in targets):
        return "its targets answer different descriptions"
    slots: list[ChangeSlot] = []
    for current in targets:
        candidates = _candidates(game, item, announcement, current)
        if candidates is None:
            return "its legal targets cannot be enumerated"
        slots.append(ChangeSlot(
            current,
            tuple(candidate for candidate in candidates if not candidate.same_object(current)),
        ))
    return slots


def _completable(slots, picks: list, position: int) -> bool:
    """Whether slots ``position..`` can each still take a candidate no earlier
    slot took (CR 115.3: one instance of "target" names each object once).

    CR 115.7a is all-or-nothing — "if all the targets aren't changed to other
    legal targets, none of them are changed" — so a pick is only offered when
    the rest of the change can still be completed behind it. A depth-first
    search: the slots of one announcement are few, and each level only tries
    candidates nothing above it holds.
    """
    if position >= len(slots):
        return True
    for candidate in slots[position].candidates:
        if any(candidate.same_object(taken) for taken in picks):
            continue
        if _completable(slots, picks + [candidate], position + 1):
            return True
    return False


def change_options(slots, picks: list) -> list[ChosenTarget]:
    """What slot ``len(picks)`` may be changed to, given the earlier *picks*:
    another legal target (CR 115.7a) no earlier slot took (CR 115.3) that
    still lets every later slot be changed too."""
    position = len(picks)
    if position >= len(slots):
        return []
    return [
        candidate
        for candidate in slots[position].candidates
        if not any(candidate.same_object(taken) for taken in picks)
        and _completable(slots, picks + [candidate], position + 1)
    ]


def _set_at(value, position: int, new):
    """*value* with *new* at *position*, keeping its scalar-or-list shape."""
    if isinstance(value, list):
        updated = list(value)
        while len(updated) <= position:
            updated.append(None)
        updated[position] = new
        return updated
    return new


def apply_target_change(game: "Game", item: "StackItem", slots, picks) -> bool:
    """Rewrite *item*'s announcement so each slot names its pick (CR 115.7a).

    All of them or none: called only with one pick per slot, and it re-checks
    that every picked object is still where it was offered before writing
    anything — a pick that left between the choice and this step leaves the
    object exactly as it was ("the original target is unchanged").

    Everything else the object announced — its controller, X, modes, the
    division of a divided effect (CR 115.7f) — is untouched.
    """
    from .divided_damage import stamped_entry

    if len(picks) != len(slots) or not slots:
        return False
    for pick in picks:
        if pick.kind == "permanent" and game.find_permanent_by_id(pick.permanent_id) is None:
            return False
        if pick.kind == "graveyard" and game.graveyard_index_of(pick.stamp) is None:
            return False
        if pick.kind == "stack" and not any(other is pick.stack_item for other in game.stack):
            return False
        if pick.kind == "player" and game.players[pick.seat].lost:
            return False

    for slot, pick in zip(slots, picks):
        channel, position = slot.current.channel, slot.current.position
        if channel == "stack":
            if pick.kind == "stack":
                item.target_stack_item = pick.stack_item
            else:
                # "Target spell or permanent" re-aimed from a spell onto a
                # permanent: the stack reference goes and the id arrives.
                item.target_stack_item = None
                seat, permanent = game.find_permanent_by_id(pick.permanent_id)
                item.target_player_index = seat
                item.target_permanent_id = pick.permanent_id
                item.target_permanent_index = game.battlefield_index_of(permanent)
            continue
        if channel == "graveyard":
            index = game.graveyard_index_of(pick.stamp)
            item.target_graveyard_card = _set_at(item.target_graveyard_card, position, pick.stamp)
            item.target_permanent_index = _set_at(item.target_permanent_index, position, index)
            item.target_player_index = pick.stamp.seat
            continue
        if channel == "divided":
            divided = list(item.choices.get(DIVIDED_TARGETS) or ())
            share = divided_entry(divided[position])[2]
            if pick.kind == "player":
                divided[position] = (pick.seat, None) if share is None else (pick.seat, None, share)
            else:
                seat, permanent = game.find_permanent_by_id(pick.permanent_id)
                divided[position] = stamped_entry(
                    seat, game.battlefield_index_of(permanent), share, pick.permanent_id
                )
            item.choices[DIVIDED_TARGETS] = divided
            continue
        # "item" / "player": the scalar fields, or one slot of the id list.
        if pick.kind == "stack":
            item.target_stack_item = pick.stack_item
            item.target_permanent_id = None
            item.target_permanent_index = None
            continue
        if pick.kind == "player":
            # All three written together, whichever way the target points
            # (``change_target_spell_target``): a stale id would be resolved as
            # an object target by every handler that prefers it.
            item.target_player_index = pick.seat
            item.target_permanent_id = None
            item.target_permanent_index = None
            continue
        seat, permanent = game.find_permanent_by_id(pick.permanent_id)
        item.target_permanent_id = _set_at(item.target_permanent_id, position, pick.permanent_id)
        item.target_permanent_index = _set_at(
            item.target_permanent_index, position, game.battlefield_index_of(permanent)
        )
        if not isinstance(item.target_permanent_id, list):
            item.target_player_index = seat

    if isinstance(item.target_permanent_id, list):
        # A list of objects has one seat beside it only while they share a
        # battlefield (``Game.announced_target_seat``); the resolutions that
        # read a list read the ids.
        shared = game.announced_target_seat(item.target_permanent_id)
        if shared is not None:
            item.target_player_index = shared
    return True

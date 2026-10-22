"""What a permanent forbids every player — or some — to cast or play
(CR 601.3a, CR 305.1, CR 602.5).

The board half of CR 601.3. ``engine/cast_restrictions.py`` reads a gate the
**casting card prints about itself** ("Cast this spell only during …"); every
row here is a sentence printed on a **permanent** about other spells, so each
is answered by a scan of the battlefields rather than of the spell:

* by type, for everybody ("Creature spells can't be cast.", Aether Storm) and
  for one side of the table ("You can't cast creature spells.", Steel Golem;
  "Your opponents can't cast blue creature spells.", Llawan);
* by name — a name chosen as the permanent entered (Meddling Mage, Null
  Chamber) or any name a nontoken permanent has (Cornered Market);
* by moment — only on one's own turn (City of Solitude), not during combat
  (Hand to Hand);
* by relation and count — a colour shared with the last spell cast (Mana
  Maze), more than N spells a turn (Arcane Laboratory, Yawgmoth's Agenda);
* by a seat the board derives — whoever controls the most permanents (Damping
  Engine), with CR 116.2d's special action that buys a turn off it.

**Whom a sentence binds is read off the sentence**, never widened from a
neighbouring row: a scope taken from the wrong half of a sentence bans the
wrong players. Each row has one reader that the grammar's registry claims the
line with and the cast path enforces it with
(``engine/cast_prohibitions.py``'s one table asks every ban here), so a ban
claimed and not enforced cannot be spelled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game


# --- The board half of CR 601.3: a prohibition a *permanent* imposes ---------
#
# Everything in ``engine/cast_restrictions.py`` is read off the **casting
# card's own text** — a gate the
# spell prints about itself. "Creature spells can't be cast." (Aether Storm) is
# the other direction entirely: the sentence is printed on a permanent, it names
# no seat, and it stops *every* player casting spells of a type (CR 601.3a).
# So it is a scan of the battlefields rather than a scan of the spell, and its
# own reader for that reason.
#
# The card **type** is payload, for
# `aura_restrictions.aura_controller_cast_ban`'s reason: "Artifact spells can't
# be cast." is the same sentence and must need no second row. That reader is
# deliberately *not* widened into this one — what differs between them is the
# **scope**, and a scope taken from the wrong half of a sentence bans the wrong
# players. Aether Storm's ban reaches its own controller; Brand of Ill Omen's
# reaches only the enchanted creature's.
_BANNABLE_SPELL_TYPES = (
    r"(?:artifact|creature|enchantment|instant|sorcery|planeswalker|battle)"
)
_GLOBAL_CAST_BAN = re.compile(
    rf"^(?P<type>{_BANNABLE_SPELL_TYPES}) spells can't be cast$"
)


@lru_cache(maxsize=None)
def global_cast_ban_line(line: str) -> str | None:
    """The card type *line* forbids anybody from casting, or None.

    One reader, two callers, exactly as
    :func:`aura_restrictions.aura_controller_cast_ban` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and ``mixins/stack/casting.py`` asks it at CR 601.2 so the line is
    *enforced*. A restriction that is claimed and not enforced is an
    enchantment that reports supported and lets every creature through, which
    is the one failure this seam exists to make impossible.
    """
    match = _GLOBAL_CAST_BAN.match(line.strip().lower().rstrip("."))
    return match.group("type") if match is not None else None


#: "**You** can't cast creature spells." (Steel Golem.) The third scope this
#: prohibition is printed in, and the reason it is a third reader rather than a
#: widening of :data:`_GLOBAL_CAST_BAN` above: what differs between the three is
#: **whom the sentence binds**, and a scope taken from the wrong half of a
#: sentence bans the wrong players. Aether Storm's "Creature spells can't be
#: cast" binds everybody; Brand of Ill Omen's binds the enchanted creature's
#: controller (``aura_restrictions.aura_controller_cast_ban``); this one binds
#: the seat that controls the permanent printing it, and nobody else — an
#: opponent who steals the Golem is stopped and its former controller is freed,
#: which is exactly what CR 109.5 makes of the word "you".
#:
#: The card type is payload for the reason every printed word in this table is
#: one: "…can't cast artifact spells" is the same sentence and must need no
#: second row.
#:
#: **Whom it binds is payload too, and so is a colour.** "**Your opponents**
#: can't cast **blue** creature spells." (Llawan, Cephalid Empress.) The seat is
#: still read off the sentence's own subject — the half this reader exists to
#: get right — and it is still the permanent's controller the word is relative
#: to (CR 109.5: "you" is that player; CR 102.3: "your opponents" is every other
#: player in the game), so one reader serves both and a scope cannot be taken
#: from the wrong half of a sentence. The colour narrows the spell (CR 105.2:
#: a gold spell is blue if blue is one of its colours).
_OWN_CAST_BAN = re.compile(
    r"^(?P<who>you|your opponents) can't cast "
    r"(?:(?P<color>white|blue|black|red|green) )?"
    rf"(?P<type>{_BANNABLE_SPELL_TYPES}) spells$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, not ``"cast_restrictions"``, for
#: :data:`GLOBAL_PLAY_TIMING_CLAIM`'s reason: that claim says *when this card*
#: may be cast, and this sentence is a standing prohibition on a player.
OWN_CAST_BAN_CLAIM = "own_cast_ban"


@dataclass(frozen=True)
class SeatedCastBan:
    """What a "<you / your opponents> can't cast [<colour>] <type> spells"
    line forbids: whom it binds relative to the permanent's controller
    (``"controller"`` / ``"opponents"``), the card type, and the colour symbol
    the spell must have to be stopped (None: any colour)."""

    binds: str
    card_type: str
    color: str | None = None


@lru_cache(maxsize=None)
def own_cast_ban_line(line: str) -> SeatedCastBan | None:
    """What *line* forbids a seat relative to its controller from casting, or None.

    One reader, three callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    ``engine/oracle.py``'s two support gates ask it so the card is admitted on
    the strength of a restriction that exists, and ``mixins/stack/casting.py``
    asks it at CR 601.2 so the line is *enforced*. A restriction claimed and not
    enforced is a permanent that reports supported while its controller keeps
    casting the spells it forbids — and on Steel Golem, whose drawback is the
    whole of what pays for a 3/3 for {3}, that is not a card doing less but a
    card doing something else.
    """
    from .grammar.vocabulary import COLOR_WORDS

    match = _OWN_CAST_BAN.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    return SeatedCastBan(
        binds="controller" if match.group("who") == "you" else "opponents",
        card_type=match.group("type"),
        color=COLOR_WORDS[match.group("color")] if match.group("color") else None,
    )


def own_cast_ban(game: "Game", caster_index: int, card) -> str | None:
    """The name of a permanent forbidding *caster_index* to cast *card* because
    of who controls it, or None.

    "You can't cast …" asks only the caster's own battlefield, which is the
    whole difference from :func:`global_cast_ban` beside it — an opponent's
    Steel Golem says nothing about your creature spells. "Your opponents can't
    cast …" asks every *other* seat's (Llawan's controller casts its own blue
    creatures; CR 102.3).

    ``effective_card`` rather than the printed face, for that function's reason:
    what a permanent says is what layer 1 and layer 3 have made of it (CR 707.2,
    CR 612.1). The type test is :func:`search_filters.card_has_type` for its
    reason too — a card has **every** type its line names (CR 205.2), so an
    artifact creature is stopped by a ban on either word. The colour is the
    spell's as its caster would cast it (``object_colors.card_colors``, the
    reading :func:`last_cast_color_ban` takes), so a gold card with blue in it
    is a blue spell (CR 105.2b) and a card a Celestial Dawn has made white is
    not one.
    """
    from .object_colors import card_colors
    from .search_filters import card_has_type

    for seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            ban = own_cast_ban_line(raw_line)
            if ban is None:
                continue
            binds_caster = (
                seat == caster_index if ban.binds == "controller"
                else caster_index in game.opponents_of(seat)
            )
            if not binds_caster or not card_has_type(card, ban.card_type):
                continue
            if ban.color is not None and ban.color not in card_colors(game, card, caster_index):
                continue
            return permanent.card.name
    return None


#: Where a permanent records the names two seats chose as it entered (Null
#: Chamber). A list, and the order is the choosers' — it is read as a *set* by
#: the ban below, but recorded in order because each slot belongs to one seat
#: and a prompt answering into the wrong one would swap the two players'
#: choices.
CHOSEN_CARD_NAMES = "chosen_card_names"

#: "Spells with the chosen names can't be cast and lands with the chosen names
#: can't be played." (Null Chamber.) The *name*-keyed twin of the type-keyed ban
#: above, and its own row rather than a widening of that one: what a card is
#: called is not a characteristic anything else in this table tests, and the
#: names are not in the sentence at all — they were chosen as the permanent
#: entered (CR 614.1c) and live on it.
#:
#: Both halves of the printed sentence are one row on purpose. A spell and a
#: land drop are the same action to `cast_from_hand`, so one gate covers both —
#: and claiming only the casting half would ship an enchantment that stops a
#: Wrath of God and lets its Island through, which is not the card.
_CHOSEN_NAME_BAN = re.compile(
    r"^spells with the chosen names can't be cast and lands with the chosen "
    r"names can't be played$"
)

#: Where a permanent records the **one** name its controller chose as it
#: entered (Runed Halo, Booby Trap, Meddling Mage) — the key
#: ``_initialize_permanent_state`` and the ``enter_choice`` resolver have always
#: written; named here because the ban below is its newest reader.
CHOSEN_CARD_NAME = "chosen_card_name"

#: "Spells with the chosen name can't be cast." (Meddling Mage.) Null Chamber's
#: sentence with one name instead of two and **no land half** — and the second
#: difference is the one that must not be folded away: a land is played, never
#: cast (CR 305.1), so this row stops no land drop, where Null Chamber's row
#: says so in as many words and does.
_CHOSEN_SINGLE_NAME_BAN = re.compile(
    r"^spells with the chosen name can't be cast$"
)

#: Each printed chosen-name prohibition as ``(pattern, the metadata key its
#: names were recorded under, whether it also stops a land being played)``.
#: The reader below returns the last two, so the enforcement reads what the
#: line printed rather than a flag somebody has to keep in step with it.
_CHOSEN_NAME_BAN_ROWS: tuple[tuple["re.Pattern[str]", str, bool], ...] = (
    (_CHOSEN_NAME_BAN, CHOSEN_CARD_NAMES, True),
    (_CHOSEN_SINGLE_NAME_BAN, CHOSEN_CARD_NAME, False),
)


@lru_cache(maxsize=None)
def chosen_name_ban_row(line: str) -> tuple[str, bool] | None:
    """``(record key, binds lands)`` for a chosen-name prohibition, or None."""
    text = line.strip().lower().rstrip(".")
    for pattern, record_key, binds_lands in _CHOSEN_NAME_BAN_ROWS:
        if pattern.match(text) is not None:
            return record_key, binds_lands
    return None


def chosen_name_ban_line(line: str) -> bool:
    """Whether *line* is a chosen-name prohibition — either printed row.

    One reader, every caller, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` and ``engine/oracle.py``'s creature gate
    ask it so the printed line is *claimed*, and ``mixins/stack/casting.py``
    asks :func:`chosen_name_ban` at CR 601.3 so the line is *enforced*. A
    restriction claimed and not enforced is a permanent that reports supported
    and stops nothing.
    """
    return chosen_name_ban_row(line) is not None


def chosen_name_ban(game: "Game", card) -> str | None:
    """The name of a permanent whose chosen names forbid *card*, or None.

    Every battlefield and no seat comparison: the sentence names nobody, so it
    binds everybody including the enchantment's own controller (CR 601.3a) —
    which for Null Chamber is the whole design, since one of the two names is
    its controller's own choice and the other is an opponent's.

    Compared through ``search_filters.name_key`` on both sides, so a printing
    with different punctuation is the same name — the comparison every other
    name test in the engine makes.
    """
    from .search_filters import card_has_type, name_key

    # **The name of what is being cast**, which for a split card is the half
    # (CR 709.3a: "only the chosen half is evaluated to see if it can be
    # cast") — the cast path hands this the face it is announcing, so a Mage
    # naming "Wax" stops Wax and leaves Wane castable.
    wanted = name_key(getattr(card, "name", "") or "")
    if not wanted:
        return None
    is_land = card_has_type(card, "land")
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            row = chosen_name_ban_row(raw_line)
            if row is None:
                continue
            record_key, binds_lands = row
            if is_land and not binds_lands:
                # "Spells … can't be cast" says nothing about a land drop.
                continue
            recorded = permanent.metadata.get(record_key) or ()
            chosen = [recorded] if isinstance(recorded, str) else list(recorded)
            if any(name_key(str(name)) == wanted for name in chosen if name):
                return permanent.card.name
    return None


#: "Players can't cast spells with the same name as a nontoken permanent." /
#: "Players can't play nonbasic lands with the same name as a nontoken
#: permanent." (Cornered Market.)
#:
#: Null Chamber's ban one screen up, with the names read off the **board**
#: instead of off the permanent: nothing was chosen, so what the sentence
#: forbids changes every time a permanent enters or leaves. Its own row rather
#: than a widening of that one, because the two differ in where the name set
#: comes from — a chosen name is a record and this is a question about the
#: table, and a reader that took either would have to be told which every time.
#:
#: **Two printed lines, and each is claimed on its own**, which is the opposite
#: arrangement from Null Chamber's single sentence: there one line states both
#: rules, and here the card spends a line on each. The alternation is what makes
#: them one row — the noun after "can't" is the only word that differs — and
#: which half a line stated is returned, because the halves forbid different
#: sets: the land line exempts a **basic** land and the spell line has no such
#: word.
#:
#: "Nontoken" is a real narrowing on the *permanent* side and CR 111.1's reason
#: it is printed: a token copy of a creature would otherwise lock its own name
#: out of every hand at the table.
_SAME_NAME_AS_PERMANENT_BAN = re.compile(
    r"^players can't (?P<half>cast spells|play nonbasic lands) with the same "
    r"name as a nontoken permanent$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above, its own for :data:`GLOBAL_PLAY_TIMING_CLAIM`'s reason.
SAME_NAME_AS_PERMANENT_BAN_CLAIM = "same_name_as_permanent_ban"


@lru_cache(maxsize=None)
def same_name_as_permanent_ban_line(line: str) -> str | None:
    """Which half of Cornered Market *line* states, or None.

    ``"cast spells"`` or ``"play nonbasic lands"`` — the words themselves, so a
    caller cannot invent a third value and the enforcement below reads the
    printed distinction rather than a flag somebody has to keep in step.

    One reader, two callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and ``mixins/stack/casting.py`` asks it at CR 601.3 / CR 305.1 so the line
    is *enforced*. A restriction claimed and not enforced is an enchantment that
    reports supported and stops nothing.
    """
    match = _SAME_NAME_AS_PERMANENT_BAN.match(line.strip().lower().rstrip("."))
    return match.group("half") if match is not None else None


def same_name_as_permanent_ban(game: "Game", card) -> str | None:
    """The name of a permanent whose ban stops *card* being played, or None.

    Every battlefield and no seat comparison: the sentence names nobody, so it
    binds everybody including the enchantment's own controller (CR 601.3a) —
    which on this card is the whole design, since the names it locks out are
    whatever anybody has already resolved.

    **Which half applies is decided by the card, not by the caller.** A land is
    never cast (CR 305.1 makes playing one a special action), so the spell line
    cannot reach it and the land line cannot reach anything else; and the land
    line exempts a basic land, which the spell line does not say and must not be
    given. Read the other way round, a Forest would stop being playable the
    moment anybody resolved one.

    The comparison goes through ``search_filters.name_key`` on both sides, so a
    printing with different punctuation is the same name — the comparison every
    other name test in the engine makes. The permanent's **effective** name is
    what counts (CR 707.2): a Clone that copied a Bear really is called Grizzly
    Bears, and it is the name the card asks about.
    """
    from .search_filters import card_has_type, name_key

    wanted = name_key(getattr(card, "name", "") or "")
    if not wanted:
        return None
    is_land = card_has_type(card, "land")
    if is_land and "basic" in (getattr(card, "type_line", "") or "").lower():
        # The land half's own word. A basic land is exempt however many of it
        # are on the table, which is what keeps this from ending the game.
        return None
    half = "play nonbasic lands" if is_land else "cast spells"
    for _seat, permanent in game.permanents_with_controller():
        if permanent.metadata.get("is_token"):
            continue
        for raw_line in (
            permanent.effective_card.oracle_text or ""
        ).splitlines():
            if same_name_as_permanent_ban_line(raw_line) != half:
                continue
            # The banning permanent is not what has to share the name — any
            # nontoken permanent on the table does, this one included.
            if _a_nontoken_permanent_is_named(game, wanted):
                return permanent.card.name
    return None


def _a_nontoken_permanent_is_named(game: "Game", wanted: str) -> bool:
    """Whether any **nontoken** permanent on any battlefield answers to *wanted*.

    Its own two lines because the ban above walks the board twice for two
    different questions — which permanents impose the prohibition, and which
    ones supply the names — and folding them into one loop is how a card would
    come to forbid only its own name.
    """
    from .search_filters import name_key

    for _seat, permanent in game.permanents_with_controller():
        if permanent.metadata.get("is_token"):
            continue
        if name_key(permanent.effective_card.name) == wanted:
            return True
    return False


#: "Players can cast spells and activate abilities only during their own
#: turns." (City of Solitude.) The **timing** half of CR 601.3a and CR 602.5,
#: read off the board rather than off the object being played: nothing about
#: the spell or the ability decides it, only whose turn it is.
#:
#: One row, two gates. Both halves of the printed sentence are one rule for
#: ``_CHOSEN_NAME_BAN``'s reason one screen up — claiming the casting half
#: alone would ship an enchantment that stops an opponent's Counterspell and
#: lets their Icy Manipulator through, which is not the card — and the two
#: enforcement sites (``mixins/stack/casting.py``, ``mixins/stack/activation.py``)
#: both ask :func:`global_play_timing`.
#:
#: "Their own turns" is the seat's, so the question is whether the player
#: acting is the active player. No exception for mana abilities: the sentence
#: names none, and CR 605.1a's exception is a thing *other* cards print
#: (Faith's Fetters) rather than a rule about restrictions in general.
_GLOBAL_PLAY_TIMING = re.compile(
    r"^players can cast spells and activate abilities only during their own "
    r"turns$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, not ``"cast_restrictions"``: that claim says *when
#: this card* may be cast, and this sentence is the whole of what the permanent
#: does and is about everybody else's turns — the same distinction
#: ``global_activation_ban`` records one file over.
GLOBAL_PLAY_TIMING_CLAIM = "global_play_timing"

#: "**During combat**, players can't cast instant spells or activate abilities
#: that aren't mana abilities." (Hand to Hand.)
#:
#: The row above with a *phase* in place of a turn, and the same two gates read
#: it for the same reason: one printed sentence stating one rule about both
#: ways of acting, so claiming the casting half alone would ship an enchantment
#: that stops a combat trick and lets an Icy Manipulator through.
#:
#: The spell type is payload, like every other printed word in this table. The
#: mana-ability exception is **not** optional: CR 605.1a's exception is
#: something a card prints rather than a rule about prohibitions in general
#: (``_GLOBAL_PLAY_TIMING`` above names none and so stops mana abilities too),
#: so a sentence without those words is a different, stricter card and must not
#: be read as this one.
_COMBAT_PLAY_BAN = re.compile(
    rf"^during combat, players can't cast (?P<type>{_BANNABLE_SPELL_TYPES}) "
    r"spells or activate abilities that aren't mana abilities$"
)

#: The claim name for the row above, its own for
#: :data:`GLOBAL_PLAY_TIMING_CLAIM`'s reason.
COMBAT_PLAY_BAN_CLAIM = "combat_play_ban"


@lru_cache(maxsize=None)
def combat_play_ban_line(line: str) -> str | None:
    """The spell type *line* forbids during combat, or None.

    One reader, three callers, exactly as :func:`global_play_timing_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and the casting and activation gates ask it so the line is *enforced*.
    """
    match = _COMBAT_PLAY_BAN.match(line.strip().lower().rstrip("."))
    return match.group("type") if match is not None else None


def combat_play_ban(game: "Game") -> tuple[str, str] | None:
    """``(the permanent's name, the spell type it stops)`` while combat is on,
    or None.

    Every battlefield and no seat comparison, for :func:`global_play_timing`'s
    reason: the sentence names nobody, so it binds its own controller as
    thoroughly as anybody (CR 601.3a).

    "During combat" is CR 506.1's phase — every step of it, from the beginning
    of combat through end of combat — which is what ``current_turn_phase``
    answers. Asked of the *phase* rather than of a step, because a card naming
    a step would say so.
    """
    if getattr(game, "current_turn_phase", None) != "combat":
        return None
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            banned = combat_play_ban_line(raw_line)
            if banned is not None:
                return permanent.card.name, banned
    return None


@lru_cache(maxsize=None)
def global_play_timing_line(line: str) -> bool:
    """Whether *line* is the board-wide own-turn-only restriction.

    One reader, three callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and the casting and activation gates ask it so the line is *enforced*. A
    restriction that is claimed and not enforced is an enchantment that reports
    supported while every player keeps playing on every turn.
    """
    return _GLOBAL_PLAY_TIMING.match(line.strip().lower().rstrip(".")) is not None


def global_play_timing(game: "Game", actor_index: int) -> str | None:
    """The name of a permanent forbidding *actor_index* from acting now, or None.

    Every battlefield and no seat comparison against the permanent's own
    controller: the sentence names nobody, so it binds its controller too — on
    an opponent's turn the enchantment stops its own player as thoroughly as
    anybody (CR 601.3a).

    ``effective_card`` rather than the printed face, for
    :func:`global_cast_ban`'s reason: what a permanent says is what layer 1 and
    layer 3 have made of it (CR 707.2, CR 612.1).
    """
    if actor_index == game.active_player_index:
        return None
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            if global_play_timing_line(raw_line):
                return permanent.card.name
    return None


#: "Players can't cast spells **that share a color with the spell most recently
#: cast this turn**." (Mana Maze.) CR 601.3a again, and a scope none of the rows
#: above reads it in: what is forbidden is decided by a *relation* between the
#: spell being announced and another spell — CR 105.2's shared colour — and the
#: other spell is whichever was cast last, by anybody.
#:
#: It needs no record of its own, for the spell cap's reason one row down. The
#: turn's ledger (``engine/damage_ledger.py``) has held every cast in order, by
#: its per-cast identity, since Backdraft — and ``begin_turn_bookkeeping``
#: clears it at the turn boundary, which is the printed "this turn": the first
#: spell of a turn is compared against nothing.
#:
#: The whole sentence is the pattern. Nothing in it is payload, because nothing
#: in it is a word another card could print differently and mean this rule.
_LAST_CAST_COLOR_BAN = re.compile(
    r"^players can't cast spells that share a color with the spell most "
    r"recently cast this turn$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, for :data:`SPELL_CAP_CLAIM`'s reason: no other ban
#: here compares two spells.
LAST_CAST_COLOR_BAN_CLAIM = "last_cast_color_ban"


@lru_cache(maxsize=None)
def last_cast_color_ban_line(line: str) -> bool:
    """Whether *line* is, in full, Mana Maze's prohibition.

    One reader, four callers: ``engine/grammar/registries.py`` asks it so the
    printed line is *claimed*, ``engine/oracle.py``'s support gate so the card
    is admitted on the strength of a restriction that exists,
    ``mixins/stack/casting.py`` at CR 601.2 so it is *enforced*, and
    ``ai_policy`` so a seat stops proposing what the cast path will refuse.
    """
    return _LAST_CAST_COLOR_BAN.match(line.strip().lower().rstrip(".")) is not None


def most_recent_cast_colors(game: "Game") -> frozenset[str] | None:
    """The colours of the spell most recently cast this turn, or None when no
    spell has been cast this turn.

    ``frozenset()`` — empty, and **not** None — is a colourless spell, which is
    a real answer: after an artifact every spell is castable, because a
    colourless object shares a colour with nothing (CR 105.2c).

    Read off the ledger's per-cast ``StackItem`` through the one reader of a
    spell's colour (``Game._stack_item_colors``), so a spell a Lace recoloured
    on the stack is the colour it became — and the item is kept by the ledger
    after it has left the stack, which is the common case: "most recently
    cast" is usually a spell that has already resolved or been countered, and
    what it was is its last-known information (CR 608.2h).

    Cast, not copied and not put onto the stack some other way: the ledger is
    written at CR 601.2i and nowhere else.
    """
    from .damage_ledger import ledger

    casts = ledger(game).casts
    if not casts:
        return None
    return frozenset(game._stack_item_colors(casts[-1].item))


def last_cast_color_ban(game: "Game", caster_index: int, card) -> str | None:
    """The name of a permanent whose Maze stops *card* being cast, or None.

    Every battlefield and no seat comparison, for :func:`global_cast_ban`'s
    reason: the sentence says "players", so it binds its own controller as
    thoroughly as anybody (CR 601.3a).

    The spell being announced is read through ``object_colors.card_colors``
    with the seat casting it — the layer-5 reading every colour question about
    a card in a hand takes — so a gold card is stopped by either of its colours
    (CR 105.2b) and a card a Celestial Dawn has made white is white.

    A land is never cast (CR 305.1), so the sentence cannot reach one: this
    function is asked from a path that land drops also take.
    """
    from .object_colors import card_colors, share_a_color
    from .search_filters import card_has_type

    if card_has_type(card, "land"):
        return None
    previous = most_recent_cast_colors(game)
    if not previous:
        return None
    if not share_a_color(previous, card_colors(game, card, caster_index)):
        return None
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            if last_cast_color_ban_line(raw_line):
                return permanent.card.name
    return None


#: "Each player can't cast more than one spell each turn." (Arcane Laboratory;
#: Rule of Law is the same sentence.) CR 601.3a again, and the fourth scope this
#: file reads it in — the three above ask *what* may be cast and this one asks
#: **how many**, which is why it is its own row rather than a payload on any of
#: them: nothing in those patterns counts, and a count is not a card type.
#:
#: The number is payload, for every other printed word in this table's reason: a
#: card printed "more than two spells" is this restriction and must need no
#: second row. Printed as a **word** on every card that prints it at all, so it
#: is read through a number table, and a word with no number behind it leaves
#: the line unclaimed rather than reaching the comparison as a string — where it
#: would compare unequal to every count and stop nobody.
#:
#: It needs no record of its own. ``PlayerState.spells_cast_this_turn`` has held
#: every cast of the turn since Stormwing Entity's ordinal, and
#: ``turn_management`` empties it at the turn boundary — which is the half that
#: matters, because a record outliving its turn is a restriction that stops
#: applying, and a cap lifted is a spell castable when the card forbids it.
#:
#: **Who is capped is payload too.** "**You** can't cast more than one spell
#: each turn." (Yawgmoth's Agenda) is the same count over one seat — CR 109.5's
#: "you", the permanent's controller — where "each player" binds the table.
#: Read as one row so the two cannot drift, and recorded rather than matched
#: and dropped: an Agenda read as Arcane Laboratory caps its controller's
#: opponents as well, which is a drawback turned into a lock.
_SPELL_CAP_PER_TURN = re.compile(
    r"^(?P<who>each player|you) can't cast more than (?P<count>[a-z]+) "
    r"spells? each turn$"
)

#: Printed number words a cap can be written with. Its own table for the reason
#: ``combat_restrictions._NUMBER_WORDS`` is its own: what the two have in common
#: is English, not a rule.
_CAP_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, for :data:`OWN_CAST_BAN_CLAIM`'s reason: that claim
#: says which *types* a seat may not cast, and this sentence caps how many
#: spells of any type everybody may cast.
SPELL_CAP_CLAIM = "spell_cap"


@lru_cache(maxsize=None)
def spell_cap_line(line: str) -> int | None:
    """How many spells a turn *line* caps every player at, or None.

    One reader, three callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    ``engine/oracle.py``'s support gate asks it so the card is admitted on the
    strength of a restriction that exists, and ``mixins/stack/casting.py`` asks
    it at CR 601.2 so the line is *enforced*. A restriction claimed and not
    enforced is an enchantment that reports supported while every player casts
    as many spells as they like — which on this card is the whole of what it
    does.
    """
    match = _SPELL_CAP_PER_TURN.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    return _CAP_NUMBER_WORDS.get(match.group("count"))


@lru_cache(maxsize=None)
def spell_cap_binds_controller_only(line: str) -> bool:
    """Whether *line*'s cap is printed on "**you**" rather than "each player".

    Beside :func:`spell_cap_line` rather than folded into its answer, so the
    three callers that ask only "is this a cap, and of how many" keep the int
    they read — and the one that enforces it asks this as well.
    """
    match = _SPELL_CAP_PER_TURN.match(line.strip().lower().rstrip("."))
    return match is not None and match.group("who") == "you"


def spell_cap_ban(game: "Game", caster_index: int) -> str | None:
    """The name of a permanent whose per-turn cap *caster_index* has reached.

    Every battlefield and no seat comparison, for :func:`global_play_timing`'s
    reason: the sentence says "each player", so it binds its own controller as
    thoroughly as anybody (CR 601.3a). The one comparison is the printed
    "**you**" (Yawgmoth's Agenda), which binds the permanent's controller and
    nobody else.

    The count read is the seat's **own** record, not a shared one: CR 601.3a
    restricts the player who is casting, and one table-wide tally would let an
    opponent's turn-one Ornithopter spend everybody's allowance. The record is
    appended to further down the cast (``mixins/stack/casting.py``), so a seat
    that has already cast *cap* spells is at its limit and the spell being
    announced is the one too many.

    ``effective_card`` rather than the printed face, for :func:`global_cast_ban`'s
    reason: what a permanent says is what layer 1 and layer 3 have made of it
    (CR 707.2, CR 612.1).
    """
    if not (0 <= caster_index < len(game.players)):
        return None
    cast_so_far = len(game.players[caster_index].spells_cast_this_turn)
    for seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            cap = spell_cap_line(raw_line)
            if cap is None or cast_so_far < cap:
                continue
            if spell_cap_binds_controller_only(raw_line) and seat != caster_index:
                continue
            return permanent.card.name
    return None


#: A printed run of card types: "artifact, creature, or enchantment"
#: (Damping Engine). Any number of alternatives with any of the printed
#: separators, because the count and the punctuation are facts about one card
#: rather than about the template -- the reading
#: ``cost_modifier_lines._TYPE_LIST`` already makes of the same English one
#: file over.
_BANNABLE_TYPE_LIST = (
    rf"{_BANNABLE_SPELL_TYPES}(?:,? (?:and |or )?{_BANNABLE_SPELL_TYPES})*"
)

#: "**A player who controls more permanents than each other player** can't play
#: lands or cast artifact, creature, or enchantment spells." (Damping Engine.)
#: The fifth scope this file reads CR 601.3a in, and the first whose subject is
#: not a seat any sentence names but one *derived from the board*: whoever is
#: strictly ahead on permanents right now, which may be nobody and may change
#: between one spell and the next.
#:
#: One row for both halves of the printed sentence, for ``_CHOSEN_NAME_BAN``'s
#: reason: a land drop and a cast are one prohibition here, and claiming the
#: casting half alone would ship an artifact that stops a Wrath of God and lets
#: the same player's Island through -- which on a card that exists to slow the
#: player who is ahead is not a card doing less, it is a card doing something
#: else.
#:
#: The types are payload, like every other printed word in this table.
_MOST_PERMANENTS_PLAY_BAN = re.compile(
    r"^a player who controls more permanents than each other player can't "
    rf"play lands or cast (?P<types>{_BANNABLE_TYPE_LIST}) spells$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, for :data:`OWN_CAST_BAN_CLAIM`'s reason: those bans
#: name the seat in the sentence and this one derives it from the board.
MOST_PERMANENTS_PLAY_BAN_CLAIM = "most_permanents_play_ban"

#: Where the permanent records the seats that have bought a turn off its
#: prohibition (CR 116.2d). On the **source**, not on the player, because the
#: offer is the source's and a second Damping Engine is a second prohibition to
#: buy off -- and swept by the cleanup step like every other "until end of
#: turn" record in this engine, which is what the printed duration is.
IGNORED_PLAY_BAN_SEATS = "ignored_play_ban_seats_until_eot"


def _types_in(clause: str) -> tuple[str, ...]:
    """The card types a printed run names, in order.

    Split here rather than in the pattern so the count stays payload: a card
    printing four would need no change.
    """
    parts = re.split(r",| and | or ", clause or "")
    return tuple(word for part in parts if (word := part.strip()))


@lru_cache(maxsize=None)
def most_permanents_play_ban_sentence(sentence: str) -> tuple[str, ...] | None:
    """The spell types one printed *sentence* forbids the leading player, or
    None.

    The **sentence**, where every other reader in this file takes a line,
    because this prohibition is printed with its CR 116.2d escape hatch behind
    it on the same line -- and the two are read by two tables, so the line
    reader below asks this one and ``special_actions`` for the other half.
    """
    match = _MOST_PERMANENTS_PLAY_BAN.match(
        sentence.strip().lower().rstrip(".")
    )
    if match is None:
        return None
    return _types_in(match.group("types"))


@lru_cache(maxsize=None)
def most_permanents_play_ban_line(line: str) -> tuple[str, ...] | None:
    """The spell types a whole printed *line* forbids the leading player.

    Both sentences must be accounted for, for ``_ABILITY_REDUCTION``'s reason
    in ``cost_modifiers``: the offer behind the prohibition is not decoration,
    it is what the player who is ahead can do about it, and a reader claiming
    only the first sentence would ship a permanent that stops a player with no
    way out. The second is read by the table that *performs* it
    (``special_actions``) rather than by a copy of its sentence here, so the
    claim and the offer cannot describe different words.

    A line carrying only the prohibition is a complete, harsher effect and is
    read as one -- the arrangement the Celestial Dawn row in
    ``global_statics`` makes of its own optional second sentence.
    """
    from .special_actions import permanent_special_action_sentence

    sentences = [
        part.strip() for part in (line or "").split(".") if part.strip()
    ]
    if not sentences:
        return None
    banned = most_permanents_play_ban_sentence(sentences[0])
    if banned is None:
        return None
    for extra in sentences[1:]:
        found = permanent_special_action_sentence(extra)
        if found is None or found[0] != IGNORE_BOARD_STATIC:
            return None
    return banned


def _most_permanents_ban_sources(game: "Game", seat: int):
    """Every permanent currently forbidding *seat* to play, with what it stops.

    Yields ``(permanent, banned types)``. A permanent stops *seat* only while
    that seat is the one the sentence describes — strictly ahead of every other
    living player on permanents — and only while that seat has not bought the
    turn off it (CR 116.2d).

    Every battlefield and no seat comparison, for :func:`global_play_timing`'s
    reason: the sentence names nobody's side, so a Damping Engine stops its own
    controller exactly as readily as anybody else.

    The board is asked for a *source* before anybody is asked who is ahead.
    This runs at every cast and at every land drop in every game, and counting
    two players' permanents to discover that nobody printed the sentence is a
    tally taken on every board that has never seen the card.
    """
    from .handlers._conditions import most_permanents_seat

    sources = [
        (permanent, banned)
        for _controller, permanent in game.permanents_with_controller()
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines()
        if (banned := most_permanents_play_ban_line(raw_line)) is not None
    ]
    if not sources or most_permanents_seat(game) != int(seat):
        return
    for permanent, banned in sources:
        if int(seat) in (permanent.metadata.get(IGNORED_PLAY_BAN_SEATS) or ()):
            continue
        yield permanent, banned


def most_permanents_cast_ban(game: "Game", caster_index: int, card) -> str | None:
    """The name of a permanent forbidding *caster_index* to cast *card*, or None.

    The type test is :func:`search_filters.card_has_type` for
    :func:`global_cast_ban`'s reason: a card has **every** type its line names
    (CR 205.2), so an artifact creature is stopped by a ban on either word.
    """
    from .search_filters import card_has_type

    for permanent, banned in _most_permanents_ban_sources(game, caster_index):
        if any(card_has_type(card, wanted) for wanted in banned):
            return permanent.card.name
    return None


def most_permanents_land_ban(game: "Game", seat: int) -> str | None:
    """The name of a permanent forbidding *seat* to play a land, or None.

    The other half of the same printed sentence, asked by ``_land_play_refusal``
    — the one gate every land drop goes through — for ``_CHOSEN_NAME_BAN``'s
    reason: one sentence, one reader, two gates, and neither half able to be
    enforced without the other.
    """
    for permanent, _banned in _most_permanents_ban_sources(game, seat):
        return permanent.card.name
    return None


# --- CR 116.2d: what the player who is ahead may do about it ----------------

#: The kind of battlefield special action the offer below registers.
#: ``aura_restrictions.py`` holds the *attached* twin ("that creature's
#: controller may sacrifice…", Volrath's Curse); this is the board-wide one,
#: and they are two kinds rather than one because what makes the offer is
#: different — an Aura asks its host who controls it, and this asks the board
#: who is ahead.
IGNORE_BOARD_STATIC = "ignore_board_static_until_eot"


@lru_cache(maxsize=None)
def _line_prints_the_escape_hatch(line: str) -> bool:
    """Whether *line* carries CR 116.2d's offer sentence as well as the
    prohibition.

    Asked separately from :func:`most_permanents_play_ban_line`, which accepts
    a line printing the prohibition **alone** — a complete and harsher effect,
    read as one for the reason the Celestial Dawn row in ``global_statics``
    reads its own optional second sentence. The offer must not be inferred from
    the restriction: a card printing only the first sentence gives the player
    who is ahead no way out, and offering one would be this module handing back
    what that card took.
    """
    from .special_actions import permanent_special_action_sentence

    if most_permanents_play_ban_line(line) is None:
        return False
    return any(
        (found := permanent_special_action_sentence(part.strip())) is not None
        and found[0] == IGNORE_BOARD_STATIC
        for part in (line or "").split(".") if part.strip()
    )


def _ignore_board_static_offer(game, permanent):
    """What *permanent* is offering the leading player right now, or None."""
    from .handlers._conditions import most_permanents_seat
    from .special_actions import SpecialActionOffer

    if not any(
        _line_prints_the_escape_hatch(raw_line)
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines()
    ):
        return None
    seat = most_permanents_seat(game)
    if seat is None:
        return None
    if seat in (permanent.metadata.get(IGNORED_PLAY_BAN_SEATS) or ()):
        # Already bought this turn. Offering it again would let a seat pay
        # twice for one turn's relief, which the printed duration does not do —
        # ``aura_restrictions._ignore_static_offer``'s rule, and the same one.
        return None
    # "…**a permanent** of their choice", which is CR 110.1's whole noun: an
    # empty filter is every permanent, and a narrower phrase on a later card is
    # the same field with data in it.
    return SpecialActionOffer(seat=seat, sacrifice={})


def _take_ignore_board_static(game, seat: int, permanent) -> None:
    kept = set(permanent.metadata.get(IGNORED_PLAY_BAN_SEATS) or ())
    permanent.metadata[IGNORED_PLAY_BAN_SEATS] = sorted(kept | {int(seat)})
    game.log.append(
        f"{game.players[seat].name} ignores {permanent.card.name}'s effect "
        "until end of turn (CR 116.2d)"
    )


def clear_ignored_play_bans(permanent) -> bool:
    """CR 514.2's cleanup: an "until end of turn" suspension ends.

    Beside ``aura_restrictions.clear_ignored_restrictions`` in the same sweep,
    because that is what the printed duration is and the two records are one
    rule bought in two shapes. Returns whether anything was cleared.
    """
    return permanent.metadata.pop(IGNORED_PLAY_BAN_SEATS, None) is not None


def _register_board_static_special_action() -> None:
    """Register CR 116.2d's board-wide offer, once.

    Guarded rather than bare, exactly as ``auras`` guards its own:
    ``engine/special_actions.py`` imports this module from inside its seam to
    make sure the registration has happened, and a duplicate kind raises there
    by design.
    """
    from .special_actions import (PERMANENT_SPECIAL_ACTIONS,
                                  PermanentSpecialAction,
                                  register_permanent_special_action)

    if IGNORE_BOARD_STATIC in PERMANENT_SPECIAL_ACTIONS:
        return
    register_permanent_special_action(PermanentSpecialAction(
        kind=IGNORE_BOARD_STATIC,
        offer=_ignore_board_static_offer,
        take=_take_ignore_board_static,
    ))


_register_board_static_special_action()


def global_cast_ban(game: "Game", card) -> str | None:
    """The name of a permanent forbidding *card* from being cast, or None.

    Every battlefield, and no seat comparison: the sentence names nobody, so it
    binds everybody including the permanent's own controller (CR 601.3a).

    ``effective_card`` rather than the printed face, for the reason the cost-tax
    scan reads it: a type word rewritten by a text-changing effect (CR 613 layer
    3) changes which spells the line stops, and this table should not have to
    know that text can change.

    The type test is :func:`search_filters.card_has_type`, not ``primary_type``:
    a card has **every** type its line names (CR 205.2), so an artifact creature
    is a creature spell and Aether Storm stops it.
    """
    from .search_filters import card_has_type

    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            banned = global_cast_ban_line(raw_line)
            if banned is not None and card_has_type(card, banned):
                return permanent.card.name
    return None

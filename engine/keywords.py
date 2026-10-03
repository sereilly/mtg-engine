"""Single write API for keyword abilities (CR 613 layer 6).

Granting and removing an ability share one layer, so which one wins is decided
by **timestamp**, not by which code path happened to run last (CR 613.9's
worked example is exactly this: an Aura granting flying and one removing it,
resolved by whichever is newer). Recording each grant and removal in order is
what makes that answerable.

The engine previously stored one metadata flag per keyword per direction —
``gains_flying``, ``gains_flying_until_eot``, ``loses_flying``,
``gains_trample_until_eot`` and so on — read by an if-chain that checked
removals first and so made removal always win. That is a rule the rules do not
have, and it needed a new flag and a new branch for every keyword.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterable

from .continuous import next_timestamp
from .oracle_types import _COLOR_WORD_TO_SYMBOL

if TYPE_CHECKING:
    from .models import Permanent

# Key under which a permanent's ordered grants/removals live.
ABILITY_EFFECTS = "ability_effects"

# Key under which *derived* grants live — abilities a permanent has because of
# something else on the battlefield right now (a lord's "other Goblins have
# mountainwalk"). They carry no timestamp of their own because they are not
# recorded: the channel is cleared and rebuilt from the board on every
# continuous-effects recompute, exactly like the derived layer-7c P/T channels.
#
# Recording them through :func:`grant_keyword` instead would append one entry
# per recompute forever, and CR 611.3a means the recompute runs constantly.
DERIVED_GRANTS = "derived_ability_grants"

# The mirror channel: abilities a permanent has *lost* because of something else
# on the battlefield right now ("All creatures lose flying", Gravity Sphere).
# Same lifetime and the same reason for it — cleared and rebuilt from the board
# on every recompute, so the source leaving gives the ability back with nothing
# to find and undo. Kept apart from DERIVED_GRANTS rather than signed, because
# layer 6 resolves a grant against a removal and a single list could not say
# which a word was.
DERIVED_REMOVALS = "derived_ability_removals"

# The third derived channel: a whole printed **ability line** a permanent has
# because of something else on the battlefield right now — Tempest's Slivers
# ("All Slivers have \"{2}: Regenerate this permanent.\""), Zombie Master.
#
# ``DERIVED_GRANTS`` above is the *word* half of layer 6 and is no use here for
# the reason :data:`GRANTED_ABILITY_LINES` records: what CR 113.3 grants in
# quotes is a sentence, and only the compiler turns a sentence into behaviour.
# So the sentence is recorded and ``Permanent.effective_card`` folds it in,
# exactly as that channel does — the difference is the *lifetime*, which is why
# this is a separate key rather than a write to that one. A lord's grant lasts
# only while the lord is on the battlefield reaching this permanent, so it is
# cleared and rebuilt on every recompute (CR 611.3a/611.3b); a grant recorded on
# ``GRANTED_ABILITY_LINES`` waits for a *sweep* to end it, and a lord writing
# there would append one copy of its sentence per recompute forever.
DERIVED_ABILITY_LINES = "derived_ability_lines"

# Key under which granted **printed ability lines** live — the third channel in
# this file, and the one for an ability layer 6's word-set cannot carry.
#
# Most keywords are behaviour the engine reads off the word: `has_keyword`
# answers, and flying, trample and the rest are checked wherever they apply. A
# few are not, because the CR *defines* them as an ability rather than
# describing one — CR 702.23a says "Rampage N" **means** "Whenever this creature
# becomes blocked, …", and `engine/rampage.py` accordingly rewrites the printed
# line into the trigger it already is. Nothing downstream of the compiler knows
# the word, which is exactly why granting one as a layer-6 keyword would grant
# nothing at all: the compiler has already run, over a card that did not say it.
#
# So a grant of such an ability grants the *line*, and `Permanent.effective_card`
# folds it into the rules text — the same channel a board-wide static's granted
# ability already uses (`engine/global_statics.py`), for the same reason. From
# there the compiler produces the ability like any printed one and the
# becomes-blocked dispatcher fires it without knowing a spell granted it.
GRANTED_ABILITY_LINES = "granted_ability_lines"

# The mirror channel: a *printed* ability line an effect has taken away
# (CR 613.1f, layer 6 — ability-removing effects).
#
# ``DERIVED_REMOVALS`` above is the keyword half — it names a word, and
# ``has_keyword`` asks it. That is no use for an ability the compiler builds out
# of a whole printed sentence: Takklemaggot's returning enchantment loses
# "enchant creature", and there is no keyword flag anywhere that says whether a
# permanent has an enchant ability. What says so is the sentence, so what is
# removed is the sentence — recorded here and dropped by
# ``Permanent.effective_card`` in the same fold that appends a granted one.
#
# Recorded rather than applied for the reason every other layer channel is:
# the removal is a contribution, so nothing has to remember a delta and the
# printed card is never rewritten.
REMOVED_ABILITY_LINES = "removed_ability_lines"

# The *third* removal channel, and the one a line-derived keyword needs.
#
# ``REMOVED_ABILITY_LINES`` above takes a whole printed sentence away by
# matching it, and ``ABILITY_EFFECTS`` takes a *word* out of layer 6's set. A
# line-derived keyword (:data:`LINE_DERIVED_KEYWORDS`) is neither: the ability
# is built by the compiler out of a printed keyword line, so removing the word
# from layer 6 leaves the trigger compiled and firing, and removing "the line"
# by matching it would have to match "Flanking (Whenever a creature without
# flanking blocks this creature, …)" — reminder text and all — and would take
# the whole line even where the creature prints two keywords on it.
#
# So what is recorded here is the **keyword**, and
# ``Permanent.effective_card`` strikes that part out of every keyword line it
# has left after the grants are folded in. After the grants, deliberately:
# Barbed Foliage takes flanking off a creature Agility granted it to, and a
# removal applied before the grant would leave the granted line standing.
#
# Recorded rather than applied, and durationed, for the reason the grant
# channel beside it is: the sweep that ends it is named by the entry, so no
# turn step carries a list of what to undo.
REMOVED_ABILITY_KEYWORDS = "removed_ability_keywords"

# The **fourth** removal channel, and the one a per-permanent blanket needs.
#
# The three above each take something *named* away: a printed sentence, a
# layer-6 word, a line-derived keyword. "Target creature loses all abilities"
# (Humble, Soul Sculptor) names none of them — CR 613.1f's blanket, which the
# engine had only as a board-wide static read off a permanent's text
# (``global_statics.removes_all_abilities``, Humility and Titania's Song). A
# static has no way to say "this one creature, until end of turn": it is
# re-derived from the board on every recompute, so a permanent that entered
# afterwards is covered by it and a permanent the spell named is not.
#
# So this is a record on the permanent, in the durationed shape the two
# channels above already use, and ``Permanent.effective_card`` reads it in the
# same fold that answers the static. One reader for both, which is what makes
# the four consumers of "what does it say?" — the keyword set, the activated
# abilities off the compiled program, the triggered ones off the card, the
# statics re-derived from the text — agree without any of them knowing there
# are two ways to lose everything.
ALL_ABILITIES_REMOVED = "all_abilities_removed"

#: Which keyword words that applies to. The membership test is not "does it have
#: a number": it is "does the compiler build this keyword's behaviour out of the
#: printed line". Prowess and lifelink also have behaviour the layer system does
#: not store, but `has_keyword` is what reads them, so a layer-6 grant reaches
#: them. Rampage's reader is `compile_card_oracle`, and so is flanking's
#: (CR 702.25a defines it as a triggered ability — `engine/flanking.py`).
#:
#: **Granting the line gives the word back, which flanking is the first keyword
#: to need.** Layer 6's ability set is seeded from the compiled *keyword lines*
#: as well as from the ingested field (`layer_bridge._TEXT_KEYWORDS`), so a
#: granted "Flanking" line is folded into the effective card, compiles to a
#: keyword line, and lands back in the word set — which is what lets Agility's
#: enchanted creature both trigger and count as "with flanking" for the next
#: flanker's filter. Cumulative upkeep is deliberately absent: no card in the
#: pool grants or removes it, and a row here with nothing behind it is a claim
#: nothing checks.
LINE_DERIVED_KEYWORDS = frozenset({"rampage", "flanking"})


def keyword_ability_name(keyword: str) -> str:
    """*keyword* without its argument — the name of the ability itself.

    "Protection from black" is the keyword *protection* carrying a quality
    (CR 702.16a) and "rampage 2" is *rampage* carrying its N (CR 702.23a); the
    registries in this engine list abilities, not every argument one can take.

    Here rather than in the grammar because both sides of the colon need it: the
    lowering asks whether a grant names an implemented ability, and the handler
    asks which channel to put it on. Two spellings of "strip the argument" is
    how those two come to disagree about what a card said.

    Which keywords take a number is the parser's vocabulary — imported here
    rather than restated, and imported inside the function because this module
    sits underneath the grammar in the import order.
    """
    from .banding import BANDS_WITH_OTHER, is_bands_with_other
    from .grammar.vocabulary import NUMERIC_ARGUMENT_KEYWORDS

    if keyword.startswith("protection from "):
        return "protection"
    # "Bands with other legendary creatures" is the ability *bands with other*
    # carrying a quality (CR 702.22b) — the same shape protection has one line
    # up, so the registry holds one entry and every printed quality strips to
    # it. Without this, asking the registry about a granted band would be asking
    # about a word no list can contain: the quality is whatever the card prints.
    if is_bands_with_other(keyword):
        return BANDS_WITH_OTHER
    head = keyword.split(" ")[0]
    return head if head in NUMERIC_ARGUMENT_KEYWORDS else keyword


def protection_quality(word: str) -> tuple[str, str] | None:
    """The canonical quality one word of a protection clause names, or None.

    Four families (CR 702.16, the qualities this engine models): a colour
    ("white"), "multicolored" (Basri's Lieutenant), a card type ("artifacts",
    Angelic Curator; "planeswalkers", Sparkhunter Masticore), and a creature
    subtype ("Demons", Baneslayer Angel; "Dogs", Pack Leader's flock). Both
    print pluralized, the catalogs store singulars.

    **The card-type family reads the catalog rather than one word.** It was
    the literal pair ``("planeswalker", "planeswalkers")``, which is a list of
    the card types somebody had met — and the direction that costs is the
    silent one: ``oracle._is_supported_static_creature_line`` admits any line
    beginning "protection from " *without asking this function at all*, so
    Yavimaya Scion ("Protection from artifacts") reported supported, compiled
    to a bare ``static_line``, and had no protection from anything. A word this
    function cannot read is a shield that is simply absent, and only the cards
    printing an unmet type can tell you it happened.

    Here rather than beside its consumer for :func:`keyword_ability_name`'s
    reason exactly: both sides of the grant need it. ``permanent_state``
    reads it to turn a printed clause into the quality a shield answers to,
    and the two front ends that *admit* a "have protection from X" anthem —
    ``lord_buffs.lord_buff_for`` and ``grammar/statics.py``'s lowering — read
    it to refuse a word nothing can answer. A quality only one of them knew
    would be an anthem that compiles, reports supported, and protects nobody.
    """
    word = (word or "").strip().lower()
    if not word:
        return None
    symbol = _COLOR_WORD_TO_SYMBOL.get(word)
    if symbol:
        return ("color", symbol)
    if word == "multicolored":
        return ("multicolored", "")
    # Lazily for the reason :func:`keyword_ability_name` imports lazily: this
    # module sits underneath the grammar in the import order.
    from .grammar.vocabulary import CARD_TYPES, CREATURE_TYPES

    singular = word[:-1] if word.endswith("s") else word
    # Card types before creature types, and the two catalogs share no word
    # (asserted by ``tests/engine/test_keyword_registry.py``) — so the order is
    # documentation rather than a tie-break. Both answers reach
    # ``_permanent_has_quality``'s one ``has_type`` call, which resolves through
    # the layer system: an animated artifact land is an artifact source and a
    # printed type line would say otherwise.
    if word in CARD_TYPES:
        return ("card_type", word)
    if singular in CARD_TYPES:
        return ("card_type", singular)
    if word in CREATURE_TYPES:
        return ("subtype", word)
    if singular in CREATURE_TYPES:
        return ("subtype", singular)
    return None


#: How long a layer-6 keyword grant or removal lasts, each key naming the sweep
#: that ends it. The same table :data:`GRANTED_ABILITY_DURATIONS` is for a
#: quoted ability line, and literally the same object: a card printing one
#: duration over a keyword and another over a quote must not find two different
#: answers, and two frozensets side by side is how they come to differ.
#:
#: It was a ``until_eot`` boolean, and round 28 fixed exactly this shape one
#: channel over. A boolean is a duration table with two rows, so every printed
#: duration that was not "until end of turn" silently **became** it: "until end
#: of combat" ran on through the second main phase and the whole of the
#: opponent's turn, "until your next turn" ended a step early, and the lowering
#: had no table to refuse against — it passed ``until_eot=True`` and lost the
#: word. ``None`` — no printed duration — lasts until the end of the game
#: (CR 611.2a's second sentence) and appears in no sweep.
#: …and the windows that end on an **event** instead of at a turn step
#: (CR 611.2a, `engine/event_durations.py`): "until a player casts a creature
#: spell" (Soul Sculptor). Folded in rather than listed again, because that
#: module *is* their sweep — this table's whole content is "a duration with
#: something behind it", so a row added there becomes legal here for the reason
#: it should, and a row removed stops being legal the same moment.
#:
#: Imported inside the function below rather than at module scope: the sweep
#: module imports the four ``clear_*`` functions from this one, and naming it
#: at the top would close the cycle.
KEYWORD_GRANT_DURATIONS: frozenset[str] = frozenset({
    "end_of_turn", "end_of_combat", "your_next_upkeep",
})


def _sweepable_durations() -> frozenset[str]:
    """Every duration something in this engine ends."""
    from .event_durations import EVENT_DURATION_KINDS

    return KEYWORD_GRANT_DURATIONS | EVENT_DURATION_KINDS

#: The durations whose sweep has to know *whose* they are. "Until **your** next
#: upkeep" is one player's step, and CR 109.5 makes that the controller of the
#: ability rather than of the affected permanent — so the seat is frozen when
#: the grant is recorded and compared when it is swept.
SEATED_GRANT_DURATIONS: frozenset[str] = frozenset({"your_next_upkeep"})


def _check_duration(duration: str | None, seat: int | None, table) -> None:
    """Refuse a duration with no sweep, and a seated one with no seat.

    Both channels below ask this, so "which durations exist" is answered once.
    Loudly, because a duration nothing ends is a grant that outlives what the
    card said — the failure the table exists to prevent.
    """
    if duration is not None and duration not in table:
        # The event-ended windows are folded in here rather than into the table
        # itself: the table is a module constant and this is the one question
        # asked of it, so widening the *question* keeps the constant importable
        # from the sweep module without a cycle. Asked second, so nothing
        # changes for the three turn-step words.
        if duration in _sweepable_durations():
            return
        raise ValueError(f"no sweep ends a granted ability at {duration!r}")
    if duration in SEATED_GRANT_DURATIONS and seat is None:
        raise ValueError(f"a {duration!r} grant needs the seat whose step ends it")


def _expires_at(entry: dict, duration: str, seat: int | None) -> bool:
    """Whether *entry* is one the sweep for *duration* (and *seat*) takes."""
    if entry.get("duration") != duration:
        return False
    return seat is None or entry.get("seat") == seat


def _record(
    perm: Permanent, keyword: str, *, grant: bool,
    duration: str | None, seat: int | None,
) -> None:
    _check_duration(duration, seat, KEYWORD_GRANT_DURATIONS)
    entry: dict = {
        "keyword": keyword.lower(),
        "grant": grant,
        "duration": duration,
        "timestamp": next_timestamp(),
    }
    if seat is not None:
        entry["seat"] = seat
    effects = perm.metadata.setdefault(ABILITY_EFFECTS, [])
    effects.append(entry)


def grant_keyword(
    perm: Permanent, keyword: str, *,
    duration: str | None = None, seat: int | None = None,
) -> None:
    """Layer 6: give *perm* a keyword ability from now (613.7b).

    *duration* names the sweep that will take it away again, a key of
    :data:`KEYWORD_GRANT_DURATIONS`.
    """
    _record(perm, keyword, grant=True, duration=duration, seat=seat)


def remove_keyword(
    perm: Permanent, keyword: str, *,
    duration: str | None = None, seat: int | None = None,
) -> None:
    """Layer 6: take a keyword ability away. Whether this beats a grant is
    decided by timestamp, so a later grant restores the ability."""
    _record(perm, keyword, grant=False, duration=duration, seat=seat)


def expand_ability_removal(names: Iterable[str], present: Iterable[str]) -> set[str]:
    """Which abilities a layer-6 removal of *names* actually takes away.

    A removal may name a **family** rather than an ability, and a family name is
    not something any permanent has — so removing it literally would take
    nothing away and report success, which is the silent half of a removal. What
    the name stands for is only knowable here, against the permanent's computed
    ability set, because the removal was recorded before that set existed.

    Two families print one today, and the second is why this moved out of
    `engine/banding.py`:

    * **banding** — CR 702.22b: "If an effect causes a permanent to lose
      banding, the permanent loses all 'bands with other' abilities as well."
      Tolaria prints both halves and Shelkin Brownie only the second, so neither
      card is evidence for where the rule lives: it lives here, and any future
      "loses banding" reaches it without knowing the rule exists.
    * **landwalk** — CR 702.14a builds a landwalk's name out of a printed
      quality, so the members are open and no list can hold them. The parser
      used to expand "all landwalk abilities" into the five basics plus
      desertwalk, which is what `IMPLEMENTED_KEYWORDS` happens to name, and
      Hammerheim therefore left Rime Dryad's **snow** forestwalk in place: the
      card did less than it prints, silently, with the suite green.
      `engine/evasion_negation.py` had already learned this and answers with the
      family word for the same reason.

    Each family is a *predicate* over what the permanent has, never a list.
    """
    from .banding import BANDS_WITH_OTHER, band_quality
    from .landwalk import LANDWALK, is_landwalk

    families: tuple[tuple[frozenset[str], "Callable[[str], bool]"], ...] = (
        (frozenset({"banding", BANDS_WITH_OTHER}), lambda a: band_quality(a) is not None),
        (frozenset({LANDWALK}), is_landwalk),
    )
    removed = {name for name in names}
    for named, belongs in families:
        if removed & named:
            removed |= {ability for ability in present if belongs(ability)}
    return removed


def clear_granted_keywords(
    perm: Permanent, duration: str, *, seat: int | None = None
) -> None:
    """Drop the grants and removals whose duration is *duration*, at that sweep.

    The twin of :func:`clear_granted_ability_lines`, called beside it at every
    sweep: a keyword and a quoted line granted by the same sentence end at the
    same moment, and two spellings of "which entries go" is how they come to
    disagree.

    *seat* narrows to the entries armed by one player, which is what "**your**
    next upkeep" means — a seated duration swept without one would take an
    opponent's grant at the wrong step.
    """
    effects = perm.metadata.get(ABILITY_EFFECTS)
    if not effects:
        return
    remaining = [
        entry for entry in effects if not _expires_at(entry, duration, seat)
    ]
    if len(remaining) == len(effects):
        return
    if remaining:
        perm.metadata[ABILITY_EFFECTS] = remaining
    else:
        perm.metadata.pop(ABILITY_EFFECTS, None)


def ability_effects(perm: Permanent) -> list[dict]:
    """The recorded grants and removals, oldest first."""
    return list(perm.metadata.get(ABILITY_EFFECTS) or ())


def clear_derived_grants(perm: Permanent) -> None:
    """Drop the grants and removals derived from the current board (CR 611.3b).

    Called by the same function that rebuilds them. Splitting the clear from the
    rebuild is how a derived channel turns into an accumulating one — and both
    directions are cleared here, together, for the same reason: a removal left
    behind by a pass that only cleared the grants would keep taking an ability
    away after its source had gone.
    """
    perm.metadata.pop(DERIVED_GRANTS, None)
    perm.metadata.pop(DERIVED_REMOVALS, None)
    # …and the sentence half of the same layer, cleared in the same breath. A
    # line left behind by a clear that only knew about the words would keep a
    # dead lord's ability on the board with nothing to point at.
    perm.metadata.pop(DERIVED_ABILITY_LINES, None)


#: The durations a granted ability line can be given, each naming the sweep that
#: ends it. The same shape as `pt.TEMPORARY_PT_CHANNELS` and for the same
#: reason: a duration is implemented by *having a sweep*, not by having a word,
#: so the lowering can refuse a printed duration by asking this table instead of
#: by carrying a list of its own. ``None`` — no printed duration — lasts as long
#: as the object (CR 611.3b: a static ability's effect "applies at all times
#: that the permanent generating it is on the battlefield") and appears in no
#: sweep.
GRANTED_ABILITY_DURATIONS: frozenset[str] = KEYWORD_GRANT_DURATIONS


def grant_ability_line(
    perm: Permanent, line: str, *,
    duration: str | None = None, seat: int | None = None,
) -> None:
    """Layer 6: give *perm* a printed ability *line* (see GRANTED_ABILITY_LINES).

    Recorded rather than applied, and read back in grant order, because the
    compiler is what turns the line into an ability — this channel only has to
    say what the permanent now says.

    *duration* names the sweep that will take it away again, a key of
    :data:`GRANTED_ABILITY_DURATIONS`. It was a ``until_eot`` boolean, which is
    a duration table with exactly two rows and no room for the third: Johan
    grants "Johan can't attack" **until end of combat**, and a boolean would
    have recorded that as end of turn and left the grant running through the
    second main phase and the whole of the opponent's turn.
    """
    _check_duration(duration, seat, GRANTED_ABILITY_DURATIONS)
    # CR 602.5c: a restriction on an ability a permanent *acquires* applies only
    # to that ability as acquired, so a fresh grant of a sentence carrying a
    # use budget brings a fresh budget with it. Cleared here rather than at the
    # sweep that ends the grant, because a line printed on the card itself is
    # never granted and must keep the budget it has spent.
    from .activation_restrictions import clear_once_only_tally

    clear_once_only_tally(perm, line)
    lines = perm.metadata.setdefault(GRANTED_ABILITY_LINES, [])
    entry: dict = {"line": line, "duration": duration}
    if seat is not None:
        entry["seat"] = seat
    lines.append(entry)


def granted_ability_lines(perm: Permanent) -> tuple[str, ...]:
    """The printed ability lines *perm* has been granted, oldest first."""
    return tuple(entry["line"] for entry in perm.metadata.get(GRANTED_ABILITY_LINES) or ())


def clear_granted_ability_lines(
    perm: Permanent, duration: str, *, seat: int | None = None
) -> None:
    """Drop the granted lines whose duration is *duration*, at that sweep.

    The twin of :func:`clear_granted_keywords`, called beside it at cleanup
    and again at the end of combat step: a grant that outlived its duration
    would leave the permanent compiling an ability it no longer has.
    """
    lines = perm.metadata.get(GRANTED_ABILITY_LINES)
    if not lines:
        return
    remaining = [
        entry for entry in lines if not _expires_at(entry, duration, seat)
    ]
    if len(remaining) == len(lines):
        return
    if remaining:
        perm.metadata[GRANTED_ABILITY_LINES] = remaining
    else:
        perm.metadata.pop(GRANTED_ABILITY_LINES, None)


def add_derived_grant(perm: Permanent, keyword: str) -> None:
    """Layer 6: *perm* has *keyword* for as long as the source keeps granting it."""
    granted = perm.metadata.setdefault(DERIVED_GRANTS, [])
    lowered = keyword.lower()
    if lowered not in granted:
        granted.append(lowered)


def derived_grants(perm: Permanent) -> tuple[str, ...]:
    """The abilities *perm* currently has from a board-wide source."""
    return tuple(perm.metadata.get(DERIVED_GRANTS) or ())


def add_derived_removal(perm: Permanent, keyword: str) -> None:
    """Layer 6: *perm* lacks *keyword* for as long as the source keeps taking
    it away."""
    removed = perm.metadata.setdefault(DERIVED_REMOVALS, [])
    lowered = keyword.lower()
    if lowered not in removed:
        removed.append(lowered)


def derived_removals(perm: Permanent) -> tuple[str, ...]:
    """The abilities a board-wide source is currently taking from *perm*."""
    return tuple(perm.metadata.get(DERIVED_REMOVALS) or ())


def add_derived_ability_line(perm: Permanent, line: str) -> None:
    """Layer 6: *perm* says *line* for as long as the source keeps granting it.

    Deduplicated on the sentence, because CR 611.3a makes two lords printing the
    same quoted ability two grants of one sentence and the compiler would build
    two identical abilities out of a repeat — two rows in the UI's ability list,
    two entries the activation index has to tell apart, and nothing gained.
    """
    lines = perm.metadata.setdefault(DERIVED_ABILITY_LINES, [])
    if line not in lines:
        lines.append(line)


def derived_ability_lines(perm: Permanent) -> tuple[str, ...]:
    """The printed ability lines a board-wide source currently gives *perm*."""
    return tuple(perm.metadata.get(DERIVED_ABILITY_LINES) or ())


def remove_ability_line(
    perm: Permanent, line: str, *,
    duration: str | None = None, seat: int | None = None,
) -> None:
    """Layer 6: *perm* no longer has the printed ability *line*.

    Matched on the normalized sentence rather than the printed one, because the
    card that takes the ability away quotes it in lower case ("It loses
    \"enchant creature\"") while the card prints it capitalised. One
    normalization, shared with :func:`removed_ability_lines`, so what is
    recorded and what is dropped cannot disagree.

    Two shapes of entry. With no *duration* the removal is indefinite
    (Takklemaggot, the Licids) and the entry is the bare normalized sentence,
    exactly as it always was. "**Until end of turn**, this creature loses
    "<line>"" (Glittering Lion) carries a duration, so its entry is a dict in
    the durationed shape the grant channel uses, and
    :func:`clear_removed_ability_lines` is the sweep that gives it back.
    """
    removed = perm.metadata.setdefault(REMOVED_ABILITY_LINES, [])
    normalized = normalized_ability_line(line)
    if not normalized:
        return
    if duration is None:
        if normalized not in removed:
            removed.append(normalized)
        return
    _check_duration(duration, seat, GRANTED_ABILITY_DURATIONS)
    entry: dict = {"line": normalized, "duration": duration}
    if seat is not None:
        entry["seat"] = seat
    removed.append(entry)


def _removed_line_text(entry) -> str:
    """The normalized sentence one removal entry names, whichever shape it is."""
    return entry["line"] if isinstance(entry, dict) else entry


def clear_removed_ability_lines(
    perm: Permanent, duration: str, *, seat: int | None = None
) -> None:
    """Give back the removed ability lines whose duration is *duration*.

    The line twin of :func:`clear_removed_ability_keywords`, called beside it at
    every duration boundary. An indefinite removal (a bare string entry) is
    never taken by a sweep.
    """
    entries = perm.metadata.get(REMOVED_ABILITY_LINES)
    if not entries:
        return
    remaining = [
        entry for entry in entries
        if not (isinstance(entry, dict) and _expires_at(entry, duration, seat))
    ]
    if len(remaining) == len(entries):
        return
    if remaining:
        perm.metadata[REMOVED_ABILITY_LINES] = remaining
    else:
        perm.metadata.pop(REMOVED_ABILITY_LINES, None)


def restore_ability_line(perm: Permanent, line: str) -> bool:
    """Layer 6's undo: *perm* has the printed ability *line* again.

    :func:`remove_ability_line` has no duration, which is the honest reading
    while nothing in the pool gives an ability back on a timer — but a
    CR 116.2c special action is not a timer. A Licid's controller may pay to
    end the effect the Licid's own ability created, and the ability it lost is
    part of that effect; without this the offer would hand back the type and
    leave the permanent an enchantment that can never become a creature again.

    Returns whether anything was recorded, so a caller can tell "the ability
    came back" from "it had never gone".
    """
    removed = perm.metadata.get(REMOVED_ABILITY_LINES)
    if not removed:
        return False
    normalized = normalized_ability_line(line)
    remaining = [
        entry for entry in removed if _removed_line_text(entry) != normalized
    ]
    if len(remaining) == len(removed):
        return False
    if remaining:
        perm.metadata[REMOVED_ABILITY_LINES] = remaining
    else:
        perm.metadata.pop(REMOVED_ABILITY_LINES, None)
    return True


def normalized_ability_line(line: str) -> str:
    """One spelling of a printed ability line, for comparing two of them."""
    return " ".join((line or "").split()).strip().lower().rstrip(".")


def removed_ability_lines(perm: Permanent) -> tuple[str, ...]:
    """The printed ability lines an effect has taken away from *perm*."""
    return tuple(
        _removed_line_text(entry)
        for entry in perm.metadata.get(REMOVED_ABILITY_LINES) or ()
    )


def remove_all_abilities(
    perm: Permanent, *, duration: str | None = None, seat: int | None = None
) -> None:
    """Layer 6: *perm* loses **every** ability (CR 613.1f).

    The blanket twin of :func:`remove_ability_keyword` above, and recorded in
    the same durationed shape for the same reason: the sweep that gives the
    abilities back is named by the entry, so no turn step carries a list of
    what to undo, and an effect ending restores whatever the other
    contributions still say.

    *duration* is a key of :data:`GRANTED_ABILITY_DURATIONS`, the table the
    grant side reads — "until end of turn" has to mean one moment whichever
    direction the sentence points.
    """
    _check_duration(duration, seat, GRANTED_ABILITY_DURATIONS)
    entries = perm.metadata.setdefault(ALL_ABILITIES_REMOVED, [])
    entry: dict = {"duration": duration}
    if seat is not None:
        entry["seat"] = seat
    entries.append(entry)


def all_abilities_removed(perm: Permanent) -> bool:
    """Whether an effect has taken every one of *perm*'s abilities away."""
    return bool(perm.metadata.get(ALL_ABILITIES_REMOVED))


def clear_all_abilities_removals(
    perm: Permanent, duration: str, *, seat: int | None = None
) -> None:
    """Give the abilities back where the removal's window is *duration*.

    The fourth member of the sweep group called at every duration boundary
    (:func:`clear_granted_keywords`, :func:`clear_granted_ability_lines`,
    :func:`clear_removed_ability_keywords`): a removal that outlived its window
    would leave the permanent a vanilla creature for the rest of the game.
    """
    entries = perm.metadata.get(ALL_ABILITIES_REMOVED)
    if not entries:
        return
    remaining = [
        entry for entry in entries if not _expires_at(entry, duration, seat)
    ]
    if len(remaining) == len(entries):
        return
    if remaining:
        perm.metadata[ALL_ABILITIES_REMOVED] = remaining
    else:
        perm.metadata.pop(ALL_ABILITIES_REMOVED, None)


def remove_ability_keyword(
    perm: Permanent, keyword: str, *, duration: str | None = None,
    seat: int | None = None,
) -> None:
    """Layer 6: *perm* loses a **line-derived** keyword ability.

    The mirror of ``handlers/pump._grant_one_keyword``'s line grant, and the
    mirror for the same reason: CR 702.25a *defines* flanking as a triggered
    ability, so the compiler builds it out of the printed line and layer 6's
    word set is not where its reader looks. Granting one grants the line;
    removing one has to strike the line's keyword part, which is what
    :meth:`Permanent.effective_card` does with what is recorded here.

    *duration* names the sweep that will give the ability back, a key of
    :data:`GRANTED_ABILITY_DURATIONS` — the same table the grant side reads,
    because "until end of turn" has to mean one moment whichever direction the
    sentence points.
    """
    _check_duration(duration, seat, GRANTED_ABILITY_DURATIONS)
    entries = perm.metadata.setdefault(REMOVED_ABILITY_KEYWORDS, [])
    entry: dict = {"keyword": keyword.lower(), "duration": duration}
    if seat is not None:
        entry["seat"] = seat
    entries.append(entry)


def removed_ability_keywords(perm: Permanent) -> tuple[str, ...]:
    """The line-derived keyword abilities an effect has taken from *perm*."""
    return tuple(
        entry["keyword"]
        for entry in perm.metadata.get(REMOVED_ABILITY_KEYWORDS) or ()
    )


def clear_removed_ability_keywords(
    perm: Permanent, duration: str, *, seat: int | None = None
) -> None:
    """Give back the keyword abilities whose duration is *duration*.

    The third member of the sweep trio called at every duration boundary
    (:func:`clear_granted_keywords`, :func:`clear_granted_ability_lines`): a
    removal that outlived its duration would leave the permanent silently short
    an ability it has back.
    """
    entries = perm.metadata.get(REMOVED_ABILITY_KEYWORDS)
    if not entries:
        return
    remaining = [
        entry for entry in entries if not _expires_at(entry, duration, seat)
    ]
    if len(remaining) == len(entries):
        return
    if remaining:
        perm.metadata[REMOVED_ABILITY_KEYWORDS] = remaining
    else:
        perm.metadata.pop(REMOVED_ABILITY_KEYWORDS, None)


__all__ = [
    "ABILITY_EFFECTS", "DERIVED_ABILITY_LINES", "DERIVED_GRANTS",
    "DERIVED_REMOVALS",
    "GRANTED_ABILITY_LINES", "REMOVED_ABILITY_LINES",
    "REMOVED_ABILITY_KEYWORDS",
    "remove_ability_line", "removed_ability_lines", "normalized_ability_line",
    "clear_removed_ability_lines",
    "remove_ability_keyword", "removed_ability_keywords",
    "clear_removed_ability_keywords",
    "LINE_DERIVED_KEYWORDS", "ability_effects", "add_derived_ability_line",
    "add_derived_grant",
    "add_derived_removal", "derived_removals",
    "GRANTED_ABILITY_DURATIONS",
    "clear_derived_grants", "clear_granted_ability_lines",
    "KEYWORD_GRANT_DURATIONS", "SEATED_GRANT_DURATIONS",
    "clear_granted_keywords", "derived_ability_lines", "derived_grants",
    "grant_ability_line",
    "keyword_ability_name",
    "expand_ability_removal",
    "granted_ability_lines", "grant_keyword", "remove_keyword",
]

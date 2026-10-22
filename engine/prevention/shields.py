"""The shields a recipient was **given** — what each one does when damage would
be dealt (CR 615.1, 615.7-615.8, 702.16e).

``engine/shields.py`` is what a shield *is* (one collection per recipient:
what it answers to, how much it absorbs, how long it lasts); this module is
what one *does*. Something resolved and armed it, and it is spent: the
directional "dealt to and/or dealt by" marker (and the static form of the same
sentence, printed on an Aura or a creature), the collection read as CR 616.1's
pure half — which shields of a kind could modify this event — and then the
shields themselves: protection's damage half, the combat blankets, Forcefield's
cap, half prevention, Reverse Damage, the exile, team and reflect riders, the
chosen-source and colour shields, the subject and targeting blankets, the
resolving object's own shield, and the numeric pool.

Split out of ``prevention.py`` at the 2,000-line cap's split round, on the line
that module's own last section drew: a permanent's **own** static prevention —
no charges, no lifetime, nothing to sweep — is ``static.py``'s.
"""

from __future__ import annotations

import re

from ..damage_source_colors import damage_source_colors
from ..effect_ordering import affected_seat
from ..models import PlayerState
from ..shields import (END_OF_TURN as SHIELD_END_OF_TURN, PREVENT_ALL_BUT,
                       PREVENT_AND_DAMAGE_SOURCE, PREVENT_AND_GAIN_LIFE,
                       PREVENT_HALF, PREVENT_FROM_COLOR,
                       PREVENT_FROM_SUBJECT, PREVENT_FROM_TARGETING_SOURCE,
                       PREVENT_BY_RESOLVING_OBJECT,
                       PREVENT_NEXT_N, PREVENT_NEXT_N_AND_COUNTERS,
                       PREVENT_WHOLE, PREVENT_AND_EXILE,
                       PREVENT_ALL_FROM_CHOSEN_SOURCE,
                       PREVENT_TEAM, Shield, drop_spent, shields_on)
from .registry import (
    CHOSEN_SOURCE_BLANKET, COLOR_SHIELD, COMBAT_BLANKET, COMBAT_BLANKET_EXCEPT,
    COMBAT_BLANKET_SCOPED, COMBAT_SHIELD, GENERIC_CAP, GENERIC_EXILE_SHIELD,
    GENERIC_HALF, GENERIC_REFLECT_SHIELD, GENERIC_SHIELD, GENERIC_TEAM_SHIELD,
    GENERIC_WHOLE, POOL, POOL_WITH_COUNTERS, PROTECTION, SOURCE_CAP,
    SOURCE_EXILE_SHIELD, SOURCE_HALF, SOURCE_REFLECT_SHIELD, SOURCE_SHIELD,
    SOURCE_TEAM_SHIELD, SOURCE_WHOLE, SPELL_BLANKET, SUBJECT_BLANKET,
    TARGETING_BLANKET, Applicability, PreventionOutcome, prevention_effect,
    source_has_type,
)


#: Which end of the event a combat shield covers. "Prevent all combat damage
#: that would be dealt **to and dealt by** that creature this turn" (Ebony
#: Horse, Maze of Ith) covers both; the Legends cards need the halves, because
#: "…that would be dealt **by** target creature this turn" (Horn of Deafening,
#: Lady Evangela) leaves the creature perfectly able to *take* combat damage,
#: and folding it into the two-way shield would make those creatures unkillable
#: in combat.
#:
#: Ebony Horse's used to be a bare boolean on its own metadata key, written by a
#: name-keyed hook. Maze of Ith prints the same sentence, which is what that
#: hook's entry bar forbids — so the sentence became a grammar production and
#: the boolean became the two-way value of this one record.
COMBAT_SHIELD_BY = "by"
COMBAT_SHIELD_TO = "to"
COMBAT_SHIELD_BOTH = "to_and_by"

#: The directional turn-long marker, swept by ``_EOT_METADATA_KEYS``.
#:
#: The record is a list of ``[direction, combat_only]`` pairs rather than one
#: direction word, because **how wide the shield is, is payload**: "Prevent all
#: *combat* damage that would be dealt by target creature this turn" (Horn of
#: Deafening, Lady Evangela) and "Prevent all damage that would be dealt this
#: turn by target creature you control" (Kry Shield) are the same sentence one
#: word apart. A second metadata key per width would be a second mechanism for
#: a narrowing, and the wide one would then have to be remembered in every place
#: the narrow one already is.
_COMBAT_SHIELD_DIRECTION_KEY = "prevent_combat_damage_direction_until_eot"


def add_directional_shield(
    perm, direction: str, *, combat_only: bool, lifetime: str = SHIELD_END_OF_TURN,
) -> None:
    """Shield *perm* in *direction* until *lifetime* ends (CR 615.1).

    *combat_only* is the printed word "combat": True covers combat damage
    alone, False covers damage of every kind. Duplicate records are folded, so
    two resolutions of the same effect leave one entry.

    *lifetime* is the printed window, and it is a third element of the entry for
    the reason ``combat_only`` is the second: **how long the shield lasts is
    payload**. "…dealt to and dealt by that creature **this turn**" (Ebony
    Horse, Maze of Ith) and "…**this combat**" (Winter's Chill) are the same
    sentence four characters apart, and a card whose shield outlived its combat
    would go on preventing through a second combat phase the card never
    mentions. It takes the same two words ``engine/shields.py`` gives every
    other shield, so the two sweeps that already run — end of combat, and
    cleanup — are the two that end these.
    """
    record = [list(entry) for entry in (perm.metadata.get(_COMBAT_SHIELD_DIRECTION_KEY) or ())]
    entry = [str(direction), bool(combat_only), str(lifetime)]
    if entry not in record:
        record.append(entry)
    perm.metadata[_COMBAT_SHIELD_DIRECTION_KEY] = record


def clear_directional_shields(perm, lifetime: str) -> None:
    """Drop *perm*'s directional shields whose window is *lifetime*.

    The twin of ``shields.clear_shields`` for the marker form, called from the
    same end-of-combat sweep — so "this combat" is implemented by *having a
    sweep* rather than by the phrase being read and then forgotten. The
    end-of-turn entries are left to ``_EOT_METADATA_KEYS``, which has always
    cleared the whole key at cleanup.
    """
    metadata = getattr(perm, "metadata", None)
    if not metadata:
        return
    kept = [
        list(entry) for entry in (metadata.get(_COMBAT_SHIELD_DIRECTION_KEY) or ())
        if _shield_lifetime(entry) != lifetime
    ]
    if kept:
        metadata[_COMBAT_SHIELD_DIRECTION_KEY] = kept
    else:
        metadata.pop(_COMBAT_SHIELD_DIRECTION_KEY, None)


def _shield_lifetime(entry) -> str:
    """One directional record's window. Entries written before the window was
    payload carry two elements and mean the rest of the turn."""
    return str(entry[2]) if len(entry) > 2 else SHIELD_END_OF_TURN

#: The **static** form, printed on the permanent the shield covers rather than
#: resolved onto one. Two subjects and one sentence: an Aura or Equipment names
#: what it is attached to (Gaseous Form, Demonic Torment) and a creature names
#: **itself** (Fog Bank). Not a marker at all in either case — it is read off
#: the text at the moment damage would be dealt, so the shield ends when the
#: Aura leaves or the creature does, with nothing having to clear it. The same
#: shape ``_source_type_shielded_by`` uses in ``static.py``, and its same two
#: readers: that pattern is likewise printed with "this" and with "enchanted".
#:
#: One pattern with the subject captured, and **two** readers over it rather
#: than one permissive matcher, for `prevent_all_from_source_type`'s reason
#: exactly: an Aura is itself a permanent, so a single reader would have
#: Gaseous Form shielding *itself* from combat damage — a card nobody printed.
#:
#: **The printed word "combat" is payload here too**, exactly as it is on the
#: marker form above. It was part of the pattern until Mercadian Masques, which
#: prints the same two sentences one word narrower — Inviolability ("Prevent all
#: damage that would be dealt to enchanted creature") beside Prismatic Ward's
#: shape and Muzzle beside Demonic Torment's — and the width has to reach
#: ``_shield_directions`` rather than be a second pattern, for the reason
#: ``add_directional_shield`` gives: a second matcher per width is a second
#: mechanism for a narrowing, and the wide one would then have to be remembered
#: everywhere the narrow one already is.
_STATIC_DAMAGE_SHIELD_RE = re.compile(
    r"^prevent all (?P<combat>combat )?damage that would be dealt "
    r"(?P<direction>to and dealt by|to|by) "
    r"(?P<subject>this|enchanted|equipped) (?:artifact )?creature$"
)


def _static_shield_match(line: str, card_name: str | None = None):
    """The static shield pattern against one printed line.

    *card_name* collapses CR 201.5's self-reference first: pre-modern and
    legendary templating write "Prevent all damage that would be dealt to
    **Cho-Manno**" where modern templating writes "this creature", and the
    pattern is anchored on the modern wording. The same rewrite
    ``self_reference._restriction_line`` makes for the combat-restriction table, at the
    one consult that needs it — a caller naming no card gets today's answer
    unchanged, which is what every reader asking about a *line* rather than a
    card wants.
    """
    normalized = " ".join((line or "").strip().lower().rstrip(".").split())
    if card_name:
        from ..self_reference import _collapse_self_references

        normalized = _collapse_self_references(
            normalized, card_name, "this creature"
        )
    return _STATIC_DAMAGE_SHIELD_RE.match(normalized)


def _shield_from_static_match(match) -> dict:
    printed = match.group("direction")
    return {
        "direction": (
            COMBAT_SHIELD_BOTH if printed == "to and dealt by" else printed
        ),
        "combat_only": bool(match.group("combat")),
    }


def attached_damage_shield(line: str, card_name: str | None = None) -> dict | None:
    """Which end of a damage event one printed **Aura** line shields, and how
    wide the shield is — ``{"direction", "combat_only"}`` — or None.

    One matcher, asked by the interceptor below and by ``engine/auras.py``'s
    support gate, so what is claimed and what is carried out are one rule.
    """
    match = _static_shield_match(line, card_name)
    if match is None or match.group("subject") == "this":
        return None
    return _shield_from_static_match(match)


def self_damage_shield(line: str, card_name: str | None = None) -> dict | None:
    """The same answer for the form a creature prints about **itself** (Fog
    Bank: "Prevent all combat damage that would be dealt to and dealt by this
    creature"; Cho-Manno, Revolutionary, by its own name).

    Exported for ``prevention_claims_line``, which is what admits a creature
    whose only ability is this one: the sentence has no duration and never
    resolves, so nothing in the compiled program can stand for it.
    """
    match = _static_shield_match(line, card_name)
    if match is None or match.group("subject") != "this":
        return None
    return _shield_from_static_match(match)


def _attached_damage_shields(perm) -> list[dict]:
    """Every static shield *perm* carries — from its own text and from each Aura
    or Equipment attached to it.

    Both readings answer here rather than at two call sites, because they are
    one question with two places the sentence can be printed: the same read
    ``_source_type_shielded_by`` makes of a damaged permanent's own text and of
    what is attached to it.

    **Every one of them, not the first.** This returned one answer and stopped
    at it, which was invisible while the pattern demanded the word "combat":
    the pool's static shields were Gaseous Form and Fog Bank, both already
    two-way, so a second one could add nothing. Mercadian Masques prints the two
    halves as separate Auras — Inviolability shields its host from damage and
    Muzzle shields everything *from* its host — and a creature carrying both is
    an ordinary board on which the first-match reading silently dropped one of
    them.

    The permanent's *effective* name goes with its effective text, which is what
    lets a self-referencing line survive a copy (CR 706.2: the copy's name is
    the copied one, so "dealt to Cho-Manno" still names the object it is on).
    """
    if not hasattr(perm, "metadata"):
        return []
    from ..aura_attachment import auras_attached_to

    found: list[dict] = []
    own = getattr(perm, "effective_card", None) or getattr(perm, "card", None)
    own_name = getattr(own, "name", None)
    for line in (getattr(own, "oracle_text", "") or "").splitlines():
        shield = self_damage_shield(line, own_name)
        if shield is not None:
            found.append(shield)
    for aura in auras_attached_to(perm):
        card = aura.effective_card
        for line in (card.oracle_text or "").splitlines():
            shield = attached_damage_shield(line, card.name)
            if shield is not None:
                found.append(shield)
    return found


def _shield_directions(perm, *, combat: bool) -> frozenset[str]:
    """Every direction *perm* is currently shielded in against an event of this
    width, from any of the three places a directional shield is recorded.

    *combat* is the event's own ``combat`` flag. Both forms record their width:
    the marker per entry, the static form per line — "…dealt by **enchanted
    creature**" (Muzzle) covers the creature's ping ability and Demonic
    Torment's "…**combat** damage…" does not, one printed word apart.

    Accepts None and non-permanent damage sources (a spell's
    ``CardDefinition``), which carry no shield at all.
    """
    # Not an early return on an empty ``metadata``, which is what it used to
    # be: the **static** form below is read off printed text and a creature
    # that has never been marked with anything carries an empty dict, so a
    # Fog Bank fresh on the battlefield answered "no shield at all".
    metadata = getattr(perm, "metadata", None) or {}
    directions: set[str] = set()
    for entry in metadata.get(_COMBAT_SHIELD_DIRECTION_KEY) or ():
        direction, combat_only = entry[0], entry[1]
        if combat_only and not combat:
            # "Prevent all **combat** damage …": a shield that ignored the word
            # would stop the creature's ping ability as well, which is a
            # strictly larger effect than the card prints.
            continue
        directions.add(str(direction))
    # Asked whatever the event's width, and narrowed by the line's own printed
    # word rather than by the caller's: this read used to sit behind ``if
    # combat:``, which was right only while the pattern demanded the word.
    for attached in _attached_damage_shields(perm):
        if combat or not attached["combat_only"]:
            directions.add(attached["direction"])
    return frozenset(directions)


def shields_damage(perm, *, dealt_to: bool, combat: bool) -> bool:
    """Whether *perm*'s shields cover an event it is on one end of.

    *dealt_to* says which end: True when *perm* is the recipient, False when it
    is the source. The two-way marker answers both; a one-way one answers only
    its own end, which is the whole point of carrying the direction.
    """
    directions = _shield_directions(perm, combat=combat)
    wanted = COMBAT_SHIELD_TO if dealt_to else COMBAT_SHIELD_BY
    return COMBAT_SHIELD_BOTH in directions or wanted in directions



# ---------------------------------------------------------------------------
# Reading the collection (CR 616.1's pure half)
# ---------------------------------------------------------------------------
#
# "Does this shield apply?" is separated from "apply it", because 616.1 has to
# know how many effects are in contention *before* any of them runs. The guard
# each shield used to open with *moved* here rather than being copied, so the
# shield body starts after the decision and the two cannot drift. Predicates are
# pure: none of them spends a charge, since a shield that is asked about may
# then not be chosen — ``Shield.would_prevent`` computes, ``Shield.spend``
# mutates, and only the second is reachable from an ``apply``.


def _source_matches(game, shield: Shield, source, seat: int | None = None) -> bool:
    """Whether *shield* answers damage from *source*.

    Two independent narrowings, both rechecked at damage time rather than
    locked in when the shield was armed (CR 615.9): the chosen source of
    CR 615.8, matched the way every other chosen-source effect in the engine
    matches one, and the source *property* a Circle of Protection names. A
    shield recording neither answers to any source.
    """
    if shield.source is not None:
        if game._match_chosen_damage_source([shield.source], source) is None:
            return False
    if shield.colors and not set(shield.colors) & set(
        damage_source_colors(game, source, seat=seat)
    ):
        return False
    if shield.source_type is not None and not source_has_type(
        game, source, shield.source_type
    ):
        return False
    if shield.source_filter is not None and not _source_in_subject(game, shield, source):
        return False
    return True


def _source_in_subject(game, shield: Shield, source) -> bool:
    """Whether *source* is one of the objects *shield*'s noun phrase names.

    Asked through ``subject_filters.subject_matches`` — the one answer every
    reader of a printed noun phrase uses — rather than field by field here, so
    a phrase the matcher cannot test is refused where the line is *compiled*
    instead of being quietly ignored at damage time.

    **A source that is not a permanent gets the one question a card can answer.**
    A spell reaches the damage paths as its printed ``CardDefinition``
    (CR 109.5), which has no battlefield, no controller and no layers — so every
    key in the vocabulary is unanswerable about it except ``named``, which is a
    characteristic of the card itself. "…would be dealt to this creature **by
    Torrent of Lava** this turn" names a spell and nothing else, and answering
    it "no" because the source is not a permanent would have made the shield
    Torrent of Lava grants prevent nothing at all. A phrase describing anything
    wider still declines, which is the safe direction: a shield is smaller than
    the card prints, never larger.
    """
    from ..search_filters import name_key
    from ..subject_filters import subject_matches

    described = dict(shield.source_filter or {})
    if source is None:
        return False
    if not hasattr(source, "metadata"):
        if set(described) != {"named"}:
            return False
        return name_key(getattr(source, "name", "") or "") == name_key(
            str(described["named"])
        )
    return subject_matches(
        game, source, described, observer=shield.filter_seat
    )


def _object_targets_recipient(game, recipient) -> bool:
    """Whether the spell or ability now resolving targets *recipient*.

    ``Game.resolving_targets`` is the seam ``_execute_oracle_instruction``
    pushes around every instruction, and it is the only place the answer lives:
    a spell reaches the damage paths as its printed ``CardDefinition``, which
    records nothing about what was chosen, and the stack object is popped before
    its instructions run.

    Spells **and** abilities, unlike ``static.py``'s ``_spell_targets_recipient``:
    Bronze Horse's static says "spells that target it", and this reads a card
    that says "a spell or ability", which is the same seam asked without the
    narrowing rather than a second mechanism. Combat damage is caused by no
    resolving object at all, so it is outside this by construction.
    """
    permanent_id = getattr(recipient, "permanent_id", None)
    if permanent_id is None:
        return False
    chosen = getattr(game, "resolving_targets", None) or ()
    return bool(chosen) and permanent_id in chosen[-1]


def _class_shields(game, recipient) -> list[Shield]:
    """The shields that watch *recipient* by a printed **noun phrase** rather
    than by hanging off it, oldest first.

    A shield normally lives on the recipient it protects, which is what makes it
    findable at all. "…would deal damage to you **and/or creatures you
    control**" (Shadowbane) names a phrase instead, and a phrase is not an
    object: the creatures it covers include ones that have not entered the
    battlefield yet, so there is nothing to hang it on and nothing to update
    when one arrives. So it lives on the seat it also protects, in the same
    collection, and is matched by asking the phrase about each damaged
    permanent.

    The exact twin of ``damage_redirects.class_redirects``, which the redirect
    side has had since Blood of the Martyr — and it keeps the sweeps and the
    lifetimes as they were, because the cleanup step already clears every
    player's shields.

    Only a permanent can be watched this way. The player half of the phrase is
    the seat the shield already hangs off, so asking a ``PlayerState`` here
    would find the same shield twice.
    """
    if not hasattr(recipient, "metadata"):
        return []
    from ..subject_filters import subject_matches

    found: list[Shield] = []
    for player in game.players:
        for shield in shields_on(player):
            if shield.recipients is None:
                continue
            if subject_matches(
                game, recipient, dict(shield.recipients),
                observer=shield.filter_seat,
            ):
                found.append(shield)
    return found


def _resolving_object_shields(game) -> list[Shield]:
    """The shields hanging off the stack object whose instructions are running.

    Hidden Retreat — "Prevent all damage that would be dealt by target instant
    or sorcery spell this turn" — shields no recipient at all: it stops whatever
    that *one spell* would deal, to anyone. So its shield hangs off the spell,
    which is the same rule every other one follows (it lives on the object it
    watches), and it is reached through ``Game.resolving_items`` rather than by
    matching the damage's source.

    **That is the only way a spell can be recognised.** A spell's damage source
    is its printed ``CardDefinition`` (CR 109.5) — one object per *card*, handed
    out once per copy by the deck builder — so a shield matching on the source
    would silence a second copy too, on a card that named one. A ``StackItem``
    is one object per cast, and this seam is where it is knowable.

    The exact twin of ``damage_redirects.resolving_object_redirects``, down to
    being empty while a resolution waits on a prompt: damage dealt after a
    CR 616.1e question was asked mid-resolution is outside this. The direction is
    the safe one — the damage lands as it would have without the shield — and it
    is stated rather than hidden.
    """
    items = getattr(game, "resolving_items", None) or ()
    return list(shields_on(items[-1])) if items else []


def _live(game, event: dict, kind: str, *, chosen: bool | None = None):
    """Shields of *kind* on the event's recipient that could modify this event.

    *chosen* selects one half of the order space: True for shields naming a
    source, False for the "any source" fallback an AI or headless activation
    arms. They are separate registrations because they take separate default
    orders, and CR 616.1e's default is rules-visible.
    """
    recipient = event["recipient"]
    amount = event["amount"]
    # The recipient's own collection, plus — when the recipient is a permanent
    # — the class-scoped shields sitting on a *seat* whose printed phrase names
    # it. A team shield covers its holder as well as the phrase ("**you** and/or
    # creatures you control"), so it is not excluded from the holder's own list;
    # and a permanent is never in that list, so nothing is counted twice.
    for shield in (
        # A shield that spares its holder (Sivvi's Ruse's "to creatures you
        # control") hangs off a seat without covering it, so the seat's own
        # list does not count it; ``_class_shields`` is how it is reached.
        [s for s in shields_on(recipient) if not s.spares_holder]
        + _class_shields(game, recipient)
        # …and the shields on the stack object currently resolving, which watch
        # no recipient at all (Hidden Retreat). Every recipient it damages finds
        # the same one shield, which is what "prevent **all** damage that would
        # be dealt by that spell" means.
        + _resolving_object_shields(game)
        # …and the shields that watch no recipient and outlive their resolution
        # (Penance). The third and last way a shield can be reached from an
        # event, beside "it hangs on the recipient" and "its phrase names the
        # recipient".
        + _table_shields(game)
    ):
        if shield.kind != kind or shield.spent:
            continue
        if shield.combat_only and not event.get("combat"):
            # "Prevent all **combat** damage …" (Snag): the event's own flag,
            # which no property of the source can stand in for.
            continue
        if chosen is not None and (shield.source is not None) != chosen:
            continue
        if not _source_matches(
            game, shield, event.get("source"), event.get("source_seat")
        ):
            continue
        if shield.targets_recipient and not _object_targets_recipient(game, recipient):
            # Checked here rather than in `_source_matches`, and the difference
            # is real: this is not a property of the source but a relation
            # between the *resolving object* and the recipient, and only the
            # event knows who the recipient is.
            continue
        if shield.would_prevent(amount) <= 0:
            continue
        yield shield


def _table_shields(game) -> list[Shield]:
    """The shields that watch **no recipient at all** and outlive the resolution
    that armed them, oldest seat first.

    "The next time a black or red source of your choice would deal damage this
    turn, prevent that damage." (Penance.) CR 615.8 defines this shield by the
    source alone — the rule's own words have no recipient in them — so it stops
    that source's next damage whoever it was headed for, a player or a
    permanent alike.

    The shield still *lives* on the seat that armed it, which is where the
    cleanup sweep can find it to expire; what this function supplies is the
    other half, the reach. That is the same split ``_class_shields`` above makes
    for Shadowbane and ``_resolving_object_shields`` below makes for Hidden
    Retreat — the difference between them is only what a shield with no
    recipient of its own hangs off, and Penance's has to be a seat because it
    outlives the stack object.
    """
    found: list[Shield] = []
    for player in game.players:
        found.extend(
            shield for shield in shields_on(player) if shield.any_recipient
        )
    return found


def _arms(kind: str, *, chosen: bool | None = None, player_only: bool = False) -> Applicability:
    """The applicability predicate for a shield of *kind*: is one armed that
    would remove at least a point from this event?

    "Would remove a point" rather than merely "is armed" is the deliberate
    reading, and it is the one place this differs from Aladdin's Lamp — see
    ``_forcefield_chosen_attacker``, which is the shield it could bite.

    *player_only* is a fact about the shields a kind's pool holds, not about the
    kind: every Circle of Protection prints "to you", so a colour shield reached
    from a permanent was a shield that could not exist. Penance is that kind's
    first printing with no recipient (CR 615.8), and it is reached from a
    damaged *creature* as readily as from a player — so the gate asks the
    shields rather than refusing outright, and every recipient-bound shield of
    the kind stays exactly as restricted as it was.
    """

    def applies(game, event: dict) -> bool:
        if player_only and not isinstance(event["recipient"], PlayerState):
            return any(
                shield.any_recipient
                for shield in _live(game, event, kind, chosen=chosen)
            )
        return next(_live(game, event, kind, chosen=chosen), None) is not None

    return applies


def _spend(game, event: dict, kind: str, *, chosen: bool | None = None, rider=None):
    """Apply the recipient's shields of *kind* to this event.

    Draining every matching shield rather than one is what keeps CR 615.7's
    "such effects count only the amount of damage" true when a recipient holds
    two numeric pools: the pair behaves as the single total the old integer
    field held. A whole-instance shield takes the event to 0 on its first
    application and the loop stops there, so exactly one is consumed.

    *rider* is CR 615.5's "additional effect, which may refer to the amount of
    damage that was prevented" — run after the prevention, with the shields that
    did it, never before.
    """
    remaining = event["amount"]
    prevented = 0
    used: list[Shield] = []
    for shield in list(_live(game, event, kind, chosen=chosen)):
        take = shield.would_prevent(remaining)
        if take <= 0:
            continue
        shield.spend(take)
        used.append(shield)
        prevented += take
        remaining -= take
        if remaining <= 0:
            break
    drop_spent(event["recipient"])
    if rider is not None and prevented > 0:
        rider(game, event, used, prevented)
    return PreventionOutcome(prevented=prevented)


def _applies_all_combat(game, event: dict) -> bool:
    return bool(event.get("combat")) and game.combat_damage_prevented_until_eot


def _applies_scoped_combat(game, event: dict) -> bool:
    """Whether an armed "…to <noun phrase>" prevention covers this event.

    The noun phrase is matched **now**, not when the effect resolved (CR 611.2c
    fixes a set only where the effect says so, and "Dogs you control" does not):
    a Dog that entered after Pack Leader attacked is still a Dog its controller
    controls when the damage would be dealt.
    """
    if not event.get("combat"):
        return False
    recipient = event.get("recipient")
    if recipient is None or not hasattr(recipient, "card"):
        # A player is not a "Dog you control". Only permanents are scoped.
        return False
    from ..subject_filters import subject_matches

    for entry in getattr(game, "combat_damage_prevented_for", ()) or ():
        seat = entry.get("seat")
        if subject_matches(game, recipient, entry.get("filter") or {}, observer=seat):
            return True
    return False


def _applies_all_combat_except(game, event: dict) -> bool:
    """Undergrowth with its cost paid: every combat damage event **but** the
    ones whose source the printed noun phrase names.

    The source is re-matched at the moment damage would be dealt rather than
    captured when the spell resolved, exactly as ``_applies_scoped_combat``
    re-matches its recipients: a creature that turned red since, or entered
    since, is one the sentence exempts.

    A source that is not a permanent — a spell, an ability — cannot be matched
    and is therefore not exempt, which is the right way round: this is a
    *combat* damage shield, and combat damage is only ever dealt by a permanent.
    """
    if not event.get("combat"):
        return False
    records = getattr(game, "combat_damage_prevented_except_from", ()) or ()
    if not records:
        return False
    from ..subject_filters import subject_matches
    from ..models import Permanent

    source = event.get("source")
    for entry in records:
        if isinstance(source, Permanent) and subject_matches(
            game, source, entry.get("filter") or {}, observer=entry.get("seat"),
        ):
            continue  # the sentence lets this source's damage through
        return True
    return False


def _applies_combat_to_and_by(game, event: dict) -> bool:
    """Whether either end of this damage event is shielded.

    Each end is asked with the direction it is on, so a "dealt **by**" shield
    stops the shielded creature's own damage without also stopping damage dealt
    *to* it — which is the difference between Gaseous Form and Demonic Torment,
    printed one word apart. The event's own width is passed down rather than
    checked here, because a shield that names no "combat" covers a ping as well
    (Kry Shield) and one that names it covers only combat.
    """
    combat = bool(event.get("combat"))
    return shields_damage(event["recipient"], dealt_to=True, combat=combat) or shields_damage(
        event.get("source"), dealt_to=False, combat=combat
    )


# ---------------------------------------------------------------------------
# Shields
# ---------------------------------------------------------------------------
#
# Protection comes first and is the extreme case of the pattern the next few
# share: it holds no charge at all, because it is a static ability of the
# damaged object rather than something armed onto it.
#
# The two combat blankets after it are turn-wide flags rather than shields a
# recipient holds, which is why they read a game flag and a permanent's marker
# instead of the collection: nothing is consumed, so there is no charge, no
# lifetime and no remaining-uses bookkeeping for a Shield to carry. The
# directional one also has to be readable off the damage's *source* ("dealt to
# and dealt by"), which a recipient-keyed collection cannot express.

def _applies_protection(game, event: dict) -> bool:
    """CR 702.16e: is the recipient protected from a quality this source has?

    **The one place the damage half of protection is asked**, and it took the
    engine until now to have one. It used to be four early returns inside the
    combat damage step and a fifth inside the player-damage path, each of which
    skipped the damage event entirely rather than preventing it — so a White
    Knight took its point from a Pestilence, a Subterranean Spirit swept itself
    with its own red ability, and both had done so for the life of this engine.
    ``deal_damage`` is the seam every damage path goes through (CR 120.4), and
    this is the rule read there instead.

    Prevention rather than a skip, because that is the rule's own word: "Any
    damage that would be dealt … **is prevented**". Two consequences fall out
    of taking it literally and both are correct. Damage that *can't* be
    prevented (Whippoorwill's marker, Lava Burst's rider) beats protection,
    because ``damage_candidates`` drops every ``prevents_or_redirects``
    contender and every entry in this package is one. And protection joins
    CR 616.1's contention set, so a recipient holding a second applicable
    shield is asked which applies first — the answer cannot change the damage,
    since protection takes the whole instance either way, but which shield is
    *spent* is the affected player's choice and the rules give it to them.

    Both kinds of recipient, because CR 702.16e says "a permanent **or
    player**". A permanent answers through ``_protection_qualities``; a player
    can only have this pool's one printing of player protection (Runed Halo,
    CR 702.16i, a card *name* rather than a quality), which
    ``engine/named_protection.py`` derives. Two derivations because the two
    bearers genuinely have nothing in common — one reads a permanent's layers,
    the other scans a seat's board for a chosen name — but one place they are
    *asked*, which is what was missing.
    """
    source = event.get("source")
    if source is None:
        return False
    recipient = event["recipient"]
    if isinstance(recipient, PlayerState):
        from ..named_protection import protected_from

        seat = affected_seat(game, recipient)
        return seat is not None and protected_from(game, seat, source)
    if not hasattr(recipient, "metadata"):
        return False
    return game._is_protected_from(
        recipient, source, as_damage_source=True,
        seat=event.get("source_seat"),
    )


@prevention_effect(PROTECTION, applies=_applies_protection)
def _protection_prevents_damage(game, event: dict) -> PreventionOutcome | None:
    """Protection: "Any damage that would be dealt by sources that have the
    stated quality to a permanent or player with protection is prevented."
    (CR 702.16e.)

    The whole instance, and nothing is consumed — protection is a static
    ability, so the next point from the same source is prevented too.
    """
    game.log.append(
        f"{recipient_label(event['recipient'])} has protection from "
        f"{_source_label(event.get('source'))}"
    )
    return PreventionOutcome(prevented=event["amount"])


def _source_label(source) -> str:
    """A damage source's name for the log, whichever of CR 109.5's two shapes it
    is — ``recipient_label``'s twin at the other end of the event."""
    card = getattr(source, "effective_card", None) or getattr(source, "card", source)
    return getattr(card, "name", None) or "that source"


@prevention_effect(COMBAT_BLANKET, applies=_applies_all_combat)
def _prevent_all_combat_damage(game, event: dict) -> PreventionOutcome | None:
    """Fog / Holy Day: "Prevent all combat damage that would be dealt this
    turn." A turn-wide flag rather than a shield, so it is never used up — and
    it applies only to combat damage, leaving spell and ability damage alone."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_BLANKET_SCOPED, applies=_applies_scoped_combat)
def _prevent_scoped_combat_damage(game, event: dict) -> PreventionOutcome | None:
    """Pack Leader: "Prevent all combat damage that would be dealt this turn to
    Dogs you control." A turn-wide record like the blanket above rather than a
    shield each Dog holds, so it is never used up and it covers Dogs that were
    not on the battlefield when it resolved."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_BLANKET_EXCEPT, applies=_applies_all_combat_except)
def _prevent_all_combat_damage_except_from(game, event: dict) -> PreventionOutcome | None:
    """Undergrowth, cost paid: "Prevent all combat damage that would be dealt
    this turn… this effect doesn't affect combat damage that would be dealt by
    red creatures."

    The blanket above with a hole in it. A turn-wide record rather than a shield
    for that one's reason — nothing is used up — and the hole is described by
    the source, so it covers a creature that becomes red after this resolves and
    exempts one that stops being red."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(COMBAT_SHIELD, applies=_applies_combat_to_and_by)
def _prevent_combat_damage_to_and_by(game, event: dict) -> PreventionOutcome | None:
    """Ebony Horse, Maze of Ith: "Prevent all combat damage that would be dealt
    to and dealt by that creature this turn." Both directions are one check here
    — the shielded creature may be either end of the event."""
    return PreventionOutcome(prevented=event["amount"])


@prevention_effect(SOURCE_CAP, applies=_arms(PREVENT_ALL_BUT, chosen=True))
def _forcefield_chosen_attacker(game, event: dict) -> PreventionOutcome | None:
    """Forcefield: "The next time an unblocked creature of your choice would
    deal combat damage to you this turn, prevent all but 1 of that damage."
    The chosen attacker is consumed by the damage it caps.

    A shield that would prevent nothing does not apply, so a chosen attacker
    dealing exactly 1 leaves it armed. That is the one place this pool's shields
    could have taken Aladdin's Lamp's shape instead — a charge spent even when
    it does nothing (CR 614.1) — and CR 615.8 arguably says they should. It is
    left as it was rather than changed under cover of a refactor; see
    ROADMAP.md's phase 5 entry."""
    return _spend(game, event, PREVENT_ALL_BUT, chosen=True)


@prevention_effect(GENERIC_CAP, applies=_arms(PREVENT_ALL_BUT, chosen=False))
def _forcefield_generic(game, event: dict) -> PreventionOutcome | None:
    """Forcefield activated without recording a chosen attacker (AI / headless):
    the next damage event from any source is capped to 1."""
    return _spend(game, event, PREVENT_ALL_BUT, chosen=False)


def _gain_prevented_life(game, event: dict, used: list[Shield], prevented: int) -> None:
    # CR 615.5: the prevention happens first, then the rest of the effect —
    # here a life gain referring to the amount prevented.
    recipient = event["recipient"]
    game.log.append(f"Reverse Damage prevented {prevented} damage to {recipient.name}")
    game._gain_life(recipient, prevented, source_name="Reverse Damage")


@prevention_effect(SOURCE_HALF, applies=_arms(PREVENT_HALF, chosen=True, player_only=True))
def _half_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Dark Sphere: "The next time a source of your choice would deal damage to
    you this turn, prevent half that damage, rounded down."

    Half of *this* event, computed by the shield when the event exists — see
    ``Shield.would_prevent``. A 1-damage event therefore prevents nothing and
    leaves the shield armed, the same reading ``_forcefield_chosen_attacker``
    takes of the same situation and for the same reason.
    """
    return _spend(game, event, PREVENT_HALF, chosen=True)


@prevention_effect(GENERIC_HALF, applies=_arms(PREVENT_HALF, chosen=False, player_only=True))
def _half_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """Dark Sphere sacrificed without recording a chosen source (AI / headless):
    the next damage event from any source is halved."""
    return _spend(game, event, PREVENT_HALF, chosen=False)


@prevention_effect(
    SOURCE_SHIELD, applies=_arms(PREVENT_AND_GAIN_LIFE, chosen=True, player_only=True)
)
def _reverse_damage_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage: "The next time a source of your choice would deal damage
    to you this turn, prevent that damage. You gain life equal to the damage
    prevented this way." The whole instance is prevented regardless of its size
    (CR 615.8)."""
    return _spend(game, event, PREVENT_AND_GAIN_LIFE, chosen=True, rider=_gain_prevented_life)


@prevention_effect(
    GENERIC_SHIELD, applies=_arms(PREVENT_AND_GAIN_LIFE, chosen=False, player_only=True)
)
def _reverse_damage_generic(game, event: dict) -> PreventionOutcome | None:
    """Reverse Damage cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and gained as life."""
    return _spend(game, event, PREVENT_AND_GAIN_LIFE, chosen=False, rider=_gain_prevented_life)


def _exile_for_prevented(game, event: dict, used: list[Shield], prevented: int) -> None:
    """Bone Mask's rider (CR 615.5): the prevention happens first, then cards
    equal to what it absorbed leave the top of the shielded player's library.

    The recipient's own library, because "your library" is the shield holder's
    and this shield only ever sits on a player (``player_only`` below). An empty
    library exiles what is there and no more — running out is not a loss until
    a draw is attempted (CR 104.3c), and this is not a draw.
    """
    recipient = event["recipient"]
    taken = min(prevented, len(recipient.library))
    exiled = [recipient.library.pop(0) for _ in range(taken)]
    recipient.exile.extend(exiled)
    game.log.append(
        f"{used[0].source_name or 'A shield'} prevented {prevented} damage to "
        f"{recipient.name}"
        + (
            ", exiling " + ", ".join(card.name for card in exiled)
            if exiled else ", with no cards left to exile"
        )
    )


@prevention_effect(
    SOURCE_EXILE_SHIELD, applies=_arms(PREVENT_AND_EXILE, chosen=True, player_only=True)
)
def _exile_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Bone Mask: the whole instance from the chosen source, and then the
    library pays for it."""
    return _spend(game, event, PREVENT_AND_EXILE, chosen=True, rider=_exile_for_prevented)


@prevention_effect(
    GENERIC_EXILE_SHIELD,
    applies=_arms(PREVENT_AND_EXILE, chosen=False, player_only=True),
)
def _exile_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """The same shield armed without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and paid for."""
    return _spend(game, event, PREVENT_AND_EXILE, chosen=False, rider=_exile_for_prevented)


def _gain_life_if_rider_colour(
    game, event: dict, used: list[Shield], prevented: int
) -> None:
    """Shadowbane's rider (CR 615.5): the prevention happens first, then the
    life gain — but only when the source was one of the colours the shield
    recorded.

    The colour is rechecked against the source *now* rather than when the shield
    was armed (CR 615.9's reading, applied to the rider's own condition): a
    source that has changed colour since is tested by what it is now.

    The life goes to the shield's holder, not to the damage's recipient: "you
    gain that much life" is the caster's sentence and the recipient may be one
    of their creatures.
    """
    shield = used[0]
    holder = (
        game.players[shield.filter_seat]
        if shield.filter_seat is not None
        and 0 <= shield.filter_seat < len(game.players)
        else event["recipient"]
    )
    recipient = event["recipient"]
    game.log.append(
        f"{shield.source_name or 'A shield'} prevented {prevented} damage to "
        f"{getattr(recipient, 'name', None) or recipient.card.name}"
    )
    if not shield.rider_colors:
        game._gain_life(holder, prevented, source_name=shield.source_name)
        return
    if set(shield.rider_colors) & set(
        damage_source_colors(game, event.get("source"), seat=event.get("source_seat"))
    ):
        game._gain_life(holder, prevented, source_name=shield.source_name)


@prevention_effect(
    SOURCE_TEAM_SHIELD, applies=_arms(PREVENT_TEAM, chosen=True)
)
def _team_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Shadowbane: the whole instance from the chosen source, wherever on this
    player's side it was headed."""
    return _spend(
        game, event, PREVENT_TEAM, chosen=True, rider=_gain_life_if_rider_colour
    )


@prevention_effect(
    GENERIC_TEAM_SHIELD, applies=_arms(PREVENT_TEAM, chosen=False)
)
def _team_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """The same shield cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented."""
    return _spend(
        game, event, PREVENT_TEAM, chosen=False, rider=_gain_life_if_rider_colour
    )


def _damage_the_source_controller(
    game, event: dict, used: list[Shield], prevented: int
) -> None:
    """Honorable Passage's rider (CR 615.5): the prevention happens first, then
    the damage comes back — but only when the source was one of the colours the
    shield recorded.

    Three things are read *now* rather than at the arming, and each is a rule
    rather than a convenience:

    * the colour, because CR 615.9's recheck is against the source as it is when
      the damage would be dealt (the same reading ``_gain_life_if_rider_colour``
      takes one rider over);
    * how much, because "that much" is what this shield absorbed and no arming
      knows it;
    * **whose** source it was — ``source_seat``, derived once inside
      ``deal_damage`` for CR 109.5's reason: a spell's ``source`` is the card as
      printed, shared by every copy and controlled by nobody, so no read of it
      can answer.

    The damage is dealt by the *card that armed the shield*, not by the
    prevented source: "Honorable Passage deals that much damage" names itself.
    ``source_name`` is the only handle the shield keeps on it, so the shield's
    own recorded name is what a later reader sees on the log line.
    """
    shield = used[0]
    game.log.append(
        f"{shield.source_name or 'A shield'} prevented {prevented} damage to "
        f"{recipient_label(event['recipient'])}"
    )
    if prevented <= 0:
        return
    if shield.rider_colors and not (
        set(shield.rider_colors)
        & set(damage_source_colors(
            game, event.get("source"), seat=event.get("source_seat")
        ))
    ):
        return
    seat = event.get("source_seat")
    if seat is None or not (0 <= seat < len(game.players)):
        # CR 109.5 has no answer for a source nobody controls (a turn-based
        # action), and the card names one. Nothing happens rather than the
        # damage landing on a guessed seat.
        return
    controller = game.players[seat]
    if getattr(controller, "lost", False):
        return
    game._deal_damage_to_player(
        controller, prevented, source=shield.source_name, asks=True,
        then=lambda dealt, name=shield.source_name, who=controller: game.log.append(
            f"{name or 'A shield'} dealt {dealt} damage to {who.name}"
        ),
    )


@prevention_effect(
    SOURCE_REFLECT_SHIELD, applies=_arms(PREVENT_AND_DAMAGE_SOURCE, chosen=True)
)
def _reflect_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Honorable Passage: the whole instance from the chosen source, wherever
    on the table it was headed."""
    return _spend(
        game, event, PREVENT_AND_DAMAGE_SOURCE, chosen=True,
        rider=_damage_the_source_controller,
    )


@prevention_effect(
    GENERIC_REFLECT_SHIELD, applies=_arms(PREVENT_AND_DAMAGE_SOURCE, chosen=False)
)
def _reflect_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """The same shield cast without recording a chosen source (AI / headless):
    the next damage event from any source is prevented and answered."""
    return _spend(
        game, event, PREVENT_AND_DAMAGE_SOURCE, chosen=False,
        rider=_damage_the_source_controller,
    )


def _log_whole_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    game.log.append(
        f"{used[0].source_name or 'A shield'} prevented {prevented} damage to "
        f"{recipient_label(event['recipient'])}"
    )


def recipient_label(recipient) -> str:
    """A damage recipient's name, whichever of CR 615.1's two kinds it is.

    A ``PlayerState`` has a ``name`` and a ``Permanent`` has a card that does.
    Every log line here read the player half until Circle of Despair armed a
    whole-instance shield on a creature, which is not a case a log line should
    ever have been able to decide.
    """
    return getattr(recipient, "name", None) or recipient.card.name


@prevention_effect(SOURCE_WHOLE, applies=_arms(PREVENT_WHOLE, chosen=True))
def _whole_prevention_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Pentagram of the Ages: "The next time a source of your choice would deal
    damage to you this turn, prevent that damage."

    CR 615.8's plain sentence, and the whole instance regardless of its size —
    the same absorption ``_reverse_damage_chosen_source`` performs, without the
    life gain that one's card prints after it.
    """
    return _spend(game, event, PREVENT_WHOLE, chosen=True, rider=_log_whole_prevention)


# ``player_only`` is gone from both of these, and it was never the rule: CR
# 615.1 puts a shield around "a player or a permanent", and every card that
# armed one of these happened to protect a player until Circle of Despair
# printed "…would deal damage to **any target**". A flag that says which cards
# exist rather than which the rule allows is one this engine removes when a card
# disagrees with it.
@prevention_effect(GENERIC_WHOLE, applies=_arms(PREVENT_WHOLE, chosen=False))
def _whole_prevention_generic(game, event: dict) -> PreventionOutcome | None:
    """The same shield activated without recording a chosen source (AI /
    headless): the next damage event from any source is prevented."""
    return _spend(game, event, PREVENT_WHOLE, chosen=False, rider=_log_whole_prevention)


def _chosen_source_blanket_rider(
    game, event: dict, used: list[Shield], prevented: int
) -> None:
    """What a chosen-source blanket does after it absorbs (CR 615.5).

    Always the log line; and for Samite Ministration, "whenever damage from a
    black or red source is prevented this way this turn, you gain that much
    life" — once per prevention event, which is what "whenever" asks of a
    shield that outlives its first use.

    The colour is rechecked against the source as it is *now* and as a source
    of damage (CR 609.7b), through the one reader every colour question about
    damage asks — so a source a Lace turned red since the shield was armed
    pays, and one Ghostly Flame has made colorless does not.

    No rider colours means no rider at all, unlike ``_gain_life_if_rider_colour``
    beside this, where the empty tuple is Reverse Damage's unconditional gain:
    nothing prints an unconditional gain on the blanket, and reading the empty
    tuple that way would have Protective Sphere gaining life.
    """
    shield = used[0]
    recipient = event["recipient"]
    game.log.append(
        f"{shield.source_name or 'A shield'} prevented {prevented} damage to "
        f"{recipient_label(recipient)} from {_source_label(event.get('source'))}"
    )
    if not shield.rider_colors:
        return
    if not set(shield.rider_colors) & set(
        damage_source_colors(game, event.get("source"), seat=event.get("source_seat"))
    ):
        return
    holder = (
        game.players[shield.filter_seat]
        if shield.filter_seat is not None
        and 0 <= shield.filter_seat < len(game.players)
        else recipient
    )
    if isinstance(holder, PlayerState):
        game._gain_life(holder, prevented, source_name=shield.source_name)


@prevention_effect(
    CHOSEN_SOURCE_BLANKET, applies=_arms(PREVENT_ALL_FROM_CHOSEN_SOURCE)
)
def _prevent_all_from_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Samite Ministration: "Prevent all damage that would be dealt to you this
    turn by a source of your choice."

    Every instance the chosen source would deal to the shield's holder until
    the cleanup sweep, combat or not. ``_live`` is what holds it to that
    source and — for Protective Sphere — to a source that still shares a
    colour with the mana that paid for it (CR 609.7b: the property is
    rechecked when the damage would be dealt, and a shield whose property
    fails is not used up, because this one never is).
    """
    return _spend(
        game, event, PREVENT_ALL_FROM_CHOSEN_SOURCE,
        rider=_chosen_source_blanket_rider,
    )


def _log_color_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    # Through ``recipient_label``, which exists for exactly the reason this line
    # needed it: every Circle prints "to you", so this read ``.name`` off a
    # PlayerState and could not have been wrong until Penance armed the same
    # kind with no recipient at all and a **creature** was the one damaged. That
    # is the widened-gate class — a reader keyed on the classification the gate
    # used to guarantee — and here it raised rather than lying, which is the
    # good half of it.
    game.log.append(
        f"Circle of Protection prevented {prevented} damage to "
        f"{recipient_label(event['recipient'])} from a "
        + ("/".join(used[0].colors) or str(used[0].source_type or "chosen"))
        + " source"
    )


@prevention_effect(COLOR_SHIELD, applies=_arms(PREVENT_FROM_COLOR, player_only=True))
def _circle_of_protection(game, event: dict) -> PreventionOutcome | None:
    """Circle of Protection: "The next time a <color> source of your choice
    would deal damage to you this turn, prevent that damage." One shield per
    activation, matched against the source's colors at damage time (CR 615.9)
    and prevented in full."""
    return _spend(game, event, PREVENT_FROM_COLOR, rider=_log_color_prevention)


def _log_subject_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    # ``recipient_label``: Sivvi's Ruse's blanket shields *creatures*, and a
    # ``Permanent`` has no ``name`` of its own.
    game.log.append(
        f"{used[0].source_name or 'A shield'} prevented {prevented} damage to "
        f"{recipient_label(event['recipient'])}"
    )


@prevention_effect(SUBJECT_BLANKET, applies=_arms(PREVENT_FROM_SUBJECT))
def _prevent_from_subject(game, event: dict) -> PreventionOutcome | None:
    """Al-abara's Carpet: "Prevent all damage that would be dealt to you this
    turn by attacking creatures without flying."

    A blanket rather than a charge: the shield holds neither points nor uses, so
    every matching source this turn is prevented in full and the sweep is what
    ends it. Which sources match is the printed noun phrase, rechecked against
    each one when the damage would be dealt (CR 615.9) — a creature that has
    since gained flying, or has left combat, is no longer described by it.
    """
    return _spend(game, event, PREVENT_FROM_SUBJECT, rider=_log_subject_prevention)


@prevention_effect(
    TARGETING_BLANKET, applies=_arms(PREVENT_FROM_TARGETING_SOURCE)
)
def _prevent_from_targeting_source(game, event: dict) -> PreventionOutcome | None:
    """Silhouette: "If a spell or ability that targets that creature would cause
    a source to deal damage to that creature this turn, prevent that damage."

    A blanket, so every qualifying event this turn is prevented in full and the
    cleanup sweep is what ends it. What qualifies is rechecked when the damage
    would be dealt (CR 615.9) — a burn spell aimed elsewhere that splashes onto
    this creature is not "a spell that targets that creature", and combat damage
    never is.
    """
    return _spend(game, event, PREVENT_FROM_TARGETING_SOURCE)


@prevention_effect(SPELL_BLANKET, applies=_arms(PREVENT_BY_RESOLVING_OBJECT))
def _prevent_by_resolving_object(game, event: dict) -> PreventionOutcome | None:
    """Hidden Retreat: "Prevent all damage that would be dealt by target instant
    or sorcery spell this turn."

    A blanket, so every event that spell deals is prevented in full and the
    cleanup sweep is what ends it. Which spell is asked by the seam the shield
    was found through — ``_resolving_object_shields`` — and *what* it answers to
    is the spell's own card, so a sorcery that has a creature deal the damage
    leaves that creature's damage alone.
    """
    return _spend(game, event, PREVENT_BY_RESOLVING_OBJECT)


def _log_pool_prevention(game, event: dict, used: list[Shield], prevented: int) -> None:
    recipient = event["recipient"]
    if not isinstance(recipient, PlayerState):
        game.log.append(f"Prevented {prevented} damage to {recipient.card.name}")


@prevention_effect(
    POOL_WITH_COUNTERS, applies=_arms(PREVENT_NEXT_N_AND_COUNTERS)
)
def _prevention_pool_with_counters(game, event: dict) -> PreventionOutcome | None:
    """Temper: "Prevent the next X damage that would be dealt to target creature
    this turn. For each 1 damage prevented this way, put a +1/+1 counter on that
    creature."

    CR 615.7's pool with CR 615.5's additional effect: "the prevention takes
    place at the time the original event would have happened; the rest of the
    effect takes place immediately afterward". So the counters go on **here**,
    inside the damage event, and not when the spell resolved — at resolution the
    pool has absorbed nothing, and a placement read there would put down zero
    counters for ever. That is the whole difference between this card and Sacred
    Boon, which prints the same clause behind a delay and really is a delayed
    ability reading the shield at the end step.

    The number is each shield's own increase rather than the event's total,
    which is why the running totals are read before ``_spend`` and again in the
    rider. Two of these pools on one creature absorb one event between them
    (CR 615.7's "such effects count only the amount of damage"), and each places
    counters for what *it* absorbed — a card printing a different counter kind
    would otherwise place the wrong one for the other's points.
    """
    before = {
        id(shield): shield.prevented
        for shield in _live(game, event, PREVENT_NEXT_N_AND_COUNTERS)
    }

    def place(game, event: dict, used: list[Shield], prevented: int) -> None:
        recipient = event["recipient"]
        if not hasattr(recipient, "permanent_id"):
            # The lowering only admits this rider on a shield announced over a
            # creature, so this is unreachable from the pool — and a counter on
            # a player is not a counter this engine has.
            return
        for shield in used:
            placed = game.place_pt_counters(
                recipient, shield.counter,
                shield.prevented - before.get(id(shield), 0),
            )
            if placed:
                game.log.append(
                    f"{shield.source_name or 'A shield'}: "
                    f"{recipient.card.name} gets {placed} {shield.counter} "
                    f"counter{'s' if placed != 1 else ''}"
                )

    return _spend(game, event, PREVENT_NEXT_N_AND_COUNTERS, rider=place)


@prevention_effect(POOL, applies=_arms(PREVENT_NEXT_N))
def _prevention_pool(game, event: dict) -> PreventionOutcome | None:
    """"Prevent the next N damage that would be dealt to <recipient> this turn"
    (Healing Salve's prevention mode, Samite Healer, Rock Hydra, …). Each point
    prevented reduces the shield by 1; the remainder is dealt normally
    (CR 615.7). The one shield that protects creatures as well as players."""
    return _spend(game, event, PREVENT_NEXT_N, rider=_log_pool_prevention)

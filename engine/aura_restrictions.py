"""What an attached Aura forbids its host, and its host's controller.

Not characteristics, so CR 613's layers do not apply to them: they change how
the game is played, meaning what may attack or block (CR 506, 508.1, 509.1),
what untaps (CR 502.3), what may be enchanted (CR 303.4) and what the
controller may cast. The ownership principle is still the one the layers gave
P/T and keywords. A reader asks whether any attached Aura imposes the
restriction right now (``aura_restriction_active``,
``attached_combat_restrictions``, ``attached_block_ceiling``,
``controller_cast_ban``), derived from the Aura's own text on every read,
instead of the Aura stamping a flag that something has to remember to take
off. The CR 116.2d offer that buys a turn off one ("…sacrifice a permanent of
their choice … to ignore this effect until end of turn") is here with the
record it writes, because these readers are the ones that consult it.

Split out of ``engine/auras.py`` at the 2,000-line cap. The support gate there
(``aura_continuous_claim``) claims each of these lines through the reader here
that enforces it.
"""

from __future__ import annotations

import re

from .aura_attachment import auras_attached_to
from .aura_vocabulary import (
    _NOUN,
    _ATTACHED,
    _COLORS,
    _LazyPattern,
    _line_text,
    _keyword_alternation,
)


#: The restriction names an Aura is currently *not* imposing, because the
#: permanent it is attached to bought a turn off them (CR 116.2d). Recorded on
#: the Aura and cleared by the cleanup step, like every other "until end of
#: turn" record in this engine — nothing is undone, the record simply stops
#: being there.
#:
#: The **names** rather than a flag on the Aura, because the printed offer says
#: "ignore **this effect**" and names one sentence: an Aura whose second
#: restriction line sat behind the offer would otherwise be suspended whole.
IGNORED_RESTRICTIONS = "ignored_restrictions_until_eot"

#: "That creature's controller may sacrifice a permanent of their choice for
#: that player to ignore this effect until end of turn." (Volrath's Curse.)
#: CR 116.2d, and the sentence in front of it is what "this effect" names —
#: which is why the pattern reads the noun: the offer is about the restriction
#: line above it, on the permanent that line is about.
_IGNORE_STATIC_OFFER = re.compile(
    r"^that (?P<noun>[a-z]+)'s controller may sacrifice a permanent of their "
    r"choice for that player to ignore this effect until end of turn$"
)


def aura_ignore_offer(oracle_text: str) -> frozenset[str] | None:
    """The restrictions an Aura's CR 116.2d offer suspends, or None.

    "This effect" is the sentence printed in front of the offer, so the two are
    read together: the restriction set comes from :func:`aura_restrictions` over
    the same line, which is the reader that will be asked to skip them. An offer
    printed against a sentence this file does not implement claims nothing —
    a suspension of a restriction nobody imposes is not an effect.
    """
    for raw_line in (oracle_text or "").splitlines():
        line = _line_text(raw_line)
        for index, sentence in enumerate(part.strip() for part in line.split(".")):
            if not sentence or _IGNORE_STATIC_OFFER.match(sentence) is None:
                continue
            preceding = ". ".join(
                part.strip() for part in line.split(".")[:index] if part.strip()
            )
            restrictions = aura_restrictions(preceding)
            return restrictions or None
    return None


def _ignore_static_offer(game, aura):
    """What *aura* is offering its host's controller (CR 116.2d), or None."""
    from .special_actions import SpecialActionOffer

    restrictions = aura_ignore_offer(aura.effective_card.oracle_text)
    if not restrictions:
        return None
    host = aura.metadata.get("attached_to")
    if host is None or not game.is_on_battlefield(host):
        return None
    if restrictions <= set(aura.metadata.get(IGNORED_RESTRICTIONS) or ()):
        # Already bought this turn. Offering it again would let a seat pay twice
        # for one turn's relief, which the printed duration does not do.
        return None
    seat = game.controller_index_of(host)
    if seat is None:
        return None
    # "…**a permanent** of their choice", which is CR 110.1's whole noun: an
    # empty filter is every permanent, and a narrower phrase on a later card is
    # the same field with data in it.
    return SpecialActionOffer(seat=seat, sacrifice={})


def _take_ignore_static_offer(game, seat: int, aura) -> None:
    restrictions = aura_ignore_offer(aura.effective_card.oracle_text) or frozenset()
    kept = set(aura.metadata.get(IGNORED_RESTRICTIONS) or ())
    aura.metadata[IGNORED_RESTRICTIONS] = sorted(kept | set(restrictions))
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{game.players[seat].name} ignores {aura.card.name}'s effect until "
        "end of turn (CR 116.2d)"
    )


def clear_ignored_restrictions(permanent) -> bool:
    """CR 514.2's cleanup: an "until end of turn" suspension ends.

    Beside the other cleanup sweeps and swept the same way, because that is what
    the printed duration is. Returns whether anything was cleared.
    """
    return permanent.metadata.pop(IGNORED_RESTRICTIONS, None) is not None


#: "Enchanted creature has phasing **and can't be blocked except by Walls**."
#: (Cloak of Invisibility.) One printed line carrying two effects in two
#: channels — a layer-6 keyword grant and a CR 506 combat restriction — which is
#: the shape ``aura_grants._COMPOUND_INDESTRUCTIBLE`` and
#: ``_TYPE_ADDITION_GRANT`` already have, and for their reason: each half
#: already has a reader, and the line matching neither pattern whole is what
#: left the card unsupported with both of its halves individually working.
#:
#: Neither half is spelled out. The keyword run goes to the same
#: ``_keyword_list`` every other grant uses and the restriction tail goes to
#: ``combat_restrictions.combat_restriction_for`` — the table that already reads
#: that sentence when a creature prints it about itself — so a card printing
#: "has flying and can't be blocked by Walls" is this rule with nothing added.
#: A tail that table cannot read leaves the whole line unmatched and the card
#: unsupported, rather than granting the keyword and dropping the restriction:
#: a restriction the card prints and no combat step asks about is an ability
#: that works more often than the card allows, which is the quiet direction.
_KEYWORD_GRANT_AND_RESTRICTION = _LazyPattern(lambda: re.compile(
    rf"^{_ATTACHED} (?P<noun>{_NOUN}) has "
    rf"(?P<keyword>(?:{_keyword_alternation()})"
    rf"(?:(?:, and |, | and )(?:{_keyword_alternation()}))*) "
    rf"and (?P<restriction>can't .+)$"
))


#: "Enchanted creature gets +1/+1 **and can't be blocked except by creatures
#: with flying**." (Treetop Bracers.) The P/T twin of the keyword compound
#: above: a layer-7c grant and a CR 509.1b restriction on one printed line. The
#: grant half is already read by :func:`aura_static_pt_grant`, which searches
#: the line for its numbers and declines only a tail that makes the grant
#: something other than flat (a duration, a condition, a count) — a restriction
#: is none of those. So what was missing was only the restriction half's
#: reader, and this hands it to :func:`aura_combat_restriction` through the one
#: splitter both compounds share.
_PT_GRANT_AND_RESTRICTION = re.compile(
    rf"^{_ATTACHED} (?P<noun>{_NOUN}) gets [+-]\d+/[+-]\d+ "
    rf"and (?P<restriction>can't .+)$"
)


def _compound_restriction_clause(normalized: str):
    """The ``(noun, restriction clause)`` a compound line carries, or None.

    Split out because both halves of the compound are read by different
    functions — the keyword by :func:`aura_keyword_grants` (or the P/T by
    :func:`aura_static_pt_grant`), the tail by :func:`aura_combat_restriction`
    — and a second copy of the pattern in each is exactly the two-lists-one-rule
    shape this file's other comments record removing.
    """
    match = (
        _KEYWORD_GRANT_AND_RESTRICTION.match(normalized)
        or _PT_GRANT_AND_RESTRICTION.match(normalized)
    )
    if match is None:
        return None
    return match.group("noun"), match.group("restriction")


# ---------------------------------------------------------------------------
# Restrictions an Aura imposes
# ---------------------------------------------------------------------------
#
# These are not characteristics, so CR 613's layers do not apply to them — they
# change how the game is played (what may block, what untaps, what may attack).
# The ownership principle is the same one the layers gave P/T and keywords: the
# reader asks whether any attached Aura imposes the restriction, instead of the
# Aura stamping a flag on the permanent and something having to remember to
# take it off again.
#
# Each name is the vocabulary the readers use; the pattern is the printed line.
_RESTRICTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf"^all creatures able to block {_ATTACHED} creature do so$"),
        "must_be_blocked_by_all_able",
    ),
    (
        # "Enchanted creature gets +3/+0 and **can only attack alone**."
        # (Errantry.) CR 506.5's "attacking alone", read as a restriction on the
        # *declaration*: the creature may attack only in a declaration where it
        # is the sole attacker. The P/T half is `aura_static_pt_grant`'s, which
        # is why the prefix is optional here — the same split `_KEYWORD_GRANT`
        # makes.
        re.compile(
            rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? "
            r"can only attack alone$"
        ),
        "can_only_attack_alone",
    ),
    (
        # The optional P/T prefix is the same split `_KEYWORD_GRANT` and the
        # attack-alone row make: "Enchanted creature gets +1/+1 **and** doesn't
        # untap during its controller's untap step" (Dance of the Dead) is one
        # printed line carrying two effects in two channels, and
        # `aura_static_pt_grant` searches rather than anchors, so both halves
        # are read. Without the prefix the line matched nothing and the Aura
        # lost the restriction *and* reported the line unclaimed.
        re.compile(
            rf"^{_ATTACHED} {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? "
            r"doesn't untap during its controller's untap step$"
        ),
        "doesnt_untap",
    ),
    (
        re.compile(rf"^{_ATTACHED} {_NOUN} can attack as though it didn't have defender$"),
        "ignores_defender",
    ),
    (
        # Furor of the Bitten. The P/T half is read by `aura_static_pt_grant`,
        # which searches rather than anchors — so this pattern claims the whole
        # line and neither half is dropped.
        re.compile(
            rf"^enchanted {_NOUN} gets [+-]\d+/[+-]\d+ and attacks each combat if able$"
        ),
        "must_attack_each_combat",
    ),
    (
        # The other half of Consecrate Land's compound line; the indestructible
        # half is a layer-6 keyword grant (aura_keyword_grants).
        re.compile(
            rf"^enchanted {_NOUN} has indestructible and "
            r"can't be enchanted by other auras$"
        ),
        "cant_be_enchanted_by_auras",
    ),
    (
        # Instill Energy. NOT a haste grant: CR 702.10b lifts the attack clause
        # of CR 302.6, and this wording lifts only that same clause. Granting
        # the haste keyword instead also lifted the {T}-ability clause, so a
        # summoning-sick Llanowar Elves under Instill Energy tapped for mana.
        re.compile(rf"^enchanted {_NOUN} can attack as though it had haste$"),
        "attacks_as_though_hasty",
    ),
    (
        # Faith's Fetters, first half. Two restrictions in one printed clause,
        # and both are named here rather than one standing for the pair: a card
        # printing only "can't attack" (Pacifism) or only "can't block" is a
        # different card, and the enforcement sites are two different steps.
        re.compile(rf"^enchanted {_NOUN} can't attack or block\b"),
        "cant_attack",
    ),
    (
        re.compile(rf"^enchanted {_NOUN} can't attack or block\b"),
        "cant_block",
    ),
    (
        # Demonic Torment / Pacifism's half. The compound rows above say in so
        # many words that a card printing only "can't attack" is a different
        # card; this is that card, and without the row its line was unclaimed
        # and the Aura reported unsupported.
        re.compile(rf"^enchanted {_NOUN} can't attack$"),
        "cant_attack",
    ),
    (
        # Convulsing Licid. The blocking half of the pair above, and the same
        # argument for a row of its own: the compound "can't attack or block"
        # rows say in so many words that a card printing one half is a
        # different card, and Stronghold prints the half nobody had. Without
        # the row the line was unclaimed, the Licid reported unsupported, and
        # `declare_blockers_step` — which has read this very name since
        # Pacifism's cousins arrived — had nothing to read.
        #
        # The optional P/T prefix is the same split the attack-alone and
        # "doesn't untap" rows above make, and Maniacal Rage is the card that
        # prints it: "Enchanted creature gets +2/+2 **and** can't block" is one
        # line carrying two effects in two channels, the numbers read by
        # `aura_static_pt_grant` (which searches rather than anchors) and the
        # restriction read here. Without the prefix the line matched nothing —
        # the Aura lost the restriction *and* reported the line unclaimed,
        # which is the failure Dance of the Dead's row records one screen up.
        re.compile(rf"^enchanted {_NOUN}(?: gets [+-]\d+/[+-]\d+ and)? can't block$"),
        "cant_block",
    ),
    (
        # Faith's Fetters, second half. CR 605.1a's exception is part of the
        # name, because the clause without it is a strictly harsher restriction
        # — an Aura that stopped a land tapping for mana would lock its
        # controller out of the game rather than shut off one ability.
        re.compile(
            rf"^{_ATTACHED} {_NOUN} can't attack or block, and its activated "
            r"abilities can't be activated unless they're mana abilities$"
        ),
        "activated_abilities_shut_off",
    ),
    (
        # Volrath's Curse prints the same sentence **without** CR 605.1a's
        # exception, and that is a different card rather than a wording of the
        # row above: a Birds of Paradise under Faith's Fetters may still tap for
        # mana and one under the Curse may not. Its own name for that reason —
        # the enforcement site reads which of the two it is, and one name for
        # both would have to pick a side.
        #
        # Anchored on the clause rather than the line, like the two "can't
        # attack or block" rows above it: this sentence is printed with a second
        # one behind it (the CR 116.2d offer), so a `$` would match nothing. The
        # lookahead is what keeps it off the longer wording above.
        re.compile(
            rf"^{_ATTACHED} {_NOUN} can't attack or block, and its activated "
            r"abilities can't be activated(?! unless)"
        ),
        "all_activated_abilities_shut_off",
    ),
    (
        # "Enchanted creature's activated abilities can't be activated."
        # (Stupefying Touch.) The Curse's second clause alone, in the
        # possessive, and the same restriction by name — no CR 605.1a
        # exception is printed, and the card's ruling says what that means:
        # "Unlike many similar abilities, Stupefying Touch's last ability stops
        # mana abilities from being activated." (2016-06-08.) Anchored on the
        # whole line: the clause with "unless they're mana abilities" behind
        # it is the row below, and a creature that also can't attack is the
        # Curse's row above.
        re.compile(rf"^{_ATTACHED} {_NOUN}'s activated abilities can't be activated$"),
        "all_activated_abilities_shut_off",
    ),
    (
        # …and the same possessive with Faith's Fetters' exception printed.
        re.compile(
            rf"^{_ATTACHED} {_NOUN}'s activated abilities can't be activated "
            r"unless they're mana abilities$"
        ),
        "activated_abilities_shut_off",
    ),
)

# A "doesn't untap" restriction that holds only while a counter is present —
# the Legends sleep/pupa pair. The counter's kind and which object holds it are
# the parameters (payload, exactly as every text-keyed table treats them):
# Venarian Gold reads the counter off the **enchanted creature**, Cocoon off
# the **Aura itself**. Both rows are read by `aura_restriction_active`, so the
# untap step needs no new question — a conditional row whose condition holds is
# simply "doesnt_untap" being active this step.
#
# Cocoon prints "during **your** untap step" where Venarian Gold prints
# "during **its controller's**". The rows deliberately answer both with the
# creature's controller's step — the one the untap step is asking about —
# because Cocoon's "Enchant creature you control" makes the two the same seat
# whenever the attachment is legal: an opponent gaining control of the creature
# makes the attachment illegal, and the state-based sweep puts the Aura into
# the graveyard before any untap step arrives (CR 704.5m/n).
#
# **One pattern over two axes, not a row per pairing.** The step is printed two
# ways ("its controller's", "your") and the holder two ways ("it", "this
# aura"), and Merseine prints the crossing the pairing table had no row for —
# "during **its controller's** untap step if **this Aura** has a net counter on
# it". A row per pairing is quadratic in the clauses that exist, which is the
# arrangement `engine/activation_restrictions.py` records replacing for exactly
# this reason; and the clause nobody had listed is not a dead restriction, it
# is an *unenforced* one, so the card untaps every turn while reporting fine.
_COUNTER_UNTAP_CONDITION = re.compile(
    rf"^{_ATTACHED} {_NOUN} doesn't untap during (?:its controller's|your) "
    r"untap step if (?P<holder>it|this aura) has an? (?P<kind>[a-z]+) "
    r"counter on it$"
)


#: "Enchanted creature doesn't untap during its controller's untap step **if it
#: attacked during its controller's last turn**." (Tangle Kelp.) The same
#: sentence Goblin Rock Sled prints about *itself*, which is idiom 14 exactly:
#: one question, asked with the subject rewritten. The answer is
#: ``turn_state.attacked_during_seats_last_turn`` for both, so the Aura cannot
#: drift from the creature that prints it — and neither can drift from the
#: declare-attackers step, which refuses Giant Turtle's attack on the same read.
_ATTACHED_UNTAP_ATTACKED_LAST_TURN = re.compile(
    rf"^{_ATTACHED} {_NOUN} doesn't untap during its controller's untap step "
    r"if it attacked during its controller's last turn$"
)


def aura_attacked_untap_condition(line: str) -> bool:
    """Whether *line* is the attack-conditioned "doesn't untap" Aura clause."""
    return _ATTACHED_UNTAP_ATTACKED_LAST_TURN.match(_line_text(line)) is not None


def aura_counter_untap_condition(line: str) -> tuple[str, str] | None:
    """``(counter kind, holder)`` for a counter-conditioned untap line, or None.

    *holder* names which object the condition reads: ``"attached"`` (Venarian
    Gold's sleep counter on the creature) or ``"aura"`` (Cocoon's pupa counter
    on the Aura itself).
    """
    match = _COUNTER_UNTAP_CONDITION.match(_line_text(line))
    if match is None:
        return None
    holder = "aura" if match.group("holder") == "this aura" else "attached"
    return match.group("kind"), holder


#: "Enchanted creature can't block **if it's black**." (Hobble.) A combat ban
#: that holds only while the host is a colour — the conditioned twin of the
#: plain ``cant_attack`` / ``cant_block`` rows in ``_RESTRICTIONS``, read by the
#: same predicate under the same two names, so the two steps that enforce those
#: rows need no new question: a conditioned row whose condition holds is simply
#: the restriction being active this declaration. That is the arrangement the
#: counter-conditioned "doesn't untap" rows above already have.
#:
#: **One pattern over two axes**, for the reason that pattern gives: the verb is
#: printed two ways and the colour five, and a row per pairing would leave the
#: nine nobody listed *unenforced* rather than dead. Hobble prints one crossing;
#: the other nine are the same sentence.
#:
#: The colour is the host's as the layers currently have it (CR 613 layer 5),
#: asked when combat asks — a creature turned black stops being able to block,
#: and one turned another colour can block again, with nothing to clear.
_COLOR_CONDITIONED_COMBAT_BAN = re.compile(
    rf"^{_ATTACHED} {_NOUN} can't (?P<verb>attack|block) "
    rf"if it's (?P<color>{_COLORS})$"
)

#: The restriction name each printed verb is enforced under.
_COMBAT_BAN_NAMES = {"attack": "cant_attack", "block": "cant_block"}


def aura_color_conditioned_combat_ban(line: str) -> tuple[str, str] | None:
    """``(restriction name, colour word)`` for a colour-conditioned combat ban,
    or None.

    The colour is the printed *word*, for :func:`aura_protection_colors`'
    reason: the caller maps it, and layer 3's text change (Sleight of Mind) has
    already rewritten the word by the time it is read off ``effective_card``.
    """
    match = _COLOR_CONDITIONED_COMBAT_BAN.match(_line_text(line))
    if match is None:
        return None
    return _COMBAT_BAN_NAMES[match.group("verb")], match.group("color")


def aura_restrictions(oracle_text: str) -> frozenset[str]:
    """The named restrictions an Aura imposes while attached."""
    found = {
        name
        for raw_line in oracle_text.splitlines()
        for pattern, name in _RESTRICTIONS
        if pattern.match(_line_text(raw_line))
    }
    return frozenset(found)


#: The combat-restriction kinds a reader asks of the *attached* channel below.
#:
#: ``engine/combat_restrictions.py``'s table reads a printed line, and an Aura
#: printing one of its sentences about the permanent it is attached to is the
#: same restriction — so the table is asked rather than copied, exactly as
#: ``aura_continuous_claim`` asks the derivation tables rather than listing
#: their sentences again. But every one of those kinds is enforced by reading
#: the *creature's own* compiled program, and a kind claimed here with nothing
#: consulting :func:`attached_combat_restrictions` would be a restriction the
#: card prints, the support gate admits, and no combat step ever asks about —
#: an ability that works more often than the card allows. So the set names
#: exactly the kinds a reader consults, and adding one means adding that
#: reader.
ENFORCED_ATTACHED_COMBAT_RESTRICTIONS = frozenset({
    # "Enchanted creature can't be blocked." (Cloak of Mists.) The unnarrowed
    # member of the family below: no blocker class, no count and no price, so
    # nothing may block the host at all (CR 509.1b). Phantom Warrior prints the
    # same sentence about itself, which is what makes it one table asked with
    # the subject rewritten rather than a second reading.
    #
    # Its readers are ``phases/declare_blockers_step._can_block_attacker``,
    # which refuses every blocker, and ``legality.is_unblockable``, which fades
    # the creature in the UI. Both already answered the kind off the
    # *attacker's own* program and had to be taught this channel as well --
    # a kind in this set with only one of its readers widened is a restriction
    # the UI shows and the step ignores, or the reverse.
    "cant_be_blocked",
    "cant_be_blocked_by",
    # "Enchanted creature can't be blocked except by artifact creatures and/or
    # white creatures." (Seeker.) The whitelist form, read through the same
    # subject rewrite as the blacklist beside it — the difference between
    # Seeker and Elven Riders is whose text the sentence is printed on.
    "cant_be_blocked_except_by",
    # "Enchanted creature can't attack unless its controller pays {3}."
    # (Brainwash.) CR 508.1h, an additional cost to declare the creature as an
    # attacker. Its reader is
    # ``phases/declare_attackers_step._attack_mana_costs_of``, which asks this
    # channel and the creature's own compiled program together — the gate in
    # ``can_attack`` and the charge in ``declare_attackers`` share it, so the
    # restriction cannot be checked and then left uncharged.
    "cant_attack_unless_pay",
    # "Enchanted creature can't block creatures with power equal to or greater
    # than the enchanted creature's toughness." (Ironclaw Curse.) The mirror of
    # ``cant_be_blocked_by`` above — that one says what may not block the
    # creature, this one what the creature may not block — and Ironclaw Orcs
    # prints the same sentence about itself, so it is the same table asked with
    # the subject rewritten (idiom 14). Its reader is
    # ``phases/declare_blockers_step``, which asks this channel and the
    # blocker's own compiled program in one loop, so the two spellings of the
    # restriction cannot come to be enforced differently.
    "cant_block_subject",
    # "Enchanted creature can block only creatures with flying." (Air Bladder.)
    # Shacklegeist prints the same sentence about itself, so it is the same
    # table asked with the subject rewritten. Its reader is
    # ``phases/declare_blockers_step._can_block_attacker``, which asks this
    # channel and the blocker's own compiled program in one loop — the shape
    # ``cant_block_subject`` above already has, for its reason.
    "can_block_only_with_keyword",
    # "Enchanted creature can't be blocked unless defending player pays {3} for
    # each creature they control that's blocking it." (Awesome Presence.)
    # CR 509.1d's cost owed by the **defender**, the mirror of
    # ``cant_attack_unless_pay`` above. Its reader is
    # ``phases/declare_blockers_step._block_mana_costs_of``, which asks this
    # channel about the *attacker* alongside the blocker's own program, so the
    # gate in ``_can_block_attacker`` and the charge in ``declare_blockers``
    # share one reading and a block cannot be accepted and left unpaid.
    "cant_be_blocked_unless_pay",
})

#: "Enchanted creature" / "equipped creature" in the subject position, with the
#: noun kept: the table below is written about "this creature", and a line about
#: an enchanted *artifact* is a sentence about something else that must fail to
#: match rather than be rewritten into one that does.
_ATTACHED_SUBJECT = re.compile(rf"^{_ATTACHED} (?P<noun>{_NOUN})(?= )")


def aura_combat_restriction(line: str):
    """The combat restriction an Aura's *line* imposes on what it is attached to.

    "Enchanted creature can't be blocked by artifact creatures." (Artifact
    Ward.) Argothian Pixies prints the same restriction about itself, so the
    difference between the two cards is the subject of the sentence and nothing
    else — which is why this rewrites the subject and asks
    ``combat_restrictions.combat_restriction_for`` instead of holding a second
    copy of its table.

    Returns None for a kind nothing consults through the attached channel; see
    :data:`ENFORCED_ATTACHED_COMBAT_RESTRICTIONS`.
    """
    from .combat_restrictions import combat_restriction_for

    normalized = _line_text(line)
    # "Enchanted creature has phasing **and can't be blocked except by Walls**."
    # (Cloak of Invisibility.) The restriction half of a compound line, asked
    # first because the plain subject match below would hand the whole
    # sentence — keyword grant included — to a table anchored on "can't", which
    # answers None and drops a restriction the card prints.
    compound = _compound_restriction_clause(normalized)
    if compound is not None:
        noun, clause = compound
        restriction = combat_restriction_for(f"this {noun} {clause}")
        if restriction is None or restriction.also_kinds or restriction.kind not in (
            ENFORCED_ATTACHED_COMBAT_RESTRICTIONS
        ):
            return None
        return restriction
    match = _ATTACHED_SUBJECT.match(normalized)
    if match is None:
        return None
    restriction = combat_restriction_for(
        f"this {match.group('noun')}{normalized[match.end():]}"
    )
    if restriction is None:
        return None
    if restriction.kind not in ENFORCED_ATTACHED_COMBAT_RESTRICTIONS:
        return None
    # A row naming several kinds over one sentence
    # (``CombatRestriction.also_kinds``) has only its first honoured here: this
    # channel returns one restriction per line and every reader asks about one
    # kind. Refusing keeps the Aura unsupported and named, where returning the
    # first would enforce one clause of its sentence and drop the others.
    if restriction.also_kinds:
        return None
    return restriction


def attached_combat_restrictions(permanent) -> tuple:
    """Every combat restriction the Auras on *permanent* impose on it.

    Asked at the moment combat reads it, so the restriction ends when the Aura
    does with nothing having to clear a flag — the same shape
    :func:`aura_restriction_active` has, carrying a payload.
    """
    found = []
    for aura in auras_attached_to(permanent):
        for raw_line in (aura.effective_card.oracle_text or "").splitlines():
            restriction = aura_combat_restriction(raw_line)
            if restriction is not None:
                found.append(restriction)
    return tuple(found)


def aura_block_permission(line: str) -> int:
    """How many attackers beyond the printed one an Aura's *line* lets the
    permanent it is attached to block, or 0.

    "Enchanted creature can block any number of creatures." (Entangler.) Wall of
    Glare and Avatar of Hope print the same permission about themselves, so the
    difference between the cards is the subject of the sentence and nothing
    else — which is why this rewrites the subject and asks
    ``combat_permissions.printed_block_ceiling`` instead of holding a second
    copy of its table, exactly as :func:`aura_combat_restriction` asks the
    restriction table. An Equipment printing it is the same rule (CR 301.5f).
    """
    from .combat_permissions import printed_block_ceiling

    normalized = _line_text(line)
    match = _ATTACHED_SUBJECT.match(normalized)
    if match is None:
        return 0
    return printed_block_ceiling(
        (f"this {match.group('noun')}{normalized[match.end():]}",)
    )


def attached_block_ceiling(permanent) -> int:
    """The block permissions the Auras on *permanent* grant it, summed.

    Asked when the declare-blockers step reads the ceiling (CR 509.1b), so the
    permission ends when the Aura does with nothing to clear — the shape
    :func:`attached_combat_restrictions` has. Summed rather than maximised for
    ``printed_block_ceiling``'s reason: CR 509.1b's permissions add.
    """
    return sum(
        aura_block_permission(raw_line)
        for aura in auras_attached_to(permanent)
        for raw_line in (aura.effective_card.oracle_text or "").splitlines()
    )


#: "This token can't be enchanted." (Tetravus's Tetravites.) A restriction the
#: permanent prints about **itself**, which is the opposite direction from
#: everything else in this file — those describe what an Aura does to what it is
#: attached to. It lives here anyway because attachment is what it is about, and
#: because the two predicates that already answer "can an Aura go on this?" have
#: to ask one question rather than growing a third source each.
#:
#: Anchored on the whole sentence. Consecrate Land's "can't be enchanted by
#: other auras" is a *narrower* restriction with its own name in the table
#: above, and a prefix match here would claim it and then enforce the wider one.
_SELF_CANT_BE_ENCHANTED = re.compile(
    rf"^this (?:token|{_NOUN}) can't be enchanted$"
)


def self_cant_be_enchanted_line(line: str) -> bool:
    """Whether one printed line is "this <noun> can't be enchanted", in full.

    Read by the support gate and by both attachment predicates, so what is
    claimed and what is enforced cannot drift.
    """
    return _SELF_CANT_BE_ENCHANTED.match(_line_text(line)) is not None


def cant_be_enchanted_by_own_text(permanent) -> bool:
    """Whether *permanent*'s own text forbids Auras attaching to it.

    Off ``effective_card``, so a copy of a Tetravite carries the restriction
    (CR 707.2) and a text change can take it away.
    """
    card = getattr(permanent, "effective_card", None) or getattr(permanent, "card", None)
    text = getattr(card, "oracle_text", "") or ""
    return any(self_cant_be_enchanted_line(line) for line in text.splitlines())


def aura_restriction_active(
    permanent, name: str, *, game=None, seat: int | None = None
) -> bool:
    """Whether any Aura attached to *permanent* imposes restriction *name*.

    This is the whole of "does the restriction apply": when the Aura leaves it
    stops being attached, so it stops being asked. Nothing is stamped and
    nothing has to be cleaned up.

    *game* and *seat* are what the conditional ``doesnt_untap`` rows need: one
    of them reads the permanent's attack record against a seat's turn ordinal,
    which is not readable off the permanent alone. A caller that cannot supply
    them gets the unconditional rows only — the untap step, the one place the
    restriction is enforced, supplies both.
    """
    from .named_counters import counters_on
    from .turn_state import attacked_during_seats_last_turn

    for aura in auras_attached_to(permanent):
        # CR 116.2d: the host's controller bought a turn off this Aura's
        # restrictions, so it is imposing none of them for the rest of the turn
        # (Volrath's Curse). Asked here rather than at each of the eight readers
        # of this predicate, because this is the one place "does the restriction
        # apply?" is answered — a suspension wired into the combat step alone
        # would leave the creature's activated abilities still shut off.
        if name in (aura.metadata.get(IGNORED_RESTRICTIONS) or ()):
            continue
        text = aura.effective_card.oracle_text
        if name in aura_restrictions(text):
            return True
        if name in ("cant_attack", "cant_block"):
            # "Enchanted creature can't block **if it's black**." (Hobble.) The
            # colour-conditioned rows: active exactly while the host is that
            # colour, read through layer 5 at ask time.
            from .grammar.vocabulary import COLOR_WORDS

            colors_now = permanent.effective_colors
            for raw_line in (text or "").splitlines():
                ban = aura_color_conditioned_combat_ban(raw_line)
                if (
                    ban is not None
                    and ban[0] == name
                    and COLOR_WORDS[ban[1]] in colors_now
                ):
                    return True
            continue
        if name != "doesnt_untap":
            continue
        # The conditioned rows: the restriction is active exactly while the
        # condition holds, read at ask time — so when the last counter leaves,
        # or the creature sits out a turn, nothing has to be cleared for it to
        # untap again.
        for raw_line in (text or "").splitlines():
            found = aura_counter_untap_condition(raw_line)
            if found is not None:
                kind, holder = found
                holder_obj = permanent if holder == "attached" else aura
                if counters_on(holder_obj, kind) > 0:
                    return True
                continue
            if (
                aura_attacked_untap_condition(raw_line)
                and game is not None
                and seat is not None
                and attacked_during_seats_last_turn(game, permanent, seat)
            ):
                return True
    return False


#: "Enchanted creature's **controller** can't cast creature spells."
#: (Brand of Ill Omen.) A restriction on a *player*, which is what keeps it out
#: of ``_RESTRICTIONS`` beside it: every row there is a fact about the attached
#: permanent, asked of that permanent by the step that enforces it, and there is
#: no permanent here to ask.
#:
#: The card **type** is payload for the reason every printed word in this file
#: is one: "…can't cast artifact spells" is the same sentence and must need no
#: second row. So is the seat word — CR 109.5 makes "enchanted creature's
#: controller" the controller of the *creature*, not of the Aura, and that is
#: read off the host at the gate rather than assumed to be the Aura's own.
_ATTACHED_CONTROLLER_CAST_BAN = re.compile(
    rf"^{_ATTACHED} {_NOUN}'s controller can't cast (?P<type>{_NOUN}) spells$"
)


def aura_controller_cast_ban(line: str) -> str | None:
    """The card type the enchanted permanent's controller can't cast, or None.

    One reader, two callers, which is this file's standing rule: the support
    gate asks it through :func:`aura_continuous_claim` so the line is claimed,
    and ``mixins/stack/casting.py`` asks it at CR 601.2 so the line is
    *enforced*. A printed restriction is only done when something enforces it —
    parsed and dropped, this one is an Aura that reports supported and lets the
    creature spells through.
    """
    match = _ATTACHED_CONTROLLER_CAST_BAN.match(_line_text(line))
    return match.group("type") if match is not None else None


def controller_cast_ban(game, seat: int, card) -> str | None:
    """The name of an Aura forbidding *seat* from casting *card*, or None.

    Read off the **host**, not off the Aura: the sentence says "enchanted
    creature's controller", and an Aura an opponent controls on your creature
    stops *you* casting. Every Aura on the battlefield is asked, because that is
    where the attachment record lives — an Aura that has left is no longer
    attached and so no longer says anything, with nothing to clean up.
    """
    for host_seat, host in game.permanents_with_controller():
        if host_seat != seat:
            continue
        for aura in auras_attached_to(host):
            for raw_line in (aura.effective_card.oracle_text or "").splitlines():
                banned = aura_controller_cast_ban(raw_line)
                if banned is not None and card.primary_type == banned:
                    return aura.card.name
    return None

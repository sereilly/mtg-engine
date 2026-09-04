"""Text-keyed *additional* costs a spell prints in its own text (CR 601.2b).

The same model as ``cast_restrictions.py``, and for the same reason: "As an
additional cost to cast this spell, sacrifice a creature" means the same thing
on every card that prints it, so it is a table keyed by the canonical phrase
rather than four per-card hooks. A new card printed with a known phrase needs no
registration at all.

**What this replaced was not a gap, it was worse than one.** The phrase sat in
``SUPPORTED_SPELL_PATTERNS`` — a substring whitelist whose match produces a
marker instruction with no handler — so Village Rites compiled to "draw two
cards" plus a no-op, reported ``supported``, and cast **for free**: the cost was
claimed, never paid, and nothing in the engine knew the difference. Thrill of
Possibility's discard did not even get the marker. Alpha's Sacrifice and
Metamorphosis escaped only because a *card hook* folded the cost into their
effect, which is why the general form had never been needed.

A cost is not an effect, so none of this is an instruction. The compiler asks
this table whether a line is a cost (which is what stops the line being reported
"too complex"), and ``queue_from_hand`` asks it twice more: once before any
payment, because CR 601.2h says an unpayable cost can't be paid and CR 601.2h's
failure is *the spell can't be cast*, and once after, to perform it.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .oracle_types import _NUMBER_WORDS
from .subject_filters import filter_head_noun

if TYPE_CHECKING:
    from .models import CardDefinition


@dataclass(frozen=True)
class OptionalManaCost:
    """One "you may pay {1}{R}" an additional-cost sentence offers (CR 601.2b).

    Its own object rather than a field on :class:`AdditionalCost` because a
    single printed sentence offers **several** of them independently — Primitive
    Justice's "you may pay {1}{R} and/or {1}{G} any number of times" is two
    offers, each paid however many times the caster likes, and the effect reads
    the two counts apart. One field could hold one count; two cards in this set
    need two.

    ``symbols`` is the canonical spelling ``mana_cost_label`` produces, so the
    key a resolution reads back by ("for each additional **{1}{R}** you paid")
    is the same string however the card printed it. ``repeatable`` is CR 601.2b's
    "any number of times": without it the offer may be taken once.
    """

    symbols: str
    repeatable: bool = False

    @property
    def cost(self) -> dict[str, int]:
        """What one payment of this offer costs, as the symbol dict every
        payment in this engine speaks."""
        from .mana_payment import mana_cost_from_symbols

        return mana_cost_from_symbols(self.symbols) or {}


@dataclass(frozen=True)
class AdditionalCost:
    """One printed additional cost.

    ``sacrifice_filter`` is the noun phrase the sacrifice must match, in the same
    payload vocabulary ``ActivatedAbilityCost.sacrifice_filter`` and the
    forced-sacrifice prompt use — the *choice* is the same on all three sides
    (CR 601.2b and CR 602.2b are the same announcement step), so what may pay
    should not be described three ways. ``None`` means "no sacrifice", never
    "anything": an empty filter would let the payment be a land.
    """

    phrase: str
    sacrifice_filter: dict | None = None
    #: "…, sacrifice **two** creatures." (Phyrexian Tribute.) How many the
    #: printed cost eats, in the same field ``ActivatedAbilityCost`` carries it
    #: in and for the same reason CR 601.2b and CR 602.2b share a vocabulary:
    #: what may pay a printed sacrifice, and how many of it, is one question
    #: wherever the sacrifice is printed.
    #:
    #: Its own field rather than a count folded into the phrase, because the
    #: *number* is the whole of what makes such a cost unpayable: one creature
    #: is no more a payment than none (CR 601.2h), and a gate that asked only
    #: "is there a creature?" would admit the cast and then charge one -- a
    #: spell cast for less than it prints, which is this module's whole subject.
    sacrifice_count: int = 1
    #: "As an additional cost to cast this spell, **exile a creature you
    #: control**." (Soul Exchange.) The same noun-phrase vocabulary one field
    #: up, one zone over -- and its own field for the reason
    #: ``ActivatedAbilityCost`` keeps the two apart: an exiled permanent is
    #: still a card somewhere afterwards, a sacrificed one is in a graveyard,
    #: and a spell may read back either. ``None`` means "no exile", never
    #: "anything".
    exile_filter: dict | None = None
    discard_cards: int = 0
    #: "…, discard **a red or green card**." (Surge of Strength.) Which cards in
    #: hand may pay the discard above, as the alternatives the payer chooses
    #: between — the same tuple-of-payloads shape
    #: ``ActivatedAbilityCost.discard_filters`` carries, read by the same
    #: function (``oracle._chargeable_discard_filters``) and tested by the same
    #: matcher (``subject_filters.card_matches_any``). CR 601.2b and CR 602.2b
    #: are one announcement step, so what may pay a printed discard is one
    #: answer wherever the discard is printed.
    #:
    #: An empty tuple is the unrestricted "discard a card", where the whole hand
    #: pays — never "nothing pays", which is what a refusal means and why the
    #: reader returns None for that instead.
    discard_filters: tuple[dict, ...] = ()
    #: "…by paying **3 life** and discarding a card" (Demonic Embrace).
    #: CR 119.4 caps a life payment at the payer's life total and CR 601.2h then
    #: makes an unpayable cost an uncastable spell, checked with
    #: the rest of the costs before anything is spent.
    pay_life: int = 0
    #: "As an additional cost to cast this spell, pay **X** life." (Fire
    #: Covenant.) A life cost whose amount is the X the caster announces
    #: (CR 601.2b, CR 107.3) rather than a printed number — a separate field
    #: rather than a sentinel in ``pay_life``, because every reader of that
    #: field is arithmetic and a string in it would be charged as garbage.
    pay_life_x: bool = False
    #: "…, **you may pay {1}{R} and/or {1}{G} any number of times**."
    #: (Primitive Justice, Taste of Paradise, Undergrowth.) CR 601.2b's
    #: *optional* additional cost, and the only one in this file that is
    #: optional at all — every field above it is a price the cast pays or is
    #: refused for. So it is never part of ``_unpayable_additional_cost``: an
    #: offer nobody takes costs nothing, and an offer taken past what the pool
    #: can pay is refused by the mana payment itself, which is where CR 601.2h
    #: puts an unpayable mana cost.
    #:
    #: A tuple because one sentence may offer several independently, and how
    #: many times each was taken is what the resolution reads back — see
    #: ``game_types.ADDITIONAL_COSTS_PAID``.
    optional_mana: tuple[OptionalManaCost, ...] = ()
    #: The zone this cost applies to, when the sentence naming it also names a
    #: zone. Demonic Embrace costs {1}{B}{B} from the hand and {1}{B}{B} plus 3
    #: life plus a card from the graveyard — the *same card*, so the cost cannot
    #: be a property of the card alone. ``None`` means every zone, which is what
    #: an "as an additional cost to cast this spell" line means.
    from_zone: str | None = None

    def life_charged(self, x_value: int | None) -> int:
        """How much life this cost takes, given the announced X.

        One reader for the gate and the payment, because they are the same
        question asked twice — CR 601.2h refuses the cast when the answer is
        more life than the caster has, and CR 601.2b's announcement is what
        makes the answer knowable at all. A cost that spelled X and charged the
        printed 0 is the shape this whole module exists to prevent.
        """
        if self.pay_life_x:
            return max(0, int(x_value or 0))
        return self.pay_life

    def describe(self) -> str:
        parts = []
        for offer in self.optional_mana:
            parts.append(
                f"you may pay {offer.symbols}"
                + (" any number of times" if offer.repeatable else "")
            )
        if self.sacrifice_filter is not None:
            noun = filter_head_noun(self.sacrifice_filter)
            parts.append(
                f"sacrifice a {noun}" if self.sacrifice_count == 1
                else f"sacrifice {self.sacrifice_count} {noun}s"
            )
        if self.exile_filter is not None:
            parts.append(f"exile a {filter_head_noun(self.exile_filter)}")
        if self.pay_life_x:
            parts.append("pay X life")
        elif self.pay_life:
            parts.append(f"pay {self.pay_life} life")
        if self.discard_cards:
            named = filter_head_noun(self.discard_filters[0]) if self.discard_filters else "card"
            parts.append(f"discard {self.discard_cards} {named}(s)")
        return " and ".join(parts) or "no additional cost"


# Canonical lowercase phrases, matched against a whole normalized line. Both
# shapes the pool prints; a third goes here beside them.
#: "As an additional cost to cast this spell, <clauses>." (CR 601.2b.)
#:
#: This was a table of two whole *phrases*, each of which wrote the preamble out
#: again — so the only thing that varied was the clause after the comma, and a
#: clause nobody had listed was a line the table did not read. Fumarole's "pay 3
#: life" is one, and the way it showed up is worth keeping: the card had no
#: other blocker, so the moment its second line parsed it compiled *supported*
#: and cast for free. A preamble plus a clause vocabulary is the same shape
#: ``_SELF_PERMISSION_COSTS`` one function down already had.
_ADDITIONAL_COST_PREAMBLE = re.compile(
    r"^as an additional cost to cast this spell, (?P<costs>.+)$"
)


#: "You may cast this card from your <zone> by paying <costs> in addition to
#: paying its other costs." The costs half of the sentence
#: ``cast_permissions.self_permission_zone`` reads the zone half of.
_SELF_PERMISSION_COSTS = re.compile(
    r"^you may cast this card from your (?P<zone>graveyard|exile) by paying "
    r"(?P<costs>.+?) in addition to paying its other costs$"
)

#: The cost clauses either sentence may list, each mapped to the field it fills.
#: A clause outside this set makes the whole line unread — the card then reports
#: unsupported, or keeps the line in the parse-coverage backlog, rather than
#: being castable at a discount, which is the direction a cost must never drift
#: in.
#:
#: **One table for both sentences**, which print the same costs in two
#: grammatical forms: "as an additional cost …, **pay 3 life**" and "…by
#: **paying 3 life** in addition to paying its other costs". Two tables would be
#: two answers to "what can this engine charge", and the one that grew slower
#: would decide which cards were free.
#:
#: "pay X life" (Fire Covenant) is here now, and the note that used to say why
#: it was not is worth keeping: X is announced as the spell is cast (CR 601.2b)
#: and this engine used to run the affordability gate *before* resolving it, so
#: a clause here would have charged zero. That ordering was the bug, not the
#: reason — the card was already `supported` on its damage line alone, so the
#: cost was not being deferred, it was not being charged at all. The gate now
#: runs after X is announced and before any mana is spent, which is where
#: CR 601.2h puts it.
_COST_CLAUSES: tuple[tuple[re.Pattern[str], str], ...] = (
    # "…, **you may pay {1}{R} and/or {1}{G} any number of times**." (Primitive
    # Justice.) CR 601.2b's optional additional cost. First in the table because
    # it is the one clause whose text begins with a word another row could
    # claim, and because it is the only *optional* one — every row below it is a
    # price, and reading this as one would refuse the cast of a caster who
    # simply declined the offer.
    #
    # The whole run of symbols is captured together: ``_read_cost_clauses``
    # splits its sentence on ", " and " and ", and "and/or" contains neither, so
    # a two-offer sentence arrives here intact and is split by the reader below.
    (
        re.compile(
            r"^you may pay (?P<mana>\{.+?\})(?P<repeated> any number of times)?$"
        ),
        "optional_mana",
    ),
    (re.compile(r"^(?:pay )?x life$"), "pay_life_x"),
    (re.compile(r"^(?:pay )?(\d+) life$"), "pay_life"),
    # "discard a card", and its **narrowed** spelling: "discard a red or green
    # card" (Surge of Strength). This row used to be the literal
    # ``(?:a|one) card``, so a printed narrowing matched nothing at all — and a
    # clause this table cannot read leaves the whole sentence unread, which for
    # a card whose *other* line compiles means it reports ``supported`` and is
    # cast **without the cost**. Surge of Strength was exactly that: the discard
    # was printed, claimed by nobody, and never charged.
    #
    # The noun phrase goes through the same reader an activation cost's discard
    # does (``oracle._chargeable_discard_filters``), so what may pay a printed
    # discard is one answer wherever the discard is printed. Only the singular
    # is admitted, for the reason ``grammar/costs.py`` states on the activation
    # side: a counted "discard two cards" is a shape nothing charges, and
    # admitting it would describe a payment that never happens.
    (re.compile(r"^(?:discard|discarding) (?P<noun>(?:a|an|one) .+)$"), "discard"),
    # The **noun phrase is read, not spelled out**. This row was
    # ``sacrifice a creature`` as a literal, so Goblin Grenade's "sacrifice a
    # **Goblin**" matched nothing at all -- and a clause the table cannot read
    # leaves the line unclaimed, which for a card whose *other* line compiles
    # means it reports ``supported`` and is cast without its real cost. The
    # phrase goes through the same reader an activation cost's does
    # (``oracle.chargeable_sacrifice_payload``), so what may pay a printed
    # cost is one answer wherever the cost is printed.
    (re.compile(r"^(?:sacrifice|sacrificing) (?P<noun>.+)$"), "sacrifice"),
    # "…, **exile a creature you control**." (Soul Exchange.) The same clause
    # one zone over, gated by the exile charger's own reader for the same
    # reason -- two readers of one phrase drift, and the direction they drift
    # in is a cost nobody pays.
    (re.compile(r"^(?:exile|exiling) (?P<noun>.+)$"), "exile"),
)


def _read_cost_clauses(costs: str) -> dict | None:
    """The fields the clauses of one cost sentence fill, or None.

    **Every** clause must be read or the whole sentence is refused: one this
    table cannot charge would otherwise be dropped, and a dropped cost is a
    spell cast for less than it prints. That is the same all-or-nothing rule
    ``upkeep_costs.upkeep_cost_from_phrase`` states for CR 702.24a's cost, and
    it is here for the same reason.
    """
    fields: dict = {
        "pay_life": 0, "pay_life_x": False, "discard_cards": 0,
        "discard_filters": (),
        "sacrifice_filter": None, "sacrifice_count": 1, "exile_filter": None,
        "optional_mana": (),
    }
    for clause in re.split(r",\s*|\s+and\s+", costs):
        clause = clause.strip()
        if not clause:
            continue
        for pattern, field in _COST_CLAUSES:
            found = pattern.match(clause)
            if found is None:
                continue
            if field == "optional_mana":
                offers = _optional_mana_offers(
                    found.group("mana"), repeatable=bool(found.group("repeated")),
                )
                if offers is None:
                    # A symbol the payment cannot spend ({X}, a hybrid) or a
                    # second offer of the same cost, which would give the
                    # read-back one key for two counts. Refused whole, this
                    # function's rule everywhere else.
                    return None
                fields["optional_mana"] = fields["optional_mana"] + offers
            elif field == "pay_life_x":
                fields["pay_life_x"] = True
            elif field == "pay_life":
                fields["pay_life"] += int(found.group(1))
            elif field == "discard":
                from .oracle import _chargeable_discard_filters

                if fields["discard_cards"]:
                    # A second discard clause would need a second alternatives
                    # list, and one field cannot hold two: folded together they
                    # would read as a union, which is a strictly *cheaper* cost
                    # than the two narrowings printed. Refused whole, which is
                    # this function's rule everywhere else.
                    return None
                narrowed = _chargeable_discard_filters(found.group("noun"))
                if narrowed is None:
                    return None
                fields["discard_cards"] += 1
                fields["discard_filters"] = narrowed
            elif field == "sacrifice":
                # "…, sacrifice **two** creatures." (Phyrexian Tribute.) The
                # count is printed in front of the noun phrase, which leaves
                # that phrase the bare plural the noun parser reads with
                # ``plural=True`` -- the same split ``oracle`` makes for the
                # identically shaped activation cost, with the same table
                # reading the word. Anything that is not a number of two or
                # more falls through to the singular below, which is where "a
                # creature" has always been read: ``_NUMBER_WORDS`` maps "a",
                # "an" and "one" to 1, so the article cannot be mistaken for a
                # count.
                noun = found.group("noun")
                count, _, rest = noun.partition(" ")
                number = (
                    int(count) if count.isdigit() else _NUMBER_WORDS.get(count, 0)
                )
                if number >= 2 and rest:
                    described = _chargeable_object(rest, field, plural=True)
                    if described is None:
                        return None
                    fields["sacrifice_filter"] = described
                    fields["sacrifice_count"] = number
                    break
                described = _chargeable_object(noun, field)
                if described is None:
                    return None
                fields["sacrifice_filter"] = described
            else:
                described = _chargeable_object(found.group("noun"), field)
                if described is None:
                    # The phrase names something the payment path cannot
                    # enumerate or cannot test. The whole sentence is refused
                    # rather than charged as the part that was read — the
                    # all-or-nothing rule this function already states, and the
                    # one that keeps a card unsupported instead of cheap.
                    return None
                fields[f"{field}_filter"] = described
            break
        else:
            return None
    return fields


def _optional_mana_offers(
    printed: str, *, repeatable: bool
) -> tuple[OptionalManaCost, ...] | None:
    """The offers ``{1}{R} and/or {1}{G}`` names, or None.

    "and/or" is the only conjunction the pool prints here, and it is read as
    *independent* offers rather than as one cost: Primitive Justice's caster may
    pay {1}{R} twice and {1}{G} not at all, and the two counts are read back
    separately. A conjunction this does not know refuses the sentence, which
    leaves the card unsupported rather than castable for a cost nobody charged.

    Each run goes through ``mana_cost_from_symbols`` — the one reader that turns
    printed symbols into a payment — and is spelled back out by
    ``mana_cost_label``, so the key the effect reads back by is canonical rather
    than however this card happened to print it.

    Two offers of the *same* cost refuse: they would share one read-back key and
    one count, so the second would silently double the first.
    """
    from .mana_payment import mana_cost_from_symbols, mana_cost_label

    runs = [run.strip() for run in re.split(r"\s*and/or\s*", printed.strip())]
    offers: list[OptionalManaCost] = []
    for run in runs:
        if not run:
            return None
        if re.fullmatch(r"(?:\{[^{}]+\})+", run) is None:
            # Anything but a bare run of symbols — a word left over from a
            # conjunction this does not read, most likely. Refused rather than
            # charged as the part that matched.
            return None
        symbols = mana_cost_from_symbols(run)
        if not symbols:
            return None
        label = mana_cost_label(symbols)
        if any(offer.symbols == label for offer in offers):
            return None
        offers.append(OptionalManaCost(label, repeatable=repeatable))
    return tuple(offers) or None


def _chargeable_object(
    phrase: str, action: str, *, plural: bool = False
) -> dict | None:
    """The filter payload a "sacrifice/exile <noun phrase>" cost charges, or None.

    The **charger's own** reading, not a second one: ``engine/oracle.py`` holds
    ``chargeable_sacrifice_payload`` and ``chargeable_exile_payload`` because an
    activation cost asks the same question (CR 601.2b and CR 602.2b are one
    announcement step), and a phrase admitted here that they would refuse is a
    cost this table claims and nothing collects.

    **One zone**, because that is all ``_pay_additional_costs`` can reach: both
    verbs take a permanent off the caster's own battlefield. A phrase naming a
    graveyard or a hand is already refused by ``subject_filter_payload``, whose
    whole job is to read a phrase describing a *permanent*; the zone check below
    is the belt to that braces, so a later widening of that reader cannot
    silently admit a cost this table has nothing to charge.

    Imported inside the function for the reason every other reader of these does:
    ``engine/oracle.py`` imports this module at load time, so the edge back is
    taken at call time.

    *plural* is what a printed count leaves behind: "sacrifice two **creatures**"
    is the bare plural, and the noun parser reads a plural only when it is told
    to -- so the flag travels with the count rather than the reader guessing
    from the word, which is how "creatures" and "creature" would come to be one
    phrase.
    """
    from .grammar import subject_filter_payload
    from .oracle import chargeable_exile_payload, chargeable_sacrifice_payload

    described = subject_filter_payload(phrase.strip(), plural=plural)
    if described is None:
        return None
    if described.get("zone") not in (None, "battlefield"):
        return None
    reader = (
        chargeable_sacrifice_payload if action == "sacrifice"
        else chargeable_exile_payload
    )
    carried = reader(described)
    if carried is None or not (
        carried.get("type_filter") or carried.get("subtype_filter")
    ):
        # An *unnamed* cost — one whose noun phrase pins neither a card type nor
        # a subtype — would let the payment eat anything the caster controls,
        # a land included. The same narrowing ``grammar/costs.py`` makes for an
        # activation cost, and the one a key set cannot express.
        return None
    return carried


def _self_permission_cost(line: str) -> AdditionalCost | None:
    """The additional costs a self-granted zone permission charges, or None.

    Every clause must be read or the line is refused: a sentence that named a
    cost this table cannot charge would otherwise let the card be cast from the
    graveyard for less than it prints.
    """
    match = _SELF_PERMISSION_COSTS.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    fields = _read_cost_clauses(match.group("costs"))
    if fields is None:
        return None
    return AdditionalCost(match.group(0), from_zone=match.group("zone"), **fields)


def _printed_additional_cost(line: str) -> AdditionalCost | None:
    """The costs "As an additional cost to cast this spell, …" charges, or None.

    Unmarked by zone, which is what the sentence means: the cost applies
    wherever the spell is cast from (see ``AdditionalCost.from_zone``).
    """
    match = _ADDITIONAL_COST_PREAMBLE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    fields = _read_cost_clauses(match.group("costs"))
    if fields is None:
        return None
    return AdditionalCost(match.group(0), **fields)


def additional_cost_for_line(line: str) -> AdditionalCost | None:
    """The cost *line* states, or None when it states none.

    Matched on the line's whole text (minus a trailing period) rather than as a
    substring, because a substring match is how the whitelist this replaced came
    to claim things it did not implement.
    """
    return _printed_additional_cost(line) or _self_permission_cost(line)


def additional_costs(card: CardDefinition) -> tuple[AdditionalCost, ...]:
    """Every additional cost *card* prints, in printed order."""
    found = [
        cost
        for line in (card.oracle_text or "").split("\n")
        if (cost := additional_cost_for_line(line)) is not None
    ]
    return tuple(found)


def cast_cost_claims_line(line: str) -> bool:
    """Whether this table reads *line*.

    The support gate and the parse-coverage report both ask this, so what the
    engine implements and what it claims to have read cannot drift — the same
    seam ``enter_effects.enter_effect_line`` is.
    """
    return additional_cost_for_line(line) is not None


__all__ = [
    "AdditionalCost",
    "OptionalManaCost",
    "additional_cost_for_line",
    "additional_costs",
    "cast_cost_claims_line",
]

"""A printed quantity that is **counted**, against the sentence that spends it.

A **floor**, not a family: nine lowering families read it and it reads none of
them back, and inside `lowering/` a module a family imports has to sit below the
families (`ast/_primitives.py` is a floor for the same reason, one package
over).

Split out of `damage.py` at the 1,000-line guard, along the line CR 107.2/107.3
already draw: a printed quantity that is **counted** — off a board, out of the
resolution's own scratchpad, or off a cast the player picked — against the
sentence that spends it.

`_counted_damage.py` split back out of *this* module at Tempest's Phase 0, on
the second half of that same sentence. Every sentence here that **spent** a
count was a damage sentence — the cost channels, the difference, the board
count, the per-seat record, the chosen cast — so they went, and the counting
stayed, which is what this module's name has said since the first cut. What is
left is three readings of one quantity: what a count *is* (`count_spec`, and
the halving over it), how big a printed P/T change is, and where an X definition
is written onto the sentence that reads one.
"""

from ...oracle_types import OracleInstruction, X_FROM_COUNT
from .. import ast
from ..errors import LoweringError
from ._common import dropped_narrowings


# ---------------------------------------------------------------------------
# The count itself — the spec a resolution or a continuous recompute evaluates.
#
# Here rather than in `_common` for this module's own reason, and it is the
# reason the module exists: a printed quantity that is *counted* is CR
# 107.2/107.3's subject, and `_common` reached the thousand-line guard holding
# it. Every family that spends a count imports it from the floor that reads
# one.
# ---------------------------------------------------------------------------
# The zones a count can be taken over, and what may narrow it there. On the
# battlefield the ordinary object filter applies, because the counter asks
# `permanent_matches_filter` — the same question every target of the same words
# asks. In any other zone the objects are *cards*, which have no computed
# characteristics at all, so only the printed type union and a card's name are
# testable and anything else refuses rather than being counted as if it were
# not there.
# "the number of cards in their library" (Peer into the Abyss). The evaluator
# reads the zone off the owner by name, so the library needed no counting code —
# only saying so here. It is listed last because it is the one zone whose count a
# player cannot see, which changes nothing about the arithmetic and everything
# about what a *picker* built on the same spec could offer.
_COUNTABLE_ZONES = ("battlefield", "graveyard", "hand", "exile", "library")
# What a *card* in a hidden or public non-battlefield zone can be tested for.
# Held to `subject_filters.CARD_ONLY_FILTER_KEYS`, which is what the matcher
# behind the count actually answers: a key admitted here and unanswered there is
# a narrowing dropped on the floor, and a count that ignores its adjective is
# larger than the card printed.
_CARD_ZONE_KEYS = frozenset({"type_filter", "named", "color_filter"})

#: Narrowings a count cannot apply even on the battlefield. ``evaluate_count``
#: asks ``permanent_matches_filter`` — the *pure* half of the matcher — and a
#: keyword is CR 613 layer 6, which needs the game, so only ``subject_matches``
#: answers these two. Handed to the pure matcher they are keys nothing reads,
#: and a count that ignores its adjective is larger than the card printed.
#:
#: No card in the pool counts a keyword-narrowed set today, which is exactly why
#: this is here: the first one to print "the number of creatures with flying you
#: control" would otherwise count every creature and report itself supported.
_UNCOUNTABLE_FILTER_KEYS = frozenset({"with_keywords", "without_keywords"})


def count_spec(
    filt: "ast.ObjectFilter", node, *, aggregate: str = "count", multiplier: int = 1,
    offset: int = 0,
) -> dict:
    """What ``count_from_payload`` needs to take this count at resolution.

    One reader for both callers — the where-clause that *defines* an X and the
    amount that *is* one ("draw cards equal to the number of …"). They ask the
    same question of the same noun phrase, so a restriction one of them refused
    and the other silently dropped would be the same count meaning two things.
    """
    if filt.zone not in _COUNTABLE_ZONES:
        raise LoweringError(f"no count reads the {filt.zone}", node=node)
    payload = dict(filt.to_payload())
    # The same gate `_filter_payload` puts in front of every other consumer of a
    # noun phrase, and it was missing here: `to_payload` emits nothing for a
    # *relative* narrowing, so "for each creature **blocking it**" reduced to
    # "for each creature" and the count read the whole of its owner's
    # battlefield. A count that is too large is a pump that is too big — the
    # dropped-rider bug with an arithmetic face — so a narrowing with no payload
    # form refuses the sentence rather than widening it.
    #
    # `blocking_source` is the one such field a count *can* answer, carried
    # separately below the way `attached_to` is: it is a relation to one named
    # permanent, which the matcher cannot test and the evaluator resolves.
    dropped = tuple(
        field for field in dropped_narrowings(filt, payload)
        if field not in ("blocking_source", "on_the_battlefield")
    )
    if dropped:
        raise LoweringError(
            f"a count cannot test {', '.join(dropped)}", node=node
        )
    if filt.zone != "battlefield" and set(payload) - _CARD_ZONE_KEYS:
        raise LoweringError(
            f"a {filt.zone} count cannot test {sorted(set(payload) - _CARD_ZONE_KEYS)}",
            node=node,
        )
    uncountable = set(payload) & _UNCOUNTABLE_FILTER_KEYS
    if uncountable:
        raise LoweringError(
            f"a count cannot test {', '.join(sorted(uncountable))}", node=node
        )
    # Whose objects are counted is the *zone owner*, and the counter reads it
    # off there. A filter narrowing by controller as well ("the number of
    # Mountains **they** control") is asking a question the count cannot answer
    # — `permanent_matches_filter` does not test a controller, so the key would
    # be handed over and silently ignored, and the count taken on the wrong
    # player's battlefield. Refused rather than dropped.
    controller = payload.pop("controller", None)
    if controller not in (None, "you"):
        raise LoweringError(
            f"a count cannot be narrowed to the {controller}'s permanents", node=node
        )
    # "the number of green creatures **on the battlefield**" (An-Havva
    # Constable, An-Havva Inn). CR 403.1's one shared zone, which is the *whole*
    # of it and not one seat's share — and the default here is "you", so the
    # phrase has to be read or the card counts half a board. `owner: "all"` is
    # the spelling `evaluate_count` already uses for "in all graveyards"
    # (Lhurgoyf), so this is one more zone that answers to it rather than a
    # second vocabulary for the same idea.
    #
    # Two scopes in one phrase would name two different sets, so a filter that
    # says both refuses instead of picking: "creatures you control on the
    # battlefield" is not a card, and reading it as either half would be
    # reading a card nobody printed.
    if filt.on_the_battlefield:
        if filt.zone != "battlefield" or controller is not None or filt.zone_owner:
            raise LoweringError(
                "a count cannot be scoped to the battlefield and to a player",
                node=node,
            )
        owner = "all"
    else:
        owner = filt.zone_owner.kind if filt.zone_owner else "you"
    # "…for each **blocking** creature other than Márton Stromgald." A combat
    # role is a property of the *battlefield*, not of a controller, and the seat
    # that asks is not necessarily the seat the objects are on — so a phrase
    # narrowed to one and scoped to nobody counts every seat, exactly as
    # `blocking_source` below settles which pile it reads for the same reason.
    #
    # Both halves of the rule have a card behind them. CR 509.1a and CR 802.2
    # give a multiplayer game **several** defending players, each declaring
    # blockers from creatures they control, so "each blocking creature" spans
    # seats: at a three-seat table with two blockers beside it, Márton counted
    # one. And CR 508.1a puts every attacker on the *active* player's
    # battlefield, which is the one seat a defending player's card counting
    # attackers would not read — `owner: "you"` answers zero there.
    #
    # The `all` reading is what the sentence's other reader already uses:
    # `buff_creatures_global` takes the same printed noun phrase over every
    # seat, so leaving the count seat-scoped had one clause meaning two sets.
    if owner == "you" and not filt.zone_owner and controller is None:
        if payload.get("blocking_only") or payload.get("attacking_only"):
            owner = "all"
    spec: dict = {
        "zone": filt.zone,
        "owner": owner,
        "filter": payload,
    }
    # "the number of Auras **attached to it**" (Rabid Wombat). A relation to one
    # named permanent, not a property of each object, so it rides the spec
    # rather than the filter — ``permanent_matches_filter`` cannot test it, and
    # a key handed to that matcher is a key silently ignored. It also settles
    # *which pile* is counted: what is attached to a permanent is recorded on
    # that permanent, so the count is not a battlefield scan and does not
    # inherit the owner scope above (an opponent's Aura on your creature is
    # attached to your creature).
    if filt.attached_to is not None:
        if filt.attached_to != "source":
            raise LoweringError(
                f"no count resolves an attachment to the {filt.attached_to}",
                node=node,
            )
        spec["attached_to"] = filt.attached_to
    # "…for each creature **blocking it** beyond the first" (Johtull Wurm).
    # A relation to the ability's own source (CR 509.1a), not a property of
    # each creature counted — so it rides the spec beside `attached_to` for
    # that key's reason exactly, and it also settles which pile is counted: a
    # blocker is on the *defending* player's battlefield, which the owner scope
    # above would have read as the source controller's.
    if filt.blocking_source:
        spec["blocking_source"] = True
        # …and out of the filter it is now emitted into. The evaluator resolves
        # the relation itself (it holds the source and the combat maps) and
        # then tests each blocker with the *pure* matcher, which has no key for
        # it — so a copy left inside would be a key nothing reads, and every
        # count spec written before the key existed would move. Lifted rather
        # than left redundant, so `oracle_diff` stays quiet about cards this
        # change is not about.
        payload.pop("blocking_source", None)
    # Omitted when it is the default, so every spec written before aggregates
    # existed is byte-identical.
    if aggregate != "count":
        spec["aggregate"] = aggregate
    # "**Twice** the number of white creatures that player controls" (Jovial
    # Evil). Carried on the spec rather than folded into whatever reads it,
    # because the same spec is read by the resolution-time evaluator and by the
    # continuous recompute — a factor applied in one of them would make the
    # same printed count mean two numbers. Omitted at 1, for the reason the
    # aggregate is: an untouched spec stays byte-identical.
    if multiplier != 1:
        spec["multiplier"] = multiplier
    # "…for each creature blocking it **beyond the first**" (Johtull Wurm).
    # Applied where the multiplier is, and for its reason: one place scales
    # every aggregate, and an offset honoured at one of the evaluator's return
    # sites and forgotten at the rest is the dropped-rider bug with an
    # arithmetic face. Omitted at 0 so an untouched spec stays byte-identical.
    if offset:
        spec["offset"] = offset
    return spec


def halved_count_spec(amount: "ast.Amount", node) -> dict | None:
    """The spec for a computed amount that may be halved, or None if it is not one.

    "Half the number of cards in their library" and "half their life" (Peer into
    the Abyss) are the same shape: something the resolution computes, divided,
    and rounded. So the halving rides on the *spec* rather than becoming a second
    amount vocabulary — one evaluator still answers, which is the rule round 64
    wrote down when the pump handler was found carrying its own counter.

    A player's life total is not a pile to scan, so it arrives as a *named* board
    count rather than a filter: ``evaluate_count`` maps the name onto the one
    thing that computes it and answers 0 for a name it has no computation for,
    which is why the name is minted here and nowhere else.
    """
    rounding = None
    divisor = 2
    if isinstance(amount, ast.Half):
        rounding = amount.rounding
        divisor = amount.divisor
        amount = amount.of
    if isinstance(amount, ast.CountOf):
        spec = count_spec(amount.filter, node)
    elif isinstance(amount, ast.BoardCount) and amount.name == "their_life":
        spec = {"board_count": "their_life", "owner": "target"}
    else:
        return None
    if rounding is not None:
        spec["half"] = rounding
        # "a third of their life" (Pox). Omitted at 2 so every spec written
        # before fractions existed stays byte-identical; see `ast.Half`.
        if divisor != 2:
            spec["divide_by"] = divisor
    return spec


# ---------------------------------------------------------------------------
# How big a printed P/T change is.
#
# Beside the count itself, and for the same reason: "+1/+1 **for each** …",
# "+X/+0 **where X is** …" and "…**beyond the first**" are three spellings of
# one quantity, and `lowering/characteristics.py` reached the thousand-line
# guard holding them. They read the count spec above and nothing reads them
# back, which is what makes them floor rather than family.
# ---------------------------------------------------------------------------
def x_offset_amount(amount: ast.Amount) -> dict | None:
    """``{"plus_x": n}`` for "**X plus n**", or None when the amount is not one.

    "You gain X plus 1 life, where X is the number of green creatures on the
    battlefield." (An-Havva Inn.) The constant belongs to the *sentence that
    spends* the quantity, not to the count that defines it — a card printing
    the same "plus 1" over a different where-clause is this shape — so it rides
    the amount payload rather than the count spec, exactly as ``{"times_x": n}``
    beside it does and for the reason that key gives: one spec may feed two
    halves scaled differently.

    ``resolve_amount`` is the one reader, so the arithmetic happens where every
    other amount's does. Returns None rather than raising, so a caller that has
    no branch for it keeps the refusal it already had — which is every caller
    but the one family with a card printing the words.
    """
    if (
        isinstance(amount, ast.Plus)
        and isinstance(amount.left, ast.Var)
        and isinstance(amount.right, ast.Fixed)
    ):
        return {"plus_x": amount.right.value}
    return None


def _static_x_amount(amount: ast.Amount, negative: bool, node) -> int | str:
    """One half of a computed static bonus: the string "x" or a literal.

    A negated X refuses. The refresh resolves the amount against the computed
    value and nothing carries a sign for it, so admitting "-X/-0" here would be
    a bonus applied with the wrong sign — the direction that makes a creature
    bigger when the card shrinks it.
    """
    if isinstance(amount, ast.Var):
        if negative:
            raise LoweringError("a static computed bonus cannot be negative", node=node)
        return "x"
    if isinstance(amount, ast.Fixed):
        return -amount.value if negative else amount.value
    raise LoweringError("a static computed bonus needs X or a number", node=node)


def _per_each_amount(amount: ast.Amount, negative: bool, node) -> dict | int:
    """One half of a "for each" bonus: how much *each* repetition is worth.

    ``{"times_x": n}`` is what ``resolve_amount`` multiplies by the count. A
    printed 0 stays a plain 0 — nothing times a count is still nothing, and the
    literal keeps every payload written before this existed byte-identical.
    """
    if not isinstance(amount, ast.Fixed):
        raise LoweringError(
            'a "for each" bonus needs a printed number to repeat', node=node
        )
    value = -amount.value if negative else amount.value
    return {"times_x": value} if value else 0


def _x_definition_spec(definition: ast.Amount, node) -> dict:
    """The spec behind a where-clause's X, whichever aggregate it names."""
    # "…, where X is **half** the creature's power, **rounded down**."
    # (Catacomb Dragon.) The halving rides on the spec rather than on the
    # definition, so every alternative below carries it without knowing it can
    # — `_scaled` is the one place that applies it, the same arrangement the
    # multiplier and the offset already have. Unwrapped first because it is not
    # a definition at all: it is an arithmetic over whichever one follows.
    if isinstance(definition, ast.Half):
        spec = _x_definition_spec(definition.of, node)
        spec["half"] = definition.rounding
        # Omitted at 2, so every spec written before fractions existed stays
        # byte-identical (see `ast.Half`).
        if definition.divisor != 2:
            spec["divide_by"] = definition.divisor
        return spec
    if isinstance(definition, ast.GreatestPowerAmong):
        return count_spec(definition.filter, node, aggregate="greatest_power")
    if isinstance(definition, ast.ColorsAmong):
        return count_spec(definition.filter, node, aggregate="distinct_colors")
    if isinstance(definition, ast.CountOf):
        return count_spec(definition.filter, node)
    if isinstance(definition, ast.CharacteristicOfSubject):
        # "…, where X is **its** mana value" (Great Defender, Subdue, Kry
        # Shield), "…, where X is **its toughness minus 1**" (Blood Lust). Not
        # an aggregate over a set: the object is the one the sentence already
        # named, and the resolution reads the characteristic off it — mana
        # value off the card (CR 202.3), power and toughness through the layers
        # (CR 613), which is the resolution's business rather than this one's.
        return {
            "object_characteristic": {
                "object": "target",
                "characteristic": definition.characteristic,
                "offset": definition.offset,
            }
        }
    raise LoweringError("only a count or a maximum can define X here", node=node)


def _per_each_offset(node: ast.Pump) -> int:
    """"…beyond the first" as the count spec's offset."""
    return -1 if node.per_each_beyond_first else 0


# ---------------------------------------------------------------------------
# The other end of a computed quantity: the sentence that spends it.
#
# Moved here from ``_common`` at the thousand-line guard, along the line this
# module's own docstring already draws. These two are read by
# ``lowering/where_x.py`` and by nothing else, and what they do is the "against
# the sentence that spends it" half of CR 107.3: one asks whether the sentence
# reads an X at all, the other writes the definition onto every step of it.
# ``count_spec`` above answers what the quantity *is*; these answer where it
# goes. `_common` is the module every family imports, so a pair with one caller
# and one subject belongs in the floor that owns the subject.
# ---------------------------------------------------------------------------

def _stamp_x_from_count(
    instructions: tuple[OracleInstruction, ...], spec: dict
) -> tuple[OracleInstruction, ...]:
    """Put *spec* on every instruction, including the steps nested inside one.

    A sentence lowers to a tuple, and a wrapper (`sequence`, `if_then`, `may`)
    carries its own steps in its payload — so stamping the top level alone would
    define X for the outer instruction and leave the inner ones reading the
    cast's X, which for a triggered ability is None.
    """
    stamped = []
    for instruction in instructions:
        payload = dict(instruction.payload)
        if X_FROM_COUNT in payload and payload[X_FROM_COUNT] != spec:
            # One resolution has one X (`context.x_value`), so a sentence whose
            # where-clause defines one *and* whose amount is a count of its own
            # ("draw cards equal to the number of …, where X is …") would have
            # the two silently overwrite each other. Neither reading is the
            # card, so the line refuses.
            raise LoweringError("two counts cannot share one X")
        payload[X_FROM_COUNT] = spec
        for key in ("steps", "then", "else", "otherwise", "action"):
            nested = payload.get(key)
            if isinstance(nested, tuple) and nested and isinstance(nested[0], OracleInstruction):
                payload[key] = _stamp_x_from_count(nested, spec)
        stamped.append(OracleInstruction(instruction.kind, instruction.value, payload))
    return tuple(stamped)


#: Amount-payload keys whose *value* is a printed constant and whose meaning is
#: an arithmetic on X. Named rather than inferred from a suffix, because what
#: makes a key one of these is that ``handlers/_common.resolve_amount`` reads
#: the X for it — and a key added here that resolver does not read is an
#: instruction reporting itself computed and resolving to a literal.
_X_ARITHMETIC_KEYS = frozenset({"times_x", "plus_x"})


def _mentions_x(instructions: tuple[OracleInstruction, ...]) -> bool:
    """Whether anything in *instructions* actually reads an X.

    Most amounts carry the literal string; ``unless_pays_x`` is the one that
    says so with a flag instead ("counter it unless that player pays {X}"), and
    it is named here because a where-clause over that sentence is a real card
    (In the Eye of Chaos) that would otherwise be refused for defining an X
    nothing reads.
    """
    for instruction in instructions:
        if instruction.payload.get("unless_pays_x"):
            return True
        for key, value in instruction.payload.items():
            if value == "x":
                return True
            # A cost is a symbol dict, so its X sits one level down —
            # "you may pay {X}" lowers to ``{"generic": "x"}``. Read here rather
            # than by naming the ``cost`` key, because what makes it an X is the
            # amount, not which key carries it.
            if isinstance(value, dict) and "x" in value.values():
                return True
            # An amount that does *arithmetic* on X carries the number instead
            # of the letter: ``{"times_x": n}`` for a "for each" repetition,
            # ``{"plus_x": n}`` for "X plus 1 life" (An-Havva Inn). Both read
            # the X, so a where-clause over either is defining one that *is*
            # read — refusing them would refuse the card that prints the words.
            if isinstance(value, dict) and set(value) & _X_ARITHMETIC_KEYS:
                return True
            if isinstance(value, tuple) and value and isinstance(value[0], OracleInstruction):
                if _mentions_x(value):
                    return True
    return False

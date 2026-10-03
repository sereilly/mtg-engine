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

import dataclasses

from ...oracle_types import OracleInstruction, TAPPED_THIS_WAY, X_FROM_COUNT
from .. import ast
from ..errors import LoweringError
from ._common import dropped_narrowings
from ._cost_records import cost_record_spec
from ._events import _EVENT_SUBJECT_PLAYERS, EVENT_SUBJECT_PLAYER


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

#: Narrowings a count cannot apply even on the battlefield.
#:
#: It held ``with_keywords`` and ``without_keywords`` while ``evaluate_count``
#: asked ``permanent_matches_filter`` — the *pure* half of the matcher, which
#: cannot answer a keyword (CR 613 layer 6 needs the game). The battlefield
#: scan asks ``subject_matches`` now, so both are answered where they used to
#: be dropped, and the one card that counted a keyword-narrowed set
#: (Aven Gagglemaster) stopped needing a hand-built payload of its own.
#:
#: Empty rather than deleted: it is the place a key goes when the matcher
#: behind the count cannot test it, and a count that ignores its adjective is
#: larger than the card printed. The non-battlefield zones have their own,
#: stricter list (``_CARD_ZONE_KEYS``) — a card in a graveyard has no computed
#: characteristics at all.
_UNCOUNTABLE_FILTER_KEYS: frozenset[str] = frozenset()

#: How a count is *scoped* when the printed noun phrase narrows it to a player
#: the spell targets — "the number of black permanents **target opponent**
#: controls" (Reap, Superior Numbers' subtrahend).
#:
#: A **scope** rather than a filter key, for this function's own stated reason
#: one comment down: nothing downstream tests a ``controller`` key on a count,
#: so a count narrowed by one is a count taken on the wrong battlefield. And its
#: own value rather than the plain ``"target"`` beside it because CR 102.3 says
#: a player is never their own opponent: the resolution's fallback seat is not
#: necessarily one, and this scope is what tells ``count_from_payload`` to skip
#: past the caster when the announcement did not name a seat.
#:
#: Defined **here**, in the floor, and imported by ``_counted_damage`` — it was
#: written there when Superior Numbers was the only card that needed it, and a
#: family cannot be imported by the floor every family reads. Two spellings of
#: one scope would be two answers to "whose board is this?".
TARGET_OPPONENT_SCOPE = "target_opponent"

#: How a count is scoped when the printed noun phrase narrows it to *every*
#: seat but the counting one — "the number of permanents of the chosen color
#: **your opponents control**" (Chameleon Spirit).
#:
#: The scope's twin above names one seat a spell picked; this one names a set
#: the rules define (CR 102.1), so nothing is announced and nothing has to be
#: resolved — but it is still a scope rather than a filter key, and for a reason
#: the ``target_opponent`` comment one paragraph up only half states. What the
#: evaluator needs from it is **two** answers that ``owner`` used to give as
#: one: which piles to scan, and whose "you" the filter's seat words are
#: relative to. ``"all"`` answers both with nobody, which is right for CR 403.1's
#: shared battlefield and wrong here; this answers the first with everybody and
#: the second with the counting seat, and leaves the narrowing itself in the
#: filter where ``subject_matches`` reads it — the same key, the same reader, as
#: anywhere else the phrase is printed.
#:
#: The three printed spellings — "your opponents control", "each opponent
#: controls", "an opponent controls" — all reach ``ObjectFilter.controller`` as
#: the one value ``"opponent"``, which means "controlled by a seat that is not
#: the observer". Counting every permanent that answers to it *is* the union of
#: every opponent's board, so the first two readings are exact and the third
#: (which no count in the pool prints, and which Magic templates as one of the
#: other two) is read as the same union rather than as an unanswerable "some
#: one of them".
OPPONENTS_SCOPE = "opponents"

#: The ``ObjectFilter.controller`` value the scope above is lifted from.
_OPPONENT_CONTROLLER = "opponent"


def count_filter_on_frozen_seat(
    filt: "ast.ObjectFilter", event: str | None, node
) -> "ast.ObjectFilter":
    """*filt* with a "that player controls" narrowing moved onto the axis a
    count reads — whose zone is scanned — when the firing event froze the seat.

    "…where X is the number of nontoken permanents of the chosen color **they
    control**" (Psychic Allergy) and "…put a charge counter on this enchantment
    for each untapped land **that player controls**" (Mana Cache) are one
    quantity: the event's player (CR 603.10), frozen by the fire site under the
    key every "that player" reader asks. ``count_spec`` refuses a controller
    key outright — the matcher behind a count tests no controller — so the
    restriction rides ``zone_owner`` instead, which ``count_from_payload``
    resolves to that seat.

    Here rather than in the where-clause lowering that had it, because a counter
    placement asks the same question from a floor that cannot import a family —
    and two copies of the rewrite would be two answers about which events froze
    a seat. Refuses under an event that froze none: "that player" there points
    at nobody, and the count would fall back to the caster's board while the
    card compiled clean.

    A filter that does not name the seat comes back unchanged.
    """
    if filt.controller != "that_player":
        return filt
    if event not in _EVENT_SUBJECT_PLAYERS:
        raise LoweringError(
            "'that player' in a count with no player target to name", node=node
        )
    return dataclasses.replace(
        filt, controller=None, zone_owner=ast.PlayerRef(EVENT_SUBJECT_PLAYER),
    )


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
    # "…the number of black permanents **target opponent** controls" (Reap).
    # The one narrowing that is not dropped but *lifted*: it names a seat rather
    # than a property of each object, and `count_from_payload` has resolved that
    # seat since Superior Numbers — so it becomes the spec's ``owner`` below,
    # where the evaluator reads it, instead of a filter key nothing tests.
    #
    # Reachable on the battlefield alone, and by construction rather than by a
    # second condition: a count in any other zone refuses a ``controller`` key
    # outright at the `_CARD_ZONE_KEYS` gate above, before this line runs.
    # "…the number of nonbasic lands **defending player** controls" (Mercadia's
    # Downfall). The second narrowing that is lifted rather than dropped, and
    # for the target-opponent branch's reason exactly: it names a *seat* rather
    # than a property of each object, and ``count_from_payload`` resolves that
    # seat through ``defending_player_seat`` — the one reader of CR 506.2's
    # player. Left in the filter it would be handed to a matcher that does not
    # test a controller and silently counts the whole table's lands.
    if controller not in (
        None, "you", TARGET_OPPONENT_SCOPE, _OPPONENT_CONTROLLER,
        "defending_player",
    ):
        raise LoweringError(
            f"a count cannot be narrowed to the {controller}'s permanents", node=node
        )
    if controller == TARGET_OPPONENT_SCOPE and filt.zone_owner is not None:
        # Two seats in one phrase name two different sets, exactly as the
        # battlefield-scope branch below says of its pair. Refused rather than
        # resolved to either half.
        raise LoweringError(
            "a count cannot be scoped to a target opponent and to a zone's owner",
            node=node,
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
        # "the number of cards named ~ in **all graveyards**" (Kindle). The
        # seat-set kind the noun phrase carries, translated once here into the
        # ``owner: "all"`` spelling `evaluate_count` has answered since Lhurgoyf
        # — the same key the branch above writes for "on the battlefield", so
        # one scope has one word in the spec however the card printed it.
        # Translated rather than passed through: every other value of this key
        # is a seat the resolution resolves, and `each_player` reaching
        # `count_from_payload` unrecognised falls to `context.target or
        # context.caster`, which is one player's graveyard read as everyone's.
        if owner == "each_player":
            owner = "all"
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
    # The lift the controller gate above admitted. Written after the zone-owner
    # reading rather than in place of it so the refusal beside it stays the only
    # way two seats can be named at once.
    if controller == TARGET_OPPONENT_SCOPE:
        owner = TARGET_OPPONENT_SCOPE
    # The same lift for CR 506.2's seat, and it has to come after the combat-role
    # widening above rather than before it: "each nonbasic land **defending
    # player** controls" is scoped to a seat even though the *pumped* subject is
    # an attacking class, and the `all` reading would count both boards' lands.
    elif controller == "defending_player":
        owner = "defending_player"
    # The second lift, and the one that keeps its key. "…the number of permanents
    # of the chosen color **your opponents control**" (Chameleon Spirit): the
    # scope says which piles to scan and the *filter* still says which of the
    # permanents in them count, because "not the observer's" is a question
    # ``subject_matches`` already answers for every other sentence that prints
    # it. Dropping the key here and scoping alone would work only while the
    # scope and the narrowing agree — they do today and would not the moment a
    # phrase pairs "your opponents control" with anything the scan cannot
    # express — so the key is put back rather than trusted to the scope.
    elif controller == _OPPONENT_CONTROLLER:
        owner = OPPONENTS_SCOPE
        payload["controller"] = controller
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


def seat_scoped_count_spec(
    filt: "ast.ObjectFilter", node, *, multiplier: int = 1
) -> dict | None:
    """The count spec for a noun phrase narrowed to **the recipient's** seat —
    "…the number of Islands **that player** controls" (Typhoon), "…for each
    creature **they** control" (Stronghold Discipline) — or None when the
    phrase names no such seat.

    One number per recipient, so the spec is read by a handler that loops its
    recipients and hands ``evaluate_count`` each seat directly: the controller
    narrowing is stripped before :func:`count_spec` sees it (nothing downstream
    tests a controller key on a count, which is why that function refuses one)
    and the scope is the loop. ``owner`` is dropped rather than left saying
    "you", which is the one seat the phrase certainly does not mean.

    On the floor because two families spend it: a damage sweep
    (``_counted_damage._recipient_seat_count``) and a life loss
    (``life._lower_lose_life``). It was the damage family's alone until the
    second sentence arrived, and a second copy would be two answers to "whose
    board does *they* name?".
    """
    if filt.controller != "that_player":
        return None
    if filt.zone_owner is not None:
        # The phrase would then name two different players — the zone's owner
        # and "that player" — and only one of them can be the recipient.
        raise LoweringError(
            "a per-recipient count cannot also name a zone owner", node=node
        )
    spec = count_spec(
        dataclasses.replace(filt, controller=None), node, multiplier=multiplier
    )
    spec.pop("owner", None)
    return spec


def recorded_count_spec(
    amount: "ast.Amount", produced: frozenset[str], node
) -> dict | None:
    """The ``x_from_count`` spec for a quantity an earlier step of this same
    effect **recorded**, or None when *amount* is not one.

    "For each card discarded this way, put **two** +1/+1 counters on this
    creature." (Mind Maggots.) The third of this module's three readings of a
    printed quantity: :func:`count_spec` counts a board, ``_counted_damage``
    reads a cast, and this reads the resolution's own scratchpad — which is the
    sentence the module docstring has named since the first cut and the only one
    that had no reader.

    :class:`ast.Times` is unwrapped here rather than by each caller, for the
    reason ``lower_where_x`` unwraps it: "two counters **for each** card" is one
    number, and a factor honoured by one spender and dropped by the next is the
    dropped-rider bug with an arithmetic face. It lands on ``multiplier``, which
    ``handlers/_common._scaled`` already applies to every aggregate — so the
    arithmetic is the same one place that halves a count and offsets it.

    **The words must name their producer, and a step of this effect must be it.**
    A bare "that many" names nothing the parser can see (``ast.ThatMuch``'s own
    docstring), so it is left to the caller's own reading; a named one with no
    producer would be answered 0 by ``count_from_payload`` — a card that reports
    supported and places no counters at all, which is precisely the shape this
    gate exists to refuse.
    """
    multiplier = 1
    if isinstance(amount, ast.Times):
        multiplier = amount.factor
        amount = amount.of
    if not isinstance(amount, ast.ThatMuch) or amount.source is None:
        return None
    if amount.bonus:
        # "…equal to its power **plus 2**" over a recorded count. The channel
        # carries a `plus`, but no card prints one here and admitting it
        # untested would be a number nothing has ever checked.
        raise LoweringError(
            "a recorded count carries no printed bonus", node=node
        )
    if amount.source not in produced:
        raise LoweringError(
            f"back-reference to {amount.source!r} with no producer in this "
            "effect", node=node,
        )
    spec: dict[str, object] = {"back_reference": amount.source}
    if multiplier != 1:
        # Omitted at 1, for the reason `count_spec` omits its own: a spec
        # written before the factor existed stays byte-identical.
        spec["multiplier"] = multiplier
    return spec


def tapped_this_way_record(filt: "ast.ObjectFilter", produced, node) -> str:
    """The record "the number of <noun> **tapped this way**" reads, or a refusal.

    "…, where X is the number of Islands tapped this way" (Monsoon) and "…deals
    damage to the player equal to the number of creatures tapped this way"
    (Angel's Trumpet) are the same quantity in the two printed positions a
    quantity can occupy, so they ask one reader. Written twice they would
    eventually disagree, and the direction that fails is silent: the where-clause
    form refuses a narrowing and the "equal to" form, had it grown its own copy,
    would have been free to admit one.

    Two refusals, both of them the fourth idiom's:

    * **Only the bare head noun.** What the tap recorded is a *number*, not the
      set, so a narrower noun phrase would be counted as though the narrowing
      were not there. The sweep's own narrowings ("untapped", "that player
      controls", "that didn't attack this turn") are exactly the ones the card
      leaves off the counting clause, which is why the head noun is enough.
    * **A step of this same effect must have tapped something.** What the board
      now holds tapped is not what this effect turned — a creature that was
      already tapped is not one the sweep tapped, and CR 611.2c fixed the set
      when the effect began — so with no producer the words name nothing and the
      count would be a zero the card never printed.

    A floor rather than a helper in either family, for this module's own reason:
    ``lowering/where_x`` and ``lowering/damage`` both ask it and neither may
    import the other.
    """
    described = filt.to_payload()
    if filt.zone != "battlefield" or set(described) - {
        "type_filter", "subtype_filter"
    } or len(described) != 1:
        raise LoweringError(
            "'tapped this way' counts what the earlier step tapped and cannot "
            "be narrowed further", node=node,
        )
    if TAPPED_THIS_WAY not in produced:
        raise LoweringError(
            "'tapped this way' with no earlier step in this effect that tapped "
            "anything", node=node,
        )
    return TAPPED_THIS_WAY


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


def _x_definition_spec(
    definition: ast.Amount, node, *, recorded: "frozenset[str] | None" = None
) -> dict:
    """The spec behind a where-clause's X, whichever aggregate it names.

    *recorded* is the set of scratchpad keys steps of this same effect write,
    and passing one admits a back-reference — "…, where X is the number of
    cards **revealed this way**" (Ivy Seer, Nightshade Seer and their two
    Scents). ``None`` means no back-reference may define an X here at all, and
    it is the default because the two callers ask different questions of one
    helper. A **durational** pump is evaluated once, at resolution, where the
    record the reveal wrote is sitting in the scratchpad; a durationless one is
    a CR 613 layer 7c contribution the P/T refresh rebuilds on every recompute,
    and a scratchpad key is not there to be read the second time. A continuous
    effect sized by a frozen record is the failure
    ``characteristics._lower_pump_per_milled`` refuses in its own words.

    One parameter rather than a flag beside a set, because the two questions
    are one: may a record define this X, and which records exist. A caller that
    answered the first and not the second would admit a clause naming a step
    nothing performs, which is a pump of zero on a card reporting supported.
    """
    # "…, where X is **half** the creature's power, **rounded down**."
    # (Catacomb Dragon.) The halving rides on the spec rather than on the
    # definition, so every alternative below carries it without knowing it can
    # — `_scaled` is the one place that applies it, the same arrangement the
    # multiplier and the offset already have. Unwrapped first because it is not
    # a definition at all: it is an arithmetic over whichever one follows.
    if isinstance(definition, ast.Half):
        spec = _x_definition_spec(definition.of, node, recorded=recorded)
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
    if isinstance(definition, ast.CountersOnSource):
        # "…, where X is the number of **verse counters on this enchantment**"
        # (War Dance, and the four other verse cards Urza's Saga prints). Not an
        # aggregate over a set either: a counter is not an object, so there is
        # no zone to scan — what the words name is a number sitting on the
        # ability's own source, which only a resolution knows.
        #
        # The same ``source_counters`` spec ``where_x._lower_where_x_counters``
        # and ``cards._lower_draw`` already build for the identical phrase in
        # their own word orders, so the one evaluator answers all three and the
        # spellings cannot count differently. It reaches here rather than there
        # because a P/T where-clause carries its definition on the ``Pump``
        # node instead of wrapping the sentence in a ``WhereX``.
        #
        # Reading it off a *sacrificed* source is CR 608.2h's last known
        # information and needs no code: the counters live in the permanent
        # object's own metadata (``engine/named_counters.py``), and a cost that
        # sacrificed it took it off the battlefield without destroying the
        # object the resolution still holds.
        return {"source_counters": definition.kind}
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
    # "{1}{B}, Discard a creature card: Volrath the Fallen gets +X/+X until end
    # of turn, where X is **the discarded card's mana value**." A quantity the
    # ability's own *cost* recorded (CR 601.2h), read off the payment path's
    # record at resolution — so only where a resolution reads this spec at all
    # (``recorded`` set): a durationless pump is a layer-7c contribution the
    # P/T refresh rebuilds with no resolution context, where no payment record
    # exists to be read.
    if recorded is not None:
        paid = cost_record_spec(definition, node)
        if paid is not None:
            return paid
    if recorded is not None and isinstance(definition, ast.ThatMuch):
        # "…, where X is the number of cards **revealed this way**." The parse
        # resolved the printed noun and participle against
        # ``records._THIS_WAY_COUNTS`` and what arrives is the key, so this
        # reads it onto the ``back_reference`` channel ``count_from_payload``
        # already answers — the same one the damage and the life gain spend the
        # identical clause on, so one evaluator answers all three.
        #
        # A printed bonus refuses: "…plus one" over a record is arithmetic this
        # spec has no key for, and dropping it is a pump one smaller than the
        # card.
        if definition.source is None or definition.bonus:
            raise LoweringError(
                "a recorded X names its producer and carries no bonus", node=node
            )
        if definition.source not in recorded:
            # The gate every back-reference in this grammar carries: with no
            # step in front of it the words name nothing, and the spec would be
            # answered 0 — a card that reports supported and pumps by nothing.
            raise LoweringError(
                f"back-reference to {definition.source!r} with no producer in "
                "this effect", node=node,
            )
        return {"back_reference": definition.source}
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

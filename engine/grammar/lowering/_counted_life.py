"""How much life a **gain** computes, and the ceiling on it.

A **floor**, not a family: ``life.py`` reads it and it reads nothing back --
inside ``lowering/`` a module a family imports has to sit below the families,
which is ``_counted_damage``'s reason and ``_counted_pumps``' after it.

Pre-split out of ``life.py`` at the Phase 0 between Invasion's two waves, with
that module 21 lines under the 1,000-line guard and nobody owning it, along
exactly the line those two floors were cut on -- the one ``_amounts`` was
itself cut on: a printed quantity that is **counted**, off a board or out of
the resolution's own scratchpad, **against the sentence that spends it**.
``_amounts`` keeps the quantity (``count_spec`` and the readers beside it);
every reading of ``_lower_gain_life`` whose *size* is read off something
rather than printed is here. The third of the pattern, one rule over again: CR
119.3's gain, after CR 120's damage and layer 7c's modification.

Three names -- the two ways a gain prints a size it does not state, and the
bound on one of them:

* ``lower_counted_gain`` -- "you gain life **equal to** …". The amount is read
  off something: a characteristic the fire site froze as the creature died, the
  bound creature's power, the mana value of the object a loop is on, the
  permanent a cost sacrificed, a recorded count at a printed rate, the bare
  back-reference, a board count, the source's counters, the payments made.
* ``lower_per_each_gain`` -- "you gain N life **for each** …". A printed rate
  times a count: the turn's death tally, this effect's own sacrifices, the
  counters a cost removed, the counters on the source, a counted zone.
* ``_life_gain_cap_payload`` -- "…**but not more than** …". Here rather than
  with the seats because it is part of how much life the gain is and of
  nothing else: only a back-referenced gain can carry one, and the function
  refuses on behalf of every reading that cannot.

**Nothing here chooses a seat.** ``life._lower_gain_life`` settles who gains
before it asks either reader and hands the answer down, so a branch here may
*refuse* a seat it cannot serve and may count against the one it was given,
and that is all. The printed number stays behind with the seats: both readers
return None for a sentence that has not reached its reading yet, which is
``lower_counted_pump``'s contract with ``_lower_pump`` and for its reason.

A **loss**'s counted readings are not here, and that was measured rather than
left over. Every one of them names the losing seat as it counts -- whose life
is halved, whose battlefield, whose graveyard -- so in ``_lower_lose_life`` the
two questions do not come apart with one parameter between them.

What left is the half that **grows with the pool**, the playbook's tiebreak
when both halves are dispatch: of the 372 lines ``life.py`` had gained and kept
since it left ``game``, 219 were one more printed shape of a gain's amount and
64 were a seat, a gain's or a loss's.
"""

from ...oracle_types import OracleInstruction, X_FROM_COUNT
from .. import ast
from ..errors import LoweringError
from ._amounts import (count_filter_on_frozen_seat, count_spec,
                       printed_count_spec, recorded_count_spec)
from ._common import (
    dropped_narrowings,
    _amount_payload,
    _restrictions_beyond,
)
from ._cost_records import optional_cost_key
from ._counted_damage import _READABLE_COST_SACRIFICE_CHARACTERISTICS
from ._deaths import DEAD_CHARACTERISTIC_EVENTS, DEAD_CHARACTERISTIC_RECORDS
from ._events import (
    LOOP_BOUND_OBJECT,
    DAMAGE_RECIPIENT,
    EVENT_SUBJECT_PLAYER,
    _back_reference_payload,
)


def _life_gain_cap_payload(
    node: ast.GainLife, produced: frozenset[str]
) -> dict[str, object]:
    """"…but not more than A, B, C, or D" as payload, or ``{}``.

    The three recipient terms fold into one entry carrying *which kinds of
    recipient* they named, because the engine answers them with one number —
    what the damaged object could absorb before the damage — and which of the
    three that number means is a fact about the target, not about the sentence.
    The kinds are kept so a card printing only "the creature's toughness" does
    not cap a gain from damaging a player.

    Refused rather than dropped when nothing in this effect recorded the
    recipient: a cap the handler cannot read would gain the uncapped amount,
    which is the failure this whole clause exists to prevent.
    """
    if not node.capped_by:
        return {}
    if not isinstance(node.amount, ast.ThatMuch):
        raise LoweringError(
            "a capped life gain reads back what an earlier step dealt", node=node,
        )
    terms: list[dict[str, object]] = []
    recipients = tuple(
        cap.recipient for cap in node.capped_by
        if cap.kind == "recipient_capacity" and cap.recipient
    )
    if recipients:
        if DAMAGE_RECIPIENT not in produced:
            raise LoweringError(
                "a cap on the damaged object's life, loyalty or toughness needs "
                "a step of this effect that damaged one",
                node=node,
            )
        terms.append({"kind": "recipient_capacity", "recipients": list(recipients)})
    for cap in node.capped_by:
        if cap.kind == "mana_spent_on_x":
            # "the amount of {B} spent on X" — a fact about the *cast*, carried
            # on the stack item by the payment that chose the split, not about
            # anything an earlier instruction did. So there is no producer to
            # gate on here; a resolution with no such record caps the gain at
            # zero, which is the safe direction.
            terms.append({"kind": "mana_spent_on_x", "symbol": cap.symbol})
    unknown = {cap.kind for cap in node.capped_by} - {
        "recipient_capacity", "mana_spent_on_x",
    }
    if unknown:
        raise LoweringError(
            f"no reader for life-gain cap {sorted(unknown)!r}", node=node,
        )
    return {"capped_by": terms}


def lower_counted_gain(
    node: ast.GainLife,
    recipient: str,
    cap_payload: dict[str, object],
    produced: frozenset[str],
    event: str | None,
) -> tuple[OracleInstruction, ...] | None:
    """A gain whose amount is **read off something** -- "equal to …" -- or
    None for one whose amount is printed.

    None rather than a refusal, for ``lower_counted_pump``'s reason: this is
    the head of ``life._lower_gain_life``'s chain and not the whole of it. A
    gain of a printed number, or of a printed rate "for each …" (which
    ``lower_per_each_gain`` reads next), has simply not reached its reading yet.

    ``recipient`` is the seat the caller already settled and ``cap_payload``
    the ceiling it already read. Every branch below is held to both: one that
    cannot serve the seat refuses, and one that returns ahead of the
    back-reference branch -- the only one that carries a cap -- declines a
    capped gain rather than dropping the cap on the way past.
    """
    # "When this creature dies, you gain life equal to **its** power."
    # (Conclave Mentor.) "It" is the dead permanent, which is in a graveyard by
    # the time this resolves — so the amount is last-known information
    # (CR 603.10 / 608.2h) frozen by the fire site, exactly as Basri's
    # Lieutenant's counter clause is. Admitted only under a death trigger,
    # because those are the only events that record it; anywhere else the
    # back-reference still refuses below.
    #
    # Two characteristics and two events, one branch. "…equal to its
    # **toughness**" under "whenever a creature is put into an opponent's
    # graveyard from the battlefield" (Grim Feast) asks the same question about
    # the same object at the same moment, and splitting it would be two ways of
    # reading one sentence. The printed characteristic is the payload; the fire
    # sites freeze both whether or not the card asks, for the reason they
    # already freeze the power.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source in DEAD_CHARACTERISTIC_RECORDS
        # Widened from a literal pair to the set the fire sites answer for, so
        # an Aura's "when enchanted creature dies" reads the same frozen number
        # a creature's own death trigger does. The set is what a site *stamps*,
        # never what a condition table merely names.
        and event in DEAD_CHARACTERISTIC_EVENTS
        and node.player.kind == "you"
        # This shortcut returns before the back-reference branch below, which
        # is the only one that carries a cap, so it declines a capped gain
        # rather than dropping the cap on the way past.
        and not node.capped_by
    ):
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount_from_trigger": DEAD_CHARACTERISTIC_RECORDS[
                        node.amount.source
                    ],
                    "recipient": "caster",
                },
            ),
        )
    # "…you may gain life equal to **its** power" (Delif's Cone), inside a delay
    # whose opener targeted the creature (CR 603.7c) — so "it" is that creature
    # and `rebinding` said so by naming the amount for it. Read live at
    # resolution rather than frozen: the creature is on the battlefield,
    # attacking and unblocked, at the moment this ability resolves.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "bound_power"
    ):
        if node.player.kind != "you" or node.capped_by:
            raise LoweringError(
                "the bound creature's power is gained by the ability's own "
                "controller, uncapped",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {"amount_from_bound_power": True, "recipient": "caster"},
            ),
        )
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_mana_value"
        and LOOP_BOUND_OBJECT in produced
    ):
        # "…gains life equal to **its mana value**" inside the loop (Seeds of
        # Innocence). The scratchpad key of the same name is one number about
        # one victim, written by the singular destroy; a sweep destroys many
        # and writes none, so the phrase has to read the object the iteration
        # is on. Last-known information either way (CR 608.2h): by the time
        # this runs the artifact is a card in a graveyard, and the `Permanent`
        # the loop hands round is what still remembers what it was.
        #
        # Read before the back-reference branch below, which would refuse this
        # for want of the producer that cannot exist here.
        if node.capped_by:
            raise LoweringError(
                "a loop-bound mana value is gained uncapped", node=node
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {"amount_from_bound_mana_value": True, "recipient": recipient},
            ),
        )
    if isinstance(node.amount, ast.SacrificedForCost):
        # "You gain life equal to the sacrificed creature's toughness" (Life
        # Chisel, Diamond Valley); "…equal to the sacrificed enchantment's mana
        # value" (Faith Healer). The number is read off the permanent the
        # ability's own cost ate, which the activation path carried forward as
        # last-known information (CR 608.2h).
        #
        # Through the ``x_from_count`` channel every *other* family already
        # reads this record on — the mill (Altar of Dementia), the damage
        # (Freyalise Supplicant) and the where-clause (Burnt Offering) — rather
        # than the private ``amount_from_cost_sacrifice`` key this branch used
        # to emit. That key was a second reader of one question and it had
        # already drifted: it answered ``effective_<characteristic>`` off the
        # permanent, which reads a P/T and cannot read a mana value at all, so
        # "toughness" was the only word it could admit and Faith Healer refused
        # for printing the one the shared evaluator has answered since Burnt
        # Offering. The set is held to what that evaluator answers, because a
        # characteristic it cannot answer is a card reporting supported and
        # gaining nothing.
        if node.amount.characteristic not in _READABLE_COST_SACRIFICE_CHARACTERISTICS:
            raise LoweringError(
                "no handler reads the sacrificed permanent's "
                f"{node.amount.characteristic!r}",
                node=node,
            )
        if node.player.kind != "you":
            raise LoweringError(
                "the sacrificed permanent's characteristic is gained by the "
                "ability's own controller",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount": "x",
                    X_FROM_COUNT: {
                        "cost_sacrifice_characteristic": node.amount.characteristic
                    },
                    "recipient": "caster",
                },
            ),
        )
    # "You gain **2 life for each** enchantment destroyed this way."
    # (Multani's Decree.) The bare record one branch down with a printed rate on
    # it, so it goes through ``recorded_count_spec`` — the one reader that
    # unwraps a factor, checks the producer really ran and lands the number on
    # ``x_from_count``, where ``handlers/_common._scaled`` applies the
    # multiplier. Written here as its own arithmetic it would be a second
    # answer to "two life per what?", and the direction that fails is silent:
    # a factor read by one spender and dropped by the next gains half what the
    # card prints.
    #
    # Above the bare-``ThatMuch`` branch and never through it, so every card
    # written before a rate existed compiles to the byte-identical program —
    # ``scaled_by_recorded_count`` folds a printed 1 away rather than minting
    # ``Times(1, …)``, so nothing that used to reach that branch reaches this.
    if isinstance(node.amount, ast.Times):
        if node.per_each is not None:
            raise LoweringError(
                "a life gain reads one multiplier, not two", node=node
            )
        spec = recorded_count_spec(node.amount, produced, node)
        if spec is None:
            # A factor over something that is not a recorded count — the same
            # refusal ``_lower_recorded_count_placement`` makes of the same
            # node, and for its reason: reading it as the bare quantity would
            # gain a fraction of what the card says.
            raise LoweringError(
                "a multiplied life gain reads a recorded count", node=node
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount": "x", X_FROM_COUNT: spec,
                    "recipient": recipient, **cap_payload,
                },
            ),
        )
    if isinstance(node.amount, ast.ThatMuch):
        # "You gain life equal to the damage dealt" — reads the value the
        # preceding damage instruction recorded in the resolution scratchpad,
        # which is what lets the two effects be separate instructions at all.
        # A bare "that much" may instead name the firing event's own quantity;
        # `_back_reference_payload` is the one place that decides which, and
        # refuses when neither offers a number rather than reading a zero.
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    **_back_reference_payload(node.amount, produced, event),
                    "recipient": recipient,
                    **cap_payload,
                },
            ),
        )
    # "You gain life equal to the number of Cats you control." (Rin and Seri.)
    # A counted amount, through the same evaluator every other computed number
    # in the engine uses — the alternative is a second counter with its own
    # spelling of the spec, which is the drift `count_spec` exists to prevent.
    if isinstance(node.amount, ast.CountOf):
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount": "x", "recipient": recipient,
                    X_FROM_COUNT: count_spec(node.amount.filter, node),
                },
            ),
        )
    # "When this creature leaves the battlefield, you gain life equal to **the
    # number of age counters on it**." (Revered Unicorn.) Not a count of a set
    # in any zone — a counter is not an object — so it travels the
    # ``source_counters`` spec ``cards._lower_draw`` and
    # ``where_x._lower_where_x_counters`` already write for the identical
    # phrase, resolved at the one substitution point. One evaluator, so the
    # three printed word orders cannot count differently.
    #
    # Uncapped and to the ability's own controller: the pool prints no other
    # shape, and a cap dropped on the way past is the bug this file refuses on
    # behalf of everywhere else.
    if isinstance(node.amount, ast.CountersOnSource):
        if node.capped_by or node.per_each is not None:
            raise LoweringError(
                "a counter-counted life gain is gained uncapped", node=node
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount": "x", "recipient": recipient,
                    X_FROM_COUNT: {"source_counters": node.amount.kind},
                },
            ),
        )
    # "You gain 3 life **plus an additional 3 life for each additional {1}{G}
    # you paid**." (Taste of Paradise.) One gain (CR 119.3) whose amount scales
    # with a CR 601.2b payment: the printed base, plus a per-payment step times
    # however many times the caster took the offer. Two instructions would show
    # a life-gain replacement two events where the card prints one.
    #
    # Read before `x_offset_amount`, which `life._lower_gain_life` asks once
    # this function returns None: it reads the other shape a `Plus` can be (an
    # X with a constant on it) and would refuse this one.
    if (
        isinstance(node.amount, ast.Plus)
        and isinstance(node.amount.right, ast.Times)
        and isinstance(node.amount.right.of, ast.AdditionalCostPaidCount)
    ):
        base = _amount_payload(node.amount.left)
        if not isinstance(base, int):
            raise LoweringError(
                "a payment-scaled life gain starts from a printed number",
                node=node,
            )
        if node.player.kind != "you" or node.capped_by or node.per_each is not None:
            # "You" is the only gainer any card prints this on, and a cap or a
            # second multiplier on top would be arithmetic the handler does not
            # do — refused rather than dropped, which is the direction that
            # gains less than the card says instead of more.
            raise LoweringError(
                "a payment-scaled life gain is the caster's own, uncapped",
                node=node,
            )
        return (
            OracleInstruction(
                "target_gains_life", "",
                {
                    "amount": base,
                    "recipient": "caster",
                    "plus_per_cost_paid": {
                        "cost": optional_cost_key(node.amount.right.of.symbols),
                        "each": node.amount.right.factor,
                    },
                },
            ),
        )
    return None


def lower_per_each_gain(
    node: ast.GainLife,
    payload: dict[str, object],
    recipient: str,
    produced: frozenset[str],
    event: str | None,
) -> tuple[OracleInstruction, ...] | None:
    """A gain at a printed rate **for each** of something, or None when the
    sentence prints no multiplier.

    ``payload`` is the gain as ``life._lower_gain_life`` has built it so far --
    the printed rate on ``amount``, the settled seat on ``recipient`` -- and a
    branch that answers writes the count beside them as ``per_each`` and
    returns the instruction. One that does not answer leaves it untouched,
    which is what lets the caller finish the printed gain with the same dict.
    """
    # "…for each creature you control with flying" (Aven Gagglemaster): a
    # battlefield count of the gainer's own permanents. The honoured fields are
    # exactly what the handler tests; anything else refuses rather than being
    # dropped into a larger gain.
    if isinstance(node.per_each, ast.DiedThisTurn):
        # "…for each creature that died this turn" (Canopy Stalker). A tally,
        # not a scan: the creatures counted are precisely the ones no longer on
        # a battlefield, so there is nothing to filter and the count comes off
        # the game's own record. Game-wide, because the card says "each
        # creature" and not "each creature you control" — the per-seat tally is
        # a different number and answers a different card.
        if node.player.kind != "you":
            raise LoweringError(
                "the per-each life gain is the effect's own controller", node=node
            )
        leftover = _restrictions_beyond(node.per_each.filter, frozenset({"card_types"}))
        if leftover or node.per_each.filter.card_types != ("creature",):
            raise LoweringError(
                "the death tally counts creatures and nothing narrower", node=node
            )
        payload["per_each"] = {"history": "creatures_died_this_turn"}
        return (OracleInstruction("target_gains_life", "", payload),)
    if isinstance(node.per_each, ast.CountOfSacrificesThisWay):
        # "Sacrifice any number of permanents. You gain 2 life **for each
        # permanent sacrificed this way**." (Renounce.) The number is what the
        # sentence in front of this one actually took, and nothing on a board
        # holds it: "any number" prints no count and the permanents are cards in
        # a graveyard by now (CR 400.7), among everything else that ever arrived
        # there.
        #
        # It travels on ``recorded_cards`` — the channel Reprocess's draw and
        # Song of Blood's pump already read for this same record — which counts
        # the entries of a recorded *list* against a printed phrase rather than
        # reading a slot holding a number. The printed 2 stays the *rate* on
        # ``amount`` and the count multiplies it, which is what ``per_each``
        # means everywhere else in this function.
        if node.player.kind != "you":
            raise LoweringError(
                "a gain counted off this effect's own sacrifice is the "
                "effect's controller's",
                node=node,
            )
        if "sacrificed_cards" not in produced:
            raise LoweringError(
                "back-reference to 'sacrificed_cards' with no producer in "
                "this effect",
                node=node,
            )
        from ...subject_filters import card_only_filter

        described = card_only_filter(node.per_each.filter.to_payload())
        if described is None or dropped_narrowings(
            node.per_each.filter, node.per_each.filter.to_payload()
        ):
            # Only what is *printed* is testable off a record (CR 613.1): the
            # permanents are gone and what was kept is their cards. A narrowing
            # the card matcher cannot answer refuses rather than being counted
            # as though it were not there — a count that is too large is life
            # the card never offered.
            raise LoweringError(
                "a sacrificed-permanent count cannot test this restriction",
                node=node,
            )
        payload["per_each"] = {
            "recorded_cards": "sacrificed_cards", "filter": described,
        }
        return (OracleInstruction("target_gains_life", "", payload),)
    if isinstance(node.per_each, ast.CountersRemovedForCost):
        # "You gain 2 life **for each elixir counter removed this way**."
        # (Essence Bottle.) The complement of the branch below it: those
        # counters came off to pay this ability's own cost (CR 601.2h), so by
        # resolution the artifact holds none and a source read would multiply
        # by zero on every activation. The number is last-known information
        # (CR 608.2h) the activation path recorded, reached through the one
        # count evaluator every other computed amount uses.
        if node.player.kind != "you":
            raise LoweringError(
                "a gain counted off the cost's counter removal is the "
                "ability's own controller's",
                node=node,
            )
        payload["per_each"] = {"cost_counters_removed": node.per_each.counter}
        return (OracleInstruction("target_gains_life", "", payload),)
    if isinstance(node.per_each, ast.CountersOnSource):
        # "You gain 1 life **for each credit counter on this creature**."
        # (Icatian Moneychanger.) A count of the ability's own source, not of a
        # set of objects — so the payload names the counter word and the
        # handler names the reader, exactly as `deal_damage`'s
        # `amount_from_named_counters` does for the same phrase one family
        # over. The counter word is payload the whole way down, so a card
        # printing any other kind needs nothing here.
        if node.player.kind != "you":
            raise LoweringError(
                "a gain counted off the source's counters is the ability's own "
                "controller's",
                node=node,
            )
        payload["per_each"] = {"counters_on_source": node.per_each.kind}
        return (OracleInstruction("target_gains_life", "", payload),)
    if node.per_each is not None:
        filt = node.per_each
        # **Whether the gainer has to be "you" is a question about the count,
        # not about the gain.** The multiplier used to be a battlefield scan
        # taken against the *gainer*, and this refusal was that scan's contract;
        # the fold onto `count_from_payload` (see the comment below) made the
        # count read its own ``owner`` scope instead, so the two are independent
        # now and the refusal outlived its reason.
        #
        # It is narrowed rather than dropped, because most scopes still are
        # about a seat: ``owner: "all"`` is CR 403.1's one shared battlefield —
        # "for each creature **on the battlefield**" (Congregate) counts every
        # seat's and names none — so it is the one scope that cannot disagree
        # with whoever gains. Every other spec keeps the refusal, and gets it
        # in the spelling that says what is actually wrong.
        # "…**that player** gains 1 life for each basic land type among lands
        # **they** control" (Collapsing Borders). The gainer and the counted
        # seat are one player — the event's (CR 603.10) — so the narrowing moves
        # onto the scope `count_from_payload` resolves to that frozen seat, and
        # the refusal below admits it: this *is* that seat's own count.
        own_seat = recipient == EVENT_SUBJECT_PLAYER and filt.controller == "that_player"
        if own_seat:
            filt = count_filter_on_frozen_seat(filt, event, node)
        # ``printed_count_spec`` rather than ``count_spec`` (W1G6): a phrase
        # naming no seat names every permanent on the battlefield, CR 403.1.
        # A filter the line above moved onto a frozen seat carries a
        # ``zone_owner`` and is left as it is.
        spec = printed_count_spec(filt, node)
        if node.player.kind != "you" and spec.get("owner") != "all" and not own_seat:
            raise LoweringError(
                "a life gain counted off one seat's zone is that seat's own",
                node=node,
            )
        # "For each artifact or creature card in target opponent's graveyard, …
        # you gain 1 life." (Spoils of Evil.) "You gain 2 life **for each card
        # in your hand**." (Gerrard's Wisdom.) "You gain 1 life **for each
        # attacking creature**." (Respite.) One count, one reader — the same
        # `count_spec` / `count_from_payload` pair the mana half of Spoils of
        # Evil's sentence goes through one instruction over, because the two
        # halves are one count and two readings of it are two answers.
        #
        # **The battlefield branch used to be hand-built here**, and that is
        # what this fold removes: three payload keys named one at a time
        # (`controller`, `card_types`, `with_keywords`), a `_restrictions_beyond`
        # allow-list of exactly those three, and a second battlefield scan in
        # the handler that re-read them. So every other printed narrowing —
        # "each **attacking** creature" among them — refused, on a card whose
        # sentence the general counter has read since Spoils of Evil.
        # `count_spec` also answers the question the local list could not: an
        # unscoped combat role is counted across **every** seat (CR 508.1a puts
        # the attackers on the active player's battlefield), where
        # `controller: "you"` answered zero for the seat casting the fog.
        payload["per_each"] = spec
        return (OracleInstruction("target_gains_life", "", payload),)
    return None

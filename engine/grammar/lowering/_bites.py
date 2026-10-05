"""Lowering a **bite**: one named object deals damage equal to a characteristic
it still has.

Split out of ``lowering/damage.py`` at Mirage's third wave, the fifth time that
module reached the thousand-line guard, along the line the branches themselves
already drew. Everything left in `damage` computes a **quantity** — a printed
number, a count of a board, a record of an earlier step — and hands it to the
generic ``deal_damage``, whose source is the spell or the ability. A bite reads
one object's **power** at resolution (CR 613's computed value, not the printed
one) and that object is the *dealer*: CR 120.7's source of damage is the
object that dealt it, so the creature is, so lifelink, "a source you control" and "damage dealt by a creature"
all answer differently from the generic kind. That is why each of these is its
own instruction rather than an amount key.

Who the dealer is, is the axis the kinds are named along:

* ``source_bites_target`` — the ability's own source (or, on an Aura, the
  permanent it enchants, CR 113.7a).
* ``target_bites_target`` — two chosen targets, the biter first.
* ``bound_bites_source`` — a permanent an earlier step of this same effect
  recorded, biting the ability's source.
* ``bound_bites_player`` — the same biter, biting a **player** (Delirium).

A floor rather than a family for ``_amounts``' reason exactly: ``damage`` reads
it and it reads nothing back, and inside a package a module a family imports
cannot itself be one.
"""

from ...oracle_types import ATTACHED_PERMANENT_CONTROLLER, OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _optional_slot_key,
    _describe_targets,
    _filter_payload,
    _is_enchanted,
    _is_source,
    _is_target,
    _restrictions_beyond,
    testable_filter_payload,
)
from ._events import (_DAMAGED_PERMANENTS, _EVENT_SUBJECT_CONTROLLERS,
                      _EVENT_SUBJECT_OBJECTS, _RECORDED_PERMANENTS)


def lower_bite(
    node: ast.DealDamage, produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> tuple[OracleInstruction, ...] | None:
    """The bite *node* describes, or None when no bite reading applies.

    None rather than a raise, because the caller has a dozen readings left to
    try: this is a probe among the branches of one damage lowering, not a
    dispatch point. The refusals inside are the other kind — a sentence that
    *is* a bite and names something no handler can find — and those raise.
    """
    # "Target creature you control deals damage equal to its power to another
    # target creature." (Garruk, Savage Herald's −2.) A fused kind: the biter
    # and the bitten are two chosen targets resolved as a list, and the amount
    # is the biter's power read at resolution — which is why the generic
    # deal_damage cannot carry it.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and node.source.quantifier == "target"
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.TargetSpec)
        and node.recipients[0].distinct_from_prior
        # Both slots are *targets*. "another target creature" and "another
        # creature" are different cards — the second chooses on resolution
        # (CR 601.2c names nothing) — and this kind builds a two-slot cast-time
        # picker, so admitting the untargeted phrase would raise a picker for a
        # choice the card never announces and drop the printed word.
        and node.recipients[0].targeted
    ):
        return (
            OracleInstruction(
                "target_bites_target",
                "",
                {
                    "targets": {
                        "quantifier": "target",
                        "kind": "object",
                        "filter": _filter_payload(node.source.filter),
                        # Two picks: the biter (first), then the bitten — and
                        # they are *differently* restricted. "Target creature
                        # you control deals damage … to **another target
                        # creature**" names the caster's creature and then
                        # anyone's, and one filter for both slots is what made
                        # the picker offer only the caster's for the second:
                        # Garruk's -2 could bite nothing but his own board while
                        # its handler was written to allow either.
                        "filters": [
                            _filter_payload(node.source.filter),
                            _filter_payload(node.recipients[0].filter),
                        ],
                        "count": 2,
                        # The printed "another" (CR 115.3/601.2c), **carried**
                        # rather than only checked. The branch above already
                        # requires it — an unqualified second "target" is a
                        # different card and refuses here — and the comment
                        # below says this kind "refuses a second target equal to
                        # the first". It did not: the word was read to decide
                        # whether to build this instruction and then dropped, so
                        # the announcement gate had nothing to enforce and a
                        # creature could be sent to bite itself for its own
                        # power. One instance of the word may name one object
                        # once; two instances may name it twice *unless* the
                        # card says otherwise, and this is the card saying so.
                        "distinct": True,
                        **_optional_slot_key(
                            (node.source, node.recipients[0])
                        ),
                    },
                },
            ),
        )
    # "Target creature deals damage **to itself** equal to its power."
    # (Repentance.) The biter and the bitten are one creature, which is why it
    # is a kind of its own rather than ``target_bites_target`` with the same
    # permanent in both slots: that kind builds a *two*-slot cast-time picker
    # and refuses a second target equal to the first (the printed "another"),
    # so a single-target card routed through it would ask for a pick it never
    # announces and then decline it.
    #
    # "Itself" is the sentence's own subject, not the ability's source: a
    # sorcery has no permanent, and the reflexive can only mean the creature
    # the sentence just named. Read here rather than by rewriting the pronoun,
    # because the branch is gated on the subject being a **target** — a card
    # whose subject really is the ability's source ("this creature deals damage
    # to itself…") is a different sentence and keeps its own refusal.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and not node.amount.bonus
        and node.source is not None
        and isinstance(node.source, ast.TargetSpec)
        and node.source.quantifier == "target"
        and node.source.targeted
        and len(node.recipients) == 1
        and _is_source(node.recipients[0])
        and node.riders == ast.DamageRiders()
    ):
        payload: dict[str, object] = {}
        _describe_targets(payload, node.source)
        payload["filter"] = _filter_payload(node.source.filter)
        return (OracleInstruction("target_bites_itself", "", payload),)
    # "**Each** creature deals damage to itself equal to its power." (Wave of
    # Reckoning.) The branch above with the quantifier changed, and its own kind
    # for the same reason that one is not ``target_bites_target``: what differs
    # is *how many creatures bite*, and the targeted kind builds a cast-time
    # picker this sentence announces nothing for.
    #
    # It is **not** the sweep further down either, which is the opposite
    # sentence: there one source bites a described set, here every member of the
    # set bites itself. Routed through that kind the whole board would take the
    # spell's own source's power — zero for a sorcery — which is the silent
    # direction.
    #
    # "Itself" is each *iteration's* creature, not the ability's source: a
    # sorcery has no permanent, so the reflexive can only mean the creature the
    # sweep is on. That is what makes the dealer the permanent (CR 120.7) rather
    # than the printed card, which the handler is held to.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and not node.amount.bonus
        and node.source is not None
        and isinstance(node.source, ast.TargetSpec)
        and not node.source.targeted
        and node.source.quantifier in ("all", "each")
        and len(node.recipients) == 1
        and _is_source(node.recipients[0])
        and node.riders == ast.DamageRiders()
        and node.per_each is None
    ):
        if node.source.filter.card_types != ("creature",):
            # CR 120.3: damage is dealt only to a battle, a creature or a
            # planeswalker, and only a creature has the power this sentence
            # reads. A sweep written over any other noun would mark damage
            # nothing could read, off a number nothing has.
            raise LoweringError(
                "only a creature sweep bites itself for its own power",
                node=node,
            )
        described = testable_filter_payload(
            node.source.filter,
            refusal="the bite sweep cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        return (
            OracleInstruction(
                "each_matching_bites_itself", "", {"filter": described},
            ),
        )
    # "This creature deals damage equal to its power to target **player** or
    # planeswalker." (Leafkin Avenger.) The recipient is not an object, so the
    # bites handler below — which resolves a permanent — cannot carry it. The
    # generic damage instruction can: what is new is only where the *number*
    # comes from, and that is one payload key rather than a kind.
    # "…**it** deals damage equal to **its** power to **its controller**"
    # (Consuming Ferocity). Three pronouns, one referent, and none of them is
    # the ability's source: the sentence in front of this one put a counter on
    # "enchanted creature", so every "it" behind it is that creature and "its
    # controller" is that creature's seat (CR 608.2h).
    #
    # Read before the source branch below, which cannot tell the two apart —
    # a bare "it" parses to the same spec either way — and gated on the record
    # rather than on the word, because the record is the only thing that says
    # a step of this effect named the attachment. Without it the branch below
    # takes the line and the Aura deals damage equal to *its own* power, which
    # is zero.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and not node.amount.bonus
        and node.source is not None
        and (_is_source(node.source) or _is_enchanted(node.source))
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.PlayerRef)
        and node.recipients[0].kind in ("controller", "that_player")
        and ATTACHED_PERMANENT_CONTROLLER in produced
    ):
        return (
            OracleInstruction(
                "deal_damage", "",
                {
                    "amount_from_attached_power": True,
                    "recipient": ATTACHED_PERMANENT_CONTROLLER,
                },
            ),
        )
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and _is_source(node.source)
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.PlayerRef)
    ):
        payload: dict[str, object] = {"amount_from_source_power": True}
        _describe_targets(payload, node.recipients[0])
        return (OracleInstruction("deal_damage", "", payload),)
    # "…it deals damage equal to its power to **each blocking creature**."
    # (Electryte.) The same bite over a *described set* instead of one object:
    # nothing is targeted and nobody picks, so it lands on the sweep handler
    # (`lowering/_sweeps.py`'s kind) with the amount read at resolution rather
    # than baked in — which is the whole reason it cannot simply go through that
    # module, whose two sweeps refuse a computed amount outright.
    #
    # Creatures only, checked here for the reason `_sweeps` checks it: CR 120.1a
    # says damage cannot be dealt to an object that is not a battle, a creature
    # or a planeswalker, so a sweep written over "each permanent" would mark
    # damage nothing could ever read. And every key of the printed noun phrase
    # must be one `subject_matches` tests, because a narrowing the matcher drops
    # burns a strictly larger board than the card prints.
    sweep = node.recipients[0] if len(node.recipients) == 1 else None
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and not node.amount.bonus
        and node.source is not None
        and _is_source(node.source)
        and node.riders == ast.DamageRiders()
        and node.per_each is None
        and isinstance(sweep, ast.TargetSpec)
        and not sweep.targeted
        and sweep.quantifier in ("all", "each")
    ):
        if sweep.filter.card_types != ("creature",):
            raise LoweringError(
                "only a creature sweep is bitten by the printed noun phrase",
                node=node,
            )
        described = testable_filter_payload(
            sweep.filter,
            refusal="the bite sweep cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        return (
            OracleInstruction(
                "deal_damage_each_matching", "",
                {"amount_from_source_power": True, "filter": described},
            ),
        )
    # "…**it** deals damage equal to its power to **any target of their
    # choice**." (Pandemonium.) The bitten end is CR 115.4's union rather than a
    # permanent, which is why it is its own branch and not a filter on the one
    # below: that one describes a noun phrase, and "any target" has none — the
    # handler resolves a face where no object was announced.
    #
    # Two biters, one branch, because only the *word* differs. Under a trigger
    # whose fire site froze the object its event was about
    # (``_EVENT_SUBJECT_OBJECTS``) a bare "it" is that object — the creature
    # that just entered, whose power is the whole of the card — and everywhere
    # else "it"/"this creature" is the ability's own source, which is the
    # payload's absence. Gated on the table rather than on the pronoun alone:
    # with no frozen object the words name nothing, and biting with the
    # enchantment instead deals zero while compiling clean.
    recipient = node.recipients[0] if len(node.recipients) == 1 else None
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and isinstance(node.source, ast.TargetSpec)
        and isinstance(recipient, ast.TargetSpec)
        and recipient.quantifier == "any_target"
        and node.riders == ast.DamageRiders()
    ):
        # A **bare pronoun** under an event that froze its object is that
        # object. ``grammar/rebinding.py`` has already swapped the trigger's
        # subject filter onto the word by the time this runs, so the pronoun is
        # no longer ``is_source`` and only the quantifier still says it was one
        # — which is why the test is the quantifier and the event table rather
        # than the filter.
        names_the_event_subject = (
            node.source.quantifier == "it" and event in _EVENT_SUBJECT_OBJECTS
        )
        if not names_the_event_subject and not _is_source(node.source):
            # "It"/"this creature" naming neither the ability's source nor a
            # frozen event subject names nothing this handler can find. Left to
            # the branches below, which all want a permanent recipient, and then
            # to the generic amount lowering, whose refusal says so by name.
            return None
        payload: dict[str, object] = {}
        if names_the_event_subject:
            payload["biter"] = "event_subject"
        described: dict[str, object] = {"quantifier": "any_target", "kind": "any"}
        if recipient.filter.their_choice:
            # "**of their choice**": the target is announced by a seat that is
            # not the ability's controller, which is CR 603.3d's "unless the
            # ability's effect states otherwise" — and this sentence states it.
            # The only player these words can name is the one the sentence
            # already named, "that creature's controller", so the seat is read
            # off the same frozen key that phrase is read off
            # (``_EVENT_SUBJECT_CONTROLLERS``).
            #
            # Refused where no event froze that seat, rather than dropped: a
            # dropped chooser is not a card that does less, it is the ability's
            # controller aiming somebody else's creature — the exact opposite of
            # what the words print, and silent.
            if event not in _EVENT_SUBJECT_CONTROLLERS:
                raise LoweringError(
                    "'of their choice' names no player this target can be "
                    "announced by",
                    node=node,
                )
            described["chooser"] = "event_subject_controller"
        payload["targets"] = described
        if node.amount.bonus:
            payload["power_bonus"] = node.amount.bonus
        return (OracleInstruction("source_bites_target", "", payload),)

    # "It deals damage equal to **its power** to target creature or
    # planeswalker." (Heartfire Immolator.) The source is sacrificed to pay the
    # cost, so by resolution it is in a graveyard — its power is last-known
    # information (CR 608.2), which the Permanent object still carries because
    # nothing off the battlefield touches it. Its own kind rather than the
    # generic damage, because the amount is a *read* rather than a number.
    # …and on an **Aura**, whose biter is the permanent it enchants (Farrel's
    # Mantle): the ability stays the Aura's (CR 113.7a) and the dealer is
    # payload, because an Aura has no power to deal.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and (_is_source(node.source) or _is_enchanted(node.source))
        and len(node.recipients) == 1
        and _is_target(node.recipients[0])
    ):
        assert isinstance(node.recipients[0], ast.TargetSpec)
        payload: dict[str, object] = {}
        _describe_targets(payload, node.recipients[0])
        payload["filter"] = _filter_payload(node.recipients[0].filter)
        if _is_enchanted(node.source):
            payload["biter"] = "attached"
            # "…to **another** target creature": other than the creature
            # *dealing* it — left as ``exclude_self`` the picker excludes the
            # Aura, never on the list, and offers the host as its own victim.
            described = (payload.get("targets") or {}).get("filter") or {}
            if described.pop("exclude_self", None):
                described["exclude_attached"] = True
                payload["exclude_biter"] = True
        # "…its power **plus 2**" (Farrel's Mantle): CR 107.3's constant.
        if node.amount.bonus:
            payload["power_bonus"] = node.amount.bonus
        return (OracleInstruction("source_bites_target", "", payload),)

    # "**That creature** deals damage equal to its power to this creature."
    # (Tracker.) The second half of a printed exchange: the biter is the
    # creature the sentence in front of this one chose, and the bitten is the
    # ability's own source. Its own kind rather than CR 701.14's fight, which
    # this looks like and is not — a fight is all-or-nothing (701.14b), so a
    # source that has left the battlefield stops *both* halves, while these are
    # two sentences and the first one still happened.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and node.source is not None
        and isinstance(node.source, ast.TargetSpec)
        and node.source.quantifier == "that"
        and len(node.recipients) == 1
        and _is_source(node.recipients[0])
        and node.riders == ast.DamageRiders()
    ):
        if _restrictions_beyond(node.source.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound object carries no narrowing the bite could honour",
                node=node,
            )
        if _DAMAGED_PERMANENTS not in produced:
            # The handler reads the biter out of the resolution scratchpad, and
            # with nothing recorded it would deal nothing while the card
            # compiled clean — the discipline every back-reference here follows.
            raise LoweringError(
                f"back-reference to {_DAMAGED_PERMANENTS!r} with no producer "
                "in this effect",
                node=node,
            )
        return (
            OracleInstruction(
                "bound_bites_source", "",
                {"permanents_from": _DAMAGED_PERMANENTS},
            ),
        )

    # "Tap target creature that player controls. **That creature deals damage
    # equal to its power to the player.**" (Delirium.) The branch above with
    # the bitten end swapped for a seat: same biter — a permanent an earlier
    # step of this same effect recorded — and the same read of its power, so it
    # is one row down rather than a kind somewhere else.
    #
    # Which seat is not something the *sentence* says. "The player" is the
    # definite article pointing back at the player line 1 named, and line 1 is
    # a cast-timing registry line that produces no instruction at all — so
    # there is nothing in this effect for the pronoun to be bound to except the
    # creature the step in front acted on. Its controller is that player, by the
    # printed target restriction ("target creature **that player** controls",
    # re-checked at CR 608.2b), and reading it off the biter is the only answer
    # that needs no record nobody writes.
    if (
        isinstance(node.amount, ast.ThatMuch)
        and node.amount.source == "its_power"
        and not node.amount.bonus
        and node.source is not None
        and isinstance(node.source, ast.TargetSpec)
        and node.source.quantifier == "that"
        and len(node.recipients) == 1
        and isinstance(node.recipients[0], ast.PlayerRef)
        and node.riders == ast.DamageRiders()
    ):
        if node.recipients[0].kind not in ("that_player", "controller"):
            # "…deals damage equal to its power to **its controller**."
            # (Backlash.) The seat Delirium reaches by inference, printed
            # outright: "its" is the biter, so the possessive names exactly the
            # seat the handler reads off it, and the two spellings are one
            # payload.
            #
            # Every other seat this engine can name is one the sentence would
            # have had to say — "you", "each opponent", the seat a trigger
            # froze. None of them is a bare "the player", and lowering one of
            # them onto this kind would damage a seat the card never named.
            raise LoweringError(
                "a bound creature's bite names the player its own controller is",
                node=node,
            )
        if _restrictions_beyond(node.source.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound object carries no narrowing the bite could honour",
                node=node,
            )
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if len(recorded) != 1:
            # Nothing recorded means the pronoun names nothing and the handler
            # would deal no damage on a card compiling clean; *two* records mean
            # the sentence is ambiguous about which step it points back at, and
            # picking one would be right half the time.
            raise LoweringError(
                "a bound creature's bite needs exactly one recorded permanent "
                "in front of it",
                node=node,
            )
        return (
            OracleInstruction(
                "bound_bites_player", "",
                {"permanents_from": recorded[0], "recipient": "biter_controller"},
            ),
        )

    return None

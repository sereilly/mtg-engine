"""Lowering control changes: CR 613 layer 2, and CR 701.12's exchange.

`_lower_gain_control` and `_lower_exchange_control`, split out of `board` when
that module reached the thousand-line guard. The line is the one `engine/`
already draws — `engine/control.py` and `engine/handlers/control_changes.py`
are separate from destruction and sacrifice for the same reason: a control
change is not a zone change, it is a timestamped *contribution* that a later
effect can end, and what lowering owes is the source and the duration rather
than a new owner.

The parse half stays in `effects/board.py`, which is the arrangement `zones`,
`library` and `mana` already have: a lowering family may outgrow its parse
family without the parse family having to split with it.
"""


from ...oracle_types import OracleInstruction
from ...subject_filters import object_only_filter, untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (_describe_targets, _filter_payload, _is_enchanted,
                      _is_source, _is_target,
                      _restrictions_beyond)
from ._events import (CHOSEN_PERMANENT, CHOSEN_PLAYER, EVENT_SUBJECT_PLAYER,
                      _EVENT_SUBJECT_PLAYERS, _UNTAPPED_PERMANENTS)


def _lower_exchange_control(node: ast.ExchangeControl) -> tuple[OracleInstruction, ...]:
    """"Exchange control of target artifact, creature, or land you control and
    target permanent an opponent controls…" (Gauntlets of Chaos, CR 701.12b.)

    Two chosen slots, described the way the two-target pump describes its pair:
    ``filters`` carries one filter per slot so the picker can enumerate both
    halves and the handler can re-check each at resolution (CR 608.2b), while
    ``filter`` stays the shape every one-slot reader already expects.

    ``shares_type`` and the printed type list travel as payload rather than as
    part of the kind, because a card exchanging (say) two enchantments would be
    this same effect with a different noun phrase.
    """
    if not isinstance(node.first, ast.TargetSpec) or not _is_target(node.first):
        raise LoweringError(
            "an exchange of control needs a chosen permanent on each side", node=node
        )
    if not isinstance(node.second, ast.TargetSpec) or not _is_target(node.second):
        raise LoweringError(
            "an exchange of control needs a chosen permanent on each side", node=node
        )
    first = _filter_payload(node.first.filter)
    second = _filter_payload(node.second.filter)
    payload: dict[str, object] = {
        "targets": {
            "quantifier": "target",
            "kind": "object",
            "filter": first,
            "filters": [first, second],
            "count": 2,
            # Two permanents on two battlefields are distinct by construction,
            # but saying so is what stops one player's own permanent filling
            # both slots if a later card drops the controller words.
            "distinct": True,
        },
        # The relation between the slots (see the node's docstring), and the
        # types it is measured over — "one of **those** types" is the first
        # slot's printed list, so it is read off that filter rather than
        # spelled out again here.
        "shares_a_type": bool(node.shares_a_type),
        "destroy_attached_auras": bool(node.destroy_attached_auras),
    }
    return (OracleInstruction("exchange_control_of_targets", "", payload),)




# The scratchpad key the tap records and this sentence reads. One name, in one
# place, because ``engine/grammar/lower.py``'s ``_PRODUCES`` writes it and the
# refusal below is what proves a producer ran — two spellings would make the
# refusal vacuous while the handler read an empty record and marked nothing.






#: The seat words ``engine/targeting.py`` turns into a *picker* flag, so a
#: control change may carry one without :func:`object_only_filter` refusing it.
#:
#: Each of these is a question about a seat, which is exactly what the pure
#: matcher the steal handlers re-ask at resolution cannot answer — and exactly
#: what ``legality._enumerate_targets`` answers before the target is ever
#: named (``own_only``, ``opponent_only``, ``defending_player_only``). Listing
#: the three rather than waving `controller` through is the claim that the
#: picker really does carry them out: a fourth spelling refuses here instead of
#: being dropped into a steal that offers every permanent on the board.
_PICKER_ENFORCED_CONTROLLERS = frozenset({"you", "opponent", "defending_player"})


def _linked_steal_filter(node: ast.GainControl, subject: ast.TargetSpec) -> dict:
    """The payload a linked steal's printed noun phrase becomes, or a refusal.

    One reader for the four linked durations, because the question they ask of
    their subject is identical: can something test this phrase before the
    control change is recorded? What differs is only which fact the sweep
    re-checks afterwards, and that has been ``link_conditions`` data since
    Scarwood Bandits.
    """
    described = _filter_payload(subject.filter)
    controller = described.get("controller")
    if controller is not None and controller not in _PICKER_ENFORCED_CONTROLLERS:
        raise LoweringError(
            "the control change cannot test this restriction", node=node
        )
    # ``controller_controls`` rides beside ``controller`` in the carried set
    # and for the same reason stated differently: the steal's own resolution
    # tests it. "…**whose controller controls an Island**" (Seasinger) is a
    # question about a seat's whole board, which no object-only matcher can
    # answer — the handler asks ``subject_filters.subject_matches``, which has
    # the game, and the picker asks the same function over the same payload.
    if object_only_filter(
        described, carried_separately=frozenset({"controller", "controller_controls"})
    ) is None:
        raise LoweringError(
            "the control change cannot test this restriction", node=node
        )
    _describe_targets(described, subject)
    return described


#: How a printed subject names the seat a steal hands the permanent to, and the
#: seat that picks it. Two seats in one word, because the sentence prints one:
#: "an opponent may gain control of a creature … **of their choice**" (Infernal
#: Denizen) makes the offered player both the chooser and the new controller,
#: and reading them as two answers is how a three-seat game ends up asking one
#: player and handing the creature to another.
#:
#: A word not in here refuses rather than defaulting to the effect's controller,
#: which is the one seat the sentence has said it is *not*.
#: Written as ``target_opponent`` in the round that added it, when one parsed
#: kind covered both "an opponent" and "target opponent". A parallel branch
#: in the same wave split those — admitting the chosen seat as a payer would
#: otherwise have admitted the article too — so the untargeted article this
#: card actually prints is ``opponent``. ``target_opponent`` is deliberately
#: absent: no card prints a *targeted* offered steal, and the docstring above
#: says an unlisted word refuses.
_OFFERED_STEAL_CHOOSERS: dict[str, str] = {"opponent": "opponent"}


def _lower_offered_steal(
    node: ast.GainControl, subject: ast.TargetSpec
) -> tuple[OracleInstruction, ...]:
    """"<player> may gain control of <a permanent> of their choice …"

    Two instructions, the pairing Preacher already uses: the pick is armed on
    the seat that makes it and the steal behind it reads the recorded answer.
    What is new is which seat *keeps* the permanent — ``new_controller`` — and
    that the prompt may be declined, which is where the printed "may" lives.

    The subject is a quantified noun phrase rather than a target: nothing is
    announced when the trigger goes on the stack, and CR 601.2c has nothing to
    say about a choice made during resolution.
    """
    chooser = _OFFERED_STEAL_CHOOSERS.get(
        node.gained_by.kind if node.gained_by is not None else ""
    )
    if chooser is None:
        raise LoweringError(
            "no handler for a control change handed to this player", node=node
        )
    if subject.quantifier != "a" or subject.count != 1:
        raise LoweringError(
            "an offered steal picks exactly one permanent", node=node
        )
    described = _filter_payload(
        subject.filter, carried_separately=frozenset({"their_choice"})
    )
    # Lifted, not carried: who picks is the prompt's own seat, and no candidate
    # can be asked whether it is "of their choice". Left in the payload it would
    # be a key `subject_matches` has no matcher for, which is the whole point of
    # the untestable-keys gate below.
    described.pop("their_choice", None)
    # The candidate rule asks `subject_matches` with the *ability's* seat as
    # observer, which is what makes "a creature **you** control" mean the
    # Denizen's controller and not the opponent doing the picking — the same
    # reading, and the same gate, the tapped-source branch above relies on.
    if untestable_filter_keys(described):
        raise LoweringError(
            "the control change cannot test this restriction", node=node
        )
    return (
        OracleInstruction(
            "choose_permanent", "",
            {
                "result_key": CHOSEN_PERMANENT,
                "chooser": chooser,
                "filter": described,
                # The printed "may": one declinable prompt rather than an offer
                # in front of a choice (see :class:`ast.GainControl`.offered).
                "optional": bool(node.offered),
                "prompt": "Choose a creature to gain control of.",
            },
        ),
        OracleInstruction(
            "steal_target_linked_to_source", "",
            {
                "permanents_from": CHOSEN_PERMANENT,
                "new_controller": "chooser",
                "link_conditions": ["source_on_battlefield"],
            },
        ),
    )


#: The seats a control change may be handed to by name. Each is one
#: ``engine/handlers/_common.resolve_target_player`` already answers, which is
#: the whole of what makes this list a claim rather than a filter: a seat word
#: nobody resolves would hand the permanent to whichever player an empty lookup
#: defaults to, which is the ability doing something the card never said.
#: "At the beginning of each player's upkeep, that player may pay {R}{R} or
#: 2 life. If the player does, **they** gain control of this creature."
#: (Emberwilde Djinn.) A seat the *firing event* named rather than one the
#: resolution chose, so it is neither a named gainer below (nothing targeted
#: it) nor a chosen one above (nobody picks).
#: ``_events._EVENT_SUBJECT_PLAYERS`` is what says an event really froze one,
#: so under any other trigger the word names a player nobody recorded and the
#: sentence refuses.
_EVENT_GAINERS = frozenset({"that_player", "they"})

_NAMED_GAINERS = frozenset({"target_opponent", "target_player", "you"})

#: The seats a control change may be handed to by a phrase that names **no**
#: particular player — "**An opponent** gains control of this land" (Rainbow
#: Vale). CR 608.2c/608.2d: the controller of the ability announces the choice
#: while applying the effect, so the sentence lowers to the pick and then the
#: hand-over, rather than to a hand-over that guesses. Kept apart from
#: ``_NAMED_GAINERS`` because those seats are already resolved by the time the
#: instruction runs and these are not.
_CHOSEN_GAINERS = {"opponent": "Choose an opponent to gain control of this permanent."}


def _lower_another_seat_gains_control(
    node: ast.GainControl, subject: ast.TargetSpec, event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"Target opponent gains control of this creature." (Chaos Lord.)

    CR 611.2b's untimed control change, handed to a seat the sentence names.
    Its own branch rather than a duration row beside the four linked ones,
    because what those four have in common is a *link* — something the sweep
    re-checks — and this has none: nothing ends it but a later contribution.

    Narrow on both axes, and deliberately. The subject must be the ability's own
    source: a card handing away something it *chose* would need the target
    picker and the CR 608.2b re-check every steal above carries, and none of
    that is exercised by a sentence no card in the pool prints. And the seat
    must be one the resolution can name.
    """
    if not _is_source(subject):
        raise LoweringError(
            "only a permanent handing itself over is implemented", node=node
        )
    if _restrictions_beyond(subject.filter, frozenset({"card_types", "is_source"})):
        raise LoweringError(
            "the source of a control change carries no narrowing", node=node
        )
    assert node.gained_by is not None
    who = node.gained_by.kind
    if who in _EVENT_GAINERS:
        # The seat the *firing event* froze, gated on the one table that says
        # which events freeze one — so this sentence under a trigger that
        # froze nobody refuses here rather than handing the permanent to
        # whichever player the resolution happened to be carrying. The same
        # gate and the same key the offer in front of it already reads for
        # its own actor, so the player who pays and the player who gains
        # cannot come apart.
        if event not in _EVENT_SUBJECT_PLAYERS:
            raise LoweringError(
                "a control change to \"that player\" needs a trigger whose "
                "event freezes a seat", node=node,
            )
        return (
            OracleInstruction(
                "give_control_of_source_to_player", "",
                {"who": EVENT_SUBJECT_PLAYER},
            ),
        )
    prompt = _CHOSEN_GAINERS.get(who)
    if prompt is not None:
        # Two steps for one sentence, the same shape ``choose_permanent`` +
        # ``steal_target_linked_to_source`` takes a few lines up: the pick may
        # have to stop and ask (three seats, three answers) and a handler that
        # stops cannot also finish. The hand-over reads the seat back under the
        # one key a chosen player is ever written to.
        return (
            OracleInstruction(
                "choose_opponent", "",
                {"result_key": CHOSEN_PLAYER, "prompt": prompt},
            ),
            OracleInstruction(
                "give_control_of_source_to_player", "", {"who": "chosen"}
            ),
        )
    if who not in _NAMED_GAINERS:
        raise LoweringError(
            f"no handler gives control to {who!r}", node=node
        )
    return (
        OracleInstruction("give_control_of_source_to_player", "", {"who": who}),
    )


def _lower_gain_control(
    node: ast.GainControl, produced: frozenset[str], event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """``Gain control of <subject> <duration>.``

    Four shapes, and which one a card is depends on its duration and subject:

    * "…until end of turn" on a chosen target (Traitorous Greed) — an ordinary
      targeted instruction carrying its noun phrase.
    * "…until end of turn" on "**that creature**" (Disharmony) — the object a
      previous step of this same effect chose, read out of the resolution
      scratchpad; a producer must have run, the same discipline
      ``_lower_doesnt_untap_next_step`` applies.
    * "…for as long as you control this creature" — the linked steal when
      targeted (Aladdin's artifact, Orcish Squatters' land, Merieke Ri Berit's
      creature), The Wretched's blocker sweep when the subject is "all
      creatures blocking this creature".
    * "…and this creature remains tapped" (Willow Satyr, Rubinia Soulsinger) —
      the two-condition linked duration; the conditions ride the payload and
      the state-based sweep re-checks them (CR 611.2b,
      ``engine/control.LINKED_CONTROL_CONDITIONS``).

    The last of those four used to be its own instruction kind, with the
    artifact **hard-coded in the handler** and the filter compared here for
    equality against the one shape it implemented — so "gain control of target
    *land*" (Orcish Squatters) and "target *creature*" (Merieke Ri Berit) were
    the same printed sentence refused for naming a different noun. The type is
    payload now, and the shape is the monitored steal beside it with the one
    ``you_control_source`` condition: what differs between these branches is
    which fact the sweep re-checks, and that has been data since Scarwood
    Bandits. Two kinds for one sentence would be the worse answer even where
    both worked — nothing would say which of them a given printing goes
    through.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec):
        raise LoweringError("the linked-control handler needs a named target", node=node)
    # "**Target opponent** gains control of this creature …" (Chaos Lord): the
    # sentence names the seat, so the permanent is handed over rather than taken.
    # Read before the duration branches because CR 611.2b's change is untimed and
    # every branch below is about when one ends. The offered form
    # (``node.offered``, Infernal Denizen) is a different sentence and keeps its
    # own branch further down — there the seat both picks and receives.
    if node.gained_by is not None and not node.offered:
        return _lower_another_seat_gains_control(node, subject, event)
    # "When this Aura enters, gain control of **enchanted land** until end
    # of turn." (Wellspring.) The permanent the Aura is attached to, which
    # is neither a target (an Aura's effect on its own host chooses nothing)
    # nor a record an earlier step wrote — so it is its own branch, reached
    # before every duration branch below for the reason the seat one above
    # is: what the sentence is *about* is settled before when it ends.
    #
    # Only "until end of turn". Mind Harness prints the untimed spelling
    # ("You control enchanted creature") as a *static* line, which
    # ``engine/auras.py`` derives on every recompute and ends by detaching —
    # a one-shot contribution with no lifetime would outlive the Aura.
    if _is_enchanted(subject):
        if node.duration != "until_end_of_turn":
            raise LoweringError(
                "control of an Aura's host is taken until end of turn; the "
                "untimed spelling is a static line", node=node,
            )
        if node.tap_when_lost:
            raise LoweringError(
                "no rider rides the control of an Aura's host", node=node
            )
        return (
            OracleInstruction(
                "gain_control_until_eot", "", {"attached": True}
            ),
        )
    if node.duration == "indefinite":
        # "Gain control of target nonartifact, nonblack creature." (Ritual of
        # the Machine.) The same contribution the until-end-of-turn branch
        # records, with the one thing that decides everything downstream
        # inverted: cleanup drops a contribution stamped ``until_eot`` and
        # leaves this one alone (CR 611.2a). That fact is the *kind* rather than
        # a payload flag, because the handler both kinds share reads it to
        # decide the lifetime — a payload key would let a lowering that forgot
        # it record a steal that quietly ends at cleanup.
        if subject.quantifier != "target":
            raise LoweringError(
                "the indefinite control change needs a named target", node=node
            )
        described = _filter_payload(subject.filter)
        # "…target artifact **defending player controls**" (Kukemssa Pirates).
        # A seat, which the pure matcher the handler re-asks at resolution
        # cannot answer and which `legality._enumerate_targets` answers before
        # the target is ever named — the claim `_PICKER_ENFORCED_CONTROLLERS`
        # states above, made here as well. The linked-duration branch has
        # carried it since Scarwood Bandits; the permanent steal refused it, so
        # every "gain control of target X <seat> controls" in the pool was
        # unsupported for a narrowing the picker was already carrying out.
        controller = described.get("controller")
        if controller is not None and controller not in _PICKER_ENFORCED_CONTROLLERS:
            raise LoweringError(
                "the control change cannot test this restriction", node=node
            )
        if object_only_filter(
            described, carried_separately=frozenset({"controller"})
        ) is None:
            raise LoweringError(
                "the control change cannot test this restriction", node=node
            )
        _describe_targets(described, subject)
        return (OracleInstruction("gain_control_of_target", "", described),)
    if node.duration == "until_end_of_turn":
        if subject.quantifier in ("that", "it"):
            # "Gain control of **that creature** until end of turn."
            # (Disharmony.) "Untap target creature an opponent controls and gain
            # control of **it** until end of turn." (Ray of Command, Magus of
            # the Unseen.) The bound object, not a second choice — and bound by
            # id when the earlier step resolved, so a restated narrowing would
            # have nothing to narrow.
            #
            # The pronoun and the repeated noun are one referent (idiom 20), the
            # same pair `lowering/stack.py` and `lowering/prevention.py` already
            # read together. Only "that" was admitted here, so a card printing
            # the shorter spelling of the identical sentence refused.
            #
            # The **filter** is only checked on the repeated noun. A bare "it"
            # is parsed as the ability's own source (`rebinding.py`: that is
            # what the word means on a line naming nothing else), so its
            # `is_source` is the parser's default rather than a narrowing the
            # card printed — reading it as one is what refused this sentence.
            # `_lower_remove_from_combat` reads the identical pronoun the same
            # way, one production over, on the very card that prints both.
            if subject.quantifier == "that" and _restrictions_beyond(
                subject.filter, frozenset({"card_types"})
            ):
                raise LoweringError(
                    "a bound object carries no narrowing the record could honour",
                    node=node,
                )
            if _UNTAPPED_PERMANENTS not in produced:
                raise LoweringError(
                    f"back-reference to {_UNTAPPED_PERMANENTS!r} with no "
                    "producer in this effect",
                    node=node,
                )
            payload: dict[str, object] = {"permanents_from": _UNTAPPED_PERMANENTS}
            # "When you lose control of the creature, tap it." (Ray of Command,
            # Magus of the Unseen.) CR 603.7's delayed trigger, carried as a key
            # on the change it watches: the cleanup that ends an
            # until-end-of-turn control change is the one place control is lost,
            # so that is where the tap happens (engine/phases/cleanup_step.py).
            if node.tap_when_lost:
                payload["tap_when_lost"] = True
            return (OracleInstruction("gain_control_until_eot", "", payload),)
        if subject.quantifier != "target":
            raise LoweringError(
                "the linked-control handler needs a named target", node=node
            )
        described = _filter_payload(subject.filter)
        if object_only_filter(described) is None:
            raise LoweringError(
                "the control change cannot test this restriction", node=node
            )
        _describe_targets(described, subject)
        return (OracleInstruction("gain_control_until_eot", "", described),)
    if node.duration == "while_source_tapped":
        # "For as long as this creature remains tapped, gain control of target
        # creature **of an opponent's choice they control**." (Preacher.)
        #
        # Two instructions rather than one: the pick belongs to another seat, so
        # it is the ordinary ``choose_permanent`` prompt — armed on the opponent,
        # answered into the resolution's scratchpad — and the steal behind it
        # reads that answer instead of a target. Both halves already exist; what
        # is new is only the pairing.
        #
        # A deliberate, recorded deviation from CR 601.2c: the printed word is
        # "target", and a target is chosen as the ability is *activated*. This
        # engine's activation flow announces targets from one seat, so the
        # opponent's pick is made at resolution instead. What that costs is the
        # 608.2b re-check and shroud on the picked creature; what the
        # alternative costs is a second seat inside the announcement step.
        if subject.quantifier != "target" or not subject.filter.chosen_by_opponent:
            raise LoweringError(
                "the tapped-source link is printed on a choice an opponent "
                "makes",
                node=node,
            )
        described = _filter_payload(
            subject.filter, carried_separately=frozenset({"chosen_by_opponent"})
        )
        # The candidate rule asks `subject_matches` with the ability's seat as
        # observer, so the gate is what that answers — including `controller`,
        # which is exactly the key this phrase carries and which the
        # object-only subset the other branches use would refuse.
        if untestable_filter_keys(described):
            raise LoweringError(
                "the control change cannot test this restriction", node=node
            )
        return (
            OracleInstruction(
                "choose_permanent", "",
                {
                    "result_key": CHOSEN_PERMANENT,
                    "chooser": "opponent",
                    # The candidates come from the chooser's own battlefield —
                    # "they control" — which is a seat question the filter's
                    # `controller` key answers only relative to the *ability's*
                    # controller. In a two-player game the two agree; with three
                    # seats they do not, and the printed word is "they".
                    "controlled_by": "chooser",
                    "filter": described,
                    "prompt": "Choose a creature you control.",
                },
            ),
            OracleInstruction(
                "steal_target_linked_to_source", "",
                {
                    "permanents_from": CHOSEN_PERMANENT,
                    "link_conditions": ["source_remains_tapped"],
                },
            ),
        )
    if node.duration == "while_source_on_battlefield":
        # "…for as long as this creature remains on the battlefield" (Scarwood
        # Bandits). The same monitored contribution the two-condition steal
        # records, with the one weaker condition — so it is that instruction
        # with a different `link_conditions` list rather than a kind of its own:
        # what differs is which fact the sweep re-checks, and that is data.
        if node.gained_by is not None:
            # "An opponent may gain control of a creature you control of their
            # choice for as long as this creature remains on the battlefield."
            # (Infernal Denizen.) Preacher's decomposition — the pick belongs to
            # another seat, so it is the ordinary ``choose_permanent`` prompt and
            # the steal behind it reads the answer — with the two facts Preacher
            # does not print: the offer ("may", carried as the prompt's own
            # ``optional``) and the *new controller*, who is the seat picking
            # rather than the ability's own.
            return _lower_offered_steal(node, subject)
        if subject.quantifier != "target":
            raise LoweringError(
                "the linked-control handler needs a named target", node=node
            )
        described = _linked_steal_filter(node, subject)
        described["link_conditions"] = ["source_on_battlefield"]
        return (OracleInstruction("steal_target_linked_to_source", "", described),)
    if node.duration == "while_you_control_source_tapped":
        # Willow Satyr / Rubinia Soulsinger. The filter must be one the
        # resolution can test (Willow's "legendary" is the supertypes key),
        # and the conditions are payload data so the sweep stays one reader.
        if subject.quantifier != "target":
            raise LoweringError(
                "the linked-control handler needs a named target", node=node
            )
        described = _linked_steal_filter(node, subject)
        described["link_conditions"] = [
            "you_control_source", "source_remains_tapped",
        ]
        return (OracleInstruction("steal_target_linked_to_source", "", described),)
    # while_you_control_source
    if (
        subject.quantifier == "all"
        and subject.filter.blocking_source
        and not _restrictions_beyond(
            subject.filter, frozenset({"card_types", "blocking_source"})
        )
        and subject.filter.card_types == ("creature",)
    ):
        # "Gain control of all creatures blocking this creature…"
        # (The Wretched.) The set was fixed when the trigger fired
        # (CR 611.2c): the end-of-combat dispatcher captures the blockers by
        # id into the trigger context, because by resolution the combat
        # record has been cleared.
        return (
            OracleInstruction(
                "steal_blockers_of_source", "",
                {"link_conditions": ["you_control_source"]},
            ),
        )
    if subject.quantifier != "target":
        raise LoweringError("the linked-control handler needs a named target", node=node)
    described = _linked_steal_filter(node, subject)
    described["link_conditions"] = ["you_control_source"]
    return (OracleInstruction("steal_target_linked_to_source", "", described),)


#: The instruction an auction for a permanent's control lowers to. One kind for
#: the whole template: who bids, what they bid for and the opening number are
#: payload, so a second card printing the same procedure needs no dispatch.
BID_LIFE_FOR_CONTROL_KIND = "bid_life_for_control"


def _lower_bid_life_for_control(
    node: ast.BidLifeForControl,
) -> tuple[OracleInstruction, ...]:
    """``Each player may bid life for control of target creature.`` and its
    procedure (Illicit Auction).

    The target is described exactly as the indefinite steal above describes
    its own, and for the same two reasons: the picker enumerates the printed
    noun phrase, and the handler re-checks it at resolution (CR 608.2b). What
    is different is only *who* ends up with it — the high bidder rather than
    the resolving object's controller — and that is decided while the spell
    resolves rather than by this payload.

    Two narrowings refuse rather than being dropped. The bidding must be
    offered to **each player**: the round-robin the handler walks is turn
    order over every seat, and a sentence naming a smaller set would be read
    as offering it to everybody. And the subject must be a **named target**,
    because the auction's winner takes one permanent and nothing here could
    choose which of several it was.
    """
    if not isinstance(node.bidders, ast.PlayerRef) or node.bidders.kind != "each_player":
        raise LoweringError(
            "the only auction the engine runs is offered to each player",
            node=node,
        )
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or not _is_target(subject):
        raise LoweringError("the auction needs a named target", node=node)
    described = _filter_payload(subject.filter)
    controller = described.get("controller")
    if controller is not None and controller not in _PICKER_ENFORCED_CONTROLLERS:
        raise LoweringError(
            "the auction cannot test this restriction", node=node
        )
    if object_only_filter(
        described, carried_separately=frozenset({"controller"})
    ) is None:
        raise LoweringError("the auction cannot test this restriction", node=node)
    _describe_targets(described, subject)
    described["starting_bid"] = int(node.starting_bid)
    return (OracleInstruction(BID_LIFE_FOR_CONTROL_KIND, "", described),)

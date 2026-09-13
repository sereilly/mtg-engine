"""Lowering board changes: bouncing, regeneration, sacrifice, phasing.

Regeneration, sacrifice (as an effect, as a toll, and as the complement of a
keep), phasing out, and putting a permanent back on the bottom of a library.

Destruction left for ``destruction`` at the thousand-line guard; tapping left
for ``tapping`` one round earlier; Juxtapose's exchange left for
``control_changes`` at Exodus's second wave, the round its AST node moved to
``ast/control_changes.py`` — so the mirror re-formed on all three sides rather
than forking. What stays is what the CR calls something else.

**The "… unless <someone> pays" productions are all here**, which is the one
place that split cut a production family in half rather than along it. All
three are parsed in ``effects/board.py`` — "sacrifice this permanent unless you
pay", "destroy this creature unless you pay", "for each land, destroy that land
unless any player pays 1 life" — and they are one printed shape with three
verbs: an *offer*, whose refusal is the effect. Two of them left with CR 701.8
and one did not, so the mirror forked; they came back when the fused
cost-repeated destroy pushed ``destruction`` past the thousand-line guard and
the boundary the guard asked about turned out to be this one.

Control changes lower to a *contribution* rather than a move — see
`engine/control.py`. What lowering owes is the timestamped source, not a new
owner.
"""

import dataclasses

from ...oracle_types import (CHOSEN_TARGET_PERMANENTS,
                             X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT,
                             OracleInstruction)
from ...subject_filters import object_only_filter, untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._amounts import halved_count_spec
from ._sacrifices import _forced_sacrifice_filter
from ._common import (_describe_targets, _filter_payload,
                      _is_enchanted, _is_source, _is_target,
                      player_deed_payload)
from ._events import (ATTACHED_SUBJECT_EVENTS, CHOSEN_PLAYER, LOOP_BOUND_OBJECT, OTHER_CHOSEN_PERMANENT, _EVENT_SUBJECT_CONTROLLERS, _EVENT_SUBJECT_PLAYERS, EVENT_SUBJECT_CONTROLLER, EVENT_SUBJECT_PLAYER, names_attached_permanent, CHOSEN_PERMANENT, _RECORDED_PERMANENTS, _back_reference_payload)
from ._delays import (_BOUND_OBJECT_DELAYED_EVENTS)


#: Where a chosen attachment host is recorded for the step behind it to read.
#: One name in one place, because the two instructions the lowering emits have
#: to agree about it and a literal written twice is two chances to disagree.


# ---------------------------------------------------------------------------
# Destruction, tapping, zones
# ---------------------------------------------------------------------------

# "Destroy all X" shapes with a dedicated sweep handler.


def _lower_put_on_library_bottom(node: ast.PutOnLibraryBottom) -> tuple[OracleInstruction, ...]:
    """"Put target card from your graveyard on the bottom of your library."
    (Epitaph Golem.) Only that exact scope has a handler: the card comes out
    of the caster's own graveyard and goes under their own library."""
    spec = node.target
    if not isinstance(spec, ast.TargetSpec) or not _is_target(spec):
        raise LoweringError("the bottoming handler reads one chosen card", node=node)
    filt = spec.filter
    if not filt.is_card or filt.zone != "graveyard" or (
        filt.zone_owner is None or filt.zone_owner.kind != "you"
    ):
        raise LoweringError(
            "the bottoming handler reads the caster's own graveyard", node=node
        )
    if filt != ast.ObjectFilter(is_card=True, zone="graveyard", zone_owner=filt.zone_owner):
        raise LoweringError("no bottoming handler honours this restriction", node=node)
    return (OracleInstruction("put_graveyard_card_on_library_bottom", "", {}),)


def _lower_put_graveyard_top_on_library_bottom(
    node: ast.PutGraveyardTopOnLibraryBottom,
) -> tuple[OracleInstruction, ...]:
    """"Put the top card of your graveyard on the bottom of your library."
    (Soldevi Digger.)

    Its own kind rather than a payload flag on the bottoming above it: that one
    is a *target*, and `engine/targeting.py` maps a kind to a picker — a flag
    could not stop the picker asking for a graveyard card this sentence never
    lets anyone choose. No payload at all, because the node carries none: the
    zone, whose it is and which card are all fixed by the printed words.
    """
    return (
        OracleInstruction("put_top_of_graveyard_on_library_bottom", "", {}),
    )


def _lower_regenerate(node: ast.Regenerate) -> tuple[OracleInstruction, ...]:
    """"Regenerate target creature" / "Regenerate this creature" (CR 701.19).

    Three handlers exist, differing in *what* they shield: the spell's target,
    the ability's own source, or the creature an Aura enchants. Picking by the
    subject keeps each one's contract rather than routing everything through
    the targeted one, which would shield the wrong creature.
    """
    subject = node.subject
    if _is_enchanted(subject):
        return (OracleInstruction("grant_regeneration_to_enchanted_creature", "", {}),)
    if _is_source(subject):
        return (OracleInstruction("grant_regeneration_to_self", "", {}),)
    if not (isinstance(subject, ast.TargetSpec) and subject.quantifier == "target"):
        raise LoweringError("no handler for regenerating this subject", node=node)
    filt = subject.filter
    # The printed narrowing is payload, not a hand-listed key. Elephant
    # Graveyard's "target Elephant" and Horror of Horrors' "target black
    # creature" are the same noun phrase, and the shield's eligibility test is
    # the one matcher every other filter reader uses. What must not ride along
    # is a narrowing that matcher cannot answer — the shield would land on a
    # creature the card never named — so the payload is gated by
    # `object_only_filter`: the resolution picks from a single player's
    # battlefield, with no observer seat and no source to compare against.
    described = _filter_payload(filt)
    carried = object_only_filter(described)
    if carried is None:
        raise LoweringError("no handler honours this regenerate restriction", node=node)
    payload: dict[str, object] = dict(carried)
    _describe_targets(payload, subject)
    return (OracleInstruction("grant_regeneration_to_target_creature", "", payload),)


# Who a sacrifice can be owed by. "You" is the absent value — a bare imperative
# means the effect's own controller — so it is the one payer with no key.
#
# ``target_opponent`` and ``target_player`` stay apart even though the handler
# resolves both to the seat the spell chose: CR 115.4 makes them different
# spells, and collapsing them would offer the caster's own seat as a legal
# target for "target **opponent** sacrifices".
#
# ``that_player`` is the seat a trigger's own condition named ("at the beginning
# of **each player's** upkeep, **that player** sacrifices …", Mana Vortex). It
# is admitted only under an event that freezes one — see ``_lower_sacrifice``.
#
# ``each_player`` is Pox's, and it is `each_opponent` plus the caster: the prompt
# is owed by every living seat rather than by every living opponent, which is
# one more entry in the same list the handler already builds.


# ``controller`` is the possessive with nothing in front of it — "**its**
# controller sacrifices a creature of their choice" (Funeral March). It names
# the controller of the object the *trigger's own event* was about, which is
# the same seat ``that_player`` resolves to under an object event, reached by a
# pronoun instead of a demonstrative. Admitted only under an event that freezes
# one, exactly as ``that_player`` is: without that gate "its" would fall
# through to the handler's unknown-payer branch, or worse, to the caster.
_SACRIFICE_PAYERS: frozenset[str] = frozenset(
    {
        "you", "each_player", "each_opponent", "target_opponent",
        "target_player", "that_player", "controller",
    }
)

# Two keys the forced-sacrifice prompt performs rather than tests, so they are
# lifted out of the filter instead of refusing the line:
#
# - ``exclude_self`` ("sacrifice **another** creature") rides beside the filter
#   as the prompt's own ``exclude`` argument, which compares by identity — a
#   look-alike on the same battlefield is a different permanent.
# - ``their_choice`` ("a creature **of their choice**", Run Afoul) says the
#   sacrificing player picks, which is what CR 701.21a already says and what the
#   prompt already does. It is read and dropped here, at a lowering whose rule
#   puts the choice there; anywhere else the word refuses.
#
#   "Anywhere else the word refuses" was a claim and not a mechanism until The
#   Abyss: ``to_payload`` emits ``their_choice`` so a gate can see it, but only
#   the gates asking "are all these keys testable?" look, and the single-target
#   destroy asked none — so the word rode into the payload, nothing read it, and
#   the ability's controller picked. ``_filter_payload`` now refuses it unless
#   the call site names it in ``carried_separately``, which is what makes the
#   sentence above true of every lowering rather than of this one.


def _per_payer_count(node: ast.Sacrifice) -> dict:
    """How many *this payer* sacrifices, as a spec the evaluator answers per
    seat. ("…sacrifices a third of the creatures they control", Pox; "…for each
    white permanent they control", Omen of Fire.)

    The two narrowings the printed phrase carries are stripped before the count
    is built, and neither is a narrowing lost:

    * **"they control"** is CR 701.21a restated — a player can only sacrifice
      what they control — and the evaluator is already owner-scoped, so handing
      it the key would make ``count_spec`` refuse a phrase that says nothing.
    * **"of their choice"** is whose decision it is, not what may be chosen;
      the prompt is the decision.

    The stripping runs over the counted set wherever it sits — under a
    fraction (Pox) or as the whole amount (Omen of Fire) — because it is a fact
    about the *phrase*, not about the arithmetic wrapped around it. Written as
    one rewrite for that reason: two copies would be two chances for one
    spelling to keep a key the other drops.
    """
    def _stripped(counted: "ast.CountOf") -> "ast.CountOf":
        return ast.CountOf(
            dataclasses.replace(counted.filter, controller=None, their_choice=False)
        )

    counted = node.count
    if isinstance(counted, ast.Half) and isinstance(counted.of, ast.CountOf):
        counted = dataclasses.replace(counted, of=_stripped(counted.of))
    elif isinstance(counted, ast.CountOf):
        counted = _stripped(counted)
    spec = halved_count_spec(counted, node)
    if spec is None:
        raise LoweringError(
            "the sacrifice prompt sizes itself from a counted fraction", node=node
        )
    return spec


def _bound_sacrifice_filter(
    subject: "ast.TargetSpec", produced: frozenset[str]
) -> dict:
    """The filter payload for a sacrifice addressed by the delay's bound id.

    "Put target creature **card from a graveyard** onto the battlefield under
    your control … When this enchantment leaves the battlefield, that creature's
    controller sacrifices it." (Necromancy.) The back-reference takes its noun
    phrase from the sentence in front of it, so it still reads "card in a
    graveyard" — and by the time the delay fires, what those words name is the
    **permanent** that step put onto the battlefield, which CR 400.7 makes a
    different object from the card. Dropping exactly the two card-in-a-zone
    words is reading the phrase rather than losing part of it; every other
    narrowing it carries goes into the payload and is tested.

    Gated on a producer, for the reason ``counters.py``'s Bogardan Phoenix
    branch is gated on the same set one family over: only a step that put a card
    onto the battlefield changes what the pronoun is about, and without one "it"
    still means the card phrase it was printed beside.
    """
    filt = subject.filter
    if filt.is_card and filt.zone == "graveyard" and (produced & _RECORDED_PERMANENTS):
        filt = dataclasses.replace(filt, is_card=False, zone="battlefield")
    return _filter_payload(filt)


def _lower_sacrifice(
    node: ast.Sacrifice,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """Only "sacrifice this <permanent>" has a handler.

    Sacrificing something *chosen* ("sacrifice a creature") is a different
    problem: the choice belongs to a player, so it needs the pending-choice
    machinery rather than an instruction that acts on a known permanent.
    Refusing here keeps that distinction visible instead of quietly sacrificing
    the wrong thing.
    """
    # "Sacrifice a creature" / "sacrifice another creature" (Dire Fleet
    # Warmonger's optional cost): the *controller chooses* which, so this
    # arms the forced-sacrifice prompt rather than acting on a known
    # permanent.
    #
    # "Each opponent sacrifices a creature" (Goremand) and "Target opponent
    # sacrifices …" (Run Afoul) are the same prompt owed by a different set of
    # seats, so they are the same instruction with the payer named — never a
    # second kind. CR 701.21a says the sacrificing player chooses, which is
    # exactly what the prompt already does; the only thing that changes is who
    # is asked, and that is also what lets the printed "of their choice" be
    # read and then dropped rather than refused.
    # "…unless they sacrifice **that artifact**" (Curse Artifact) — the
    # permanent this Aura is attached to, which the trigger's own condition
    # named. Above the chosen-sacrifice prompt below and not routed through it:
    # "that artifact" is one known permanent, and "an artifact" is a pick from
    # every artifact its controller has, so a player with two of them would be
    # offered the wrong one to give up.
    if names_attached_permanent(node.subject, event):
        return (OracleInstruction("sacrifice_attached_permanent", "", {}),)
    from_chosen = _lower_sacrifice_one_of_chosen(node, produced)
    if from_chosen is not None:
        return from_chosen
    # "When this creature leaves the battlefield this turn, **sacrifice that
    # creature**." (Phantasmal Mount.) The object the creating ability bound
    # (CR 603.7c), carried by id in the trigger's context — the mirror of
    # ``destroy_bound_permanent`` one family over, and its own kind for the same
    # reason: routed through the chosen-sacrifice prompt below the ability would
    # ask its controller to pick, and Phantasmal Mount's rider is not a choice.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and not node.subject.targeted
        and event in _BOUND_OBJECT_DELAYED_EVENTS
    ):
        return (
            OracleInstruction(
                "sacrifice_bound_permanent", "",
                _bound_sacrifice_filter(node.subject, produced),
            ),
        )
    # "**That creature's controller sacrifices it** at end of combat." (Basalt
    # Golem.) The same sentence with the object named in the *possessive* and
    # the subject left a pronoun — and the seat it names is the one CR 701.21a
    # would have picked anyway, because a permanent is sacrificed by whoever
    # controls it. So the possessive says out loud what the action already
    # implies, and the two printed spellings are one instruction rather than two
    # readings of a seat.
    #
    # Beside the "that <noun>" branch above and under the same gate: the
    # pronoun was rebound to the *trigger's* subject by
    # `rebind_pronoun_to_event_subject`, which is what makes it name the blocked
    # creature and not the Golem, and the delay is what makes the id the only
    # way to find it again at end of combat.
    #
    # Above the forced-sacrifice prompt below, which would otherwise claim it:
    # routed there, the blocked creature's controller would be asked to pick
    # *any* creature to give up, which is a strictly better card than the one
    # printed.
    if (
        node.player.kind == "that_player"
        and isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "it"
        and not node.subject.targeted
        and event in _BOUND_OBJECT_DELAYED_EVENTS
    ):
        return (
            OracleInstruction(
                "sacrifice_bound_permanent", "",
                _bound_sacrifice_filter(node.subject, produced),
            ),
        )
    if (
        node.player.kind in _SACRIFICE_PAYERS
        and isinstance(node.subject, ast.TargetSpec)
        and not node.subject.targeted
        and not _is_source(node.subject)
    ):
        described = _forced_sacrifice_filter(node.subject.filter)
        if described is None:
            raise LoweringError(
                "the sacrifice prompt cannot test this restriction", node=node
            )
        payload: dict[str, object] = {"filter": described}
        # "…**each player who tapped a land for mana this turn** sacrifices a
        # land of their choice." (Desolation.) Which of the payers the printed
        # clause actually names, carried to the handler that builds the list —
        # the *only* reader, which is why the clause is parsed nowhere else.
        # Raises rather than dropping the narrowing, so a clause no record
        # answers takes the card down instead of asking every seat at the
        # table.
        deed = player_deed_payload(node.player, node)
        if deed is not None:
            payload["who_did"] = deed
        # "…sacrifice **any number of creatures with total power 12 or
        # greater**." (Phyrexian Dreadnought.) Its own kind rather than a
        # payload key on the prompt beside it, because the two ask different
        # questions of the seat and validate different answers: that one owes a
        # printed number of permanents, this one owes *any* number whose
        # aggregate clears a floor — and a set of five may be legal where a set
        # of six is not, which no count can say. Emitted before the count
        # branches below, none of which applies: "any number" is the absence of
        # a printed count.
        if node.total_at_least is not None:
            if node.player.kind != "you":
                raise LoweringError(
                    "only the effect's own controller is asked for an "
                    "aggregate sacrifice", node=node,
                )
            characteristic, minimum = node.total_at_least
            payload["characteristic"] = characteristic
            payload["at_least"] = int(minimum)
            if node.subject.filter.other_than_source:
                payload["exclude_self"] = True
            return (
                OracleInstruction("sacrifice_permanents_totalling", "", payload),
            )
        # "…sacrifices **a third of** the creatures they control of their
        # choice." (Pox.) One number per seat, so it cannot be the printed
        # count: it is a fraction of *that* player's board, and the handler
        # asks the evaluator once per payer through the same channel the
        # per-recipient damage and the each-player discard already use.
        if isinstance(node.count, ast.CountOfDeaths):
            # "…sacrifices a creature of their choice **for each creature put
            # into your graveyard from the battlefield this turn**." (Urborg
            # Justice.) One number for the whole resolution, not one per payer:
            # the graveyard the clause names is the *caster's* (CR 400.3's
            # owner), so it goes on the shared `x_from_count` channel rather
            # than the per-recipient one beside it. Read through the
            # per-recipient key it would be answered against the sacrificing
            # opponent's own tally, which is a different card — and one that
            # asks for nothing whenever they lost no creatures.
            filt = node.count.filter
            if (
                filt.to_payload() != {"type_filter": "creature"}
                or filt.zone != "battlefield"
            ):
                # The tally counts creatures and nothing narrower, so a
                # narrowing admitted here would be counted as though it were
                # not there — a player made to sacrifice more often than the
                # card says. Word for word `_lower_where_x_deaths`' refusal,
                # because it is the same tracker.
                raise LoweringError(
                    "the death tracker counts creatures and cannot be narrowed",
                    node=node,
                )
            payload["count"] = "x"
            payload[X_FROM_COUNT] = {
                "history": f"creatures_{node.count.scope}"
            }
        elif isinstance(node.count, ast.CountersOnSource):
            # "…that player sacrifices a permanent of their choice **for each
            # soot counter on this artifact**." (Smokestack.) One number for
            # every payer, and on the *shared* channel beside Urborg Justice's
            # for that branch's reason: the pile sits on the ability's own
            # source, which is the same object whoever the upkeep belongs to.
            # Read per-payer it would be counted on a permanent the payer does
            # not control and answer zero every time.
            payload["count"] = "x"
            payload[X_FROM_COUNT] = {"source_counters": node.count.kind}
        elif node.count is not None:
            payload[X_FROM_COUNT_PER_RECIPIENT] = _per_payer_count(node)
        elif node.subject.quantifier == "any_number":
            # "**Sacrifice any number of** artifacts, creatures, and/or lands."
            # (Reprocess.) A ceiling with no printed number, which the noun
            # phrase carries as a count of **zero** — and zero is what the
            # handler owed, so the sentence sacrificed nothing and the draw
            # behind it drew nothing, with the card reporting itself supported.
            #
            # So it travels as a flag and the handler sizes the prompt from the
            # board, exactly as the each-player discard's "any number" (Flux)
            # already does: the bound is the seat's own permanents and only the
            # resolution knows it. The word carries its own "may" — none is a
            # legal answer — which is what ``up_to`` means on that prompt.
            payload["any_number"] = True
        elif node.subject.count_amount is not None:
            # "Whenever this creature is dealt damage, sacrifice **that many**
            # permanents." (Phyrexian Negator.) The count is the firing event's
            # own number, so it is asked of the one reader that decides where a
            # back-reference lives — the scratchpad of this resolution, or the
            # context the fire site froze. Asking it here rather than assuming
            # the trigger is what makes the refusal honest: an event that
            # freezes no quantity raises `LoweringError` and the card is
            # reported unsupported, where a hard-coded trigger key would read an
            # absent record as **zero** and sacrifice nothing while logging
            # itself resolved.
            #
            # The keys are the pool's existing ones (`amount_from_trigger` /
            # `amount_from`) rather than a `count_`-prefixed fork: four handlers
            # already read that vocabulary for the same question — "the number
            # this sentence spends, named by something outside it" — and a
            # second spelling would be a second answer.
            payload.update(
                _back_reference_payload(node.subject.count_amount, produced, event)
            )
        elif node.subject.count_from_x:
            # "Each player sacrifices **X** lands of their choice." (Tectonic
            # Break.) CR 107.3's announced X, which is not known until the spell
            # is cast — so it travels as the pool's existing ``"x"`` spelling
            # and the handler resolves it against ``context.x_value``, the same
            # channel every other announced X already reads.
            #
            # Ahead of the printed-count branch below rather than after it,
            # because the flag carries a count of **zero**: read as a number
            # this would sacrifice nothing whatever X was announced at, which is
            # the same silent direction the flag exists to avoid.
            payload["count"] = "x"
        elif node.subject.count != 1:
            # "Sacrifice **two** Swamps" (Mold Demon). How many is payload on
            # the one prompt, never a second kind: the forced-sacrifice queue
            # has taken a count since it was written, and it was the lowering
            # that only ever passed one.
            payload["count"] = node.subject.count
        if node.subject.filter.other_than_source:
            # "…unless they sacrifice **another** creature of their choice."
            # (Unnatural Hunger.) Under a trigger printed about the attached
            # permanent (:data:`ATTACHED_SUBJECT_EVENTS`) the antecedent of
            # "another" is that permanent, not the ability's source — an Aura
            # is not a creature, so ``exclude_self`` on a creature filter rules
            # out nothing at all and the enchanted creature is offered as its
            # own way out. Silent, and strictly in the card's favour.
            #
            # It rides the **same** ``exclude`` channel ``exclude_self`` does
            # rather than a filter key, because that channel is the one already
            # threaded end to end: the takeability gate, the inline resolution
            # and the queued prompt all compare it by identity, where a filter
            # key would need ``subject_matches`` to be handed the ability's
            # source and the sacrifice readers do not pass one. Which permanent
            # to leave out is the only thing that differs.
            #
            # Pool-wide this reaches exactly one card, measured at the round
            # rather than assumed.
            payload[
                "exclude_attached_host" if event in ATTACHED_SUBJECT_EVENTS
                else "exclude_self"
            ] = True
        if node.player.kind == "that_player":
            # "At the beginning of each player's upkeep, **that player**
            # sacrifices a land of their choice." (Mana Vortex.) The seat the
            # firing event named, which varies per firing and so is frozen by
            # the fire site rather than re-derived at resolution — the same
            # table and the same reason the damage lowering reads it (idiom 6).
            # An event that freezes no such seat refuses the line: reading an
            # absent key would sacrifice the *source controller's* land on
            # every upkeep, which is a different card that happens to work.
            # "Whenever a creature dies, **that creature's controller**
            # sacrifices a land of their choice." (Earthlink.) The possessive
            # reaches the AST as the same `that_player`, so the two tables are
            # read in turn exactly as the damage lowering reads them: one
            # freezes the seat the event was *about*, the other the seat that
            # *controlled* what it was about, and they name disjoint events —
            # so the order is documentation rather than precedence.
            if event in _EVENT_SUBJECT_PLAYERS:
                payload["who"] = EVENT_SUBJECT_PLAYER
            elif event in _EVENT_SUBJECT_CONTROLLERS:
                payload["who"] = EVENT_SUBJECT_CONTROLLER
            elif event is None:
                # "Target opponent loses 2 life unless **that player**
                # sacrifices a permanent of their choice." (Forbidden Ritual.)
                # A line with no firing event has no frozen seat to read and
                # needs none: the words are a back-reference to a player *this
                # sentence* named, which at resolution is the seat the spell
                # chose. That is the reading `discard_target_cards` has always
                # given the identical printed pronoun one family over — it
                # admits `that_player` with no event gate at all and lets the
                # handler read `context.target` — so the two spellings of one
                # printed price name one seat rather than two.
                #
                # The two branches above stay ahead of it and keep their gate:
                # under a *trigger* "that player" is the seat the fire site
                # froze, and reading `context.target` there would sacrifice the
                # source controller's land on every upkeep.
                payload["who"] = "that_player"
            else:
                raise LoweringError(
                    f"no event named {event!r} freezes the seat 'that player' names",
                    node=node,
                )
        elif node.player.kind == "controller" and LOOP_BOUND_OBJECT in produced:
            # "For each creature, **its controller** sacrifices a permanent of
            # their choice unless they pay {1}." (Fade Away.) Inside a loop
            # over objects the possessive names the iteration's own object,
            # which is the innermost binding — the handler resolves it through
            # ``bound_permanent``, whose contract is exactly that, so the seat
            # asked and the seat charged are one answer.
            #
            # Read before the frozen-seat branch below, because a loop binds
            # the pronoun more tightly than the firing event does: under
            # Earthlink's trigger there is no loop and the event's seat is the
            # only one there is, and here the event is not what the sentence is
            # about.
            payload["who"] = "controller"
        elif node.player.kind == "controller":
            # "When enchanted creature leaves the battlefield, **its
            # controller** sacrifices a creature of their choice." (Funeral
            # March.) The possessive names the departing host's controller, not
            # the Aura's — they are different seats whenever the Aura is on an
            # opponent's creature, which is every printing of this card that
            # matters. By resolution the host is in a graveyard, an exile or a
            # hand, so the seat is the one the fire site froze (CR 603.10,
            # idiom 6) rather than one re-derived here.
            if event not in _EVENT_SUBJECT_CONTROLLERS:
                raise LoweringError(
                    f"no event named {event!r} freezes the seat 'its controller' names",
                    node=node,
                )
            payload["who"] = EVENT_SUBJECT_CONTROLLER
        elif node.player.kind != "you":
            payload["who"] = node.player.kind
        return (OracleInstruction("sacrifice_matching_permanent", "", payload),)
    if not _is_source(node.subject):
        raise LoweringError("no handler for sacrificing a chosen permanent", node=node)
    if node.player.kind != "you":
        raise LoweringError("no handler for another player sacrificing", node=node)
    return (OracleInstruction("sacrifice_self", "", {}),)


def _lower_sacrifice_expansion_permanents(
    node: ast.SacrificeExpansionPermanents,
) -> tuple[OracleInstruction, ...]:
    """Golgothian Sylex. The set code was resolved at parse time from the
    manifest, so the instruction carries which set rather than which words."""
    return (
        OracleInstruction(
            "sacrifice_expansion_permanents", "", {"set_code": node.set_code}
        ),
    )


def _lower_delayed_self_action(
    node: ast.DelayedSelfAction,
) -> tuple[OracleInstruction, ...]:
    """Rocket Launcher / Rakalite. The action is payload, the delay is the kind
    — because what a reader downstream must not get wrong is *when*."""
    return (
        OracleInstruction(
            # Keyed `self_action`, not `action`: a payload key called
            # "action" is read as *nested instructions* by the composition
            # readers (test_front_end_safety's flattener among them), and a
            # bare word sitting where a list of steps is expected is a crash
            # rather than a wrong answer — but only because something looked.
            "arm_self_action_at_next_end_step", "",
            # The referent rides beside the action for the same reason the
            # action does: one sentence, one kind, and what differs is data.
            # Absent for "this artifact", so every payload written before Glyph
            # of Destruction is byte-identical.
            {"self_action": node.action}
            | ({"subject": node.subject} if node.subject != "source" else {}),
        ),
    )


def _lower_exile_one_of_chosen(
    node: "ast.Exile", subject, produced: frozenset[str]
) -> tuple[OracleInstruction, ...] | None:
    """"Exile **one of those creatures** and put two +1/+1 counters on the
    other." (Cannibalize.)

    ``_lower_sacrifice_one_of_chosen`` above one verb over, and the same
    decomposition: the pick is an ordinary ``choose_permanent`` prompt whose
    candidates are the set an *earlier sentence* chose, and the exile behind it
    acts on the recorded id. Offered over the board instead, the caster could
    exile any creature at all, which is a strictly better card than the printed
    one.

    **The chooser is the ability's controller** (CR 608.2c), which is the whole
    difference from Retribution: that card says "*that player* chooses" and
    names a seat, and this one says nothing — so no ``chooser`` rides the
    payload and the prompt is armed on the caster, which is what an unassigned
    choice means.

    Returns None without claiming the sentence unless the subject really is one
    member of a chosen set, so every ordinary "exile target creature" keeps its
    own reading. With the quantifier present and no set recorded the line
    *refuses*: "those creatures" would name nothing and the prompt would be
    offered an empty list, which is an exile that quietly happens to nobody.
    """
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "one_of_those"
    ):
        return None
    if CHOSEN_TARGET_PERMANENTS not in produced:
        raise LoweringError(
            "\"one of those\" needs an earlier step of this effect that chose "
            "a set",
            node=node,
        )
    described = _filter_payload(subject.filter)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the exile prompt cannot test this restriction", node=node
        )
    return (
        OracleInstruction(
            "choose_permanent", "",
            {
                "result_key": CHOSEN_PERMANENT,
                # Named as a record rather than copied into a filter, because
                # "those creatures" is an identity and no filter describes it.
                "among_record": CHOSEN_TARGET_PERMANENTS,
                # "…and put two +1/+1 counters on **the other**" is the step
                # behind this one, and this is where the answer to it exists.
                "remainder_key": OTHER_CHOSEN_PERMANENT,
                "filter": described,
                "prompt": "Choose a creature to exile.",
            },
        ),
        OracleInstruction(
            "exile_recorded_permanent", "",
            {"permanents_from": CHOSEN_PERMANENT},
        ),
    )


def _lower_sacrifice_one_of_chosen(
    node: ast.Sacrifice, produced: frozenset[str]
) -> tuple[OracleInstruction, ...] | None:
    """"That player chooses and sacrifices **one of those creatures**."
    (Retribution.)

    Preacher's decomposition again (``destruction._lower_destroy_of_their_choice``
    states it in full): the pick belongs to a seat that is not the effect's
    controller, so it is the ordinary ``choose_permanent`` prompt — armed on
    that seat, answered into the resolution's scratchpad — and the sacrifice
    behind it acts on the recorded id. What is new is only that the candidates
    are a set an *earlier sentence* chose rather than a battlefield the prompt
    scans: a sacrifice offered over the board would let the player give up any
    creature they own, which is a strictly better card than the one printed.

    Returns None without claiming the sentence unless every part is there, so
    an ordinary "sacrifices a creature" keeps its own reading:

    * the subject must be one member of the chosen set (``one_of_those``);
    * the sacrificing player must be the one the first sentence named
      (``that_player``), and a step of this same effect must have recorded that
      seat — with no producer "that player" names nobody and the prompt would
      be armed on the caster, who is exactly the seat the card says must not
      choose (idiom 7);
    * that step must also have recorded the set, or there is nothing to offer.
    """
    subject = node.subject
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "one_of_those"
        and node.player.kind == "that_player"
        and node.count is None
    ):
        return None
    if CHOSEN_TARGET_PERMANENTS not in produced or CHOSEN_PLAYER not in produced:
        raise LoweringError(
            "\"one of those\" needs an earlier step of this effect that chose "
            "a set and named its controller",
            node=node,
        )
    described = _filter_payload(subject.filter)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the sacrifice prompt cannot test this restriction", node=node
        )
    return (
        OracleInstruction(
            "choose_permanent", "",
            {
                "result_key": CHOSEN_PERMANENT,
                # "**That player** chooses": the seat the sentence in front of
                # this one recorded, not the ability's controller.
                "chooser": "chosen_player",
                # …and the candidates are that same sentence's set. Named as a
                # record rather than copied into a filter, because "those
                # creatures" is an identity and no filter describes it.
                "among_record": CHOSEN_TARGET_PERMANENTS,
                # "Put a -1/-1 counter on **the other**" is the step behind the
                # sacrifice, and this is where the answer to it exists.
                "remainder_key": OTHER_CHOSEN_PERMANENT,
                "filter": described,
                "prompt": "Choose a creature to sacrifice.",
            },
        ),
        OracleInstruction(
            "sacrifice_recorded_permanent", "",
            {"permanents_from": CHOSEN_PERMANENT},
        ),
    )


def _lower_rebalance_lands(node: "ast.RebalanceLands") -> tuple[OracleInstruction, ...]:
    """Natural Balance's whole paragraph, as one instruction.

    One payload key, because the production already reduced the card's four
    printed numbers to the one they agree on. Every seat's membership in either
    half and every count it owes is a function of that number and of a board the
    handler reads, so there is nothing else to carry.
    """
    if node.keep < 1:
        # A rebalancing that keeps nothing would be a one-sided Armageddon with
        # a tutor attached, and the "five minus" clause would count *up* from a
        # number the card never printed. No card prints it, and the refusal is
        # the loud failure rather than a handler improvising.
        raise LoweringError("a land rebalancing keeps at least one land", node=node)
    return (OracleInstruction("rebalance_lands", "", {"keep": node.keep}),)


#: Which seat the keep-and-sacrifice prompt is armed for, spelled as the
#: handler's ``who`` vocabulary. Absent means the effect's own controller,
#: which is what a bare imperative means (CR 109.5), and every other seat
#: refuses: a sacrifice armed for the wrong player is a card that takes
#: somebody else's board apart, which is the direction this repo does not guess
#: in. Deliberately shorter than ``sacrifice_matching_permanent``'s list — the
#: seats left out (``that_player``, the two targeted ones, the frozen-event
#: ones) are all *one* seat, and a sentence that keeps a set and sacrifices its
#: complement for one seat is a card nobody has printed.
_KEEP_SACRIFICE_SEATS = {
    "you": None,
    "each_player": "each_player",
    "each_opponent": "each_opponent",
}


def _keep_pool_filter(
    described: "ast.ObjectFilter", node: "ast.KeepChosenSacrificeRest"
) -> dict:
    """One printed noun phrase — the pool or a keep slot — as a filter payload.

    The possessive comes off **here** rather than inside
    ``_forced_sacrifice_filter``, and that is a real ordering rather than a
    preference. That helper asks "does this phrase name a set?" *before* it
    strips the controller, so a bare "the permanents they control" — which
    names no card type, no subtype and no colour — is refused for carrying a
    ``controller`` key it would have dropped one line later. Moving the strip
    inside it would admit every other card printing that shape and move their
    compiled programs, so the phrase is reduced on the way in instead.

    CR 701.21a is why dropping it is reading the phrase rather than losing part
    of it: a player can only sacrifice a permanent they control, and this
    prompt offers exactly the choosing seat's own board. Any *other* possessive
    names a third seat, which is a narrowing nothing here can honour.
    """
    if described.controller is not None:
        if described.controller not in ("you", "that_player"):
            raise LoweringError(
                f"a keep-and-sacrifice cannot be scoped to {described.controller!r}",
                node=node,
            )
        described = dataclasses.replace(described, controller=None)
    payload = _forced_sacrifice_filter(described)
    if payload is None:
        raise LoweringError(
            "the keeps cannot test what this noun phrase says", node=node
        )
    return payload


def _lower_keep_chosen_sacrifice_rest(
    node: "ast.KeepChosenSacrificeRest",
) -> tuple[OracleInstruction, ...]:
    """Cataclysm's whole sentence, and Limited Resources' entry trigger, as one
    instruction.

    One instruction rather than a choice followed by a sacrifice, because the
    two halves are one decision: what "the rest" means is fixed by the answer,
    so a sacrifice written as a separate step would have to read the choice back
    out of a scratchpad channel that has exactly one writer and one reader. The
    handler arms one prompt per seat and the prompt's *resolver* performs the
    complement, which is also what keeps CR 608.2's "nothing runs past an
    unanswered prompt" true for every seat at once.

    The pool and the slots are separate payload keys and both are required. A
    slot list alone cannot say what the complement is — Cataclysm's four keeps
    describe artifacts, creatures, enchantments and lands and its complement is
    *every* permanent — and a pool alone cannot say what may be kept.
    """
    if node.chooser.kind not in _KEEP_SACRIFICE_SEATS:
        raise LoweringError(
            f"no prompt asks {node.chooser.kind!r} to keep and sacrifice", node=node
        )
    if not node.slots:
        raise LoweringError("a keep-and-sacrifice keeps something", node=node)
    slots: list[dict[str, object]] = []
    for slot in node.slots:
        if slot.count < 1:
            # A slot that keeps nothing is not a keep; it would make the
            # sentence "sacrifice everything" with four nouns printed in front
            # of it. No card prints it and the refusal is the loud failure.
            raise LoweringError("a keep slot keeps at least one", node=node)
        slots.append(
            {"count": int(slot.count), "filter": _keep_pool_filter(slot.filter, node)}
        )
    payload: dict[str, object] = {
        "pool": _keep_pool_filter(node.pool, node),
        "slots": slots,
    }
    seat = _KEEP_SACRIFICE_SEATS[node.chooser.kind]
    if seat is not None:
        payload["who"] = seat
    return (OracleInstruction("keep_chosen_sacrifice_rest", "", payload),)

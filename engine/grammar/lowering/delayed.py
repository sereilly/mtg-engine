"""Lowering the sentences that arrange for something **later**.

A delayed triggered ability (CR 603.7) — "At the beginning of the next end
step, sacrifice it", "When that creature dies this turn, …" — and the two
sentences whose whole job is to record a choice a *later* one reads: "Choose
target creature" and Autumn Willow's shroud waiver.

It split off ``lowering/stack.py`` at Visions' second wave, when the counter's
"unless its controller pays {1} **and 1 life**" took that module past the
thousand-line guard. The line is the one that module's own section divider had
already drawn, and it is a real one: everything left in ``stack`` lowers a
sentence about an object **waiting on the stack right now** — countering it,
copying it, retargeting it, choosing a mode for it — where nothing here has a
stack object at all. What these produce is a *record*: an ability that will
trigger on an event that has not happened, or a target chosen now for a
sentence that runs later. Neither module reads the other.

**Two wave-2 groups made this split independently, in the same round, and the
seven functions they moved were byte-identical** — only these docstrings
differed. Neither knew the other was doing it; both were pushed over the guard
by their own card and both read the same section divider. That is the strongest
evidence this repo has produced that a family boundary was already there rather
than invented at the cap, and it is why the merge kept the code unchanged and
merely recorded the coincidence.

``effects/`` and ``ast/`` have no ``delayed`` for ``loops``' reason: the guard
fired on the lowerings, and ``CreateDelayedTrigger`` and ``ChooseTarget`` are
nodes that sit perfectly well beside the other statement and stack ones.
"""

import dataclasses

from ...oracle_types import CHOSEN_TARGET_PERMANENTS, OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._events import (_EVENT_SUBJECT_PLAYERS, _RECORDED_PERMANENTS,
                      CHOSEN_PLAYER, CREATED_TOKEN, binds_block_pair,
                      damage_trigger_names_damaged_end)
from ._common import (
    _REST_OF_TURN, _describe_several_targets, _describe_targets,
    _is_source, _names_several_targets, _restrictions_beyond,
    testable_filter_payload
)


def _delayed_filter_payload(filt: "ast.ObjectFilter | None", node) -> dict[str, object]:
    """A noun phrase the delayed trigger's fire site will test, or a refusal.

    The same gate ``_counter_targets_filter`` states, for the same reason and in
    the same direction: the fire site asks ``subject_matches``, so a key that
    matcher cannot answer would make the ability fire on a strictly larger set
    than the card prints. "Dealt damage by **an attacking creature**" is the
    whole difference between Glyph of Life and a card that gains life off any
    ping.
    """
    if filt is None:
        return {}
    return testable_filter_payload(
        filt,
        refusal="nothing tests a delayed trigger's subject by",
        node=node,
        require_narrowing=False,
    )


def _lower_choose_target(node: ast.ChooseTarget) -> tuple[OracleInstruction, ...]:
    """"Choose target creature." — the targeting half of a two-sentence spell.

    The instruction does nothing on resolution and that is the whole of it:
    CR 601.2c chooses the target as the spell is cast, and the sentence prints
    no effect. It exists so ``engine/targeting.py`` can derive what the spell
    targets from the compiled program, which is where every other card's
    picker comes from — the alternative is a second reading of the oracle text.
    """
    payload: dict[str, object] = {}
    if isinstance(node.subject, ast.PlayerRef):
        # "Choose target opponent." (Soldevi Sentry.) The player form, and a
        # different instruction rather than the same one over a different noun:
        # the object form's handler resolves a *permanent*, and it also records
        # nothing — where this one writes the chosen seat under the one key
        # "that player" is ever read from, because the sentence naming that seat
        # is a delayed ability created two sentences later and by then the
        # resolution that chose is over.
        _describe_targets(payload, node.subject)
        if "targets" not in payload:
            raise LoweringError("this 'choose' names no player", node=node)
        if node.chooser is not None:
            # "**That player** chooses target player who…" (the Oaths). The
            # seat the card says announces the target, carried into the same
            # description the picker reads — CR 601.2c's default is the
            # ability's controller, and under those cards' trigger that is a
            # different player from the one printed. Refused rather than
            # dropped for every other referent: a chooser the announcement
            # cannot resolve would silently fall back to the default, which is
            # the one player the card says does *not* pick.
            if node.chooser.kind != "that_player":
                raise LoweringError(
                    f"nothing announces a target for the {node.chooser.kind}",
                    node=node,
                )
            if payload["targets"].get("opponents_only"):
                # "Target **opponent**" is a narrowing the enumerator applies
                # against the seat that *announces* (CR 115.4), and a printed
                # chooser is precisely a card saying that seat is somebody
                # else. Enforced as it stands, the word would exclude the
                # ability's controller while the card excludes the chooser —
                # two different players. Refused rather than resolved to
                # either, exactly as the two-seat phrases elsewhere in this
                # package refuse.
                raise LoweringError(
                    "a printed chooser and \"target opponent\" name the "
                    "opponent of two different seats",
                    node=node,
                )
            payload["targets"]["chooser"] = node.chooser.kind
        payload["result_key"] = CHOSEN_PLAYER
        return (OracleInstruction("choose_target_player", "", payload),)
    if _names_several_targets(node.subject):
        # "Choose **X target attacking creatures**." (Winter's Chill.) A *set*,
        # and a different instruction rather than the same one with a count:
        # the singular handler resolves one permanent and the loop behind this
        # sentence has to walk every one of them, so the several-target form
        # records what it chose. Recording is the whole of what it does — the
        # targets were chosen as the spell was cast (CR 601.2c) — but nothing
        # else in the resolution can say which attacking creatures those were.
        _describe_several_targets(payload, node.subject)
        if node.subject.same_controller:
            # "…**controlled by the same opponent**" (Retribution). A relation
            # between the targets, so it rides the *description* the picker and
            # the CR 601.2c gate read rather than the filter every matcher
            # tests one permanent against — no such matcher could answer it.
            payload["targets"]["same_controller"] = True
        return (OracleInstruction("choose_target_permanents", "", payload),)
    _describe_targets(payload, node.subject)
    if "targets" not in payload:
        raise LoweringError("this 'choose' names no target", node=node)
    return (OracleInstruction("choose_target_permanent", "", payload),)


def _lower_waive_shroud(node: "ast.WaiveShroud") -> tuple[OracleInstruction, ...]:
    """"Until end of turn, Autumn Willow can be the target of spells and
    abilities controlled by **target player** as though it didn't have shroud."

    Refuses on two axes, both by name, exactly as ``_lower_attack_as_though``
    does for the other "as though" permission. The **duration** must be this
    turn's, because the waiver is a list of seats stamped on the permanent and
    swept by the cleanup step — a durationless printing would be a static
    ability nothing here ends. And the **player** must be one the activation
    chooses: a fixed seat is chosen by nobody (CR 115.1a), so a sentence naming
    one would arm the waiver for whoever the resolution happened to be carrying.
    """
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "a durationless shroud exception is a static ability, which "
            "nothing here would ever end",
            node=node,
        )
    if node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"the shroud exception is granted to a chosen player, not to "
            f"{node.player.kind!r}",
            node=node,
        )
    payload: dict[str, object] = {}
    _describe_targets(payload, node.player)
    if "targets" not in payload:
        raise LoweringError("this shroud exception names no player", node=node)
    return (OracleInstruction("waive_shroud_for_target_player", "", payload),)


def _names_a_chosen_player(statement) -> bool:
    """Whether *statement* — a delayed ability's effect — says "that player".

    A walk over the node's own fields rather than a list of the statements that
    can carry a ``PlayerRef``: the union grows, and a list of shapes goes stale
    the way a list of fire sites does. What it is looking for is one printed
    reference, and the reference is the same object wherever it sits.
    """
    seen: list = [statement]
    while seen:
        node = seen.pop()
        if isinstance(node, ast.PlayerRef):
            if node.kind == "that_player":
                return True
            continue
        if isinstance(node, (list, tuple)):
            seen.extend(node)
            continue
        fields = getattr(node, "__dataclass_fields__", None)
        if fields is None:
            continue
        seen.extend(getattr(node, name) for name in fields)
    return False


#: Instruction kinds whose object is the permanent an **earlier step of the
#: same resolution recorded**, rather than a target or the source. A delayed
#: ability carrying one has to freeze that id as it is created (CR 603.7c),
#: because the scratchpad it was read from is gone by the time it fires.
#:
#: One member today. A set rather than an equality test because the next
#: printed sentence of this shape ("destroy it at the beginning of the next
#: end step") is a row here and not a second branch.
_BOUND_TO_A_RECORDED_PERMANENT: frozenset[str] = frozenset({
    "exile_bound_permanent",
})


#: Instruction kinds that address the delayed ability's own bound object
#: (CR 603.7c) by id. An entry whose effect contains one must bind an
#: object, whatever the opener's noun phrase looked like — see the read in
#: :func:`_lower_create_delayed_trigger`.
_BOUND_TO_THE_DELAYS_OBJECT = frozenset({
    "destroy_bound_permanent", "sacrifice_bound_permanent",
    # "…**it** phases out at end of combat" (Teferi's Veil) and "…gain control
    # of **that creature** at end of combat" (Tolarian Entrancer). CR 511.1's
    # step with CR 603.7c's object: the same shape the two destroys above have,
    # with a different verb — which is the whole reason this is a set and not an
    # equality test.
    "phase_out_bound_permanent", "gain_control_of_bound_permanent",
    # "…return **that creature** to its owner's hand at end of combat" (Wall of
    # Tears). The bounce, beside the two destroys and the phase-out — one more
    # verb over one object, which is what this being a set rather than an
    # equality test is for.
    "return_bound_permanent_to_hand",
})


#: Which resolution record names the seat a :data:`EVENTS_SEATED_BY_BOUND_PLAYER`
#: event fires on. The value is what ``handlers/board_misc.create_delayed_trigger``
#: routes its ``binds_player`` read on, and every event in that set must have a
#: row here or the lowering refuses — a seat read out of the wrong record is an
#: ability that fires on nobody's upkeep, silently.
_SEAT_RECORDS: dict[str, str] = {
    # Sabertooth Cobra: the player the damage event was about, frozen by
    # ``damage_events._announce`` into the creating trigger's context.
    "damaged_players_next_upkeep": "damaged_player",
    # Ertai's Meddling: the controller of the spell an earlier step of this same
    # resolution exiled, written to the scratchpad by that step.
    "bound_players_upkeep": "exiled_spell_controller",
}


def _lower_create_delayed_trigger(
    node: ast.CreateDelayedTrigger,
    effect: tuple[OracleInstruction, ...],
    produced: frozenset[str] = frozenset(),
    creating_event: str | None = None,
    creating_event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """The ``create_delayed_trigger`` instruction for one printed delay.

    *effect* is the inner statement, already lowered by the dispatch above —
    lowered under the delayed ability's own event, so "you gain **that much**
    life" reads the number that event carries rather than one from the spell
    that created the ability.

    Two refusals, and both are the same rule stated at the two ends: an event
    no fire site announces would leave an ability waiting forever, and an
    effect that lowered to nothing would leave one firing into nothing.
    """
    from ...delayed_triggers import (DELAYED_EVENTS,
                                     EVENTS_SEATED_BY_BOUND_PLAYER)

    from ._events import (EXTRA_TURN_GRANTED, _EVENT_SUBJECT_OBJECTS,
                          _RECORDED_PERMANENTS,
                          _PERMANENTS_MADE_BY_THIS_EFFECT)

    if node.event not in DELAYED_EVENTS:
        raise LoweringError(
            f"no fire site announces the delayed event {node.event!r}", node=node
        )
    if not effect:
        raise LoweringError("this delayed ability has no effect", node=node)
    if node.event == "granted_extra_turns_end_step" and (
        EXTRA_TURN_GRANTED not in produced
    ):
        # "At the beginning of **that turn's** end step" (Final Fortune). A
        # back-reference, and this registry's standing rule for one: with no
        # earlier step of the same effect queuing a turn, the words name
        # nothing — and the ability they would arm answers to an event that
        # only happens on somebody's extra turn, so it would sit on the waiting
        # list for the rest of the game while the card compiled clean.
        raise LoweringError(
            "\"that turn\" needs an earlier step of this effect that granted "
            "an extra turn", node=node,
        )
    if node.duration is None:
        # The opener printed no window and no leading duration supplied one. A
        # repeating ability with no duration is CR 603.7b's other reading —
        # "will trigger only once" — and taking it silently would be a card
        # that fires once where it prints "whenever". Refusing leaves the line's
        # refusal instead.
        raise LoweringError("this delayed ability states no duration", node=node)
    # Several sentences behind one delay are one ability's effect, so they
    # compose the way every other multi-step effect does (CR 608.2) rather than
    # becoming several abilities.
    instruction = (
        effect[0] if len(effect) == 1
        else OracleInstruction("sequence", "", {"steps": list(effect)})
    )
    payload: dict[str, object] = {
        "event": node.event,
        "instruction": instruction,
        "once": node.once,
        "duration": node.duration,
        "binds_target": node.binds_target,
    }
    # "Choose target opponent. … When it regenerates this way, **that player**
    # may draw a card." (Soldevi Sentry.) CR 603.7c for a chosen *seat*: the
    # ability is about the player an earlier step of this same resolution
    # picked, and by the time it fires that resolution is over — so the seat is
    # frozen into the entry rather than re-read.
    #
    # Gated on a producer, and **without refusing** when there is none — which
    # is the one place this differs from every other back-reference here. "That
    # player" has other producers: Lodestone Bauble's is the graveyard owner its
    # own target named, read off the resolution rather than out of the
    # scratchpad. So the absence of a chosen player does not mean the words name
    # nobody; it means they name somebody else, and the entry keeps the reading
    # it already had.
    #
    # …and gated first on the *event*, because an event that freezes a player of
    # its own already answers "that player" — "whenever a player taps a Mountain
    # for mana, **that player** adds an additional {R}" (Chaos Moon) is the
    # tapper, not anyone this effect chose, and reading it as a chosen seat
    # would refuse a card that has no "choose" sentence to satisfy the gate.
    if (
        CHOSEN_PLAYER in produced
        and node.event not in _EVENT_SUBJECT_PLAYERS
        and _names_a_chosen_player(node.effect)
    ):
        payload["binds_player"] = True
    if node.event in EVENTS_SEATED_BY_BOUND_PLAYER:
        # "…at the beginning of **their** next upkeep" (Sabertooth Cobra),
        # "…at the beginning of **each of that player's** upkeeps" (Ertai's
        # Meddling). The possessive is the whole of what these events *are*:
        # each fires on one named player's upkeep, and which player is a fact
        # the creating effect knows and the upkeep three turns later does not.
        # So the seat is frozen as the ability is created, exactly as CR 603.7c
        # freezes the object a delayed ability is about.
        #
        # *Which* record it is read from is per event, because the two seats are
        # written down by different steps: the Cobra's is the damage event's
        # frozen recipient and Ertai's is the exiled spell's controller. Read as
        # each other, neither finds anything and the arming handler refuses —
        # an ability the card prints and nothing creates. A table rather than a
        # branch for :data:`_DELAYED_OPENERS`' reason: the difference between
        # the rows is one string.
        binds = _SEAT_RECORDS.get(node.event)
        if binds is None:
            raise LoweringError(
                f"no record says which seat {node.event!r} is about", node=node
            )
        # No ``produced`` gate on the exile row, and the reason is
        # ``exile_created_token``'s in ``lowering/exile.py``: the step that
        # writes the record is a **different printed line** of the same card
        # (Ertai's Meddling prints the exile and the delay one under the other),
        # and this lowering only ever sees one line. The card's two lines do
        # share one resolution — a spell's instructions are run as one sequence
        # against one scratchpad — so the record is there at run time; what
        # answers the absent case is ``create_delayed_trigger``, which arms
        # **nothing** and says so when ``binds_player`` finds no seat.
        payload["binds_player"] = binds
    # "…when **Stangg** leaves the battlefield" / "…when **that token** leaves
    # the battlefield". Which object the ability watches, when the opener names
    # one the effect already holds rather than one it targeted — the arming
    # handler reads the id from the source permanent or from the scratchpad the
    # token maker wrote, so nothing is resolved as a target.
    # "…**Exile it** at the beginning of the next end step." (Shallow Grave,
    # Zirilan of the Claw.) The delayed ability is about a permanent an
    # earlier step of this same resolution put onto the battlefield — not a
    # target (nothing was chosen; the ability's target is a *card*) and not
    # the source. So the id is frozen when the ability is created, which is
    # CR 603.7c's own instruction, and the record is the only place the
    # creating effect can be asked: by fire time its scratchpad is a turn
    # gone.
    #
    # Keyed on the *lowered* effect rather than on the AST, because the
    # inner lowering is what decided the pronoun names a record — one
    # decision, read here rather than made a second time and differently.
    if any(i.kind in _BOUND_TO_A_RECORDED_PERMANENT for i in effect):
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if len(recorded) != 1:
            raise LoweringError(
                "a delayed ability about a recorded permanent needs exactly "
                "one earlier step of this effect that recorded one", node=node,
            )
        payload["binds_recorded"] = recorded[0]
        # Stated rather than left standing beside it, exactly as the branch
        # below states it: the arming handler prefers the record, so a
        # `binds_target` still reading True would be a second answer nothing
        # consults. Coffin Queen is where the two came apart — its opener
        # grants the permission and its effect names a `that` noun phrase,
        # so `delay_binds_an_object` answered True for an entry that is
        # bound to a record.
        payload["binds_target"] = False
    # "…that creature's controller **sacrifices it** at end of combat."
    # (Basalt Golem.) The pronoun spelling of "sacrifice that creature", which
    # the AST cannot tell apart: the object is named in the *possessive* ("that
    # creature's controller") and the subject is a bare pronoun, so
    # `delay_binds_an_object` — which reads the noun phrase's quantifier — sees
    # no binding and the entry would arm about nothing.
    #
    # Keyed on the **lowered** effect for `binds_recorded`'s stated reason one
    # paragraph up: the inner lowering is what decided the pronoun names the
    # delay's object, and reading its answer here is that one decision rather
    # than a second one made differently. The same move
    # `_lower_activated_delayed_destroy` already makes for `destroy_bound_permanent`.
    if any(i.kind in _BOUND_TO_THE_DELAYS_OBJECT for i in effect):
        # "Put target creature **card from a graveyard** onto the battlefield …
        # When this enchantment leaves the battlefield, that creature's
        # controller sacrifices **it**." (Necromancy.) A step of this same
        # resolution *made* the permanent the words name, and the ability's own
        # target is the **card** it was — so `binds_target` would resolve a
        # graveyard slot as a permanent and bind nothing, arming an entry about
        # no object while the card compiled clean. The record is the only place
        # the permanent can be read from, which is `binds_recorded`'s own reason
        # one branch up.
        #
        # Asked whichever way the noun phrase was spelled, and that is the point
        # of `_PERMANENTS_MADE_BY_THIS_EFFECT` being a narrower set than the one
        # above: behind a step that merely *acted on* a permanent the target and
        # the record are the same object, so the reading must not change; behind
        # a step that made one they are different objects and only the record is
        # right.
        made = tuple(sorted(produced & _PERMANENTS_MADE_BY_THIS_EFFECT))
        if len(made) > 1:
            raise LoweringError(
                "a delayed ability about a permanent this effect made needs "
                "exactly one earlier step that made one", node=node,
            )
        if made:
            payload["binds_recorded"] = made[0]
            # Stated rather than left standing beside it: the arming handler
            # prefers the record, so a `binds_target` still reading True would
            # be a second answer nothing consults.
            payload["binds_target"] = False
        elif not node.binds_target:
            # "Whenever a creature you control attacks, **it** phases out at
            # end of combat." (Teferi's Veil.) The delay is created by a
            # *trigger*, and the object it is about is the one that trigger's
            # own event was about — which the fire site stamps by id and never
            # makes the stack item's target. So `binds_target` would resolve
            # nothing and arm an entry about no object at all, which is the
            # failure every bound payload in this file exists to prevent.
            #
            # Gated on the creating event, exactly as the pronoun readers in
            # the effect families are: outside these events the words name an
            # object no fire site recorded, and the delay keeps the target
            # reading it had.
            if creating_event in _EVENT_SUBJECT_OBJECTS:
                payload["binds_event_subject"] = True
            else:
                payload["binds_target"] = True
        # "Whenever this creature blocks a creature, return **that creature**
        # to its owner's hand at end of combat." (Wall of Tears.) The third
        # place a creating *trigger* can have put the object, and the one the
        # two readings above cannot reach: a block announcement records the
        # pair under ``blocked_permanent_ids`` and stamps no
        # ``event_subject_permanent_id``, while its stack item's target is the
        # ability's **own** creature — the blocker, so that a self-affecting
        # trigger can find itself.
        #
        # So ``binds_target`` here does not merely find nothing, it finds the
        # *wrong* permanent: Wall of Tears would bounce itself. Asked last and
        # allowed to override, because the block pair is a stricter answer than
        # the stack item's target under exactly the events it holds for —
        # ``binds_block_pair`` is False for every other one, delayed events
        # included.
        if binds_block_pair(creating_event, creating_event_subject):
            payload["binds_target"] = False
            payload["binds_block_pair"] = True
        # "When enchanted creature attacks, return **it** and this Aura to
        # their owners' hands at end of combat." (Contempt.) The fifth place,
        # and the one none of the four above can reach: the creating trigger is
        # an *Aura's*, so the object the words name is whatever it is attached
        # to — which no fire site stamps and which is not the stack item's
        # target either. That item's target is None for every attached trigger
        # (`phases/declare_attackers_step`), so ``binds_target`` would arm
        # nothing at all and the printed sentence would silently not happen.
        #
        # Resolved at *arming* rather than carried as a description, which is
        # CR 603.7c itself: the ability is about the creature the Aura was on
        # when the trigger resolved, so an Aura destroyed before the end of
        # combat step still returns it.
        #
        # Below the block pair and not beside it: an Aura watching a block
        # prints both narrowings at once ("whenever enchanted creature blocks
        # or becomes blocked by a creature, … that creature"), and there the
        # noun phrase names the *other* half of the pair, not the host.
        elif getattr(creating_event_subject, "is_enchanted", False):
            payload["binds_target"] = False
            payload["binds_attached_host"] = True
    if node.watches is not None:
        payload["watches"] = node.watches
    elif node.binds_target and _delay_is_about_a_created_token(node.effect, produced):
        # "Create a black Spirit creature token. … **Sacrifice the token** at
        # the beginning of the next end step." (Broken Visage.)
        #
        # "The token" is the one a step of this same resolution just made, and
        # the arming handler has exactly that record — but only under
        # ``watches``. Read as an ordinary binding it would resolve the *spell's
        # target*, which on this card is the creature the first sentence
        # destroyed: gone by now, so the handler arms **nothing** and the whole
        # sentence disappears while the card compiles clean. That is the failure
        # ``delay_binds_an_object`` documents, arriving from the other side —
        # the effect does name a bound object, and the object is not the target.
        #
        # Gated on a token maker actually standing in front of it, exactly as
        # every other back-reference is: with no producer the words name nothing
        # and the binding keeps the reading it had.
        payload["watches"] = "created_token"
        payload["binds_target"] = False
    # "…when **target creature you control** attacks and isn't blocked, …"
    # (Delif's Cone, Delif's Cube). The opener's own target, described the way
    # every other targeted instruction describes one — so `engine/targeting.py`
    # raises the picker off this instruction and the arming handler binds what
    # the player chose. Without it the ability would arm with `binds_target`
    # set, find no target, and create nothing while the card compiled clean.
    if node.target is not None:
        _describe_targets(payload, node.target)
        if "targets" not in payload:
            raise LoweringError(
                "this delay's opener names no target it can bind", node=node
            )
    subject = _delayed_filter_payload(node.subject, node)
    if subject:
        payload["subject_filter"] = subject
    agent = _delayed_filter_payload(node.agent, node)
    if agent:
        payload["agent_filter"] = agent
    return (OracleInstruction("create_delayed_trigger", "", payload),)


def _delay_is_about_a_created_token(effect, produced: frozenset[str]) -> bool:
    """Whether a delay's sentence names a token an earlier step of this same
    resolution created.

    Both printed spellings, because they are one referent: "that token"
    (Stangg) carries ``is_created_token`` and "the token" (Dance of Many,
    Broken Visage) carries ``token_only`` with ``created_with_source`` — the
    durable stamp a *permanent* leaves on what it made. A spell leaves no such
    stamp (it is never on the battlefield, so nothing is created "with" it),
    which is why the resolution record is the only answer on an instant and why
    this is asked of the effect rather than of the noun phrase's spelling.

    Written as a walk over the dataclass, for ``delay_binds_an_object``'s
    reason: the reference may be nested inside a sequence or an offer, and a
    statement class added later is covered by default.
    """
    if CREATED_TOKEN not in produced:
        return False
    return _names_a_created_token(effect)


def _names_a_created_token(node) -> bool:
    if isinstance(node, ast.TargetSpec):
        filt = node.filter
        if filt.is_created_token or (filt.token_only and filt.created_with_source):
            return True
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return any(
            _names_a_created_token(getattr(node, field.name))
            for field in dataclasses.fields(node)
        )
    if isinstance(node, (tuple, list)):
        return any(_names_a_created_token(item) for item in node)
    return False


# --- CR 701.8 destruction that happens *later* -------------------------------
# Moved whole out of ``lowering/destruction.py`` at Urza's Saga's Phase 0, when
# that module sat six lines under the thousand-line guard with a two-wave set
# about to land destroy productions on it. The seam is this module's own first
# sentence rather than a size cut: ``destruction`` lowers CR 701.8 happening
# **now**, and these four arrange for it to happen at a step that has not
# arrived — which is what every other function here already does. The one
# coupling was ``_lower_destroy``'s opening ``if node.delay`` guard, and that
# was a dispatch question rather than a shared body, so it moved *up* to the
# single ``ast.Destroy`` site in ``statement_dispatch`` instead of becoming an
# import between two families.

def _lower_delayed_destroy(
    node: ast.Destroy,
    event: str | None,
    event_subject: object | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"…destroy that creature at end of combat." (Thicket Basilisk, Cockatrice.)

    The handler destroys the creature this one blocked or was blocked by, which
    is a fact only the trigger knows — so the *event* is checked as strictly as
    the subject is. Under any other trigger the same sentence names a creature
    nobody recorded, and the handler would destroy nothing while the card
    reported as supported.

    **The other printing of the same delay is an activated ability's tail**:
    "Target creature you control can't be blocked this turn. Destroy it and
    this creature at end of combat." (Goblin Sappers.) No trigger has fired, so
    there is no pair to read — the sentence names what the step in front of it
    chose, and what it lowers to is CR 603.7's delayed ability rather than the
    block-pair handler. Read first, because its two subjects ("it", the source)
    are ones the pair reading refuses anyway, and refusing them here with the
    producer named is the more useful failure.
    """
    delayed = _lower_activated_delayed_destroy(node, produced, event, event_subject)
    if delayed is not None:
        return delayed
    damaged = _lower_delayed_destroy_of_damaged(node, event, event_subject)
    if damaged is not None:
        return damaged
    if not binds_block_pair(event, event_subject):
        raise LoweringError(
            "a delayed destroy at end of combat only has a handler on a "
            "blocks-or-blocked trigger that names one creature",
            node=node,
        )
    spec = node.subject
    # "that creature" (Thicket Basilisk) and "**the other** creature" (Infinite
    # Authority) are one referent under this event: the pair has two members,
    # the ability's own creature is one of them, and both spellings name the
    # one `block_pair_permanents` returns. The ordinal is admitted only here,
    # where a pair is what the trigger bound.
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier not in ("that", "other"):
        raise LoweringError(
            "the end-of-combat destroy acts on the creature the trigger bound", node=node
        )
    filt = spec.filter
    if filt.card_types != ("creature",) or _restrictions_beyond(
        filt, frozenset({"card_types", "subtypes"})
    ):
        raise LoweringError("no delayed-destroy handler narrows what it destroys", node=node)
    if node.no_regen:
        raise LoweringError(
            "the end-of-combat destroy handler does not bypass regeneration", node=node
        )
    # "destroy that **Wall**" (Battering Ram). The trigger that fired already
    # required a Wall, so the noun re-states what was bound rather than choosing
    # again — but it rides the payload and the handler tests it anyway, because
    # a word consumed and never read is a word that could be deleted.
    payload: dict[str, object] = {}
    if filt.subtypes:
        payload["subtype_filter"] = filt.subtypes[0]
    return (OracleInstruction("delayed_destroy_blocked_or_blocker", "", payload),)


def _lower_delayed_destroy_of_damaged(
    node: ast.Destroy, event: str | None, event_subject: object | None,
) -> tuple[OracleInstruction, ...] | None:
    """"Whenever this creature deals damage to a creature, destroy **that
    creature** at end of combat." (Lowland Basilisk.)

    None when the sentence is not this one, so the caller falls through to the
    block-pair reading — which is the better refusal for the cards that really
    are about a pair.

    The immediate spelling of the same sentence is already read one screen up
    (``_EVENT_SUBJECT_DESTROY_EVENTS``): "that creature" under a damage trigger
    is the *damaged* permanent, whose id ``damage_events._announce`` stamps onto
    the stack item. The delay is CR 603.7 wrapped around that same object, so
    ``binds_target`` — the stack item's target, which is that id — binds exactly
    what the immediate destroy would have hit.

    Gated on :func:`damage_trigger_names_damaged_end` rather than on the kind,
    and that is the whole of its correctness: a ``damage_dealt`` event has two
    objects in it, and where the damager is *described* rather than the source
    (Mangara's Equity) the words name the damager while the stamped id is the
    creature it hit. Read off the kind alone this would arm a destruction of the
    wrong end of the event.
    """
    if not damage_trigger_names_damaged_end(event, event_subject):
        return None
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "that":
        return None
    if _restrictions_beyond(spec.filter, frozenset({"card_types"})):
        raise LoweringError(
            "a creature named by a damage trigger carries no narrowing the "
            "delayed destroy could honour", node=node,
        )
    return _delayed_destroy_trigger(
        node, OracleInstruction("destroy_bound_permanent", "", {})
    )


def _lower_activated_delayed_destroy(
    node: ast.Destroy, produced: frozenset[str],
    event: str | None = None, event_subject: object | None = None,
) -> tuple[OracleInstruction, ...] | None:
    """"…Destroy it [and this creature] at end of combat." (Goblin Sappers.)

    Returns None — the caller falls through to the block-pair reading — unless
    the subject is one of the two this shape names.

    **"It" is gated on a producer**, and that gate is the whole of the card's
    correctness. `parse_recipient` reads a bare "it" as the ability's own
    source, so with nothing recorded the Sappers' first ability would arm two
    delayed destructions of the Sappers and never touch the creature it made
    unblockable — a card that compiles, resolves, logs, and does the wrong
    thing. The producer is the record the step in front wrote
    (`_RECORDED_PERMANENTS`); the entry then binds the ability's chosen target,
    which for a one-target ability is the same permanent by construction.

    **"This creature" needs no producer** and takes no binding: CR 603.7d
    freezes the creating ability's source into the entry, and `destroy_self`
    reads it back. That is why the two subjects lower to two different inner
    instructions rather than one with a flag — an entry that bound nothing and
    then destroyed "the bound object" would destroy nothing at all.

    `no_regen` refuses, for `_lower_delayed_destroy`'s reason one screen down:
    neither inner handler is asked to bypass regeneration here, and a clause
    read and dropped is a creature that regenerates from a card that says it
    cannot.
    """
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec):
        return None
    # "…**destroy that creature** at end of combat." (Winter's Chill.) The
    # third subject this shape names, and the one a loop supplies: the sentence
    # sits inside "for each of those creatures", so it is about the creature the
    # iteration is on and there is no block pair to read. Gated on the producer
    # for the "it" branch's reason — with no earlier step that chose a set of
    # permanents the words name nothing, and the block-pair reading below is the
    # better refusal for the cards that really are about a pair.
    if spec.quantifier == "that" and CHOSEN_TARGET_PERMANENTS in produced:
        if _restrictions_beyond(spec.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound creature carries no narrowing the destroy could honour",
                node=node,
            )
        if node.no_regen:
            raise LoweringError(
                "the end-of-combat destroy handler does not bypass regeneration",
                node=node,
            )
        return (
            OracleInstruction("create_delayed_trigger", "", {
                "event": "next_end_of_combat",
                "instruction": OracleInstruction("destroy_bound_permanent", "", {}),
                "once": True,
                "duration": "end_of_turn",
                "binds_target": True,
            }),
        )
    # The pronoun is read **before** the self-reference, and the order is the
    # card: `parse_recipient` gives a bare "it" the same `is_source` filter a
    # card naming itself gets, and tells them apart by the quantifier alone. Put
    # the other way round, "Destroy it and this creature" arms two destructions
    # of the Sappers and leaves the unblockable creature alone — the card
    # compiling, resolving, logging, and doing the wrong thing.
    if spec.quantifier == "it":
        if not spec.filter.is_source:
            # A rebound pronoun (an "it" the parser pointed at a trigger's
            # event subject) is not this shape: the referent is the event's,
            # not an earlier step's.
            return None
        if _RECORDED_PERMANENTS.isdisjoint(produced):
            # "When this creature blocks, **destroy it** at end of combat."
            # (Cinder Wall.) Under a trigger whose condition named no other
            # object, the word has one referent and it is the ability's own
            # source — that is exactly what
            # ``rebinding.rebind_pronoun_to_event_subject`` leaves behind, and
            # the *immediate* destroy one screen up already reads it that way
            # (its `_is_source` branch is tried first). Only the delay had the
            # two branches in the other order, for Goblin Sappers' sake, so the
            # same pronoun on the same verb meant the source without the delay
            # and nothing with it.
            #
            # An **activated** ability keeps the refusal: with no trigger and no
            # earlier step there is no antecedent at all, and reading the word
            # as the source there would be a guess rather than the rebinder's
            # answer.
            if event is not None and event_subject is None:
                inner = OracleInstruction("destroy_self", "", {})
                return _delayed_destroy_trigger(node, inner)
            raise LoweringError(
                "\"it\" names the permanent an earlier step of this effect "
                "chose, and no step here recorded one",
                node=node,
            )
        inner = OracleInstruction("destroy_bound_permanent", "", {})
    elif _is_source(spec):
        inner = OracleInstruction("destroy_self", "", {})
    else:
        return None
    return _delayed_destroy_trigger(node, inner)


def _delayed_destroy_trigger(
    node: ast.Destroy, inner: OracleInstruction
) -> tuple[OracleInstruction, ...]:
    """CR 603.7's delayed ability around one of the three inner destroys.

    One function because the three subjects differ only in what they destroy —
    the wrapper, its "once", its duration and the regeneration refusal are the
    same sentence's "at end of combat" every time, and a second copy of them is
    the second-copy-of-one-fact this repo forbids.
    """
    if node.no_regen:
        raise LoweringError(
            "the end-of-combat destroy handler does not bypass regeneration",
            node=node,
        )
    return (
        OracleInstruction("create_delayed_trigger", "", {
            "event": "next_end_of_combat",
            "instruction": inner,
            # CR 603.7b: "at end of combat" names one moment, so the ability
            # fires once and expires with the turn if that moment never comes.
            "once": True,
            "duration": "end_of_turn",
            **({"binds_target": True} if inner.kind == "destroy_bound_permanent" else {}),
        }),
    )

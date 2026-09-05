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

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._events import (_EVENT_SUBJECT_PLAYERS, CHOSEN_PLAYER,
                      CREATED_TOKEN)
from ._common import (
    _REST_OF_TURN, _describe_several_targets, _describe_targets,
    _names_several_targets, testable_filter_payload
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
})


def _lower_create_delayed_trigger(
    node: ast.CreateDelayedTrigger,
    effect: tuple[OracleInstruction, ...],
    produced: frozenset[str] = frozenset(),
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

    from ._events import EXTRA_TURN_GRANTED, _RECORDED_PERMANENTS

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
        # "…at the beginning of **their** next upkeep" (Sabertooth Cobra). The
        # possessive is the whole of what this event *is*: it fires on one
        # named player's upkeep, and which player is a fact the creating
        # trigger knows and the upkeep three turns later does not. So the seat
        # is frozen as the ability is created, exactly as CR 603.7c freezes the
        # object a delayed ability is about — and the record it is read from is
        # the damage event's own, named here rather than guessed at the fire
        # site.
        payload["binds_player"] = "damaged_player"
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
    if not node.binds_target and any(
        i.kind in _BOUND_TO_THE_DELAYS_OBJECT for i in effect
    ):
        payload["binds_target"] = True
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

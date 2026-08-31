"""Lowering counterspells and modal heads.

The filter fields `counter_top_stack_spell` reads off its own payload, the one
"unless … pays" cost the counter flow can offer, and the penalties it performs
for declining. All three are closed sets for the same reason: a restriction the
flow cannot honour has to make the line refuse, not travel in a payload nobody
reads. The modal head refuses on exactly the same principle, against the number
of modes the engine can carry out.
"""

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from .conditions import _lower_condition
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS,
    _describe_targets,
    _filter_payload,
    _restrictions_beyond,
    is_mana_value_x,
)


# Restrictions ``counter_top_stack_spell`` reads off its own payload: the
# colour gate (the Blasts, Lifeforce, Deathgrip), the mana-value gate
# (Spell Blast), the spell-type gate (Miscast's "instant or sorcery spell"),
# and the "spell" head noun recorded as zone="stack". Every other field of the
# noun phrase is refused by _restrictions_beyond, because this handler picks
# the spell to counter itself and would ignore anything it was not told to
# check.
_COUNTER_HONOURED_FILTER_FIELDS = frozenset({
    "colors", "mana_value", "card_types", "zone", "controller",
    "not_ability_targeted_by_same_name",
    # "instant or Aura spell" and "that targets a permanent you control"
    # (Avoid Fate, Ring of Immortals) — both read below and both tested by the
    # handler against the spell it chose.
    "any_classes", "targets_object",
})

# The "unless … pays" costs the counter flow can offer: ``{X}`` (Power Sink,
# sized from the caster's chosen X) and a fixed generic amount (Miscast's
# ``{3}``). Both arm the same pending mana payment; a coloured pip has no
# charging flow and refuses.
_COUNTER_UNLESS_PAYS_X = (("X", 1),)

# Penalties for declining that cost which the counter flow performs while it
# counters (engine/card_hooks.py ON_SPELL_COUNTERED, run from
# mixins/stack/choices._resolve_mana_payment). Declared here so a penalty the
# engine does not perform refuses instead of riding along unimplemented; the
# matching parse-coverage claim lives in HANDLER_CLAIMS in
# scripts/parse_coverage.py.
_COUNTER_PERFORMED_PENALTIES = frozenset({"tap_lands_and_empty_pool"})


def _fused_conditional_counter(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Counter target spell unless its controller pays {1}. If you control a
    creature with flying, counter that spell unless its controller pays {4}
    **instead**." (Lofty Denial.)

    **One counter, two amounts.** Lowered as two steps the card counters twice
    and asks its victim to pay twice, which is a different and much worse card.
    The second sentence does not add an effect — it replaces a number in the
    first — so the two fuse into the single instruction the first one describes,
    carrying the conditional amount beside the printed one.

    The condition is evaluated by the *handler*, at resolution (CR 608.2), which
    is what the card says: a flier that dies in response to the counter changes
    the number. Lowering it into two branches would have fixed the amount when
    the spell was cast.
    """
    if len(steps) != 2:
        return None
    first, second = steps
    if not isinstance(first, ast.CounterSpell):
        return None
    if not isinstance(second, ast.Conditional) or second.otherwise is not None:
        return None
    replacement = second.then
    if not isinstance(replacement, ast.CounterSpell):
        return None
    if not replacement.replaces_prior_amount:
        # Two counters in one line that are genuinely two effects. No card
        # prints it, and fusing them would silently drop one.
        raise LoweringError(
            "a second counter in one line replaces the first only when it says "
            '"instead"',
            node=replacement,
        )
    if first.unless_pays is None or replacement.unless_pays is None:
        raise LoweringError(
            "a replaced amount needs an amount on both sentences", node=replacement
        )
    if replacement.subject.filter != ast.ObjectFilter():
        raise LoweringError(
            "the replacing sentence names the spell already targeted, and nothing "
            "further about it",
            node=replacement,
        )
    (base,) = _lower_counter_spell(first)
    payload = dict(base.payload)
    replacement_payload = dict(_lower_counter_spell(
        ast.CounterSpell(first.subject, unless_pays=replacement.unless_pays)
    )[0].payload)
    if "unless_pays_amount" not in payload or "unless_pays_amount" not in replacement_payload:
        raise LoweringError(
            "a replaced amount must be a fixed cost on both sentences", node=replacement
        )
    payload["unless_pays_if"] = {
        "condition": _lower_condition(second.condition),
        "amount": replacement_payload["unless_pays_amount"],
    }
    return (OracleInstruction(base.kind, base.value, payload),)


#: Where the retarget's two steps pass the seat the controller picked. Named
#: once because the step that writes it and the step that reads it are two
#: instructions, and a literal in each is how they come to disagree — the same
#: reason ``lowering/redirection._REDIRECT_RECIPIENT_KEY`` is named once.
_NEW_TARGET_KEY = "retarget_new_target"

#: The retarget honours exactly one narrowing of its spell: CR 115.9a's count
#: of what that spell chose. Everything else about the noun phrase is refused
#: by ``_restrictions_beyond``, because the handler locates the spell itself
#: and would ignore anything it was not told to check.
_CHANGE_TARGET_HONOURED_FILTER_FIELDS = frozenset({"target_count"})

#: The bounds on the new target the resolution can actually offer, **beside**
#: the unbounded reading. ``None`` — the card prints no "the new target must
#: be…" sentence at all (Deflection, Divert) — is not a missing bound to be
#: filled in: it is the printed one, "any legal target this spell could have
#: chosen instead", and the resolution offers exactly the list the cast gate
#: would have. A *named* bound is a table row for the reason every other one
#: here is: a bound consumed by the parser and unknown to the handler is a
#: retarget free to aim anywhere.
_CHANGE_TARGET_NEW_TARGETS = frozenset({"player"})

#: The same, for "if that target is <player>". ``None`` is again the printed
#: reading — Deflection asks nothing about who the spell points at now — and
#: "you" is Reflecting Mirror's question. Anything else refuses: there is no
#: other player the picker could name before the effect is on the stack.
_CHANGE_TARGET_CURRENT_TARGETS = frozenset({"you"})


def _lower_change_target(node: ast.ChangeTarget) -> tuple[OracleInstruction, ...]:
    """CR 115.7a — "Change the target of target spell with a single target if
    that target is you. The new target must be a player." (Reflecting Mirror.)

    **Two instructions, in printed order**, because the sentence makes two
    decisions and the second reads the first: which player replaces you is
    chosen as the ability resolves, and the change is made with that answer in
    hand. That is the arrangement Backdraft's pair uses
    (``handlers/player_choices.py``) and the one the Nova Pentacle redirect
    uses, and it is what lets an interactive seat be *asked* — a prompt armed
    part-way through a resolution suspends it, and the step behind the prompt
    resumes when the answer arrives.

    Every refusal below is a way the sentence could otherwise mean more than it
    says, and each is a restriction the dispatcher would have no way to test:

    * the spell must be **chosen**, not named by an earlier sentence: there is
      no bound-spell reading of "that spell" here, and admitting one would
      retarget whatever happened to be on the stack.
    * the noun phrase must carry CR 115.9a's ``target_count``, and it must be
      **one**. Without it the phrase reads "target spell", which is every spell
      on the stack — a strictly larger card than any that prints this.
    * where the sentence *does* say what the spell's current target has to be,
      it must be **you**. There is no reading of another player's name that the
      picker could ask about, so anything else refuses rather than being
      dropped into a card that redirects spells aimed anywhere.
    * where it *does* bound the new target, the bound must be one the
      resolution can offer.

    Both of those are printed clauses rather than required ones, and a card
    printing neither is not a card missing them. Deflection is "Change the
    target of target spell with a single target." — every restriction it has is
    in the noun phrase, its new target may be anything that spell could legally
    have chosen, and the two ``None``s below are what say so. This used to
    refuse them, on the reading that an absent clause was an unimplementable
    one; what was actually absent was a candidate list that could hold a
    permanent, and that is in ``handlers/stack.py``, not here.
    """
    spec = node.subject
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "target":
        raise LoweringError(
            "a retarget names the spell it changes rather than finding one",
            node=node,
        )
    filt = spec.filter
    if filt.target_count != 1:
        raise LoweringError(
            "no handler retargets a spell this phrase does not count the "
            "targets of",
            node=node,
        )
    leftover = _restrictions_beyond(filt, _CHANGE_TARGET_HONOURED_FILTER_FIELDS)
    if leftover:
        raise LoweringError(
            "no handler honours this retarget restriction: " + ", ".join(leftover),
            node=node,
        )
    current = node.current_target
    if current is not None and current.kind not in _CHANGE_TARGET_CURRENT_TARGETS:
        raise LoweringError(
            "a retarget asking about another player's target is offered by no "
            "picker",
            node=node,
        )
    if node.new_target is not None and node.new_target not in _CHANGE_TARGET_NEW_TARGETS:
        raise LoweringError(
            "no handler bounds this retarget's new target", node=node
        )
    payload: dict[str, object] = {
        "result_key": _NEW_TARGET_KEY,
        "current_target": None if current is None else current.kind,
        "new_target": node.new_target,
    }
    return (
        OracleInstruction("choose_new_spell_target", "", dict(payload)),
        # The ``targets`` description rides the step that actually names the
        # spell. It is what ``legality._ability_target_quantifiers`` reads to
        # decide the target is **mandatory** (CR 602.2b): without it the
        # activation gate treats the ability as targeting nothing, and the {X}
        # and the tap are paid on an empty stack for no effect. The spec itself
        # still comes from the kind table in ``engine/targeting.py``, which is
        # consulted first — this says *that* it targets, not what.
        OracleInstruction(
            "change_target_spell_target", "",
            {**payload, "targets": {"quantifier": "target", "count": 1}},
        ),
    )


def _counter_targets_filter(
    inner: ast.ObjectFilter, node
) -> tuple[dict[str, object], bool]:
    """The payload for "that targets <noun phrase>" and whether that phrase is
    the ability's own source, or a refusal.

    Three gates, and each closes a way the phrase could be admitted and then
    ignored: a field ``to_payload`` never reads, a field it reads only
    sometimes, and a key the matcher the handler calls cannot answer. The
    narrowing is the whole card here — a counter that skips it counters every
    instant on the stack — so anything short of "testable in full" refuses.

    ``is_source`` is **lifted** rather than carried, the way
    ``chosen_by_opponent`` is one family over. It is not a property of any
    candidate — "this creature" is an identity, not a description — and
    ``to_payload`` deliberately emits no key for it: the word is consumed
    structurally almost everywhere else ("tap this creature" is ``tap_self``),
    so a positive key would appear in every filter in the pool and be refused by
    every gate that has never seen one. Here it is a second question, asked
    beside the filter by whoever holds the ability's source.
    """
    from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    # "…that targets **this creature**" (Mistfolk). Lifted first, so the field
    # is not reported as a narrowing nothing reads by the gate below it.
    targets_source = bool(inner.is_source)
    if targets_source:
        inner = dataclasses.replace(inner, is_source=False)
    beyond = _restrictions_beyond(inner, _PAYLOAD_HONOURED_FILTER_FIELDS)
    if beyond:
        raise LoweringError(
            "nothing tests what a spell targets by " + ", ".join(beyond), node=node
        )
    payload = _filter_payload(inner)
    untestable = set(payload) - TESTABLE_SUBJECT_FILTER_KEYS
    if untestable:
        raise LoweringError(
            "nothing tests a targeted permanent by " + ", ".join(sorted(untestable)),
            node=node,
        )
    return payload, targets_source


def _lower_counter_spell(node: ast.CounterSpell) -> tuple[OracleInstruction, ...]:
    """"Counter target spell", with the colour, mana-value and "unless … pays"
    riders the pool's counterspells carry. The handler chooses the spell to
    counter itself, so a restriction it cannot honour must be refused rather
    than dropped — countering the wrong spell is worse than not supporting the
    card."""
    spec = node.subject
    # "Whenever a player casts a spell, **counter it**." The spell is the one
    # the trigger's own condition bound, so there is nothing to target and no
    # picker to raise — the handler reads it off the trigger's event. Everything
    # past this point is shared with the targeted form, which is the point: the
    # filters and the "unless … pays" flow are the same card mechanics.
    bound_to_trigger = spec.quantifier in ("it", "that")
    if not bound_to_trigger and spec.quantifier != "target":
        raise LoweringError("no handler for a non-targeted counter", node=node)
    if node.replaces_prior_amount:
        # "…pays {4} **instead**" reaching here alone means no earlier sentence
        # named the amount it replaces. The fused form (Lofty Denial) never
        # arrives this way — it builds its own node from the *first* sentence's
        # subject — so the flag surviving to here is a replacement of nothing,
        # and dropping it would print a card that asks for one amount where it
        # says two.
        raise LoweringError(
            "a replacement amount with no earlier amount to replace", node=node
        )
    filt = spec.filter
    if filt.zone not in ("battlefield", "stack"):
        # "battlefield" is the ObjectFilter default a bare "target spell"
        # carries; "stack" is the recorded "… spell" head noun. Any zone a
        # postmodifier actually named is an object the counter flow cannot see.
        raise LoweringError("the counter flow reads spells on the stack", node=node)
    payload: dict[str, object] = {}
    if filt.card_types:
        # "target instant or sorcery **spell**" (Miscast), "target artifact
        # **spell**" (Artifact Blast). The handler tests the chosen spell's type
        # against this union, the same shape as the colour gate below.
        #
        # The printed word "spell" is what the noun parser turns into
        # ``zone == "stack"`` once a type has been named, and requiring it here
        # is what stops the word being droppable: without it the phrase reads as
        # "target artifact" — a permanent — and lowered identically, which is
        # the dropped-rider shape the deletion probe exists to report.
        if filt.zone != "stack":
            raise LoweringError(
                "a typed counter targets a **spell**; this phrase names a "
                "permanent",
                node=node,
            )
        payload["card_types"] = list(filt.card_types)
    if filt.any_classes:
        # "target **instant or Aura** spell" (Avoid Fate, Ring of Immortals):
        # one union across two axes, carried whole rather than split into the
        # type and subtype keys — those are ANDed by every matcher, so the split
        # would counter nothing at all. The printed "spell" is required for the
        # same reason it is above: without it the phrase names a permanent.
        if filt.zone != "stack":
            raise LoweringError(
                "a class-narrowed counter targets a **spell**; this phrase "
                "names a permanent",
                node=node,
            )
        payload["any_classes"] = [list(entry) for entry in filt.any_classes]
    if filt.targets_object is not None:
        # "…**that targets a permanent you control**" (Avoid Fate, Ring of
        # Immortals). The inner noun phrase is admitted only when every key it
        # produces is one ``subject_matches`` tests — an untestable narrowing
        # here is a counter that reaches spells the card does not name, which is
        # the direction nothing crashes and the card is simply wrong.
        described, targets_source = _counter_targets_filter(filt.targets_object, node)
        payload["targets_filter"] = described
        if targets_source:
            # "Counter target spell **that targets this creature**." (Mistfolk.)
            # A separate key because it is a separate question: the filter says
            # what the spell's target must *be*, and this says which permanent
            # it must be. Both are re-asked at resolution and both narrow the
            # picker, so the ability cannot be activated with nothing to counter.
            payload["targets_source"] = True
    if filt.colors:
        if len(filt.colors) > 1:
            raise LoweringError("no handler for a multi-colour counter filter", node=node)
        payload["color_filter"] = filt.colors[0]
    if filt.mana_value is not None:
        # Spell Blast: "counter target spell with mana value X". The handler
        # compares the X chosen on the cast against the target's mana value;
        # that equality is the only mana-value question it can ask, so a fixed
        # number or an inequality ("mana value 3 or less") has to refuse rather
        # than counter regardless of cost.
        if not is_mana_value_x(filt.mana_value):
            raise LoweringError("no handler for this mana-value restriction", node=node)
        payload["mv_equals_x"] = True
    if filt.controller is not None:
        # "counter target artifact spell **you control**" (Goblin Artisans).
        # Whose spell it is, checked by the handler against the caster's seat —
        # the one restriction here that is about the spell's controller rather
        # than the card, and refused for any other value because the handler
        # can only ask about "mine".
        if filt.controller != "you":
            raise LoweringError("no handler for this counter controller", node=node)
        payload["controller"] = "you"
    if filt.not_ability_targeted_by_same_name:
        # "…that isn't the target of an ability from another creature named ~"
        # (Goblin Artisans). Answered off the stack at resolution: the abilities
        # aiming at that spell are objects on it (CR 113.7a), so there is
        # nothing to read off the spell itself.
        payload["not_ability_targeted_by_same_name"] = True
    leftover = _restrictions_beyond(filt, _COUNTER_HONOURED_FILTER_FIELDS)
    if leftover:
        raise LoweringError(
            "no handler honours this counter restriction: " + ", ".join(leftover), node=node
        )

    if node.only_if is not None:
        # "…if it would destroy a land you control" (Equinox). Carried as the
        # key the handler asks `engine/counter_conditions.py` with — the same
        # table the parse gate read, so what the card was admitted for and what
        # the counter checks cannot part company. An unkeyed condition here
        # would be a counter that fires on every spell, which is the direction
        # nothing crashes and the card is simply wrong.
        from ...counter_conditions import counter_condition_key

        key = counter_condition_key(node.only_if)
        if key is None:
            raise LoweringError(
                f"nothing answers the counter condition {node.only_if!r}", node=node
            )
        payload["only_if"] = key
    if node.unless_pays is not None:
        if node.unless_pays.pips == _COUNTER_UNLESS_PAYS_X:
            payload["unless_pays_x"] = True
        elif (
            len(node.unless_pays.pips) == 1
            and node.unless_pays.pips[0][0] == "generic"
        ):
            # Miscast's "{3}": the same pending payment Power Sink arms, with
            # the amount fixed by the printed cost instead of a chosen X.
            payload["unless_pays_amount"] = node.unless_pays.pips[0][1]
        else:
            raise LoweringError("no counter flow offers this cost", node=node)
    if node.unpaid_penalty is not None:
        if node.unless_pays is None:
            raise LoweringError("a decline penalty with no cost to decline", node=node)
        if node.unpaid_penalty not in _COUNTER_PERFORMED_PENALTIES:
            raise LoweringError(
                f"nothing performs the {node.unpaid_penalty!r} penalty", node=node
            )

    if bound_to_trigger:
        # No `targets` description at all: a trigger chooses nothing (CR 603.3),
        # and describing one would raise a spell picker in front of an ability
        # that has already been given its spell.
        payload["bound_to_trigger"] = True
        return (OracleInstruction("counter_top_stack_spell", "", payload),)
    # A counterspell targets a *spell on the stack*, not a permanent. Describing
    # it with the generic object shape would tell the targeting layer to offer
    # battlefield permanents.
    payload["targets"] = {"quantifier": "target", "kind": "spell"}
    return (OracleInstruction("counter_top_stack_spell", "", payload),)


def _lower_counter_ability(
    node: ast.CounterAbility,
) -> tuple[OracleInstruction, ...]:
    """"Counter target activated or triggered ability." (Sublime Epiphany.)

    The printed kinds ride the payload, so "counter target **triggered**
    ability" is the same instruction with a narrower list — and the handler
    tests them, because an effect that countered an activated ability when the
    card says triggered is countering something its controller could not have
    chosen.
    """
    if node.subject.quantifier not in ("target", "that"):
        raise LoweringError("an ability is countered by targeting it", node=node)
    payload: dict[str, object] = {
        "ability_kinds": tuple(node.subject.filter.ability_kinds),
    }
    # "**Counter that ability.**" (Imprison.) Nothing is chosen: the ability is
    # the one the trigger's event was about, and the fire site put it on the
    # stack item's context. The same flag `counter_top_stack_spell` carries for
    # "counter it", so the handler pair answers "which object?" the same way on
    # both sides of CR 113.7a's card/no-card divide.
    if node.subject.quantifier == "that":
        payload["bound_to_trigger"] = True
    # "…from an artifact source" (Rust, Ayesha Tanaka). Payload for the reason
    # the kinds above are: the handler tests it, because a counter that reached
    # an ability from a creature when the card says artifact is countering
    # something its controller could not have chosen.
    if node.subject.filter.ability_source_types:
        payload["source_card_types"] = list(node.subject.filter.ability_source_types)
    # "…unless that ability's controller pays {W}" (Ayesha Tanaka). Carried as a
    # symbol dict, which is what a cost is everywhere in this engine — the
    # spell counter's `unless_pays_amount` beside it is a bare number and the
    # reason a coloured cost had no flow to arrive through until now.
    if node.unless_pays is not None:
        cost = dict(node.unless_pays.pips)
        if "X" in cost:
            raise LoweringError(
                "no ability counter sizes its payment from an X", node=node
            )
        payload["unless_pays_cost"] = cost
    return (OracleInstruction("counter_stack_ability", "", payload),)


def _lower_modal_head(node: ast.ModalNode) -> tuple[OracleInstruction, ...]:
    """"Choose one —" performs nothing, so it lowers to no instructions.

    That is a complete lowering rather than a gap, and it is the same shape as
    `KeywordLine` and `RegistryLine`: the head declares how many of the *bullet
    lines below it* the controller picks (CR 700.2), and each of those is an
    ordinary effect line with its own instructions. Emitting anything here would
    be a fourth reading of text three other places already read.

    Where the modes are assembled — the compiler, `engine/oracle.py` — is not
    this function's business either, and deliberately so: line grouping is line
    classification, and it needs the lines *around* this one, which a parser
    handed one line at a time cannot see.

    **"Choose one or more" is carried; an exact count above one is not.** The
    stack item holds a *list* of chosen modes now (CR 700.2d), each with its own
    targets, so "one or more" has somewhere to put the second choice. "Choose
    two —" would too, arithmetically, and is still refused: no card in the pool
    prints it, so admitting it would ship a bound nothing exercises — and the
    direction a wrong bound fails in is a spell that performs a mode its
    controller never chose.

    Refusing at all is the part that matters. Lowering a multi-mode head like a
    choose-one is what the substring match this replaces did to Sublime
    Epiphany, quietly turning a spell that picks several modes into one that
    picks one.
    """
    if node.choose_count != 1:
        printed = f"choose {node.choose_count}" + (" or more" if node.at_least else "")
        raise LoweringError(
            f"the engine resolves one chosen mode or any number; {printed!r} "
            "has no representation",
            node=node,
        )
    return ()


# ---------------------------------------------------------------------------
# Delayed triggered abilities (CR 603.7)
# ---------------------------------------------------------------------------


def _delayed_filter_payload(filt: "ast.ObjectFilter | None", node) -> dict[str, object]:
    """A noun phrase the delayed trigger's fire site will test, or a refusal.

    The same gate ``_counter_targets_filter`` states, for the same reason and in
    the same direction: the fire site asks ``subject_matches``, so a key that
    matcher cannot answer would make the ability fire on a strictly larger set
    than the card prints. "Dealt damage by **an attacking creature**" is the
    whole difference between Glyph of Life and a card that gains life off any
    ping.
    """
    from ...subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    if filt is None:
        return {}
    payload = _filter_payload(filt)
    untestable = set(payload) - TESTABLE_SUBJECT_FILTER_KEYS
    if untestable:
        raise LoweringError(
            "nothing tests a delayed trigger's subject by "
            + ", ".join(sorted(untestable)),
            node=node,
        )
    return payload


def _lower_choose_target(node: ast.ChooseTarget) -> tuple[OracleInstruction, ...]:
    """"Choose target creature." — the targeting half of a two-sentence spell.

    The instruction does nothing on resolution and that is the whole of it:
    CR 601.2c chooses the target as the spell is cast, and the sentence prints
    no effect. It exists so ``engine/targeting.py`` can derive what the spell
    targets from the compiled program, which is where every other card's
    picker comes from — the alternative is a second reading of the oracle text.
    """
    payload: dict[str, object] = {}
    _describe_targets(payload, node.subject)
    if "targets" not in payload:
        raise LoweringError("this 'choose' names no target", node=node)
    return (OracleInstruction("choose_target_permanent", "", payload),)


def _lower_create_delayed_trigger(
    node: ast.CreateDelayedTrigger,
    effect: tuple[OracleInstruction, ...],
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
    from ...delayed_triggers import DELAYED_EVENTS

    if node.event not in DELAYED_EVENTS:
        raise LoweringError(
            f"no fire site announces the delayed event {node.event!r}", node=node
        )
    if not effect:
        raise LoweringError("this delayed ability has no effect", node=node)
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
    # "…when **Stangg** leaves the battlefield" / "…when **that token** leaves
    # the battlefield". Which object the ability watches, when the opener names
    # one the effect already holds rather than one it targeted — the arming
    # handler reads the id from the source permanent or from the scratchpad the
    # token maker wrote, so nothing is resolved as a target.
    if node.watches is not None:
        payload["watches"] = node.watches
    subject = _delayed_filter_payload(node.subject, node)
    if subject:
        payload["subject_filter"] = subject
    agent = _delayed_filter_payload(node.agent, node)
    if agent:
        payload["agent_filter"] = agent
    return (OracleInstruction("create_delayed_trigger", "", payload),)

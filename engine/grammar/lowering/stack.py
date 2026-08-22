"""Lowering counterspells and modal heads.

The filter fields `counter_top_stack_spell` reads off its own payload, the one
"unless … pays" cost the counter flow can offer, and the penalties it performs
for declining. All three are closed sets for the same reason: a restriction the
flow cannot honour has to make the line refuse, not travel in a payload nobody
reads. The modal head refuses on exactly the same principle, against the number
of modes the engine can carry out.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _lower_condition,
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


def _lower_counter_spell(node: ast.CounterSpell) -> tuple[OracleInstruction, ...]:
    """"Counter target spell", with the colour, mana-value and "unless … pays"
    riders the pool's counterspells carry. The handler chooses the spell to
    counter itself, so a restriction it cannot honour must be refused rather
    than dropped — countering the wrong spell is worse than not supporting the
    card."""
    spec = node.subject
    if spec.quantifier != "target":
        raise LoweringError("no handler for a non-targeted counter", node=node)
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
    if node.subject.quantifier != "target":
        raise LoweringError("an ability is countered by targeting it", node=node)
    return (
        OracleInstruction(
            "counter_stack_ability", "",
            {"ability_kinds": tuple(node.subject.filter.ability_kinds)},
        ),
    )


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

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
    _restrictions_beyond,
)


# Restrictions ``counter_top_stack_spell`` reads off its own payload: the
# colour gate (the Blasts, Lifeforce, Deathgrip), the mana-value gate
# (Spell Blast), the spell-type gate (Miscast's "instant or sorcery spell"),
# and the "spell" head noun recorded as zone="stack". Every other field of the
# noun phrase is refused by _restrictions_beyond, because this handler picks
# the spell to counter itself and would ignore anything it was not told to
# check.
_COUNTER_HONOURED_FILTER_FIELDS = frozenset({"colors", "mana_value", "card_types", "zone"})

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
        # "target instant or sorcery spell" (Miscast). The handler tests the
        # chosen spell's primary type against this union, the same shape as the
        # colour gate below.
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
        if filt.mana_value.op != "eq" or not isinstance(filt.mana_value.value, ast.Var):
            raise LoweringError("no handler for this mana-value restriction", node=node)
        payload["mv_equals_x"] = True
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

    **A count other than one refuses.** The engine carries a single chosen mode
    (`StackItem.chosen_mode_index` is one index into `OracleProgram.modes`, and
    `_select_executable_instruction` resolves that one mode's instruction), so
    "Choose two —" and "Choose one or more —" have nowhere to put the second
    choice. Refusing names that; the alternative — lowering them like a
    choose-one — is what the substring match this replaces did to Sublime
    Epiphany, quietly turning a spell that picks several modes into one that
    picks one.
    """
    if node.at_least or node.choose_count != 1:
        printed = f"choose {node.choose_count}" + (" or more" if node.at_least else "")
        raise LoweringError(
            f"the engine resolves one chosen mode; {printed!r} has no representation",
            node=node,
        )
    return ()

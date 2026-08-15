"""Lower a parsed AST into ``OracleInstruction`` sequences.

The grammar deliberately stops at the IR rather than interpreting the AST
directly against game state. Three reasons:

1. The 121 registered effect handlers encode game-rule behavior that is
   orthogonal to parsing — CR 608.2b fizzling, state-based-action batching,
   replacement-effect dispatch, divided-damage arithmetic. Re-implementing that
   inside an AST interpreter would regress it.
2. ``OracleInstruction`` has many consumers beyond resolution: ``ai_policy``
   scores by instruction kind, ``StackItem`` carries instructions,
   ``trigger_utils`` filters on them, the web layer serializes them. Keeping the
   IR stable isolates the parser rewrite from the AI and UI at the same time.
3. Strangler-fig migration needs the old and new front ends to be *comparable*.
   Both emit instructions, so "grammar agrees with the legacy rules" is a
   dataclass equality check rather than a full game simulation.

Payload keys reproduce what the legacy rules have always emitted, byte for
byte; anything new is additive and read with ``payload.get`` defaults on the
handler side.

**This file is the dispatch.** ``lower_statement`` routes one AST node to its
family, ``lower_ability`` wraps that for a whole line (the `may`, sequence and
condition wrappers, the lord-buff and static-ability readings), and
``categories_of`` answers what a lowered line touches. The per-effect lowerings
live in ``grammar/lowering/``, one module per subject, mirroring
``grammar/effects/`` name for name.

``INSTRUCTION_CATEGORIES`` and ``lower_statement`` are re-exported here because
callers outside the package import them from this module
(``tests/engine/test_grammar_categories.py``, ``grammar/__init__.py``); moving
the table did not move its address.
"""

from ..lord_buffs import (LORD_BUFF_KIND, LordBuff, LordBuffFilter, QUALIFIER_FIELDS, grantable_keywords, lord_buff_payload)
from ..oracle_types import OracleInstruction
from . import ast
from .derived import derived_instruction_for_line
from .errors import LoweringError
from .lowering import (
    # Re-exported, not used here: callers outside the package import these two
    # from `engine.grammar.lower` (`grammar/__init__.py`,
    # `tests/engine/test_grammar_categories.py`, `test_grammar_lowering.py`).
    # Moving the definitions into `lowering/` did not move their address, which
    # is what kept this a pure move rather than a rename with a diff attached.
    GRAMMAR_ONLY_PAYLOAD_KEYS,
    INSTRUCTION_CATEGORIES,
    _full_mana_payload,
    _fused_draw_then_discard,
    _fused_exile_then_controller_life,
    _is_source,
    _is_you,
    _lower_add_mana,
    _lower_add_mana_for_tapped_land,
    _lower_become_color,
    _lower_cant_be,
    _lower_change_text,
    _lower_combat_restriction,
    _lower_counter_spell,
    _lower_create_emblem,
    _lower_create_token,
    _lower_damage,
    _lower_damage_conjunction,
    _lower_damage_unless_pay,
    _fused_prepare_then_interact,
    _lower_fight,
    _lower_destroy,
    _lower_discard,
    _lower_draw,
    _lower_exile,
    _lower_extra_turn,
    _lower_for_each,
    _lower_gain_control,
    _lower_gain_keyword,
    _lower_lose_keyword,
    _lower_gain_life,
    _lower_double_power,
    _lower_exile_graveyard,
    _lower_reveal_hand_and_choose,
    _lower_look_at_hand,
    _lower_lose_game,
    _lower_lose_life,
    _lower_mill,
    _lower_scry,
    _lower_modal_head,
    _lower_prevent_damage,
    _lower_pump,
    _lower_put_counter,
    _lower_phase_out,
    _lower_put_on_library_bottom,
    _lower_put_on_library_top,
    _lower_put_onto_battlefield,
    _lower_regenerate,
    _lower_reveal_top,
    _lower_remove_counter,
    _lower_return_to_zone,
    _lower_sacrifice,
    _lower_sacrifice_unless_pay,
    _lower_cast_permission,
    _lower_exile_top_of_library,
    _lower_look_top_pick,
    _lower_search_and_exile,
    _lower_search_library,
    _lower_set_base_pt,
    _lower_tap,
    _lower_tap_or_untap,
    _lower_win_game,
    _signed,
)


# ---------------------------------------------------------------------------
# Statement dispatch
# ---------------------------------------------------------------------------


# Values an instruction records in the resolution scratchpad, so a later
# back-reference ("that much") can verify it has a producer.
_PRODUCES: dict[str, str] = {
    "deal_damage": "damage_dealt",
    # The exile records whose permanent it removed, which is what "Its
    # controller creates a token" reads (Angelic Ascension, Secure the Scene).
    "exile_target_permanent": "exiled_permanent_controller",
    # Both exiles record what they exiled, which is what "you may play cards
    # exiled this way" / "you may cast them this turn" read.
    "exile_top_of_library": "exiled_cards",
    "search_and_exile_matching": "exiled_cards",
}


def lower_statement(
    statement: ast.Statement,
    produced: frozenset[str] = frozenset(),
    *,
    event: str | None = None,
    whole_effect: bool = True,
) -> tuple[OracleInstruction, ...]:
    """Lower one statement into the instructions that perform it, in order.

    *produced* names the scratchpad values earlier steps of the same effect
    already recorded; a back-reference without a producer is refused.

    *event* is the trigger kind when this statement is (part of) a triggered
    ability's effect, and None everywhere else. It is threaded into nested
    statements because it is simply true of them: every clause of a trigger is
    under that trigger's event, so "that player" and "that much" refer to it
    wherever in the sentence they sit. Gloom Sower is why — its "that creature's
    controller" is one half of a conjunction, and an unthreaded event left it
    lowering as an ordinary chosen target that happens to be right with two
    players.

    *whole_effect* is the distinction that was hiding inside the unthreaded
    parameter, and it is a different question: three lowerings pick between two
    engine *dispatch* paths by the trigger kind (the upkeep pay-or-else
    registry, the delayed block-pair destroy, an Aura's mana trigger), and each
    of those registries dispatches on the ability's whole instruction. A nested
    occurrence is not that instruction, so those readers see None and refuse
    rather than emitting a kind nothing will reach.
    """
    dispatch_event = event if whole_effect else None
    if isinstance(statement, ast.DealDamage):
        return _lower_damage(statement, event, produced)
    if isinstance(statement, ast.Fight):
        return _lower_fight(statement, whole_effect)
    if isinstance(statement, ast.DamageUnlessPay):
        return _lower_damage_unless_pay(statement, dispatch_event)
    if isinstance(statement, ast.Pump):
        return _lower_pump(statement)
    if isinstance(statement, ast.SetBasePT):
        return _lower_set_base_pt(statement)
    if isinstance(statement, ast.GainKeyword):
        return _lower_gain_keyword(statement)
    if isinstance(statement, ast.LoseKeyword):
        return _lower_lose_keyword(statement)
    if isinstance(statement, ast.PutCounter):
        return _lower_put_counter(statement)
    if isinstance(statement, ast.DoublePower):
        return _lower_double_power(statement)
    if isinstance(statement, ast.RemoveCounter):
        return _lower_remove_counter(statement)
    if isinstance(statement, ast.GainLife):
        return _lower_gain_life(statement, produced, event)
    if isinstance(statement, ast.LoseLife):
        return _lower_lose_life(statement, event, produced)
    if isinstance(statement, ast.Destroy):
        return _lower_destroy(statement, dispatch_event)
    if isinstance(statement, (ast.Tap, ast.Untap)):
        return _lower_tap(statement)
    if isinstance(statement, ast.TapOrUntap):
        return _lower_tap_or_untap(statement)
    if isinstance(statement, ast.Draw):
        return _lower_draw(statement)
    if isinstance(statement, ast.Mill):
        return _lower_mill(statement)
    if isinstance(statement, ast.Scry):
        return _lower_scry(statement)
    if isinstance(statement, ast.AddMana):
        return _lower_add_mana(statement)
    if isinstance(statement, ast.AddManaForTappedLand):
        return _lower_add_mana_for_tapped_land(statement, dispatch_event)
    if isinstance(statement, ast.CreateToken):
        return _lower_create_token(statement, produced)

    if isinstance(statement, ast.CreateEmblem):
        return _lower_create_emblem(statement)

    if isinstance(statement, ast.Conjunction):
        if len(statement.effects) == 2 and all(
            isinstance(effect, ast.DealDamage) for effect in statement.effects
        ):
            return _lower_damage_conjunction(statement)
        return _lower_steps(statement.effects, produced, event)

    if isinstance(statement, ast.SacrificeUnlessPay):
        return _lower_sacrifice_unless_pay(statement)

    if isinstance(statement, ast.BecomeColor):
        return _lower_become_color(statement)

    if isinstance(statement, ast.ChangeText):
        return _lower_change_text(statement)

    if isinstance(statement, ast.GainControl):
        return _lower_gain_control(statement)

    if isinstance(statement, ast.PreventDamage):
        return _lower_prevent_damage(statement)

    if isinstance(statement, ast.Regenerate):
        return _lower_regenerate(statement)

    if isinstance(statement, ast.CounterSpell):
        return _lower_counter_spell(statement)

    if isinstance(statement, ast.ModalNode):
        # Reached only when the head is a *step* of something larger — "Draw a
        # card, then choose one —". `_lower_line_statement` is what handles the
        # head as a whole clause, and it does not come through here.
        #
        # This has to refuse rather than lower to nothing. A head lowers to no
        # instructions because the compiler picks the modes up from the bullet
        # lines beneath it, and it finds them by recognizing the head *line*; a
        # head buried inside a sequence is not that line, so the empty tuple
        # would be a spell that quietly performs everything except its modes.
        raise LoweringError(
            "a modal head is a whole clause, not a step inside one", node=statement
        )

    if isinstance(statement, ast.Discard):
        return _lower_discard(statement, event)

    if isinstance(statement, ast.ReturnToZone):
        return _lower_return_to_zone(statement)

    if isinstance(statement, ast.PhaseOut):
        return _lower_phase_out(statement)

    if isinstance(statement, ast.PutOnLibraryTop):
        return _lower_put_on_library_top(statement)

    if isinstance(statement, ast.PutOnLibraryBottom):
        return _lower_put_on_library_bottom(statement)

    if isinstance(statement, ast.PutOntoBattlefield):
        return _lower_put_onto_battlefield(statement)

    if isinstance(statement, ast.RevealTopToHandOrBottom):
        return _lower_reveal_top(statement)

    if isinstance(statement, ast.Sacrifice):
        return _lower_sacrifice(statement)

    if isinstance(statement, ast.RevealHandAndChoose):
        return _lower_reveal_hand_and_choose(statement)
    if isinstance(statement, ast.ExileGraveyard):
        return _lower_exile_graveyard(statement)
    if isinstance(statement, ast.LookAtHand):
        return _lower_look_at_hand(statement)

    if isinstance(statement, ast.SearchLibrary):
        return _lower_search_library(statement)

    if isinstance(statement, ast.ExileTopOfLibrary):
        return _lower_exile_top_of_library(statement)

    if isinstance(statement, ast.LookTopPickToHand):
        return _lower_look_top_pick(statement)

    if isinstance(statement, ast.SearchAndExile):
        return _lower_search_and_exile(statement)

    if isinstance(statement, ast.CastPermission):
        return _lower_cast_permission(statement, produced)

    if isinstance(statement, ast.ExtraTurn):
        return _lower_extra_turn(statement)

    if isinstance(statement, ast.LoseGame):
        return _lower_lose_game(statement)

    if isinstance(statement, ast.WinGame):
        return _lower_win_game(statement)

    if isinstance(statement, ast.DrawGame):
        # "The game is a draw." (CR 104.4c.) `game_is_draw` takes an empty
        # payload and the sentence carries nothing else, so there is nothing to
        # check and nothing that could be dropped.
        return (OracleInstruction("game_is_draw", "", {}),)

    if isinstance(statement, ast.CombatRestriction):
        return _lower_combat_restriction(statement)

    if isinstance(statement, ast.CantBe):
        return _lower_cant_be(statement)

    if isinstance(statement, ast.ForEach):
        return _lower_for_each(statement)

    if isinstance(statement, ast.Exile):
        return _lower_exile(statement)

    if isinstance(statement, ast.Sequence):
        for fuse in (
            _fused_draw_then_discard,
            _fused_exile_then_controller_life,
            _fused_prepare_then_interact,
        ):
            fused = fuse(statement.steps)
            if fused is not None:
                return fused
        return _lower_steps(statement.steps, produced, event)

    if isinstance(statement, ast.Conditional):
        then = lower_statement(statement.then, produced, event=event, whole_effect=False)
        otherwise = (
            lower_statement(statement.otherwise, produced, event=event, whole_effect=False)
            if statement.otherwise else ()
        )
        return (
            OracleInstruction(
                "if_then", "",
                {
                    "condition": _lower_condition(statement.condition),
                    "then": then,
                    "else": otherwise,
                },
            ),
        )

    if isinstance(statement, ast.May):
        return _lower_may(statement, produced, event)

    if isinstance(statement, ast.RawEffect) and statement.text == "grant_team_assign_unblocked_until_eot":
        # Garruk, Savage Herald's −7 — the one quoted team grant with a
        # handler. Any other RawEffect keeps refusing below.
        return (OracleInstruction("grant_team_assign_unblocked_until_eot", "", {}),)

    raise LoweringError(f"no lowering for {type(statement).__name__}", node=statement)


def _lower_may(
    node: ast.May, produced: frozenset[str], event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"You may pay {N}. If you do, …" and "You may <action>".

    This replaces the ``optional_pay`` hook shape, which could only express a
    fixed vocabulary of consequences (gain N life, draw N cards, take N damage)
    and so needed a name-keyed entry per card. Here the consequence is an
    ordinary instruction sequence, so any effect can sit behind an optional
    cost.

    **Known limit — a spell whose whole effect is optional.** The prompt still
    rides ``pending_optional_pays``, and only the triggered-ability resolution
    path holds that queue open and drains it (``resolve_top_of_stack``'s
    ``pause_for_choices``, ``auto_resolve_pending_optional_pays``). A spell
    leaves the stack the instant it resolves, so a line like Twiddle's "You may
    tap or untap target artifact, creature, or land." would queue its effect and
    never perform it — measured, not assumed: lowering Twiddle that way makes
    all three of its pinned regression tests fail with the permanent untouched.
    No card reaches that shape today (every usable ``may`` in the pool is a
    trigger remainder), and the check cannot live here: the coverage script and
    the lowering tests compile bare *clauses*, which are indistinguishable from
    a spell's whole line once the trigger prefix is gone. It stops being a trap
    when the prompt moves to the general pending-choice queue (roadmap phase 4).
    """
    action = lower_statement(node.action, produced, event=event, whole_effect=False) if node.action else ()
    then = lower_statement(node.then, produced, event=event, whole_effect=False) if node.then else ()
    otherwise = lower_statement(node.otherwise, produced, event=event, whole_effect=False) if node.otherwise else ()

    payload: dict[str, object] = {"actor": node.actor.kind}
    if node.cost is not None:
        if not isinstance(node.cost, ast.ManaCost):
            raise LoweringError("only mana costs can be offered optionally", node=node)
        generic = dict(node.cost.pips).get("generic", 0)
        colored = {sym: n for sym, n in node.cost.pips if sym != "generic"}
        if colored:
            raise LoweringError(
                "optional colored costs need a real cost-payment prompt", node=node
            )
        payload["cost"] = generic
    if action:
        payload["action"] = action
    if then:
        payload["then"] = then
    if otherwise:
        payload["otherwise"] = otherwise
    if not (action or then or otherwise):
        raise LoweringError("an optional action with no consequence", node=node)
    return (OracleInstruction("may", "", payload),)


def _lower_steps(
    steps: tuple[ast.Statement, ...],
    produced: frozenset[str],
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """Lower consecutive steps, threading what each one records forward."""
    instructions: tuple[OracleInstruction, ...] = ()
    for step in steps:
        lowered = lower_statement(step, produced, event=event, whole_effect=False)
        for instruction in lowered:
            result = _PRODUCES.get(instruction.kind)
            if result is not None:
                produced = produced | {result}
        instructions += lowered
    return instructions


def _lower_condition(condition: ast.Condition) -> dict[str, object]:
    if isinstance(condition, ast.Controls):
        payload = {
            "kind": "controls",
            "who": condition.who.kind,
            "filter": condition.filter.to_payload(),
        }
        if condition.comparison is not None and isinstance(condition.comparison.value, ast.Fixed):
            payload["count"] = condition.comparison.value.value
            payload["op"] = condition.comparison.op
        return payload
    if isinstance(condition, ast.IsState):
        return {"kind": "is_state", "state": condition.state, "negated": condition.negated}
    if isinstance(condition, ast.DiedThisTurn):
        return {"kind": "died_this_turn", "filter": condition.filter.to_payload()}
    if isinstance(condition, ast.ReturnedToHandThisTurn):
        return {"kind": "returned_to_hand_this_turn"}
    if isinstance(condition, ast.HadPlus1Counter):
        return {"kind": "had_plus1_counter"}
    if isinstance(condition, ast.LifeGainedThisTurn):
        # The seat rides the payload rather than being baked into the kind, so
        # "if an opponent gained…" is the same condition with a different `who`
        # the day a card prints it.
        return {
            "kind": "life_gained_this_turn",
            "who": condition.who.kind,
            "amount": condition.amount,
        }
    raise LoweringError(f"no lowering for condition {type(condition).__name__}", node=condition)


def _fused_upkeep_pay_to_untap(
    node: ast.TriggeredAbilityNode,
) -> tuple[OracleInstruction, ...] | None:
    """"At the beginning of your upkeep, you may pay {N}. If you do, untap this
    <permanent>." (Mana Vault, Basalt Monolith, Brass Man, Island Fish Jasconius.)

    Fused for the reason every upkeep shape is fused: the dispatcher in
    ``engine/phases/upkeep_effects.py`` is keyed on the (trigger condition,
    instruction kind) pair, and ``upkeep_pay_to_untap_self``'s handler
    implements the whole prompt — the pay/decline choice, the affordability
    check and the untap. A decomposed ``may(pay, untap_self)`` is a truer
    reading of the sentence and has no handler at all.

    Recognised on the **node**, before ``lower_statement`` runs, because two of
    the four cards would never reach a post-hoc check: the generic ``may``
    lowering refuses a coloured optional cost outright (Island Fish Jasconius
    pays {U}{U}{U}), and the refusal is right for every other card that takes
    that path. Only the fused kind's own handler knows how to charge one.

    Returns None — not a refusal — for anything that is not exactly this shape,
    so a near miss ("…untap target creature", "…and you gain 1 life") drops back
    to the ordinary lowering and is refused there by name.
    """
    if node.event.kind != "upkeep_self" or node.intervening_if is not None:
        return None
    statement = node.statement
    if not isinstance(statement, ast.May):
        return None
    if statement.action is not None or statement.otherwise is not None:
        return None
    if not isinstance(statement.cost, ast.ManaCost) or not _is_you(statement.actor):
        return None
    # The consequence is untapping the source and nothing else. `untap_self`'s
    # handler is not consulted here — the fused handler untaps `ctx.permanent`
    # directly — so the subject is checked against the source rather than
    # against what any untap lowering would accept.
    then = statement.then
    if not isinstance(then, ast.Untap) or not _is_source(then.subject):
        return None
    return (
        OracleInstruction(
            "upkeep_pay_to_untap_self", "", {"mana": _full_mana_payload(statement.cost)}
        ),
    )


def _lower_line_statement(
    statement: ast.Statement, *, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """Lower the statement that is a line's *whole* effect.

    Identical to :func:`lower_statement` but for the one node whose meaning
    depends on occupying the whole clause: a modal head announces how many of
    the bulleted lines *below this line* the controller picks (CR 700.2), which
    is only true when it is what the line says. Nested, it refuses — see the
    `ModalNode` branch in `lower_statement`.
    """
    if isinstance(statement, ast.ModalNode):
        return _lower_modal_head(statement)
    return lower_statement(statement, event=event)


def lower_ability(node: ast.AbilityNode) -> tuple[OracleInstruction, ...]:
    """Lower a whole ability line. Keyword and static lines carry no
    instructions of their own — they are recorded by the compiler as keyword or
    static lines instead."""
    if isinstance(node, ast.SpellEffectLine):
        return _lower_line_statement(node.statement)
    if isinstance(node, ast.TriggeredAbilityNode):
        fused = _fused_upkeep_pay_to_untap(node)
        if fused is not None:
            return fused
        instructions = _lower_line_statement(node.statement, event=node.event.kind)
        # An upkeep trigger is dispatched by the (condition, instruction kind)
        # pair in engine/phases/upkeep_effects.py, whose handlers are written
        # against the *fused* kinds the legacy rules produce
        # (`upkeep_pay_to_untap_self`, …). A decomposed `may(pay, untap_self)`
        # is a more faithful reading of the card, but no upkeep handler is
        # keyed to it, so claiming the line would leave the card compiling
        # cleanly and doing nothing at all. Refuse until the upkeep flow can
        # execute decomposed instructions (roadmap phase 4).
        decomposed = set(_WRAPPER_KINDS) | {"may"}
        if node.event.kind.startswith("upkeep") and any(
            instruction.kind in decomposed for instruction in instructions
        ):
            raise LoweringError(
                "upkeep triggers are dispatched by fused instruction kind; a "
                "decomposed wrapper has no handler",
                node=node,
            )
        if node.intervening_if is not None:
            # CR 603.4: the condition is checked when the trigger would fire and
            # again on resolution. The legacy compiler dropped these outright,
            # so conditional triggers always fired.
            condition = _lower_condition(node.intervening_if)
            instructions = tuple(
                OracleInstruction(
                    instruction.kind, instruction.value,
                    {**instruction.payload, "intervening_if": condition},
                )
                for instruction in instructions
            )
        return instructions
    if isinstance(node, ast.ActivatedAbilityNode):
        return _lower_line_statement(node.statement)
    if isinstance(node, ast.KeywordLine):
        return ()
    if isinstance(node, ast.RegistryLine):
        # Zero instructions is the correct lowering, not a gap: the line is
        # already executed by a text-keyed registry reading the card's oracle
        # text (see engine/grammar/registries.py). Emitting anything here would
        # duplicate an effect the engine is already applying.
        return ()
    if isinstance(node, ast.DerivedLine):
        # The table computed the instruction when it claimed the line; asking it
        # again is what keeps this a delegation rather than a copy. It cannot
        # answer differently — every matcher in engine/grammar/derived.py is a
        # pure function of the text the node carries verbatim — but if the table
        # is ever narrowed out from under a node, refusing here is the loud
        # failure rather than an instruction nothing derives.
        derived = derived_instruction_for_line(node.text)
        if derived is None:  # pragma: no cover - defensive
            raise LoweringError(
                f"engine/grammar/derived.py no longer derives {node.table!r} "
                "for this line",
                node=node,
            )
        return (derived[1],)
    if isinstance(node, ast.StaticAbilityNode):
        return _lower_static_ability(node)
    raise LoweringError(f"no lowering for {type(node).__name__}", node=node)


def _lord_filter(filt: ast.ObjectFilter) -> LordBuffFilter:
    """The derivation table's view of *filt*, dropping nothing silently.

    Only the fields ``engine/lord_buffs.py`` carries are read here; whether that
    lost anything is decided by :func:`_object_filter_of` rebuilding the filter
    and the caller comparing the two for **equality**. Probing field by field
    ("refuse if attacking, refuse if tapped, …") is how a filter field added to
    the AST later slips past a check written before it existed — which is the
    exact failure this family already had once, when the consumer read the
    colour and the controller and ignored the rest of the sentence.
    """
    qualifier = next(
        (
            name
            for name, (field_name, value) in QUALIFIER_FIELDS.items()
            if getattr(filt, field_name) is value
        ),
        None,
    )
    return LordBuffFilter(
        colors=filt.colors,
        subtypes=filt.subtypes,
        controller=filt.controller,
        other_than_source=filt.other_than_source,
        qualifier=qualifier,
        with_plus1_counter=filt.with_plus1_counter,
    )


def _object_filter_of(lord: LordBuffFilter) -> ast.ObjectFilter:
    """*lord* back as an ``ObjectFilter`` — the round trip the equality uses."""
    fields: dict[str, object] = {
        "card_types": ("creature",),
        "colors": lord.colors,
        "subtypes": lord.subtypes,
        "controller": lord.controller,
        "other_than_source": lord.other_than_source,
        "with_plus1_counter": lord.with_plus1_counter,
    }
    if lord.qualifier is not None:
        field_name, value = QUALIFIER_FIELDS[lord.qualifier]
        fields[field_name] = value
    return ast.ObjectFilter(**fields)


def _lower_lord_effects(
    node: ast.StaticAbilityNode, effects: tuple[ast.Statement, ...]
) -> LordBuff:
    """The buff *effects* describe. They must all share one subject: "Other
    Goblins get +1/+1 and have mountainwalk" is one ability over one set."""
    subjects = {getattr(effect, "subject", None) for effect in effects}
    if len(subjects) != 1:
        raise LoweringError("a static ability over two different subjects", node=node)
    subject = subjects.pop()
    # "All creatures…" and "Each creature you control…" (Pridemalkin) name the
    # same set — a static ability applies to every object matching its
    # description (CR 611.3a), so the distributive article is a spelling, not a
    # different effect. The derivation table consumes both words the same way.
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier not in ("all", "each"):
        raise LoweringError("static abilities need the CR 613 layers engine", node=node)

    power = toughness = 0
    keywords: list[str] = []
    for effect in effects:
        if isinstance(effect, ast.Pump):
            power = _signed(effect.power, effect.power_negative)
            toughness = _signed(effect.toughness, effect.toughness_negative)
            if not isinstance(power, int) or not isinstance(toughness, int):
                raise LoweringError("a variable continuous buff has no channel", node=node)
        elif isinstance(effect, ast.GainKeyword):
            for keyword in effect.keywords:
                if keyword not in grantable_keywords():
                    raise LoweringError(
                        f"engine/lord_buffs.py grants no {keyword!r} at layer 6", node=node
                    )
                keywords.append(keyword)
        else:
            raise LoweringError("static abilities need the CR 613 layers engine", node=node)

    lord_filter = _lord_filter(subject.filter)
    if _object_filter_of(lord_filter) != subject.filter:
        raise LoweringError(
            "engine/lord_buffs.py carries no such restriction on the buffed "
            "creatures, so _recalculate_lord_buffs would drop it",
            node=node,
        )
    # A *union* is a separate question from a missing field, and the round trip
    # above cannot answer it: the table's own text parser reads one colour and
    # one subtype, so a grammar-only union would be a payload no printed card
    # produces and no test covers. Whether "white or blue creatures" means an
    # OR is decided when a card needs it.
    if len(lord_filter.colors) > 1 or len(lord_filter.subtypes) > 1:
        raise LoweringError(
            "engine/lord_buffs.py derives one colour and one subtype; a union "
            "has no matching rule behind it",
            node=node,
        )
    return LordBuff(lord_filter, power, toughness, tuple(keywords))


def _lower_static_ability(node: ast.StaticAbilityNode) -> tuple[OracleInstruction, ...]:
    """A continuous buff to a set of creatures, derived by ``engine/lord_buffs.py``.

    "Black creatures get +1/+1" (Bad Moon, Crusade, Gauntlet of Might), "Other
    Goblins get +1/+1 and have mountainwalk" (Goblin King, Lord of Atlantis),
    "Attacking creatures you control get +1/+0" (Orcish Oriflamme) and "Untapped
    creatures you control get +0/+2" (Castle) are one template with parameters,
    and ``_recalculate_lord_buffs`` now honours every one of them.

    **This is not the spell reading of the same sentence, and must not become
    it.** "Attacking creatures get +2/+0 *until end of turn*" is Army of Allah:
    a one-shot effect that locks its set in at resolution (CR 611.2c) and keeps
    ``buff_creatures_global``. Duration is what separates them, and a line
    carrying one never reaches this function — it lowers through ``_lower_pump``.

    What still refuses, and why the reason names code:

    - **A condition** ("as long as you control a Forest") belongs to
      ``engine/static_bonuses.py``, which derives the bonus from the text.
    - **A restriction the table does not carry.** The filter is rebuilt from
      what ``LordBuffFilter`` holds and compared for **equality** against the
      one the parser produced, so anything lost in that round trip refuses. A
      field added to ``ObjectFilter`` later is refused by default rather than
      ignored by a check that predates it.
    """
    if node.condition is not None:
        raise LoweringError(
            "a conditional static bonus is derived by engine/static_bonuses.py",
            node=node,
        )
    effect = node.effect
    effects = effect.effects if isinstance(effect, ast.Conjunction) else (effect,)
    buff = _lower_lord_effects(node, effects)
    return (OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(buff)),)


# Control-flow wrappers take the categories of whatever they wrap, so gating
# "damage" is enough to turn on a sequence of damage instructions without
# inventing a category nobody could reason about.
#
# ``may`` is deliberately NOT in here: it gets its own ungated category below.
# Lowering an optional action is correct, but the prompt it raises still rides
# the one-card ``pending_optional_pays`` flow, and cards already on that flow
# (Soul Net, the Rod cycle) hold their trigger on the stack until the player
# answers — behavior the generic handler does not yet reproduce. Switching
# "optional" on is gated behind the pending-choice queue.
_WRAPPER_KINDS: dict[str, tuple[str, ...]] = {
    "sequence": ("steps",),
    "if_then": ("then", "else"),
    "for_each": ("effect",),
}


def categories_of(instructions: tuple[OracleInstruction, ...]) -> frozenset[str]:
    """Migration categories covered by a lowered instruction sequence."""
    found: set[str] = set()
    for instruction in instructions:
        nested_keys = _WRAPPER_KINDS.get(instruction.kind)
        if nested_keys is not None:
            nested: tuple[OracleInstruction, ...] = ()
            for key in nested_keys:
                nested += tuple(instruction.payload.get(key) or ())
            if not nested:
                return frozenset({"__ungated__"})
            inner = categories_of(nested)
            if "__ungated__" in inner:
                return frozenset({"__ungated__"})
            found |= inner
            continue
        category = INSTRUCTION_CATEGORIES.get(instruction.kind)
        if category is None:
            return frozenset({"__ungated__"})
        found.add(category)
    return frozenset(found)


__all__ = [
    "GRAMMAR_ONLY_PAYLOAD_KEYS",
    "INSTRUCTION_CATEGORIES", "categories_of", "lower_ability", "lower_statement",
]

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

from ..oracle_types import OracleInstruction
from . import ast
from .derived import derived_instruction_for_line
from .errors import LoweringError
from .statics import _lower_static_ability
from .lowering import (
    count_spec,
    # Re-exported, not used here: callers outside the package import these two
    # from `engine.grammar.lower` (`grammar/__init__.py`,
    # `tests/engine/test_grammar_categories.py`, `test_grammar_lowering.py`).
    # Moving the definitions into `lowering/` did not move their address, which
    # is what kept this a pure move rather than a rename with a diff attached.
    GRAMMAR_ONLY_PAYLOAD_KEYS,
    INSTRUCTION_CATEGORIES,
    categories_of,
    # The scratchpad-producer registry and the wrapper walkers moved to
    # `lowering/categories.py` and `lowering/_common.py`; the dispatch
    # below still reads them, and callers outside the package keep this
    # address.
    _PRODUCES,
    _fused_upkeep_pay_to_untap,
    _mentions_x,
    _refuse_unfused_distinctness,
    _stamp_x_from_count,
    _fused_discard_then_draw,
    _fused_draw_then_discard,
    _fused_exile_then_controller_life,
    _lower_add_mana,
    _lower_add_mana_for_tapped_land,
    _lower_become_color,
    _lower_gain_type,
    _lower_cant_be,
    _lower_change_text,
    _lower_combat_restriction,
    _lower_counter_ability,
    _lower_counter_spell,
    _lower_create_emblem,
    _lower_create_copy_token,
    _lower_create_token,
    _lower_damage,
    _lower_damage_conjunction,
    _lower_damage_unless_pay,
    _fused_conditional_counter,
    _fused_prepare_then_interact,
    _fused_tap_any_number_then_pump,
    _fused_two_target_pump,
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
    _lower_become_creature,
    _lower_pump,
    _lower_player_gets_counters,
    _lower_put_counter,
    _lower_phase_out,
    _lower_put_on_library_bottom,
    _lower_put_on_library_top,
    _lower_put_onto_battlefield,
    _lower_regenerate,
    _lower_reveal_top,
    _lower_reveal_until,
    _lower_remove_counter,
    _lower_return_to_zone,
    _lower_sacrifice,
    _lower_sacrifice_expansion_permanents,
    _lower_shuffle_graveyard_into_library,
    _lower_sacrifice_unless_pay,
    _lower_cast_from_exiled_with,
    _lower_cast_permission,
    _lower_exile_graveyard_until_leaves,
    _lower_transmute_by_sacrifice,
    _lower_exile_until_leaves_or_untaps,
    _lower_ownership_exchange_unless_paid,
    _lower_exile_top_of_library,
    _lower_look_top_pick,
    _lower_search_and_exile,
    _lower_search_library,
    _lower_change_base_pt,
    _lower_set_base_pt,
    _lower_doesnt_untap_next_step,
    _lower_delayed_self_action,
    _lower_doesnt_untap_while_source_tapped,
    _lower_condition,
    _lower_tap,
    _lower_tap_or_untap,
    _lower_attach,
    _lower_win_game,
)


# ---------------------------------------------------------------------------
# Statement dispatch
# ---------------------------------------------------------------------------


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
    if isinstance(statement, ast.ChangeBasePT):
        return _lower_change_base_pt(statement)
    if isinstance(statement, ast.GainKeyword):
        return _lower_gain_keyword(statement)
    if isinstance(statement, ast.LoseKeyword):
        return _lower_lose_keyword(statement)
    if isinstance(statement, ast.PutCounter):
        return _lower_put_counter(statement)
    if isinstance(statement, ast.PlayerGetsCounters):
        return _lower_player_gets_counters(statement, event)
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
    if isinstance(statement, ast.DoesntUntapNextStep):
        # `produced` is the whole gate: this sentence acts on what an earlier
        # step of the same effect recorded, so it refuses when nothing did.
        return _lower_doesnt_untap_next_step(statement, produced)
    if isinstance(statement, ast.DelayedSelfAction):
        return _lower_delayed_self_action(statement)
    if isinstance(statement, ast.DoesntUntapWhileSourceTapped):
        return _lower_doesnt_untap_while_source_tapped(statement)
    if isinstance(statement, (ast.Tap, ast.Untap)):
        return _lower_tap(statement)
    if isinstance(statement, ast.TapOrUntap):
        return _lower_tap_or_untap(statement)
    if isinstance(statement, ast.Attach):
        return _lower_attach(statement)
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
    if isinstance(statement, ast.CreateCopyToken):
        return _lower_create_copy_token(statement)

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

    if isinstance(statement, ast.BecomeCreature):
        return _lower_become_creature(statement)

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

    if isinstance(statement, ast.CounterAbility):
        return _lower_counter_ability(statement)

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

    if isinstance(statement, ast.RevealTop):
        # CR 701.20b: revealing shows a card and moves nothing, so the whole
        # effect is the record it leaves for the sentences after it.
        return (OracleInstruction("reveal_top_of_library", "", {}),)
    if isinstance(statement, ast.RevealTopToHandOrBottom):
        return _lower_reveal_top(statement)

    if isinstance(statement, ast.Sacrifice):
        return _lower_sacrifice(statement)
    if isinstance(statement, ast.SacrificeExpansionPermanents):
        return _lower_sacrifice_expansion_permanents(statement)
    if isinstance(statement, ast.GainType):
        return _lower_gain_type(statement)
    if isinstance(statement, ast.ShuffleGraveyardIntoLibrary):
        return _lower_shuffle_graveyard_into_library(statement)

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
        return _lower_look_top_pick(statement, event)

    if isinstance(statement, ast.SearchAndExile):
        return _lower_search_and_exile(statement)

    if isinstance(statement, ast.ExileGraveyardUntilLeaves):
        return _lower_exile_graveyard_until_leaves(statement)

    if isinstance(statement, ast.TransmuteBySacrifice):
        return _lower_transmute_by_sacrifice(statement)

    if isinstance(statement, ast.OwnershipExchangeUnlessPaid):
        return _lower_ownership_exchange_unless_paid(statement)

    if isinstance(statement, ast.ExileUntilLeavesOrUntaps):
        return _lower_exile_until_leaves_or_untaps(statement)

    if isinstance(statement, ast.CastFromExiledWith):
        return _lower_cast_from_exiled_with(statement)

    if isinstance(statement, ast.CastPermission):
        return _lower_cast_permission(statement, produced)

    if isinstance(statement, ast.NameAndStrip):
        return (
            OracleInstruction(
                "name_and_strip", "",
                {
                    "zones": list(statement.zones),
                    "token_zone": statement.token_zone,
                    "token": {
                        "power": statement.token_power,
                        "toughness": statement.token_toughness,
                        "colors": list(statement.token_colors),
                        "subtypes": list(statement.token_subtypes),
                    },
                },
            ),
        )

    if isinstance(statement, ast.RevealUntil):
        return _lower_reveal_until(statement, produced)

    if isinstance(statement, ast.CopyThatSpell):
        return (OracleInstruction("copy_triggering_spell", "", {}),)

    if isinstance(statement, ast.ExtraTurn):
        return _lower_extra_turn(statement)

    if isinstance(statement, ast.EndTheTurn):
        return (OracleInstruction("end_the_turn", "", {}),)

    if isinstance(statement, ast.LoseGame):
        return _lower_lose_game(statement)

    if isinstance(statement, ast.WinGame):
        return _lower_win_game(statement)

    if isinstance(statement, ast.ChooseNumber):
        # The bounds are all there is to carry: what the number is *for* is a
        # different sentence on the card (Shapeshifter's characteristic-defining
        # P/T), which reads it back off the permanent.
        return (
            OracleInstruction(
                "choose_number", "",
                {"minimum": statement.minimum, "maximum": statement.maximum},
            ),
        )

    if isinstance(statement, ast.FlipCoin):
        # CR 705.1: the flip is the whole sentence, and it takes no payload. What
        # happens next is the conditional sentences after it, which read the
        # result this one records (`_PRODUCES`).
        return (OracleInstruction("flip_coin", "", {}),)

    if isinstance(statement, ast.DrawGame):
        # "The game is a draw." (CR 104.4c.) `game_is_draw` takes an empty
        # payload and the sentence carries nothing else, so there is nothing to
        # check and nothing that could be dropped.
        return (OracleInstruction("game_is_draw", "", {}),)

    if isinstance(statement, ast.CombatRestriction):
        return _lower_combat_restriction(statement)

    if isinstance(statement, ast.CantBe):
        return _lower_cant_be(statement)

    if isinstance(statement, ast.WhereX):
        return _lower_where_x(statement, produced, event)

    if isinstance(statement, ast.ForEach):
        return _lower_for_each(statement)

    if isinstance(statement, ast.Exile):
        return _lower_exile(statement)

    if isinstance(statement, ast.Sequence):
        for fuse in (
            # Before its mirror: both take (Discard, Draw)-shaped pairs in the
            # opposite order, and this one additionally requires "that many",
            # so neither can claim the other's sentence — the order is stated
            # rather than relied on.
            _fused_discard_then_draw,
            _fused_draw_then_discard,
            _fused_exile_then_controller_life,
            _fused_prepare_then_interact,
            _fused_two_target_pump,
            _fused_conditional_counter,
            _fused_tap_any_number_then_pump,
        ):
            fused = fuse(statement.steps)
            if fused is not None:
                return fused
        _refuse_unfused_distinctness(statement.steps)
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
                    "condition": _lower_condition(statement.condition, produced),
                    "then": then,
                    "else": otherwise,
                },
            ),
        )

    if isinstance(statement, ast.OneOf):
        return _lower_one_of(statement, produced, event)

    if isinstance(statement, ast.May):
        return _lower_may(statement, produced, event)

    if isinstance(statement, ast.RawEffect) and statement.text == "grant_team_assign_unblocked_until_eot":
        # Garruk, Savage Herald's −7 — the one quoted team grant with a
        # handler. Any other RawEffect keeps refusing below.
        return (OracleInstruction("grant_team_assign_unblocked_until_eot", "", {}),)

    raise LoweringError(f"no lowering for {type(statement).__name__}", node=statement)


def _lower_where_x(
    node: ast.WhereX, produced: frozenset[str], event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…, where X is the number of <filter>" over a whole sentence.

    The definition is stamped onto the lowered instructions rather than folded
    into their amounts, because the count is taken **at resolution** (CR 608.2):
    a Shrine entering between the trigger and its resolution changes the answer,
    so lowering cannot know it. ``engine/mixins/oracle_instructions.py``
    resolves it into the context's X at the single dispatch point, which is what
    lets one clause serve every effect family instead of one.
    """
    if isinstance(node.definition, ast.CountOfDeaths):
        return _lower_where_x_deaths(node, produced, event)
    if isinstance(node.definition, ast.ManaValueOfSubject):
        return _lower_where_x_mana_value(node, produced, event)
    if not isinstance(node.definition, ast.CountOf):
        raise LoweringError("only a count can define X in a where-clause", node=node)
    spec = count_spec(node.definition.filter, node)
    inner = lower_statement(node.statement, produced, event=event, whole_effect=False)
    if not _mentions_x(inner):
        # The clause defined an X the sentence never used, which means one of
        # them was misread. Refusing keeps that loud instead of executing the
        # sentence with the definition quietly discarded.
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, spec)


def _lower_where_x_mana_value(
    node: ast.WhereX, produced: frozenset[str], event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…, where X is **its** mana value." (Great Defender, Subdue, Kry Shield.)

    Stamped like every other where-clause and resolved at the same single
    dispatch point, so the sentence in front of it needs no special case: what
    changes is only *what* is counted. "Its" is the object the sentence already
    named — the resolution reads it off the chosen target, which is the one
    object a resolution can name without a second choice.
    """
    inner = lower_statement(node.statement, produced, event=event, whole_effect=False)
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    # "Its" is whatever object the sentence already named, and the sentence
    # names it one of two ways: by targeting a permanent, or by binding the
    # spell its trigger fired on ("Whenever a player casts an instant spell,
    # counter it unless that player pays {X}, where X is **its** mana value").
    # Decided here, where both the definition and the lowered sentence are in
    # hand, rather than by a resolution-time fallback order that would have to
    # guess when a sentence has both.
    names_a_spell = any(i.payload.get("bound_to_trigger") for i in inner)
    return _stamp_x_from_count(
        inner,
        {"object_mana_value": "triggering_spell" if names_a_spell else "target"},
    )


def _lower_where_x_deaths(
    node: ast.WhereX, produced: frozenset[str], event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…where X is the number of creatures that died under your control this
    turn." (Liliana's Standard Bearer.)

    The count is a per-seat turn history (``engine/models.py``'s
    ``creatures_died_under_your_control_this_turn``, kept since round 14 because
    the game-wide tally cannot answer "under your control"), so it reads a
    counter rather than a zone. Only the bare creature filter is admitted: the
    tracker counts creatures and nothing narrower, and a narrowing it cannot
    apply would be counted as if it were not there.
    """
    filt = node.definition.filter
    if filt.to_payload() != {"type_filter": "creature"} or filt.zone != "battlefield":
        raise LoweringError(
            "the death tracker counts creatures and cannot be narrowed", node=node
        )
    inner = lower_statement(node.statement, produced, event=event, whole_effect=False)
    if not _mentions_x(inner):
        raise LoweringError("a where-clause defined an X nothing reads", node=node)
    return _stamp_x_from_count(inner, {"history": "creatures_died_under_your_control"})


def _lower_one_of(
    node: ast.OneOf, produced: frozenset[str], event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"A **or** B" — one action, two ways to take it, lowered onto the modal
    handler the printed "Choose one —" already uses.

    The same *question* is being asked (which of these does the controller
    pick?), so it is the same prompt and the same handler; what differs is only
    where the alternatives were printed. Inventing a second mechanism would mean
    two prompts, two defaults and two places for a mode to go unoffered.

    Each option must lower to exactly one instruction: the mode payload carries
    one, and a silently truncated option is a branch the player could choose and
    then not get.
    """
    modes = []
    for index, option in enumerate(node.options):
        lowered = lower_statement(option, produced, event=event, whole_effect=False)
        if len(lowered) != 1:
            raise LoweringError(
                "an alternative that is not a single instruction has no mode to "
                "put it in",
                node=option,
            )
        label = node.labels[index] if index < len(node.labels) else ""
        modes.append({"label": label, "instruction": lowered[0]})
    return (OracleInstruction("choose_one", "", {"modes": tuple(modes)}),)


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
    # "If you do" is the rest of *this* resolution, so it can read what the
    # action just recorded: Niambi's "return another target creature you
    # control…, if you do, you gain life equal to that creature's mana value"
    # is the bounce's own record, read one instruction later. The three other
    # branches deliberately keep the outer set —
    #
    # * ``otherwise`` runs precisely when the action did *not* happen, so its
    #   records do not exist;
    # * ``reflexive`` is a separate ability under CR 603.12, created by the
    #   action and resolving later with a scratchpad of its own;
    # * the offer's own cost records nothing at all.
    #
    # Threading the action's set into any of those would make a back-reference
    # compile where nothing will have written it, and an unwritten quantity
    # reads as zero.
    after_action = produced | {
        key for instruction in action
        if (key := _PRODUCES.get(instruction.kind)) is not None
    }
    then = lower_statement(node.then, after_action, event=event, whole_effect=False) if node.then else ()
    otherwise = lower_statement(node.otherwise, produced, event=event, whole_effect=False) if node.otherwise else ()
    reflexive = (
        lower_statement(node.reflexive, produced, event=event, whole_effect=False)
        if node.reflexive else ()
    )

    payload: dict[str, object] = {"actor": node.actor.kind}
    if node.cost is not None:
        if not isinstance(node.cost, ast.ManaCost):
            raise LoweringError("only mana costs can be offered optionally", node=node)
        # The whole cost, symbol by symbol. It used to be the generic part
        # alone, with a coloured pip refusing the line — not a parser gap but a
        # *payer* one: the prompt collected its cost by counting to a number, so
        # a {B} had nothing to collect it with. `engine/mana_payment.py` is what
        # made the refusal unnecessary.
        payload["cost"] = dict(node.cost.pips)
    if action:
        payload["action"] = action
    if then:
        payload["then"] = then
    if otherwise:
        payload["otherwise"] = otherwise
    # CR 603.12: a separate key, never merged into `then`, because the handler
    # has to treat it as a separate ability — it chooses its own targets when the
    # payment creates it, and the ``then`` branch has none of its own to choose.
    if reflexive:
        payload["reflexive"] = reflexive
    if not (action or then or otherwise or reflexive):
        raise LoweringError("an optional action with no consequence", node=node)
    return (OracleInstruction("may", "", payload),)


def _lower_steps(
    steps: tuple[ast.Statement, ...],
    produced: frozenset[str],
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """Lower consecutive steps, threading what each one records forward."""
    instructions: tuple[OracleInstruction, ...] = ()
    last_produced: str | None = None
    for step in steps:
        # "…**If you do**, …" after an action that was not optional. The branch
        # asks whether the step before it took place, and this is the one place
        # that knows which step that was *and* what it records — so the pairing
        # is made here rather than in a field on the node, where it would be a
        # second copy of ``_PRODUCES`` free to disagree with the first.
        if isinstance(step, ast.Conditional) and isinstance(
            step.condition, ast.ItHappened
        ):
            if last_produced is None:
                raise LoweringError(
                    "\"if you do\" after a step that records nothing has no "
                    "condition to test",
                    node=step,
                )
            branch = lower_statement(
                step.then, produced, event=event, whole_effect=False
            )
            instructions += (
                OracleInstruction(
                    "if_then", "",
                    {
                        "condition": {"kind": "it_happened", "key": last_produced},
                        "then": branch,
                    },
                ),
            )
            last_produced = None
            continue
        lowered = lower_statement(step, produced, event=event, whole_effect=False)
        last_produced = None
        for instruction in lowered:
            result = _PRODUCES.get(instruction.kind)
            if result is not None:
                produced = produced | {result}
                last_produced = result
        instructions += lowered
    return instructions


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
        # A spell whose **whole** effect is optional. `_lower_may` has carried
        # this as a known limit since it was written, measured on this exact card
        # (Twiddle): the prompt rides `pending_optional_pays`, and only the
        # triggered-ability resolution path holds that queue open and drains it,
        # so a spell — which leaves the stack the instant it resolves — would
        # queue its effect and never perform it. It went unenforced because no
        # line reached the shape; round 88 made one reachable by teaching the
        # tap-or-untap toggle to read its noun phrase, and Twiddle's hook was
        # silently shadowed by a `may` that did nothing.
        #
        # Only the *whole* line, and only a spell's: a `may` that is one sentence
        # of a longer spell (Basri's Aegis, Liliana's Scorn) has steps in front
        # of it that run, and a trigger remainder is the shape the queue was
        # built for.
        if isinstance(node.statement, ast.May):
            raise LoweringError(
                "a spell whose whole effect is optional has no prompt that "
                "outlives its resolution",
                node=node.statement,
            )
        return _lower_line_statement(node.statement)
    if isinstance(node, ast.TriggeredAbilityNode):
        fused = _fused_upkeep_pay_to_untap(node)
        if fused is not None:
            return fused
        instructions = _lower_line_statement(node.statement, event=node.event.kind)
        # This used to refuse every decomposed upkeep trigger — a
        # `may(pay, untap_self)` where the registry in
        # engine/phases/upkeep_effects.py wanted a fused
        # `upkeep_pay_to_untap_self` — because the registry was the *only*
        # dispatcher an upkeep trigger had, so claiming the line would have left
        # the card compiling cleanly and doing nothing.
        #
        # The upkeep step now puts an ordinary trigger on the stack (CR 603.3)
        # when the registry answers nothing, so a wrapper has somewhere to run
        # and the refusal has nothing left to protect. The registry keeps the
        # pay-or-consequence shapes, which are asked first; the fused kinds still
        # come out of `_fused_upkeep_pay_to_untap` above, unchanged.
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


__all__ = [
    "GRAMMAR_ONLY_PAYLOAD_KEYS",
    "INSTRUCTION_CATEGORIES", "categories_of", "lower_ability", "lower_statement",
]

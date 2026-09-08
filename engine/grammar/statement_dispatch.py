"""``lower_statement`` — one AST node routed to the family that lowers it.

Split out of ``lower.py`` when Alliances' third wave took that module past the
1,000-line cap with **no single group at fault**: four branches each added a
handful of arms under the cap and the sum crossed it, which is the shape
SET_PLAYBOOK.md tells the integrator to split at rather than to carry.

The seam is the one ``lower.py``'s own docstring already drew — "``lower_statement``
routes one AST node to its family, ``lower_ability`` wraps that for a whole
line" — and the half that moved is the half that *grows*. That is
``by_node.py``'s rule applied a second time: a registry inside a dispatcher is
the thing every landed card appends to, so it is the half that leaves. Here
both halves are dispatch, and the chain of 79 arms is the one a new template
lands in; the line wrappers around it have not moved in four sets.

Beside ``lower.py`` rather than under ``lowering/`` for ``by_node``'s reason
exactly: this is the dispatch layer, not an effect family. It imports every
family, so a module inside that package would be neither a family (families do
not import each other) nor a floor (a floor is read *by* families, and this
reads them).

``lower.py`` re-exports :func:`lower_statement`, so the name's address is
unchanged — the same promise that file's docstring makes about
``INSTRUCTION_CATEGORIES``.
"""

from ..oracle_types import OracleInstruction
from . import ast
from .errors import LoweringError
from .lowering._events import LOOP_BOUND_OBJECT, LOOP_BOUND_PLAYER
from .lowering.where_x import lower_where_x
from .lowering.control_flow import (
    _lower_may, _lower_one_of, _lower_unless_player_pays,
)
from .lowering.board import (_lower_exile_one_of_chosen,
                            _lower_sacrifice_unless_pay)
from .lowering.sequences import _lower_steps
from .lowering.loops import (
    _lower_for_each,
    _lower_for_each_cost_paid,
    _lower_for_each_counters_placed,
    _lower_for_each_life_lost,
    _lower_for_each_matching,
    _lower_for_each_player,
)
from .lowering import (
    INSTRUCTION_CATEGORIES,
    _refuse_unfused_distinctness,
    _fused_discard_then_draw,
    _fused_draw_then_discard,
    _fused_exile_then_controller_life,
    _fused_exile_event_subject_until_source_leaves,
    _lower_add_mana,
    _lower_become_color,
    _lower_cant_be,
    _lower_remove_from_combat,
    _lower_combat_restriction,
    lower_block_count_grant,
    _lower_create_delayed_trigger,
    _lower_next_draw_replacement,
    _lower_create_token,
    _lower_damage,
    _lower_damage_conjunction,
    _lower_damage_unless_pay,
    _fused_conditional_counter,
    _fused_tap_enchanted_then_counters,
    _fused_tap_then_bite,
    _fused_prepare_then_interact,
    _fused_tap_any_number_then_pump,
    _fused_two_target_keyword_move,
    _fused_two_target_pump,
    _fused_cost_repeated_destroys,
    _lower_fight,
    _lower_delayed_destroy,
    _lower_destroy,
    _lower_draw,
    _lower_exile,
    _lower_repeat_for_types,
    _lower_repeat_optional_process,
    _lower_put_exiled_with_source,
    _lower_put_library_top_into_hand,
    _lower_repeat_process,
    _lower_repeat_process_while,
    _lower_for_each_destroyed,
    _lower_for_each_exiled,
    _lower_for_each_tapped,
    _lower_for_each_chosen,
    _lower_for_each_short_of_this_way,
    _lower_announced_choice,
    _lower_choose_permanent,
    _lower_choose_permanents,
    _lower_gain_control,
    _lower_gain_ability_text,
    _lower_prevent_damage,
    _lower_put_on_library_top,
    _lower_chosen_source_next_damage,
    _lower_gain_keyword,
    _lower_lose_keyword,
    _lower_pump,
    _lower_phase_out,
    _lower_gain_life,
    _lower_discard_revealed_matching_unless_pay_life,
    _lower_discard_revealed_unless_pay_life,
    _lower_lose_life,
    _lower_bin_revealed_card,
    _lower_put_revealed_card_onto_battlefield,
    _lower_put_milled_card_onto_battlefield,
    _lower_put_counter,
    _lower_put_onto_battlefield,
    _lower_remove_counter,
    _lower_return_to_zone,
    _lower_sacrifice,
    _lower_destroy_unless_pay,
    _lower_cast_permission,
    _lower_search_player_library,
    _lower_graveyard_pick_onto_battlefield,
    _lower_untap_restriction,
    _lower_condition,
    pronoun_target_referent,
    _lower_tap,
)


#: The node types whose lowering is *only* a name — one AST class, one
#: function, nothing to decide. These were 78 two-line branches of the chain
#: below: 156 lines saying what a dict says in 78, growing by three every time
#: a round adds a node. Dispatching them by type is what every other seam in
#: this engine already does (`EFFECT_HANDLERS` is the one the architecture
#: notes name), and it is what the module-size guard was pointing at — the
#: families were absorbing the work; the chain grew anyway, by construction.
#:
#: The chain below keeps every branch that *decides* something: a node whose
#: lowering depends on its own fields, on the firing event, or on which of
#: several kinds it should become.
#:
#: Read before the chain, which is safe by construction rather than by
#: inspection: no class in this table appears anywhere else in the chain and
#: none of them inherits from another, so at most one branch could ever have
#: matched a given node.
from .statement_dispatch_naming import lower_naming_statement
from .by_node import (_BY_NODE_TYPE, _BY_NODE_TYPE_WITH_EVENT,
                      _BY_NODE_TYPE_WITH_EVENT_AND_PRODUCED,
                      _BY_NODE_TYPE_WITH_PRODUCED)


# ---------------------------------------------------------------------------
# Statement dispatch
# ---------------------------------------------------------------------------


def lower_statement(
    statement: ast.Statement,
    produced: frozenset[str] = frozenset(),
    *,
    event: str | None = None,
    event_subject: object | None = None,
    whole_effect: bool = True,
) -> tuple[OracleInstruction, ...]:
    """Lower one statement into the instructions that perform it, in order.

    *produced* names the scratchpad values earlier steps of the same effect
    already recorded; a back-reference without a producer is refused.

    *event_subject* is that trigger's printed narrowing — the noun phrase in
    "…becomes blocked **by a creature**" — and travels with *event* because it
    is the same fact about the same trigger. Two spellings share a kind and
    differ only here, and the difference decides whether "that creature" names
    one object or several (CR 509.3c/509.3d), so a reader given the kind alone
    has to guess and was wrong in both directions.

    *event* is the trigger kind when this statement is (part of) a triggered
    ability's effect, and None everywhere else. It is threaded into nested
    statements because it is simply true of them: every clause of a trigger is
    under that trigger's event, so "that player" and "that much" refer to it
    wherever in the sentence they sit. Gloom Sower is why — its "that creature's
    controller" is one half of a conjunction, and an unthreaded event left it
    lowering as an ordinary chosen target that happens to be right with two
    players.

    *whole_effect* is the distinction that was hiding inside the unthreaded
    parameter, and it is a different question: some lowerings pick between two
    engine *dispatch* paths by the trigger kind (the upkeep pay-or-else
    registry, an Aura's mana trigger), and each of those registries dispatches
    on the ability's whole instruction. A nested occurrence is not that
    instruction, so those readers see None and refuse rather than emitting a
    kind nothing will reach.

    The delayed block-pair destroy used to be filtered here too and is not any
    more: it asks the event whether the trigger bound *one* creature, which is
    a fact about the trigger rather than about where in the sentence the clause
    sits, and the kind it produces reaches its handler through the ordinary
    dict dispatch however deeply it is nested. Filtered, it refused Infinite
    Authority — a trigger whose effect is two sentences, so the destroy lowers
    under a `Sequence` and saw no event at all.
    """
    dispatch_event = event if whole_effect else None
    # The narrowing follows the kind through the same gate: a nested
    # occurrence is not the ability's whole instruction, so a registry
    # keyed on it must see neither half.
    dispatch_subject = event_subject if whole_effect else None
    # The name-only lowerings, by node type (see `_BY_NODE_TYPE`).
    lowering = _BY_NODE_TYPE.get(type(statement))
    if lowering is not None:
        return lowering(statement)
    # The same registry one argument wider (see `_BY_NODE_TYPE_WITH_EVENT`).
    # The **raw** `event`, not `dispatch_event`: every row here reads the event
    # to answer a printed "that player", and a seat pronoun means the firing
    # event's seat wherever in the sentence it is printed — including inside an
    # offer's branch, which is not the ability's whole effect and so sees no
    # `dispatch_event` at all. The three branches this table absorbed all passed
    # the raw one, and passing the narrowed one instead silently pointed Cloak
    # of Confusion's and Mindstab Thrull's discards at the wrong seat.
    lowering = _BY_NODE_TYPE_WITH_EVENT.get(type(statement))
    if lowering is not None:
        return lowering(statement, event)
    # …and the third: a node whose lowering reads what earlier steps of this
    # same effect recorded (see `_BY_NODE_TYPE_WITH_PRODUCED`).
    lowering = _BY_NODE_TYPE_WITH_PRODUCED.get(type(statement))
    if lowering is not None:
        return lowering(statement, produced)
    # …and the fourth: a node carrying two pronouns, one answered by the firing
    # event and one by the records (see `_BY_NODE_TYPE_WITH_EVENT_AND_PRODUCED`).
    lowering = _BY_NODE_TYPE_WITH_EVENT_AND_PRODUCED.get(type(statement))
    if lowering is not None:
        return lowering(statement, event, produced)

    # "Sacrifice **it** unless you pay its mana cost reduced by {2}" (Flash).
    # In the chain rather than in the name-only table above because the pronoun
    # is only a pronoun *relative to what came before it*: with no record from
    # an earlier step of the same sentence, "it" has no referent but the source,
    # and the two readings lower to different machinery.
    if isinstance(statement, ast.SacrificeUnlessPay):
        return _lower_sacrifice_unless_pay(statement, produced)
    if isinstance(statement, ast.Draw):
        # "…then draws **as many cards as they discarded this way**" (Forget).
        # A back-reference names its producer or refuses, and only `produced`
        # can say whether a step of this same effect recorded one — which is
        # why the draw left `by_node`'s name-only table, whose rows take the
        # node and nothing else.
        return _lower_draw(statement, produced, event)
    if isinstance(statement, ast.DealDamage):
        # The **unfiltered** event and its subject: "that creature's controller"
        # under a damage trigger names one of the event's *two* objects, and
        # which one is decided by how the condition spelled its damager
        # (`damage_trigger_names_damaged_end`). A reader given the kind alone
        # cannot tell Backfire's end from Bellowing Fiend's.
        return _lower_damage(statement, event, produced, event_subject)
    if isinstance(statement, ast.Fight):
        return _lower_fight(statement, whole_effect)
    if isinstance(statement, ast.DamageUnlessPay):
        return _lower_damage_unless_pay(statement, dispatch_event, produced)
    if isinstance(statement, ast.Pump):
        # "…**that creature** gets +1/+1 until end of turn." (Flailing Drake.)
        # The **unfiltered** event and its subject, for `_lower_lose_keyword`'s
        # reason directly below: the pump asks whether the trigger bound exactly
        # one creature, which is a fact about the *trigger* rather than about
        # where in the sentence the clause sits — and `binds_block_pair` cannot
        # answer it from the kind alone (CR 509.3c/509.3d).
        #
        # It left `_BY_NODE_TYPE` for that: the name-only table is for a node
        # whose lowering decides nothing, and a pump now picks between two
        # engine kinds by what the firing event bound.
        return _lower_pump(statement, event, event_subject)
    if isinstance(statement, ast.LoseKeyword):
        # The **unfiltered** event and its subject, for `_lower_destroy`'s
        # reason below: the removal asks whether the trigger bound exactly one
        # creature, and `binds_block_pair` cannot answer that from the kind
        # alone (CR 509.3c/509.3d — the printed narrowing is the difference).
        return _lower_lose_keyword(statement, dispatch_event, event_subject)
    if isinstance(statement, ast.PhaseOut):
        # The **unfiltered** event, for `_lower_destroy`'s reason below: the
        # phase-out asks whether the trigger bound one creature
        # (CR 509.3c/509.3d), which is a fact about the trigger and true of
        # every clause under it. Dream Fighter's sentence is a union of two
        # subjects, so it lowers under a `Conjunction` and would see no event
        # at all if this were gated on `whole_effect`.
        return _lower_phase_out(statement, event, event_subject, produced)
    if isinstance(statement, ast.PutCounter):
        # The narrowing travels with the event for `_lower_destroy`'s reason,
        # and so does the **unfiltered** event beside it: "put four fungus
        # counters on **that creature**" (Mindbender Spores) asks whether the
        # block trigger named one creature, which is a fact about the trigger
        # and true of every clause under it — and that clause is the first of
        # the trigger's *two* sentences, so it lowers under a `Sequence` and a
        # `whole_effect` gate would show it no event at all. The filtered event
        # still travels as its own argument, because the branches that pick a
        # *dispatch* path by trigger kind read that one.
        return _lower_put_counter(
            statement, dispatch_event, produced, event_subject, event
        )
    if isinstance(statement, ast.RemoveCounter):
        return _lower_remove_counter(statement, dispatch_event)
    if isinstance(statement, ast.GainLife):
        return _lower_gain_life(statement, produced, event)
    if isinstance(statement, ast.LoseLife):
        return _lower_lose_life(statement, event, produced)
    if isinstance(statement, ast.Destroy):
        # The **unfiltered** event, and this is the one of the three that is not
        # a dispatch question. `_lower_delayed_destroy` reads it to ask whether
        # the trigger bound one creature (CR 509.3c/509.3d) — a fact about the
        # trigger, true of every clause under it — and the instruction it
        # produces is dispatched by kind through `EFFECT_HANDLERS` like any
        # other, nested or not. Gated on `whole_effect` it refused Infinite
        # Authority, whose "destroy the other creature at end of combat" is the
        # first of a trigger's *two* sentences and so lowers under a `Sequence`.
        # The `delay` branch is here rather than inside `_lower_destroy`
        # because it is a dispatch question — "which family lowers this
        # sentence?" — and the two families answering it must not import each
        # other. It moved up at Urza's Saga's Phase 0, when the delayed forms
        # went to `lowering/delayed.py`; see that module's own note.
        if statement.delay:
            return _lower_delayed_destroy(
                statement, event, event_subject, produced
            )
        return _lower_destroy(statement, event, event_subject, produced)
    # "…becomes blocked by a creature, put **that creature** on top of its
    # owner's library." (Elven Warhounds.) In the chain rather than the
    # name-only table because the tuck's subject can be the block pair's other
    # half, and `binds_block_pair` needs both halves of the trigger to answer:
    # the kind says which fire site froze the pair and the *narrowing* says
    # whether it froze one creature or several (CR 509.3c/509.3d).
    #
    # The raw `event`, like the destroy above: this asks a question about the
    # trigger, which is true of the clause wherever in the sentence it sits.
    if isinstance(statement, ast.PutOnLibraryTop):
        return _lower_put_on_library_top(statement, event, event_subject)
    # In the chain rather than the name-only table, all three: each acts on what
    # an earlier step recorded, and `produced` refuses when nothing did.
    if isinstance(statement, ast.GainAbilityText):
        return _lower_gain_ability_text(
            statement, produced, event, event_subject
        )
    # "Untap any number of target creatures. Prevent all combat damage that
    # would be dealt to and dealt by **those creatures** this turn." (Energy
    # Arc.) The shield's recipients are the set the sentence in front of it
    # untapped, so this left `by_node.py` the day it stopped being a lowering
    # that needs nothing but its node.
    if isinstance(statement, ast.PreventDamage):
        return _lower_prevent_damage(statement, produced)
    # Beside the shield above, and here rather than in `by_node.py` for its
    # reason: the source it names is one a step in front of it chose (idiom 7).
    if isinstance(statement, ast.ChosenSourceNextDamage):
        return _lower_chosen_source_next_damage(statement, produced)
    if isinstance(statement, (ast.DoesntUntapNextStep, ast.DoesntUntapWhileCounter)):
        # The **unfiltered** event, for `_lower_destroy`'s reason one branch
        # up: whose creature "that creature" names is a fact about the trigger
        # (CR 509.3c/509.3d), true of every clause under it, and Labyrinth
        # Minotaur's restriction is the whole of its trigger's effect while
        # Joven's Ferrets' is the second sentence of one.
        return _lower_untap_restriction(
            statement, produced, event, event_subject
        )
    if isinstance(statement, (ast.Tap, ast.Untap)):
        # The **unfiltered** event, for the same reason `_lower_destroy` takes
        # one: whether a repeated "that <noun>" names the permanent the source
        # is attached to is a fact about the trigger, true of every clause under
        # it, and Mind Whip's tap sits inside a `may`'s otherwise branch.
        return _lower_tap(statement, event, produced)
    if isinstance(statement, ast.AddMana):
        return _lower_add_mana(statement, produced)
    if isinstance(statement, ast.CreateToken):
        # ``event`` for the P/T back-reference: "its power is equal to that
        # creature's power" is read through the one place that decides where a
        # back-reference comes from, and that place asks whether a trigger
        # records the number.
        return _lower_create_token(statement, produced, event)

    if isinstance(statement, ast.Conjunction):
        # **Any** run of damage clauses, not only a pair. Cone of Flame prints
        # three, and the damage lowering is the only reader that can tell one
        # announcement of three targets (CR 601.2c) from three announcements --
        # so a length test here decided that question before the module that
        # knows the answer was asked, and the run fell through to `_lower_steps`
        # as three independent instructions with three pickers, of which one
        # target would have reached the stack.
        if len(statement.effects) >= 2 and all(
            isinstance(effect, ast.DealDamage) for effect in statement.effects
        ):
            return _lower_damage_conjunction(
                statement, event, produced, event_subject
            )
        # `event_subject` travels with `event`, exactly as it does for the
        # `Sequence` branch below: they are the same fact about the same
        # trigger, and a conjunct that saw only the kind could not tell CR
        # 509.3c's bare becomes-blocked firing from CR 509.3d's narrowed one —
        # so "that creature" inside a conjunction refused where the same clause
        # in a sequence lowered. Dream Fighter's "this creature **and** that
        # creature phase out" is one conjunction and nothing else.
        return _lower_steps(
            statement.effects, produced, event, event_subject,
            lower_statement=lower_statement,
        )

    if isinstance(statement, ast.DestroyUnlessPay):
        return _lower_destroy_unless_pay(statement, dispatch_event)
    if isinstance(statement, ast.BecomeColor):
        return _lower_become_color(statement, dispatch_event, dispatch_subject)

    if isinstance(statement, ast.GainControl):
        # `produced` carries the earlier steps' records: Disharmony's
        # "gain control of that creature" reads what its untap chose.
        #
        # The event carries the *seat* half of the same question: "…**they**
        # gain control of this creature" (Emberwilde Djinn) names the player
        # the firing trigger froze, which only the event can say. The **raw**
        # event, for the reason the two readers above give: the sentence is
        # printed inside an offer's branch, so it is not the ability's whole
        # effect and `dispatch_event` is already None there.
        return _lower_gain_control(statement, produced, event)


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

    if isinstance(statement, ast.BinRevealedCard):
        # Here rather than in `by_node.py`, and not in its event-bearing table
        # either: "it" names the card an earlier step of *this* effect turned
        # up, so the lowering needs `produced` where that table passes `event`.
        return _lower_bin_revealed_card(statement, produced)

    if isinstance(statement, ast.PutMilledCardOntoBattlefield):
        # Here rather than in `by_node.py` because "one of **them**" names a
        # set an earlier step of this same effect recorded, so the lowering
        # needs `produced` and the node cannot answer on its own.
        return _lower_put_milled_card_onto_battlefield(statement, produced)

    if isinstance(statement, ast.ReturnToZone):
        # `produced` is what makes "…for each card discarded this way" legal:
        # the clause names a set an earlier step of this same effect made, so it
        # is admitted only where a step really recorded one.
        return _lower_return_to_zone(statement, event, produced)

    if isinstance(statement, ast.PutOntoBattlefield):
        # One node, two families, composed here because composing them is what
        # this dispatch is for. No printed "target" plus a graveyard named by a
        # referent is a *pick made during resolution* (CR 115.1b) and belongs to
        # the search-prompt family; everything else is the zone-change family's.
        # Asked first because the zone lowering demands a target and would
        # refuse this line on the more confident-sounding of the two errors, and
        # it returns None for every shape that is not its own — so it can only
        # add a reading here, never take one away.
        picked = _lower_graveyard_pick_onto_battlefield(statement)
        if picked is not None:
            return picked
        # "Reveal the top card of your library. If it's a creature card, put
        # **it** onto the battlefield." (Call of the Wild.) A third family, and
        # the one only `produced` can pick out: the pronoun names the card an
        # earlier step of this same effect turned up, where the zone lowering
        # below reads it as the ability's own source. Asked here for the pick's
        # reason — it answers nothing for any line with no reveal in front of
        # it, so it can only add a reading, never take one away.
        revealed = _lower_put_revealed_card_onto_battlefield(statement, produced)
        if revealed:
            return revealed
        # ``bound_card_from`` over ``event``: which event recorded the card
        # "that card" names is a fact about the whole printed line, and the
        # parser is what reads one (``rebinding.bind_recorded_card``).
        return _lower_put_onto_battlefield(
            statement, statement.bound_card_from or event
        )

    if isinstance(statement, ast.Sacrifice):
        # ``event``, not ``dispatch_event``: what "that artifact" names is a
        # fact about the *trigger* — its condition already named the enchanted
        # permanent — rather than about where in the sentence the clause sits,
        # and the kind it produces reaches its handler through the ordinary
        # dict dispatch however deeply it is nested. The same reading
        # ``_lower_destroy`` above takes, and for the same reason: Curse
        # Artifact's sacrifice lowers under a ``May``.
        # ``produced`` for the same reason ``_lower_destroy`` takes it: "one of
        # those creatures" names a set an earlier step of this effect chose.
        # The **unfiltered** event, for `_lower_destroy`'s reason: "that
        # creature's controller sacrifices **it** at end of combat" (Basalt
        # Golem) reaches the bound branch through the *delay's* event, which is
        # a fact about the sentence rather than about where in it the clause
        # sits.
        return _lower_sacrifice(statement, event, produced)
    if isinstance(statement, ast.DiscardRevealedUnlessPayLife):
        return _lower_discard_revealed_unless_pay_life(statement, produced)
    if isinstance(statement, ast.DiscardRevealedMatchingUnlessPayLife):
        # The plural, and in the chain beside the singular for its reason: the
        # record an earlier step wrote is the whole of the gate, so the lowering
        # needs `produced` and cannot sit in the name-only table.
        return _lower_discard_revealed_matching_unless_pay_life(
            statement, produced
        )

    if isinstance(statement, ast.CastPermission):
        # *event* as well as *produced*: "**The player** may play that card this
        # turn" (Elkin Lair) names the seat the firing trigger was about, and
        # only an event that freezes one can answer.
        return _lower_cast_permission(statement, produced, event)

    # "Search that player's library for **that many** cards" (Jester's Mask):
    # the count is a back-reference, so this lowering needs the record of what
    # the steps before it produced — which is why it is dispatched here rather
    # than from the node table below.
    if isinstance(statement, ast.SearchPlayerLibrary):
        return _lower_search_player_library(statement, produced)

    # The naming and choice arms live in `statement_dispatch_naming.py`;
    # None means none of them matched and the chain continues.
    named = lower_naming_statement(statement, produced, event)
    if named is not None:
        return named

    if isinstance(statement, ast.CombatRestriction):
        return _lower_combat_restriction(statement, dispatch_event, produced)

    if isinstance(statement, ast.BlockCountGrant):
        # The permission twin of the restriction above, and its own branch for
        # the node's own reason: the two say opposite things and share only the
        # rule they read (CR 509.1b).
        return lower_block_count_grant(statement)

    if isinstance(statement, ast.CantBe):
        # The **unfiltered** event, for the reason `_lower_destroy` above takes
        # one: "that creature can't be regenerated this turn" (Lim-Dûl's
        # Cohort) asks whether the trigger bound exactly one creature, which is
        # a fact about the trigger and so true of the clause wherever in the
        # sentence it sits — and the kind it produces reaches its handler
        # through the ordinary dict dispatch, nested or not.
        return _lower_cant_be(statement, event, event_subject)

    if isinstance(statement, ast.RemoveFromCombat):
        return _lower_remove_from_combat(statement, produced)


    # In the chain: the event decides whether "that creature gains first
    # strike" names a block pair's other half or nothing at all.
    #
    # …and  decides whether it names neither — the permanent an
    # earlier step of this same effect put onto the battlefield (Shallow Grave,
    # Zirilan of the Claw), which is a *record* rather than anything the
    # ability chose.
    if isinstance(statement, ast.GainKeyword):
        return _lower_gain_keyword(statement, event, event_subject, produced)
    if isinstance(statement, ast.CreateDelayedTrigger):
        return _lower_create_delayed_trigger(statement, lower_statement(
            # The delay's own noun phrase is the created ability's narrowing —
            # its ``agent`` where the phrase names the pair's *other* half.
            statement.effect, produced, event=statement.event, whole_effect=True,
            event_subject=statement.subject or statement.agent,
        ), produced, creating_event=event, creating_event_subject=event_subject)

    if isinstance(statement, ast.NextDrawReplacement):
        # The inner sentence is lowered under *this* line's event, not the
        # replaced draw: see `_lower_next_draw_replacement`.
        return _lower_next_draw_replacement(statement, lower_statement(
            statement.effect, produced, event=event,
            event_subject=event_subject, whole_effect=False,
        ))

    if isinstance(statement, ast.WhereX):
        # The wrapped sentence is lowered *here* so `where_x` can sit a layer
        # down: every one of its productions only checks that the sentence reads
        # an X and stamps the definition onto it, and none of them cares how it
        # was lowered.
        return lower_where_x(
            statement,
            lower_statement(
                statement.statement, produced,
                event=event, event_subject=event_subject, whole_effect=False,
            ),
            produced,
            event=event,
        )

    if isinstance(statement, ast.ForEach):
        # Five iterators, five lowerings, and the split is the *set* rather
        # than the effect. Three of them name a set an earlier step of this
        # same effect produced and are refused without that producer; one is a
        # count off the firing event and is refused without the event; one is
        # the seats. The tally form ("that died this **turn**") reads no inner
        # instructions at all — the counter lowering turns it into a
        # multiplier — which is why the body is lowered lazily here.
        def repeated(
            marker: frozenset[str] = frozenset(),
        ) -> tuple[OracleInstruction, ...]:
            return lower_statement(
                statement.effect, produced | marker,
                event=event, event_subject=event_subject, whole_effect=False,
            )

        # The four iterators that bind an **object**. Their bodies are lowered
        # with `LOOP_BOUND_OBJECT` in hand, which is what lets "its controller"
        # and "its mana value" read the iteration rather than the whole effect:
        # the *records* they read are written by any sweep at all, so the marker
        # is the only thing that can say a loop is there to bind them.
        object_loop = frozenset({LOOP_BOUND_OBJECT})
        if isinstance(statement.iterator, ast.DiedThisWay):
            return _lower_for_each_destroyed(statement, repeated(object_loop), produced)
        if isinstance(statement.iterator, ast.ExiledThisWay):
            return _lower_for_each_exiled(statement, repeated(object_loop), produced)
        # "For each creature **tapped this way**, …" (Raiding Party) — the third
        # "this way" window, over a record whose objects never left the
        # battlefield. Beside its two siblings and refused on the same terms.
        if isinstance(statement.iterator, ast.TappedThisWay):
            return _lower_for_each_tapped(statement, repeated(object_loop), produced)
        if isinstance(statement.iterator, ast.ChosenThisWay):
            return _lower_for_each_chosen(statement, repeated(object_loop), produced)
        # "For each **1 life you lost**" (Oath of Lim-Dûl).
        if isinstance(statement.iterator, ast.EachLifeLost):
            return _lower_for_each_life_lost(statement, repeated(), event)
        # "For each **additional {1}{R} you paid**" (Primitive Justice, Taste
        # of Paradise) — the seventh iterator, and the first whose number comes
        # off the *cast* (CR 601.2b) rather than off the board, the firing
        # event or an earlier step of this same resolution.
        if isinstance(statement.iterator, ast.EachAdditionalCostPaid):
            return _lower_for_each_cost_paid(statement, repeated())
        # "For each **+1/+1 counter you put on a creature this way**" (Bounty of
        # the Hunt) — the fourth "this way" window, refused without its producer
        # exactly as the three object-shaped ones are.
        if isinstance(statement.iterator, ast.CountersPlacedThisWay):
            return _lower_for_each_counters_placed(
                statement, repeated(), produced
            )
        # "For each **card less than two a player draws this way**" (Truce) —
        # the sixth iterator: a per-seat shortfall against a record an earlier
        # step of this same effect wrote, so it is refused without that
        # producer exactly as the three "this way" sets are.
        if isinstance(statement.iterator, ast.EachShortOfThisWay):
            return _lower_for_each_short_of_this_way(
                statement, repeated(), produced
            )
        # "**For each player,** …" (Lim-Dûl's Hex) — a loop over seats, whose
        # iteration binds "that player" the way an object loop binds "it". The
        # body is lowered knowing it: the marker is what lets a damage clause
        # inside the loop read the target slot the handler rebinds per seat,
        # where the same words under the bare trigger refuse for want of a
        # frozen seat.
        if isinstance(statement.iterator, ast.PlayerRef):
            return _lower_for_each_player(statement, lower_statement(
                statement.effect, produced | {LOOP_BOUND_PLAYER},
                event=event, event_subject=event_subject, whole_effect=False,
            ))
        # "**For each attacking red creature,** …" (Heroism, Tidal Flats) — the
        # set the board holds now. Read before the tally below, which is the
        # *other* thing an untyped iterator can be: that one's iterator is a
        # ``DiedThisTurn`` window, so neither can claim the other's node.
        if isinstance(statement.iterator, ast.ObjectFilter):
            # With `LOOP_BOUND_OBJECT` in hand, exactly as the four "this way"
            # loops above are lowered. The marker was missing here and the
            # omission had no reason behind it: ``handlers/control_flow.for_each``
            # binds ``iteration_target`` per object on *this* branch too — it is
            # the same ``run_one`` — so "its controller" and "its mana value"
            # inside a board loop name the object the iteration is on, and
            # without the marker they refused for want of a producer that
            # cannot exist in a loop. "For each creature, **its controller**
            # sacrifices a permanent of their choice unless **they** pay {1}"
            # (Fade Away) is the sentence that needs it, and the seat it names
            # is one ``_offered_seats`` and ``bound_permanent`` already resolve.
            return _lower_for_each_matching(statement, repeated(object_loop))
        return _lower_for_each(statement)

    # Both repeat clauses take the recursion back as an argument: their
    # lowerings live in the `repeats` family, which is below this dispatcher.
    # Two arms rather than one, because the two printed sentences are two
    # mechanisms — see `engine/grammar/repeats.py`.
    if isinstance(statement, ast.RepeatProcess):
        return _lower_repeat_process(statement, lower_statement)
    if isinstance(statement, ast.RepeatOptionalProcess):
        return _lower_repeat_optional_process(statement, lower_statement)
    if isinstance(statement, ast.RepeatForEachType):
        return _lower_repeat_for_types(statement, lower_statement)
    # The fourth, and the only one whose clause is a *condition* — so it takes
    # the condition lowering back as an argument too, for the same reason it
    # takes the statement one: both live below this dispatcher.
    if isinstance(statement, ast.PutLibraryTopIntoHand):
        # Takes ``produced``: Scroll Rack prints "put **that many** cards",
        # which is a back-reference to the exile a step earlier.
        return _lower_put_library_top_into_hand(statement, produced)
    if isinstance(statement, ast.PutExiledWithSource):
        # Left ``by_node`` when Duplicity's "put **all other** cards you own
        # exiled with this enchantment into your hand" gave it a
        # back-reference: "other" names the cards a step of this same effect
        # exiled, so the lowering reads ``produced`` and the row stopped being
        # one that needs nothing but its node.
        return _lower_put_exiled_with_source(statement, produced)
    if isinstance(statement, ast.RepeatProcessWhile):
        return _lower_repeat_process_while(
            statement, lower_statement, _lower_condition, produced, event,
        )

    if isinstance(statement, ast.ChoosePermanent):
        # Two lowerings, told apart by the printed quantifier. The plural needs
        # ``produced``: "**that player** chooses up to two Plains" inside a loop
        # names the seat an earlier step of this same effect recorded about the
        # object the loop is on, which is a reading only the producer set can
        # admit. That argument is why this pair sits here rather than in
        # ``by_node``, whose rows take the node and nothing else.
        # "**any number of** creatures they control" (Oracle en-Vec) is the
        # plural too, and its own word rather than an "up to" with a very large
        # count — see ``references.parse_target_spec``. Both go left, so the set
        # and the singular pick stay two answers rather than one that has to be
        # told which it is.
        if statement.spec.quantifier in ("up_to", "any_number"):
            return _lower_choose_permanents(statement, produced, event=event)
        # "**You** choose target creature …": the chooser the card names is
        # CR 601.2c's default, so the pick is the *announcement* rather than a
        # prompt at resolution. Tried first because the two produce different
        # instruction kinds and only this one can say which — the prompt below
        # has no reading of the printed word "target" at all.
        announced = _lower_announced_choice(statement)
        if announced is not None:
            return announced
        return _lower_choose_permanent(statement, produced)

    if isinstance(statement, ast.Exile):
        # `produced` is the gate on "exile **that token**": the phrase names
        # the token an earlier step of this same effect made, and with no such
        # step there is no id to read.
        #
        # The **unfiltered** event, for `_lower_destroy`'s reason: which object
        # a bare "it" names is a fact about the trigger (idiom 20), true of
        # every clause under it, and Whippoorwill's "exile **the creature**" is
        # the third sentence of one — so it lowers under a `Sequence` and would
        # see no event at all through `dispatch_event`.
        # "Exile **one of those creatures** and put two +1/+1 counters on the
        # other." (Cannibalize.) Read here, before the exile family sees the
        # node, because it is the *board* family's shape rather than the exile
        # family's: the pick among a set an earlier sentence chose, which is
        # where ``_lower_sacrifice_one_of_chosen`` already sits. Routing it
        # here is what keeps ``exile`` from importing ``board``, which the
        # family rule forbids and which is the whole reason a dispatcher
        # exists. None means the node is an ordinary exile.
        chosen = _lower_exile_one_of_chosen(statement, statement.subject, produced)
        if chosen is not None:
            return chosen
        return _lower_exile(statement, produced, event, event_subject)

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
            # "…target creature with the chosen ability loses it and
            # another target creature gains it." (Phyrexian Splicer.) The
            # keyword twin of the pump above, opening on a different node
            # pair, so neither can claim the other's sentence.
            _fused_two_target_keyword_move,
            _fused_conditional_counter,
            _fused_tap_any_number_then_pump,
            _fused_tap_enchanted_then_counters,
            # "Tap target creature. It deals damage equal to its power to
            # another target creature." (Deadshot.) Last of the loop's rows
            # because it is the narrowest: it opens on a Tap, which three of
            # the rows above also read, and every one of them refuses without
            # consuming.
            _fused_tap_then_bite,
        ):
            fused = fuse(statement.steps)
            if fused is not None:
                return fused
        # The one fuser that needs the recursion back, for
        # `_lower_repeat_process`'s reason: its clauses may carry a rider ("…,
        # and you gain 1 life") which is an arbitrary statement, and a lowering
        # family cannot reach this dispatcher. Beside the others rather than in
        # the loop above, because the loop's rows all take the steps and nothing
        # else.
        fused = _fused_cost_repeated_destroys(statement.steps, lower_statement)
        if fused is not None:
            return fused
        # "Exile that creature. Return that card to the battlefield … when this
        # artifact leaves the battlefield." (Portcullis.) Beside the loop rather
        # than in it, for `_fused_cost_repeated_destroys`' reason one line up:
        # the rows above take the steps and nothing else, and this pair is a
        # CR 610.3 link only under an event that froze the object the first
        # sentence exiles.
        fused = _fused_exile_event_subject_until_source_leaves(
            statement.steps, event
        )
        if fused is not None:
            return fused
        _refuse_unfused_distinctness(statement.steps)
        # The narrowing travels with the kind, as it does everywhere else it is
        # threaded: a trigger's noun phrase is as true of the second sentence of
        # its effect as of the first, and dropped here it left
        # `binds_block_pair` unable to tell a bound pair from a bare firing.
        return _lower_steps(
            statement.steps, produced, event, event_subject,
            lower_statement=lower_statement,
        )

    if isinstance(statement, ast.Conditional):
        then = lower_statement(statement.then, produced, event=event, event_subject=event_subject, whole_effect=False)
        if _guard_is_the_arms_own_precondition(statement.condition, then):
            return then
        otherwise = (
            lower_statement(statement.otherwise, produced, event=event, event_subject=event_subject, whole_effect=False)
            if statement.otherwise else ()
        )
        return (
            OracleInstruction(
                "if_then", "",
                {
                    # The branch is lowered first so the condition can be told
                    # what "it" names (`pronoun_target_referent`): a spell and a
                    # permanent are targeted by the same printed clause and
                    # answered from different halves of the resolution context,
                    # and this is the only place both the condition and the
                    # effect it guards are in view.
                    # The **firing event** travels down too. A trailing "if" is
                    # still a clause of the ability the event fired, so a
                    # condition asking about what the event named ("a card with
                    # the same name", Bazaar of Wonders) has to be able to see
                    # which event that was — and a condition that cannot see it
                    # refuses rather than answering about nothing.
                    "condition": _lower_condition(
                        statement.condition, produced, event,
                        referent=pronoun_target_referent(then),
                    ),
                    "then": then,
                    "else": otherwise,
                },
            ),
        )

    if isinstance(statement, ast.OneOf):
        return _lower_one_of(
            statement, produced, event, event_subject,
            lower_statement=lower_statement,
        )

    if isinstance(statement, ast.May):
        return _lower_may(
            statement, produced, event, event_subject,
            lower_statement=lower_statement,
        )

    if isinstance(statement, ast.UnlessPlayerPays):
        return _lower_unless_player_pays(
            statement, produced, event, event_subject,
            lower_statement=lower_statement,
        )

    if isinstance(statement, ast.RawEffect) and statement.text == "grant_team_assign_unblocked_until_eot":
        # Garruk, Savage Herald's −7 — the one quoted team grant with a
        # handler. Any other RawEffect keeps refusing below.
        return (OracleInstruction("grant_team_assign_unblocked_until_eot", "", {}),)

    raise LoweringError(f"no lowering for {type(statement).__name__}", node=statement)


def _guard_is_the_arms_own_precondition(condition, then) -> bool:
    """"**If it's a creature**, put a +0/+1 counter on it for each 1 damage
    prevented this way…" (Scars of the Veteran.)

    The guard restates what the arm can already only do. "Any target" is a
    creature, a player or a planeswalker (CR 115.4), and the arm is
    ``add_pt_counters_per_damage_prevented``, whose whole reading is the
    ``permanent_id`` the shield step recorded — armed on a player it records
    none and the arm places nothing. So the condition is CR-redundant here, in
    the way "under its owner's control" restates CR 400.3, and dropping it is
    not dropping a rider.

    **Not** consumed into nothing: it is checked against the arm, so a printing
    that guarded some *other* effect with the same words still reaches the
    ordinary conditional lowering — where it refuses, because nothing in the
    effect revealed a card for "it" to name. This is the one arm whose own
    record answers the question, and the pair is asserted rather than assumed.
    """
    from .lowering._common import _restrictions_beyond

    return (
        isinstance(condition, ast.RevealedCardIs)
        and not condition.negated
        and condition.filter.card_types == ("creature",)
        and not _restrictions_beyond(
            condition.filter, frozenset({"card_types"})
        )
        and len(then) == 1
        and then[0].kind == "add_pt_counters_per_damage_prevented"
    )

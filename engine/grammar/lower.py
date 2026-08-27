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

import dataclasses

from ..oracle_types import OracleInstruction
from . import ast
from .derived import derived_instruction_for_line
from .errors import LoweringError
from .lowering._events import CHOSEN_PLAYER
from .lowering.where_x import lower_where_x
from .statics import _lower_static_ability
from .lowering.control_flow import (
    _lower_may, _lower_one_of, _lower_steps,
)
from .lowering import (
    count_spec,
    _targets_payload,
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
    _amount_payload,
    _lower_produces_mana_instead,
    _lower_spend_mana_as_though,
    _lower_become_color,
    _lower_gain_type,
    _lower_cant_be,
    _lower_attack_as_though,
    _lower_assigns_no_combat_damage,
    _lower_attacking_doesnt_tap,
    _lower_remove_from_combat,
    _lower_change_text,
    _lower_combat_restriction,
    _lower_counter_ability,
    _lower_choose_target,
    _lower_counter_spell,
    _lower_create_delayed_trigger,
    _lower_create_emblem,
    _lower_create_copy_token,
    _lower_create_token,
    _lower_damage,
    _lower_damage_conjunction,
    _lower_damage_unless_pay,
    _fused_conditional_counter,
    _fused_tap_enchanted_then_counters,
    _fused_prepare_then_interact,
    _fused_tap_any_number_then_pump,
    _fused_two_target_pump,
    _lower_fight,
    _lower_destroy,
    _lower_discard,
    _lower_draw,
    _lower_exile,
    _lower_put_source_into_zone,
    _lower_extra_turn,
    _lower_for_each,
    _lower_repeat_process,
    _lower_for_each_destroyed,
    _lower_for_each_chosen,
    _lower_choose_cards_in_hand,
    _lower_put_iterated_card_on_library,
    _lower_pay_life,
    _lower_gain_control,
    _lower_gain_ability_text,
    _lower_gain_keyword,
    _lower_lose_keyword,
    _lower_ante,
    _lower_exchange_life_totals,
    _lower_set_life_total,
    _lower_gain_life,
    _lower_double_power,
    _lower_switch_pt,
    _lower_exile_cost_sacrifices,
    _lower_exile_graveyard,
    _lower_reveal_hand_and_choose,
    _lower_look_at_hand,
    _lower_look_at_library_top,
    _lower_lose_game,
    _lower_lose_life,
    _lower_mill,
    _lower_scry,
    _lower_modal_head,
    _lower_prevent_damage,
    _lower_redirect_damage,
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
    _lower_shuffle_hand_into_library,
    _lower_destroy_unless_pay,
    _lower_sacrifice_unless_pay,
    _lower_cast_from_exiled_with,
    _lower_cast_permission,
    _lower_exile_graveyard_until_leaves,
    _lower_transmute_by_sacrifice,
    _lower_exile_until_leaves_or_untaps,
    _lower_ownership_exchange_unless_paid,
    _lower_random_reveal_ownership_exchange,
    _lower_exile_top_of_library,
    _lower_put_exiled_with_source,
    _lower_look_top_pick,
    _lower_search_and_exile,
    _lower_graveyard_pick_onto_battlefield,
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
    _lower_choose_permanent,
    _lower_exchange_control,
    _lower_exchange_greatest_mana_value,
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
    if isinstance(statement, ast.GainAbilityText):
        return _lower_gain_ability_text(statement)
    if isinstance(statement, ast.GainKeyword):
        return _lower_gain_keyword(statement)
    if isinstance(statement, ast.LoseKeyword):
        return _lower_lose_keyword(statement, dispatch_event)
    if isinstance(statement, ast.PutCounter):
        return _lower_put_counter(statement, dispatch_event, produced)
    if isinstance(statement, ast.PlayerGetsCounters):
        return _lower_player_gets_counters(statement, event)
    if isinstance(statement, ast.DoublePower):
        return _lower_double_power(statement)
    if isinstance(statement, ast.SwitchPT):
        return _lower_switch_pt(statement)
    if isinstance(statement, ast.RemoveCounter):
        return _lower_remove_counter(statement, dispatch_event)
    if isinstance(statement, ast.Ante):
        return _lower_ante(statement)
    if isinstance(statement, ast.ExchangeLifeTotals):
        return _lower_exchange_life_totals(statement)
    if isinstance(statement, ast.SetLifeTotal):
        return _lower_set_life_total(statement)
    if isinstance(statement, ast.GainLife):
        return _lower_gain_life(statement, produced, event)
    if isinstance(statement, ast.LoseLife):
        return _lower_lose_life(statement, event, produced)
    if isinstance(statement, ast.PayLife):
        return _lower_pay_life(statement)
    if isinstance(statement, ast.Destroy):
        # The **unfiltered** event, and this is the one of the three that is not
        # a dispatch question. `_lower_delayed_destroy` reads it to ask whether
        # the trigger bound one creature (CR 509.3c/509.3d) — a fact about the
        # trigger, true of every clause under it — and the instruction it
        # produces is dispatched by kind through `EFFECT_HANDLERS` like any
        # other, nested or not. Gated on `whole_effect` it refused Infinite
        # Authority, whose "destroy the other creature at end of combat" is the
        # first of a trigger's *two* sentences and so lowers under a `Sequence`.
        return _lower_destroy(statement, event, event_subject)
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
    if isinstance(statement, ast.ChoosePermanent):
        return _lower_choose_permanent(statement)
    if isinstance(statement, ast.ExchangeControl):
        return _lower_exchange_control(statement)

    if isinstance(statement, ast.ExchangeGreatestManaValue):
        return _lower_exchange_greatest_mana_value(statement)
    if isinstance(statement, ast.Draw):
        return _lower_draw(statement)
    if isinstance(statement, ast.Mill):
        return _lower_mill(statement)
    if isinstance(statement, ast.Scry):
        return _lower_scry(statement)
    if isinstance(statement, ast.AddMana):
        return _lower_add_mana(statement, produced)
    if isinstance(statement, ast.AddManaForTappedLand):
        return _lower_add_mana_for_tapped_land(statement, dispatch_event)
    if isinstance(statement, ast.ProducesManaInstead):
        return _lower_produces_mana_instead(statement)
    if isinstance(statement, ast.SpendManaAsThough):
        return _lower_spend_mana_as_though(statement)
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
        return _lower_steps(
            statement.effects, produced, event, lower_statement=lower_statement
        )

    if isinstance(statement, ast.SacrificeUnlessPay):
        return _lower_sacrifice_unless_pay(statement)
    if isinstance(statement, ast.DestroyUnlessPay):
        return _lower_destroy_unless_pay(statement, dispatch_event)

    if isinstance(statement, ast.BecomeCreature):
        return _lower_become_creature(statement)

    if isinstance(statement, ast.BecomeColor):
        return _lower_become_color(statement, dispatch_event, dispatch_subject)

    if isinstance(statement, ast.ChangeText):
        return _lower_change_text(statement)

    if isinstance(statement, ast.GainControl):
        # `produced` carries the earlier steps' records: Disharmony's
        # "gain control of that creature" reads what its untap chose.
        return _lower_gain_control(statement, produced)

    if isinstance(statement, ast.PreventDamage):
        return _lower_prevent_damage(statement)

    if isinstance(statement, ast.RedirectDamage):
        return _lower_redirect_damage(statement)

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
        # `produced` is what makes "…for each card discarded this way" legal:
        # the clause names a set an earlier step of this same effect made, so it
        # is admitted only where a step really recorded one.
        return _lower_return_to_zone(statement, event, produced)

    if isinstance(statement, ast.PhaseOut):
        return _lower_phase_out(statement)

    if isinstance(statement, ast.PutOnLibraryTop):
        return _lower_put_on_library_top(statement)

    if isinstance(statement, ast.ChooseCardsInHand):
        return _lower_choose_cards_in_hand(statement)

    if isinstance(statement, ast.PutIteratedCardOnLibrary):
        return _lower_put_iterated_card_on_library(statement)

    if isinstance(statement, ast.PutOnLibraryBottom):
        return _lower_put_on_library_bottom(statement)

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
    if isinstance(statement, ast.ShuffleHandIntoLibrary):
        return _lower_shuffle_hand_into_library(statement)

    if isinstance(statement, ast.RevealHandAndChoose):
        return _lower_reveal_hand_and_choose(statement)
    if isinstance(statement, ast.ExileCostSacrifices):
        return _lower_exile_cost_sacrifices(statement)
    if isinstance(statement, ast.ExileGraveyard):
        return _lower_exile_graveyard(statement)
    if isinstance(statement, ast.LookAtHand):
        return _lower_look_at_hand(statement)
    if isinstance(statement, ast.LookAtLibraryTop):
        return _lower_look_at_library_top(statement)

    if isinstance(statement, ast.SearchLibrary):
        return _lower_search_library(statement)

    if isinstance(statement, ast.ExileTopOfLibrary):
        return _lower_exile_top_of_library(statement)
    if isinstance(statement, ast.PutExiledWithSource):
        return _lower_put_exiled_with_source(statement)

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

    if isinstance(statement, ast.RandomRevealOwnershipExchange):
        return _lower_random_reveal_ownership_exchange(statement)

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

    if isinstance(statement, ast.NameAndRandomReveal):
        # "Target opponent" is the only seat this paragraph names, and every
        # sentence after the first is about that same seat — "that player" is
        # the revealer. A description is emitted so the picker chooses the
        # opponent at activation (CR 601.2c), and the count rides as the
        # announced amount rather than a number, because X is not known until
        # the ability is activated.
        return (
            OracleInstruction(
                "name_and_random_reveal", "",
                {
                    "count": _amount_payload(statement.count),
                    "zone": statement.zone,
                    "targets": {
                        "quantifier": "target",
                        "kind": "player",
                        "opponents_only": True,
                    },
                },
            ),
        )

    if isinstance(statement, ast.NameThenRevealTop):
        # "Target player chooses…" is the only subject printed on this
        # paragraph, and it is the whole shape of the effect: the chooser, the
        # revealer and the card's destination are all the *same* seat. A
        # sentence naming anyone else would be a different card, so it refuses
        # rather than lowering onto a seat the handler would then have to guess
        # between.
        if statement.who.kind != "target_player":
            raise LoweringError(
                "the guess is made by the player the spell targets",
                node=statement,
            )
        return (
            OracleInstruction(
                "name_then_reveal_top", "",
                {
                    "match_zone": statement.match_zone,
                    "miss_zone": statement.miss_zone,
                    "targets": _targets_payload(statement.who),
                },
            ),
        )

    if isinstance(statement, ast.RevealUntil):
        return _lower_reveal_until(statement, produced)

    if isinstance(statement, ast.CopyThatSpell):
        return (OracleInstruction("copy_triggering_spell", "", {}),)

    if isinstance(statement, ast.CopySpell):
        # "Copy **this** spell" — the resolving object, which this engine has
        # already popped off the stack, so the handler reads
        # `Game.resolving_items[-1]` rather than scanning. Who gets the copy is
        # payload (CR 707.10a): the sentence's printed subject, which for Chain
        # Lightning is the player who paid and not the spell's controller.
        return (
            OracleInstruction(
                "copy_this_spell", "",
                {
                    "controller": statement.controller.kind,
                    "may_choose_new_target": bool(statement.may_choose_new_target),
                },
            ),
        )

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

    if isinstance(statement, ast.ChoosePlayerWhoCast):
        # "Choose a player who cast one or more sorcery spells this turn."
        # (Backdraft.) The choice and nothing else: what the chosen player is
        # *for* is the sentence after it, which reads the seat this one records
        # (`_PRODUCES`) — the same shape the coin flip below has, and for the
        # same reason.
        return (
            OracleInstruction(
                "choose_player_who_cast", "",
                {
                    "card_type": statement.card_type,
                    "minimum": statement.minimum,
                    "result_key": CHOSEN_PLAYER,
                },
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
        return _lower_combat_restriction(statement, dispatch_event)

    if isinstance(statement, ast.AttackAsThough):
        return _lower_attack_as_though(statement)
    if isinstance(statement, ast.CantBe):
        return _lower_cant_be(statement)

    if isinstance(statement, ast.AssignsNoCombatDamage):
        return _lower_assigns_no_combat_damage(statement)

    if isinstance(statement, ast.AttackingDoesntTap):
        return _lower_attacking_doesnt_tap(statement)

    if isinstance(statement, ast.RemoveFromCombat):
        return _lower_remove_from_combat(statement, produced)

    if isinstance(statement, ast.ChooseTarget):
        return _lower_choose_target(statement)

    if isinstance(statement, ast.CreateDelayedTrigger):
        return _lower_create_delayed_trigger(statement, lower_statement(
            statement.effect, produced, event=statement.event, whole_effect=True,
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
        )

    if isinstance(statement, ast.ForEach):
        # Two iterators, two lowerings, and the split is the *set* rather than
        # the effect: "that died this turn" is a tally the engine keeps and the
        # counter lowering reads as a multiplier, while "that died this way" is
        # the objects an earlier step of this same effect destroyed and has to
        # be walked one at a time. The inner statement is lowered here, as
        # `ast.WhereX`'s is — the lowering below only repeats it.
        if isinstance(statement.iterator, ast.DiedThisWay):
            return _lower_for_each_destroyed(
                statement,
                lower_statement(
                    statement.effect, produced,
                    event=event, event_subject=event_subject, whole_effect=False,
                ),
                produced,
            )
        # "For each of **those cards**" — the third iterator, and the same
        # split: a set an earlier step of this effect chose, walked one at a
        # time, and refused when nothing chose one.
        if isinstance(statement.iterator, ast.ChosenThisWay):
            return _lower_for_each_chosen(
                statement,
                lower_statement(
                    statement.effect, produced,
                    event=event, event_subject=event_subject, whole_effect=False,
                ),
                produced,
            )
        return _lower_for_each(statement)

    # The offer-round loop takes the recursion back as an argument: its lowering
    # lives in the `game` family, which is below this dispatcher.
    if isinstance(statement, ast.RepeatProcess):
        return _lower_repeat_process(statement, lower_statement)

    if isinstance(statement, ast.PutSourceIntoZone):
        return _lower_put_source_into_zone(statement)

    if isinstance(statement, ast.Exile):
        # `produced` is the gate on "exile **that token**": the phrase names
        # the token an earlier step of this same effect made, and with no such
        # step there is no id to read.
        return _lower_exile(statement, produced)

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
            _fused_tap_enchanted_then_counters,
        ):
            fused = fuse(statement.steps)
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
        otherwise = (
            lower_statement(statement.otherwise, produced, event=event, event_subject=event_subject, whole_effect=False)
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
        return _lower_one_of(
            statement, produced, event, event_subject,
            lower_statement=lower_statement,
        )

    if isinstance(statement, ast.May):
        return _lower_may(
            statement, produced, event, event_subject,
            lower_statement=lower_statement,
        )

    if isinstance(statement, ast.RawEffect) and statement.text == "grant_team_assign_unblocked_until_eot":
        # Garruk, Savage Herald's −7 — the one quoted team grant with a
        # handler. Any other RawEffect keeps refusing below.
        return (OracleInstruction("grant_team_assign_unblocked_until_eot", "", {}),)

    raise LoweringError(f"no lowering for {type(statement).__name__}", node=statement)














#: Which scratchpad key an activation **cost** writes when it is paid. The twin
#: of ``_PRODUCES`` for the cost side of a colon, and separate from it for the
#: same reason the two sides are separate: a cost is charged by
#: ``engine/mixins/stack/activation.py`` rather than by an instruction, so there
#: is no instruction kind to key it on. Land's Edge's "the discarded card" reads
#: the record this names; a cost added here needs the activation path to record
#: it under the same key, or the condition would compile and read nothing.
_COST_PRODUCES: dict[type, str] = {
    ast.DiscardCost: "discarded_cards",
}


def _lower_line_statement(
    statement: ast.Statement,
    *,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
    event_subject: object | None = None,
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
    return lower_statement(
        statement, produced, event=event, event_subject=event_subject
    )


def lower_ability(node: ast.AbilityNode) -> tuple[OracleInstruction, ...]:
    """Lower a whole ability line. Keyword and static lines carry no
    instructions of their own — they are recorded by the compiler as keyword or
    static lines instead."""
    if isinstance(node, ast.SpellEffectLine):
        # A spell whose **whole** effect is optional used to refuse here. The
        # reason was real and is now gone: the prompt rode
        # ``pending_optional_pays``, which only the triggered-ability resolution
        # path held open, so a spell — which leaves the stack the instant it
        # resolves — queued its effect and never performed it. Since
        # ``arm_pending_choice`` stamps the resolving stack object and
        # ``ChoiceSpec.holds_priority`` keeps that object on the stack until the
        # last of its prompts is answered (CR 608.2, CR 117.3b), a spell's
        # ``may`` outlives its own resolution exactly like a trigger's. Twiddle
        # and Rebirth are the two cards that reach the shape.
        return _lower_line_statement(node.statement)
    if isinstance(node, ast.TriggeredAbilityNode):
        fused = _fused_upkeep_pay_to_untap(node)
        if fused is not None:
            return fused
        instructions = _lower_line_statement(
            node.statement, event=node.event.kind,
            event_subject=node.event.subject,
        )
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
            condition = _lower_condition(
                node.intervening_if, event=node.event.kind
            )
            instructions = tuple(
                OracleInstruction(
                    instruction.kind, instruction.value,
                    {**instruction.payload, "intervening_if": condition},
                )
                for instruction in instructions
            )
        return instructions
    if isinstance(node, ast.ActivatedAbilityNode):
        # An activation cost is paid before the ability goes on the stack
        # (CR 602.2b), so what it ate is a record the *effect* can read back —
        # "If the discarded card was a land card" (Land's Edge). This is the one
        # place the cost clause and the effect clause are both in view, which is
        # why the seeding happens here rather than in a field on the condition:
        # the same pairing rule `_lower_steps` follows for "if you do".
        produced = frozenset(
            _COST_PRODUCES[type(cost)]
            for cost in node.costs
            if type(cost) in _COST_PRODUCES
        )
        return _lower_line_statement(node.statement, produced=produced)
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

"""Lowering combat **requirements** — CR 508.1d and CR 509.1c, "attacks/blocks
if able".

Split off ``lowering/combat.py`` when Tempest's second wave took that module
past the thousand-line guard on Trumpeting Armodon's and Magnetic Web's block
requirements — the second time the guard has fired on that module and the
second time the line was already drawn. ``prohibitions`` left it on the printed
voice; this leaves it on the CR's own pair of words. CR 506.3 names exactly
two things an effect can do to a declaration: a **restriction** says a creature
*can't*, and a **requirement** says it *must*. Everything left in ``combat``
lowers the first, plus the permissions that lift one; everything here lowers
the second.

The distinction is not stylistic, and CR 509.1c is where it shows: a
requirement is obeyed "to the maximum possible number **without disobeying any
restrictions**", so the two are asked in a fixed order at every enforcement
site and neither can be written as the negation of the other.

It completes ``permissions``/``prohibitions``' pair into the trio the rules
use — may, may not, must — and takes the third name from the same place they
took theirs. A **lowering-only** family, like ``zones``, ``library`` and
``mana``: the parse side keeps both productions in ``effects/combat.py``, where
each is one branch of a verb table, and it is the lowerings that outgrew the
cap.

A family rather than a floor: ``combat`` does not read it —
``grammar/by_node.py`` reaches both lowerings directly, one layer up — so
nothing here is below anything and no lowering family imports it.
"""

import dataclasses

from ...oracle_types import CHOSEN_THIS_WAY_OBJECTS, OracleInstruction
from ...turn_state import THAT_PLAYERS_NEXT_TURN
from .. import ast
from ..errors import LoweringError
from ._common import (
    _describe_targets, _is_source, _names_several_targets, _restrictions_beyond,
    testable_filter_payload,
)
from ._record_keys import (CHOSEN_PERMANENT, CHOSEN_PLAYER, DAMAGE_RECIPIENT,
                           _UNTAPPED_PERMANENTS)


#: The noun phrase a sentence may use to name the set an earlier step of the
#: same effect chose: "**the chosen creatures**", and nothing narrower. The set
#: is the record, so any extra word in the phrase would describe a subset the
#: payload has no way to carry and the mark would go on the whole set anyway —
#: which is a card compelling more creatures than it names.
_CHOSEN_CREATURES = ast.ObjectFilter(card_types=("creature",))


def _chosen_set_payload(
    subject, produced: frozenset[str], node
) -> dict[str, object]:
    """The payload keys that aim an effect at "the chosen creatures" during
    "that player's next turn".

    Two records and both are required. ``CHOSEN_THIS_WAY_OBJECTS`` is the set,
    and ``CHOSEN_PLAYER`` is the seat whose next turn the window names — the
    player the choosing step asked. Gated on ``produced`` rather than trusted,
    for the reason every other back-reference in this package is: with no such
    step the words name nobody, and an effect armed for a guessed seat holds on
    the wrong turn.
    """
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "chosen"
        and subject.filter == _CHOSEN_CREATURES
    ):
        raise LoweringError(
            "this window is only carried over the set an earlier step chose",
            node=node,
        )
    if CHOSEN_THIS_WAY_OBJECTS not in produced:
        raise LoweringError(
            "no step of this effect chose the creatures this sentence names",
            node=node,
        )
    if CHOSEN_PLAYER not in produced:
        raise LoweringError(
            "no step of this effect named the player whose turn this is",
            node=node,
        )
    return {"subject_from": CHOSEN_THIS_WAY_OBJECTS, "window": THAT_PLAYERS_NEXT_TURN}


def _lower_destroy_chosen_that_didnt_attack(
    node: "ast.DestroyChosenThatDidntAttack",
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"At the beginning of **that turn's** end step, destroy each of the chosen
    creatures that didn't attack this turn." (Oracle en-Vec.)

    The same instruction Maddening Imp's tail lowers to one function up, and the
    same mark behind it — ``engine/phases/end_step.py`` sweeps both — with the
    window and the set as payload instead of as the sentence's position. Marked
    now and swept later for that lowering's stated reason: "the chosen
    creatures" is the set as it stood when the ability resolved, and re-reading
    the phrase at an end step a turn later would name whatever the board looked
    like by then.
    """
    subject = node.subject
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.filter.attacked_this_turn is False
    ):
        # "…that **didn't attack** this turn" is the whole condition of the
        # sentence and the mark is what tests it, at the end step, against the
        # record the declaration wrote. A phrase without it would destroy the
        # set unconditionally; one with it inverted is a different card.
        raise LoweringError(
            "this end-step destruction is about the creatures that stayed home",
            node=node,
        )
    stripped = dataclasses.replace(
        subject, filter=dataclasses.replace(subject.filter, attacked_this_turn=None)
    )
    return (
        OracleInstruction(
            "destroy_subject_at_end_step_if_it_didnt_attack", "",
            _chosen_set_payload(stripped, produced, node),
        ),
    )


#: Trigger events whose fire site records the **attacking** creature, so
#: "…block *that creature* this turn if able" (Magnetic Web) names it. A subset
#: of `_EVENT_SUBJECT_OBJECTS` rather than that set itself: the pronoun here
#: has to name an attacker, and most of those events are about a permanent that
#: entered, was tapped or was dealt damage — none of which is in combat at all,
#: so a requirement aimed at one would compel a block nobody could make.
_BOUND_ATTACKER_EVENTS = frozenset({"matching_creature_attacks"})


def _lower_force_chosen_creature_to_attack(
    node: ast.ForceChosenCreatureToAttack,
) -> tuple[OracleInstruction, ...]:
    """Nettling Imp / Norritt's three sentences, as the one instruction the
    engine already had a handler, a target spec and a legality rule for.

    Fused rather than composed into a ``sequence``, and this is the shape the
    composition rule asks for rather than an exception to it: the second and
    third sentences have no subject of their own to compose over — both name
    the creature the first one chose — and the third is conditional on what
    that creature did about the second. Three instructions would need a
    scratchpad key to pass the chosen creature between them and a fourth to
    remember the requirement, which is a fused instruction with extra steps.

    Arcum's Whistle puts a price on it — "That player may pay {X}, where X is
    that creature's mana value. **If they don't pay**, …" — and that half *is*
    composed, through the ordinary offer: the requirement is the offer's
    declined branch and nothing else about it changes. ``that_player`` is the
    seat the ability's own target names (the creature's controller, which this
    template's noun phrase already fixes as the active player), and the price is
    the one computed amount every other offer carries.
    """
    requirement = OracleInstruction("mark_non_wall_target_to_attack", "", {})
    if not node.unless_controller_pays_mana_value:
        return (requirement,)
    return (
        OracleInstruction("may", "", {
            "actor": "that_player",
            "cost": {"generic": "x"},
            "x_from_count": {
                "object_characteristic": {
                    "object": "target", "characteristic": "mana_value",
                    "offset": 0,
                },
            },
            # The **declined** branch, which is where the target lives:
            # `targeting._from_instructions` reads an offer's `otherwise` last
            # and for exactly this reason — CR 601.2c picks the creature as the
            # ability is activated, before anyone is offered the payment.
            "otherwise": (requirement,),
        }),
    )


def _lower_attacks_this_turn_if_able(
    node: ast.AttacksThisTurnIfAble,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """CR 508.1d's requirement for one turn, on the source or on a chosen
    creature.

    "…this creature deals 3 damage to you **and attacks this turn if able**"
    (Kookus) names its own source and needs no picker. "**Target creature**
    attacks this turn if able." (Boiling Blood) names one the caster chose, and
    the note that used to stand here — "a targeted spelling would need a
    picker" — was the work item rather than the reason: the picker falls out of
    the ``targets`` description, because ``targeting._from_targets_payload``
    reads a description into a spec for any kind that carries one.

    Two kinds rather than one with an optional target, because the two answer
    "which permanent?" in different places: the source is on the context and a
    chosen creature is a target CR 601.2c fixed at announcement, and a single
    kind would have to guess which it was handed.

    Not the printed static ``engine/combat_restrictions.py`` reads for "attacks
    **each combat** if able": that one holds for as long as the permanent is on
    the battlefield and this ends with the turn (CR 611.2a). The production in
    front of this one refuses the "each combat" spelling in the *parse*, which
    is what leaves the table its line.
    """
    if node.window is None:
        # The sentence printed no window here and no leading duration supplied
        # one (``sentence_clauses._distribute_duration``). Refused rather than
        # defaulted: a requirement with no end is a creature that must attack
        # every combat for the rest of the game, which is the widening
        # direction and the one a card may not get wrong by accident.
        raise LoweringError(
            "this attack requirement names no window", node=node
        )
    if node.window == THAT_PLAYERS_NEXT_TURN:
        # "**During that player's next turn**, the chosen creatures attack if
        # able." (Oracle en-Vec.) The same CR 508.1d requirement over a turn
        # that has not started, on the set an earlier step chose — so the same
        # instruction with the window and the record as payload, which is where
        # every other printed parameter in this grammar goes.
        payload = _chosen_set_payload(node.subject, produced, node)
        if node.destroy_if_absent:
            payload["destroy_if_absent"] = True
        return (
            OracleInstruction("force_subject_to_attack_until_eot", "", payload),
        )
    if node.destroy_if_absent and not (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("all", "each")
    ):
        # The tail names "**those creatures**" — a set — so it is read only
        # behind the quantified branch below. Refused rather than dropped for
        # this file's standing reason: a rider parsed and ignored is a card that
        # compels an attack and then forgives the creature that stayed home,
        # which is the card working *more* often in its controller's favour and
        # nothing failing.
        raise LoweringError(
            "the end-step destruction is about the set this sentence "
            "described, and this sentence describes one creature",
            node=node,
        )
    if _is_source(node.subject):
        return (OracleInstruction("force_self_to_attack_until_eot", "", {}),)
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("all", "each")
    ):
        # "**Non-Wall creatures the active player controls** attack this turn
        # if able." (Maddening Imp.) The unnarrowed twin of the targeted branch
        # below and the exact mirror of the block family's, down to the reason
        # it carries no picker: every creature the printed noun phrase
        # describes, reached through the same ``subject_matches`` every other
        # noun phrase goes through, so there is nothing to choose.
        #
        # This is the sentence Siren's Call prints, which until now was a
        # name-keyed hook with ``active_player_index`` written into the handler
        # behind it. The seat is a filter word now
        # (``subject_filters``: ``controller: "active_player"``), which is what
        # turns one card's hook into a template.
        described = testable_filter_payload(
            node.subject.filter,
            refusal=(
                "the attack requirement is enforced against every creature the "
                "phrase describes, so a narrowing the matcher cannot test "
                "would compel a strictly larger set than the card names"
            ),
            node=node,
            require_narrowing=False,
        )
        if described.get("type_filter") != "creature":
            # CR 508.1a is about creatures, exactly as the targeted branch
            # below requires: a noun phrase this lowering cannot confirm names
            # one would mark permanents that can never meet the requirement.
            raise LoweringError(
                "an attack requirement names a creature", node=node
            )
        requirement = OracleInstruction(
            "force_subject_to_attack_until_eot", "", {"subject": described}
        )
        if not node.destroy_if_absent:
            return (requirement,)
        # "…At the beginning of the next end step, destroy each of **those
        # creatures** that didn't attack this turn." Composed rather than fused
        # into a flag on the requirement, because the two halves *do* have a
        # subject to compose over — the same one, and that is the whole content
        # of the word "those". Nettling Imp's three sentences are fused for the
        # opposite reason: there the set is one creature a *target* chose, so
        # the second sentence has nothing but a pronoun to name it.
        #
        # The same description in both, evaluated in the same resolution, is
        # what makes "those creatures" mean the set the requirement marked: both
        # marks are placed now, and the end step reads only the marks
        # (`engine/phases/end_step.py`). A second reading of the noun phrase a
        # turn later would name whatever the board looked like by then.
        return (
            requirement,
            OracleInstruction(
                "destroy_subject_at_end_step_if_it_didnt_attack", "",
                {"subject": described},
            ),
        )
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and DAMAGE_RECIPIENT in produced
    ):
        # "This artifact deals 1 damage to target creature. **That creature**
        # attacks this turn if able." (Bullwhip.) The pronoun names the object
        # an earlier step of this same resolution hit, not a second target —
        # CR 601.2c fixed one creature when the ability was activated, and a
        # target description here would make the picker ask for it twice.
        #
        # Gated on the damage step's own record rather than assumed: with
        # nothing in front of it the words name nothing, and a requirement that
        # resolved against whichever object the context happened to hold would
        # compel a creature the card never mentions. The same shape the
        # keyword-grant family uses for "that creature gains haste".
        #
        # A bound object carries no narrowing to honour — the noun restates
        # what the step in front already found — so anything beyond the printed
        # type refuses rather than being dropped.
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound attack requirement reads the permanent an earlier "
                "step damaged and nothing narrower",
                node=node,
            )
        if node.subject.filter.card_types not in ((), ("creature",)):
            raise LoweringError(
                "an attack requirement names a creature", node=node
            )
        return (
            OracleInstruction("force_bound_to_attack_until_eot", "", {}),
        )
    if isinstance(node.subject, ast.TargetSpec) and node.subject.targeted:
        if _names_several_targets(node.subject):
            raise LoweringError(
                "the attack requirement marks one creature; nothing here "
                "collects several",
                node=node,
            )
        described = testable_filter_payload(
            node.subject.filter,
            refusal=(
                "the attack requirement is enforced against the chosen "
                "creature, so a narrowing the matcher cannot test would be "
                "dropped and the picker would offer creatures the card "
                "never names"
            ),
            node=node,
            require_narrowing=False,
        )
        payload: dict[str, object] = {}
        _describe_targets(payload, node.subject)
        if described.get("type_filter") != "creature":
            # CR 508.1a is about creatures; a noun phrase this lowering cannot
            # confirm names one would put the mark on a permanent that can
            # never meet the requirement.
            raise LoweringError(
                "an attack requirement names a creature", node=node
            )
        return (
            OracleInstruction("force_target_to_attack_until_eot", "", payload),
        )
    raise LoweringError(
        "no handler makes that subject attack this turn", node=node
    )


def _lower_blocks_this_turn_if_able(
    node: ast.BlocksThisTurnIfAble,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """CR 509.1c's requirement for one turn, on named creatures and aimed at one
    named attacker (Trumpeting Armodon, Magnetic Web).

    Two halves, and both are checked here rather than trusted.

    The **attacker** is what must be blocked, and there are two referents. The
    ability's own source is Trumpeting Armodon's; "that creature" is the
    object the trigger's event was about (Magnetic Web's attacker), which only
    resolves under an event whose fire site records one — on any other trigger
    the handler would find nothing and the card would compile clean while
    compelling nobody. A block is a pair (CR 509.1a) and a requirement whose
    second half was dropped would compel the creature to block anything at all.

    The **subject** is who must block: a *target*, so the picker falls out of
    the ``targets`` description exactly as it does for the attack twin, or a
    quantified noun phrase, which reaches every creature it describes and so
    carries no picker at all.
    """
    if node.attacker is None:
        # "**That creature** blocks this turn if able." (Provoke.) No attacker
        # named, which is the *weakest* CR 509.1c requirement rather than a
        # dropped half: the creature must block something it legally can, which
        # is what Watchdog's printed static already says and what the
        # declare-blockers step already checks. Its own kind for that reason —
        # the narrowed one records which attacker is owed, and a list with
        # nothing in it would compel nobody.
        #
        # The subject is the object the sentence in front of this one untapped,
        # gated on that step's own record: with nothing in front the pronoun
        # names nobody, and a requirement resolved against whatever the
        # resolution happened to hold would compel a creature the card never
        # mentions.
        if not (
            isinstance(node.subject, ast.TargetSpec)
            and node.subject.quantifier == "that"
            and _UNTAPPED_PERMANENTS in produced
        ):
            raise LoweringError(
                "an unaimed block requirement names the permanent an earlier "
                "step of this effect untapped",
                node=node,
            )
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound block requirement reads the permanent an earlier "
                "step untapped and nothing narrower",
                node=node,
            )
        if node.subject.filter.card_types not in ((), ("creature",)):
            raise LoweringError(
                "a block requirement names a creature", node=node
            )
        return (
            OracleInstruction("force_bound_to_block_until_eot", "", {}),
        )
    if isinstance(node.attacker, ast.TargetSpec) and _is_source(node.attacker):
        attacker = "source"
    elif (
        isinstance(node.attacker, ast.TargetSpec)
        and node.attacker.quantifier == "that"
        and not _restrictions_beyond(
            node.attacker.filter, frozenset({"card_types"})
        )
    ):
        if event not in _BOUND_ATTACKER_EVENTS:
            raise LoweringError(
                "\"that creature\" is the attacker this trigger's event was "
                "about, and this event records none",
                node=node,
            )
        attacker = "bound"
    else:
        raise LoweringError(
            "the block requirement names one attacker, and neither the "
            "ability's source nor a bound attacker is what this names",
            node=node,
        )
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("all", "each")
    ):
        # "**All creatures with magnet counters on them** block that creature
        # this turn if able." (Magnetic Web.) Every creature the noun phrase
        # describes, so there is nothing to target and nothing for a picker to
        # ask — the filter travels as `subject` and the handler sweeps the
        # board with it, through the same `subject_matches` every other
        # printed noun phrase goes through.
        described = testable_filter_payload(
            node.subject.filter,
            refusal=(
                "the block requirement is enforced against every creature the "
                "phrase describes, so a narrowing the matcher cannot test "
                "would compel a strictly larger set than the card names"
            ),
            node=node,
            require_narrowing=False,
        )
        if described.get("type_filter") != "creature":
            raise LoweringError(
                "a block requirement names a creature", node=node
            )
        return (
            OracleInstruction(
                "force_subject_to_block_until_eot", "",
                {"attacker": attacker, "subject": described},
            ),
        )
    # "Defending player chooses an untapped creature they control. **That
    # creature blocks this creature this turn if able.**" (Crashing Boars.) The
    # creature the step in front of this one *chose* — not one this sentence
    # targets, and not one the trigger's event named: CR 601.2c does not reach a
    # choice made on resolution, so there is no announcement and no picker, and
    # the pronoun's only referent is the record that choice wrote.
    #
    # Gated on that record's presence, like every other back-reference in this
    # package: with no chooser in front of it the words name nobody, and a
    # requirement resolved against whatever the resolution happened to hold
    # would compel a creature the card never mentions.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and not node.subject.targeted
        and CHOSEN_PERMANENT in produced
    ):
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound block requirement reads the permanent an earlier "
                "step of this effect chose and nothing narrower",
                node=node,
            )
        if node.subject.filter.card_types not in ((), ("creature",)):
            raise LoweringError(
                "a block requirement names a creature", node=node
            )
        if attacker != "source":
            raise LoweringError(
                "a chosen creature is compelled to block the ability's own "
                "source",
                node=node,
            )
        return (
            OracleInstruction(
                "force_target_to_block_until_eot", "",
                {"attacker": attacker, "permanents_from": CHOSEN_PERMANENT},
            ),
        )
    if not (
        isinstance(node.subject, ast.TargetSpec) and node.subject.targeted
    ):
        raise LoweringError(
            "no handler makes that subject block this turn", node=node
        )
    if attacker != "source":
        raise LoweringError(
            "a targeted block requirement resolves only against the ability's "
            "own source",
            node=node,
        )
    if _names_several_targets(node.subject):
        raise LoweringError(
            "the block requirement marks one creature; nothing here collects "
            "several",
            node=node,
        )
    described = testable_filter_payload(
        node.subject.filter,
        refusal=(
            "the block requirement is enforced against the chosen creature, so "
            "a narrowing the matcher cannot test would be dropped and the "
            "picker would offer creatures the card never names"
        ),
        node=node,
        require_narrowing=False,
    )
    if described.get("type_filter") != "creature":
        # CR 509.1a is about creatures; a noun phrase this lowering cannot
        # confirm names one would put the mark on a permanent that can never
        # meet the requirement.
        raise LoweringError("a block requirement names a creature", node=node)
    payload: dict[str, object] = {"attacker": attacker}
    _describe_targets(payload, node.subject)
    return (
        OracleInstruction("force_target_to_block_until_eot", "", payload),
    )

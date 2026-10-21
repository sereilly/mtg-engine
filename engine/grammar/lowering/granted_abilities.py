"""Lowering for an ability granted as **quoted text** (CR 113.3, CR 611.2c).

"…that creature gains "Remove a matrix counter from this creature: Regenerate
this creature."" (Life Matrix.) What such a sentence grants is not a keyword
and not a described effect — it is a whole printed ability, recorded on
``engine/keywords.py``'s granted-ability-lines channel and compiled off the
permanent's rules text like any printed line. The one question that is not the
compiler's — can the engine read the quoted text at all — is asked of
``engine/granted_abilities.py``, whose name this module takes so the mirror
re-forms on the engine side rather than forking a third word for one subject
(the reuse ``linked_exile`` and ``colors`` make).

Split out of ``keywords`` at Torment's Phase 0, 51 lines under the guard, along
that module's own title: "keyword abilities (CR 702)". A quoted ability is
CR 113.3, and nothing here asks the keyword registry's gate. The two lowerings
called nothing of each other's; what they shared was the table of printed
durations a grant has a sweep for — one table for both channels, because the
printed phrase is the same phrase — and it went down to ``_common`` rather than
staying in either, because two families reading one fact is what a floor is
for.

The keyword grant kept the name because it is the half that grows: since
``keyword_removal`` left it at Tempest's wave-3 integration it gained 189 lines
over six commits (Wishmonger's chooser, the colour asked while the effect is
applied, Samite Elder's chosen permanent, Skyshroud Blessing's typed sweep),
where this lowering gained 36 in one (the Licids' granted set).

Taking a quoted ability *away* (Glittering Lion) stays in ``keyword_removal``
beside the keyword removal: that module is 389 lines, and the guard fired here,
on the grant.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._events import _RECORDED_PERMANENTS, binds_block_pair
from ._common import (_GRANT_DURATIONS, _describe_targets, _is_source,
                      _is_target, _restrictions_beyond,
                      testable_filter_payload)


def _lower_gain_ability_text(
    node: ast.GainAbilityText,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """"…gains "<ability>"." (Life Matrix.) CR 113.3 / CR 611.2c.

    The grant is the *text*: `engine/keywords.py`'s granted-ability-lines
    channel records it, ``Permanent.effective_card`` folds it into the rules
    text, and the compiler makes the ability from there — so the activation
    enumerator, the trigger scans and the web payload all find it without
    knowing that a spell granted it.

    Two gates, both of them the difference between a card that works and a card
    that reports supported and sits inert:

    * the quoted text has to compile (``granted_ability_supported``), because a
      grant of a sentence the engine cannot read grants nothing;
    * the duration has to be one the engine can end. Every grant channel here
      expires at the cleanup step or not at all, so a printed "until end of
      combat" (Johan) would silently run to end of turn.
    """
    from ...granted_abilities import granted_ability_supported

    if not node.abilities:
        raise LoweringError("a quoted grant needs an ability", node=node)
    if node.self_name is not None and not _is_source(node.subject):
        # "Johan can't attack" is an ability on Johan and a proper noun on
        # anything else. The grant is recorded as text and recompiled on
        # whatever permanent holds it, so handing this sentence to another
        # creature would record a line that stops compiling on arrival — a
        # grant of nothing, which is exactly what the probe below exists to
        # refuse. Caught here because the probe cannot see who receives it.
        raise LoweringError(
            f"the granted ability {node.abilities[0]!r} names its own source, "
            "so it can only be granted to that source",
            node=node,
        )
    for text in node.abilities:
        if not granted_ability_supported(text, node.self_name):
            raise LoweringError(
                f"the granted ability {text!r} is not one the engine compiles",
                node=node,
            )
    if node.duration.kind is not None and node.duration.kind not in _GRANT_DURATIONS:
        raise LoweringError(
            f"no granted-ability channel expires {node.duration.kind!r}", node=node
        )
    payload: dict[str, object] = {
        "abilities": tuple(node.abilities),
        # A grant with no printed duration lasts as long as the object
        # (CR 611.2a) — the same reading the durationless keyword
        # grant in ``keywords`` takes, and the reason the channel takes the
        # sweep's name rather than assuming one answer.
        "duration": _GRANT_DURATIONS.get(node.duration.kind),
    }
    # "If it doesn't have "<ability>," it gains that ability." (Musician.) The
    # printed condition is about the very sentence being granted, so it rides
    # on the grant rather than wrapping it: CR 611.2c allows a permanent to
    # hold one ability twice, and a second copy of Musician's would ask for the
    # upkeep payment a second time.
    if node.only_if_absent:
        payload["only_if_absent"] = True
    if _is_source(node.subject):
        return (OracleInstruction("grant_self_ability_text", "", payload),)
    # "Each of **those creatures** gains "{4}: Remove a paralyzation counter
    # from this creature."" (Dread Wight.) The bound plural: the recipients are
    # whatever an earlier step of this same effect recorded (CR 611.2c fixed
    # the set when the effect began), so nothing is chosen and no ``targets``
    # description is emitted. The same kind as the single-permanent grant,
    # because the grant is identical and only its subject differs — and
    # ``_grant_ability_texts`` is already the one place a quoted ability is
    # recorded, so a set is a loop rather than a second channel.
    #
    # The gates are the ones every bound-plural reader here applies: no
    # narrowing beyond the card type (a restated adjective would be dropped and
    # the grant would reach permanents the phrase excludes), and a producer must
    # have run — with nothing recorded the handler grants nothing while the card
    # compiles clean.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "those"
        and not node.subject.targeted
    ):
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "a bound plural carries no narrowing the grant could honour",
                node=node,
            )
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if not recorded:
            raise LoweringError(
                "\"those creatures\" names objects nothing in this effect "
                "recorded", node=node,
            )
        if len(recorded) != 1:
            raise LoweringError(
                "\"those creatures\" is ambiguous: several earlier steps "
                "recorded objects", node=node,
            )
        payload["permanents_from"] = recorded[0]
        return (OracleInstruction("grant_target_ability_text", "", payload),)
    # "Put a matrix counter on target creature and **that creature** gains …"
    # (Life Matrix.) The bound object the clause in front of it already
    # targeted, not a second choice — so no ``targets`` description is emitted
    # and the handler acts on the ability's one target, exactly as the
    # where-clause pump reads the same pronoun. A bound object carries no
    # narrowing to honour, so a restated adjective refuses rather than being
    # dropped.
    bound = (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "that"
        and not _restrictions_beyond(node.subject.filter, frozenset({"card_types"}))
    )
    if bound and binds_block_pair(event, event_subject):
        # "Whenever this creature blocks a creature, … **the creature** gains
        # "<ability>" and "<ability>"." (Mindbender Spores.) The other half of
        # the block, which the trigger froze — never a choice, so the recipient
        # is neither a target nor a record this effect wrote.
        #
        # Read **before** the target-shaped reading below, and that order is the
        # card: on the *blocks* half of the event the stack item's target is the
        # blocking creature itself (the fire site puts it there so a
        # self-affecting trigger can find itself), so the fall-through would
        # have granted both abilities to the Spores and left the creature it
        # blocked untouched — a card that reports supported and plays as its own
        # opposite.
        payload["on_block_pair"] = True
        types = tuple(node.subject.filter.card_types)
        if types:
            payload["subject_types"] = types
        return (OracleInstruction("grant_target_ability_text", "", payload),)
    if bound:
        # "Return target … creature card from your graveyard to the
        # battlefield. **That creature** gains "Cumulative upkeep {2}.""
        # (Dreams of the Dead.) The bound object is a permanent an earlier step
        # of this effect *created*, not the ability's target — the target is a
        # card in a graveyard, and granting to it would grant to nothing. So
        # when a step recorded permanents, the grant reads that record; when
        # none did, the words keep their existing reading as the ability's own
        # chosen target (Life Matrix, Glyph of Delusion) and the payload below
        # is byte-identical to what it has always been.
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if len(recorded) > 1:
            raise LoweringError(
                "\"that creature\" is ambiguous: several earlier steps "
                "recorded objects", node=node,
            )
        if recorded:
            payload["permanents_from"] = recorded[0]
            return (
                OracleInstruction("grant_target_ability_text", "", payload),
            )
        # The printed noun, carried even though the *choice* was made by the
        # clause in front of this one: "**that enchantment** gains …"
        # (Balduvian Shaman) is not a creature, and the grant's resolution
        # otherwise asks whether it is — the default every other card printing
        # this shape has wanted. Dropped, the enchantment is no valid target and
        # the grant silently does nothing.
        types = tuple(node.subject.filter.card_types)
        if types:
            payload["subject_types"] = types
        return (OracleInstruction("grant_target_ability_text", "", payload),)
    # "Until end of turn, **creatures you control** gain "{1}: Regenerate this
    # creature."" (Resuscitate.) A *described* set rather than a chosen one:
    # nothing is targeted, so no ``targets`` description is emitted and the
    # board is read as the effect resolves (CR 611.2c fixes the set then).
    #
    # The same shape ``grant_team_keyword_until_eot`` already has one grant over
    # — a keyword and a quoted ability are the same layer-6 addition and differ
    # only in what is recorded — so this is the *same* kind with a filter on the
    # payload rather than a second channel: ``_grant_ability_texts`` is already
    # the one place a quoted ability is written, and a set is a loop around it,
    # exactly as the bound plural above is.
    #
    # Every key of the printed phrase must be testable, because the receiver
    # applies it with ``subject_matches``: a narrowing dropped here is a grant
    # reaching creatures the sentence excludes.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("all", "each")
        and not node.subject.targeted
    ):
        described = testable_filter_payload(
            node.subject.filter,
            refusal="a team grant cannot narrow by",
            node=node,
            require_narrowing=False,
        )
        # Whose creatures. "Creatures **you control**" is the caster's board and
        # nothing else; a phrase naming no controller reaches every seat, which
        # is the same pair of scopes the keyword grant reads and for its reason
        # (Stampede is castable by the defending player).
        payload["filter"] = {
            key: value for key, value in described.items() if key != "controller"
        }
        if node.subject.filter.controller != "you":
            payload["every_seat"] = True
        return (OracleInstruction("grant_target_ability_text", "", payload),)
    if not _is_target(node.subject):
        raise LoweringError("unsupported granted-ability subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("grant_target_ability_text", "", payload),)

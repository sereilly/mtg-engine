"""Taking a keyword away (CR 702), the other half of ``keywords``.

Split from it at Tempest's wave-3 integration, when two groups' additions summed
past the 1,000-line guard with **neither branch at fault** — one added a grant
onto a token it had just created, the other a landwalk whose word is computed
from a sacrificed land. That is the shape SET_PLAYBOOK.md tells the integrator
to split at rather than to carry.

The seam is the one ``keywords``' own first line already draws: *"granting one,
and taking one away"*. They share the gate (a word outside
``vocabulary.IMPLEMENTED_KEYWORDS`` refuses the line rather than lowering onto a
removal of nothing, which reads as working) and nothing else; the two helpers
they did share went down to ``_common``, where a fragment two families need
belongs.

Granting is the half that grows — every set prints more ways to give an ability
than to take one — so it is the half that stayed.
"""

from __future__ import annotations

from ...keywords import keyword_ability_name
from ...oracle_types import OracleInstruction
from ...subject_filters import object_only_filter, untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ..vocabulary import IMPLEMENTED_KEYWORDS
from ._events import _EVENT_SUBJECT_OBJECTS, binds_block_pair
from ._common import (_describe_targets, _filter_payload, _is_landwalk,
                      _is_source, _is_target, _refuse_bare_chosen_ability,
                      _restrictions_beyond)


def _team_removal_payload(node: ast.LoseKeyword) -> dict[str, object] | None:
    """The payload for a board-wide keyword removal, or None when the subject
    is not one.

    Written against the same three facts the team *grant* reads — the
    quantifier, the card types and the controller — because "all creatures" and
    "creatures you control" are one sentence with one word changed, and the
    difference is which seats the handler walks.

    A narrowing the subject matcher cannot test refuses rather than being
    dropped. Dropping it on the grant side gives a keyword to more creatures
    than the card names; dropping it here takes one away from more creatures
    than the card names, which is the same error and just as silent.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec):
        return None
    if subject.targeted or subject.quantifier not in ("all", "each"):
        return None
    if subject.filter.card_types not in ((), ("creature",)):
        return None
    if subject.filter.controller not in ("you", None):
        return None
    leftover = _restrictions_beyond(
        subject.filter, frozenset({"card_types", "controller"})
    )
    described = _filter_payload(subject.filter)
    if leftover and untestable_filter_keys(described):
        raise LoweringError(
            "the team keyword removal cannot narrow by: " + ", ".join(leftover),
            node=node,
        )
    payload: dict[str, object] = {
        "keywords": tuple(node.keywords), "duration": "end_of_turn",
    }
    if not subject.filter.card_types:
        # "Permanents lose …" — the same removal over a wider board, which is
        # the one key that changes. The handler defaults to creatures, so every
        # payload written for the narrower reading stays what it was.
        payload["every_permanent"] = True
    if leftover:
        payload["filter"] = described
    # No controller word is every seat's board: "all creatures" is not "creatures
    # you control", and a removal scoped to the caster would leave the half of
    # the board the card names untouched.
    payload["every_seat"] = subject.filter.controller is None
    return payload


def _lower_lose_all_abilities(
    node: ast.LoseKeyword,
) -> tuple[OracleInstruction, ...]:
    """"Until end of turn, **target creature loses all abilities** …" (Humble.)

    CR 613.1f aimed at one permanent, which is the half of that rule this engine
    did not have: the blanket removal existed only as a **board-wide static**
    (Humility, Titania's Song — ``global_statics.removes_all_abilities``), and a
    static has no channel for "this one creature, until end of turn".

    Two refusals, and both are the shapes that already have owners:

    * **No duration** is the printed static ("All creatures lose all
      abilities"), which the global-statics table reads off the card's text and
      re-derives on every recompute. Claiming it here would replace a
      continuous effect with a one-shot stamp nothing re-derives, and a creature
      entering after Humility resolved would keep its abilities.
    * **A subject that is not a chosen target** is that same static's set, or a
      pronoun this instruction cannot address. The removal writes a record onto
      one permanent, so the sentence has to name one.
    """
    if node.duration.kind not in ("until_end_of_turn", "this_turn"):
        raise LoweringError(
            "a durationless blanket ability removal is a static ability "
            "(engine/global_statics.py)",
            node=node,
        )
    if not _is_target(node.subject):
        raise LoweringError(
            "the blanket ability removal reaches one chosen permanent",
            node=node,
        )
    payload: dict[str, object] = {"duration": "end_of_turn"}
    _describe_targets(payload, node.subject)
    return (
        OracleInstruction("remove_target_abilities_until_eot", "", payload),
    )


def _lower_lose_keyword(
    node: ast.LoseKeyword,
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """"It loses indestructible until end of turn." (Soul Sear, bound to the
    damage sentence's target by the pronoun rider.)

    The mirror of the targeted grant: `remove_keyword` puts the removal into
    layer 6, so it composes with grants by timestamp rather than by flag
    fights. Gated on IMPLEMENTED_KEYWORDS exactly like the grant — removing a
    word whose behaviour is not built would report a removal of nothing.
    """
    _refuse_bare_chosen_ability(node)
    if node.all_abilities:
        return _lower_lose_all_abilities(node)
    for keyword in node.keywords:
        # Through the ability's *name*, so a keyword carrying a printed
        # argument is asked about the ability rather than about the argument:
        # "all 'bands with other' abilities" and "bands with other legendary
        # creatures" are the same registry entry, and only the first is a word
        # any list could hold.
        if (
            keyword_ability_name(keyword) not in IMPLEMENTED_KEYWORDS
            and not _is_landwalk(keyword)
        ):
            raise LoweringError(
                f"removing {keyword!r} needs the keyword implemented", node=node
            )
        # A line-derived ability (CR 702.23a, CR 702.25a) is not in layer 6's
        # word set at all — the compiler built the trigger out of the printed
        # line — so removing the word there would report a removal and take
        # nothing away. That used to refuse here, with the comment "the day one
        # does, it needs the removal channel built". Barbed Foliage is that
        # card, and the channel is ``keywords.remove_ability_keyword``: the
        # keyword is recorded and ``Permanent.effective_card`` strikes its part
        # out of the keyword line, so the compiler never makes the trigger.
        # Which channel a word goes on is the *handler's* decision
        # (``handlers/pump._remove_one_keyword``), exactly as it is on the
        # granting side — so nothing here has to know the difference.
    if node.duration.kind is None:
        # "When this creature blocks, **it loses defender**." (Elder Land
        # Wurm.) Durationless and still not a static ability: it is the one-shot
        # effect of a *triggered* ability, so it happens once and the word is
        # gone for good rather than being a continuous effect the layer system
        # re-derives. `remove_keyword` without the until-end-of-turn flag writes
        # exactly that record into layer 6 — the cleanup sweep drops only the
        # flagged ones — so nothing new is needed under it.
        #
        # "{0}: This creature loses flying. (This effect lasts indefinitely.)"
        # (Mist Dragon.) An **activated** ability's own effect is the same
        # one-shot as the trigger's — CR 611.2 gives an effect with no printed
        # duration an indefinite one either way — so the gate here is the
        # subject, not which kind of ability produced the clause.
        #
        # It used to be ``event is None``, refusing on the ground that the
        # printed *static* line is a continuous effect the layer system has to
        # re-derive. That is true and it is enforced somewhere else: a bare
        # printed line about the source lowers through
        # ``statics._lower_lord_effects`` and refuses there with "static
        # abilities need the CR 613 layers engine", and one about a *set*
        # ("Creatures you control lose flying") is stopped by the `_is_source`
        # check immediately below. Nothing but an ability's effect clause
        # reaches this line, so the trigger test was buying nothing and cost
        # Mist Dragon the half of its card that turns the flying back off.
        if not _is_source(node.subject):
            raise LoweringError(
                "the durationless removal reaches the ability's own source",
                node=node,
            )
        return (
            OracleInstruction(
                "remove_self_keyword", "", {"keywords": tuple(node.keywords)}
            ),
        )
    if node.duration.kind not in ("until_end_of_turn", "this_turn"):
        raise LoweringError(
            f"no handler removes a keyword for {node.duration.kind!r}", node=node
        )
    # "**All creatures** lose flying until end of turn." (Whiteout.) The mirror
    # of the team *grant* above, and the same reading of CR 611.2c: the set is
    # locked in at resolution, so the handler walks the board once rather than
    # contributing a derived effect. The width is payload — which seats' boards
    # and which permanents on them — for the reason the grant's is: a card
    # printing "creatures you control lose flying" is the same instruction with
    # one key different.
    team = _team_removal_payload(node)
    if team is not None:
        return (OracleInstruction("remove_team_keyword_until_eot", "", team),)
    # "{1}{G}: This creature gains flying and **loses trample** until end of
    # turn." (Canopy Dragon); "{T}: This creature gets -2/+2 and **loses
    # flying** until end of turn." (Leering Gargoyle.) The ability's own source,
    # with a duration — which the durationless branch above reads and the
    # targeted branch below reads, and neither of them covered. Same kind as the
    # durationless self-removal, carrying the duration as payload for the reason
    # ``pump_self`` carries its "indefinite": every payload written before this
    # branch existed meant no expiry, so the new answer has to say so out loud.
    if _is_source(node.subject):
        return (
            OracleInstruction(
                "remove_self_keyword", "",
                {"keywords": tuple(node.keywords), "duration": "end_of_turn"},
            ),
        )
    # "Whenever a creature attacks you, **it** loses flanking until end of
    # turn." (Barbed Foliage.) The pronoun was rebound to the *event's* subject
    # by ``rebinding.rebind_pronoun_to_event_subject``, so it is neither the
    # source nor a target: nothing was chosen and nothing may be, because the
    # object is the one the event was about.
    #
    # Gated on the event, exactly as the counter one family over is: under any
    # other trigger the same word names an object no fire site recorded, and the
    # handler would strip a keyword from nothing while the card compiled clean.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "it"
        and not node.subject.filter.is_source
    ):
        if event not in _EVENT_SUBJECT_OBJECTS:
            raise LoweringError(
                "\"it\" names the object the event was about, and this event "
                "records none",
                node=node,
            )
        described = _filter_payload(node.subject.filter)
        if object_only_filter(described) is None:
            # The rebound filter re-states the event's own narrowing, so it is
            # carried and re-checked rather than dropped — a word consumed and
            # never read is a word that could be deleted with no change to what
            # the card does.
            raise LoweringError(
                "the removal's subject carries a restriction the resolution "
                "cannot test", node=node,
            )
        payload = {
            "keywords": tuple(node.keywords),
            "duration": "end_of_turn",
            "on_event_subject": True,
        }
        if described:
            payload["filter"] = described
        return (OracleInstruction("remove_event_subject_keyword", "", payload),)
    # "Whenever this creature blocks or becomes blocked by a creature, **that
    # creature** loses first strike until end of turn." (Talruum Champion.) The
    # mirror of the block-pair *grant* above, and admitted by the same
    # question: `binds_block_pair` rather than the kind, because CR 509.3c
    # makes a bare "becomes blocked" fire once with several blockers in hand
    # and no way to say which "that creature" is, while CR 509.3d's narrowed
    # spelling fires once per creature and names exactly one.
    #
    # It has to come **before** the target-shaped reading below, and that order
    # is the card: on the *blocks* half of the event the stack item's target is
    # the blocking creature itself (the fire site puts it there so a
    # self-affecting trigger can find itself), so falling through would strip
    # first strike from the Champion and leave the creature it blocked with it
    # — the card playing as its own opposite while reporting supported. The
    # grant one function up records the same trap.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("that", "other")
        and binds_block_pair(event, event_subject)
    ):
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "the block-pair keyword removal reads the creature its trigger "
                "already named and nothing narrower",
                node=node,
            )
        return (
            OracleInstruction(
                "remove_keyword_from_block_pair", "",
                {"keywords": tuple(node.keywords), "duration": "end_of_turn"},
            ),
        )
    if not _is_target(node.subject):
        raise LoweringError("no handler removes a keyword from this subject", node=node)
    payload: dict[str, object] = {"keywords": tuple(node.keywords)}
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("remove_target_keyword_until_eot", "", payload),)

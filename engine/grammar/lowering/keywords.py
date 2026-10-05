"""Lowering for keyword abilities (CR 702): granting one, and taking one away.

Split out of ``characteristics`` when that module reached the thousand-line
guard, and split *here* because the two answer different questions. CR 208 is
what a creature's power and toughness *are* — a characteristic, computed in
layer 7. CR 702 is an ability an object *has*, granted and removed in layer 6.
The pump family and this one shared no helper, only the module.

The gate both halves pass is the same one: a word outside
``vocabulary.IMPLEMENTED_KEYWORDS`` refuses the line rather than lowering onto a
grant of nothing (or, worse, a removal of nothing, which reads as working).
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import (CHOSEN_COLOR_THIS_WAY, CHOSEN_TARGET_PERMANENTS,
                             OracleInstruction)
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ..keywords import (PROTECTION_FROM_CHOSEN_COLOR,
                        PROTECTION_FROM_EACH_OF_THAT_PERMANENTS_COLORS,
                        PROTECTION_FROM_TARGETS_CONTROLLERS_CHOSEN_COLOR,
                        PROTECTION_FROM_THE_CHOSEN_COLOR)
from ..vocabulary import IMPLEMENTED_KEYWORDS
from ._events import _RECORDED_PERMANENTS, binds_block_pair
from ._record_keys import CREATED_TOKEN
from ._common import (_check_grantable, _describe_several_targets,
                      _describe_targets, _filter_payload,
                      _durationless_reason, _is_created_token,
                      _refuse_bare_chosen_ability,
                      _restrictions_beyond, _is_enchanted,
                      _is_source, _is_target, _names_several_targets,
                      testable_filter_payload)

#: Where a landwalk whose land type is not printed reads that type from
#: (Excavator: "landwalk of each of the land types of **the sacrificed land**").
#: The parse side names the record in its own words and this is the only place
#: those words become a scratchpad key — an unlisted word refuses the line
#: rather than lowering onto a record nothing writes, which is the difference
#: between an unsupported card and one that grants no keyword at all.
_LANDWALK_SOURCES: dict[str, str] = {"sacrificed": "sacrificed_for_cost"}

_KEYWORD_GRANTS: dict[tuple[str, str], str] = {
    ("flying", "target"): "grant_target_flying_until_eot",
    ("flying", "self"): "grant_self_flying_until_eot",
    ("banding", "target"): "grant_banding_to_target",
}


#: The printed durations a grant has a sweep for, mapped to the
#: `keywords.KEYWORD_GRANT_DURATIONS` key that names it. Everything absent
#: refuses: a duration the engine cannot *end* is a grant that outlives what the
#: card said, which is worse than an unsupported card.
#:
#: One table for both grant channels — a keyword and a quoted ability line —
#: because the printed phrase is the same phrase and the two channels are swept
#: together. It served the quoted line alone while the keyword grant answered
#: the question with a boolean, which is how "until end of combat" over a
#: keyword became "until end of turn" without anything refusing.
_GRANT_DURATIONS: dict[str, str] = {
    "until_end_of_turn": "end_of_turn",
    "this_turn": "end_of_turn",
    "until_end_of_combat": "end_of_combat",
    # "…gains that ability **until your next upkeep**" (Gabriel Angelfire).
    # Whose upkeep is CR 109.5's answer — the controller of the ability — and
    # the handler freezes that seat, because by the time the sweep runs the
    # affected permanent may be controlled by somebody else.
    "until_your_next_upkeep": "your_next_upkeep",
}


def _grant_duration(node, duration) -> str:
    """The channel key *duration* names, or a refusal.

    Asked by every grant lowering in this file, so a printed duration is
    admitted in exactly one place — which is what makes the table above the
    answer to "which durations does this engine end" rather than a list one
    branch happens to consult.
    """
    key = _GRANT_DURATIONS.get(duration.kind)
    if key is None:
        raise LoweringError(
            f"no grant handler expires at the duration {duration.kind!r}",
            node=node,
        )
    return key


def _binds_a_recorded_permanent(subject, produced: frozenset[str]) -> bool:
    """Whether *subject* is the "that creature" an earlier step of this same
    effect recorded — the arm at the bottom of :func:`_lower_gain_keyword`.

    Asked by the **undurated** branch far above that arm, which would otherwise
    refuse the sentence before it could be reached. One predicate rather than
    the condition written twice, so the two readings of the pronoun cannot come
    apart: a gate that admitted a phrase the arm then refused would trade one
    refusal message for another, and one that admitted more than the arm claims
    would fall through to "unsupported keyword-grant subject" instead.

    "That **token**" is deliberately not one of these: ``CREATED_TOKEN`` is not
    a member of :data:`_RECORDED_PERMANENTS` and the token arm is asked first,
    so a card printing both a token maker and (say) a tap would otherwise reach
    that arm through a gate written for its neighbour.
    """
    return (
        isinstance(subject, ast.TargetSpec)
        and not _is_created_token(subject)
        and subject.quantifier in ("that", "those")
        and bool(produced & _RECORDED_PERMANENTS)
    )


def _targets_description(payload: dict[str, object]) -> dict[str, object]:
    """Just the ``targets`` description out of *payload*, or nothing.

    Named rather than spelled inline at its one call site, because what it
    copies is a **claim**: that the two steps Wishmonger's sentence lowers to
    point at one permanent. A second, differently-written description would be
    a chooser and a grantee the engine could disagree about.
    """
    described = payload.get("targets")
    return {"targets": described} if described is not None else {}


def _lower_gain_keyword(
    node: ast.GainKeyword,
    event: str | None = None,
    event_subject: object | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    # "gains **your choice of** deathtouch or lifelink" (Alchemist's Gift). A
    # choice between two effects is `choose_one` — the composition seam
    # (engine/handlers/control_flow.py) that a modal ability already uses — so
    # there is no per-keyword prompt, no new pending-choice kind, and the
    # non-interactive default is the one already stated for a mode: the first
    # printed. Lowering each alternative through this same function is what
    # keeps a keyword the engine cannot grant refusing the whole line rather
    # than being offered as an option that does nothing.
    if node.choose_one:
        alternatives = tuple(
            dataclasses.replace(node, keywords=(keyword,), choose_one=False)
            for keyword in node.keywords
        )
        modes = []
        for alternative in alternatives:
            lowered = _lower_gain_keyword(alternative, event, event_subject)
            # "…protection from artifacts or from **the color of your choice**"
            # (Jeweled Spirit). An alternative that asks its own question is two
            # steps — the ask and the grant — and the mode is both of them, in
            # order: the colour is asked only if that alternative is the one
            # taken, which is why the ask rides inside the mode rather than in
            # front of the whole choice.
            instruction = (
                lowered[0] if len(lowered) == 1
                else OracleInstruction("sequence", "", {"steps": lowered})
            )
            modes.append({"label": alternative.keywords[0], "instruction": instruction})
        return (OracleInstruction("choose_one", "", {"modes": tuple(modes)}),)
    return _chosen_color_prelude(node, produced) + _lower_granted_keywords(
        node, event, event_subject, produced
    )


def _chosen_color_prelude(
    node: ast.GainKeyword, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """The step that asks "the color of your choice", or nothing.

    CR 608.2d: a colour is not among what CR 601.2b–c / 602.2b announce, so
    the player names it *while the effect is applied* — after every response
    has resolved, which is the whole point of Mother of Runes. A handler that
    stopped to ask could not also finish the grant (the answer arrives after it
    has returned), so the question is a step in front of the sentence that
    spends it: Extinction's "of the creature type of your choice" is the same
    arrangement one characteristic over (``_common.split_creature_type_choice``),
    and Wishmonger's ask below is the same step asked of a different seat.

    ``chooser: "you"`` is CR 109.5's "your" — the controller of the spell or
    ability, which for an activated ability is the player who activated it —
    and it records the answer in this resolution's scratchpad alone: the
    granting permanent has no continuous ability that keeps asking about a
    colour, so a standing record on it would be a second, staler answer.

    "The chosen color" asks nothing: it reads back what a "Choose a color."
    sentence earlier in this effect recorded, so it is admitted only where one
    did — read under any other sentence it would grant from a colour nobody in
    this resolution was asked.
    """
    if (
        PROTECTION_FROM_THE_CHOSEN_COLOR in node.keywords
        and CHOSEN_COLOR_THIS_WAY not in produced
    ):
        raise LoweringError(
            "'the chosen color' reads a colour an earlier sentence of this "
            "effect chose, and none did",
            node=node,
        )
    if (
        PROTECTION_FROM_EACH_OF_THAT_PERMANENTS_COLORS in node.keywords
        and CHOSEN_TARGET_PERMANENTS not in produced
    ):
        # "…protection from each of **that permanent's colors**" (Samite
        # Elder). The same rule one record over: the words name the permanent a
        # "Choose target permanent …" sentence earlier in this effect recorded,
        # and read under any other sentence they would grant from an object
        # nobody chose — which the handler answers with no protection at all,
        # on a card reporting supported.
        raise LoweringError(
            "'that permanent's colors' reads a permanent an earlier sentence "
            "of this effect chose, and none did",
            node=node,
        )
    if PROTECTION_FROM_CHOSEN_COLOR not in node.keywords:
        return ()
    return (OracleInstruction("choose_color", "", {"chooser": "you"}),)


def _lower_granted_keywords(
    node: ast.GainKeyword,
    event: str | None,
    event_subject: object | None,
    produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    """Every grant that is not a choice between keywords — the body of
    :func:`_lower_gain_keyword` behind its "your choice of" branch and its
    colour question."""
    # "Target creature gains **landwalk of each of the land types of the
    # sacrificed land** until end of turn." (Excavator.) CR 702.14a builds a
    # landwalk's *name* out of a land type, and which land type is a fact about
    # the cost that was paid — so no keyword can be in the payload and the
    # handler builds the words at resolution off the record the cost wrote.
    #
    # `_check_grantable` is deliberately not asked: it validates printed words,
    # and there is none here. What stands in its place is the table above (the
    # record has to be one something writes) and `landwalk.landwalk_abilities_of`
    # (every word it builds is one `landwalk_requirement` can answer, because it
    # is built from the land's own types).
    _refuse_bare_chosen_ability(node)
    if node.landwalk_from is not None:
        if node.keywords:
            raise LoweringError(
                "a computed landwalk grant carries no printed keyword", node=node
            )
        record = _LANDWALK_SOURCES.get(node.landwalk_from)
        if record is None:
            raise LoweringError(
                f"nothing records the land {node.landwalk_from!r} names", node=node
            )
        if not _is_target(node.subject):
            raise LoweringError(
                "a computed landwalk grant reads a chosen target", node=node
            )
        computed: dict[str, object] = {
            "keywords": (),
            "duration": _grant_duration(node, node.duration),
            "landwalk_from": record,
        }
        _describe_targets(computed, node.subject)
        return (
            OracleInstruction("grant_target_keyword_until_eot", "", computed),
        )
    if node.duration.kind is None:
        # "…and that creature gains flying." (Cocoon's hatch, bound to the
        # enchanted creature by the rider that read it.) A one-shot grant with
        # no stated duration lasts until the end of the game (CR 611.2a:
        # "If no duration is stated, it lasts until the end of the game") —
        # which on a permanent means until it leaves, since CR 400.7 makes
        # what comes back a different object. Recorded on the *creature*
        # through the layer-6 write API, which is what lets it outlive the
        # Aura that granted it.
        if _is_enchanted(node.subject):
            leftover = _restrictions_beyond(
                node.subject.filter, frozenset({"card_types", "is_enchanted"})
            )
            if leftover:
                raise LoweringError(
                    "the enchanted keyword grant cannot narrow by: "
                    + ", ".join(leftover),
                    node=node,
                )
            if len(node.keywords) != 1:
                raise LoweringError(
                    "the enchanted keyword grant takes one keyword", node=node
                )
            keyword = node.keywords[0]
            if keyword not in IMPLEMENTED_KEYWORDS:
                raise LoweringError(
                    f"granting {keyword!r} needs the keyword implemented", node=node
                )
            return (
                OracleInstruction(
                    "grant_keyword_to_attached", "", {"keyword": keyword}
                ),
            )
        # "{1}{R}: This creature … gains flying." (Goblin Ski Patrol.) The
        # keyword half of the same sentence the pump lowering admits one module
        # over, and indefinite for the same CR 611.2a reason: a resolved
        # ability's grant with no printed duration is not the *static* ability's
        # continuous contribution the refusal below is about — that one is
        # refused a layer up, in `_lower_static_ability`.
        #
        # Through the very kinds a durated self-grant already uses, with the
        # duration named as ``None``. ``engine/keywords.grant_keyword`` has
        # always meant "no sweep takes this away" by that value, so the
        # difference between this card and Fetid Imp is one payload entry
        # rather than a second channel.
        if _is_source(node.subject):
            for keyword in node.keywords:
                _check_grantable(keyword, node)
            if len(node.keywords) == 1:
                kind = _KEYWORD_GRANTS.get((node.keywords[0], "self"))
                if kind is not None:
                    return (OracleInstruction(kind, "", {"duration": None}),)
            return (
                OracleInstruction("grant_self_keyword_until_eot", "", {
                    "keywords": tuple(node.keywords), "duration": None,
                }),
            )
        # "Put a +1/+1 counter on target creature or **that creature gains
        # banding, first strike, or trample**." (Nature's Blessing, whose
        # reminder text says the effect "lasts indefinitely".) A *chosen*
        # object's grant with no printed duration, which is CR 611.2a's
        # indefinite one — the same reading the source branch above already
        # takes, and through the same channels: `grant_keyword` has always
        # meant "no sweep takes this away" by a ``None`` duration, and
        # `KEYWORD_GRANT_DURATIONS` documents that value. So the difference
        # between this and Helm of Chatzuk's "until end of turn" is one payload
        # entry rather than a second handler.
        #
        # Everything past this point is the ordinary target path: the narrowing
        # is described for the picker, the keyword registry is asked, and a
        # keyword with no behaviour behind it still refuses.
        #
        # "You may put a creature card from your hand onto the battlefield.
        # **That creature gains haste.**" (Sneak Attack.) The *bound* spelling
        # of the same indefinite grant, and it is admitted here only so the
        # arm far below can claim it — the two arms are already written, one
        # for the printed duration and one for the back-reference, and this
        # branch was between them refusing every sentence that carried both.
        # A grant with no printed duration lasts as long as the object
        # (CR 611.2a), which is the reading the source and target branches
        # above take; the permanent it names is the one an earlier step of this
        # same resolution recorded, so nothing about *how long* changes with
        # *which* permanent.
        #
        # Gated on a producer, exactly as that arm is: with nothing recorded in
        # front of it the pronoun names no permanent, and the refusal below
        # stays. "That **token**" is not admitted — `CREATED_TOKEN` is not one
        # of these records, so the token arm goes on refusing an undurated
        # grant rather than being widened by a gate written for its neighbour.
        if not (_is_target(node.subject) or _binds_a_recorded_permanent(node.subject, produced)):
            reason = _durationless_reason(node.subject)
            if reason.startswith("continuous pump"):
                reason = "continuous keyword grant needs the CR 613 layers engine"
            raise LoweringError(reason, node=node)
        duration: str | None = None
    else:
        duration = _grant_duration(node, node.duration)
    # Which sweep ends this grant, decided **before** any kind is chosen. Every
    # branch below used to hand the layer-6 channel a bare ``until_eot=True``,
    # so a duration this table does not hold did not refuse — it became end of
    # turn. That took "until end of combat" through the opponent's whole turn
    # and ended "until your next turn" a step early, and it is why Erhnam
    # Djinn's line needed a card-keyed hook: the one duration whose loss was
    # *visible* was special-cased into a refusal here, and the hook caught it.
    # The hook is gone with this table.
    # "Creatures you control gain flying until end of turn." (Basri, Devoted
    # Paladin's −6.) A team grant locked in at resolution (CR 611.2c) — its own
    # kind, resolved over the controller's board by the handler.
    #
    # "**Permanents** you control gain hexproof and indestructible" (Heroic
    # Intervention) is the same grant over a wider board, and the width is the
    # only difference — so it is a payload key rather than a second kind. The
    # key is emitted only for the wider reading, which leaves every payload
    # written before it byte-identical, and the handler defaults to creatures.
    #
    # "**All lands** gain shroud until end of turn." (Skyshroud Blessing.) The
    # same grant over a board named by another card type. The handler has two
    # widths — creatures, or every permanent — so a type that is neither is
    # carried the way Stampede's "attacking" is: as a filter over the wider
    # board, tested by the one subject matcher. The branch used to admit only
    # the two widths, which left every other typed sweep at "unsupported
    # keyword-grant subject" for a grant the handler already performs.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "all"
        and node.subject.filter.controller in ("you", None)
        # The handler resolves the board once, at resolution (CR 611.2c), so a
        # duration it can end is the only requirement — which the table above
        # has already checked.
        and duration == "end_of_turn"
    ):
        typed = node.subject.filter.card_types not in ((), ("creature",))
        # "creatures you control **blocking that creature** gain first strike"
        # (Tidal Flats). A relation to the object the loop around this sentence
        # bound, not a characteristic of the blocker — so it has no
        # ``to_payload`` form and no matcher key, and it is carried as its own
        # payload word the handler resolves against the combat maps. The same
        # decomposition ``prevent_damage_by_target_until_eot`` makes for
        # "…and each creature blocking it" (Feint).
        blocking_bound = node.subject.filter.blocking_bound_target
        carried = frozenset({"blocking_bound_target"}) if blocking_bound else frozenset()
        leftover = _restrictions_beyond(
            node.subject.filter,
            frozenset({"card_types", "controller"}) | carried,
        )
        described = _filter_payload(node.subject.filter, carried_separately=carried)
        if leftover or typed:
            # "**Attacking** creatures get +1/+0 and gain trample until end of
            # turn" (Stampede). A narrowing the *matcher* can test is carried as
            # a filter rather than refused — the P/T half of this very sentence
            # already goes to `buff_creatures_global` with the same narrowing,
            # so refusing here shipped a card whose two halves reached two
            # different sets of creatures.
            #
            # Only a testable one: an untestable key dropped from a grant is a
            # keyword given to more creatures than the card names, which is the
            # one direction this must never go.
            if untestable_filter_keys(described):
                raise LoweringError(
                    "the team keyword grant cannot narrow by: " + ", ".join(leftover),
                    node=node,
                )
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        team_payload: dict[str, object] = {"keywords": tuple(node.keywords)}
        if typed or not node.subject.filter.card_types:
            team_payload["every_permanent"] = True
        if leftover or typed:
            # The narrowing travels whole, and with it the fact that the
            # sentence named no controller: "attacking creatures" is every
            # attacking creature, and Stampede is castable by the defending
            # player.
            team_payload["filter"] = described
            team_payload["every_seat"] = node.subject.filter.controller is None
        elif node.subject.filter.controller is None:
            # "**All creatures** gain menace until end of turn." (Gorilla War
            # Cry.) No controller word and no other narrowing is every creature
            # on the table, which is the same `every_seat` the narrowed
            # sentence above already carries — the width is what the printed
            # word says and nothing else about the grant changes.
            #
            # It used to refuse here, naming the handler: "the team keyword
            # grant reads one player's board". That stopped being true when
            # Stampede taught the handler the key, and a refusal that outlives
            # its reason is a card unsupported for a mechanic the engine has.
            team_payload["every_seat"] = True
        if blocking_bound:
            team_payload["blocking_bound_target"] = True
        team_payload["duration"] = duration
        return (OracleInstruction("grant_team_keyword_until_eot", "", team_payload),)
    # "**X** target creatures gain islandwalk until end of turn." (Part Water.)
    # Several chosen targets rather than one, which is a property of the noun
    # phrase and not of the effect — so it is the same instruction with a
    # several-target description, and the handler grants to each. Described
    # through `_describe_several_targets`, which is the opt-in a handler that
    # reads a list makes; describing it the ordinary way would raise a
    # multi-slot picker in front of a one-target resolution and drop every
    # choice after the first.
    if _names_several_targets(node.subject):
        assert isinstance(node.subject, ast.TargetSpec)
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        several_payload: dict[str, object] = {
            "keywords": tuple(node.keywords), "duration": duration,
        }
        _describe_several_targets(several_payload, node.subject)
        return (
            OracleInstruction("grant_target_keyword_until_eot", "", several_payload),
        )
    # "Each creature blocking or blocked by this creature gains first strike
    # until end of turn." (Spitting Slug.) A set named by a combat relation to
    # the ability's own source (CR 509), which is not a characteristic any
    # candidate carries — so the relation is the whole of the instruction and
    # nothing is described for a picker. The team grant beside it cannot take
    # this: it walks the *caster's* board, and the creatures blocking this one
    # are the opponent's.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and not node.subject.targeted
        and node.subject.quantifier in ("all", "each")
        and node.subject.filter.in_combat_with_source
    ):
        leftover = _restrictions_beyond(
            node.subject.filter,
            frozenset({"card_types", "in_combat_with_source"}),
        )
        if leftover or node.subject.filter.card_types != ("creature",):
            raise LoweringError(
                "the combat-pair keyword grant reads creatures in combat with "
                "its source and nothing narrower",
                node=node,
            )
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        return (
            OracleInstruction(
                "grant_keyword_to_creatures_in_combat_with_source", "",
                {"keywords": tuple(node.keywords), "duration": duration},
            ),
        )
    # "…**that creature** gains first strike until end of turn." (Goblin
    # Flotilla, and the printed static form of the same sentence.) The other
    # half of the block pair the trigger fired on — named by the ids the fire
    # site recorded, not by anything the creature carries, which is why the
    # relation is the whole instruction and nothing is described for a picker.
    #
    # ``binds_block_pair`` is what admits it: CR 509.3c/509.3d make a *bare*
    # block trigger fire once with several creatures in hand and no way to say
    # which "that creature" is, so the narrowing has to be printed. Under any
    # other event the words name nothing and the refusal below stands.
    #
    # "…**the other** creature gains first strike until end of turn." (Mammoth
    # Harness.) The same referent under a different printed word: a block binds
    # two creatures, the trigger's own is one of them, and the ordinal names the
    # one left — which is exactly the creature ``block_pair_permanents``
    # returns. ``lowering/destruction.py`` already reads the pair's two
    # spellings as one referent (Thicket Basilisk's "that creature", Infinite
    # Authority's "the other creature"); this is that same equality in the
    # keyword family, and the ordinal is admitted **only** here, where a pair is
    # what the trigger bound.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("that", "other")
        and binds_block_pair(event, event_subject)
    ):
        if _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
            raise LoweringError(
                "the block-pair keyword grant reads the creature its trigger "
                "already named and nothing narrower",
                node=node,
            )
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        return (
            OracleInstruction(
                "grant_keyword_to_block_pair", "",
                {"keywords": tuple(node.keywords), "duration": duration},
            ),
        )
    # "…**it** gains trample until end of turn", where the trigger's subject was
    # the enchanted creature (Bestial Fury). The keyword half of the same
    # rebinding ``pump_enchanted_creature`` already carries one family over: the
    # pronoun points at the Aura's host, not at the Aura, and an Aura that gave
    # *itself* trample is a card doing nothing at all.
    #
    # Checked before the source/target split below, because the rebound subject
    # is neither: it is a `TargetSpec` the reader never picks, resolved at
    # resolution off the attachment record.
    if _is_enchanted(node.subject):
        if _restrictions_beyond(
            node.subject.filter, frozenset({"card_types", "is_enchanted"})
        ):
            raise LoweringError(
                "the attached keyword grant reads the permanent its Aura is "
                "attached to and nothing narrower",
                node=node,
            )
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        return (
            OracleInstruction(
                "grant_enchanted_keyword_until_eot", "",
                {"keywords": tuple(node.keywords), "duration": duration},
            ),
        )
    # "…**That token** gains haste until end of turn." (Echo Chamber.) The
    # token an earlier step of this same resolution made, which is neither the
    # source nor a target: the ability targets nothing this sentence could
    # mean, and the token did not exist when it was activated (CR 400.7).
    #
    # Its own arm rather than a member of ``_RECORDED_PERMANENTS`` above,
    # because the phrase is spelled by the *noun* rather than by the
    # quantifier: ``references`` reads "that token" into a filter flag and
    # "that creature" into a card type, and the reader that answers one cannot
    # answer the other. ``lowering/exile.py`` draws the same line for the same
    # two words.
    #
    # Read **before** the recorded-permanent arm below, and that ordering is
    # load-bearing rather than tidy: "that token" carries the ``that``
    # quantifier too, so that arm would claim the phrase and then refuse it
    # for carrying a narrowing (``is_created_token``) it has no answer for.
    #
    # ``produced`` is the whole gate, exactly as it is there: with no token
    # maker in front of it the words name nothing, and a grant that silently
    # found nothing would be a card reporting itself supported and doing
    # nothing.
    if _is_created_token(node.subject):
        if CREATED_TOKEN not in produced:
            raise LoweringError(
                "back-reference to a created token with no token maker in "
                "this effect",
                node=node,
            )
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        return (
            OracleInstruction(
                "grant_target_keyword_until_eot", "",
                {
                    "keywords": tuple(node.keywords), "duration": duration,
                    "permanents_from": CREATED_TOKEN,
                },
            ),
        )
    # "…**That creature** gains haste until end of turn." (Shallow Grave;
    # Zirilan of the Claw prints "that Dragon".) The permanent an earlier
    # step of this same resolution put onto the battlefield — not a target,
    # because the ability's target is a *card* in a graveyard or a library
    # and the permanent did not exist when it was announced.
    #
    # The quoted-ability grant beside this one has read the same record since
    # Dreams of the Dead; the *keyword* grant refused the subject outright,
    # which is one printed pronoun with two answers. `produced` is the gate,
    # so with nothing recorded the words keep whatever reading they had.
    # "**Those creatures** gain haste until end of turn." (Reins of Power.) The
    # plural spelling of the identical back-reference, admitted beside the
    # singular rather than under a branch of its own: the ``permanents_from``
    # channel is always a sequence and the handler already iterates it, so the
    # only thing the two words differ in is how many permanents the step in
    # front happened to record. `lowering/tapping.py` and the untap-restriction
    # lowering have read the plural since Frost Breath; the keyword grant
    # refused it, which is one printed pronoun with two answers.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier in ("that", "those")
        and (produced & _RECORDED_PERMANENTS)
    ):
        # A bound object carries no narrowing to honour: the noun restates
        # what the step in front of it already found ("that **Dragon**" after
        # a search for a Dragon), and a subtype re-tested at resolution would
        # be a second reading of one choice. Anything beyond the printed type
        # and subtype refuses rather than being dropped.
        if _restrictions_beyond(
            node.subject.filter, frozenset({"card_types", "subtypes"})
        ):
            raise LoweringError(
                "a bound keyword grant reads the permanent an earlier step "
                "recorded and nothing narrower", node=node,
            )
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if len(recorded) != 1:
            raise LoweringError(
                "\"that creature\" is ambiguous: several earlier steps "
                "recorded objects", node=node,
            )
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        return (
            OracleInstruction(
                "grant_target_keyword_until_eot", "",
                {
                    "keywords": tuple(node.keywords), "duration": duration,
                    "permanents_from": recorded[0],
                },
            ),
        )
    scope = "self" if _is_source(node.subject) else ("target" if _is_target(node.subject) else None)
    if scope is None:
        raise LoweringError("unsupported keyword-grant subject", node=node)
    # "Target creature gains protection from the color of **its controller's**
    # choice until end of turn." (Wishmonger.) The word "its" names the subject
    # of this very sentence, so a grant whose subject is the source — or a
    # sweep, which has no single controller — would leave the possessive
    # pointing at nobody. Refused where the scope is known rather than at the
    # arm below, so the message names the phrase that is wrong.
    asks_the_targets_controller = (
        PROTECTION_FROM_TARGETS_CONTROLLERS_CHOSEN_COLOR in node.keywords
    )
    if asks_the_targets_controller and scope != "target":
        raise LoweringError(
            "'its controller's choice' names the creature this sentence "
            "targets", node=node,
        )
    if len(node.keywords) == 1:
        kind = _KEYWORD_GRANTS.get((node.keywords[0], scope))
        if kind is not None:
            shortcut: dict[str, object] = {"duration": duration}
            # **The printed noun phrase travels even down the shortcut.** These
            # kinds used to carry a duration and nothing else, and the phrase in
            # front of the verb was simply dropped: Whalebone Glider's "target
            # creature **with power 3 or less**" and Krovikan Elementalist's
            # "target creature **you control**" both offered every creature on
            # the board, because `engine/targeting.py` derives the picker from
            # this payload and there was nothing in it to narrow. Goblin Kites
            # prints the same shape with two narrowings at once.
            #
            # Described rather than re-routed to the generic pair below, whose
            # handler re-tests the phrase at resolution: an *earlier step of the
            # same ability* may have changed the creature (Phantasmal Mount's
            # "gets +1/+1 **and** gains flying until end of turn" takes a
            # toughness-2 creature to 3 before the grant runs), and CR 608.2b
            # checks a target's legality once, when the ability begins
            # resolving — not between its instructions. So the narrowing is
            # enforced where the rules put it, at announcement
            # (CR 601.2c / 602.2b, `legality.py`'s gates over the same
            # `_enumerate_targets` list the picker gets).
            if scope == "target":
                _describe_targets(shortcut, node.subject)
            return (OracleInstruction(kind, "", shortcut),)
    # Any other grant rides the generic payload pair, gated on the keyword
    # registry: `grant_keyword` puts the word into layer 6 for anything, but a
    # word whose behaviour is not built would be a grant of nothing — the same
    # silent wrongness the printed-keyword gate refuses. Several keywords in
    # one sentence ("gains hexproof and indestructible") are one instruction
    # carrying them all.
    for keyword in node.keywords:
        _check_grantable(keyword, node)
    payload: dict[str, object] = {
        "keywords": tuple(node.keywords), "duration": duration,
    }
    if scope == "self":
        return (OracleInstruction("grant_self_keyword_until_eot", "", payload),)
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    grant = OracleInstruction("grant_target_keyword_until_eot", "", payload)
    if not asks_the_targets_controller:
        return (grant,)
    # **Two steps for one printed sentence** (Wishmonger), because CR 608.2d
    # makes the colour a choice taken *during* this resolution and the seat
    # taking it is not the one that announced anything: it is the controller of
    # the creature the grant lands on. A prompt that suspends cannot be armed
    # and answered inside one handler — the answer arrives after the handler has
    # returned — so the ask and the grant are a ``sequence``, which is the loop
    # ``engine/resumption.py`` records the rest of. ``choose_color`` already
    # declares ``CHOSEN_COLOR_THIS_WAY`` as what it produces, and
    # ``_grant_one_keyword`` is the step behind it that spends the record.
    #
    # The **same** ``targets`` description rides both steps, so the two resolve
    # one creature through one reader: a chooser found by a second reading of
    # the announcement is a seat that can disagree with the seat the grant
    # lands on, and the printed word "its" is precisely the claim that they are
    # the same.
    ask = OracleInstruction(
        "choose_color", "",
        {"chooser": "target_controller", **_targets_description(payload)},
    )
    return (ask, grant)



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
        # grant above takes, and the reason the channel takes the sweep's name
        # rather than assuming one answer.
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

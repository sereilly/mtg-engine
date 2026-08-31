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

from ...banding import BANDS_WITH_OTHER
from ...keywords import LINE_DERIVED_KEYWORDS, keyword_ability_name
from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ..vocabulary import IMPLEMENTED_KEYWORDS, NUMERIC_ARGUMENT_KEYWORDS
from ._common import (
    _describe_several_targets,
    _describe_targets,
    _filter_payload,
    _durationless_reason,
    _restrictions_beyond,
    _is_enchanted,
    _is_source,
    _is_target,
    _names_several_targets,
    _targets_payload,
)

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


def _lower_gain_keyword(node: ast.GainKeyword) -> tuple[OracleInstruction, ...]:
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
            lowered = _lower_gain_keyword(alternative)
            if len(lowered) != 1:
                raise LoweringError("a keyword choice needs one instruction per option", node=node)
            modes.append({"label": alternative.keywords[0], "instruction": lowered[0]})
        return (OracleInstruction("choose_one", "", {"modes": tuple(modes)}),)
    if node.duration.kind is None:
        # "…and that creature gains flying." (Cocoon's hatch, bound to the
        # enchanted creature by the rider that read it.) A one-shot grant with
        # no stated duration lasts as long as the object (CR 611.2c's last
        # bullet: no duration and no source dependence means it holds until
        # the object leaves) — recorded on the *creature* through the layer-6
        # write API, which is what lets it outlive the Aura that granted it.
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
        # over, and indefinite for the same CR 611.2b reason: a resolved
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
        reason = _durationless_reason(node.subject)
        if reason.startswith("continuous pump"):
            reason = "continuous keyword grant needs the CR 613 layers engine"
        raise LoweringError(reason, node=node)
    # Which sweep ends this grant, decided **before** any kind is chosen. Every
    # branch below used to hand the layer-6 channel a bare ``until_eot=True``,
    # so a duration this table does not hold did not refuse — it became end of
    # turn. That took "until end of combat" through the opponent's whole turn
    # and ended "until your next turn" a step early, and it is why Erhnam
    # Djinn's line needed a card-keyed hook: the one duration whose loss was
    # *visible* was special-cased into a refusal here, and the hook caught it.
    # The hook is gone with this table.
    duration = _grant_duration(node, node.duration)
    # "Creatures you control gain flying until end of turn." (Basri, Devoted
    # Paladin's −6.) A team grant locked in at resolution (CR 611.2c) — its own
    # kind, resolved over the controller's board by the handler.
    #
    # "**Permanents** you control gain hexproof and indestructible" (Heroic
    # Intervention) is the same grant over a wider board, and the width is the
    # only difference — so it is a payload key rather than a second kind. The
    # key is emitted only for the wider reading, which leaves every payload
    # written before it byte-identical, and the handler defaults to creatures.
    if (
        isinstance(node.subject, ast.TargetSpec)
        and node.subject.quantifier == "all"
        and node.subject.filter.card_types in ((), ("creature",))
        and node.subject.filter.controller in ("you", None)
        # The handler resolves the board once, at resolution (CR 611.2c), so a
        # duration it can end is the only requirement — which the table above
        # has already checked.
        and duration == "end_of_turn"
    ):
        leftover = _restrictions_beyond(
            node.subject.filter, frozenset({"card_types", "controller"})
        )
        described = _filter_payload(node.subject.filter)
        if leftover:
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
        elif node.subject.filter.controller is None:
            # No controller word and no other narrowing is "all creatures",
            # which the board-wide grant below is not — it walks one seat.
            raise LoweringError(
                "the team keyword grant reads one player's board", node=node
            )
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        team_payload: dict[str, object] = {"keywords": tuple(node.keywords)}
        if not node.subject.filter.card_types:
            team_payload["every_permanent"] = True
        if leftover:
            # The narrowing travels whole, and with it the fact that the
            # sentence named no controller: "attacking creatures" is every
            # attacking creature, and Stampede is castable by the defending
            # player.
            team_payload["filter"] = described
            team_payload["every_seat"] = node.subject.filter.controller is None
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
    scope = "self" if _is_source(node.subject) else ("target" if _is_target(node.subject) else None)
    if scope is None:
        raise LoweringError("unsupported keyword-grant subject", node=node)
    if len(node.keywords) == 1:
        kind = _KEYWORD_GRANTS.get((node.keywords[0], scope))
        if kind is not None:
            return (OracleInstruction(kind, "", {"duration": duration}),)
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
    return (OracleInstruction("grant_target_keyword_until_eot", "", payload),)



def _lower_gain_ability_text(node: ast.GainAbilityText) -> tuple[OracleInstruction, ...]:
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
        # (CR 611.2c's last bullet) — the same reading the durationless keyword
        # grant above takes, and the reason the channel takes the sweep's name
        # rather than assuming one answer.
        "duration": _GRANT_DURATIONS.get(node.duration.kind),
    }
    if _is_source(node.subject):
        return (OracleInstruction("grant_self_ability_text", "", payload),)
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
    if bound:
        return (OracleInstruction("grant_target_ability_text", "", payload),)
    if not _is_target(node.subject):
        raise LoweringError("unsupported granted-ability subject", node=node)
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("grant_target_ability_text", "", payload),)


LANDWALK = "landwalk"


def _is_landwalk(keyword: str) -> bool:
    """Whether *keyword* is a landwalk the engine enforces.

    Asked beside :data:`IMPLEMENTED_KEYWORDS` rather than folded into it,
    because CR 702.14a builds a landwalk's **name** out of a printed quality —
    "islandwalk", "snow forestwalk", "nonbasic landwalk" — so the set of names
    is open and no frozenset can hold it. `engine/landwalk.py` is the reader
    that decides whether a quality is one the block check can test, and it is
    already the gate `engine/oracle.py` asks about a printed keyword *line*.
    A grant asking a different question is how "gains landwalk of the chosen
    type" comes to work for five types and refuse the other thirteen.
    """
    from ...landwalk import is_landwalk

    return is_landwalk(keyword)


def _check_grantable(keyword: str, node) -> None:
    """Refuse a grant of a keyword the engine cannot actually give.

    Two questions, and both have to be asked here: whether the *ability* is
    implemented at all (`grant_keyword` will put any word into layer 6, and a
    word with no behaviour behind it is a grant of nothing), and whether the
    keyword's printed argument came with it. "Rampage 2" grants +2/+2 per extra
    blocker; a bare "rampage" names no N, so there is nothing to grant — the
    parser leaves the number optional because a *test* for the ability does not
    want it (CR 702.23a defines the ability, the number parameterises it).
    """
    name = keyword_ability_name(keyword)
    if name not in IMPLEMENTED_KEYWORDS and not _is_landwalk(keyword):
        raise LoweringError(
            f"granting {keyword!r} needs the keyword implemented", node=node
        )
    # The bare family name, which only a *removal* prints ("loses all 'bands
    # with other' abilities"). CR 702.22b's ability is the word plus a quality;
    # granting the family alone would put a word into layer 6 that names no set
    # of creatures, so the band it created would be one nothing could join —
    # the grant-of-nothing this function exists to refuse, in the one spelling
    # the keyword registry cannot catch, since the family word is what the
    # registry lists.
    if keyword == BANDS_WITH_OTHER:
        raise LoweringError(
            f"granting {keyword!r} needs the quality the band is with", node=node
        )
    # The same shape one family over. CR 702.14a's landwalk is the word plus a
    # land type, so the bare family word names no land and restricts no block
    # (`landwalk_requirement` answers None for it) — granting it would put a
    # word into layer 6 that does nothing. A *removal* of it is a real thing and
    # is what `expand_ability_removal` reads, which is why the refusal is here
    # and not in the registry.
    if keyword == LANDWALK:
        raise LoweringError(
            f"granting {keyword!r} needs the land type it walks", node=node
        )
    if name in NUMERIC_ARGUMENT_KEYWORDS and keyword == name:
        raise LoweringError(
            f"granting {keyword!r} needs the printed number it takes", node=node
        )


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


def _lower_lose_keyword(
    node: ast.LoseKeyword, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"It loses indestructible until end of turn." (Soul Sear, bound to the
    damage sentence's target by the pronoun rider.)

    The mirror of the targeted grant: `remove_keyword` puts the removal into
    layer 6, so it composes with grants by timestamp rather than by flag
    fights. Gated on IMPLEMENTED_KEYWORDS exactly like the grant — removing a
    word whose behaviour is not built would report a removal of nothing.
    """
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
        # `remove_keyword` writes into layer 6's word set, and a line-derived
        # ability is not in it — the compiler built the ability out of the
        # printed line (CR 702.23a). Removing the word would report a removal
        # and take nothing away, which is the silent half of the same failure
        # `_check_grantable` refuses on the granting side. No card in the pool
        # prints one; the day one does, it needs the removal channel built.
        if keyword_ability_name(keyword) in LINE_DERIVED_KEYWORDS:
            raise LoweringError(
                f"removing {keyword!r} needs a channel that takes an ability "
                "the compiler read off the printed line",
                node=node,
            )
    if node.duration.kind is None:
        # "When this creature blocks, **it loses defender**." (Elder Land
        # Wurm.) Durationless and still not a static ability: it is the one-shot
        # effect of a *triggered* ability, so it happens once and the word is
        # gone for good rather than being a continuous effect the layer system
        # re-derives. `remove_keyword` without the until-end-of-turn flag writes
        # exactly that record into layer 6 — the cleanup sweep drops only the
        # flagged ones — so nothing new is needed under it.
        #
        # Admitted only as a trigger's own effect, which is what keeps the
        # printed *static* line ("Creatures you control lose flying") refusing:
        # that one is a continuous effect over a set the layer system has to
        # re-derive every recompute, and executing it once would take the word
        # away from whatever happened to be on the board at the time.
        if event is None:
            raise LoweringError(
                "a durationless keyword loss outside a trigger is a static "
                "ability, which needs the CR 613 layers engine",
                node=node,
            )
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
    if not _is_target(node.subject):
        raise LoweringError("no handler removes a keyword from this subject", node=node)
    payload: dict[str, object] = {"keywords": tuple(node.keywords)}
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("remove_target_keyword_until_eot", "", payload),)

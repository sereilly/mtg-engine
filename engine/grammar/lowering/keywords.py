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
from .. import ast
from ..errors import LoweringError
from ..vocabulary import IMPLEMENTED_KEYWORDS, NUMERIC_ARGUMENT_KEYWORDS
from ._common import (
    _describe_targets,
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
        reason = _durationless_reason(node.subject)
        if reason.startswith("continuous pump"):
            reason = "continuous keyword grant needs the CR 613 layers engine"
        raise LoweringError(reason, node=node)
    # "…gains forestwalk **until your next upkeep**." (Erhnam Djinn.) Every
    # grant kind below ends at the cleanup step, so lowering this duration onto
    # one would grant the keyword for the rest of the turn and take it away a
    # step early — a card doing less than it prints, silently.
    #
    # The duration became parseable when Xenic Poltergeist needed it, which is
    # the widened-gate hazard in miniature: the phrase used to fail
    # full-token consumption, so `card_hooks.CARD_LINE_INSTRUCTIONS` claimed
    # Erhnam Djinn's line and the upkeep registry expired the grant correctly.
    # Refusing here hands the line back to that hook. Deleting the hook in
    # favour of a general "until your next upkeep" grant is worth doing and is
    # not this round's work — and until it is done, refusing is the only answer
    # that does not quietly shorten the card.
    if node.duration.kind == "until_your_next_upkeep":
        raise LoweringError(
            "no keyword-grant handler expires at the granting player's next upkeep",
            node=node,
        )
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
        and node.subject.filter.controller == "you"
        and node.duration.kind in ("until_end_of_turn", "this_turn")
    ):
        leftover = _restrictions_beyond(
            node.subject.filter, frozenset({"card_types", "controller"})
        )
        if leftover:
            raise LoweringError(
                "the team keyword grant cannot narrow by: " + ", ".join(leftover),
                node=node,
            )
        for keyword in node.keywords:
            _check_grantable(keyword, node)
        team_payload: dict[str, object] = {"keywords": tuple(node.keywords)}
        if not node.subject.filter.card_types:
            team_payload["every_permanent"] = True
        return (OracleInstruction("grant_team_keyword_until_eot", "", team_payload),)
    scope = "self" if _is_source(node.subject) else ("target" if _is_target(node.subject) else None)
    if scope is None:
        raise LoweringError("unsupported keyword-grant subject", node=node)
    if len(node.keywords) == 1:
        kind = _KEYWORD_GRANTS.get((node.keywords[0], scope))
        if kind is not None:
            return (OracleInstruction(kind, "", {}),)
    # Any other grant rides the generic payload pair, gated on the keyword
    # registry: `grant_keyword` puts the word into layer 6 for anything, but a
    # word whose behaviour is not built would be a grant of nothing — the same
    # silent wrongness the printed-keyword gate refuses. Several keywords in
    # one sentence ("gains hexproof and indestructible") are one instruction
    # carrying them all.
    for keyword in node.keywords:
        _check_grantable(keyword, node)
    payload: dict[str, object] = {"keywords": tuple(node.keywords)}
    if scope == "self":
        return (OracleInstruction("grant_self_keyword_until_eot", "", payload),)
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("grant_target_keyword_until_eot", "", payload),)

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
    if name not in IMPLEMENTED_KEYWORDS:
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
    if name in NUMERIC_ARGUMENT_KEYWORDS and keyword == name:
        raise LoweringError(
            f"granting {keyword!r} needs the printed number it takes", node=node
        )


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
        if keyword_ability_name(keyword) not in IMPLEMENTED_KEYWORDS:
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
    if not _is_target(node.subject):
        raise LoweringError("no handler removes a keyword from this subject", node=node)
    payload: dict[str, object] = {"keywords": tuple(node.keywords)}
    assert isinstance(node.subject, ast.TargetSpec)
    _describe_targets(payload, node.subject)
    return (OracleInstruction("remove_target_keyword_until_eot", "", payload),)

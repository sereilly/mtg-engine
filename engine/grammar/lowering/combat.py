"""Lowering combat restrictions (CR 506, 509).

"Can't attack unless …", "can't be blocked by …", and the unblockable grant
whose power limit the handler hardcodes — recorded here as a value so the
lowering can check it rather than assume it.
"""

from ...oracle_types import CHOSEN_THIS_WAY_OBJECTS, OracleInstruction
from ...subject_filters import untestable_filter_keys
from ...turn_state import THAT_PLAYERS_NEXT_TURN
from .. import ast
from ..errors import LoweringError
from ._record_keys import CHOSEN_PLAYER
from ._common import (
    _describe_several_targets, _describe_targets, _filter_payload,
    _is_source, _REST_OF_TURN, RESTRICTION_TURNS,
    _names_several_targets, _restrictions_beyond, refuse_untestable,
)
from ._declaration_costs import lower_declaration_cost
from ._events import (
    _TAPPED_PERMANENTS,
    _UNTAPPED_PERMANENTS,
)







#: Trigger events whose fire site stamps the *blocked* creatures onto the
#: stack item (``blocked_permanent_ids``), so an effect may say "that creature"
#: about the other half of the blocking pair and mean it. The block-pair
#: destroy events (`_BLOCK_PAIR_EVENTS`, lowering/board.py) are a different
#: binding — those push the paired creature as the item's *target* — which is
#: why this is its own set rather than a reuse of that one.
_BLOCKED_SUBJECT_EVENTS = frozenset({"creature_blocks"})




def lower_block_count_grant(node: "ast.BlockCountGrant") -> tuple[OracleInstruction, ...]:
    """"That creature can block up to two additional creatures this turn."
    (Yare.)

    CR 509.1b's ceiling raised for one turn, on **one named creature**: the
    spell's target, the object an earlier sentence bound, or the ability's own
    source ("{W}: This creature can block an additional creature this turn.",
    Mounted Archers). A plural subject is still refused -- a board-wide
    permission no card in this pool prints, and refusing is the direction that
    does not let the whole defending team multi-block.

    The count travels as payload for the reason every printed number in this
    family does, and the duration is checked here rather than trusted: a
    permission whose end nothing sweeps is a permanent one.
    """
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "a block-count permission with no end-of-turn duration is a "
            "static ability",
            node=node,
        )
    if not isinstance(node.subject, ast.TargetSpec) or (
        node.subject.quantifier not in ("target", "that")
        # "this" qualifies on being the ability's own source and not merely on
        # the word: the payload key below says *source*, so a "this" that is
        # anything else would be described by a key the handler reads as one.
        and not _is_source(node.subject)
    ):
        raise LoweringError(
            "no handler grants extra blocks to an untargeted subject", node=node
        )
    payload: dict[str, object] = {"count": node.count}
    if node.subject.quantifier == "target":
        _describe_targets(payload, node.subject)
    # "**This creature** can block an additional creature this turn." (Mounted
    # Archers.) The ability's own source, named by the payload key every other
    # handler in this family reads for it -- so the handler resolves the
    # permanent whose line this is rather than falling through to
    # ``resolve_target_permanent``, whose no-target fallback scans the
    # battlefield and would hand the permission to somebody else's creature.
    elif _is_source(node.subject):
        payload["subject"] = "source"
    # "**That creature** can block up to two additional creatures this turn."
    # (Yare's second sentence.) The bound object the sentence in front of it
    # already targeted, not a second choice — so no ``targets`` description is
    # emitted and the handler acts on the spell's one target, the idiom
    # `lowering/keywords.py` established for the identical pronoun. A bound
    # object carries no narrowing to honour, so a restated adjective refuses
    # rather than being dropped.
    elif _restrictions_beyond(node.subject.filter, frozenset({"card_types"})):
        raise LoweringError(
            '"that creature" carries a narrowing the bound object cannot honour',
            node=node,
        )
    return (
        OracleInstruction("grant_additional_blocks_until_eot", "", payload),
    )


def _lower_combat_restriction(
    node: ast.CombatRestriction, event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """``can't attack unless …`` / ``can't block creatures with power N …``.

    Lowers to the instruction kinds the combat steps already dispatch on, with
    the payloads ``engine/combat_restrictions.py`` produces for the legacy path
    — byte for byte, so the differential can hold the two to agreement rather
    than merely to "both did something".

    *event* is the trigger kind when the restriction is a trigger's effect —
    what "that creature" is allowed to refer back to.
    """
    # "That creature can't attack during its controller's next turn." (Wall of
    # Dust.) A one-shot stamp on the creature the trigger blocked, resolved by
    # the handler from the ids the fire site recorded — so the subject must be
    # the bare back-reference (anything more would be a narrowing nothing
    # tests), and the event must be one whose fire site records those ids: on
    # any other trigger the handler would find nothing and the card would
    # compile clean while restricting nobody.
    if node.kind == "cant_attack_during_controllers_next_turn":
        subject = node.subject
        if (
            not isinstance(subject, ast.TargetSpec)
            or subject.quantifier != "that"
            or subject.filter != ast.ObjectFilter(card_types=("creature",))
        ):
            raise LoweringError(
                "the next-turn attack restriction reads the creature its "
                "trigger already named",
                node=node,
            )
        if event not in _BLOCKED_SUBJECT_EVENTS:
            raise LoweringError(
                "only a blocks trigger records which creature 'that creature' "
                "was",
                node=node,
            )
        return (
            OracleInstruction("cant_attack_during_controllers_next_turn", "", {}),
        )
    # "Creatures without flying can't block this turn." (Destructive
    # Tampering's second mode) — a one-shot, turn-scoped blanket over the
    # subject, not a property of a permanent: the payload carries the filter
    # the blocker gate tests, and cleanup sweeps the state it arms. The gate
    # tests card types and (without-)keywords; any other narrowing refuses
    # rather than being dropped.
    # "Creatures can't attack this turn." (Festival.) The attack twin of the
    # blanket can't-block below, and the same three gates for the same reasons:
    # a duration, a plural subject, and a filter the enforcing gate can test.
    # The gate here is `declare_attackers_step.can_attack`, which tests a filter
    # payload through `subject_matches` — so what it may carry is wider than the
    # blocker gate's three keys, and is held to `TESTABLE_SUBJECT_FILTER_KEYS`
    # for the reason that set exists: a narrowing the matcher cannot test would
    # ground creatures the card never named.
    # "This creature can't attack or block alone." (Mogg Flunkies.) CR 506.5
    # and CR 509.1b's "alone" is a floor of one on the declaration this
    # creature joins, which is exactly what ``declaration_company_required``
    # already reads for Orcish Conscripts' printed count — so the three
    # spellings lower to those two kinds and add no enforcement site. The
    # compound returns *both*, over one subject read once, for the reason
    # ``CombatRestriction.also_kinds`` exists on the text-table side: two rows
    # reading one sentence could come to disagree about who it restricts.
    if node.kind in ("cant_attack_alone", "cant_block_alone",
                     "cant_attack_or_block_alone"):
        if not _is_source(node.subject):
            # Both kinds are read off the creature's *own* compiled program at
            # the declaration (`declaration_company_required` takes one
            # permanent), so a sentence about a described set has nowhere to be
            # enforced and would be dropped rather than applied.
            raise LoweringError(
                "the alone restriction is read off the creature that prints it",
                node=node,
            )
        emitted: list[OracleInstruction] = []
        if node.kind != "cant_block_alone":
            emitted.append(
                OracleInstruction(
                    "cant_attack_unless_others_attack", "", {"count": 1}
                )
            )
        if node.kind != "cant_attack_alone":
            emitted.append(
                OracleInstruction(
                    "cant_block_unless_others_block", "", {"count": 1}
                )
            )
        return tuple(emitted)
    if node.kind == "cant_attack_until_eot":
        payload = dict(node.payload)
        # "**Target creature** can't attack this turn." (Change of Heart.) The
        # exact mirror of the blanket can't-block's targeted branch below, and
        # its own kind for that branch's reason: the blanket arms a board-wide
        # filter the attack gate tests, where this marks the one permanent the
        # spell chose, and folding them would ground every creature the noun
        # phrase describes — which on "target creature" is the whole board.
        #
        # Read before the plural gate rather than after it: the sentence is one
        # printed template with two subjects, and refusing the singular one on
        # "reads a plural subject" is the refusal Stronghold's census carried
        # for a card whose sentence the engine can enforce end to end.
        if (
            isinstance(node.subject, ast.TargetSpec)
            and node.subject.quantifier == "target"
        ):
            if payload.get("duration") not in _REST_OF_TURN:
                # Checked rather than defaulted, exactly as the blanket does:
                # the mark is swept by the cleanup step, so a restriction with
                # any other window would end at the wrong time or never.
                raise LoweringError(
                    "a targeted can't-attack with no end-of-turn duration has "
                    "nothing to sweep it",
                    node=node,
                )
            targeted_attack: dict[str, object] = {}
            _describe_targets(targeted_attack, node.subject)
            return (
                OracleInstruction(
                    "target_cant_attack_until_eot", "", targeted_attack
                ),
            )
        if not isinstance(node.subject, ast.TargetSpec) or (
            node.subject.quantifier not in ("all", "each")
        ):
            raise LoweringError(
                "the blanket can't-attack reads a plural subject", node=node
            )
        described = _filter_payload(node.subject.filter)
        untestable = untestable_filter_keys(described)
        if untestable:
            raise LoweringError(
                "the attack gate cannot test this restriction: "
                + ", ".join(sorted(untestable)),
                node=node,
            )
        duration = payload.get("duration")
        # No duration at all: "Creatures without flying can't attack." (Moat.)
        # A **static** ability of the permanent printing it, which is a
        # different rule from the one-shot above — it is re-derived from the
        # board at every declaration and ends when its source leaves, with
        # nothing to sweep. `engine/combat_restrictions.py` has implemented it
        # since Moat arrived, and this produces that table's instruction and
        # payload exactly, which `test_grammar_derived_lines` compares over the
        # whole pool.
        if duration is None:
            return (
                OracleInstruction(
                    "creatures_cant_attack", "", {"subject": described}
                ),
            )
        # "**During that player's next turn**, … and other creatures can't
        # attack." (Oracle en-Vec.) A window that opens on a turn nobody is
        # taking yet, so it cannot be a count of cleanup steps — one subtracted
        # from it would end the restriction before it ever applied. The entry
        # carries the window by name and the handler turns it into a seat-turn
        # stamp; ``phases/cleanup_step`` drops it once that turn has passed.
        if duration == THAT_PLAYERS_NEXT_TURN:
            if CHOSEN_THIS_WAY_OBJECTS not in produced:
                raise LoweringError(
                    "no step of this effect chose the creatures this window "
                    "spares",
                    node=node,
                )
            if CHOSEN_PLAYER not in produced:
                raise LoweringError(
                    "no step of this effect named the player whose turn this is",
                    node=node,
                )
            # "**Other** creatures can't attack." The word is read by the noun
            # parser as "other than this creature", which is what it means on a
            # permanent's own static — and not what it means here, where the
            # sentence in front named a set. Lifted out of the filter into the
            # exclusion the gate answers, exactly as the choose family lifts
            # "that player" out of a controller: left inside it the restriction
            # would ground the chosen creatures too, which is the whole card.
            if not described.pop("exclude_self", False):
                raise LoweringError(
                    "this window's restriction is the complement of the set "
                    "an earlier step chose",
                    node=node,
                )
            return (
                OracleInstruction(
                    "cant_attack_until_eot", "",
                    {
                        "filter": described,
                        "window": THAT_PLAYERS_NEXT_TURN,
                        "except_from": CHOSEN_THIS_WAY_OBJECTS,
                    },
                ),
            )
        # "This turn **and next turn**" (Peace Talks). The same one-shot
        # restriction over a longer window, and the window is a count of
        # cleanup steps rather than a second kind: the sweep decrements it, so
        # a printed "this turn and the next two turns" would be a row in
        # `_common.RESTRICTION_TURNS` and nothing else.
        turns = RESTRICTION_TURNS.get(str(duration))
        if turns is None:
            raise LoweringError(
                "a blanket can't-attack with no end-of-turn duration is a "
                "static ability",
                node=node,
            )
        armed: dict[str, object] = {"filter": described}
        if turns != 1:
            armed["remaining_turns"] = turns
        return (
            OracleInstruction("cant_attack_until_eot", "", armed),
        )
    # CR 508.1g / CR 509.1d: what a declaration *costs*, as against the
    # restrictions this function answers. One question asked once, in
    # ``_declaration_costs`` — the floor those four branches moved to when the
    # two mana tolls took this module past the size guard. It answers None for
    # every kind it does not own, so the branches below keep their reading.
    declaration_cost = lower_declaration_cost(node)
    if declaration_cost is not None:
        return declaration_cost
    # "…unless defending player controls an Island" (Sea Serpent) / "…if
    # defending player controls an untapped creature with power 3 or greater"
    # (Goblin Mutant). One kind, one payload: the printed noun phrase and the
    # polarity. It was five basic land *words* welded into a `land_type`
    # string, because the enforcing check scanned the defender's lands by name —
    # so a card naming any other kind of permanent had nowhere to go, and this
    # production refused a phrase the noun parser reads perfectly well.
    #
    # The land scoping the old check spelled out is CR 205.3i's, not this
    # payload's: a land subtype can only be on a land, so "an Island" describes
    # a land whether or not the word is repeated.
    if node.kind == "cant_attack_unless_defender_controls":
        payload = dict(node.payload)
        if not _is_source(node.subject):
            raise LoweringError(
                "the defender-board restriction is read off the creature it "
                "restricts",
                node=node,
            )
        described = _filter_payload(payload["subject"])
        # Idiom 2: the gate tests the phrase with `subject_matches`, so a key
        # that matcher cannot answer would be carried and ignored — and ignoring
        # a narrowing *lifts* the restriction (every board satisfies "controls
        # something"), which is the widening direction.
        untestable = untestable_filter_keys(described)
        if untestable or not described:
            raise LoweringError(
                "the attack gate cannot test what the defender controls: "
                + (", ".join(sorted(untestable)) or "nothing was described"),
                node=node,
            )
        return (
            OracleInstruction(
                "cant_attack_unless_defender_controls", "",
                {"subject": described, "required": bool(payload["required"])},
            ),
        )
    # "This creature can't attack unless **a black or green creature** also
    # attacks." (Scarred Puma.) The companion's noun phrase as the filter the
    # declaration gate tests against each *other* declared attacker. Held to
    # what ``subject_matches`` can answer for the usual reason, sharper here
    # than usual: a narrowing the gate ignored would let any second attacker
    # escort the Puma, which is the restriction quietly lifted.
    if node.kind == "cant_attack_unless_subject_attacks":
        if not _is_source(node.subject):
            # Read off the creature's own compiled program at the declaration
            # (``declaration_companion_required`` takes one permanent), so a
            # sentence about a described set has nowhere to be enforced.
            raise LoweringError(
                "the escort restriction is read off the creature that prints it",
                node=node,
            )
        described = _filter_payload(dict(node.payload)["companion"])
        untestable = untestable_filter_keys(described)
        if untestable or not described:
            raise LoweringError(
                "the attack gate cannot test the creature that must also "
                "attack: "
                + (", ".join(sorted(untestable)) or "nothing was described"),
                node=node,
            )
        return (
            OracleInstruction(
                "cant_attack_unless_subject_attacks", "", {"companion": described}
            ),
        )
    # "This creature can't block white creatures with power 2 or greater."
    # (Orcish Veteran.) The printed noun phrase as the filter list the
    # enforcement site tests against the *attacker*, byte for byte the payload
    # `engine/combat_restrictions.py` builds for the same sentence — a list
    # because the union spelling ("Walls and/or creatures with flying") is the
    # same reader on the other side, and one shape is what keeps the two
    # producers comparable.
    if node.kind == "cant_block_subject":
        from ...subject_filters import unimplemented_filter_keywords

        described = _filter_payload(dict(node.payload)["blockees"])
        # A keyword no behaviour is registered under makes the filter inert, not
        # unreadable — `Game._has_keyword` answers no for every creature — so the
        # restriction would forbid nothing while the card reported supported.
        # The same check `engine/combat_restrictions.py` makes of the same
        # sentence, through the same reader.
        inert = unimplemented_filter_keywords(described)
        if inert:
            raise LoweringError(
                "the blocker gate cannot answer this keyword: "
                + ", ".join(sorted(inert)),
                node=node,
            )
        untestable = untestable_filter_keys(described)
        if untestable or not described:
            # Idiom 2: the gate tests the phrase with `subject_matches`, and an
            # untestable key would be carried and ignored — which for a *block*
            # restriction is the widening direction, a creature that may block
            # attackers the card forbids it.
            raise LoweringError(
                "the blocker gate cannot test what this creature can't block: "
                + (", ".join(sorted(untestable)) or "nothing was described"),
                node=node,
            )
        if not _is_source(node.subject):
            # "**Blue creatures** can't block creatures you control." (Heat
            # Wave.) The same printed sentence about a described *set* of
            # blockers rather than about the permanent carrying it, which makes
            # it a board restriction (CR 509.1b) rather than one read off a
            # creature's own program: the source is an enchantment nobody is
            # blocking, and the blocker gate has to find it by scanning.
            #
            # Its own kind for that reason. The payload the branch above builds
            # carries only what may not be blocked, because *who* is restricted
            # is the permanent the instruction was read from; here that is a
            # second noun phrase, and a kind sharing the payload would let the
            # scan read a Heat Wave as an Ironclaw Orcs and forbid every block
            # on the table.
            if (
                not isinstance(node.subject, ast.TargetSpec)
                or node.subject.quantifier != "all"
                or node.subject.targeted
            ):
                raise LoweringError(
                    "this block restriction is read off the creature it "
                    "restricts, or off a described set",
                    node=node,
                )
            subject = _filter_payload(node.subject.filter)
            subject_inert = unimplemented_filter_keywords(subject)
            if subject_inert:
                raise LoweringError(
                    "the blocker gate cannot answer this keyword: "
                    + ", ".join(sorted(subject_inert)),
                    node=node,
                )
            subject_untestable = untestable_filter_keys(subject)
            if subject_untestable or not subject:
                raise LoweringError(
                    "the blocker gate cannot test which creatures are "
                    "restricted: "
                    + (
                        ", ".join(sorted(subject_untestable))
                        or "nothing was described"
                    ),
                    node=node,
                )
            return (
                OracleInstruction(
                    "subject_cant_block_subject", "",
                    {"subject": subject, "blockee_filters": [described]},
                ),
            )
        return (
            OracleInstruction(
                "cant_block_subject", "", {"blockee_filters": [described]}
            ),
        )
    # "Target creature can't block this creature this turn." (Duct Crawler.)
    # CR 509.1b's denial aimed at one *named attacker*, which makes it the
    # mirror of Trumpeting Armodon's requirement rather than of the blanket:
    # both halves of the pair are printed, and a lowering that dropped the
    # attacker would forbid the creature from blocking anything at all.
    if node.kind == "cant_block_named_attacker_until_eot":
        payload = dict(node.payload)
        if payload.get("duration") not in _REST_OF_TURN:
            raise LoweringError(
                "a named-attacker block denial with no end-of-turn duration "
                "has nothing to sweep it",
                node=node,
            )
        attacker = payload.get("attacker")
        if not (isinstance(attacker, ast.TargetSpec) and _is_source(attacker)):
            # The handler records the attacker by ``permanent_id`` off the
            # ability's own source. Any other referent has nothing to resolve
            # against at resolution, and a denial that recorded no id would be
            # a "can't block at all" the card does not print.
            raise LoweringError(
                "the attacker this creature may not block is the ability's "
                "own source",
                node=node,
            )
        if not (
            isinstance(node.subject, ast.TargetSpec) and node.subject.targeted
        ):
            raise LoweringError(
                "the named-attacker block denial marks the creature the "
                "ability chose",
                node=node,
            )
        if _names_several_targets(node.subject):
            raise LoweringError(
                "the block denial marks one creature; nothing here collects "
                "several",
                node=node,
            )
        denied: dict[str, object] = {}
        _describe_targets(denied, node.subject)
        return (
            OracleInstruction(
                "target_cant_block_source_until_eot", "", denied
            ),
        )
    if node.kind == "cant_block_until_eot":
        payload = dict(node.payload)
        if payload.get("duration") not in _REST_OF_TURN:
            raise LoweringError(
                "a blanket can't-block with no end-of-turn duration is a "
                "static ability",
                node=node,
            )
        if not isinstance(node.subject, ast.TargetSpec):
            raise LoweringError(
                "the blanket can't-block reads a plural subject", node=node
            )
        # "**Target creature** can't block this turn." (Panic.) The same printed
        # sentence about one chosen creature rather than a described set, and a
        # different effect for it: the blanket arms a board-wide filter the
        # blocker gate tests, where this marks the one permanent the spell
        # chose. Two kinds, because the dispatch really is different — folding
        # them would make a targeted restriction reach every creature the noun
        # phrase describes, which on "target creature" is all of them.
        if node.subject.quantifier == "target":
            targeted: dict[str, object] = {}
            _describe_targets(targeted, node.subject)
            return (
                OracleInstruction("target_cant_block_until_eot", "", targeted),
            )
        # "**Up to three target creatures** can't block this turn." (Panic
        # Attack.) The row above over a list of chosen creatures (CR 601.2c),
        # and the same kind: its handler resolves the list strictly when the
        # description says several, exactly as ``grant_unblockable_to_target``
        # — its mirror — does for Runed Arch.
        if _names_several_targets(node.subject):
            several: dict[str, object] = {}
            _describe_several_targets(several, node.subject)
            return (
                OracleInstruction("target_cant_block_until_eot", "", several),
            )
        if node.subject.quantifier != "all":
            raise LoweringError(
                "the blanket can't-block reads a plural subject", node=node
            )
        filt = node.subject.filter
        leftover = _restrictions_beyond(
            filt, frozenset({"card_types", "with_keywords", "without_keywords"})
        )
        if leftover:
            raise LoweringError(
                "the blocker gate cannot test this restriction: " + ", ".join(leftover),
                node=node,
            )
        return (
            OracleInstruction(
                "cant_block_until_eot", "",
                {
                    "filter": {
                        "type_filter": filt.card_types[0] if filt.card_types else "creature",
                        "with_keywords": list(filt.with_keywords),
                        "without_keywords": list(filt.without_keywords),
                    }
                },
            ),
        )
    return (OracleInstruction(node.kind, "", dict(node.payload)),)


def _lower_become_blocked(
    node: "ast.BecomeBlocked",
) -> tuple[OracleInstruction, ...]:
    """"Target unblocked attacking creature becomes blocked." (Dazzling Beauty;
    CR 509.1h.)

    A chosen target, unlike its neighbour below: the sentence names the creature
    itself rather than borrowing one an earlier step recorded, so the target
    description is carried and the handler resolves it. The printed narrowing
    ("unblocked", "attacking") travels in that description — a card is what its
    noun phrase says, and dropping the two adjectives would let this be cast on
    a creature that is not in combat at all.
    """
    subject = node.subject
    # "**Attacking creatures** become blocked." (Fog Patch.) The untargeted
    # plural of the same sentence: every creature the noun phrase describes,
    # chosen by nobody, so the description travels as the ordinary filter
    # payload ``subject_matches`` tests and no ``targets`` description is built
    # — which is what keeps the picker from asking for one.
    #
    # Two gates, each a way the sentence could otherwise mean more than it says.
    # The phrase must be testable (a narrowing the matcher drops is a sweep over
    # strictly more creatures than printed), and it must say *attacking*:
    # CR 509.1h is about attacking creatures, and a sweep without the word would
    # mark every creature on the table as a blocked attacker.
    if (
        isinstance(subject, ast.TargetSpec)
        and not subject.targeted
        and subject.quantifier in ("all", "each")
    ):
        described = refuse_untestable(
            _filter_payload(subject.filter),
            refusal="a becomes-blocked sweep cannot narrow by",
            node=node,
        )
        if not described.get("attacking_only"):
            raise LoweringError(
                "only an attacking creature can become blocked (CR 509.1h)",
                node=node,
            )
        return (OracleInstruction("become_blocked", "", {"subject": described}),)
    if not isinstance(subject, ast.TargetSpec) or not subject.targeted:
        raise LoweringError(
            "becoming blocked is a change to a creature the spell targets",
            node=node,
        )
    payload: dict[str, object] = {}
    # "**X target attacking creatures** become blocked. Choking Vines deals 1
    # damage to each of those creatures." The plural of the same sentence, so
    # it is the same instruction with the several-targets description rather
    # than a kind of its own — the description is what tells the picker to
    # collect X and the handler to resolve a list.
    #
    # Opted into here rather than admitted by the ordinary description, which is
    # that description's whole safety: a handler resolving one permanent must
    # never be handed a several-target picker, because every choice after the
    # first would be collected and dropped.
    if _names_several_targets(subject):
        _describe_several_targets(payload, subject)
    else:
        _describe_targets(payload, subject)
    return (OracleInstruction("become_blocked", "", payload),)


def _lower_remove_from_combat(
    node: ast.RemoveFromCombat, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"Untap target attacking creature **and remove it from combat**."
    (Disharmony) / "…tap the creature, remove it from combat…" (Imprison).
    CR 506.4c.

    Two refusals, each a way the sentence could otherwise mean more than it
    says — the discipline ``_lower_doesnt_untap_next_step`` states:

    * The subject must be the pronoun "it": the pool prints this sentence only
      as the tail of a conjunction whose head chose the object. A chosen
      target here would be a second, independent choice the card never
      offered (False Orders makes one, and stays a name-keyed hook).
    * A producer must have recorded which permanent that was — whichever of
      the two spellings wrote it, since a tap and an untap both record what
      they affected. The handler reads ids out of the resolution scratchpad,
      and with nothing recorded it would remove nothing while the card
      compiled clean.
    """
    subject = node.subject
    # "**Remove target attacking creature you control from combat** and untap
    # it." (Reconnaissance.) The other half of the sentence above: here the
    # removal is the step that *chooses*, and the pronoun behind it is the one
    # that reads. So a targeted subject is admitted — the picker falls out of
    # the ``targets`` description, exactly as it does for every other targeted
    # instruction — and the removal records what it took out of combat under
    # ``REMOVED_FROM_COMBAT_PERMANENTS`` for the untap behind it.
    #
    # One target only. Nothing in the pool prints a removal of several, and
    # ``_names_several_targets`` is the opt-in a handler that resolves a list
    # would need: routed here without one, every choice after the first would
    # be collected and dropped.
    if isinstance(subject, ast.TargetSpec) and subject.targeted:
        if _names_several_targets(subject):
            raise LoweringError(
                "the combat removal takes one creature; nothing here collects "
                "several",
                node=node,
            )
        described = refuse_untestable(
            _filter_payload(subject.filter),
            refusal=(
                "the combat removal is enforced against the chosen permanent, "
                "so a narrowing the matcher cannot test would be dropped and "
                "the picker would offer permanents the card never names"
            ),
            node=node,
        )
        payload: dict[str, object] = dict(described)
        payload["frees_blocked_attackers"] = node.frees_blocked_attackers
        _describe_targets(payload, subject)
        return (OracleInstruction("remove_from_combat", "", payload),)
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "it":
        raise LoweringError(
            "remove-from-combat acts on the object the sentence already chose",
            node=node,
        )
    # **Whichever record the step in front of it wrote.** Disharmony untaps its
    # creature and Imprison taps its own; both sentences then say "remove it
    # from combat", and "it" is what that step affected either way. Asked of
    # `_RECORDED_PERMANENTS` — the keys that hold permanents by id — rather than
    # of one spelling, because naming one producer here would refuse the other
    # card for saying "tap" where this one said "untap".
    source = next(
        (key for key in (_UNTAPPED_PERMANENTS, _TAPPED_PERMANENTS) if key in produced),
        None,
    )
    if source is None:
        raise LoweringError(
            "back-reference to a permanent this effect recorded, with no "
            "producer in this effect",
            node=node,
        )
    return (
        OracleInstruction(
            "remove_from_combat", "",
            {
                "permanents_from": source,
                # The printed "…and creatures it was blocking … become
                # unblocked" (Imprison). CR 509.1h is the default and this is
                # the sentence that overrides it, so the *card* decides rather
                # than the removal.
                "frees_blocked_attackers": node.frees_blocked_attackers,
            },
        ),
    )


def _lower_attack_as_though(node: ast.AttackAsThough) -> tuple[OracleInstruction, ...]:
    """"…can attack this turn as though it didn't have defender."
    (Wall of Wonder.)

    Refuses on two axes, both by name. The **ignored ability** must be one the
    declare-attackers step actually asks about: defender is the only keyword
    that stops an attack by itself, so a permission naming any other word would
    be a clause the engine consumed and nothing acted on. The **duration** must
    be this turn's, because the permission is recorded on the permanent and
    swept by the cleanup step — a durationless printing is the Aura's static
    ability (``engine/auras.py``), which is derived while it is attached rather
    than stamped.
    """
    if node.ignored_keyword != "defender":
        raise LoweringError(
            f"no attack permission ignores {node.ignored_keyword!r}", node=node
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError(
            "a durationless attack permission is a static ability, which the "
            "Aura derivation owns rather than an instruction",
            node=node,
        )
    if not _is_source(node.subject):
        raise LoweringError(
            "no handler grants an attack permission to this subject", node=node
        )
    return (OracleInstruction("attack_as_though_no_defender_until_eot", "", {}),)


def _lower_attacking_doesnt_tap(
    node: ast.AttackingDoesntTap,
) -> tuple[OracleInstruction, ...]:
    """"Attacking doesn't cause creatures you control to tap this combat if
    Johan is untapped." (Johan; CR 508.1f.)

    Two noun phrases, both payload. **Which creatures** the exemption reaches is
    the sentence's subject; **what must stay true** for it to apply is the
    trailing "if …", which is read as a noun phrase about the effect's own
    source rather than as a condition evaluated once. That difference is the
    card: Johan's creatures attack untapped only while Johan himself is
    untapped, so a condition tested at resolution and then forgotten would keep
    the exemption running after he attacked.

    Both are held to ``TESTABLE_SUBJECT_FILTER_KEYS``, the same gate every other
    printed noun phrase passes: a narrowing the matcher cannot test is one the
    declare-attackers step would silently ignore, and an exemption that reaches
    a *wider* set than the card prints is the one failure a combat rule must
    never have.
    """
    subject = node.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier not in ("all", "each"):
        raise LoweringError(
            "an attack-tap exemption names a set of creatures, not one of them",
            node=node,
        )
    if subject.targeted:
        raise LoweringError("an attack-tap exemption does not target", node=node)
    described = subject.filter.to_payload()
    refuse_untestable(
        described,
        refusal="the attack-tap exemption cannot narrow by",
        node=node,
    )
    payload: dict[str, object] = {"filter": described}
    if node.gate_state is not None:
        payload["gate_filter"] = _attack_tap_gate_filter(node)
    return (OracleInstruction("exempt_from_attack_tapping", "", payload),)


def _attack_tap_gate_filter(node: ast.AttackingDoesntTap) -> dict[str, object]:
    """The trailing "if …" as a noun phrase tested against the effect's source.

    "If Johan is untapped" says the same thing as the adjective in "untapped
    creature you control", so it lowers to the same filter key and is answered
    by the same matcher — which is what lets the declare-attackers step ask it
    again at every declaration instead of once at resolution. A state the filter
    has no field for refuses by name rather than being dropped.
    """
    try:
        probe = ast.ObjectFilter(**{node.gate_state: not node.gate_negated})
    except TypeError:
        raise LoweringError(
            f"no permanent filter describes {node.gate_state!r}", node=node
        ) from None
    described = probe.to_payload()
    if not described or untestable_filter_keys(described):
        raise LoweringError(
            f"no testable filter says {'not ' if node.gate_negated else ''}"
            f"{node.gate_state!r} of a permanent",
            node=node,
        )
    return described


def _lower_choose_blocks_for_defenders(
    node: ast.ChooseBlocksForDefenders,
) -> tuple[OracleInstruction, ...]:
    """"You choose which creatures block this combat and how those creatures
    block." (Melee.) CR 509.1a's chooser, substituted for this combat.

    Refuses the turn-scoped printing ("this turn", Master Warcraft): the
    substitution is *combat*-scoped state, cleared when the combat phase begins
    and again when it ends, and a turn-scoped one would either have to survive
    that reset or quietly stop applying at the second combat of a turn. Neither
    is what the words say, so the card refuses naming its clause rather than
    working for one combat out of two.
    """
    if node.duration.kind != "until_end_of_combat":
        raise LoweringError(
            "a block-chooser substitution is combat-scoped; nothing carries "
            "one across a combat boundary",
            node=node,
        )
    return (OracleInstruction("choose_blocks_for_defenders", "", {}),)


def _lower_reassign_blockers_between_attackers(
    node: ast.ReassignBlockersBetweenAttackers,
) -> tuple[OracleInstruction, ...]:
    """"Choose two target blocked attacking creatures. If each of those
    creatures could be blocked by all creatures that the other is blocked by,
    …" (General Jarkeld.)

    Two targets of one kind, so the description is the homogeneous one rather
    than Sorrow's Path's ordered roles: neither slot's legal set depends on what
    was chosen for the other. The *relation* between them is a condition the
    handler checks at resolution (CR 608.2b), not a narrowing the picker could
    apply — "could be blocked by all creatures that the other is blocked by" is
    a question about a pair, and a picker that tried to enforce it would have to
    answer it before the pair existed.

    Both printed narrowings are carried and both are testable
    (``TESTABLE_SUBJECT_FILTER_KEYS``): an attacker that is not blocked has no
    blockers to hand over, and one that is not attacking is not in this combat
    at all. A narrowing the matcher could not test would be a restriction the
    dispatcher then ignored, which is the wider-than-printed reading this file
    refuses everywhere.
    """
    subject = node.subject
    if not _names_several_targets(subject) or subject.count != 2:
        raise LoweringError(
            "this reassignment is announced with exactly two chosen attackers",
            node=node,
        )
    filter_payload = _filter_payload(subject.filter)
    untestable = untestable_filter_keys(filter_payload)
    if untestable:
        raise LoweringError(
            f"nothing tests {sorted(untestable)!r} on a chosen attacker",
            node=node,
        )
    if not (filter_payload.get("attacking_only") and filter_payload.get("blocked_only")):
        raise LoweringError(
            "the reassignment moves blockers between *blocked attacking* "
            "creatures; a wider phrase would move blockers off creatures the "
            "sentence never named",
            node=node,
        )
    payload: dict[str, object] = dict(filter_payload)
    _describe_several_targets(payload, subject)
    return (
        OracleInstruction("reassign_blockers_between_attackers", "", payload),
    )


"""Lowering CR 614.9's damage redirections.

Split out of ``damage`` at the thousand-line guard — twice over in one round,
independently, by two branches that each hit the cap on the same module and cut
it in the same place. Along the line the CR already draws: CR 120 is a source
dealing damage, CR 614.9 is a **replacement effect** that changes who it is
dealt *to*. The damage is still dealt, in full, by the same source, and only
its recipient changes — which is why ``ast/damage.py`` gives it a node of its
own, and why a redirect read as a shield would lose lifelink, the damage
triggers and the dealt-damage records all at once.

The parse side keeps redirection with damage (``effects/damage.py``), because
the two read the same recipient, source and duration vocabulary; the lowering
halves share nothing but the generic helpers every family here uses. That is
the same asymmetry ``prevention`` records one module over — a lowering half
that outgrew its parse half. See ``tests/engine/test_grammar_layering.py``.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (
    _REST_OF_TURN,
    _describe_targets,
    _filter_payload,
    _is_source,
    _is_target,
    _is_you,
    _restrictions_beyond,
    _targets_payload,
)


#: The key a Nova Pentacle-shaped redirect writes its opponent's pick under, and
#: the key the redirect step behind it reads. Named once because the two halves
#: are two instructions and a literal in each is how they come to disagree.
_REDIRECT_RECIPIENT_KEY = "redirect_recipient"


def _lower_redirect_damage(node: ast.RedirectDamage) -> tuple[OracleInstruction, ...]:
    """CR 614.9 — "…is dealt to <recipient> instead."

    Two instructions, and the difference between them is not the effect but how
    the moved damage's *source* is named: the ability either targets it (Shimian
    Night Stalker's "by target attacking creature") or the player chooses it as
    the ability is activated (Nova Pentacle's "a source of your choice"). That is
    the axis ``engine/targeting.py``'s kind→spec table keys on — one picker runs
    over the battlefield's attackers and the other over every source including
    the stack — so it cannot be payload under one kind, exactly as
    ``prevent_damage_by_target_until_eot`` and ``grant_reverse_damage_shield``
    are two kinds for the two ways a shield names its source.

    Everything else *is* payload, and every refusal below is a way this sentence
    could otherwise mean more than it says:

    * the protected recipient must be **you**. The record is armed on the
      ability's controller; there is no handler that arms one on a chosen
      player, and Reverberation — which names no protected recipient at all, so
      its redirect covers everyone the spell would damage — refuses here.
    * a source must be *named*. With neither a target nor a chosen source this
      would move **all** damage to the new recipient, which is a strictly larger
      effect than any of these cards prints.
    * the duration must be this turn, because that is what the sweeps give it.
    * the new recipient must be this permanent, or a creature an opponent picks.
      A redirect whose recipient the engine cannot resolve would arm a record
      pointing at nothing, and CR 614.9 makes that a redirect that silently does
      nothing at all.
    """
    if node.optional:
        return _lower_optional_class_redirect(node)
    if node.to is None:
        # "All damage that would be dealt this turn **by target sorcery spell**
        # is dealt to that spell's controller instead." (Reverberation.) The one
        # printed shape with no protected recipient: it names only the source,
        # so it moves whatever that spell would deal, to whoever it would have
        # damaged.
        return _lower_spell_damage_redirect(node)
    if not _is_you(node.to):
        raise LoweringError(
            "a redirect is armed on its controller; no handler protects "
            "another recipient",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    payload: dict[str, object] = {"to_self": True}
    if node.one_shot:
        # "**The next time** a source …" — one instance, not every one.
        payload["uses"] = 1
    recipient = node.new_recipient
    if _is_source(recipient):
        # "…is dealt to **this creature** instead." The permanent the ability is
        # on, which the handler already has and nothing needs to choose.
        payload["new_recipient"] = "source"
    elif (
        isinstance(recipient, ast.TargetSpec)
        and recipient.quantifier == "target"
        and node.chooser is not None
    ):
        # "…to **target creature of an opponent's choice**". The pick is the
        # other seat's, so it is made through the general permanent prompt as
        # the ability resolves and read back out of the resolution's results —
        # the same course Cuombajj Witches' opposing target takes, and for the
        # same reason: the picker in front of an activation is the activating
        # player's.
        payload["new_recipient"] = "chosen"
        payload["result_key"] = _REDIRECT_RECIPIENT_KEY
    else:
        raise LoweringError(
            "no handler resolves this redirect's new recipient", node=node
        )
    # "…by **unblocked creatures** this turn" (Kjeldoran Royal Guard). A printed
    # *class* of sources rather than one chosen object, which is why it is its
    # own instruction: every branch below hands the handler an object to match
    # by identity, and a class has none — it is re-asked of each source when the
    # damage would be dealt (CR 614.9 does not fix the set when the ability
    # resolves), so a creature that becomes unblocked afterwards is covered.
    spec = node.dealt_by
    if (
        isinstance(spec, ast.TargetSpec)
        and not spec.targeted
        and spec.quantifier in ("all", "each")
    ):
        return _lower_source_class_redirect(node, spec)
    if node.combat_only:
        # The printed word is honoured by exactly one lowering. Every record
        # below moves damage of any kind, so a "combat" that reached one would
        # be dropped — and a redirect wider than the card prints is the silent
        # direction.
        raise LoweringError(
            "only the source-class redirect is scoped to combat damage", node=node
        )
    if node.from_chosen_source:
        if node.dealt_by is not None:
            raise LoweringError(
                "a redirect names its source once: either a chosen source or a "
                "target",
                node=node,
            )
        instructions: tuple[OracleInstruction, ...] = (
            OracleInstruction(
                "redirect_damage_from_chosen_source_until_eot", "", payload
            ),
        )
    else:
        spec = node.dealt_by
        if not isinstance(spec, ast.TargetSpec) or spec.quantifier != "target":
            raise LoweringError(
                "no handler redirects the damage of a source the sentence does "
                "not choose",
                node=node,
            )
        _describe_targets(payload, spec)
        instructions = (
            OracleInstruction("redirect_damage_from_target_until_eot", "", payload),
        )
    if payload.get("new_recipient") == "chosen":
        # The prompt runs first and the redirect reads its answer, so the two are
        # a sequence in printed order rather than one fused instruction.
        return (
            OracleInstruction(
                "choose_permanent", "",
                {
                    "result_key": _REDIRECT_RECIPIENT_KEY,
                    "filter": _filter_payload(recipient.filter),
                    "chooser": "opponent",
                    "prompt": "Choose a creature to take the redirected damage.",
                },
            ),
        ) + instructions
    return instructions


def _lower_source_class_redirect(
    node: ast.RedirectDamage, spec: ast.TargetSpec
) -> tuple[OracleInstruction, ...]:
    """Kjeldoran Royal Guard: "{T}: All combat damage that would be dealt to you
    by unblocked creatures this turn is dealt to this creature instead."

    Veteran Bodyguard's sentence with a duration on it, which is the whole
    reason it is a *record* rather than the static
    ``engine/replacements.py`` derives off the printed line: that one is asked
    of the board on every damage event and is true exactly while the creature is
    untapped, and this one is armed once and lasts the turn whatever happens to
    the Guard afterwards.

    Four refusals, each a way the sentence could otherwise mean more than it
    says:

    * the damage must move onto the permanent whose ability this is. There is no
      handler that arms a class-scoped record pointing at a chosen object, and
      one that pointed nowhere would be a redirect that silently does nothing.
    * the class must describe *something*. An empty filter is no narrowing at
      all, so it would move every point of damage the player would be dealt.
    * every key of the phrase must be one ``subject_matches`` can test, because
      a narrowing the matcher cannot answer is dropped when the damage is dealt
      — a record strictly wider than the card prints.
    * a chosen source, a "next time" bound and an opponent's pick all have
      readings on the recorded redirects above and none here.
    """
    if node.from_chosen_source or node.one_shot or node.chooser is not None:
        raise LoweringError(
            "a source-class redirect names no chosen source, no bound and no "
            "other chooser",
            node=node,
        )
    if not _is_source(node.new_recipient):
        raise LoweringError(
            "a source-class redirect moves the damage onto the permanent whose "
            "ability it is",
            node=node,
        )
    described = _filter_payload(spec.filter)
    if not described:
        raise LoweringError(
            "a source-class redirect describes the sources it moves", node=node
        )
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "a redirect cannot test " + ", ".join(sorted(untestable)), node=node
        )
    return (
        OracleInstruction(
            "redirect_source_class_damage_until_eot", "",
            {"sources": described, "combat_only": bool(node.combat_only)},
        ),
    )


def _lower_spell_damage_redirect(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """Reverberation: "All damage that would be dealt this turn by target
    sorcery spell is dealt to that spell's controller instead."

    A spell rather than a permanent on the source end, which is the whole reason
    this is its own instruction: a spell is chosen from the stack, and it is
    recognised at damage time by the *cast* rather than by the source object —
    see ``engine/damage_redirects.resolving_object_redirects``.

    "That spell's controller" reaches lowering as a bare "that player", because
    the possessive names an object the sentence has already named — and the
    sentence named exactly one, the spell. So the recipient is the spell's
    controller by the only reading available, and any other player reference
    refuses rather than being resolved to a seat nobody chose.
    """
    spec = node.dealt_by
    if (
        not isinstance(spec, ast.TargetSpec)
        or spec.quantifier != "target"
        or spec.filter.zone != "stack"
    ):
        raise LoweringError(
            "a redirect with no protected recipient moves one chosen spell's "
            "damage",
            node=node,
        )
    if not isinstance(node.new_recipient, ast.PlayerRef) or node.new_recipient.kind != "that_player":
        raise LoweringError(
            "no handler resolves this redirect's new recipient", node=node
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    if not spec.filter.card_types:
        # "target **sorcery** spell". Without a type this reads "target spell",
        # which is a strictly wider card — and the handler tests the chosen
        # spell against this union at resolution (CR 608.2b), so an empty one
        # would admit every spell on the stack.
        raise LoweringError("this spell redirect names no kind of spell", node=node)
    # "zone" is the printed word "spell" itself — the noun parser records it
    # when a type is followed by that word — and it is checked above rather than
    # dropped here.
    if _restrictions_beyond(spec.filter, frozenset({"card_types", "zone"})):
        raise LoweringError(
            "the spell redirect narrows its target by type and nothing else",
            node=node,
        )
    return (
        OracleInstruction(
            "redirect_damage_from_target_spell_until_eot", "",
            {
                "new_recipient": "spell_controller",
                "card_types": list(spec.filter.card_types),
            },
        ),
    )


def _lower_optional_class_redirect(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """Blood of the Martyr: "Until end of turn, if damage would be dealt to any
    creature, you may have that damage dealt to you instead."

    Two things separate this from every recorded redirect above, and both are
    payload rather than a kind of their own:

    * the protected recipient is a **class**, not an object. Every other
      redirect in the pool hangs its record off the one recipient it watches;
      a class has no object to hang off, so the record goes on the seat that
      takes the damage and carries the noun phrase it answers to
      (``engine/damage_redirects.class_redirects``). That is also why the
      filter is held to what ``subject_matches`` can test: a restriction the
      matcher would drop is a redirect covering strictly more creatures than
      the card prints.
    * the replacement is **optional** (CR 614). The word is carried through to
      the interceptor, which offers a
      :class:`~engine.replacement_choices.ReplacementChoice` instead of moving
      the damage — dropping it would make every point compulsory.

    Everything else refuses. A source narrowing, a "next time" bound, an
    opponent's pick and any duration but this turn all have readings on the
    recorded redirect and none here, and admitting one would arm a record that
    quietly ignores it.
    """
    if not _is_you(node.new_recipient):
        raise LoweringError(
            "an optional redirect is armed on its controller; no handler moves "
            "damage onto another recipient",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    if (
        node.dealt_by is not None
        or node.from_chosen_source
        or node.one_shot
        or node.chooser is not None
    ):
        raise LoweringError(
            "an optional class redirect names no source, no bound and no other "
            "chooser",
            node=node,
        )
    spec = node.to
    if not isinstance(spec, ast.TargetSpec) or spec.quantifier not in ("all", "each"):
        raise LoweringError(
            "no handler arms a redirect over this class of recipients", node=node
        )
    described = _filter_payload(spec.filter)
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "a redirect cannot test " + ", ".join(sorted(untestable)), node=node
        )
    return (
        OracleInstruction(
            "redirect_matching_damage_to_you_until_eot", "",
            {"recipients": described, "optional": True},
        ),
    )

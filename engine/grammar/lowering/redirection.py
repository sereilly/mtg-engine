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

**The module is CR 614 on a damage event, which is wider than its name**, and
Mirage's second wave is where that showed. ``_lower_double_combat_damage``
arrived on one branch and stated the taxonomy — three replacements separated by
*which half of the event they change*, the recipient here, the amount there,
whether it happens at all in ``prevention``. ``_lower_damage_becomes_counter_removal``
came off another and is the fourth: the damage does not happen and something
else does instead, so it belongs to neither shield nor redirect. It moved here
at the integration, when ``prevention`` crossed the size guard on nobody's
branch and the seam was the one already written down.

**The counted redirects left at Nemesis' first wave**, for ``_counted_redirects``
— "the next N damage …", CR 615.7's numeric shield read with this module's
verb. The seam is the parse side's own: one production reads both quantities,
and ``_lower_redirect_damage`` already handed a counted node down before any
branch here could read it. The blanket redirects off an announced target
(Sivvi's Valor, Oracle's Attendants) arrived in the same round and stayed.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (_REST_OF_TURN, _describe_targets,
                      _filter_payload, _is_source, _is_target, _is_you,
                      _names_several_targets, _optional_slot_key,
                      _restrictions_beyond, testable_filter_payload)
# "The next **N** damage …" (Daughter of Autumn, Zhalfirin Crusader): the
# counted half of the one production, a floor this module hands the sentence
# down to the moment the printed quantity is a number.
from ._counted_redirects import _lower_next_damage_redirect


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
    if node.amount is not None:
        # "**The next N** damage …" — a point pool rather than the whole event.
        # Read ahead of every branch below rather than beside them, because
        # each of those was written when there was no number to read: handed a
        # counted node they would move the *whole* event and report the card
        # supported, so a redirect one point wide would move a Fireball's
        # twelve. The counted lowering refuses everything it does not
        # implement, which keeps the number from being dropped anywhere.
        return _lower_next_damage_redirect(node)
    if node.optional:
        return _lower_optional_class_redirect(node)
    if node.to is None:
        # "All damage that would be dealt this turn **by target sorcery spell**
        # is dealt to that spell's controller instead." (Reverberation.) The one
        # printed shape with no protected recipient: it names only the source,
        # so it moves whatever that spell would deal, to whoever it would have
        # damaged.
        return _lower_spell_damage_redirect(node)
    if _is_source(node.dealt_by):
        # "The next time **this creature** would deal combat damage to an
        # opponent this turn…" (Soltari Guerrillas). The moved damage's source
        # is the ability's own permanent — named, not chosen and not targeted —
        # which is the axis every branch below keys on, and it is also the only
        # shape whose *protected* recipient is somebody other than the seat that
        # armed it. Both facts belong to one branch: the seats are known only
        # because the source is.
        return _lower_named_source_redirect(node)
    if node.from_chosen_source and isinstance(node.to, ast.TargetSpec):
        if isinstance(node.new_recipient, ast.TargetSpec) and _is_target(
            node.new_recipient
        ):
            # "All damage that would be dealt this turn to **target creature you
            # control** by a source of your choice is dealt to **another target
            # creature** instead." (Kor Chant.) The branch below's sentence with
            # its taker announced too, so the announcement carries three
            # answers — two targets (CR 601.2c) and CR 615.8's chosen source,
            # which is not a target at all.
            return _lower_chosen_source_redirect_between_targets(node)
        # "The next time a source of your choice would deal damage to **target
        # creature** this turn, that damage is dealt to this creature instead."
        # (Shaman en-Kor.) CR 615.8's chosen source over a protected recipient
        # the ability *announces* rather than one it is printed on — which is
        # why it is a kind of its own and not the branch below with a flag: the
        # record hangs off the target instead of off the caster, and the picker
        # has a creature to ask for as well as the source.
        return _lower_chosen_source_redirect_off_target(node)
    if (
        isinstance(node.to, ast.TargetSpec)
        and node.to.quantifier == "target"
        and node.dealt_by is None
        and not node.from_chosen_source
    ):
        # "All damage that would be dealt to **target creature** this turn is
        # dealt to you instead." (Sivvi's Valor.) The protected recipient is
        # announced, and the sentence names no source at all — so every
        # source's damage moves, which is what "all damage" says.
        return _lower_redirect_off_target(node)
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
    elif (
        node.from_chosen_source
        and isinstance(recipient, ast.TargetSpec)
        and recipient.quantifier == "target"
    ):
        # "{3}: The next time a source of your choice would deal damage to you
        # this turn, that damage is dealt to **target creature you control**
        # instead." (General's Regalia.) The branch above with the pick made by
        # the *activating* player rather than by an opponent — so it is a target
        # (CR 601.2c), announced with the ability, and not a prompt the
        # resolution arms.
        #
        # Restricted to the **chosen-source** shape, because the targeted-source
        # arm below writes its own ``targets`` description of the moved damage's
        # source onto this same payload: two target descriptions on one
        # instruction is one of them silently overwriting the other, and the
        # picker reads whichever survived.
        payload["new_recipient"] = "target"
        _describe_targets(payload, recipient)
        untestable = untestable_filter_keys(
            (payload.get("targets") or {}).get("filter") or {}
        )
        if untestable:
            # The picker offers this description and the resolution re-checks
            # it (CR 608.2b), so a narrowing the matcher cannot answer is a
            # redirect onto a creature the printed phrase excludes.
            raise LoweringError(
                "a redirect cannot test " + ", ".join(sorted(untestable)),
                node=node,
            )
    elif (
        isinstance(recipient, ast.PlayerRef)
        and recipient.kind == "controller"
        and not node.from_chosen_source
        and isinstance(node.dealt_by, ast.TargetSpec)
        and node.dealt_by.quantifier == "target"
    ):
        # "…by target unblocked creature is dealt to **its controller**
        # instead." (Mirror Strike.) "Its" is the announced source's, and its
        # controller is CR 109.5's live answer when the damage would be dealt —
        # Reflect Damage's ``to_source_controller`` derivation, read off the
        # damage's own source rather than frozen at resolution, so a creature
        # that changes hands sends the damage to whoever controls it then.
        payload["new_recipient"] = "source_controller"
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
        # The printed word is honoured by the record's own ``combat_only`` flag
        # (``damage_redirects.applicable_redirect`` reads it off the event), and
        # the one arm below that carries it onto the record is the targeted
        # source's: "All **combat** damage that would be dealt to you this turn
        # by target unblocked creature…" (Mirror Strike). The chosen-source arm
        # does not hand it on, so it still refuses there — a redirect wider
        # than the card prints is the silent direction.
        if node.from_chosen_source or not (
            isinstance(spec, ast.TargetSpec) and spec.quantifier == "target"
        ):
            raise LoweringError(
                "only a source-class or a targeted-source redirect is scoped to "
                "combat damage",
                node=node,
            )
        payload["combat_only"] = True
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


#: Which seats a named-source redirect watches, by the printed seat word.
#: "an opponent" and "each opponent" are one record — the sentence describes the
#: damage event rather than choosing a seat (nothing is targeted), so the record
#: has to exist on every seat the event could land on before it happens. A word
#: outside this table refuses: a redirect armed on the wrong seats is a card
#: that either does nothing or covers damage it never mentioned.
_REDIRECT_PROTECTED_SEATS: dict[str, str] = {
    "you": "you",
    "opponent": "opponents",
    "each_opponent": "opponents",
}


def _lower_redirect_off_target(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """Sivvi's Valor: "All damage that would be dealt to target creature this
    turn is dealt to you instead."

    The record hangs off the **announced** creature — a record lives on the
    recipient whose damage it moves (``engine/damage_redirects.py``) — and
    answers to every source, because the sentence names none. That is the one
    thing separating it from Shaman en-Kor's shape below: there the source is
    CR 615.8's choice and the picker asks for it, here nothing is chosen but the
    creature, so it is its own kind for the reason every kind in this module is
    (``engine/targeting.py`` keys the picker on the kind).

    Payload rather than a kind for everything else the sentence can vary:

    * the taker: "you" is the ability's controller (CR 109.5) and "this
      creature" the permanent whose ability it is — both known to the handler
      without a choice. Any other taker would need a second announcement or a
      prompt, and refuses rather than arming a record pointing at nothing
      (CR 614.9: a redirect with nowhere to go does nothing);
    * "**the next time**" — one instance, ``uses=1``, which the record already
      carries for every other redirect;
    * "all **combat** damage" — the record's own ``combat_only`` flag, which
      ``applicable_redirect`` reads off the event.

    Every refusal below is a way the sentence could otherwise mean more than it
    says: one announced creature, a phrase every key of which ``subject_matches``
    can test (the target is re-checked at resolution, CR 608.2b), this turn's
    duration (what the cleanup sweep gives a record), and no opponent's pick or
    offer, which have readings on the redirects above and none here.
    """
    if node.chooser is not None or node.optional:
        raise LoweringError(
            "a redirect off an announced target names no other chooser and no "
            "offer",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    spec = node.to
    if _names_several_targets(spec):
        raise LoweringError(
            "a redirect off an announced target protects one creature", node=node
        )
    recipient = node.new_recipient
    if _is_source(recipient):
        taker = "source"
    elif _is_you(recipient):
        taker = "you"
    else:
        raise LoweringError(
            "no handler resolves this redirect's new recipient", node=node
        )
    payload: dict[str, object] = {"new_recipient": taker}
    _describe_targets(payload, spec)
    untestable = untestable_filter_keys(
        (payload.get("targets") or {}).get("filter") or {}
    )
    if untestable:
        raise LoweringError(
            "a redirect cannot test " + ", ".join(sorted(untestable)), node=node
        )
    if node.one_shot:
        payload["uses"] = 1
    if node.combat_only:
        payload["combat_only"] = True
    return (
        OracleInstruction("redirect_damage_off_target_until_eot", "", payload),
    )


def _lower_chosen_source_redirect_off_target(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """Shaman en-Kor: "{1}{W}: The next time a source of your choice would deal
    damage to **target creature** this turn, that damage is dealt to this
    creature instead."

    CR 615.8's "a source of your choice" with CR 614.9's verb, and the one
    printing in the pool whose **protected** recipient is announced as a target.
    Every other chosen-source redirect is armed on the ability's controller
    (``to_self``), so the record has nowhere to go but the caster; this one
    hangs off the creature it watches, which is where a record normally lives
    (``engine/damage_redirects.py``: a record lives on the recipient whose
    damage it moves).

    Its own instruction rather than a flag on ``redirect_damage_from_chosen_source_until_eot``
    for the reason every kind in this module is its own: the picker is keyed on
    the kind, and this ability announces **two** choices — the creature it
    protects (CR 601.2c) and the source whose damage moves (CR 615.8) — where
    that one announces the source alone.

    **Both quantities.** "The next time" is one instance (``uses=1``); "**All
    damage** that would be dealt to target creature this turn by a source of
    your choice is dealt to this creature instead" (Oracle's Attendants) is
    every instance that source deals the creature all turn, so ``uses`` is
    absent. The difference is carried rather than refused because the handler
    honours it: with no source announced it falls back to "any source" only
    for the one-instance record and arms *nothing* for the blanket one — Kor
    Chant's rule, for Kor Chant's reason (a blanket answering to any source
    would move every point dealt to the creature all turn).

    Every refusal below is a way the sentence could otherwise mean more than it
    says:

    * the source is named once. A chosen source beside a targeted one is two
      answers to one question.
    * the duration must be this turn, because that is what the sweeps give it.
    * the protected creature must be one target the phrase describes, and every
      key of that phrase must be one ``subject_matches`` can test — the target
      is re-checked at resolution (CR 608.2b) and a narrowing the matcher would
      drop is a redirect covering strictly more creatures than the card prints.
    * the damage must move onto the permanent whose ability this is. Jade
      Monolith's "that source deals that damage to **you**" is the same
      arrangement with the caster as the taker, and it reaches no production
      here — its sentence is in the active voice and the parse refuses it — so
      admitting the recipient would be a branch no card can reach.
    * a combat scope, an opponent's pick and an optional replacement all have
      readings on the redirects above and none here.
    """
    if node.dealt_by is not None:
        raise LoweringError(
            "a redirect names its source once: either a chosen source or a "
            "target",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    if node.combat_only or node.chooser is not None or node.optional:
        raise LoweringError(
            "a chosen-source redirect off a target names no combat scope, no "
            "other chooser and no offer",
            node=node,
        )
    spec = node.to
    if spec.quantifier != "target" or _names_several_targets(spec):
        raise LoweringError(
            "a chosen-source redirect protects one announced target", node=node
        )
    if not _is_source(node.new_recipient):
        raise LoweringError(
            "a chosen-source redirect off a target moves the damage onto the "
            "permanent whose ability it is",
            node=node,
        )
    # ``uses`` first and only for "the next time", so Shaman en-Kor's payload is
    # byte-identical to what it was before the blanket printing was admitted.
    payload: dict[str, object] = (
        {"uses": 1, "new_recipient": "source"} if node.one_shot
        else {"new_recipient": "source"}
    )
    _describe_targets(payload, spec)
    untestable = untestable_filter_keys(
        (payload.get("targets") or {}).get("filter") or {}
    )
    if untestable:
        raise LoweringError(
            "a redirect cannot test " + ", ".join(sorted(untestable)), node=node
        )
    return (
        OracleInstruction(
            "redirect_chosen_source_damage_off_target_until_eot", "", payload
        ),
    )


def _lower_chosen_source_redirect_between_targets(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """Kor Chant: "All damage that would be dealt this turn to **target creature
    you control** by a source of your choice is dealt to **another target
    creature** instead."

    The function above's sentence with its *taker* announced too, so the
    announcement carries three answers: two targets (CR 601.2c) and CR 615.8's
    chosen source, which is not a target at all (CR 609.7a). Its own kind and
    not a flag on that one, for the reason every kind in this module is its own
    — ``engine/targeting.py`` keys the picker on the kind, and this one raises a
    **two-role** walk where that one raises a single creature picker.

    The two roles are what make the sentence safe to lower at all. The slots are
    differently narrowed — "you control" against a bare "another" — so
    ``targeting._slot_roles_spec`` turns the description into ordered roles, and
    a shared candidate list would have let the caster move their own creature's
    damage onto a second creature of their own while the printed "you control"
    was enforced by nothing. CR 601.2c's distinctness comes out of the same
    walk: a permanent taken by role 0 is not offered to role 1, which is what
    "another" prints.

    **This is the only blanket chosen-source record in the pool**, and that is
    what its refusals are about. Every other card printing "a source of your
    choice" is a "next time" — ``uses=1``, spent on one instance — so an
    announcement that named no source can safely fall back to a record
    answering to any source. This one lasts the turn, so the same fallback would
    move *every* point of damage dealt all turn onto the second creature. The
    handler therefore arms nothing when no source was announced (see
    ``handlers/damage.py``), and ``one_shot`` is carried through as ``uses``
    rather than assumed absent, so a "next time" printing of this same shape
    would get the bounded record its sentence describes.

    Five refusals, each a way the sentence could otherwise mean more than it
    says:

    * the source is named once. A chosen source beside a targeted one is two
      answers to one question.
    * the duration must be this turn, because that is what the sweeps give it.
    * neither slot may name several targets: the handler reads slot 0 and slot 1
      positionally, and a third answer would be collected and dropped.
    * a combat scope and an opponent's pick have readings on the redirects above
      and none here.
    * every key of both printed noun phrases must be one ``subject_matches`` can
      test — both are re-checked at resolution (CR 608.2b), and a narrowing the
      matcher would drop is a redirect covering strictly more creatures than the
      card prints.
    """
    if node.dealt_by is not None:
        raise LoweringError(
            "a redirect names its source once: either a chosen source or a "
            "target",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    if node.combat_only or node.chooser is not None:
        raise LoweringError(
            "a chosen-source redirect between two targets names no combat "
            "scope and no other chooser",
            node=node,
        )
    protected, taker = node.to, node.new_recipient
    if _names_several_targets(protected) or _names_several_targets(taker):
        raise LoweringError(
            "a chosen-source redirect between two targets announces one "
            "creature per slot",
            node=node,
        )
    refusal = "a redirect cannot test"
    first = testable_filter_payload(protected.filter, refusal=refusal, node=node)
    second = testable_filter_payload(taker.filter, refusal=refusal, node=node)
    payload: dict[str, object] = {
        "targets": {
            "quantifier": "target",
            "kind": "object",
            # ``filter`` stays the shape every one-slot reader expects and
            # ``filters`` is what makes the picker ordered roles — the pair
            # ``lowering/control_changes.py`` writes for the same reason.
            "filter": first,
            "filters": [first, second],
            "count": 2,
            **_optional_slot_key((protected, taker)),
            # "…is dealt to **another** target creature instead." (Kor Chant.)
            # CR 601.2c: a sentence printing the word "target" twice may name
            # one object for both instances *unless* the card forbids it, and
            # this one does. Read off the printed word rather than asserted
            # unconditionally, because the two slots are otherwise a legitimate
            # pair — a redirect whose sentence omitted "another" really would
            # let the same creature fill both.
            #
            # Kor Chant is safe today by accident and not by this key: its two
            # noun phrases differ ("you control" against a bare creature), so
            # ``targeting._slot_roles_spec`` converts the pair to a roles walk,
            # which gets distinctness free. A card printing the word over two
            # *identical* phrases would fall back to the shared-list reading
            # with nothing forbidding the repeat, which is the silence this
            # line closes.
            **({"distinct": True} if taker.distinct_from_prior
               or protected.distinct_from_prior else {}),
        },
    }
    if node.one_shot:
        # "**The next time** …" — one instance rather than every instance for
        # the duration, which is what ``uses=None`` already means on the record.
        payload["uses"] = 1
    return (
        OracleInstruction(
            "redirect_chosen_source_damage_between_targets_until_eot", "", payload
        ),
    )


def _lower_named_source_redirect(
    node: ast.RedirectDamage,
) -> tuple[OracleInstruction, ...]:
    """Soltari Guerrillas: "{0}: The next time this creature would deal combat
    damage to an opponent this turn, it deals that damage to target creature
    instead."

    The third way a redirect can name the source whose damage moves, beside the
    targeted one (Shimian Night Stalker) and the chosen one (Nova Pentacle): it
    is the ability's **own permanent**, so nothing is picked for it and the
    handler already holds it. Its own kind for that reason and not as payload,
    exactly as those two are two kinds — ``engine/targeting.py`` keys the picker
    on the kind, and this one raises a picker for the *new recipient* where
    theirs raise one for the source or none at all.

    What is new underneath is the **protected** seat. Every other recorded
    redirect is armed on its controller (``to_self``); this one watches the
    seats the sentence describes, which are the caster's opponents, and the
    record is one object shared between them — CR 615.8's "the next **time**" is
    one instance of one replacement effect, so a per-seat copy would fire once
    per opponent.

    Six refusals, each a way the sentence could otherwise mean more than it
    says:

    * the source must carry no narrowing beyond naming itself. A restated
      adjective has nothing left to narrow and would be dropped.
    * the protected seats must be a word this table reads. A record armed on
      the wrong seats covers damage the card never mentioned — or none.
    * the duration must be this turn, because that is what the sweeps give it.
    * the new recipient must be one target the **activating** player picks.
      Nova Pentacle's "of an opponent's choice" is a different prompt on a
      different kind, and several targets would be collected and dropped.
    * every key of that noun phrase must be one ``subject_matches`` can test,
      because the picker and the handler both ask it.
    * a chosen source alongside a named one names the source twice.
    """
    if node.from_chosen_source:
        raise LoweringError(
            "a redirect names its source once: either a chosen source or the "
            "ability's own permanent",
            node=node,
        )
    if _restrictions_beyond(
        node.dealt_by.filter, frozenset({"card_types", "is_source"})
    ):
        raise LoweringError(
            "the ability's own source carries no narrowing the record could "
            "honour",
            node=node,
        )
    protects = _REDIRECT_PROTECTED_SEATS.get(getattr(node.to, "kind", ""))
    if protects is None:
        raise LoweringError(
            "a named-source redirect watches its controller or their opponents",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded redirect lasts exactly this turn", node=node)
    if node.chooser is not None:
        raise LoweringError(
            "the activating player picks a named-source redirect's new "
            "recipient",
            node=node,
        )
    recipient = node.new_recipient
    if (
        not isinstance(recipient, ast.TargetSpec)
        or recipient.quantifier != "target"
        or _names_several_targets(recipient)
    ):
        raise LoweringError(
            "no handler resolves this redirect's new recipient", node=node
        )
    described = _filter_payload(recipient.filter)
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "a redirect cannot test " + ", ".join(sorted(untestable)), node=node
        )
    payload: dict[str, object] = {
        "protects": protects,
        "combat_only": bool(node.combat_only),
    }
    if node.one_shot:
        # "**The next time** …" — one instance. Absent is every instance for
        # the duration, which is what ``uses=None`` already means on the record.
        payload["uses"] = 1
    _describe_targets(payload, recipient)
    return (
        OracleInstruction("redirect_source_damage_to_target_until_eot", "", payload),
    )


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
    if node.from_chosen_source:
        # "The next time **a source of your choice** would deal damage this
        # turn, that damage is dealt to that source's controller instead."
        # (Reflect Damage.) Reverberation's sentence with the source named the
        # other way — chosen as the spell is cast (CR 615.8's phrase) rather
        # than targeted — which is the axis every source-naming effect in this
        # engine splits on: one picker runs over the stack alone and the other
        # over every source there is.
        if node.dealt_by is not None:
            raise LoweringError(
                "a redirect names its source once: either a chosen source or a "
                "target",
                node=node,
            )
        if (
            not isinstance(node.new_recipient, ast.PlayerRef)
            or node.new_recipient.kind != "that_player"
        ):
            raise LoweringError(
                "no handler resolves this redirect's new recipient", node=node
            )
        if node.duration.kind not in _REST_OF_TURN:
            raise LoweringError(
                "a recorded redirect lasts exactly this turn", node=node
            )
        if not node.one_shot:
            # "**The next time**" is the whole of how far this record reaches.
            # A blanket printing of the same sentence would move every point of
            # damage that source deals all turn, which is a different card and
            # has no handler — refused rather than armed with the bound
            # dropped.
            raise LoweringError(
                "a chosen-source redirect with no recipient moves one instance",
                node=node,
            )
        return (
            OracleInstruction(
                "redirect_damage_from_chosen_source_until_eot", "",
                {"uses": 1, "any_recipient": True,
                 "new_recipient": "source_controller"},
            ),
        )
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


def _lower_double_combat_damage(
    node: ast.DoubleCombatDamage,
) -> tuple[OracleInstruction, ...]:
    """Blind Fury: "If a creature would deal combat damage to a creature this
    turn, it deals double that damage to that creature instead."

    Beside the redirect in this module rather than with the shields: all three
    are CR 614 replacements on a damage event, and what separates them is which
    half of the event they change — the recipient here, the amount there, and
    whether it happens at all in ``prevention``.

    No payload, because the node carries none: the pool prints one wording and
    every word of it is a narrowing the interceptor tests. A parameter with no
    second card behind it would be a claim nothing checks.
    """
    return (OracleInstruction("double_combat_damage_until_eot", "", {}),)


def _lower_damage_becomes_counter_removal(
    node: "ast.DamageBecomesCounterRemoval",
) -> tuple[OracleInstruction, ...]:
    """"For each 1 damage that would be dealt to you until your next upkeep,
    you remove an echo counter from this enchantment instead." (Soul Echo.)

    Two refusals, and each is a way the sentence could otherwise cover more
    than it says.

    The player is the ability's **controller**. CR 109.5 makes "you" the
    ability's controller wherever it is printed, and this sentence is offered
    to an *opponent* — so reading the seat off the offer would arm the
    replacement over the wrong player's life total, which is the whole card
    inverted.

    The duration is required and is "until your next upkeep" alone. It is what
    the sweep at the top of the upkeep step keys on; a replacement armed with
    no duration is one nothing ever takes away, and the card would replace
    every point of damage its controller was ever dealt.
    """
    if node.recipient.kind != "you":
        raise LoweringError(
            "the counter-removal replacement covers the ability's controller",
            node=node,
        )
    if node.duration.kind != "until_your_next_upkeep":
        raise LoweringError(
            "a counter-removal replacement lasts until your next upkeep",
            node=node,
        )
    return (
        OracleInstruction(
            "arm_damage_to_counter_removal", "", {"counter": node.counter},
        ),
    )

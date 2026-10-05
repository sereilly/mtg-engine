"""Lowering destruction: CR 701.8, of an object the sentence **names**.

Split out of ``board`` at the thousand-line guard — a cap neither parallel
branch crossed alone, which is what made the boundary visible: one added an
activated ability's delayed destroy and the other a per-payer sweep, and both
are destruction rather than board changes generally.

The line is the CR's own keyword action. Destroying a permanent (CR 701.8) is
not sacrificing one (CR 701.21), regenerating one (CR 701.19), phasing one out
(CR 702.26) or exchanging control of one, and those are what ``board`` keeps.
The two halves share no name in either direction — checked at the split rather
than assumed — so this is a family boundary and not a size cut.

**The destroy over a set the sentence describes left for ``_destroy_sweeps``**
at Invasion's Phase 0 between waves 1 and 2, with this module at 987 lines.
"Destroy all …" was 384 of them in one branch of :func:`_lower_destroy`, every
path of which returned or raised, so it came out as one call and took the two
tables only it read, and with them its seat gate, which
:func:`_lower_destroy_of_their_choice` now reads from there. What decided the
cut is which half was growing and why: two of the three wave-1 additions landed
in that branch, because a sweep's narrowing has to reach a handler as payload
and every printed relation the shared matcher cannot test needs a branch of its
own there.

What stays is every destroy that names its object, and the question each
branch below asks is the other one — not "does the narrowing survive to a
reader that can test it" but "which record says which object this is":

* the superlative ("the creature with the least power"), read first because
  the definite article gives it the sweep's own quantifier;
* several announced targets, as ordered roles or as a chosen list;
* the references — the permanent this Aura is attached to, the ability's own
  source, the firing event's object ("it", "that creature", "the other
  creature"), the other half of a block pair, a delayed ability's bound object
  or its agent, and a pick an earlier step recorded. None of them offers a
  choice (CR 603.3d), so none describes a target for a picker to raise, and
  each is gated on the event or the record that gives the word a referent;
* the one target, and The Abyss's "of their choice", which prints the word
  "target" and is picked by another seat at resolution.

The title above promised "the delayed and conditional forms" until this split
and had not held either for some time: the end-of-combat delay is
``lowering/delayed.py``'s and the "unless <someone> pays" offers went back to
``board`` and on to ``tolls``. ``_lower_destroy`` still *refuses* a delay on
the one reading that cannot carry one, and that is all it knows about them.
"""

import dataclasses

from ...oracle_types import CHOSEN_TARGET_PERMANENTS, OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._common import (
    describe_independent_target_roles, _describe_several_targets,
    _describe_targets, _filter_payload, _is_source, _names_several_targets,
    _restrictions_beyond, is_mana_value_x, SEVERAL_DESTROY_NARROWINGS,
    testable_filter_payload
)
from ._destroy_sweeps import _refuse_unfrozen_that_player, lower_destroy_sweep
from ._events import (ATTACHED_PERMANENT_CONTROLLER, _EVENT_STAMPED_TARGET_OBJECTS, _EVENT_SUBJECT_OBJECTS, EVENT_SUBJECT_PLAYER, ROLE_NAMES_BLOCK_PARTNER, binds_block_pair, names_attached_permanent, CHOSEN_PERMANENT)
from ._delays import (_DELAYED_AGENT_EVENTS, _BOUND_OBJECT_DELAYED_EVENTS)
from ._superlatives import superlative_pick


def _lower_destroy(
    node: ast.Destroy,
    event: str | None = None,
    event_subject: object | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    if not isinstance(node.subject, ast.TargetSpec):
        raise LoweringError("destroy needs an object target", node=node)
    spec = node.subject
    filt = spec.filter

    # "…that share a color with **it**" (Spreading Plague) is read by the
    # sweep (``_destroy_sweeps``) and by nothing in this function: a *target*
    # narrowed by a relation to the firing event's object would need the
    # picker and the CR 608.2b recheck to hold the trigger's context, and
    # neither does. Refused up here so the single-target tail cannot carry the
    # key into a payload no matcher reads.
    if filt.shares_color_with_it and spec.quantifier not in ("all", "each"):
        raise LoweringError(
            "only a sweep reads 'shares a color with it'", node=node
        )

    # "Destroy **the creature with the least power**. It can't be regenerated."
    # (Drop of Honey.) Purging Scythe prints the same noun phrase under a damage
    # verb one family over, which is why the pick is a floor both read
    # (``_superlatives``) rather than a branch in either. Above every sweep
    # below, because "all" is the quantifier the definite article gives a
    # described phrase and this one names **one** object — falling through, the
    # word is refused by name at the key gate, which is the safe direction but
    # not the card.
    pick = superlative_pick(spec, node=node, verb="destroy")
    if pick is not None:
        if node.also_targets or node.delay:
            raise LoweringError(
                "a superlative destroy carries no second target and no delay",
                node=node,
            )
        step, key = pick
        destroy_payload: dict[str, object] = {"permanents_from": key}
        if node.no_regen:
            destroy_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("sequence", "", {"steps": (
                step,
                OracleInstruction(
                    "destroy_target_permanent", "", destroy_payload
                ),
            )}),
        )

    if node.also_targets:
        # "Destroy target creature **and target land**." (Fumarole.) Several
        # targeted phrases of one announcement, described as ordered roles so
        # the picker asks for each in turn (CR 601.2c). One instruction, because
        # one announcement — see ``ast.Destroy.also_targets``.
        #
        # Above every branch below, and carrying **no** top-level filter keys:
        # those describe one target, and a payload holding both would let the
        # single-target tail read the first role's noun as though it were the
        # whole spell.
        payload: dict[str, object] = {}
        if node.no_regen:
            payload["bypass_regeneration"] = True
        describe_independent_target_roles(payload, (spec, *node.also_targets))
        return (OracleInstruction("destroy_target_permanent", "", payload),)

    if spec.quantifier in ("all", "each"):
        # Every reading of a described set is one module down, where the
        # order its branches are asked in is the whole of their safety.
        return lower_destroy_sweep(node, spec, event, produced)

    # "Destroy **it**", where the sentence's "it" is the permanent this Aura
    # enchants (Blight: "When enchanted land becomes tapped, destroy it"), and
    # the equivalent spelling that names it outright. Its own handler for the
    # reason `untap_enchanted_creature` and
    # `grant_regeneration_to_enchanted_creature` have theirs: the subject is
    # known from the source's own attachment, so routing it through the
    # targeted destroy would ask for a pick the card never offers — and would
    # find a permanent by index on whichever battlefield the context happened
    # to carry.
    #
    # "…destroy **that land**" (Erosion) is the same referent spelled with the
    # noun repeated instead of the pronoun, and only under an event whose
    # condition already named it -- see `names_attached_permanent`. Asked here,
    # above the "that" branch below, because that branch reads the *firing
    # event's* object and would destroy whatever the fire site had stamped.
    # "When **enchanted creature** becomes the target of a spell or ability,
    # destroy **that creature**." (Spinal Graft.) The same referent again, under
    # a condition kind that is *also* printed about the source itself — so the
    # event's own subject is what says which, and it is passed rather than
    # inferred from the kind.
    if names_attached_permanent(spec, event, event_subject):
        attached_payload: dict[str, object] = {}
        if node.no_regen:
            attached_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_attached_permanent", "", attached_payload),
        )

    # "**Destroy this Aura.**" (Imprison.) The sentence names its own source —
    # the SELF token, or "this <type>" where the type is the source's own — so
    # like the attached destroy above it chooses nothing and there is nothing
    # for a picker to offer. Its own handler rather than the targeted one for
    # exactly that reason: routed through `destroy_target_permanent` the
    # ability would ask for a pick the card never printed and then destroy
    # whichever permanent the resolution context happened to carry.
    #
    # Above the "that" branch below, and not folded into it: "that creature" is
    # the object a trigger's *event* was about and only exists under an event
    # that recorded one, while "this Aura" is the ability's source and is
    # answerable under every event and none.
    if _is_source(spec):
        self_payload: dict[str, object] = {}
        if node.no_regen:
            self_payload["bypass_regeneration"] = True
        return (OracleInstruction("destroy_self", "", self_payload),)

    # "Whenever a Djinn or Efreet enters, **destroy it**." (Suleiman's Legacy.)
    # A bare pronoun that `rebinding.rebind_pronoun_to_event_subject` has already
    # pointed at the trigger's own subject — which is what makes the filter
    # non-source here, and so what tells this apart from the `_is_source` branch
    # above: an "it" the rebinder left alone is still the ability's own source
    # and is destroyed by `destroy_self`.
    #
    # Its own kind rather than the targeted destroy, for `destroy_self`'s and
    # `destroy_bound_permanent`'s reason: the card offered no choice (CR 603.3d),
    # so routing it through the picker would ask for one and then destroy
    # whichever permanent the resolution context happened to carry.
    #
    # Admitted only under an event whose fire site freezes the object, because
    # everywhere else the pronoun has no referent at all.
    if spec.quantifier == "it" and not spec.filter.is_source:
        if event not in _EVENT_SUBJECT_OBJECTS:
            raise LoweringError(
                "\"it\" names the firing event's object, and this event "
                "records none",
                node=node,
            )
        subject_payload: dict[str, object] = {}
        if node.no_regen:
            subject_payload["bypass_regeneration"] = True
        return (OracleInstruction("destroy_event_subject", "", subject_payload),)

    # "…destroy **the blocking creature**." / "…destroy **the attacking
    # creature**." (No Quarter.) A printed *combat role*, which is how a
    # board-wide block trigger names the half of the pair its own condition did
    # not describe — the ability's source is in no combat at all, so neither
    # "this creature" nor "that creature" is available to it.
    #
    # Gated on the event, and the gate is the whole of the card's correctness:
    # a role names the partner under exactly one of the two block events, and
    # under the other one it names the creature the firing is *about*. Read
    # ungated, "destroy the blocking creature" under a blocks trigger would
    # destroy the attacker.
    #
    # Its own kind rather than the targeted destroy, for `destroy_self`'s
    # reason two branches up: the card offered no choice (CR 603.3d), so the
    # picker would ask for one.
    if spec.quantifier in ROLE_NAMES_BLOCK_PARTNER:
        if event not in ROLE_NAMES_BLOCK_PARTNER[spec.quantifier]:
            raise LoweringError(
                f"\"the {spec.quantifier} creature\" names the other half of a "
                "block, and this event announces none it is that half of",
                node=node,
            )
        if filt.card_types not in ((), ("creature",)) or _restrictions_beyond(
            filt, frozenset({"card_types"})
        ):
            # The role *is* the reference; a narrowing on top of it would be a
            # second choice the sentence never offers, and dropped it would
            # destroy a creature the card did not name.
            raise LoweringError(
                "a creature named by its combat role carries no narrowing the "
                "destroy could honour",
                node=node,
            )
        partner_payload: dict[str, object] = {}
        if node.no_regen:
            partner_payload["bypass_regeneration"] = True
        return (
            OracleInstruction(
                "destroy_block_pair_partner", "", partner_payload
            ),
        )

    # "If you win the flip, destroy **the creature you chose**. If you lose the
    # flip, destroy **the creature your opponent chose**." (Mogg Assassin.) Two
    # back-references to two *different* choosers' picks, and which record each
    # names follows from how this engine models the two choices rather than from
    # anything about this card:
    #
    # * the ability's controller picks at **announcement** (CR 601.2c), so
    #   "you chose" is the ``choose_target_permanent`` step's record;
    # * any other seat picks at **resolution**, through the ordinary
    #   ``choose_permanent`` prompt, so "your opponent chose" is that step's.
    #
    # Both gated on the record really having been written, which is the rule
    # every back-reference in this package follows: without the step in front of
    # it the words name nothing, and a destroy reading an empty record is a card
    # that compiles clean and destroys nothing.
    if spec.quantifier in _CHOSEN_BY_RECORDS:
        record = _CHOSEN_BY_RECORDS[spec.quantifier]
        if record not in produced:
            raise LoweringError(
                f"back-reference to {record!r} with no producer in this effect",
                node=node,
            )
        if _restrictions_beyond(filt, frozenset({"card_types"})):
            # The noun restates what was chosen; it does not narrow it. A phrase
            # carrying anything more would be describing a *different* object,
            # and the record cannot be re-filtered — the pick is already made.
            raise LoweringError(
                "a chosen object carries no narrowing the destroy could honour",
                node=node,
            )
        chosen_payload: dict[str, object] = {"permanents_from": record}
        if node.no_regen:
            chosen_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_target_permanent", "", chosen_payload),
        )

    # "Whenever enchanted creature deals damage to a creature, destroy **the
    # other creature**." (Venomous Fangs.) English's "other" contrasts with the
    # nearest antecedent noun phrase, and a damage event has exactly two objects
    # -- the trigger's own condition named the damager, so the word names the one
    # that took it. Which is the same object "that <noun>" names under this
    # event, and it rides the same instruction and the same
    # ``target_permanent_id`` the fire site stamps.
    #
    # A branch of its own rather than a second word on the "that" guard below,
    # because that guard opens onto four readings this word does not have: the
    # attachment record, the two delayed-agent tables and the event subject. "The
    # other" under a *delayed* ability is Infinite Authority's, and
    # ``lowering/delayed.py`` already reads it there.
    #
    # Gated on ``_EVENT_STAMPED_TARGET_OBJECTS`` exactly as that branch is, and
    # for its reason: under any other event there is no second object for the
    # word to contrast with, and a destroy reading an unstamped id would resolve
    # nothing while the card reported supported.
    if spec.quantifier == "other":
        if event not in _EVENT_STAMPED_TARGET_OBJECTS:
            raise LoweringError(
                "\"the other creature\" names the second object of the firing "
                "event, and this event announces only one",
                node=node,
            )
        if _restrictions_beyond(filt, frozenset({"card_types"})):
            # The noun restates the object the event already named; a narrowing
            # on top of it would be a second choice the sentence never offers,
            # and dropped it would destroy a permanent the card did not name.
            raise LoweringError(
                "\"the other creature\" carries no narrowing the destroy could "
                "honour",
                node=node,
            )
        other_payload = _filter_payload(filt)
        if node.no_regen:
            other_payload["bypass_regeneration"] = True
        return (
            OracleInstruction("destroy_target_permanent", "", other_payload),
        )

    # "…destroy **that planeswalker**." (Hooded Blightfang.) "That" is not a
    # target the card ever asked for — it is the object the trigger's event was
    # about, which the fire site stamps onto the stack item by permanent id. So
    # this rides the ordinary destroy handler and simply does not describe a
    # cast-time target: `_describe_targets` below would raise a picker for a
    # choice CR 603.3d says was never offered. Admitted only under the events
    # whose fire site records one, because everywhere else "that" has no
    # referent and a bare destroy would hit whatever the context happened to
    # hold.
    if spec.quantifier == "that":
        # "…then destroy **that creature** and it can't be regenerated."
        # (Consuming Ferocity.) The permanent the Aura is attached to, named
        # "enchanted creature" by the step in front of this one — so it is the
        # ordinary attached destroy, and the only thing that makes the pronoun
        # readable is that record. Checked rather than assumed: with no such
        # step the words name nothing, and a destroy that reached the
        # attachment anyway would be reading a card that never said
        # "enchanted".
        #
        # Ahead of the delayed and event-subject branches below because it is
        # the narrower question: those ask what a *trigger* recorded, and this
        # asks what an earlier step of this same effect did (CR 608.2h).
        if ATTACHED_PERMANENT_CONTROLLER in produced:
            attached_payload: dict[str, object] = {}
            if node.no_regen:
                attached_payload["bypass_regeneration"] = True
            return (
                OracleInstruction(
                    "destroy_attached_permanent", "", attached_payload
                ),
            )
        # "…destroy **that creature**" inside a *delayed* ability (War Barge).
        # The object is the one the creating ability bound (CR 603.7c), carried
        # by id in the trigger's context — never a pick, and never the object
        # the delay *watched*, which for this card is the artifact itself. Its
        # own kind for the reason `destroy_self` and `destroy_attached_permanent`
        # have theirs: routed through the targeted destroy the ability would ask
        # for a choice the card never offered, and then destroy whichever
        # permanent the resolution context happened to carry.
        # "Whenever target creature deals combat damage to a non-Wall creature
        # this turn, destroy **that non-Wall creature**." (Acidic Dagger.) The
        # event has two objects and the words name the *other* one: the entry is
        # bound to the creature that dealt the damage, and the phrase restates
        # the one that took it. Read before the bound branch below, which would
        # destroy the Dagger's own target — the creature its controller aimed
        # the ability at, which is the opposite of what the card does.
        if event in _DELAYED_AGENT_EVENTS:
            agent_payload = _filter_payload(filt)
            if node.no_regen:
                agent_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_delayed_agent", "", agent_payload),
            )
        if event in _BOUND_OBJECT_DELAYED_EVENTS:
            bound_payload = _filter_payload(filt)
            if node.no_regen:
                bound_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_bound_permanent", "", bound_payload),
            )
        # "Whenever this creature becomes blocked by a green creature, destroy
        # **that creature**. It can't be regenerated." (Phyrexian Reaper,
        # Phyrexian Slayer.) The other half of the pair the trigger bound — the
        # referent the *delayed* destroy has read since Thicket Basilisk and the
        # tuck, the tap, the pumps and the keyword grants each read one family
        # over — destroyed now instead of at end of combat. So it is No
        # Quarter's handler, which resolves the pair through
        # ``block_pair_permanents`` and never through a pick: the trigger
        # offered no choice (CR 603.3d).
        #
        # ``binds_block_pair`` rather than the kind, for that helper's reason:
        # CR 509.3c makes a *bare* "becomes blocked" fire once with several
        # blockers and no way to say which one "that creature" is, and this
        # must refuse there rather than destroy whichever came first.
        #
        # The noun restates the creature the condition already narrowed; a
        # narrowing of its own would be a second test the handler does not
        # make, so it refuses rather than being consumed and dropped.
        if binds_block_pair(event, event_subject):
            if filt.card_types != ("creature",) or _restrictions_beyond(
                filt, frozenset({"card_types"})
            ):
                raise LoweringError(
                    "the block-pair destroy names the creature the trigger "
                    "bound and carries no narrowing of its own",
                    node=node,
                )
            pair_payload: dict[str, object] = {}
            if node.no_regen:
                pair_payload["bypass_regeneration"] = True
            return (
                OracleInstruction("destroy_block_pair_partner", "", pair_payload),
            )
        if event not in _EVENT_STAMPED_TARGET_OBJECTS:
            raise LoweringError(
                "\"that\" names the firing event's object, and this event records none",
                node=node,
            )
        payload = _filter_payload(filt)
        if node.no_regen:
            payload["bypass_regeneration"] = True
        return (OracleInstruction("destroy_target_permanent", "", payload),)

    # "Destroy X target snow lands." (Avalanche.) "Up to two target creatures"
    # is the same shape with a printed number instead of an announced one, and
    # both are what `_names_several_targets` names: a chosen *list*, not a
    # chosen permanent.
    #
    # This branch is why "up to two" used to fall through to the single-target
    # path below and emit an instruction with **no target description at all** —
    # `_targets_payload` refuses a several-target spec, so `_describe_targets`
    # added nothing, the picker had nothing to read, and the card would have
    # destroyed one permanent of the two it names. No card in the pool prints
    # it, which is the only reason that was latent rather than live.
    #
    # Gated to a filter `destroy_target_permanent`'s list branch answers in
    # full, exactly as the untap beside it is: a narrowing dropped from a
    # several-target destroy is not a spell that does less, it is one that
    # destroys the wrong permanents.
    if _names_several_targets(spec):
        leftovers = _restrictions_beyond(spec.filter, SEVERAL_DESTROY_NARROWINGS)
        if leftovers:
            raise LoweringError(
                "the several-target destroy cannot narrow by: " + ", ".join(leftovers),
                node=node,
            )
        several = testable_filter_payload(
            spec.filter,
            refusal="the several-target destroy cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        if node.no_regen:
            several["bypass_regeneration"] = True
        _describe_several_targets(several, spec)
        return (OracleInstruction("destroy_target_permanent", "", several),)

    if spec.quantifier not in ("target", "up_to"):
        raise LoweringError("unsupported destroy quantifier", node=node)

    if filt.their_choice:
        return _lower_destroy_of_their_choice(node, spec, event)

    # "Destroy target artifact **with mana value X**." (Detonate.) The bound is
    # the X chosen on the cast, so it has no literal to ride the payload as an
    # ordinary narrowing — it is split off into a flag the legality check reads
    # against that X, exactly as Spell Blast's counter does. Splitting it out
    # rather than leaving it on the filter is what keeps `_filter_payload` free
    # to go on refusing every *other* variable bound.
    mv_equals_x = is_mana_value_x(filt.mana_value)
    if mv_equals_x:
        # Off the *spec* as well as the local filter: `_describe_targets` below
        # builds the picker's description from the spec's own filter, so a copy
        # left behind there would refuse the line at that call instead.
        filt = dataclasses.replace(filt, mana_value=None)
        spec = dataclasses.replace(spec, filter=filt)
    payload = _filter_payload(filt)
    if mv_equals_x:
        payload["mv_equals_x"] = True
    if node.no_regen:
        payload["bypass_regeneration"] = True
    _describe_targets(payload, spec)
    return (OracleInstruction("destroy_target_permanent", "", payload),)



#: Which scratchpad record each "the <noun> <somebody> chose" phrase names.
#:
#: Two entries and they are not two cards: they are this engine's two ways of
#: making a choice, named by the seat that made it. ``back_references`` reads
#: the printed clause into the quantifier; this says what the quantifier means.
_CHOSEN_BY_RECORDS: dict[str, str] = {
    "chosen_by_you": CHOSEN_TARGET_PERMANENTS,
    "chosen_by_opponent": CHOSEN_PERMANENT,
}


def _lower_destroy_of_their_choice(
    node: ast.Destroy, spec: ast.TargetSpec, event: str | None
) -> tuple[OracleInstruction, ...]:
    """"…destroy target nonartifact creature **that player controls of their
    choice**." (The Abyss.)

    Preacher's decomposition, and for Preacher's reason: the pick belongs to a
    seat that is not the ability's controller, so it is the ordinary
    ``choose_permanent`` prompt — armed on that seat, answered into the
    resolution's scratchpad — and the destroy behind it reads the recorded id
    through ``permanents_from`` instead of a target. Both halves already exist;
    what is new is only the pairing, exactly as it was there.

    A deliberate, recorded deviation from CR 603.3d, the same one Preacher's
    branch in ``control_changes`` documents: the printed word is "target", and a
    triggered ability's targets are chosen as it is *put on the stack*. This
    engine announces an upkeep trigger's targets from one seat, so the affected
    player's pick is made at resolution instead. What that costs is the CR
    608.2b re-check and shroud on the picked creature; what the alternative
    costs is a second seat inside the upkeep step's announcement.

    Three refusals, and each is a way the phrase could otherwise mean something
    the card does not print:

    * a quantifier other than "target" — "of their choice" names one pick, and
      the prompt records one id;
    * a controller other than "that player" — "their" is a pronoun, and the
      only player this sentence has already named is the one the condition did;
    * an event that froze no seat, which is the destroy sweep's own gate
      (``_destroy_sweeps._refuse_unfrozen_that_player``) asked of the same two
      words: with no seat there is nobody to ask, and a prompt armed on nobody
      is an effect that silently does not happen.
    """
    filt = spec.filter
    if spec.quantifier != "target":
        raise LoweringError(
            "'of their choice' names one permanent to destroy", node=node
        )
    described = _filter_payload(
        filt, carried_separately=frozenset({"their_choice"})
    )
    _refuse_unfrozen_that_player(described, event, node)
    if described.get("controller") != "that_player":
        raise LoweringError(
            "'of their choice' names no player this destroy can ask", node=node
        )
    # Both lifted, not carried. Who picks is the prompt's own seat and no
    # candidate can be asked whether it is "of their choice"; whose creatures
    # may be picked is the prompt's ``controlled_by``, because
    # ``subject_matches`` refuses ``that_player`` outright — the seat is known
    # only to the resolution holding the trigger's context, which is where the
    # prompt is armed. Left in the payload either one would be a key the
    # candidate rule cannot test, which is the whole point of the gate below.
    described.pop("their_choice", None)
    described.pop("controller", None)
    if untestable_filter_keys(described):
        raise LoweringError(
            "the destroy prompt cannot test this restriction", node=node
        )
    destroy_payload: dict[str, object] = {"permanents_from": CHOSEN_PERMANENT}
    if node.no_regen:
        destroy_payload["bypass_regeneration"] = True
    return (
        OracleInstruction("sequence", "", {"steps": (
            OracleInstruction(
                "choose_permanent", "",
                {
                    "result_key": CHOSEN_PERMANENT,
                    # "**That player** … of **their** choice": one seat named
                    # twice, so the prompt is armed on the seat the firing
                    # event froze and the candidates come from that same seat's
                    # battlefield. `controlled_by` is what makes the second
                    # half a seat question rather than a filter key — the
                    # matcher answers "you control" relative to the *ability's*
                    # controller, which is the wrong player here.
                    "chooser": EVENT_SUBJECT_PLAYER,
                    "controlled_by": "chooser",
                    "filter": described,
                    "prompt": "Choose a creature you control to be destroyed.",
                },
            ),
            OracleInstruction("destroy_target_permanent", "", destroy_payload),
        )}),
    )

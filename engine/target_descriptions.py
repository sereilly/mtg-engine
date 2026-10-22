"""A lowering's ``targets`` description, read as a picker spec (CR 115.1).

The grammar records on each instruction what its printed "target ..." phrase
described — the kind of object, the quantifier and count, the narrowings —
and :func:`_from_targets_payload` turns that record into the spec the picker
raises: the kind decides which picker, and the flags beside it
(:func:`_narrowing_flags`) decide what it offers. It is the evidence that tells
Lightning Bolt ("any target") from Earthbind ("target creature with flying")
when both compile to a bare ``deal_damage``. A several-role description is
read role by role (:func:`roles_spec`, :func:`_slot_roles_spec`), each role an
ordinary description of its own; the role vocabulary is
``engine/target_roles.py``.

The kind a printed type filter means (:data:`_TYPE_FILTER_TO_KIND`) and the
graveyard spec kinds (:data:`GRAVEYARD_TARGET_KIND`, :data:`SINGLE_GRAVEYARD`)
live here because this is the lowest reader that names them. Split out of
``engine/targeting.py`` at the 2,000-line cap; a caller imports a name from
here.
"""

from __future__ import annotations

from .oracle_types import SPELL_OR_OBJECT_TARGET
from .target_roles import ROLES_TARGET_KIND, role_dependency


# An instruction's type_filter, as a target kind. Filters naming more than one
# type fall back to the general permanent picker, which then applies the filter.
_TYPE_FILTER_TO_KIND = {
    "artifact": "artifact",
    "creature": "creature",
    "land": "land",
    "enchantment": "permanent",
    "permanent": "permanent",
    "artifact_or_enchantment": "permanent",
    # "…deals 1 damage to target planeswalker." (Sparkhunter Masticore.) Its own
    # picker rather than the general permanent one: a planeswalker is the only
    # permanent type a printed phrase names this often *without* also admitting
    # creatures, and offering every permanent would be a prompt the resolution
    # then refuses.
    "planeswalker": "planeswalker",
}


def _kind_for_type_filter(type_filter) -> str | None:
    """*type_filter* as a target kind, or None when nothing describes it.

    A filter may name a *union* of types — Icy Manipulator's "target artifact,
    creature, or land" lowers to ``["artifact", "creature", "land"]``. No single
    picker matches a union, so it takes the general permanent picker and
    ``permanent_matches_filter`` narrows it back down at enumeration time, the
    same way it does at resolution.
    """
    if isinstance(type_filter, (list, tuple)):
        return "permanent"
    return _TYPE_FILTER_TO_KIND.get(type_filter)


def _narrowing_flags(source: dict) -> dict:
    """The picker-narrowing flags *source* (a filter or a payload) carries.

    These are the restrictions the enumerator itself applies
    (`_permanent_matches_target_kind`), as opposed to the ones it delegates to
    the instruction's own filter through `_ability_target_legal`. Both are read
    from the same compiled payload; only the vocabulary differs.
    """
    flags: dict = {}
    # `blocked_only` joined the three when General Jarkeld printed "two target
    # **blocked** attacking creatures". Left out, the word parsed, rode the
    # instruction's own filter to resolution and was dropped by the picker: the
    # ability could be activated naming an unblocked attacker, which is the
    # wider-than-printed reading CR 602.2b exists to refuse before anything is
    # paid. `unblocked_attacker` beside it in the enumerator is Forcefield's
    # spelling of the other half.
    for key in (
        "attacking_only", "blocked_only", "blocking_only", "flying_only",
        # "target creature **you cast this turn**" (Cycle of Life). Here rather
        # than left to the instruction's own filter for ``blocked_only``'s
        # stated reason: a narrowing the picker does not apply is one the
        # player can announce past, and CR 602.2b refuses the activation
        # before anything is paid rather than after.
        "cast_by_you_this_turn",
    ):
        if source.get(key):
            flags[key] = True
    # "…by **target unblocked creature**" (Mirror Strike, Gossamer Chains). The
    # filter's ``unblocked_only`` is the picker's ``unblocked_attacker`` —
    # Forcefield's flag, which the enumerator already applies. An activation
    # also asks the instruction's own filter, so Gossamer Chains was already
    # honoured; a *cast* asks only these flags, and without this one Mirror
    # Strike offered (and its announcement gate admitted) a blocked creature.
    if source.get("unblocked_only"):
        flags["unblocked_attacker"] = True
    # "Untap target creature **with power less than the number of cards in your
    # graveyard**" (Temporary Insanity). Carried by value on the spec root
    # beside ``cast_by_you_this_turn`` and for its reason: the bound is a count
    # of the *choosing seat's* pile, so the enumerator answers it with the
    # observer it holds — under ``filter`` it would be asked with none and
    # offer nothing. CR 601.2c's gate and CR 608.2b's re-check read this spec,
    # so a graveyard that shrank in response makes the target illegal.
    pile_bound = source.get("power_vs_count")
    if pile_bound:
        flags["power_vs_count"] = dict(pile_bound)
    # Carried by value, not flattened to a flag: "attacking or blocking" and
    # "tapped or blocking" are the same key with different words in it, and a
    # bare True would tell the picker a union applies without saying which one.
    any_states = source.get("any_states")
    if any_states:
        flags["any_states"] = list(any_states)
    # "…target attacking or blocking creatures **without flying**" (Rock
    # Slide). Carried by value beside the union above and for its reason: which
    # keyword is excluded is the narrowing, and a bare True would tell the
    # picker that something is excluded without saying what.
    #
    # Here rather than left to the instruction's own filter for
    # ``blocked_only``'s stated reason: a narrowing the picker does not apply is
    # one the player can announce past — and for a *cast* this same spec is
    # what CR 601.2c checks, so the announcement was legal too.
    without = source.get("without_keywords")
    if without:
        flags["without_keywords"] = list(without)
    if source.get("subtype_filter") == "wall":
        # The picker's name for a Wall subtype filter (Ali Baba, Dwarven
        # Demolition Team). Kept as a flag rather than left to the instruction
        # filter so a Wall-only prompt reads the same whether the narrowing
        # came from the ability's payload or from an Aura's "Enchant Wall".
        flags["wall_only"] = True
    color = source.get("color_filter")
    if color:
        flags["color_filter"] = color
    if source.get("controller") == "you":
        # "target creature you control". The enumerator applies this one itself
        # (it is a seat test, not a permanent test), and it has to: a picker
        # that offered an opponent's creature would let a player choose a target
        # the effect then declines to affect, with nothing on screen saying why.
        flags["own_only"] = True
    elif source.get("controller") in ("opponent", "not_you"):
        # "target creature **you don't control**" (Provoke) is the same seat
        # test: CR 102.2 makes every other player an opponent, and this engine
        # has no teammates. Left off, Provoke could be aimed at its caster's own
        # creature and still drew its card.
        #
        # "target artifact **an opponent controls**" (Hyperion Blacksmith). The
        # mirror of `own_only` and a seat test for the same reason, so it is the
        # picker's job rather than the permanent matcher's. Without it the
        # narrowing had nowhere to go: `permanent_matches_filter` cannot answer
        # a controller, so the lowering refused the line outright rather than
        # let a "an opponent controls" ability untap the activator's own
        # artifact — a restriction dropped in the player's favour.
        flags["opponent_only"] = True
    elif source.get("controller") == "defending_player":
        # "target artifact **defending player controls**" (Floral Spuzzem).
        # The third seat test, and the one the enumerator cannot answer on its
        # own: "you" and "opponent" are relative to the seat choosing, while
        # this one is relative to the *combat* the ability's trigger fired in.
        # So the flag says the narrowing exists and the caller that knows the
        # attack — the trigger's announcement — supplies the seat beside it.
        # With no seat supplied the enumerator offers nothing, which is the
        # safe direction: an unanswerable narrowing must never widen to "any".
        flags["defending_player_only"] = True
    elif source.get("controller") == "that_player":
        # "up to two target creatures **that player** controls" (Fatal Lore).
        # The fourth seat test, and `defending_player_only`'s exact shape one
        # record over: the seat is not relative to whoever is choosing but to
        # something the *announcement* froze — there, the combat; here,
        # CR 700.2e's mode choice. Two flags rather than one because they are
        # two printed phrases reading two different records, and a caller that
        # can supply one usually cannot supply the other.
        #
        # With no seat beside it the enumerator offers nothing, for that flag's
        # stated reason: an unanswerable narrowing must never widen to "any",
        # and this one widens to *every creature in the game*.
        flags["that_player_only"] = True
    if source.get("enchanted_only"):
        # "destroy target **enchanted** creature" (Ramses Overdark) — the
        # positive twin of ``not_enchanted`` below, and a picker flag for the
        # same reason: the enumerator narrows with the same matcher the handler
        # re-asks at resolution, so what is offered and what is destroyed cannot
        # disagree.
        flags["enchanted_only"] = True
    if source.get("not_enchanted"):
        # "target permanent **that isn't enchanted**" (Time Elemental) —
        # CR 303.4a. A picker flag rather than a restriction left to the
        # handler, and for the reason ``own_only`` above gives: the handler
        # already refuses an enchanted permanent at resolution, so a picker that
        # offered one would let a player tap the Elemental and pay {2}{U}{U} for
        # a bounce that then returns nothing, with nothing on screen saying why.
        flags["not_enchanted"] = True
    if source.get("exclude_self"):
        # "up to two **other** target creatures you control" (Basri's Acolyte),
        # "**another** target creature" as a fight's opponent (Brash Taunter).
        # Same argument as `own_only` directly above, and it had the same gap in
        # the other direction: every handler carrying this key already refuses
        # the source at resolution (pump.py, zones.py, damage.py), so a picker
        # that omitted it offered a target the effect then declined to affect.
        # `legality.py` has honoured `exclude_source` all along — nothing read
        # the filter key into it.
        flags["exclude_source"] = True
    if source.get("exclude_attached"):
        # "…to **another** target creature" on an Aura (Farrel's Mantle). The
        # same word about a different object: the creature dealing the damage
        # is the one the Aura is attached to, so the picker excludes the host
        # rather than the source. A flag of its own because the two exclude
        # different permanents, and the Aura was never on the list anyway.
        flags["exclude_attached"] = True
    if source.get("blocked_by_source"):
        # "target creature **it's blocking**" (Goblin Snowman, Tinder Wall).
        # A relation to the ability's own source, so the enumerator applies it —
        # it holds the source, and ``permanent_matches_filter`` could not answer
        # it from the candidate alone. Without the flag the picker offered every
        # creature on the board for a ping the card aims at exactly one.
        flags["blocked_by_source"] = True
    if source.get("blocking_source"):
        # "target creature **blocking this creature**" (Barbed-Back Wurm). The
        # mirror of the flag above and the enumerator's for its reason exactly:
        # the relation is to the ability's own source, which the loop holds and
        # the candidate alone cannot answer. Without the flag the picker offers
        # every creature on the board for an ability aimed at the ones in front
        # of it.
        flags["blocking_source"] = True
    if source.get("attacking_you"):
        # "target creature **that's attacking you**" (Ice Floe, Snow Fortress).
        # A seat test like ``own_only`` — which player the creature was declared
        # against — and the enumerator's for the same reason: the seat choosing
        # is the one it is relative to.
        flags["attacking_you"] = True
    if source.get("attacked_you_this_turn"):
        # "target … creature **that attacked you this turn**" (Jabari's
        # Influence). The record behind the flag above, and carried for its
        # reason exactly: the seat choosing is the one it is relative to, and
        # a picker without it offers every creature on the board.
        flags["attacked_you_this_turn"] = True
    # A printed subtype or supertype narrowing, carried whole under ``filter``
    # — the spec form `spec_only_subtype` already reads and the enumerator
    # already applies through ``subject_matches`` (legality's own loop), so the
    # picker offers exactly what resolves. "X target **Mountains**" (Volcanic
    # Eruption) and "X target **snow** lands" (Avalanche) both rode only the
    # instruction's payload before this, which the per-candidate cast probe
    # does not ask for a several-target description — so the picker offered a
    # Forest for a spell that destroys Mountains. A Wall stays on ``wall_only``
    # above, its established spelling, rather than being said twice.
    narrowed: dict = {}
    subtype = source.get("subtype_filter")
    if isinstance(subtype, str) and subtype != "wall":
        narrowed["subtype_filter"] = subtype
    supertypes = source.get("supertypes")
    if supertypes:
        narrowed["supertypes"] = list(supertypes)
    # The negations travel with them. "Target **nonsnow** basic land" (Arcum's
    # Weathervane) is one description, and carrying the "basic" while dropping
    # the "nonsnow" offers a superset — the picker would list the snow lands
    # the ability then refuses. Both keys are in
    # ``TESTABLE_SUBJECT_FILTER_KEYS``, so the enumeration can ask them; a
    # narrowing the matcher could not test would have to stay off the spec
    # rather than ride it unenforced.
    for key in ("exclude_supertypes", "exclude_subtypes"):
        excluded = source.get(key)
        if excluded:
            narrowed[key] = list(excluded)
    # And the colour **exclusion**, for the same reason one sentence up.
    # "Destroy two target **nonblack** creatures" (Reckless Spite, Dregs of
    # Sorrow) is a several-target announcement, so no arm of
    # ``_validate_cast_targets`` sees it: ``primary`` is the ``sequence``
    # wrapper the card's second printed sentence makes, which is exactly the
    # shape ``cast_target_refusal`` exists for -- and that gate reads this
    # spec. Left off it, the caster could name a black creature, the
    # announcement was accepted, and the resolution then silently dropped the
    # slot -- a target list shorter than the X that was paid for, refused
    # nowhere (CR 601.2c).
    #
    # ``exclude_colors`` is in ``TESTABLE_SUBJECT_FILTER_KEYS`` and is answered
    # off the permanent's layer-5 colours, so the enumeration asks it exactly
    # as it asks the type exclusions above. Its **positive** twin is not here:
    # ``color_filter`` already rides the spec root and
    # ``_permanent_matches_target_kind`` tests it there, so a copy under
    # ``filter`` would be one printed word with two readers -- the fork this
    # module's own comments keep naming. The negative had no root form at all,
    # which is why it needed one here rather than a second one.
    # …and every other narrowing a candidate can be asked about **on its own**.
    # ``OBJECT_ONLY_FILTER_KEYS`` is the exact boundary: the enumerator's loop
    # calls ``subject_matches(perm, spec["filter"], defending=…)`` with no
    # observer and no source, so a seat-relative key here would be *refused*
    # and the picker would offer nothing at all. That is why the seats have
    # their own spec flags (``own_only``, ``opponent_only``,
    # ``that_player_only``) and are not carried here.
    #
    # Five keys, and a card behind each. Every one was riding the instruction
    # payload and reaching neither the picker nor CR 601.2c's gate, because
    # ``primary`` on these cards is the ``sequence`` their second printed
    # sentence makes and so no arm of ``_validate_cast_targets`` ever saw them:
    #
    #   exclude_types     Ashes to Ashes ("two target **nonartifact**
    #                     creatures"), Secure the Scene, Broken Visage,
    #                     Jabari's Influence
    #   with_keywords     Vertigo ("target creature **with flying**") — the one
    #                     of the five that was wrong in the *player's* favour:
    #                     the spell dealt its 2 damage to a vanilla Bear and
    #                     killed it
    #   untapped_only     Energy Tap ("target **untapped** creature you
    #                     control")
    #   not_attacking     Alarum ("target **nonattacking** creature")
    #
    # The other four were the harmless direction — the announcement was
    # accepted and the resolution then affected nothing, so the spell was spent
    # for no effect. CR 601.2c makes that an *illegal announcement*, refused
    # before mana is paid, rather than an ineffective spell.
    # ``without_keywords`` is deliberately absent, ``color_filter``'s reason
    # exactly: it already rides the spec **root** and
    # ``_permanent_matches_target_kind`` tests it there (Rock Slide, Pit Trap,
    # Ice Floe), so a copy under ``filter`` would be one printed word with two
    # readers. ``with_keywords`` had no root form at all, which is why it needs
    # one here rather than a second one. ``any_states`` is absent for the same
    # reason as ``without_keywords``.
    for key in (
        "exclude_colors", "exclude_types", "with_keywords",
        "untapped_only", "not_attacking",
    ):
        value = source.get(key)
        if value:
            narrowed[key] = list(value) if isinstance(value, (list, tuple)) else value
    # "Exile target creature **with the greatest power among creatures on the
    # battlefield**." (Topple.) Not object-only — the extreme is read off the
    # whole board — but the enumerator's loop holds the game, which is all the
    # printed comparison set asks for: "creatures on the battlefield" names no
    # seat. A set that did ("among creatures you control") would find no
    # observer here and offer nothing, the direction that cannot widen a target
    # description. Without it the picker offered every creature and CR 601.2c's
    # gate, which reads this spec, accepted a target the resolution then
    # declined to exile.
    superlative = source.get("superlative_among")
    if superlative:
        narrowed["superlative_among"] = superlative
    # "Exile target creature **with power 2 or less**." (Last Breath.) A printed
    # P/T bound is a property of the candidate alone, so the enumeration can ask
    # it like any key above — and it has to, for the reason the five keys above
    # give: on a spell whose ``primary`` is a ``sequence`` no arm of
    # ``_validate_cast_targets`` ever saw it, so a Hill Giant was a legal
    # announcement, nothing was exiled, and CR 608.2b (which re-asks this spec)
    # could not call the target illegal. An **integer** bound only: "mana value
    # X or less" (Dominate) is substituted from the announcement by the cast
    # gate, and a bound the enumeration cannot evaluate must stay off the spec
    # rather than ride it unanswerable.
    for key in ("power", "toughness"):
        bound = source.get(key)
        if isinstance(bound, dict) and isinstance(bound.get("value"), int):
            narrowed[key] = dict(bound)
    if narrowed:
        flags["filter"] = narrowed
    return flags


#: The narrowings a **graveyard** role carries, and the whole of what separates
#: one from the battlefield roles beside it.
#:
#: Every name here is one ``handlers/_filters.graveyard_card_matches`` already
#: reads, which is the point: the picker, the announcement gate and the CR
#: 608.2b re-check ask that one predicate, so a role described in this module's
#: own spelling would be a fourth reading of "which cards may be chosen" — the
#: shape this repo keeps finding on the wrong side of.
_GRAVEYARD_ROLE_KEYS = (
    "any_card", "card_type", "card_types",
    "graveyard_colors", "graveyard_subtypes", "graveyard_mana_value",
    "supertypes", "own_graveyard_only", "opponent_graveyard_only",
)


def roles_spec(targets: dict) -> dict | None:
    """The ordered-role spec a ``kind: "roles"`` description means.

    Each role is itself an ordinary object description, so it goes through the
    same :func:`_from_targets_payload` every one-target spell does — the picker
    flags a role carries mean exactly what they mean anywhere else, and a
    narrowing added to that reader reaches a role for free.

    ``depends_on`` is lifted out of the role's own key so every consumer asks
    one question ("which earlier role settles this one?") rather than knowing
    the vocabulary of relations. The relation *key* travels beside it, because
    the enumerator has to know not merely that there is a dependency but what
    it asks of the pair.
    """
    roles: list[dict] = []
    for entry in targets.get("roles") or ():
        if not isinstance(entry, dict):
            return None
        described = _from_targets_payload({**entry, "kind": entry.get("kind", "object")})
        if described is None:
            return None
        described["role"] = entry.get("role")
        relation, depends_on = role_dependency(entry)
        if relation is not None:
            described["relation"] = relation
            described["depends_on"] = depends_on
        roles.append(described)
    if len(roles) < 2:
        # One role is not a roles description — it is an ordinary one-target
        # spell wearing a shape nothing else reads. Refusing here rather than
        # flattening it keeps the two shapes from both being able to mean the
        # same spell.
        return None
    return {"kind": ROLES_TARGET_KIND, "roles": roles}



def _carry_player_comparison(spec: dict, targets: dict) -> None:
    """Carry "…who controls more creatures than they do" onto *spec*.

    A whole clause rather than a flag, which is the only difference from the
    three narrowings beside it: what is counted, in which direction, by how
    much and against whom are four printed facts, and the seat loop needs all
    four to answer any of them. Carried whole for that reason — a spec keeping
    three of them would be a picker enforcing a comparison the card did not
    print.

    Written by both player kinds through one call, because "target opponent who
    has more life than you do" and "target player or planeswalker" narrowed the
    same way are one sentence with a wider slot, and a key honoured for one
    kind and forgotten for the other is a restriction that depends on which
    noun the card printed.
    """
    compared = targets.get("compared")
    if compared:
        spec["compared"] = compared
    # "**That player** chooses target player…" — who announces, when the card
    # names somebody other than the ability's controller (CR 601.2c). Carried
    # beside the clause it goes with: the seat that picks and the seat the
    # comparison is against are the same player on every card that prints
    # either, and a spec carrying one without the other would ask the wrong
    # player a question about the right board.
    chooser = targets.get("chooser")
    if chooser:
        spec["chooser"] = chooser


def slot_list_is_exact(targets: dict) -> bool:
    """Whether a ``targets`` description is a slot list that must be named in
    full — one mandatory target per printed instance of the word (CR 601.2c).

    "Target creature gets +2/+2 … **Another** target creature gets -2/-2"
    (Consume Strength). The several-slot shape with the bare quantifier
    ``target`` and no slot the card lets the caster leave empty
    (``optional_slots``, Primal Might's "up to one"). One predicate for the two
    readers that have to agree about it: the picker's ``exact_targets`` flag
    just below, and ``legality.exact_target_count``, which the cast gate counts
    an announcement against. Asked of one and not the other it is a confirm
    button that waits for two targets in front of an engine that takes one.
    """
    slots = targets.get("filters")
    count = targets.get("count")
    return (
        targets.get("quantifier") == "target"
        and isinstance(slots, list) and len(slots) > 1
        and isinstance(count, int) and not isinstance(count, bool)
        and count == len(slots)
        and not targets.get("optional_slots")
    )


def _slot_roles_spec(targets: dict, slot_filters: list) -> dict | None:
    """A roles spec for a multi-slot description whose slots differ, or None.

    "Target creature you control fights target creature **an opponent
    controls**" (Triangle of War); "target creature **with the chosen ability**
    … and another target creature" (Phyrexian Splicer). Two slots, two different
    printed restrictions, and one announcement (CR 601.2c).

    **A shared list cannot say it.** This used to intersect the per-slot
    narrowing flags — right, given a single list, because a flag only one slot
    has would hide a target the other slot legitimately admits — but the
    intersection of "you control" and "an opponent controls" is *nothing*, so
    the picker offered every creature for both slots, the announcement gate read
    that same over-wide list and admitted it, and the cost was paid. Eight cards
    were in that state, six of them with a controller restriction enforced by
    nothing at all.

    Roles are the shape already built for it: ``legality_roles._role_target_walk``
    enumerates slot *n* with slots 0…n-1 settled, which gets each slot its own
    filter, gets CR 601.2c's distinctness for free (a permanent taken by an
    earlier role is not offered to a later one), and makes the picker and the
    gate one call. The description is left untouched, so no compiled program
    moves and every handler goes on reading ``filters`` positionally — the
    answers arrive in role order, which is slot order.

    None when the slots do **not** differ, which is the ordinary several-target
    spell ("Destroy two target creatures") and is honestly one list.

    The role *name* is positional. Nothing renders it — the browser labels a
    role by its ``kind`` and its step ("Choose the creature for Triangle of War
    (2 of 2)") — and these slots often share a printed noun, which is exactly
    what ``describe_independent_target_roles`` refuses to name.
    """
    if all(slot == slot_filters[0] for slot in slot_filters[1:]):
        return None
    if targets.get("optional_slots"):
        # "…it fights **up to one** target creature an opponent controls"
        # (Primal Might). CR 601.2c lets that slot be left empty, and a roles
        # walk has no way to say so — every role is answered or the announcement
        # is refused. Converting it would turn an optional target into a
        # required one, which is a *different* wrongness rather than a smaller
        # one: the shared list at least lets the card be cast the way it prints.
        #
        # So the shared-list reading stays for these, with its own narrowing
        # loss intact, and the remainder is recorded in SET_PLAYBOOK's Known
        # gaps rather than papered over. An optional role is the piece that
        # closes it.
        return None
    roles: list[dict] = []
    for position, slot in enumerate(slot_filters):
        described = _from_targets_payload({
            "quantifier": "target", "kind": "object", "filter": slot or {},
        })
        if described is None:
            # A slot this reader cannot describe would be enumerated as
            # "anything", which is the widening this function exists to remove.
            # Refuse the whole conversion rather than build a spec that is right
            # about one slot and silent about the other.
            return None
        described["role"] = f"slot_{position}"
        roles.append(described)
    return {"kind": ROLES_TARGET_KIND, "roles": roles}


def _from_targets_payload(targets) -> dict | None:
    """The spec from a grammar-lowered ``targets`` description.

    This is the evidence the legacy rules never recorded: it is what tells
    Lightning Bolt ("any target") apart from Earthbind ("target creature with
    flying") when both compile to a bare ``deal_damage``.
    """
    if not isinstance(targets, dict):
        return None
    kind = targets.get("kind")
    if kind == "card":
        # A card in a graveyard is not a permanent (CR 115.2), and this function
        # only knows how to describe permanents, players and the stack. The
        # instruction that carries such a description settles its own spec in
        # `_KIND_TO_SPEC_FROM_PAYLOAD`; answering here would hand the picker a
        # battlefield when the effect reads a graveyard.
        return None
    if kind == "graveyard_card":
        # One **role** of a several-role announcement whose object is a card in
        # a graveyard (Goblin Welder's second slot). Read here rather than
        # under ``kind == "card"`` above, which refuses: that shape carries no
        # description of its own and leaves the spec to the instruction's own
        # kind, while a role *is* the description — a roles walk enumerates
        # slot by slot and has nothing else to ask.
        #
        # The keys are the ones ``graveyard_card_matches`` reads, copied rather
        # than re-derived, so the picker offers exactly what the announcement
        # gate admits and the resolution re-checks.
        described = {"kind": GRAVEYARD_TARGET_KIND}
        for key in _GRAVEYARD_ROLE_KEYS:
            if key in targets:
                described[key] = targets[key]
        return described
    if kind == "roles":
        return roles_spec(targets)
    if kind == "any":
        spec = {"kind": "any"}
        # "…to any target **of their choice**" (Pandemonium). Who announces,
        # carried onto CR 115.4's union exactly as it is carried onto the two
        # player kinds below, through the same reader: the seat that picks is a
        # printed fact about the sentence and not about which noun the slot
        # admits, so a kind that dropped it would hand the choice to the
        # ability's controller — the one seat this card says does not make it.
        _carry_player_comparison(spec, targets)
        return spec
    if kind == "divided":
        # Fireball: "X damage divided evenly … among any number of targets".
        # The UI picks the targets and X follows from how many were chosen, so
        # this is its own prompt rather than a repeated "any target".
        spec = {"kind": "divided", "division": targets.get("division", "evenly")}
        # "…among any number of **target creatures**" (Fire Covenant). The
        # printed noun, carried through so the picker offers what the card
        # names — without it the seat loop in `legality_enumeration._enumerate_targets`
        # offers both players' faces, which is a legal Fire Covenant target
        # only in an engine that never read the noun.
        narrowing = targets.get("filter") or {}
        if narrowing.get("type_filter") == "creature":
            spec["creatures_only"] = True
        # "…among any number of target **attacking or blocking creatures
        # without flying**" (Rock Slide). The noun is not the whole phrase, and
        # everything past it was being dropped: the picker offered an idle
        # creature and a flyer for a spell that names neither, and CR 601.2c's
        # cast check reads this same spec, so the announcement was legal too.
        #
        # Read through ``_narrowing_flags``, the one reader every other kind
        # already asks, so a divided spell's picker narrows by exactly what a
        # single-target one does — which is the property that made this
        # omission invisible: no card had printed a divided target with a
        # narrowing the flags carry until now.
        spec.update(_narrowing_flags(narrowing))
        # "…to **each of X targets**" (Firestorm) / "…and 3 damage to **a third
        # target**" (Cone of Flame). How many targets the *card* prints, where
        # every other divided spell leaves the number to the caster. Carried as
        # the raw description value — a number, or the string "x" for a count
        # the caster announces (CR 107.3a) — because the picker, the AI and the
        # cast gate each resolve it against a different thing they know: the
        # browser against the X box, the policy against the X it chose, the gate
        # against the X that was announced.
        #
        # A separate key from ``max_targets`` above, which is a *ceiling* on a
        # count the caster still chooses (Contagion's "one or two"). Folding the
        # two together would let a Firestorm announced with one target past a
        # gate that only ever asked "not too many".
        printed_count = targets.get("target_count")
        if printed_count is not None and not isinstance(printed_count, bool):
            spec["divided_target_count"] = printed_count
        # **What each position of the list is**, for a picker to say as the
        # caster clicks (``_targets.card_divided_target_description``). The
        # sentence's own roles where it gives its targets different jobs
        # (Captain's Maneuver: the protected end, then the taker), and the
        # printed shares where it gives them different amounts — "1 damage to
        # any target, 2 damage to another target, and 3 damage to a third
        # target" (Cone of Flame) is read by position exactly as the redirect
        # is, and the first click is the one that gets 1. Absent wherever the
        # positions are interchangeable, which is every other divided spell.
        named = targets.get("target_roles")
        shares = targets.get("shares")
        if isinstance(named, (list, tuple)) and named:
            spec["target_roles"] = [str(name) for name in named]
        elif isinstance(shares, (list, tuple)) and len(set(shares)) > 1:
            spec["target_roles"] = [f"target that gets {share}" for share in shares]
        if printed_count == "x":
            # "…to **each of X targets**" (Firestorm). X *is* how many targets
            # were chosen, so the caster is never asked for it separately —
            # picking the targets is announcing it. ``x_equals_targets`` is the
            # client's own name for exactly that, read by ``app.js`` since
            # Volcanic Eruption and emitted by nothing until now: that card's
            # spec turned out to be a ``land`` picker with ``x_targets``, so the
            # branch has never run. This is the first card whose sentence means
            # it, which is also why the flag is set here and not wherever a
            # count happens to be "x" — an announcement the caster makes
            # separately (Winter Blast's "X target creatures") is a different
            # question with the same letter in it.
            spec["x_equals_targets"] = True
        bound = targets.get("max_targets")
        if isinstance(bound, int):
            # "…among **one or two** target creatures" (Contagion). A divided
            # spell is otherwise unbounded, so the picker would offer a third
            # creature the casting path then refuses (CR 601.2c). Carried as
            # the same ``max_targets`` key every other picker spec uses rather
            # than a divided-only spelling — the client already reads it.
            spec["max_targets"] = bound
        return spec
    if kind == "player":
        spec = {"kind": "player"}
        if targets.get("attacked_this_turn"):
            # "target player **who attacked this turn**" (Fire and Brimstone) —
            # the printed narrowing, carried to the seat loop that enforces it.
            spec["attacked_this_turn"] = True
        if targets.get("opponents_only"):
            # "Target opponent" — the caster's own seat is not a legal answer
            # (CR 102.2/102.3). The same flag Word of Command's kind-table entry
            # carries, enforced by legality's seat check.
            spec["opponents_only"] = True
        if targets.get("damaged_by_source"):
            # "…**previously dealt damage by it**" (Diseased Vermin). Carried to
            # the same seat loop for the same reason the two flags above are: it
            # is the picker that enforces a printed narrowing, and an ability
            # whose restriction stops at the parser is one that hits anybody.
            spec["damaged_by_source"] = True
        _carry_player_comparison(spec, targets)
        return spec
    if kind == "player_or_planeswalker":
        # Chandra's Magmutt: player faces plus planeswalker permanents — the
        # "any" picker minus its creature half.
        spec = {"kind": "player_or_planeswalker"}
        if targets.get("opponents_only"):
            # "Target **opponent** or planeswalker" (Eternal Flame): the same
            # union with the caster's own seat struck out (CR 102.2/102.3), carried on
            # the same flag the plain player picker above reads. Legality's seat
            # loop already asks it for this kind; without it here the flag never
            # reaches the loop and the caster is offered as a legal target.
            spec["opponents_only"] = True
        _carry_player_comparison(spec, targets)
        return spec
    if kind == "spell":
        # A spell on the stack, which the UI picks from a different zone than
        # any permanent — "stack" is the name for that picker.
        spec: dict = {"kind": "stack"}
        card_types = targets.get("card_types")
        if card_types:
            # "Target **instant or sorcery** spell becomes the color of your
            # choice." (Vodalian Mystic.) The printed union, handed to the
            # enumeration under the key the counter's own spec uses
            # (``_counter_spec``), so a described spell target and a counter
            # narrow the picker through one reader.
            spec["stack_card_types"] = list(card_types)
        # A **spell role** carries what narrows it in the picker's own keys
        # (``lowering/_roles._spell_role_description``): a counter keeps its
        # colour and type on its payload, not in ``targets``, so the role was
        # stamped with the step's derived ``stack_*`` flags and they are handed
        # straight back. Absent on every description that is not a role.
        for key, value in targets.items():
            if key.startswith("stack_"):
                spec[key] = value
        return spec
    if kind == SPELL_OR_OBJECT_TARGET:
        # "Target **spell or permanent** becomes the color of your choice until
        # end of turn." (Illusion, Blind Seer.) One object in one of two zones
        # — the picker the Lace cycle's kind row (``_KIND_TO_SPEC``) has always
        # answered with, reached here by a card that *describes* the union.
        # Bare, because the lowering admits no narrowing beside it.
        return {"kind": "spell_or_permanent"}
    if kind != "object":
        return None
    filt = targets.get("filter") or {}
    # A description whose slots are *differently* restricted carries one filter
    # per slot, and a single shared list cannot express it: a narrowing may only
    # be applied to that list when **every** slot has it, so a slot's own
    # restriction is simply dropped. The spec becomes ordered **roles** instead,
    # one per slot, which is the shape built for exactly this question.
    slot_filters = targets.get("filters")
    if isinstance(slot_filters, list) and len(slot_filters) > 1:
        roles = _slot_roles_spec(targets, slot_filters)
        if roles is not None:
            return roles
        # Still one shared list: either the slots agree, or one of them is
        # optional and roles cannot say so. A narrowing may then only be applied
        # when **every** slot has it — a flag only one slot carries would hide a
        # target another slot legitimately admits, which is what kept Garruk,
        # Savage Herald's -2 from ever biting an opponent's creature. That loses
        # a slot's own restriction, which is the whole reason the roles
        # conversion above exists; it survives here only for the shapes that
        # cannot take it.
        per_slot = [_narrowing_flags(slot or {}) for slot in slot_filters]
        flags = {
            key: value
            for key, value in per_slot[0].items()
            if all(other.get(key) == value for other in per_slot[1:])
        }
    else:
        flags = _narrowing_flags(filt)
    # "Up to N target …", N > 1. The picker has to know the maximum, or it would
    # collect one target for a spell that names several — which is what the
    # instruction's own lowering refuses to emit until a handler reads a list.
    # Absent for every one-target description, so nothing downstream has to
    # special-case the common shape.
    # **How many printed instances of the word "target" this description is.**
    # CR 115.3 turns on exactly that: "the same target can't be chosen multiple
    # times for any one instance of the word 'target'", and one object may be
    # chosen once per instance where a sentence prints several. A slot list is
    # the several-instance shape ("target creature you control ... up to one
    # target creature you don't control", Primal Might), and a bare plural count
    # is the one-instance shape ("**two target** nonartifact creatures", Ashes
    # to Ashes). So the list is the discriminator, and it is already here.
    several_instances = isinstance(slot_filters, list) and len(slot_filters) > 1
    count = targets.get("count")
    if isinstance(count, int) and count > 1:
        flags = {**flags, "max_targets": count}
        # "Exile **two** target artifacts" (Dust to Dust) against "Return **up
        # to two**" (Sanguine Indulgence): CR 601.2c lets the second announce
        # fewer and does not let the first, and the grammar has told the two
        # apart since it parsed them — `quantifier` is "exactly" or "up_to".
        # The spec dropped the distinction and reported both as a maximum, so
        # the picker offered "up to 2" for a card that prints a number.
        if targets.get("quantifier") == "exactly" or slot_list_is_exact(targets):
            flags = {**flags, "exact_targets": True}
        if targets.get("same_controller"):
            # "Choose two target creatures **controlled by the same
            # opponent**." (Retribution, CR 601.2c.) A relation over the whole
            # announcement, which is why it travels beside ``max_targets``
            # rather than inside the per-candidate filter: enumerating
            # candidates one at a time can never see it, and the gate that
            # checks what the caster *named* is where it is answered.
            flags = {**flags, "same_controller": True}
    elif isinstance(count, dict):
        # "Destroy target artifact. **For each additional {1}{R} you paid**,
        # destroy another target artifact…" (Primitive Justice). CR 601.2c fixes
        # the number of targets as the spell is announced, and here that number
        # is a function of the CR 601.2b payment announced one step earlier — so
        # there is no maximum to write down, only the arithmetic. Carried whole,
        # for the reason `x_targets` is a flag rather than a number one branch
        # down: how many the caster may name depends on what they announce, and
        # this spec is built from the card alone.
        #
        # The picker resolves it through `oracle_types.cost_target_count`, the
        # same reader `legality_cast_gates.cast_target_refusal` gates the announcement
        # with — a second arithmetic would be a picker offering a count the
        # engine then refuses.
        flags = {**flags, "cost_targets": count, "exact_targets": True}
        if targets.get("distinct"):
            # The printed "**another**" (CR 601.2c). Beside the count rather
            # than inside the per-candidate filter for `same_controller`'s
            # reason: it is a relation over the whole announcement, and an
            # enumeration that looks at one candidate at a time can never see
            # it.
            flags = {**flags, "distinct_targets": True}
    elif count == "x":
        # "**X** target creatures" (Part Water, Winter Blast). The count is the
        # announced X, so there is no number here to be a maximum — and saying
        # nothing at all left the picker on its one-target default, which is
        # how Winter Blast came to tap a single creature in the browser while
        # its handler had read a list since round 23. Reported as a flag rather
        # than a number: how many the caster may name depends on what they can
        # pay, which is knowable at the picker and nowhere earlier.
        flags = {**flags, "x_targets": True}
    elif targets.get("unbounded"):
        # "One or more target creatures" names no maximum. `legality.py` turns
        # this into a `max_targets` once it knows how many legal targets exist,
        # which is the same route Drafna's Restoration's "any number of" takes.
        flags = {**flags, "unbounded_targets": True}
    # CR 115.3, for every shape above that lets one announcement name more than
    # one object: the plural count, the announced X ("**X** target creatures",
    # Winter Blast) and the unbounded list ("**one or more** target creatures").
    # All three are one printed instance of the word, so no object may be named
    # twice — and the gates read this one flag rather than re-deriving the
    # question from three different keys.
    #
    # Where the sentence really does print several instances, the default flips
    # to the rule's other half (one object may be chosen once per instance) and
    # only the card's own "**another** target" forbids a repeat, which is the
    # ``distinct`` the grammar has always carried. The ``cost_targets`` branch
    # above sets this from that same key and is left alone: it is several
    # instances by construction ("destroy another target artifact", Primitive
    # Justice).
    if (
        flags.get("max_targets") not in (None, 1)
        or flags.get("x_targets")
        or flags.get("unbounded_targets")
    ) and (targets.get("distinct") if several_instances else True):
        flags = {**flags, "distinct_targets": True}
    type_filter = filt.get("type_filter")
    if not type_filter:
        # "X target **Mountains**" (Volcanic Eruption) prints no card type at
        # all — but CR 205.3i puts every land subtype on lands and nothing
        # else, so a bare land-subtype filter is a land target and the picker
        # should offer lands, not every permanent. The subtype itself is still
        # enforced by the gate and the handler, exactly as Avalanche's snow
        # supertype is: the spec is the picker's hint, and the engine re-checks
        # the announcement against the whole filter either way.
        subtype = filt.get("subtype_filter")
        if isinstance(subtype, str):
            from .grammar.vocabulary import LAND_TYPES

            if subtype in LAND_TYPES:
                return {"kind": "land", **flags}
        # A targeted object with no type restriction is any permanent.
        return {"kind": "permanent", **flags}
    derived = _kind_for_type_filter(type_filter)
    if derived is None:
        return None
    if derived == "permanent" and type_filter != "permanent":
        # **The head noun the picker's kind could not carry.** A union ("target
        # artifact, creature, **or** land") and the nouns with no picker of
        # their own ("target **enchantment**", "artifact or enchantment") all
        # fall back to the general permanent picker, whose docstring promised
        # that the filter "narrows it back down at enumeration time" — and for a
        # *spell* nothing did: an ability's enumeration delegates to its own
        # instruction filter, but a cast's has only this spec. So Serene
        # Offering ("Destroy target enchantment. You gain 4 life.") could be
        # announced at a creature and gained its life for destroying nothing,
        # Aftershock at an enchantment dealt its 3 damage to its caster, and
        # CR 608.2b — which re-asks this same enumeration — could never find
        # either target illegal. ``type_filter`` is object-testable, and the
        # matcher reads a union and ``artifact_or_enchantment`` through layer 4.
        flags = {
            **flags,
            "filter": {
                **(flags.get("filter") or {}),
                "type_filter": (
                    list(type_filter) if isinstance(type_filter, (list, tuple))
                    else type_filter
                ),
            },
        }
    return {"kind": derived, **flags}


# The one spec kind whose chosen index is *not* a battlefield slot. Named
# rather than spelled out at each reader, because "is this index a graveyard
# index?" is asked in five places and a sixth that forgets is a spell reading a
# battlefield it never targeted.
GRAVEYARD_TARGET_KIND = "graveyard_creature"

#: "…target cards from **a single** graveyard" (Ebony Charm). A relation across
#: the targets rather than a narrowing of any one of them — "two target
#: creatures controlled by the same player" one zone over (``same_controller``)
#: — so it rides the spec as a flag: every pile is offered, and an announcement
#: is all in one of them. The client reads it to keep a selection inside the
#: pile its first card came from.
SINGLE_GRAVEYARD = "single_graveyard"

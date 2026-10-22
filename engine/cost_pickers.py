"""The picker a choosable cost needs (CR 601.2b, CR 602.2b).

A cost that names what pays it — "Sacrifice a creature", "Discard a card",
"Exile a card from your graveyard", "Tap an untapped Wall you control",
"Return a land you control to its owner's hand" — is chosen as the spell is
cast or the ability activated, and that choice is not a target: CR 601.2b
comes before CR 601.2c. A spec carrying one of :data:`COST_PICKER_FLAGS` at its
top level is a payment picker and nothing else (:func:`spec_is_a_cost`), which
every gate that asks "does this target?" must hear.

:func:`_cost_picker_spec` derives it from the parsed cost, one picker per
choice, and the cast side (``cast_targets._cast_cost_picker``) and the
activation side (``targeting.derive_activation_spec``) share it, because the
choice is the same announcement step on both. Split out of
``engine/targeting.py`` at the 2,000-line cap.
"""

from __future__ import annotations

from .subject_filters import filter_head_noun
from .target_descriptions import GRAVEYARD_TARGET_KIND


#: The flag each choosable cost sets on the spec `_cost_picker_spec` derives —
#: the word that tells the client which field the answer rides and which verb
#: to say. A spec carrying one *at its top level* is a payment picker and
#: nothing else: the ability it describes targets nothing (CR 601.2b vs
#: 601.2c), which every gate that asks "does this ability target?" must hear.
COST_PICKER_FLAGS = (
    "sacrifice_cost", "discard_cost", "exile_cost", "tap_cost", "return_cost",
    # "Untap a tapped land an opponent controls" (Benthic Explorers), "Put a
    # -1/-1 counter on a creature you control" (Wandering Mage), "Remove a
    # +1/+1 counter from a creature you control" (Spike Rogue), "Put a card
    # from your hand on top of your library" (Hidden Retreat, Penance).
    "untap_cost", "put_counter_cost", "remove_counter_cost", "library_top_cost",
)


def spec_is_a_cost(spec: dict | None) -> bool:
    """Whether *spec* is a cost picker rather than a target description."""
    return bool(spec) and any(spec.get(flag) for flag in COST_PICKER_FLAGS)


def _cost_picker_spec(cost, *, announced: dict | None = None) -> dict | None:
    """The picker a choosable cost needs, or None when the cost chooses nothing.

    *announced* is CR 601.2b's answer so far, for the one cost kind that is an
    **offer** rather than a price (Constant Mists' "Buyback—Sacrifice a land").
    A declined offer charges nothing, so it chooses nothing and gets no picker —
    which is what keeps a caster who is not buying the card back from being
    asked to name a land. The check is here rather than in the callers because
    all three of them (the cast picker, the "should this card raise a picker?"
    ratchet and the picker sweep) must give one answer; a caller that forgot
    would report a picker the cast never raises.

    Shared by the cast and activation sides because the *choice* is the same on
    both — CR 601.2b and CR 602.2b are the same announcement step — and only
    what is withheld from the list differs. ``sacrifice_cost`` / ``discard_cost``
    are what tell the client which field carries the answer and to say
    "sacrifice" rather than "target"; the payment is not a target, and a card
    can have both.

    The sacrifice's head noun is the kind, rather than a fixed "creature": Atog
    eats an artifact, and a picker offering creatures for it would offer nothing
    it could pay with. Anything the noun phrase says *beyond* its head noun rides
    along as ``filter`` — "a creature with defender" (Portcullis Vine) is a
    creature picker over a narrowed list, and the enumerator applies the
    narrowing with the same matcher the charger does, so what is offered and
    what is accepted cannot disagree.

    **One picker per choice, and a cost may hand its payer several.**
    "Sacrifice a creature **and a Swamp**" (Viscerid Drone) is two permanents
    and two choices; this function used to return at the first branch that
    matched, so the creature was asked about and the Swamp was the engine's
    default for every human who ever paid it. :func:`_cost_picker_specs` builds
    the whole list, and the first entry carries the rest as ``more_costs`` —
    emitted only when there is a rest, so every spec written before a second
    choice existed is byte-identical, and every reader that asks the first
    picker's flags still gets the first picker. The answers to the whole list
    ride one ``cost_permanent_ids``, in the list's order, and each charger
    takes the ids its own candidates contain.
    """
    specs = _cost_picker_specs(cost, announced=announced)
    if not specs:
        return None
    first, *rest = specs
    if rest:
        return {**first, "more_costs": rest}
    return first


def _cost_picker_specs(cost, *, announced: dict | None = None) -> list[dict]:
    """Every picker *cost* needs, in the order the client asks them; empty when
    the cost chooses nothing. :func:`_cost_picker_spec` is the shape callers
    read; this is the list it is made from."""
    if cost is None:
        return []
    offer_key = getattr(cost, "optional_key", None)
    if offer_key is not None and not (announced or {}).get(offer_key):
        return []
    specs: list[dict] = []
    if getattr(cost, "discard_cards", 0) and not getattr(cost, "discard_at_random", False):
        # "Discard a card **at random**" (Coral Helm, Stormbind, Amok,
        # Draconian Cylix, Canyon Drake; Sonic Burst and Flowstone Flood on the
        # cast side) is the condition's second half. The payer names
        # **nothing**, so there is no choice for a picker to collect — and both
        # payment paths already ignore a named card here, deliberately, because
        # honouring one would hand the choice back and make the cost strictly
        # better than the card prints.
        #
        # So a picker was a prompt whose answer was discarded: the client asked
        # which card to bin, the player chose, and the RNG binned a different
        # one. Nothing crashed, nothing was missing, and the card was **wrong in
        # the player's favour** right up to the moment the answer was thrown
        # away. It is refused here rather than in each caller for this
        # function's own stated reason: all three of them must give one answer.
        spec = {
            "kind": "hand_card",
            "own_only": True,
            "discard_cost": True,
            "count": cost.discard_cards,
        }
        # "…, discard **X** cards" (Firestorm, the Dreams): how many is the X
        # the caster announces (CR 601.2b), so the spec says an X is owed —
        # the flag "Sacrifice X lands" carries below — rather than the printed
        # 1 ``count`` holds. Emitted only for an X, so every other discard
        # spec is unchanged.
        if getattr(cost, "discard_count_x", False):
            spec["announces_x"] = True
        # "Discard a **land card or Shrine card**" (Sanctum of Shattered
        # Heights) — the printed alternatives ride along so the enumerator
        # narrows the offered hand with the same reader the charger accepts by.
        # Emitted only when there is a narrowing: an empty key would read as one
        # to anything that tests for its presence.
        alternatives = getattr(cost, "discard_filters", ()) or ()
        if alternatives:
            spec["filters"] = [dict(alt) for alt in alternatives]
        specs.append(spec)
    described = getattr(cost, "exile_filter", None)
    if described is not None:
        # "Exile a creature you control" (City of Shadows) / "Exile a creature
        # card from your graveyard" (Necropolis). The sacrifice picker one zone
        # over: the *choice* is the same announcement (CR 601.2b), and only the
        # list it is made from differs. ``exile_cost`` is what tells the client
        # to send the answer on the cost field and to say "exile" rather than
        # "target" — a cost is not a target (idiom 10).
        if getattr(cost, "exile_zone", "battlefield") == "graveyard":
            spec = {
                "kind": GRAVEYARD_TARGET_KIND,
                "exile_cost": True,
            }
            # Whose pile the payer may reach into. "from **your** graveyard"
            # (Necropolis) is one seat; "from a single graveyard" (Night Soil)
            # is anybody's, and the charger really does enumerate every seat —
            # so a picker that said "your own" here would offer less than the
            # cost accepts, which is the picker/charger disagreement this file
            # exists to prevent, in the direction that hides a legal payment.
            if getattr(cost, "exile_zone_owner", "you") == "you":
                spec["own_graveyard_only"] = True
            wanted = described.get("type_filter")
            if isinstance(wanted, str):
                spec["card_type"] = wanted
            else:
                # "Exile **two cards** from your graveyard" (Psychatog,
                # Bearscape), "Exile **a card** …" (Screams of the Damned).
                # The phrase names no type, and a graveyard spec that names
                # none is read as "a creature card" — the reanimation Auras'
                # default (``graveyard_card_matches``). So the picker offered
                # creature cards only for a cost the charger takes any card
                # for: a pile of lands could pay and showed nothing to click.
                # No card printed the unnarrowed phrase until Odyssey.
                spec["any_card"] = True
            # Whatever else the phrase narrows by rides along and is asked
            # through the charger's own matcher (``_card_matches_filter``) by
            # the enumerator, so what is offered and what is accepted cannot
            # disagree. Emitted only when there is something to carry.
            narrowing = {
                key: value for key, value in described.items()
                if not (key == "type_filter" and isinstance(value, str))
            }
            if narrowing:
                spec["cost_filter"] = narrowing
            # How many the payer names. Emitted only when the printed count is
            # more than one, so every spec written before a counted cost existed
            # stays byte-identical.
            count = getattr(cost, "exile_count", 1) or 1
            if count == "any":
                # "Exile **any number of** cards from your graveyard"
                # (Painbringer). No size to state — the set is the payer's,
                # none included — so the spec says that instead of a number.
                # The answer rides ``cost_graveyard_indices``.
                spec["any_number"] = True
            elif int(count) > 1:
                spec["count"] = int(count)
            # "…from **a single** graveyard": all of them out of the same pile,
            # which is a restriction on the *set* rather than on any one card
            # and so cannot ride the filter.
            if getattr(cost, "exile_same_zone", False):
                spec["same_zone"] = True
            specs.append(spec)
        elif getattr(cost, "exile_zone", "battlefield") == "hand":
            # "Exile a card **from your hand**" (Cadaverous Bloom). The discard
            # picker's list with the exile's verb. This fell through to the
            # battlefield branch below and described a *permanent* picker for a
            # cost paid out of a hand — so the list offered was the payer's
            # board and the answer, had anything sent it, would have been read
            # as a hand position. The charger reads ``cost_hand_index`` for it,
            # the field every other hand-card cost answers on.
            spec = {
                "kind": "hand_card",
                "own_only": True,
                "exile_cost": True,
            }
            count = int(getattr(cost, "exile_count", 1) or 1)
            if count > 1:
                spec["count"] = count
            # A printed narrowing ("a **blue** card") as the alternatives list
            # the hand enumerator already reads; "a card" carries none.
            if described:
                spec["filters"] = [dict(described)]
            specs.append(spec)
        else:
            spec = {
                "kind": filter_head_noun(described),
                "own_only": True,
                "exile_cost": True,
            }
            if described.get("exclude_self"):
                spec["exclude_source"] = True
            narrowing = {
                key: value
                for key, value in described.items()
                if key not in ("exclude_self", "controller")
                and not (key == "type_filter" and isinstance(value, str))
            }
            if narrowing:
                spec["filter"] = narrowing
            specs.append(spec)
    described = getattr(cost, "sacrifice_filter", None)
    if described is not None:
        spec = {
            "kind": filter_head_noun(described),
            "own_only": True,
            "sacrifice_cost": True,
        }
        # "Sacrifice **another** creature" (Hobblefiend): the source is not a
        # legal payment, so a lone Hobblefiend can offer nothing and cannot
        # activate at all — which the payment path already enforces. It is
        # lifted out of the carried filter rather than left in it, because the
        # enumerator excludes by identity and a key nothing reads is a key
        # silently dropped.
        if described.get("exclude_self"):
            spec["exclude_source"] = True
        # "Sacrifice **two** Goblins" (Goblin Warrens): how many the payer
        # names. Emitted only above one, so every spec written before a counted
        # sacrifice existed is unchanged — and "any" stays off it, because that
        # cost already travels on ``cost_permanent_ids`` and has no fixed size.
        sacrifice_count = getattr(cost, "sacrifice_count", 1)
        if isinstance(sacrifice_count, int) and sacrifice_count > 1:
            spec["count"] = sacrifice_count
        # "Sacrifice **X** lands" (Copper-Leaf Angel): how many is the X the
        # activator announces (CR 601.2b), so the spec says an X is owed — the
        # flag the cast side's X box already reads — rather than a number.
        if sacrifice_count == "x":
            spec["announces_x"] = True
        # `kind` already *is* the head noun, so re-stating it in the carried
        # filter would be the same restriction written twice. A type *union* has
        # no head noun (`kind` falls back to "permanent"), so it rides along.
        narrowing = {
            key: value
            for key, value in described.items()
            # ``own_only`` above already *is* "you control", so carrying the
            # seat again would be the same restriction written twice — and the
            # second copy would reach an enumerator with no observer, which
            # refuses every candidate rather than narrowing anything.
            if key not in ("exclude_self", "controller")
            and not (key == "type_filter" and isinstance(value, str))
        }
        if narrowing:
            spec["filter"] = narrowing
        specs.append(spec)
    described = getattr(cost, "sacrifice_also_filter", None)
    if described is not None:
        # "Sacrifice a creature **and a Swamp**" (Viscerid Drone); "Sacrifice a
        # creature named Feral Shadow, **a creature named Breathstealer**, and
        # this creature" (Urborg Panther). The second noun phrase is a second
        # permanent and a second choice (CR 601.2h through CR 602.2b), and
        # until it had a picker of its own the Swamp was whichever one the
        # default reached first. A set of one, so it is the tap cost's shape
        # with the sacrifice's verb; the charger takes, of the named ids, the
        # one its own candidates contain — which never includes the permanent
        # the first phrase was paid with.
        specs.append(_permanent_set_cost_spec(described, "sacrifice_cost", 1))
    described = getattr(cost, "return_to_hand_filter", None)
    if described is not None and getattr(cost, "return_to_hand_count", 0):
        # "**Return a Forest you control to its owner's hand**: Untap target
        # creature" (Quirion Ranger), "Return two Islands you control …"
        # (Flooded Shoreline). The tap cost below one zone over, and the
        # charger reads the same ``cost_permanent_ids``: which Forest goes
        # home — the tapped one or the untapped one — is the payer's.
        specs.append(_permanent_set_cost_spec(
            described, "return_cost", int(cost.return_to_hand_count)
        ))
    described = getattr(cost, "return_filter", None)
    if described is not None and not getattr(cost, "return_count_x", False):
        # The **cast** side's spelling of the same cost
        # (``AdditionalCost.return_filter``): "Kicker—Return a creature you
        # control to its owner's hand." (Arctic Merfolk.) Which creature goes
        # home is the caster's (CR 601.2b), and the charger has read
        # ``cost_permanent_ids`` for it since Infernal Harvest — but nothing
        # described the choice, so a human who kicked the Merfolk returned
        # whichever creature the default met first.
        #
        # A printed count only. "Return **X** Swamps" (Infernal Harvest) stays
        # pinned in ``test_cost_pickers._PICKERLESS_CAST_COSTS`` with its own
        # reason: the cast client asks X after the cost stage, so a set of X
        # has nowhere to learn its size from.
        specs.append(_permanent_set_cost_spec(
            described, "return_cost", int(getattr(cost, "return_count", 1) or 1)
        ))
    described = getattr(cost, "tap_filter", None)
    if described is not None and getattr(cost, "tap_count", 0):
        # "**Tap an untapped creature you control**: …" (Opposition, Earthcraft,
        # Keldon Battlewagon), "Tap two untapped Spirits you control"
        # (Shacklegeist). The sacrifice picker's shape with a different verb:
        # *which* permanents tap is the payer's choice (CR 601.2h through
        # CR 602.2b), and the charger has taken the answer on
        # ``cost_permanent_ids`` since the cost existed — but nothing derived a
        # picker for it, so a human seat was never asked and the deterministic
        # default tapped whatever came first. ``tap_cost`` tells the client to
        # say "tap" and send the ids on the cost field; ``count`` is always
        # stated, because every printing of this cost is a set the payer picks,
        # one or several.
        specs.append(
            _permanent_set_cost_spec(described, "tap_cost", int(cost.tap_count))
        )
    described = getattr(cost, "untap_filter", None)
    if described is not None:
        # "{T}, **Untap a tapped land an opponent controls**: …" (Benthic
        # Explorers). The tap cost's mirror, and the first picker over a
        # permanent the payer does **not** control (CR 602.1a: a cost is any
        # action) — so the printed seat clause is the picker's seat, not
        # ``own_only``. The charger has always taken the answer on
        # ``cost_permanent_ids``; nothing asked, so a human untapped whichever
        # land the default met first, and the mana the ability makes is "any
        # type **that land** could produce".
        spec = _permanent_set_cost_spec(
            described, "untap_cost", 1, seat=described.get("controller")
        )
        if spec is not None:
            specs.append(spec)
    described = getattr(cost, "put_counter_filter", None)
    if described is not None and getattr(cost, "put_counter", None):
        # "{B}, **Put a -1/-1 counter on a creature you control**: …"
        # (Wandering Mage). Which creature shrinks is the payer's, and the
        # charger reads ``cost_permanent_ids``; ``counter`` is the printed kind,
        # so the client can say what is being put on.
        spec = _permanent_set_cost_spec(described, "put_counter_cost", 1)
        spec["counter"] = cost.put_counter
        specs.append(spec)
    described = getattr(cost, "remove_counter_filter", None)
    if described is not None and getattr(cost, "remove_counter", None):
        # "{2}, **Remove a +1/+1 counter from a creature you control**: …"
        # (Spike Rogue). The placing twin's mirror, with one more condition on
        # who can pay: the permanent must be *holding* the counter (CR 601.2h),
        # which the charger checks and so the picker must too — offered a
        # creature with none, the player's answer would be silently replaced by
        # the default. ``with_named_counter`` is the testable key that asks it
        # (it reads +1/+1 counters through the same store the charger counts).
        #
        # It asks "at least one", so a printed count above one has no key to
        # say it and gets no picker — the guard then names the card, which is
        # the loud direction, rather than offering creatures that cannot pay.
        if cost.remove_counter_count == 1:
            spec = _permanent_set_cost_spec(
                {**described, "with_named_counter": cost.remove_counter},
                "remove_counter_cost", 1,
            )
            spec["counter"] = cost.remove_counter
            specs.append(spec)
    if getattr(cost, "hand_to_library_top", 0):
        # "**Put a card from your hand on top of your library**: …" (Hidden
        # Retreat, Penance). The discard picker's shape with a different
        # destination: which card is the payer's (CR 601.2b through
        # CR 602.2b), the charger reads ``cost_hand_index`` exactly as the
        # discard does, and the flag tells the client to say "put on top of
        # your library" rather than "discard".
        specs.append({
            "kind": "hand_card",
            "own_only": True,
            "library_top_cost": True,
            "count": int(cost.hand_to_library_top),
        })
    return specs


#: The seat clause a printed cost phrase carries, as the enumerator's seat flag.
#: ``None`` — no clause — is the payer's own, which is what every tap, return
#: and sacrifice cost in the pool means; "an opponent controls" is the one
#: other clause a cost prints (Benthic Explorers).
_COST_SEAT_FLAGS = {None: "own_only", "you": "own_only", "opponent": "opponent_only"}


def _permanent_set_cost_spec(
    described: dict, flag: str, count: int, *, seat: str | None = None
) -> dict | None:
    """The picker for a cost paid with *count* permanents named by *described*
    — a tap, a return to hand, an untap, a counter put on or taken off, the
    second half of a conjoined sacrifice. *flag* is the verb the client says
    and the field the answer rides is ``cost_permanent_ids``.

    *seat* is the printed seat clause, for the one cost that reaches past the
    payer's own permanents ("Untap a tapped land **an opponent controls**").
    A clause this table cannot say derives no picker at all, rather than one
    over the payer's own board — the guard then names the card.

    The rest of the printed phrase — "untapped", "blue", "Spirit", "snow",
    "Forest" — rides along as ``filter`` for the reason the sacrifice's
    narrowing does: the enumerator applies it with the matcher the charger
    accepts by, so what is offered and what is accepted cannot disagree.
    """
    seat_flag = _COST_SEAT_FLAGS.get(seat)
    if seat_flag is None:
        return None
    spec = {
        "kind": filter_head_noun(described),
        seat_flag: True,
        flag: True,
        "count": count,
    }
    if described.get("exclude_self"):
        spec["exclude_source"] = True
    narrowing = {
        key: value
        for key, value in described.items()
        if key not in ("exclude_self", "controller")
        and not (key == "type_filter" and isinstance(value, str))
    }
    if narrowing:
        spec["filter"] = narrowing
    return spec

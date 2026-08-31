"""Lowering mana production: "Add {G}." and the tapped-land mana trigger.

The two kinds here are the whole of the "mana" migration category. They part
company at dispatch, which is why the trigger keeps its own kind: an activated
"{T}: Add {G}" resolves through EFFECT_HANDLERS, while the triggered mana
ability on a land being tapped (CR 605.1b) is resolved inline by
``Game.tap_land_for_mana``, because CR 605.4a says a triggered mana ability
never uses the stack.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import (card_only_filter, object_only_filter,
                                untestable_filter_keys)
from .. import ast
from ..errors import LoweringError
from ._common import (
    _REST_OF_TURN,
    _amount_payload,
    _filter_payload,
    _targets_payload,
)
from ._events import _RECORDED_PERMANENTS


def _lower_add_mana(
    node: ast.AddMana, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """Emit the mana as structured pips rather than clause text.

    "Add one mana of any color" (Birds of Paradise, Celestial Prism) is the one
    player-chosen shape that lowers, and it is the exception that keeps the
    text. ``add_mana_from_text``'s any-colour branch is ``_add_mana_from_text``
    probing for the literal phrase "one mana of any color"; the chosen symbol
    arrives separately as ``color``, injected by mixins/stack/activation when
    ``any_color`` is set. Structured pips would say nothing the handler could
    read, so the clause rides along in ``oracle_text`` exactly as the legacy
    rule wrote it — which is what :attr:`ast.AddMana.source_text` exists for,
    and what keeps this payload byte-identical while the handler stays
    text-keyed.

    Any other count refuses. That probe recognizes *one* mana and no other
    number, so Black Lotus's "Add three mana of any one color" lowered here
    would add nothing while reporting success; it keeps its own fused
    ``sacrifice_self_for_mana`` handler on the legacy path.
    """
    # "Add an amount of {B} equal to the sacrificed artifact's mana value."
    # (Priest of Yawgmoth.) The mana is one symbol and the *amount* is the mana
    # value of what the ability's sacrifice cost ate, which the handler reads
    # back off `sacrificed_for_cost` — the same channel the casting path has
    # used for Sacrifice and Metamorphosis since that cost became general.
    #
    # `bonus` is 0 here and 1 on Metamorphosis's "1 plus …"; it is on the
    # payload for the same reason the colour is, so a card printing either
    # needs no code.
    # "…add an amount of {C} equal to that spell's mana value." (Mana Drain.)
    # The number is not on this clause at all: it was recorded by the sentence
    # that countered the spell, and the delayed ability created between them
    # froze the scratchpad (CR 608.2h). So the clause refuses unless an earlier
    # step of the same effect actually produced it — a back-reference with no
    # producer would add nothing while reporting itself supported.
    if node.from_countered_spell:
        if "countered_spell_mana_value" not in produced:
            raise LoweringError(
                "\"that spell's mana value\" names a spell nothing in this "
                "effect countered", node=node,
            )
        return (
            OracleInstruction(
                "add_mana_from_text", "",
                {
                    "symbol": node.from_countered_spell,
                    "count_from_trigger": "countered_spell_mana_value",
                },
            ),
        )
    # "Tap target untapped creature you control. If you do, add an amount of
    # {C} equal to **that creature's** mana value." (Energy Tap.) The creature
    # is still on the battlefield when this runs, so the number is read off it
    # at resolution rather than remembered — but *which* creature is only
    # knowable from what an earlier step of this same effect recorded. So the
    # clause refuses unless one of those steps recorded a permanent: with no
    # record the handler would find nothing and add no mana while the card
    # reported itself supported.
    if node.from_bound_creature:
        recorded = tuple(sorted(produced & _RECORDED_PERMANENTS))
        if len(recorded) != 1:
            raise LoweringError(
                "\"that creature's mana value\" names a creature "
                + ("nothing in this effect recorded" if not recorded
                   else "several earlier steps recorded"),
                node=node,
            )
        return (
            OracleInstruction(
                "add_mana_from_text", "",
                {
                    "symbol": node.from_bound_creature,
                    "count_from_mana_value_of": recorded[0],
                },
            ),
        )
    if node.from_sacrificed_cost:
        return (
            OracleInstruction(
                "sacrifice_creature_for_mana", "",
                {"color": node.from_sacrificed_cost, "bonus": 0, "spend_only": None},
            ),
        )
    if node.from_noted:
        # "Add one mana of this artifact's last noted type." (Jeweled Amulet.)
        # No symbol at all: what is added is the record an earlier activation of
        # the same permanent wrote (``engine/noted_mana.py``), which only a
        # resolution holding the source can read. ``from_noted`` says which half
        # of the record the clause uses — the type alone, or the amount with it.
        payload = {"from_noted": node.from_noted}
        if node.spend_only is not None:
            payload["spend_only"] = node.spend_only
        return (OracleInstruction("add_mana_from_text", "", payload),)
    if node.runs_choice:
        # "Add {U} or {C}{U}." (Adarkar Unicorn.) Its own key for the reason
        # ``pips_choice`` is one: a reader that has not learned it adds nothing
        # rather than every alternative, and "nothing" is the failing-safe
        # direction for a mana ability.
        payload = {"pips_alternatives": node.runs_choice}
        if node.spend_only is not None:
            payload["spend_only"] = node.spend_only
        return (OracleInstruction("add_mana_from_text", "", payload),)
    if node.combination:
        # "Add three mana in any combination of {R} and/or {G}." (Orcish
        # Lumberjack.) The count and the symbols are both payload; which unit is
        # which colour is the seat's choice at resolution, so nothing about it
        # is decided here.
        payload = {
            "combination": node.combination,
            "combination_count": _amount_payload(node.combination_count),
        }
        if node.spend_only is not None:
            payload["spend_only"] = node.spend_only
        return (OracleInstruction("add_mana_from_text", "", payload),)
    if node.pips:
        # A printed "or" ships under its own key, never as bare ``pips``: a
        # reader that has not learned ``pips_choice`` then adds *nothing*
        # rather than every alternative, which is the failing-safe direction —
        # "Add {B} or {R}" making two mana is strictly worse than making none.
        key = "pips_choice" if node.choice else "pips"
        payload: dict[str, object] = {key: node.pips}
        if node.spend_only is not None:
            payload["spend_only"] = node.spend_only
        if node.per_each_counter_removed is not None:
            # "…for each charge counter removed this way" (the Mana Batteries).
            # The multiplier is the ability's own cost payment, which the
            # activation path recorded as it charged it — so the payload names
            # the counter kind and the handler reads the number back, the same
            # split "the sacrificed artifact's mana value" makes one branch up.
            #
            # Carried rather than left on the node: an unread field here is a
            # printed clause that parses, lowers, and multiplies nothing, which
            # on these five cards is a battery that always makes exactly one
            # mana however many counters it just ate.
            payload["per_each_counter_removed"] = node.per_each_counter_removed
        if node.per_each_counter_on_source is not None:
            # "…for each **storage counter on this land**" (City of Shadows).
            # Counted off the source at resolution, which is what separates it
            # from the payment above — and carried as the counter's kind, so a
            # card printing another word is data.
            payload["per_each_counter_on_source"] = node.per_each_counter_on_source
        if node.per_each is not None:
            # The count is taken at resolution through the one evaluator every
            # computed amount shares, so "creature with power 4 or greater you
            # control" means the same set here as it does anywhere else.
            # "…for each creature card **in your graveyard**" (Songs of the
            # Damned). A zone other than the battlefield, which the evaluator
            # already counts — it reads the zone off the spec — so the only
            # thing missing was carrying the one the phrase named instead of
            # writing "battlefield" here. A card in a zone has no computed
            # characteristics at all (CR 613.1), so the *matcher* differs, and
            # `card_only_filter` is what says which narrowings survive there.
            zone = node.per_each.zone or "battlefield"
            owner = node.per_each.controller if zone == "battlefield" else (
                node.per_each.zone_owner.kind if node.per_each.zone_owner else None
            )
            # "…in **target opponent's** graveyard" (Spoils of Evil). A chosen
            # seat rather than the producer's own, which the evaluator already
            # answers — `count_from_payload` reads any owner that is not "you"
            # off the resolution's target. Only out of a *zone*: "you control"
            # is a battlefield scope and a targeted one there would be a
            # different sentence with a different reader.
            if owner != "you" and not (
                zone != "battlefield" and owner == "target_opponent"
            ):
                raise LoweringError(
                    "the mana multiplier counts the producer's own board", node=node
                )
            if zone == "battlefield":
                # "You control" is performed by the count's `owner`, which scans
                # one seat's battlefield — so it is carried rather than tested,
                # the arrangement `carried_separately` exists to name. Everything
                # else has to be answerable about a permanent alone, because that
                # is what the evaluator's matcher is.
                carried = object_only_filter(
                    _filter_payload(node.per_each),
                    carried_separately=frozenset({"controller"}),
                )
            else:
                # `_filter_payload` refuses a non-battlefield filter by design —
                # every handler it feeds searches the battlefield. This one does
                # not: the zone travels on the spec and the evaluator reads it,
                # so the filter is taken raw and held to what a *card* can
                # answer.
                carried = card_only_filter({
                    key: value
                    for key, value in node.per_each.to_payload().items()
                    if key not in ("zone", "zone_owner", "is_card")
                })
            if carried is None:
                raise LoweringError(
                    "the mana multiplier cannot count this restriction", node=node
                )
            payload["per_each"] = {
                "zone": zone, "owner": owner, "filter": carried,
            }
            if owner == "target_opponent":
                # The seat is chosen when the spell is cast (CR 115.4 excludes
                # the caster's own), so the *card* targets a player and the
                # picker has to say so. Carried on this instruction because
                # `derive_cast_spec` reads the first one that describes a
                # target, and this is the first step of the sentence.
                payload["targets"] = {"kind": "player", "opponents_only": True}
        return (OracleInstruction("add_mana_from_text", "", payload),)
    # The any-colour branch keeps its clause text for a *text-keyed* handler
    # probe, so a restriction folded onto it would be carried in the payload and
    # ignored by the branch that reads the text. No card prints the pair; it
    # refuses rather than adding unrestricted mana.
    if node.spend_only is not None:
        raise LoweringError(
            "no handler restricts what any-colour mana may pay for", node=node
        )
    # ``any_color`` is a *count* now, not a flag. The handler used to probe the
    # clause text for the literal "one mana of any color", which is why every
    # other number had to refuse; it reads the number, so "add two mana of any
    # one color" and "add X mana" are the same instruction with different data.
    #
    # The clause text still rides along: ``activation.py`` keys the colour
    # injection on the ``any_color`` payload key, and the AI's mana valuation
    # reads the text. Both are the same string the legacy rule wrote.
    amount = _amount_payload(node.any_color)
    payload: dict[str, object] = {
        "oracle_text": node.source_text,
        "any_color": True,
        "any_color_count": amount,
    }
    if node.any_color_from is not None:
        # "…that a land an opponent controls could produce" (Fellwar Stone).
        # Which board narrows the choice, carried so the handler and the colour
        # picker read one answer. Emitted only when printed, so every payload
        # written before it is byte-identical.
        payload["any_color_from"] = node.any_color_from
    return (OracleInstruction("add_mana_from_text", "", payload),)


def _lower_note_mana_spent(
    node: ast.NoteManaSpent,
) -> tuple[OracleInstruction, ...]:
    """"Note the type [and amount] of mana spent to pay this activation cost."
    (Jeweled Amulet, Ice Cauldron.)

    One instruction with the one printed difference as payload. Nothing is
    produced and nothing on any board changes; the record goes on the ability's
    own source, which is what "**this artifact's** last noted type" one line
    later reads.
    """
    return (
        OracleInstruction(
            "note_mana_spent", "", {"with_amount": bool(node.with_amount)}
        ),
    )


# Which player the mana goes to, from the clause's own subject. Both spellings
# name the same seat in this engine — a player can only tap lands they control,
# so the tapping player *is* the land's controller — but they are different
# referents on the card and the handler resolves each one by name rather than
# assuming they coincide.
_TAPPED_LAND_MANA_RECIPIENTS = {
    "that_player": "that_player",   # Mana Flare: "that player"
    "controller": "land_controller",  # Gauntlet of Might: "its controller"
}


def _lower_add_mana_for_tapped_land(
    node: ast.AddManaForTappedLand, event: str | None
) -> tuple[OracleInstruction, ...]:
    """Mana Flare / Gauntlet of Might's mana, as one parameterised instruction.

    ``add_mana_for_tapped_land`` is resolved inline by
    ``Game.tap_land_for_mana`` rather than through the stack, which is what
    CR 605.4a requires of a triggered mana ability.

    The event is checked rather than assumed. "That player" and "any type that
    land produced" are bound by the trigger, so under any other condition there
    is no land and no tapping player for the handler to read — it would add
    mana of an arbitrary type to an arbitrary seat. Refusing here keeps the
    clause unclaimed and visible instead.
    """
    if event != "land_tapped_for_mana":
        raise LoweringError(
            "'that land'/'that player' are bound by a land_tapped_for_mana "
            f"trigger; {event!r} binds neither",
            node=node,
        )
    recipient = _TAPPED_LAND_MANA_RECIPIENTS.get(node.recipient.kind)
    if recipient is None:
        raise LoweringError(
            f"no tapped-land mana recipient for {node.recipient.kind!r}", node=node
        )
    payload: dict[str, object] = {"recipient": recipient}
    if node.pips:
        payload["pips"] = node.pips
    if node.of_type_produced:
        payload["of_type_produced"] = node.of_type_produced
    if node.additional:
        payload["additional"] = True
    # Snowfall's three keys, each emitted only when the sentence printed it, so
    # every payload written before they existed is byte-identical.
    if node.optional:
        payload["optional"] = True
    if node.alt_supertype:
        # The alternative replaces the base production rather than adding to
        # it, so both halves travel together: an alternative with no pips would
        # be a snow Island making nothing.
        if not node.alt_pips:
            raise LoweringError(
                "a supertype alternative names the mana it makes instead",
                node=node,
            )
        payload["alt_supertype"] = node.alt_supertype
        payload["alt_pips"] = node.alt_pips
    if node.spend_only:
        payload["spend_only"] = node.spend_only
    return (OracleInstruction("add_mana_for_tapped_land", "", payload),)


def _lower_produces_mana_instead(
    node: ast.ProducesManaInstead,
) -> tuple[OracleInstruction, ...]:
    """"…it produces colorless mana instead of white mana." (Quarum Trench
    Gnomes.)

    Nothing is produced when this resolves. What the instruction carries is the
    standing swap the handler records on the land — the symbol replaced and the
    symbol replacing it, both payload, so the same sentence about any two
    symbols is the same instruction.

    The target is described the way every other targeted effect describes one —
    the filter flat on the payload for the handler, and a ``targets`` entry for
    ``engine/targeting.py``'s picker — so the two agree on which lands are
    legal instead of each reading the printed noun again.
    """
    if node.by_controller:
        return _lower_controller_mana_swap(node)
    if node.duration.kind is not None:
        # CR 611.2's "indefinitely" is what the recorded swap gives, and the
        # record dies with the permanent (CR 400.7). A printed window would need
        # a sweep to end it, and there is none for this record.
        raise LoweringError("a targeted produced-mana swap has no window", node=node)
    if node.replaced == ast.ANY_OTHER_TYPE:
        raise LoweringError(
            "a targeted produced-mana swap names the symbol it replaces",
            node=node,
        )
    described = _targets_payload(node.target)
    if described is None:
        raise LoweringError(
            "a produced-mana swap names the land it changes with 'target'",
            node=node,
        )
    return (
        OracleInstruction(
            "produce_mana_instead",
            "",
            {
                **_filter_payload(node.target.filter),
                "targets": described,
                "replaced": node.replaced,
                "produced": node.produced,
            },
        ),
    )


def _lower_controller_mana_swap(
    node: ast.ProducesManaInstead,
) -> tuple[OracleInstruction, ...]:
    """Deep Water: "Until end of turn, if you tap a land you control for mana,
    it produces {U} instead of any other type." Chaos Moon's even branch: "…if a
    player taps a Mountain for mana, that Mountain produces colorless mana
    instead of any other type."

    A swap over a *class* rather than one named land, which is why it is a
    different instruction from the targeted one above rather than the same one
    with a wider filter: the record cannot live on a permanent. The lands it
    covers include ones that enter after this resolves, and which of them the
    seat controls is answered when each is tapped — so the record hangs off the
    seat and the filter travels with it
    (``engine/land_mana_swaps.py``).

    Three refusals, each a way the sentence could mean more than it says:

    * "instead of any other type" and nothing narrower. A named symbol here
      would be a swap that fires on some of the seat's lands and not others,
      and the record has no per-symbol reading.
    * a window the sweeps give. "Until end of turn" is the one the cleanup step
      ends; anything else would be a swap nothing ever lifts.
    * a filter the matcher can test, and one whose reach matches the printed
      tapper. A restriction ``subject_matches`` cannot answer would be dropped
      where the swap is applied, which is a seat whose *opponents*' lands change
      colour.

    **The two tappers arm the same record on different seats.** "You" is one
    record on the ability's controller; "a player" names no seat, so the effect
    arms one on **every** seat — ``land_mana_swaps.swapped_symbol`` asks the
    land's own controller for theirs, so a single record on the controller would
    leave every opponent's Mountain making red. That is the payload's ``seats``
    key, emitted only for the wider spelling so Deep Water's payload is
    unchanged.
    """
    if node.replaced != ast.ANY_OTHER_TYPE:
        raise LoweringError(
            "a controller-wide mana swap replaces every type the land makes",
            node=node,
        )
    if node.duration.kind not in _REST_OF_TURN:
        raise LoweringError("a recorded mana swap lasts exactly this turn", node=node)
    filt = node.target.filter
    wanted_controller = None if node.each_player else "you"
    if node.target.quantifier not in ("a", "all", "each") or filt.controller != wanted_controller:
        raise LoweringError(
            "a recorded mana swap covers the lands the seat it names has",
            node=node,
        )
    described = _filter_payload(filt)
    untestable = untestable_filter_keys(described)
    if untestable:
        raise LoweringError(
            "a mana swap cannot test " + ", ".join(sorted(untestable)), node=node
        )
    payload: dict[str, object] = {"produced": node.produced, "lands": described}
    if node.each_player:
        payload["seats"] = "each"
    return (OracleInstruction("swap_controller_land_mana_until_eot", "", payload),)


def _lower_spend_mana_as_though(
    node: ast.SpendManaAsThough,
) -> tuple[OracleInstruction, ...]:
    """"For one spell this turn, you may spend mana as though it were mana of
    any type…" (North Star.)

    One kind with both the count and the breadth on the payload. The breadth is
    the half that must not be widened: "any color" is CR 106.1b's five, "any
    type" adds colorless, and the payment reads the key rather than the words.
    """
    return (
        OracleInstruction(
            "grant_spend_mana_as_though",
            "",
            {"spells": node.count, "any_type": node.any_type},
        ),
    )

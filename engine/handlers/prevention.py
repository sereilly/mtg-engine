"""Arming CR 615's **consumable** shields: the numeric pool and the next instance.

The handler twin of ``engine/grammar/lowering/prevention.py``. Every handler
here arms a ``shields.Shield`` that is **spent**: CR 615.7's "prevent the next
N damage" pool (Healing Salve, Samite Healer, Remedy's divided pool, Barbed
Wire's own damage, Temper's counting rider and Sacred Boon's read-back of what
was prevented) and CR 615.8's "the next time a source would deal damage"
instance — whole (Pentagram of the Ages, and the riders Reverse Damage, Bone
Mask, Shadowbane and Honorable Passage print after it), halved (Dark Sphere),
capped (Forcefield), or keyed on a colour (the Circles of Protection). The one
reader of "a source of your choice" is here too, :func:`chosen_shield_source`,
with :func:`default_damage_source` for a seat that named none; the blanket and
redirect handlers import it. Beside them: the two sentences that take
prevention away (Whippoorwill's lock, Flaring Pain), Desperate Gambit's
next-damage riders, Eye for an Eye's mirror and Pyramids' land shield.

The **blankets** — "prevent all damage … this turn", which have no charges —
are ``prevention_blankets.py``'s, cut out at the pre-Fifth-Dawn split round on
the line ``lowering/_blankets.py`` drew on the lowering side; the two CR 614.9
redirects that sat here (Jade Monolith, Personal Incarnation) went to
``redirection.py``. What a shield *does* when damage would be dealt is
``engine/prevention/``'s, and what one *is*, ``engine/shields.py``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..shields import (
    make_counting_pool,
    make_source_type_shield,
    add_shield,
    make_capped_charge,
    make_capped_source,
    make_color_shield,
    make_exile_charge,
    make_exile_source,
    make_team_charge,
    make_team_source,
    make_half_charge,
    make_half_source,
    make_life_gain_charge,
    make_life_gain_source,
    make_named_source_pool,
    make_numeric_pool,
    make_reflect_charge,
    make_reflect_source,
    make_source_subject_shield,
    make_targeted_source_shield,
    make_whole_charge,
    make_whole_source,
)
from ..divided_damage import DIVIDED_TARGETS, EVENLY, divide, divided_entry
from ..next_damage import (DAMAGE_DOUBLED_NEXT, DAMAGE_PREVENTED_NEXT,
                           DamageMirror, add_mirror, arm, rider_key)
from ..game_types import single_chosen_id, single_slot
from ._amounts import resolve_amount
from ._targets import (default_announced_permanent, divided_target_permanent,
                       attached_host, resolve_target_permanent)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import PlayerState
    from ..oracle import OracleInstruction


def _grant_pool(
    recipient, amount: int, source_name: str | None, source_filter: dict | None = None,
    counter: str = "",
):
    """Arm one CR 615.7 numeric shield on *recipient* and return it.

    A shield rather than an addition to a running total: several "prevent the
    next N damage" effects on one recipient are several effects, each with its
    own granting card for the badge. What they hold together is still the one
    number ``damage_prevention_pool`` reports.

    Returned so the resolution that armed it can record it — Sacred Boon's
    second sentence reads back what *this* shield prevented, and only the object
    survives from here to the end step.

    *source_filter* is the printed noun phrase naming **whose** damage this
    shield answers to ("…by Torrent of Lava this turn"). Recorded on the shield
    rather than tested here, because CR 615.9 rechecks a shield's property
    against the source when the damage would be dealt — a source matched at the
    arming would shield against a creature that has since changed.
    """
    if amount <= 0:
        return None
    if counter:
        # "…**For each 1 damage prevented this way, put a +1/+1 counter on that
        # creature.**" (Temper.) CR 615.5's additional effect, so it is the
        # shield's own interceptor that performs it as the points are absorbed —
        # a different `Shield.kind` and therefore a different interceptor, which
        # is the whole reason `kind` exists. No `source_filter`: no card prints
        # this rider on a shield that also names its source, and the lowering
        # refuses the pair rather than arming one half of it.
        return add_shield(
            recipient, make_counting_pool(amount, counter, source_name)
        )
    return add_shield(
        recipient, make_numeric_pool(amount, source_name, source_filter)
    )


def apply_prevention_shield(
    game: Game,
    target: PlayerState,
    target_permanent_index: object,
    amount: int,
    source_name: str | None = None,
    context: OracleExecutionContext | None = None,
    source_filter: dict | None = None,
    counter: str = "",
    permanent: "Permanent | None" = None,
    object_only: bool = False,
) -> str:
    """Grant `amount` prevention shields to a chosen creature, or otherwise to the
    target player. Records `source_name` (the granting card) so the UI can show
    its art on the shield badge, and *source_filter* — the printed phrase naming
    whose damage the shield stops — so a narrowed shield reaching this recipient
    is narrowed here too. Returns the name of the beneficiary.

    **The chosen creature is found by id first**, the slot only when no id was
    announced (the emblem path, which has no resolution context). It was slot
    only, so an "any target" announced by id alone — which the engine's own
    activation API accepts — shielded the creature's *controller* instead (Defender
    en-Vec, Samite Healer), and an index held across a resolution addressed
    whichever creature slid into the slot when one ahead of it left.

    *object_only* is a printed target that is an object and never a player
    ("target creature"): with no creature to shield, nobody is shielded.
    *permanent* is the caller's own answer for an announcement that named none
    (``handlers/_targets.default_announced_permanent``), used only when nothing
    was announced.
    """
    target_permanent_index = single_slot(target_permanent_index)
    chosen_id = (
        single_chosen_id(context.target_permanent_id)
        if context is not None else None
    )
    if chosen_id is not None:
        found = game.permanent_by_id(chosen_id)
        if found is None or not game.is_on_battlefield(found):
            # CR 608.2b: the one creature this named has left, so it is an
            # illegal target and shields nothing — never its controller, who
            # was not the target.
            game.log.append(f"{source_name}: the creature it named is gone")
            return ""
        permanent = found
    elif (
        isinstance(target_permanent_index, int)
        and 0 <= target_permanent_index < len(target.battlefield)
    ):
        permanent = target.battlefield[target_permanent_index]
    if object_only and (permanent is None or not permanent.is_creature):
        # "Target creature" names no player, so there is nobody to fall back
        # to: an announced slot that is not a creature shields nothing.
        game.log.append(f"{source_name}: no creature was named to shield")
        return ""
    if permanent is not None and permanent.is_creature:
        _record_shield(
            context,
            _grant_pool(
                permanent, amount, source_name, source_filter, counter,
            ),
            permanent,
        )
        game.log.append(f"{permanent.card.name} gains prevention shield for {amount} damage")
        return permanent.card.name
    _record_shield(
        context, _grant_pool(target, amount, source_name, source_filter), None
    )
    game.log.append(f"{target.name} gains prevention shield for {amount} damage")
    return target.name


#: The resolution-scratchpad key a granted shield is recorded under, and the id
#: of the permanent it protects. Named once because the step that writes them
#: and the delayed ability that reads them are a whole turn apart — see
#: ``lowering/_records._PRODUCES``.
PREVENTION_SHIELD_RESULT = "prevention_shield"
PREVENTION_SHIELD_TARGET_RESULT = "prevention_shield_target"


def _record_shield(context, shield, permanent) -> None:
    """Record the shield this step armed, for a later sentence of the same
    effect to read back (CR 615.5's "prevented this way").

    The shield **object**, not a number: what it prevents is not known yet, and
    by the time the reader runs the shield may have been spent and dropped from
    its recipient. Nothing serialises a resolution's scratchpad or a delayed
    ability's captured values, so the reference is the record.
    """
    if shield is None or context is None:
        return
    context.results[PREVENTION_SHIELD_RESULT] = shield
    if permanent is not None:
        context.results[PREVENTION_SHIELD_TARGET_RESULT] = permanent.permanent_id


def _sized_for_recipient(
    game: Game,
    context: OracleExecutionContext,
    instruction: OracleInstruction,
    target: PlayerState,
    amount: int,
) -> int:
    """*amount*, or the second size the card prints for a matching recipient.

    "Prevent the next 1 damage that would be dealt to any target this turn. **If
    it's a green creature, prevent the next 2 damage instead.**" (Elvish
    Healer.) One shield of one size, chosen here because here is the first place
    the target is known — the size cannot be decided when the line compiles, and
    two shields would prevent three.

    Asked through ``subject_matches``, the one reader of a printed noun phrase,
    with the ability's controller as the observer (CR 109.5) — so "green" is
    layer 5's answer and a creature recoloured since the ability was activated
    is sized by what it is now.
    """
    alternate = instruction.payload.get("amount_if")
    if not alternate:
        return amount
    # The same choice ``apply_prevention_shield`` is about to make — a creature
    # the ability named, or nothing and therefore the player — resolved through
    # the id seam rather than by indexing the battlefield, so the two cannot
    # disagree about which permanent is being shielded.
    chosen = resolve_target_permanent(
        game, context,
        player=target,
        predicate=lambda perm: perm.is_creature,
        fallback_players=(),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        return amount
    from ..subject_filters import subject_matches

    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    if subject_matches(
        game, chosen, dict(alternate.get("filter") or {}),
        observer=observer, source=context.source_permanent,
    ):
        return int(alternate.get("amount", amount))
    return amount


@effect_handler("grant_prevention_shield")
def grant_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    source_name = context.card.name if context.card else None
    # "…**by Torrent of Lava** this turn." The printed noun phrase naming whose
    # damage this shield answers to, carried onto the shield so CR 615.9's
    # recheck can ask it when the damage would be dealt. Absent — every other
    # card reaching this handler — the shield answers to any source, exactly as
    # it always did.
    source_filter = instruction.payload.get("source_filter") or None
    # CoP-style abilities say "prevent damage to you" — protection_kind="color"
    # means the caster/controller is always the beneficiary. Conservator-style
    # abilities ("...dealt to you this turn") set to_self=True for the same reason.
    prevention_color = instruction.payload.get("prevention_color")
    # "a black **or red** source of your choice" (Greater Realm of
    # Preservation): one shield answering to either colour, never one shield
    # per colour — two would let a black source and a red source each be
    # prevented off a single activation.
    prevention_colors = tuple(
        instruction.payload.get("prevention_colors") or ()
    ) or ((prevention_color,) if prevention_color else ())
    if instruction.payload.get("prevention_color_chosen"):
        # "…a source of your choice **of the chosen color**" (Prismatic
        # Circle). The colour is not in the sentence: it is what this permanent
        # recorded as it entered (CR 614.1c), read here rather than at damage
        # time because CR 615.9 rechecks the *source* against a property the
        # shield already holds — and the property was fixed when this ability
        # resolved.
        #
        # Nothing recorded arms nothing, the reading
        # ``prevention.static._resolved_chosen_color`` takes of the same phrase on the
        # static side: a shield naming no colour would answer to every source,
        # which is the widest possible reading of a sentence that names one.
        recorded = (
            getattr(context.source_permanent, "metadata", {}) or {}
        ).get("chosen_color")
        prevention_colors = (str(recorded),) if recorded else ()
    # Circle of Protection: Artifacts — the same Circle keyed on a card type.
    # Its own branch rather than a widened colour one: `make_color_shield` sets
    # the colour field, and a shield holding a card type in it would be
    # compared against `source_colors` and never match.
    source_type = instruction.payload.get("prevention_source_type")
    if instruction.payload.get("protection_kind") == "source_type" and source_type:
        add_shield(caster, make_source_type_shield(
            str(source_type), source_name, source=chosen_shield_source(game, context),
        ))
        game.log.append(
            f"{caster.name} sets a Circle of Protection shield against "
            f"an {source_type} source"
        )
        return True, "resolved"
    # Circle of Protection: Shadow — the same Circle keyed on a printed noun
    # phrase. Its own branch beside the card-type one above and for that
    # branch's reason: `source_has_type` cannot answer a keyword, so a shield
    # holding "creature with shadow" in `source_type` would answer to every
    # creature and the narrowing the card is named for would be gone.
    #
    # `filter_seat` is CR 109.5's observer, captured now rather than at damage
    # time: "you control" inside such a phrase means the seat that activated the
    # ability, and the shield may still be armed when that seat is not the one
    # being damaged.
    if instruction.payload.get("protection_kind") == "source_class":
        # "{1}{W}: The next time **a creature of the chosen type** would deal
        # damage to you this turn, prevent that damage." (Circle of Solace.)
        # The noun-phrase Circle's shield with **no chosen source**: the next
        # source the phrase describes spends it, rechecked when the damage
        # would be dealt (``Shield.source_filter``). "Of the chosen type" is
        # the CR 614.1c record on this ability's source, resolved now — the
        # word is fixed when the ability resolves — and nothing recorded arms
        # nothing, since a shield whose phrase still names "the chosen type"
        # would answer no source at all and one with the phrase dropped would
        # answer every creature.
        from ._chosen import _CHOSEN_SUBTYPE_KEYS, _resolve_chosen_subtype

        described = _resolve_chosen_subtype(
            dict(instruction.payload.get("source_filter") or {}),
            context.source_permanent,
        )
        if not described or any(described.get(key) for key in _CHOSEN_SUBTYPE_KEYS):
            game.log.append(
                f"{source_name or 'Effect'}: no creature type was chosen, so "
                "no shield is set"
            )
            return True, "resolved"
        add_shield(
            caster,
            make_source_subject_shield(
                described, game.players.index(caster), source_name,
            ),
        )
        game.log.append(
            f"{caster.name} sets a shield against the next "
            f"{described.get('subtype_filter') or 'matching'} source to deal "
            "them damage this turn"
        )
        return True, "resolved"
    if instruction.payload.get("protection_kind") == "source_subject":
        described = dict(instruction.payload.get("source_filter") or {})
        if described:
            add_shield(
                caster,
                make_source_subject_shield(
                    described, game.players.index(caster), source_name,
                    source=chosen_shield_source(game, context),
                ),
            )
            game.log.append(
                f"{caster.name} sets a Circle of Protection shield against "
                "a chosen source"
            )
        return True, "resolved"
    if instruction.payload.get("protection_kind") == "color":
        # Circle of Protection: "The next time a <color> source of your choice
        # would deal damage to you this turn, prevent that damage." Each activation
        # arms one color-scoped shield that prevents the entire next damage event
        # from a source of that color (CR 615) — distinct from the generic numeric
        # prevention pool so it only stops matching-colored damage.
        #
        # Only when a colour was actually recorded: CR 615.9 rechecks the
        # source's properties against the shield's, so a shield naming no colour
        # can never match anything. The legacy parse rule can still produce one
        # from a card whose text has no colour word, and arming nothing is what
        # the old list-of-None amounted to.
        # "The next time a black or red source of your choice would deal damage
        # this turn, prevent that damage." (Penance.) The same shield with no
        # recipient printed — CR 615.8 keys it on the source, so it protects
        # whoever that source was about to damage. It still hangs on the seat
        # that armed it, which is what the cleanup sweep walks; what makes every
        # recipient find it is ``prevention.shields._table_shields``.
        any_recipient = bool(instruction.payload.get("prevention_any_recipient"))
        # **The chosen source is the shield's, not the log's.** "The next time
        # a red source **of your choice** would deal damage to you" names one
        # object (CR 609.7a) and CR 615.8 prevents "the next instance of
        # damage from that source". This read the choice for the log line
        # below and armed a shield that answered the colour — so a Circle that
        # named the Hill Giant spent itself on a Goblin that dealt its damage
        # first. Through the one reader every "source of your choice" card
        # uses, so a spell on the stack is a source here as it is there; an
        # activation that named nothing arms the sourceless form, as before.
        chosen_source = chosen_shield_source(game, context)
        for _ in range(max(1, amount) if prevention_colors else 0):
            add_shield(
                caster,
                make_color_shield(
                    prevention_colors, source_name, any_recipient=any_recipient,
                    source=chosen_source,
                ),
            )
        chosen = (
            getattr(getattr(chosen_source, "card", chosen_source), "name", None)
            if chosen_source is not None else None
        )
        game.log.append(
            f"{caster.name} sets a Circle of Protection shield against "
            + (
                f"{chosen} (a {'/'.join(prevention_colors)} source)"
                if chosen
                else f"a {'/'.join(prevention_colors)} source"
            )
        )
        return True, "resolved"

    # "Prevent the next 5 damage that would be dealt this turn to **any number
    # of targets, divided as you choose**." (Remedy.) CR 615.7's point pool
    # split across CR 601.2d's announced targets — one shield per recipient,
    # each holding the share its controller announced.
    #
    # One shield each rather than one shield with several recipients: CR 615.1
    # puts a shield around *the thing it affects*, and a 5-point pool split 3/2
    # is two pools that expire and are spent independently. The division itself
    # is `engine/divided_damage.py`'s, the same reader the burn spells use, so
    # "divided as you choose" and "divided evenly" cannot come to mean
    # different things on the two sides of a damage event — and a seat with no
    # way to be asked (the AI, a scripted duel) gets the even split that module
    # already falls back to.
    divided = context.choices.get(DIVIDED_TARGETS)
    if divided and (instruction.payload.get("targets") or {}).get("kind") == "divided":
        # Each entry is resolved through the seam rather than by indexing a
        # battlefield: a shield armed on the slot a dead permanent used to hold
        # would protect whoever slid into it (`engine/mixins/control_seam.py`).
        live = []
        for entry in divided:
            seat, index, _share = divided_entry(entry)
            if not (0 <= seat < len(game.players)):
                continue
            if index is None:
                live.append((entry, game.players[seat]))
                continue
            # By id, not by slot: an index announced under CR 601.2c names
            # whoever holds that slot at *resolution*, and anything leaving
            # renumbers the rest.
            permanent = divided_target_permanent(game, entry)
            if permanent is not None:
                live.append((entry, permanent))
        if not live:
            # CR 608.2b: every chosen recipient is gone, so the spell shields
            # nobody. It must not fall back to the caster, which is what a
            # targetless resolution would otherwise reach below.
            game.log.append(f"{source_name}: no remaining targets to shield")
            return True, "resolved"
        division = (instruction.payload.get("targets") or {}).get("division", EVENLY)
        shares = divide(amount, [entry for entry, _who in live], division=division)
        for (_entry, recipient), (_seat, _index, share) in zip(live, shares):
            if share <= 0:
                continue
            _grant_pool(recipient, share, source_name, source_filter)
            name = getattr(recipient, "name", None) or recipient.card.name
            game.log.append(
                f"{name} gains prevention shield for {share} damage"
            )
        return True, "resolved"

    # "{2}: Prevent the next 1 damage that would be dealt **by this artifact**
    # this turn." (Barbed Wire.) CR 615.7's pool with CR 615.8's absent
    # recipient: it answers to one source and shields whoever that source was
    # about to damage. The shield hangs on the activator's seat, which is where
    # the cleanup sweep walks; `prevention.shields._table_shields` is what lets every
    # recipient find it.
    #
    # Read before the three recipient branches below, because the sentence names
    # none of them: `to_self` is False here and falling through would arm the
    # pool on the activator, which on this card shields exactly the player the
    # artifact is *not* about to damage on three turns out of four.
    if instruction.payload.get("any_recipient") and instruction.payload.get(
        "from_source"
    ):
        source_permanent = context.source_permanent
        if source_permanent is None:
            # The permanent armed the shield and then left (it was sacrificed to
            # pay a cost, or the ability was copied off a card that is not on
            # the battlefield). A shield waiting for a source nobody can name
            # would answer to *every* source, which is wider than the card.
            game.log.append(
                f"{source_name}: the source that would be shielded against is gone"
            )
            return True, "resolved"
        _record_shield(
            context,
            add_shield(
                caster,
                make_named_source_pool(amount, source_permanent, source_name),
            ),
            None,
        )
        game.log.append(
            f"{caster.name} prevents the next {amount} damage "
            f"{source_permanent.card.name} would deal this turn"
        )
        return True, "resolved"

    if instruction.payload.get("to_self"):
        _record_shield(
            context, _grant_pool(caster, amount, source_name, source_filter), None
        )
        game.log.append(f"{caster.name} gains prevention shield for {amount} damage")
        return True, "resolved"

    # Fylgja: "Remove a healing counter from this Aura: Prevent the next 1
    # damage that would be dealt to enchanted creature this turn." The shield
    # protects the permanent the ability's source is attached to — read through
    # `attached_host`, the one accessor for that relation, so an Aura that has
    # come unattached shields nothing rather than shielding itself.
    if instruction.payload.get("to_attached"):
        host = attached_host(game, context.source_permanent)
        if host is not None:
            _record_shield(
                context,
                _grant_pool(host, amount, source_name, source_filter),
                host,
            )
            game.log.append(
                f"{host.card.name} gains prevention shield for {amount} damage"
            )
        return True, "resolved"

    # Rock Hydra: "{R}: Prevent the next 1 damage that would be dealt to this
    # creature this turn." The shield protects the ability's own source
    # permanent, never the (defaulted) target.
    if instruction.payload.get("to_source"):
        source_perm = context.source_permanent
        if source_perm is not None:
            _record_shield(
                context,
                _grant_pool(source_perm, amount, source_name, source_filter),
                source_perm,
            )
            game.log.append(
                f"{source_perm.card.name} gains prevention shield for {amount} damage"
            )
        return True, "resolved"

    # "Prevent the next N damage that would be dealt to any target" (Healing
    # Salve's prevention mode, Samite Healer, …): the target may be a creature,
    # in which case the shield protects that creature rather than its controller.
    amount = _sized_for_recipient(game, context, instruction, target, amount)
    # "…that would be dealt to **target creature** this turn" (Oasis, Samite
    # Pilgrim, Kei Takahashi). The printed target is an *object*, and a player
    # is not one: the fall-through below — "no creature, so the player" — is
    # "any target"'s answer and was this sentence's too, so an announcement
    # that named nobody armed a **player** (the opponent, by the default seat)
    # with a shield the card cannot give one. Measured over the pool: 8 of the
    # 10 activated shields printing the phrase, and a bare ``activate`` over
    # the wire did the same.
    #
    # So an object description never reaches a player. A spell or an
    # activated ability announced bare has had the picker's first creature
    # named for it by now (`engine/bare_announcements.py`), so nothing reaches
    # this unnamed that was owed; what does is a *trigger* nothing chose a
    # target for, which takes the first creature the picker would have
    # offered — and with no legal creature shields nobody.
    described = instruction.payload.get("targets")
    object_only = isinstance(described, dict) and described.get("kind") == "object"
    unannounced = None
    if (
        object_only
        and single_chosen_id(context.target_permanent_id) is None
        and single_slot(context.target_permanent_index) is None
    ):
        unannounced = default_announced_permanent(game, instruction, context)
        if unannounced is None:
            game.log.append(f"{source_name}: no creature was named to shield")
            return True, "resolved"
    apply_prevention_shield(
        game, target, context.target_permanent_index, amount, source_name,
        context=context, source_filter=source_filter,
        # Temper's CR 615.5 rider. Only the chosen-creature branch reads it —
        # the lowering refuses the rider on every other recipient, because
        # "that creature" has nothing to point at when the shield goes round a
        # player.
        counter=str(instruction.payload.get("rider_counter") or ""),
        permanent=unannounced,
        object_only=object_only,
    )
    return True, "resolved"


@effect_handler("add_pt_counters_per_damage_prevented")
def add_pt_counters_per_damage_prevented(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Sacred Boon: "…At the beginning of the next end step, put a +0/+1 counter
    on that creature for each 1 damage prevented this way."

    A delayed triggered ability (CR 603.7) firing a whole turn after the spell
    resolved, so both of the things it names come from what that resolution
    recorded: the shield it armed and the creature it armed it on. The shield is
    the object rather than a number because the number did not exist yet — the
    total goes on accumulating for the rest of the turn, which is the whole
    reason the counters are placed at the end step and not at once.

    Nothing is placed when the shield absorbed nothing: "for each 1 damage
    prevented" over zero points is zero counters, which is the card and not a
    failure. Nor when the creature has left — CR 603.7c's object is addressed by
    the id that survives it, and a permanent that came back is a different one
    (CR 400.7).
    """
    recorded = context.trigger_context or {}
    shield = recorded.get(PREVENTION_SHIELD_RESULT)
    prevented = int(getattr(shield, "prevented", 0) or 0)
    permanent_id = recorded.get(PREVENTION_SHIELD_TARGET_RESULT)
    card_name = getattr(context.card, "name", "an effect")
    if prevented <= 0 or not isinstance(permanent_id, int):
        game.log.append(f"{card_name}: no damage was prevented this way")
        return True, "resolved"
    permanent = game.permanent_by_id(permanent_id)
    if permanent is None:
        game.log.append(f"{card_name}: the creature it shielded is gone")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "+0/+1"))
    placed = game.place_pt_counters(permanent, counter, prevented)
    if placed:
        game.log.append(
            f"{card_name}: {permanent.card.name} gets {placed} {counter} "
            f"counter{'s' if placed != 1 else ''}"
        )
    return True, "resolved"


def chosen_shield_source(game, context, *, from_target_channel: bool = True):
    """The object "a source of your choice" names (CR 615.8), or None.

    One reader for every card that prints the phrase, which is what this file
    had five copies of. The answer comes from whichever channel the *card* left
    free, in the order a more specific announcement beats a less specific one:

    * ``choices["chosen_source"]`` — the announcement field that exists for
      exactly this phrase (``engine/game_types.py``), sent as
      ``source_seat``/``source_permanent_index`` or ``source_stack_index``. It
      is read first because a card that names a target *as well* (Circle of
      Despair, Jade Monolith) has nowhere else to put the source.
    * a spell on the stack the caster picked as the ability's target.
    * a permanent the caster picked as the ability's target — the channel the
      four older cards use, because their printed sentence names nothing else.

    *from_target_channel* is False for a card whose target is something else
    entirely. Circle of Despair's target is the permanent or player the shield
    *protects*, so reading it as the source would arm the shield against the
    very thing it is guarding — the shield would then answer only to damage
    that thing dealt, and prevent nothing the card is played for.

    None is a legal outcome, not an error: an AI or headless activation picks no
    source at all, and every caller falls back to a shield answering to any
    source, which is spent on one instance either way.
    """
    recorded = (context.choices or {}).get("chosen_source")
    if recorded is not None:
        return recorded
    if context.stack_target is not None:
        # A spell on the stack: matched later by its card identity, which is the
        # same ``CardDefinition`` the spell deals its damage with (CR 120.7).
        return context.stack_target.card
    if not from_target_channel:
        return None
    return resolve_target_permanent(
        game, context, predicate=lambda p: True, fallback_players=()
    )


def _shield_target(game, context, *, allow_player: bool = True):
    """The player or permanent a shield with an announced recipient protects,
    or None.

    CR 115.4's "any target" is a creature, a planeswalker, a battle or a player,
    and the two halves arrive on different channels — a permanent through the
    ability's own target resolution, a player as ``context.target``. Asked in
    that order because a permanent target also fills the player slot with
    whoever controls it, so the player reading alone would put the shield around
    the wrong object every time a creature was named.

    *allow_player* is off for a printed noun that admits no player ("target
    **creature**", Charm Peddler). ``context.target`` is filled on every
    announcement — it is the seat whose battlefield the permanent was chosen
    from — so a card whose creature target could not be resolved would otherwise
    fall through and shield that seat, which is a recipient its sentence never
    names.
    """
    permanent = resolve_target_permanent(
        game, context, predicate=lambda p: True, fallback_players=(),
        fallback_on_invalid_choice=False,
    )
    if permanent is not None:
        return permanent
    return context.target if allow_player else None


def _arm_chosen_source_shield(
    game, context, build, *, recipient=None, from_target_channel: bool = True,
    verb: str = "will prevent the next damage",
) -> tuple[bool, str]:
    """Resolve the chosen source, arm the shield *build* makes, and log it.

    The body five handlers had a copy of, and then the body two kinds share
    once four of those handlers became one payload key
    (``_whole_shield_build``). What each caller really contributes is *build* —
    one ``shields.make_*`` call, which is to say one ``Shield.kind`` — and every
    other line was the same: read the choice, arm against it if there was one,
    arm a sourceless charge if there was not.

    *recipient* is who the shield protects, defaulting to the ability's
    controller (CR 109.5) because that is who every card but Circle of Despair
    names. It may be a ``PlayerState`` or a ``Permanent``: CR 615.1 puts a
    shield around either, and ``shields.add_shield`` has always taken both.
    """
    protected = recipient if recipient is not None else context.caster
    granted_by = context.card.name if context.card else None
    chosen = chosen_shield_source(
        game, context, from_target_channel=from_target_channel
    )
    add_shield(protected, build(chosen, granted_by))
    who = getattr(protected, "name", None) or protected.card.name
    if chosen is not None:
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{who} {verb} from {getattr(source_card, 'name', 'a source')}"
        )
    else:
        game.log.append(f"{who} {verb} dealt to them")
    return True, "resolved"


def default_damage_source(game, seat: int, *, colors: tuple[str, ...] = ()):
    """The source a seat that named none is taken to choose (CR 609.7a), or
    None when nothing on the table could be one.

    The stated default for "a source of your choice" where the choice cannot
    simply be skipped — a shield that lasts all turn has no sourceless form
    (``shields.PREVENT_ALL_FROM_CHOSEN_SOURCE``). In order: the topmost spell
    an opponent has on the stack (the burn spell this is being cast in
    response to), then an opponent's attacking creature with the greatest
    power, then an opponent's creature with the greatest power at all. Each is
    the source most likely to deal this seat damage this turn, which is the
    choice a player makes with the card.

    *colors* narrows the candidates to sources sharing one of them, for
    "…that shares a color with the mana spent on this activation cost"
    (Protective Sphere): a source outside them is not one the sentence lets
    the player choose.

    A spell comes back as its ``CardDefinition`` — the object it will deal its
    damage with (CR 120.7), and what ``chosen_shield_source`` returns for an
    announced one.
    """
    from ..object_colors import share_a_color

    def admitted(found: tuple[str, ...] | set[str]) -> bool:
        return not colors or share_a_color(colors, found)

    for item in reversed(game.stack):
        if getattr(item, "caster_index", seat) == seat:
            continue
        if item.ability_instruction is not None or item.card is None:
            # An ability on the stack is not a spell: the damage it causes is
            # dealt by the permanent it came from, which the creature scan
            # below is what finds.
            continue
        if admitted(game._stack_item_colors(item)):
            return item.card
    theirs = [
        perm
        for other in range(len(game.players))
        if other != seat and not game.players[other].lost
        for perm in game.controlled_by(other)
        if perm.is_creature and admitted(game._effective_colors(perm))
    ]
    if not theirs:
        return None
    return max(
        theirs,
        key=lambda perm: (bool(perm.attacking), perm.effective_power, -perm.permanent_id),
    )


def _either(against_source, sourceless):
    """One ``build`` for ``_arm_chosen_source_shield`` out of a builder pair:
    the shield against the chosen source, and the sourceless charge an AI or
    headless announcement that named none is armed with instead."""
    return lambda chosen, by: (
        against_source(chosen, by) if chosen is not None else sourceless(by)
    )


def _whole_shield_build(game, instruction, context):
    """The ``(build, verb)`` pair a whole-instance shield's payload arms, or
    None for a rider no interceptor performs.

    ``rider`` is CR 615.5's additional effect — the sentence printed after
    "prevent that damage" — in the word the parse wrote for it
    (``ast.PreventedRider.effect``). What it selects is ``Shield.kind``, which
    names the interceptor that consumes the shield, and so what happens once the
    shield has absorbed. Nothing *before* the interceptor differs: every card
    here prints Pentagram of the Ages' sentence and then one more, so each makes
    that sentence's choice (CR 609.7a, 615.8), runs its picker and resolves
    through its body. That is why the rider is payload on this kind rather than
    four kinds of its own, which is what it was until the round that folded
    them: four handlers around one body, and every reader of the kind — the
    picker table, the effect labels, the categories — saying the same thing four
    times.

    ``recipients`` is Shadowbane's second recipient, "…to you **and/or
    creatures you control**": a printed set of permanents the shield also
    covers, recorded as the phrase and asked of each damaged permanent
    (``prevention.shields._class_shields``). Its interceptor is the team one,
    whose rider gains life, so a team shield carries exactly that rider — the
    lowering refuses any other, and this refuses it again rather than arm a
    shield that pays for something the card does not print. The seat is
    recorded with the phrase, because "creatures **you** control" is the
    caster's "you" (CR 109.5) and by damage time the resolution is long over.

    ``rider_colors`` is the condition a rider may carry ("If damage from a
    **red** source is prevented this way", Honorable Passage). It rides the
    shield rather than being rechecked here, because CR 615.9 asks about the
    source when the damage would be dealt and this resolution is over by then.
    """
    payload = instruction.payload
    rider = payload.get("rider")
    rider_colors = tuple(payload.get("rider_colors") or ())
    if payload.get("recipients"):
        if rider != "gain_life":
            return None
        caster = context.caster
        recipients = dict(payload["recipients"])
        seat = game.players.index(caster) if caster in game.players else None
        return (
            lambda chosen, by: (
                make_team_source(chosen, recipients, seat, rider_colors, by)
                if chosen is not None
                else make_team_charge(recipients, seat, rider_colors, by)
            ),
            "will prevent the next damage to them or their creatures",
        )
    if rider is None:
        return _either(make_whole_source, make_whole_charge), "will prevent the next damage"
    if rider == "gain_life":
        # "You gain life equal to the damage prevented this way." (Reverse
        # Damage, Cho-Arrim Alchemist.)
        return (
            _either(make_life_gain_source, make_life_gain_charge),
            "armed a prevent-and-gain-life shield",
        )
    if rider == "exile_from_library":
        # "Exile cards from the top of your library equal to the damage
        # prevented this way." (Bone Mask.)
        return _either(make_exile_source, make_exile_charge), "will prevent the next damage"
    if rider == "damage_source_controller":
        # "If damage from a red source is prevented this way, this spell deals
        # that much damage to the source's controller." (Honorable Passage.)
        return (
            lambda chosen, by: (
                make_reflect_source(chosen, rider_colors, by) if chosen is not None
                else make_reflect_charge(rider_colors, by)
            ),
            "will prevent the next damage and answer it",
        )
    return None


@effect_handler("grant_whole_prevention_shield")
def grant_whole_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Pentagram of the Ages: "The next time a source of your choice would deal
    damage to you this turn, prevent that damage."

    CR 615.8's whole-instance shield. The choice it makes — a permanent on any
    battlefield, or a spell on the stack matched by the ``CardDefinition`` it
    will deal its damage with — is the printed phrase's, and Dark Sphere's
    halving shield makes it too. What follows the prevention is the payload's
    ``rider`` (Reverse Damage, Bone Mask, Shadowbane, Honorable Passage), read
    once by ``_whole_shield_build``: the shield kind it arms, and so the
    interceptor that performs the sentence after "prevent that damage".

    ``from_source`` is the third way the sentence names its source: not chosen
    at all, but printed — "The next time **this creature** would deal damage to
    you this turn" (Mercenaries). One payload key rather than a kind of its own,
    because the shield it arms is the same whole-instance shield; only where the
    source comes from differs.

    The shield goes on ``caster`` unless the payload names another recipient,
    and on Mercenaries that is not the permanent's controller: it prints "Any
    player may activate this ability", so the seat that paid is the seat
    protected (CR 109.5).
    """
    caster = context.caster
    granted_by = context.card.name if context.card else None
    if instruction.payload.get("from_source"):
        source_perm = context.source_permanent
        if source_perm is None:
            game.log.append(f"{granted_by}: its own source is gone")
            return True, "resolved"
        add_shield(caster, make_whole_source(source_perm, granted_by))
        game.log.append(
            f"{caster.name} will prevent the next damage {source_perm.card.name} "
            "would deal them"
        )
        return True, "resolved"
    if instruction.payload.get("source_from") == "target":
        # "The next time **target creature** would deal damage this turn, …"
        # (Awe Strike.) The source is the announced target, by id (CR 608.2b
        # has already blanked it if it left), and the shield hangs on the
        # caster's seat for the cleanup sweep while every recipient reaches it
        # (``prevention.shields._table_shields``). "You" is that seat.
        # No fallback: a shield keyed on a permanent the spell did not name
        # would stop some other creature's damage.
        source_perm = resolve_target_permanent(
            game, context, fallback_players=(), fallback_on_invalid_choice=False,
        )
        if source_perm is None:
            game.log.append(f"{granted_by}: its target is gone")
            return True, "resolved"
        add_shield(caster, make_targeted_source_shield(
            source_perm, game.players.index(caster),
            gain_life=instruction.payload.get("rider") == "gain_life",
            source_name=granted_by,
        ))
        game.log.append(
            f"{granted_by}: the next damage {source_perm.card.name} would deal "
            "this turn is prevented"
        )
        return True, "resolved"
    shaped = _whole_shield_build(game, instruction, context)
    if shaped is None:
        return False, (
            "no interceptor performs the rider "
            f"{instruction.payload.get('rider')!r} on this shield"
        )
    build, verb = shaped
    if instruction.payload.get("recipient") == "attached":
        # "Sacrifice this Aura: The next time a source of your choice would deal
        # damage to **enchanted creature** this turn, prevent that damage."
        # (Kithkin Armor.) The shield goes around the permanent this ability's
        # source is attached to, found through ``attached_host`` — the one
        # accessor for that relation, and the reason the cost being "sacrifice
        # this Aura" does not lose the host: CR 603.10's last-known information
        # is what that reader falls back to, and the Aura is already in a
        # graveyard by the time this line runs.
        #
        # The **target channel stays free for the source**, unlike Circle of
        # Despair below: this ability targets nothing, so "a source of your
        # choice" arrives exactly where Pentagram of the Ages' does.
        host = attached_host(game, context.source_permanent)
        if host is None:
            game.log.append(f"{granted_by}: nothing is enchanted to protect")
            return True, "resolved"
        return _arm_chosen_source_shield(
            game, context, build, recipient=host, verb=verb,
        )
    if instruction.payload.get("recipient") == "target":
        # "…would deal damage to **any target** this turn, prevent that
        # damage." (Circle of Despair; Honorable Passage with its rider.) The
        # shield goes around what the ability targeted rather than around its
        # controller — CR 615.1 puts one around a player *or* a permanent, and
        # `add_shield` has always taken both.
        #
        # The target channel is spent on that choice, so the source cannot come
        # from it: read from the target channel it would arm the shield against
        # the very permanent it protects, which answers only to damage that
        # permanent deals and prevents nothing the card is played for. The
        # announcement's own ``chosen_source`` field carries it instead — the
        # second prompt `payload_target_specs._whole_prevention_shield_spec` asks for, and
        # the one Jade Monolith has run for its two choices all along.
        #
        # Charm Peddler prints the same shield over "target **creature**", so
        # the player half of CR 115.4's union is admitted only where the
        # description says the union was printed.
        protected = _shield_target(
            game, context,
            allow_player=(instruction.payload.get("targets") or {}).get("kind")
            == "any",
        )
        if protected is None:
            game.log.append(f"{granted_by}: nothing is there to protect")
            return True, "resolved"
        return _arm_chosen_source_shield(
            game, context, build,
            recipient=protected, from_target_channel=False, verb=verb,
        )
    return _arm_chosen_source_shield(game, context, build, verb=verb)


@effect_handler("grant_half_prevention_shield")
def grant_half_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Dark Sphere: "The next time a source of your choice would deal damage to
    you this turn, prevent half that damage, rounded down."

    The same choice Reverse Damage's shield makes — a permanent on any
    battlefield, or a spell on the stack matched by the CardDefinition it will
    deal its damage with — because it is the same printed phrase (CR 615.8).
    What differs is only what the shield absorbs, and that is the shield's own
    arithmetic rather than anything decided here: half of an event nobody can
    size yet.
    """
    rounding = str(instruction.payload.get("half", "down"))
    return _arm_chosen_source_shield(
        game, context,
        lambda chosen, by: (
            make_half_source(chosen, rounding, by) if chosen is not None
            else make_half_charge(rounding, by)
        ),
        verb="will prevent half the next damage",
    )


@effect_handler("grant_forcefield_shield")
def grant_forcefield_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    # Honor the chosen unblocked attacker so only that creature's combat damage is
    # capped to 1. Fall back to a generic "next combat damage" cap for AI/headless
    # activations that supply no target.
    chosen = resolve_target_permanent(game, context, fallback_players=())
    # The card that armed the shield, for CR 616.1e's option beside another
    # (``prevention.shields._granted_by``) — every other shield here names it.
    granted_by = getattr(context.card, "name", None) or None
    if chosen is not None:
        add_shield(caster, make_capped_source(chosen, granted_by))
        game.log.append(
            f"{getattr(context.card, 'name', '') or 'An effect'} will prevent all "
            f"but 1 combat damage from {chosen.card.name}"
        )
    else:
        add_shield(caster, make_capped_charge(granted_by))
        game.log.append(
            f"{getattr(context.card, 'name', '') or 'An effect'} will prevent all "
            "but 1 combat damage from the next unblocked creature"
        )
    return True, "resolved"


@effect_handler("shield_target_land_from_destruction")
def shield_target_land_from_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Pyramids mode 2: "The next time target land would be destroyed this
    turn, remove all damage marked on it instead." Arms a one-shot shield the
    destroy paths consume via _consume_land_destruction_shield."""
    card = context.card
    target_land = resolve_target_permanent(
        game,
        context,
        predicate=lambda p: p.has_type("land"),
        fallback_players=(context.caster, context.target),
    )
    if target_land is None:
        game.log.append(f"{card.name}: no valid land target")
        return True, "resolved"
    target_land.metadata["land_destruction_shield_this_turn"] = True
    game.log.append(
        f"{card.name}: the next time {target_land.card.name} would be destroyed this turn, "
        "all damage marked on it is removed instead"
    )
    return True, "resolved"


@effect_handler("arm_mirror_damage")
def arm_mirror_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Eye for an Eye: the next damage dealt to you this turn by "a source of
    your choice" also hits that source's controller for the same amount.

    One ``next_damage.DamageMirror`` on the caster: the caster picks the
    source — a permanent on any battlefield (target_permanent_index) or a spell
    on the stack (stack_target) — and only damage from that source is
    mirrored, matched by identity. With no chosen source (AI / headless casts)
    the record answers to the next damage event from any source. One instance
    (CR 615.8): spent inside a simultaneous dealing, it mirrors everything that
    source deals the caster in that dealing (``Game._apply_mirror_damage``)."""
    caster = context.caster
    if context.stack_target is not None:
        # A spell on the stack: match later by its card identity (the same
        # CardDefinition the spell deals damage with when it resolves).
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(game, context, predicate=lambda p: True, fallback_players=())
    add_mirror(caster, DamageMirror(source=chosen, source_name=getattr(context.card, "name", None)))
    if chosen is not None:
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name}: the next damage {getattr(source_card, 'name', 'a source')} "
            f"deals to them this turn is mirrored to its controller ({context.card.name})"
        )
    else:
        game.log.append(
            f"{caster.name}: the next damage dealt to them this turn is mirrored "
            f"to its source's controller ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("lock_damage_to_target")
def lock_damage_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Damage that would be dealt to that creature this turn can't be prevented
    or dealt instead to another permanent or player." (Whippoorwill.)

    The inverse of every other handler in this file: it arms nothing, it takes
    the machinery *away*. `damage_events.damage_candidates` is the one place a
    damage event's contention set is assembled, and it drops the contenders
    that prevent or move the damage when the recipient carries this marker — so
    a shield added later is covered without knowing the clause exists.

    "That creature" is the object the sentence in front of it targeted, so no
    target is chosen again and nothing is described for the picker.
    """
    from ..damage_events import DAMAGE_LOCK

    perm = resolve_target_permanent(
        game, context,
        predicate=lambda p: p.is_creature,
        fallback_on_invalid_choice=False,
    )
    if perm is None:
        game.log.append(f"{context.card.name}: no creature to lock")
        return True, "resolved"
    perm.metadata[DAMAGE_LOCK] = True
    game.log.append(
        f"damage dealt to {perm.card.name} this turn can't be prevented or "
        f"redirected ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("forbid_damage_prevention")
def forbid_damage_prevention(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Damage can't be prevented this turn." (Flaring Pain.)

    One turn-long record on the caster's seat (CR 109.5), which the cleanup
    sweep ends with every other turn record — no ``Game`` field and no clearing
    line. ``damage_events.deal_damage`` reads it on every event and marks the
    event unpreventable, so protection, a Fog, a Circle and a Phantom's shield
    all stop preventing while a CR 614.9 redirect still moves the damage (the
    sentence names prevention and nothing else). A prevention effect with an
    additional effect still has that effect (CR 615.12).
    """
    from ..turn_replacements import (DAMAGE_PREVENTION, TurnReplacement,
                                     arm_turn_replacement)

    seat = game.players.index(context.caster)
    source_name = context.card.name if context.card else None
    arm_turn_replacement(
        game,
        TurnReplacement(seat=seat, event=DAMAGE_PREVENTION, source_name=source_name),
    )
    game.log.append(f"{source_name}: damage can't be prevented this turn")
    return True, "resolved"


def _arm_next_damage_rider(
    game, instruction, context, key: str, description: str
) -> tuple[bool, str]:
    """Put one of Desperate Gambit's two riders on the source this spell chose.

    The body both handlers below share, and the reason they are two handlers at
    all is the only line it does not contain: *which* rider. One arms a CR 614
    amount replacement and the other a CR 615 prevention, which are two
    registries, two order spaces and two interceptors — so the instruction kind
    names which, exactly as ``shields.Shield.kind`` names the interceptor that
    consumes a shield.

    The source is read out of the resolution scratchpad rather than off the
    board: "that source" and "it" name what the sentence in front of these chose
    (``choose_permanent``), and nothing about a battlefield records a choice. By
    ``permanent_id``, never by slot — anything leaving between the choice and
    this step renumbers every later index (CR 400.7).

    Choosing nothing is a legal outcome, not a failure: a controller with no
    permanents had nothing to choose, and the flip still happened. The rider is
    simply not armed, and the log says so rather than saying nothing.
    """
    source_from = str(instruction.payload.get("source_from"))
    if source_from == "event_subject":
        # "Whenever a creature attacks, flip a coin. If you win the flip, the
        # next time **that creature** would deal combat damage this turn, …"
        # (Impulsive Maneuvers.) The object the firing event was about, by the
        # id the fire site froze (CR 603.10) — the trigger chose nothing, so
        # there is no record of this resolution's to read.
        recorded = (context.trigger_context or {}).get("event_subject_permanent_id")
    else:
        recorded = (context.results or {}).get(source_from)
    card_name = getattr(context.card, "name", "an effect")
    source = game.permanent_by_id(recorded) if isinstance(recorded, int) else None
    combat_only = bool(instruction.payload.get("combat_only"))
    by = getattr(context.card, "name", None)
    if source is None or not arm(source, rider_key(key, combat_only=combat_only), by=by):
        game.log.append(
            f"{card_name}: "
            + ("that creature is gone" if source_from == "event_subject"
               else "no source was chosen")
        )
        return True, "resolved"
    game.log.append(
        f"{card_name}: the next {'combat ' if combat_only else ''}damage "
        f"{source.card.name} would deal this turn {description}"
    )
    return True, "resolved"


@effect_handler("double_next_damage_from_chosen_source")
def double_next_damage_from_chosen_source(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Desperate Gambit's winning flip: "the next time that source would deal
    damage this turn, it deals double that damage instead."

    Arms the CR 614 replacement in ``engine/replacements/damage.py``; the rider itself
    is a count on the chosen permanent (``engine/next_damage.py``), which is
    what gives it CR 400.7's lifetime and the turn's sweep for free.
    """
    return _arm_next_damage_rider(
        game, instruction, context, DAMAGE_DOUBLED_NEXT, "is doubled"
    )


@effect_handler("prevent_next_damage_from_chosen_source")
def prevent_next_damage_from_chosen_source(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Desperate Gambit's losing flip: "the next time it would deal damage this
    turn, prevent that damage."

    Arms the CR 615 shield in ``engine/prevention/``. It protects nobody in
    particular — the sentence names no recipient, so the record sits on the
    source and the prevention applies wherever that source's next damage was
    headed.
    """
    return _arm_next_damage_rider(
        game, instruction, context, DAMAGE_PREVENTED_NEXT, "is prevented"
    )

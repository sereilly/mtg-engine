"""Which object or seat a resolving instruction **names**.

A handler acts on whatever its sentence points at, and this is where the pointer
is followed. Three kinds of pointer:

* the targets announced for the object (CR 601.2c) — one
  (:func:`resolve_target_permanent`, over :func:`pick_target_permanent`),
  several (:func:`resolve_target_permanents`), several by slot
  (:func:`resolve_target_slots`), one share of a division
  (:func:`divided_target_permanent`), or the roles of a several-role spell,
  each asked again as it resolves (CR 608.2b, :func:`roles_still_legal`);
* what an earlier step of the same resolution recorded
  (:func:`recorded_permanent_ids`) and what a trigger's fire site froze
  (:func:`bound_permanent`, :func:`frozen_that_player_seat`,
  :func:`block_pair_permanents`, :func:`triggering_spell`);
* the words a sentence uses for an object nobody chose — "enchanted creature"
  (:func:`attached_host`), "defending player" (:func:`defending_player_seat`),
  "its controller" after "counter target spell"
  (:func:`stack_target_controller_seat`).

By id wherever the announcement carried one, never by slot alone: a permanent
that leaves renumbers every slot after it, and a slot is then whichever
permanent slid into it.

A floor, split out of ``_common`` at the 2,000-line cap's split round. It reads
``_filters`` — a graveyard role is asked again with the predicate its picker
offered it with — and nothing else of the handler package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence


if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
from ..oracle_types import named_no_target
from ..models import Permanent, PlayerState
from ._filters import graveyard_card_matches


def attached_host(
    game: "Game", source: "Permanent | None", *, last_known: bool = True
) -> "Permanent | None":
    """The permanent *source* is attached to — or, when *source* has already
    left mid-resolution, the one it was last attached to (CR 603.10 last-known
    information) — provided that host is still on the battlefield.

    Cocoon is why the fallback exists: "…sacrifice it, put a +1/+1 counter on
    enchanted creature, and that creature gains flying" removes the Aura in
    the very resolution whose later steps name the enchanted creature, and
    ``detach_aura`` has already cleared the live record by then.

    ``last_known=False`` drops that fallback, and a **continuous** effect must
    pass it. CR 603.10 is about an ability that has already begun resolving;
    CR 611.3b says a continuous effect applies only while its criteria are met,
    and "the Aura is attached to it" is one of them. An Equipment that
    unattaches stays on the battlefield (CR 704.5n) with the record still on
    it, so a recompute reading last-known information would keep buffing the
    creature it used to be on — forever, and with nothing to undo.

    **Last-known information is only for a source that has left.** CR 608.2h
    reads an object's *current* information while it is still in the zone the
    effect expects it in, and its last-known information only once it is not.
    So the fallback is asked only when *source* is off the battlefield: an
    Equipment unattached in response to its own ability, or a Licid that ended
    its Aura form, is still a permanent and is attached to nothing — "equipped
    creature" names no creature, rather than the one it used to be on. That is
    the same mistake the continuous-effect paragraph above guards against,
    arriving through a resolution instead of a recompute.
    """
    if source is None:
        return None
    host = source.metadata.get("attached_to")
    if host is None and last_known and not game.is_on_battlefield(source):
        host = source.metadata.get("last_attached_to")
    if host is None or not game.is_on_battlefield(host):
        return None
    return host


def resolve_own_combatant(
    game: Game,
    context: OracleExecutionContext,
) -> tuple[PlayerState, int, Permanent] | None:
    """Resolve a trigger fired *on a permanent about itself* — the shape combat
    triggers use, where ``_fire_creature_attacks_triggers`` /
    ``_fire_creature_blocks_triggers`` thread the permanent's own controller and
    battlefield index through ``target``/``target_permanent_index``. Returns
    ``(controller, index, permanent)``, or ``None`` if the context no longer
    points at a live permanent (already left combat/the battlefield).

    An attack trigger is the clearest case for identity: it is put on the stack
    during declare-attackers and resolves after every other trigger above it,
    any of which may have destroyed a creature and shifted the attacker's slot.
    The index is still returned, because callers report it — but it is
    *re-derived* from the permanent the id found, never carried."""
    controller = context.target
    if controller is None:
        return None
    permanent_id = context.target_permanent_id
    if isinstance(permanent_id, int):
        found = game.permanent_by_id(permanent_id)
        if found is not None and game.controls(controller, found):
            index = game.battlefield_index_of(found)
            if index is not None:
                return controller, index, found
    idx = context.target_permanent_index
    if not isinstance(idx, int) or not (0 <= idx < len(controller.battlefield)):
        return None
    return controller, idx, controller.battlefield[idx]


def defending_player_seat(game: "Game", context: "OracleExecutionContext") -> int | None:
    """The seat a printed "defending player controls" names here (CR 506.2).

    Two steps, in this order, and both of them are the rule rather than a
    fallback chain:

    * the seat the trigger's announcement **froze** (CR 603.10). A trigger
      names the combat it fired in, and by the time it resolves that combat may
      be over — or, in a multi-defender game (CR 802), a different attacker's
      defender may be the live answer. ``trigger_defending_player_index`` is
      the key every combat fire site stamps;
    * otherwise the live combat's (``defending_player_index_now``), because a
      *spell* printing the phrase is resolving inside the combat it names, and
      outside a combat phase there is no defending player at all — so the
      phrase matches nothing rather than matching a seat.

    None is a real answer and ``subject_matches`` refuses the word when it gets
    one, which is the direction that offers nothing rather than the whole table.

    Here rather than at each reader because there were **two** copies of it
    already (``handlers/pump`` for Yare, ``handlers/control_changes`` for
    Kukemssa Pirates) and three resolutions that meet the same phrase and asked
    nothing at all — so the narrowing rode the payload the whole way and was
    then not tested. Two of those were live: Sidar Jabari's "tap target
    creature defending player controls" refused every candidate and logged "no
    valid permanent to tap", and Jangling Automaton's "untap all creatures
    defending player controls" swept an empty set every time it attacked.
    """
    frozen = (context.trigger_context or {}).get("trigger_defending_player_index")
    if isinstance(frozen, int):
        return frozen
    return game.defending_player_index_now()


def pick_target_permanent(
    player: PlayerState | None,
    index: int | None,
    *,
    game: Game | None = None,
    permanent_id: object = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
    announced: bool = False,
) -> Permanent | None:
    """Core "honor the chosen target, else fall back" resolution.

    **For an announced object there is no "else".** *announced* is
    ``OracleExecutionContext.announced``: the resolution of a spell or an
    activated ability, whose targets a player announced (CR 601.2c / 602.2b)
    — named by the caller, or defaulted from the picker's own list as the
    object was announced (``engine/bare_announcements.py``). For those the
    answer is the announced permanent where it still answers this sentence
    (steps 0 and 1 below), and otherwise **nobody**: no scan (step 2), and no
    reading of the slot beside an id this sentence declined. Both were ways
    for a resolution to act on a permanent nobody named — a bare announcement
    resolved on whatever the scan met first, which is not the picker (it knows
    the noun and nothing of protection, shroud or "with flying"), and a named
    target the handler's own predicate rejected slid onto its neighbour.
    CR 608.2b's last sentence is the rule: an illegal target is not affected,
    and nothing takes its place. An "up to one target" announced with none is
    the same answer for the same reason.

    Steps 1's index and 2's scan remain for a context that is **not** an
    announcement: a triggered ability whose fire site stamped no target, a
    turn step's hand-built context, a test calling a handler directly.

    0. If ``permanent_id`` still names a permanent *player* controls and it
       passes ``predicate``, that is the target. This is the stable answer: the
       id was recorded when the target was chosen (CR 601.2c) and means the same
       permanent however the battlefield has been renumbered since.
    0b. If ``permanent_id`` was recorded and now names **no permanent at all**,
       the target is gone (CR 608.2b) and the answer is None. Nothing below is
       consulted — see the asymmetry below for why this one case fizzles.
    1. Otherwise, if ``index`` is a valid index into ``player``'s battlefield and
       that permanent passes ``predicate`` (default: is a creature), return it.
    2. Otherwise scan ``fallback_players`` (default: just ``player``) for the
       first permanent passing ``predicate``. Pass ``()`` to disable fallback,
       or ``fallback_on_invalid_choice=False`` to skip the fallback only when
       the player explicitly chose an illegal index (the choice fizzles).

    Step 0 is *additive* in one direction only, and the asymmetry is the point.
    An id that resolves to a permanent this caller cannot use — it changed
    controller, or stopped being a creature — falls through to the index
    behaviour this function has always had, rather than inventing a fizzle the
    rest of the engine is not yet written for. Those are questions about a
    permanent that still exists, and for an announced object they are answered
    above this function now: CR 608.2b's gate judges the target against its
    description, and where it is still legal on another battlefield the seat
    is settled from the id again before any handler runs
    (``ResolutionTargetsMixin.resettle_announced_target_seats``), so the *player* this
    is handed is the one the target is on.

    An id that resolves to **nothing** is a different question, and it has an
    answer. The recorded id is the choice (CR 601.2c/602.2b); CR 400.7 makes a
    permanent that has left the battlefield a *new object* if it ever comes
    back, so there is no permanent anywhere that the choice can still mean. The
    index cannot be it either: the slot renumbered when the chosen permanent
    left, so ``battlefield[index]`` is by construction a permanent nobody
    chose, and the fallback scan is one nobody even looked at. This is
    CR 608.2b at the resolver — "the target is gone" — and it is the only shape
    where the fallback can be shown to be wrong rather than merely unsupported.

    So: **an id that was recorded and no longer resolves is a fizzle; an id
    that was never recorded is not.** A targetless activation stamps no id
    (``permanent_ids_at`` maps a missing slot to None) and keeps the fallback —
    which is what ``handlers/destruction.arm_self_action_at_next_end_step``
    asks by hand for Goblin Ski Patrol, and what every caller that resolves a
    "this permanent" pronoun off the context relies on.
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    if game is not None and isinstance(permanent_id, int) and player is not None:
        chosen = game.permanent_by_id(permanent_id)
        if chosen is None:
            # CR 608.2b/400.7: a choice was recorded and its object has left.
            # Sandals of Abdallah watched whatever slid into the dead
            # creature's slot and the islandwalk landed there too; War Barge,
            # Runesword, the two Kjeldoran guards, Phantasmal Mount, Goblin
            # Sappers, Whippoorwill and Merieke Ri Berit all read the same
            # resolver. A spell, an activated ability and a trigger whose
            # target was chosen are refused above the instructions when
            # *every* target is gone (``legality_resolution.illegal_targets_refusal``);
            # this is what is left for the object that still resolves because
            # another of its targets is legal, and for a trigger whose target
            # a fire site stamped — and it is the reading a slot blanked by
            # ``blank_illegal_resolution_targets`` is given on purpose.
            return None
        # Scoped to *player* on purpose: the callers pass the battlefield the
        # target was chosen from ("a creature you control", "target artifact an
        # opponent controls"), and widening that here would be a targeting
        # change wearing an identity change's clothes. A target that changed
        # hands and is still legal has had its seat re-settled before this is
        # asked (``resettle_announced_target_seats``) — the record moved, not
        # this scope.
        if game.controls(player, chosen) and predicate(chosen):
            return chosen
        if announced:
            # The announced permanent is not one this sentence acts on, and
            # the slot beside its id is that same choice said twice.
            return None
    explicit = isinstance(index, int)
    if explicit and player is not None and 0 <= index < len(player.battlefield):
        candidate = player.battlefield[index]
        if predicate(candidate):
            return candidate
    if announced or (explicit and not fallback_on_invalid_choice):
        return None
    if fallback_players is None:
        fallback_players = (player,) if player is not None else ()
    for scan in fallback_players:
        found = next((p for p in scan.battlefield if predicate(p)), None)
        if found is not None:
            return found
    return None


def block_pair_permanents(game, context) -> list:
    """The creature(s) a block trigger's "that creature" names.

    One reader for both halves, because the two fire sites bind it differently
    and the difference is not the effect's business. On the *becomes blocked*
    half the blocker is the stack item's target. On the *blocks* half the target
    is the blocking creature itself — the fire site needs it there so a
    self-affecting trigger (Ydwen Efreet) can find itself — and the creatures the
    firing is about ride ``blocked_permanent_ids``, by stable id because a
    removal renumbers every later slot (CR 400.7).

    Reading the target on the blocks half is the bug this function exists to
    stop: the card would name *itself*, destroying or recolouring the blocker
    instead of what it blocked, and the trigger would still look as though it
    resolved.
    """
    blocked_ids = (context.trigger_context or {}).get("blocked_permanent_ids") or ()
    if blocked_ids:
        return [
            perm
            for perm in (game.permanent_by_id(pid) for pid in blocked_ids)
            if perm is not None
        ]
    victim = resolve_target_permanent(game, context, fallback_players=())
    return [victim] if victim is not None else []


def roles_still_legal(
    game: Game, context: OracleExecutionContext, payload: dict, *, observer: int
) -> bool:
    """CR 608.2b for a several-**role** spell: is every role still legal?

    Asked once, at resolution, of every role the instruction describes - its
    printed noun phrase through the same ``subject_matches`` the picker
    enumerated with, and its dependency through the same
    ``ROLE_RELATION_TESTS`` the picker narrowed with. Two readers of one table
    rather than a second re-check written by hand, which is the arrangement
    this engine keeps finding on the wrong side of.

    The relation is what makes the re-check necessary at all. A one-target
    spell whose target left is handled by the resolver returning None; a roles
    spell can have both targets present and the *relation between them* gone -
    the Wall left and came back, so CR 400.7 made it a new object with no
    block record, and the creature the caster named is no longer one it
    blocked.
    """
    from ..subject_filters import subject_matches
    from ..target_roles import role_is_seat

    targets = (payload or {}).get("targets") or {}
    roles = list(targets.get("roles") or ())
    resolved: list = []
    for role in roles:
        # **A role is not always a battlefield permanent.** Goblin Welder's
        # second slot is a card in a graveyard, whose "still legal" question is
        # a different one: it has no controller and no keywords to have gained
        # (CR 613.1 reads its printed line and nothing else), so what CR 608.2b
        # asks of it is whether it is still *there* and still answers the
        # printed noun. The stamp resolving to a live slot is the first half —
        # the same answer ``illegal_targets_refusal`` reads one zone over — and
        # ``graveyard_card_matches`` is the second, which is the predicate the
        # picker offered by.
        if role.get("kind") == "graveyard_card":
            stamp = resolve_role_graveyard_card(game, context, payload, role.get("role"))
            if stamp is None or game.graveyard_index_of(stamp) is None:
                return False
            if not graveyard_card_matches(role, stamp.card):
                return False
            if not _role_relation_still_holds(game, role, roles, resolved, stamp):
                return False
            resolved.append(stamp)
            continue
        # **A role is not always an object either.** "Target player gains
        # control of target permanent you control" (Donate) announces a *seat*
        # in slot 0, and what CR 608.2b asks of a player is the whole of what
        # can go wrong with one: they may have left the game (CR 800.4a), which
        # takes them out of everybody's opponents and out of "target player".
        # There is no noun phrase to re-read — the seat loop's own narrowings
        # (``opponents_only`` and the rest) are properties of the announcement
        # and are re-asked by ``roles_still_legal``'s caller through the same
        # picker, exactly as a permanent role's filter is.
        if role_is_seat(role):
            seat = resolve_role_player(game, context, payload, role.get("role"))
            if seat is None or game.players[seat].lost:
                return False
            if not _role_relation_still_holds(
                game, role, roles, resolved, game.players[seat]
            ):
                return False
            resolved.append(game.players[seat])
            continue
        # …and it may be a **spell** ("Counter target spell and … deals 3
        # damage to target creature", Suffocating Blast). What CR 608.2b asks
        # of one is whether it is still on the stack and still a spell the
        # printed phrase admits — the stack picker's own list, asked again for
        # this slot, by identity.
        if role.get("kind") == "spell":
            from ..target_descriptions import _from_targets_payload

            named = context.stack_target
            admitted = game._offered_stack_targets(
                observer, context.card, _from_targets_payload(role) or {}
            )
            if named is None or not any(obj is named for obj in admitted or ()):
                return False
            resolved.append(named)
            continue
        perm = resolve_role_permanent(game, context, payload, role.get("role"))
        if perm is None or not game.is_on_battlefield(perm):
            return False
        if not subject_matches(
            game, perm, role.get("filter") or {}, observer=observer,
            source=context.source_permanent,
        ):
            return False
        if not _role_relation_still_holds(game, role, roles, resolved, perm):
            return False
        resolved.append(perm)
    return bool(roles)


def _role_relation_still_holds(game: Game, role: dict, roles: list, resolved: list, obj) -> bool:
    """CR 608.2b for one role's *dependency*, asked of the objects settled so far.

    Split out of :func:`roles_still_legal`'s loop when a second arm needed it —
    a graveyard role's relation ("in **that player's** graveyard") is the same
    question as a permanent role's and is answered by the same table, and two
    copies of this lookup is exactly how a re-check comes to disagree with the
    picker it was written from.
    """
    from ..target_roles import role_dependency, role_relation_holds

    _relation, depends_on = role_dependency(role)
    earlier = next(
        (
            candidate for candidate, entry in zip(resolved, roles)
            if entry.get("role") == depends_on
        ),
        None,
    )
    return bool(role_relation_holds(role, earlier, obj, game))


#: The context keys a fire site freezes "that player" under, in the order this
#: reads them. Two, because two kinds of event name a player directly: one whose
#: *subject is a seat* ("each player's upkeep", "an opponent draws a card",
#: "a player attacks") and one whose subject is a **damage event**, whose seat
#: the announcement has always called ``defending_player_index``. A firing
#: stamps one or the other, never both, so the order is a lookup and not a
#: precedence.
#:
#: One table because "that player" is one printed phrase. Before this it was
#: three handlers each hardcoding whichever key its own card happened to
#: freeze, which is why the fourth — the targeted destroy, The Abyss and Feline
#: Sovereign — could be written with **neither** and nobody noticed: there was
#: no one place the omission was visible.
_THAT_PLAYER_CONTEXT_KEYS: tuple[str, ...] = (
    "event_subject_player",
    "defending_player_index",
)


def frozen_that_player_seat(game: Game, context: OracleExecutionContext) -> int | None:
    """The seat a printed "**that player**" names, or ``None`` if none was frozen.

    ``subject_matches`` refuses ``controller: "that_player"`` outright and says
    why: it is not a seat any read of the board can make, because it names a
    player the *event* picked. The resolution holding the trigger's context is
    the only place that seat exists (CR 603.10), so this is where the phrase is
    answered — and a caller that gets ``None`` must end the effect rather than
    drop the narrowing, since a dropped seat on a destroy is not a card that
    does less, it is one that reaches the wrong battlefield.
    """
    frozen = context.trigger_context or {}
    for key in _THAT_PLAYER_CONTEXT_KEYS:
        seat = frozen.get(key)
        if isinstance(seat, int) and 0 <= seat < len(game.players):
            return seat
    # …or the seat **an earlier step of this same resolution chose**. "Choose
    # target opponent who has at least two fewer creature cards in their
    # graveyard than you do. Destroy target nonblack creature **that player**
    # controls." (Keeper of the Dead.) No event fired, so nothing is frozen —
    # the seat was announced with the activation (CR 602.2b) and recorded by
    # the step that announced it, under the one key every "the player this
    # effect chose" is written under (``choose_target_player``,
    # ``choose_opponent``, both permanent-choice prompts).
    #
    # Read **after** the trigger context, never before it: a fire site's seat
    # is the one CR 603.10 froze and a resolution may well have chosen a
    # different player since, so the recorded pick is an answer where there
    # was none rather than a new winner where there already was one.
    # The literal every handler that writes this key spells; it is declared in
    # ``grammar/lowering/_record_keys.CHOSEN_PLAYER``, which the handler layer
    # does not import from (``handlers/delayed.py`` records the same).
    chosen = (context.results or {}).get("chosen_player")
    if isinstance(chosen, int) and 0 <= chosen < len(game.players):
        return chosen
    # A **spell** has no firing event, so there is nothing frozen to read — and
    # the pronoun still has an antecedent: the sentence in front of it. "Cast
    # this spell only during an opponent's turn. Tap target creature **that
    # player** controls." (Delirium.) The timing clause is the only thing in
    # that card naming a player, and the table that owns the phrase is what
    # answers — the same table the picker asks, so what a player was offered and
    # what the resolution acts on cannot disagree.
    from ..cast_restrictions import timing_fixed_seat

    caster = context.caster
    if caster in game.players and context.card is not None:
        return timing_fixed_seat(game, game.players.index(caster), context.card)
    return None


def triggering_spell(game: Game, context: OracleExecutionContext):
    """The spell a cast trigger fired on, if it is still on the stack; else
    ``None``.

    "Whenever a player casts a spell, counter **it** unless that player pays
    {3}." (Nether Void.) CR 603.3 puts the trigger on the stack above the spell
    it is about, and by the time it resolves anything may sit between the two —
    so the fire site freezes *which* spell (``cast_item``, the spell's own
    stack object) and this finds it by identity.

    **The card cannot answer.** ``cast_card`` rides the same event and three
    handlers used to look for "the stack item whose card is this one". A deck
    repeats one immutable ``CardDefinition`` per copy and both seats' decks are
    built from one catalog, so two Lightning Bolts on the stack are two objects
    with one card: Nether Void's trigger for the second Bolt armed its payment
    against the first, and a trigger whose own spell had been countered in
    response went on to counter a bystander that merely shared its card. Eight
    of the pool's nine readers did the first and all nine the second. The same
    reason ``counter_stack_ability`` finds "that ability" by
    ``activated_ability_item`` rather than by its source.

    ``None`` means the object is gone (CR 608.2b's shape), and a caller does
    the rest of what it can — never the same thing to another spell.
    """
    cast_item = (context.trigger_context or {}).get("cast_item")
    if cast_item is None:
        return None
    return next((item for item in game.stack if item is cast_item), None)


def stack_target_controller_seat(
    game: Game, context: OracleExecutionContext, *, spells_only: bool = False,
    recorded_only: bool = False,
) -> int | None:
    """The seat that controls the **spell this object is about**, or ``None``.

    "Counter target spell. **Its controller** loses 3 life." (Undermine.)
    "Counter target instant or sorcery spell unless **its controller** has
    Molten Influence deal 4 damage to them." One referent, two moments, and
    until now two readers that each knew half of it:

    * once a counter step has **chosen** its spell, the seat is the record
      that step wrote (``COUNTERED_SPELL_CONTROLLER``) — written when the
      spell is chosen, not when the counter succeeds, because by the next
      sentence the spell is a card in a graveyard, and CR 109.4 gives a card
      there no controller at all. So a rider reads last-known information
      (CR 608.2h) whether or not the spell could be countered;
    * before that — an offer made *instead of* the counter — nothing has been
      recorded yet, and the seat is read off the stack object itself (CR 112.2:
      a spell's controller is the player who put it on the stack): the spell
      the announcement named while it is still there (by identity), nobody
      once a named spell has left (CR 608.2b), and the top of the stack for a
      headless caller that named none.

    The offer actor (``offers._offered_seats``) and every recipient key
    that names this seat ask here, so "its controller" cannot be one player
    when it is asked and another when it is charged.

    The **controller**, never the owner (CR 108.3): a spell cast out of
    another player's pile answers with the seat that cast it.

    *spells_only* is the offer's own narrowing — "counter target … **spell**"
    has nobody to ask about an ability — and applies to the stack read alone;
    a record is written by a step that already chose a spell.

    *recorded_only* is a **rider's** reading: a sentence behind the counter
    names the spell that step chose and no other, so with no record nothing
    was chosen and nobody is named — never whatever happens to be on top of
    the stack by then, which may be the very object that is resolving.
    """
    from ..oracle_types import COUNTERED_SPELL_CONTROLLER

    recorded = (context.results or {}).get(COUNTERED_SPELL_CONTROLLER)
    if isinstance(recorded, int):
        return recorded if 0 <= recorded < len(game.players) else None
    if recorded_only:
        return None
    named = context.stack_target
    if named is not None:
        item = named if any(found is named for found in game.stack) else None
    else:
        item = game.stack[-1] if game.stack else None
    if item is None or (spells_only and item.is_ability):
        return None
    seat = item.caster_index
    return seat if 0 <= seat < len(game.players) else None


def resolve_role_permanent(
    game: Game,
    context: OracleExecutionContext,
    payload: dict,
    role: str,
) -> "Permanent | None":
    """The permanent chosen for one **role** of a several-role spell.

    A roles spell (Glyph of Delusion) carries its chosen targets as one
    positional list in *dependency* order, and this is the one place a role's
    name is turned back into its slot - through ``payload_role_slot``, reading
    the same ``targets`` description the picker and the cast gate read. A
    handler that counted slots by hand would be a second convention, and the
    two would disagree the first time a card printed its roles in a different
    order from the one it depends on.

    Strict, and deliberately so: by id, and with no fallback scan. The singular
    resolver's "hit something rather than fizzle" is right for a spell with one
    target and wrong here - a role that no longer resolves is CR 608.2b's
    illegal target, and falling back would point the effect at a permanent the
    caster never chose *for that role*. The index form beside the ids answers a
    caller that has one seat in hand (a test, the AI); the wire always sends
    ids, because the roles of one spell may sit on two battlefields.
    """
    from ..target_roles import payload_role_slot

    slot = payload_role_slot(payload, role)
    if slot is None:
        return None
    ids = context.target_permanent_id
    if isinstance(ids, list) and 0 <= slot < len(ids) and isinstance(ids[slot], int):
        return game.permanent_by_id(ids[slot])
    indices = context.target_permanent_index
    if isinstance(indices, list) and 0 <= slot < len(indices):
        return game.permanent_at(game.players.index(context.target), indices[slot])
    return None


def resolve_role_player(
    game: Game,
    context: OracleExecutionContext,
    payload: dict,
    role: str,
) -> "int | None":
    """The seat chosen for one **player** role of a several-role spell.

    :func:`resolve_role_permanent`'s sibling over a zone that is not a zone at
    all. The two beside it turn a role name into a *slot* and read that slot of
    a positional list; a seat has no such list, because a stack item carries the
    one player a spell targets under ``target_player_index`` and always has —
    the channel means exactly what this role means, and inventing a second
    arity beside it is the defect SET_PLAYBOOK records
    ``StackItem.target_permanent_id`` already having.

    So the slot is used for a different question: **is this role the one player
    role?** An announcement with two of them would read one seat twice, and the
    quiet direction of that is a spell doing something the caster never chose.
    A second player role is refused here rather than resolved to the first,
    which is the same direction ``resolve_role_permanent`` takes on a slot that
    no longer resolves.

    **Unless the announcement recorded its seats per role**
    (``target_roles.ROLE_SEATS``), which is what one naming two players does:
    "…creatures **target player** controls … creatures **another target
    player** controls" (Cultural Exchange). Then the slot is read the way its
    siblings read theirs — positionally — and the scalar is not consulted at
    all: a ``None`` there is a slot CR 608.2b has judged illegal, and the
    answer is nobody rather than whoever the scalar still names. The refusal
    above stands for a two-player payload announced *without* the list, which
    is an announcement the cast gate does not accept.
    """
    from ..targeting import spec_roles
    from ..target_roles import (payload_role_slot, recorded_role_seats,
                                role_is_seat)

    slot = payload_role_slot(payload, role)
    if slot is None:
        return None
    roles = spec_roles((payload or {}).get("targets"))
    if not (0 <= slot < len(roles)) or not role_is_seat(roles[slot]):
        return None
    recorded = recorded_role_seats(context)
    if recorded is not None:
        named = recorded[slot] if slot < len(recorded) else None
        if (
            isinstance(named, int) and not isinstance(named, bool)
            and 0 <= named < len(game.players)
        ):
            return named
        return None
    seats = [index for index, entry in enumerate(roles) if role_is_seat(entry)]
    if seats != [slot]:
        return None
    # By **identity**, never by ``list.index``: ``PlayerState`` is a mutable
    # dataclass, so two seats holding equal state compare equal and an equality
    # search would answer with whichever came first — the same value-vs-identity
    # trap the control seam and the hand-removal seam exist for, one zone-less
    # object over. ``Game.seat_index`` asks the same way and raises where there
    # is no answer; a role that no longer resolves is CR 608.2b's illegal
    # target, so None is the answer here.
    target = context.target
    seat = next(
        (index for index, player in enumerate(game.players) if player is target),
        None,
    )
    if seat is None or not _role_seat_is_still_a_target(game, context, roles[slot], seat):
        return None
    return seat


def _role_seat_is_still_a_target(
    game: Game, context: OracleExecutionContext, role: dict, seat: int,
) -> bool:
    """CR 608.2b for the **player** one role named: is that seat still one
    this role's announcement would offer?

    "An illegal target won't be affected by parts of a resolving spell's
    effect for which it's illegal" — and the only thing asked of a named
    player at resolution was whether they had left the game. A player who
    gained **shroud** in response (Ivory Mask, CR 702.18a) was still handed
    the permanent by Donate and still dealt Lunge's 2 damage, though no
    announcement could have named them by then.

    The question is the announcement's own, through the list the picker and
    the cast gate read (``Game._enumerate_targets`` over the role, exactly as
    ``legality_roles.role_target_options`` asks it), so "may be targeted" has one
    answer at both ends. Asked as a *triggered* ability's would be: that
    skips the one test which depends on what kind of object is resolving —
    "can't be the targets of spells or activated abilities" (Peace Talks),
    which this context cannot tell apart — and nothing else.

    True where the resolving object's controller cannot be found: a context
    with no seat to ask from is not evidence that a target went illegal.
    """
    caster = next(
        (index for index, player in enumerate(game.players) if player is context.caster),
        None,
    )
    if caster is None:
        return True
    source = context.source_permanent
    return any(
        entry.get("kind") == "player" and entry.get("seat") == seat
        for entry in game._enumerate_targets(
            caster, context.card, dict(role), for_cast=False,
            source_permanent=source, ability_source=source, triggered=True,
        )
    )


def resolve_role_graveyard_card(
    game: Game,
    context: OracleExecutionContext,
    payload: dict,
    role: str,
):
    """The card chosen for one **graveyard** role, as the
    :class:`GraveyardTarget` the announcement stamped, or None.

    :func:`resolve_role_permanent`'s sibling one zone over, and it has to be a
    sibling rather than a branch: that one resolves an id through
    ``permanent_by_id``, and a card in a graveyard has no id to resolve — two
    copies of one card there are literally one ``CardDefinition``. The stamp is
    the identity (pile plus which copy), and where it sits *now* is
    ``Game.graveyard_index_of``, asked by the caller at the moment it acts.

    Strict, and for :func:`resolve_role_permanent`'s reason: the slot comes
    from ``payload_role_slot``, reading the same ``targets`` description the
    picker and the announcement gate read, and there is no fallback scan. A
    role that no longer resolves is CR 608.2b's illegal target, not an
    invitation to reanimate whichever artifact card is nearest.
    """
    from ..target_roles import payload_role_slot

    slot = payload_role_slot(payload, role)
    if slot is None:
        return None
    stamps = context.target_graveyard_card
    if isinstance(stamps, list):
        return stamps[slot] if 0 <= slot < len(stamps) else None
    return stamps if slot == 0 else None


def recorded_permanent_ids(context, key) -> tuple[int, ...]:
    """Every permanent id an earlier step of this resolution recorded under *key*.

    **The ``permanents_from`` channel's arity, decided in one place.** That
    payload key names a scratchpad record, and its twenty producers disagreed
    about shape: a reanimation, a sweep and a tap write a *list* of ids, while a
    choose-one prompt and a targeting steal write a bare id. Twenty reader sites
    across eight ``handlers/`` files each made their own assumption, and two of
    them — ``counters.add_counter_to_target`` and ``prevention``'s shield grant —
    had grown a local normalisation whose own comment called itself "the local
    half of a wider question". Nothing was broken, but only because no
    list-producer happened to feed a scalar reader; three sets in a row added
    producers and left the question open, and by Alliances the readers were no
    longer a list anybody could hold in their head while adding one.

    So the channel is **always a sequence**, read here and nowhere else. A
    producer that writes a bare id is read as a sequence of one, which is what
    every iterating reader already assumed and what the two local normalisations
    already did — this is those two, promoted to the channel's definition rather
    than added to as a third.

    An absent record is an empty sequence: a step that recorded nothing is a
    legal outcome (the seat had no creature, the reanimation found no card), not
    an error.

    **And what a producer wrote may be the permanents themselves**, which is the
    same question one level down and was answered the same way for the same
    reason. ``chosen_this_way_objects`` holds live ``Permanent`` objects — the
    sweep that reads it needs their identity (Raiding Party's "all Plains that
    weren't chosen this way") — and Equipoise's "then the chosen permanents
    phase out" is the first sentence to feed that record to *this* reader. Under
    the old body every entry failed ``isinstance(entry, int)`` and was dropped,
    so the phase-out named the right permanents and moved none of them: a card
    reporting supported, claiming every sentence, carrying no hollow line, and
    doing nothing. Reading the id off an object here is what makes the channel's
    element shape as decided as its arity, rather than adding a third local
    normalisation somewhere downstream.
    """
    if key is None:
        return ()
    recorded = (getattr(context, "results", None) or {}).get(str(key))
    if recorded is None:
        return ()
    if isinstance(recorded, int):
        return (recorded,)
    if not isinstance(recorded, (list, tuple)):
        recorded = (recorded,)
    ids = []
    for entry in recorded:
        if isinstance(entry, int):
            ids.append(entry)
            continue
        found = getattr(entry, "permanent_id", None)
        if isinstance(found, int):
            ids.append(found)
    return tuple(ids)


def one_recorded_permanent_id(context, key) -> int | None:
    """The single permanent id recorded under *key*, or None.

    The half of :func:`recorded_permanent_ids` a sentence about **one** object
    needs — "destroy that creature", "gain control of it", "sacrifice it". Those
    readers used to take the record raw and index nothing, so a list-shaped
    producer would have reached them as an unhashable id and raised; that was
    the failure this channel had been carrying, latent, since Fallen Empires.

    It asserts rather than picking: a reader written for one object that is
    handed two has been fed by a producer it was never paired with, and choosing
    the first would be the effect acting on whichever object happened to be
    recorded first. That is the direction this repo refuses everywhere else.
    """
    recorded = recorded_permanent_ids(context, key)
    if not recorded:
        return None
    assert len(recorded) == 1, (
        f"'permanents_from' record {key!r} holds {len(recorded)} permanents "
        "where this sentence names one"
    )
    return recorded[0]


def resolve_target_permanent(
    game: Game,
    context: OracleExecutionContext,
    *,
    player: PlayerState | None = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Resolve the permanent a spell or ability acts on — the context-based
    wrapper over :func:`pick_target_permanent` (see it for the semantics).

    Takes the game because identity is a *board* question: the id on the context
    means nothing without something to resolve it against. Every handler already
    receives the game as its first argument, so this reads the same way the
    handler signature does.

    **An announcement that named nobody resolves to nobody** (CR 601.2c: "up
    to one target creature" at zero; CR 115.6). Asked here, above the picker,
    because the picker's scan is what the empty target fields would otherwise
    reach — and the record (``oracle_types.NAMED_NO_TARGET``) rides the
    context's ``choices``, which the picker is not handed."""
    if named_no_target(context.choices):
        return None
    return pick_target_permanent(
        player if player is not None else context.target,
        _one_choice(context.target_permanent_index),
        game=game,
        permanent_id=_one_choice(context.target_permanent_id),
        predicate=predicate,
        fallback_players=fallback_players,
        fallback_on_invalid_choice=fallback_on_invalid_choice,
        announced=bool(getattr(context, "announced", False)),
    )


def bound_permanent(
    game: Game,
    context: OracleExecutionContext,
    *,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: "Sequence[PlayerState] | None" = None,
) -> Permanent | None:
    """The permanent a sentence's back-reference names — "that creature", "it",
    "its controller" — resolved against the **innermost** binding.

    Two bindings can be in scope at once, and the printed pronoun cannot say
    which. A spell or ability binds the target it chose (CR 601.2c), and a
    ``for_each`` running over permanents binds the object of the iteration it is
    in the middle of. Inside a loop the loop wins, because that is what the loop
    is: "Choose X target attacking creatures. **For each of those creatures**,
    its controller may pay {1} … destroy **that creature** at end of combat"
    (Winter's Chill) names a different creature each time round, and the
    resolution's own target list is *all* of them.

    Outside a loop this is exactly :func:`resolve_target_permanent`, which is
    why it is a wrapper rather than a second reader: every caller that already
    resolved a target keeps doing so, and the only thing that changes is that
    the loop's object is asked about first.

    ``iteration_target`` is not always a permanent — a loop may walk cards in a
    hand (Sylvan Library) — so the id is what qualifies it, never the mere
    presence of an item.
    """
    iterated = context.iteration_target
    if getattr(iterated, "permanent_id", None) is not None:
        if predicate is None or predicate(iterated):
            return iterated
        return None
    return resolve_target_permanent(
        game, context, predicate=predicate, fallback_on_invalid_choice=False,
        fallback_players=fallback_players,
    )


def _one_choice(chosen: object) -> object:
    """The first entry of a multi-target choice, or *chosen* unchanged.

    A single-target handler must never be handed a list: ``pick_target_permanent``
    would fail ``isinstance(index, int)``, fall through to its scan, and hit the
    first creature on the battlefield instead of a chosen one. Reading the first
    entry keeps a handler that was only ever written for one target pointed at a
    target the player actually named — the lowering is what decides whether a
    several-target line reaches such a handler at all, and it refuses.
    """
    if isinstance(chosen, list):
        return chosen[0] if chosen else None
    return chosen


def divided_target_permanent(game: "Game", entry):
    """The permanent one ``divided_targets`` entry names, or None.

    One resolver for the three handlers that read that list (damage, prevention
    and the distributed counter placement), because the way an entry becomes a
    permanent is not three questions. Each of them resolved it by **index**, and
    an index is not an address: the battlefield renumbers as soon as anything
    leaves it, so an entry announced under CR 601.2c against slot 1 named
    whoever slid into slot 1 by the time the spell resolved. Their bounds checks
    were satisfied by the wrong permanent, so nothing fizzled and nothing
    logged — Pyrotechnics simply dealt the departed target's share to the
    survivor.

    The id first (CR 400.7 makes it one object for one stay on the
    battlefield), the index only as the fallback for an entry that carries no
    id — a hand-written list in a test, or one built before the cast path
    stamped them.

    None for a player's face, which is not a permanent, and None for a
    permanent that has left: CR 608.2b makes that target illegal, and dropping
    it is every caller's own next line.
    """
    from ..divided_damage import divided_entry, divided_entry_id

    seat, index, _share = divided_entry(entry)
    if not isinstance(seat, int) or not 0 <= seat < len(game.players):
        return None
    if index is None:
        return None
    permanent_id = divided_entry_id(entry)
    if permanent_id is not None:
        return game.permanent_by_id(permanent_id)
    return game.permanent_at(seat, index)


def names_a_target_list(instruction) -> bool:
    """Whether *instruction*'s target description names more than one slot.

    Read off the description the lowering wrote rather than off the choices the
    resolution happens to carry: a two-target ability whose player named one
    creature is still a two-target ability, and deciding by what arrived would
    make the strict multi-slot resolution below silently fall back to the
    forgiving single-slot one.

    Here rather than in one handler family, because it is the question every
    caller of :func:`resolve_target_permanents` has to answer first and a second
    family now asks it (``handlers/prevention.py``'s Redeem). It is a *floor*,
    not a family: it reads a payload and nothing else.
    """
    targets = instruction.payload.get("targets")
    if not isinstance(targets, dict):
        return False
    count = targets.get("count")
    return (
        count == "x"
        or (isinstance(count, int) and count > 1)
        or bool(targets.get("unbounded"))
    )


def described_target_predicate(
    game: Game, instruction, context: OracleExecutionContext
) -> "Callable[[Permanent], bool] | None":
    """The predicate a resolver should hold a chosen permanent to when the
    instruction's printed target is **not a creature** — or None, which is the
    resolvers' own default (a creature).

    "{W}: Target **permanent** becomes white until end of turn." (Aurora
    Griffin.) Both target resolvers default to ``is_creature``, because nearly
    every sentence that reaches them names one. A handler written for those
    sentences and then handed a description that names an artifact, a land or
    any permanent at all drops what the player chose — the plural resolver
    answers "nothing was chosen" and the singular one falls through to its scan
    and finds a creature nobody aimed at. Either way the picker offered the
    permanent, the cost was paid and the effect went somewhere else or nowhere.

    So the description the lowering wrote for the *picker* is read back for the
    *resolution*: one printed noun phrase, asked through ``subject_matches``
    both times. A description that names a creature answers None and keeps the
    default, so no instruction that worked before resolves differently.
    """
    described = (instruction.payload.get("targets") or {}).get("filter")
    if not isinstance(described, dict) or described.get("type_filter") == "creature":
        return None
    from ..subject_filters import subject_matches

    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )

    def admits(candidate: Permanent) -> bool:
        return subject_matches(
            game, candidate, described, observer=observer,
            source=context.source_permanent,
        )

    return admits  # described_target_predicate


def default_announced_permanent(
    game: Game, instruction, context: OracleExecutionContext, *, prefer: str = "you",
) -> Permanent | None:
    """The permanent a **triggered** resolution falls to when nothing named
    one: the first the picker would have offered — the controller's own before
    anybody else's for *prefer* ``"you"`` (a benefit), an opponent's first
    otherwise. None when the picker offers no permanent.

    **Never for an announced object.** A spell or an activated ability that
    owed a target and named none had the picker's first entry named for it as
    it was announced (``engine/bare_announcements.py``), so by the time a
    handler runs there is nothing left unnamed that was owed — and what was
    *not* owed ("up to one target creature", announced with none) names
    nobody, which is an answer and not a gap for a handler to fill. This used
    to answer for both, as the one handler-side default drawn from the
    picker's list; the announcement makes that default now, for every
    sentence at once.

    What is left is the trigger whose fire site stamped no target: its
    handler's ordinary answer is :func:`pick_target_permanent`'s scan, which
    knows what the sentence *names* and nothing about what may be *targeted*
    — protection, shroud, "other than this creature" — and this asks the
    announcement's own list instead (``Game._enumerate_targets`` over the
    spec the instruction derives). For a handler whose own fallback has no
    permanent to give: a prevention shield's was the *player*.
    """
    from ..legality import targeting_instruction
    from ..targeting import derive_instruction_spec

    if getattr(context, "announced", False):
        return None
    caster = context.caster
    if caster not in game.players:
        return None
    spec = derive_instruction_spec([instruction])
    if not spec or spec.get("kind") in ("none", "modal", "hand_card", "player"):
        return None
    seat = game.players.index(caster)
    source = context.source_permanent
    offered = [
        entry for entry in game._enumerate_targets(
            seat, context.card, dict(spec), for_cast=False,
            ability_instruction=targeting_instruction(instruction),
            source_permanent=source, ability_source=source,
        )
        if entry.get("kind") == "permanent"
    ]
    own_first = prefer == "you"
    offered.sort(key=lambda entry: (entry["seat"] == seat) != own_first)
    for entry in offered:
        chosen = game.permanent_at(game.players[entry["seat"]], entry["index"])
        if chosen is not None:
            return chosen
    return None


def resolve_target_permanents(
    game: Game,
    context: OracleExecutionContext,
    *,
    player: PlayerState | None = None,
    predicate: Callable[[Permanent], bool] | None = None,
) -> list[Permanent]:
    """Every permanent a several-target spell or ability named (CR 115.1c).

    The plural of :func:`resolve_target_permanent`, and deliberately *not* built
    on it: the singular one falls back to scanning the battlefield when a chosen
    target no longer resolves, which is right for one target ("hit something
    rather than fizzle") and wrong for several — a fallback per slot would turn
    "up to two target creatures" into two counters on the same creature the
    moment one target died.

    So each slot is resolved strictly, by id first and index second, and a slot
    that no longer answers is simply dropped: CR 608.2b says an illegal target is
    not affected while the rest of the effect still happens. Duplicates are
    dropped by identity for the same reason — two slots that decayed onto one
    permanent would double an effect the player only chose once.

    Returns [] when nothing was chosen, which is a legal outcome of "up to N".
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    owner = player if player is not None else context.target
    indices = _as_slots(context.target_permanent_index)
    ids = _as_slots(context.target_permanent_id)
    # Positional pairing: `permanent_ids_at` keeps a slot that did not resolve as
    # None rather than dropping it, so the two lists stay the same length and
    # index k means the same choice in both.
    found: list[Permanent] = []
    for slot in range(max(len(indices), len(ids))):
        permanent_id = ids[slot] if slot < len(ids) else None
        index = indices[slot] if slot < len(indices) else None
        chosen = None
        if game is not None and isinstance(permanent_id, int):
            candidate = game.permanent_by_id(permanent_id)
            # No seat check on this branch. An id *is* the identity (CR 400.7),
            # so asking which battlefield it sits on is the index model showing
            # through — and it is wrong for a description whose slots are on two
            # boards ("target creature you control … another target creature").
            # What restricts a slot is its own filter, which the caller's
            # predicate carries; the index fallback below keeps the seat because
            # a bare index means nothing without one.
            if candidate is not None and predicate(candidate):
                chosen = candidate
        if chosen is None and isinstance(index, int) and owner is not None:
            # Through the seam, not a raw subscript: the id above is the stable
            # answer and this is only the fallback for a choice made before ids
            # existed on the wire, so it has no business opening a second way to
            # read a battlefield.
            candidate = game.permanent_at(owner, index)
            if candidate is not None and predicate(candidate):
                chosen = candidate
        if chosen is not None and not any(chosen is seen for seen in found):
            found.append(chosen)
    return found


def resolve_target_slots(
    game: Game,
    context: OracleExecutionContext,
    count: int,
    *,
    player: PlayerState | None = None,
) -> list[Permanent | None]:
    """The permanent each of *count* chosen slots names, **positionally**.

    The difference from :func:`resolve_target_permanents` is the whole reason
    this exists: that one *compacts*. It drops a slot that no longer answers and
    dedupes by identity, so a caller reading ``chosen[0]`` and ``chosen[1]``
    reads the wrong slot the moment the first target has left — slot 1's
    permanent slides into position 0. That is safe only where the two slots are
    disjointly filtered (Primal Might's "you control" / "you don't control"
    reject the impostor) and unsafe wherever they are not: Rookie Mistake's slots
    are both a bare "target creature", so a decayed first slot would hand the
    *second* creature the first slot's +0/+2.

    So this pads: slot k is index k, or None. Nothing is deduped here either —
    "another" is a *printed* restriction, and a caller that has one enforces it
    where it can say which of the two slots to drop (the later one, CR 608.2b).
    No fallback scan, for the reason `resolve_target_permanents` documents.
    """
    ids = _as_slots(context.target_permanent_id)
    indices = _as_slots(context.target_permanent_index)
    owner = player if player is not None else context.target
    found: list[Permanent | None] = []
    for slot in range(count):
        permanent_id = ids[slot] if slot < len(ids) else None
        chosen = None
        if isinstance(permanent_id, int):
            # No seat check: an id *is* the identity (CR 400.7), and a pair of
            # slots may sit on two battlefields.
            chosen = game.permanent_by_id(permanent_id)
        if chosen is None:
            index = indices[slot] if slot < len(indices) else None
            if isinstance(index, int) and owner is not None:
                chosen = game.permanent_at(owner, index)
        found.append(chosen)
    return found


def _as_slots(chosen: object) -> list:
    """A chosen-target field as a list of slots, whatever shape it arrived in."""
    if isinstance(chosen, list):
        return list(chosen)
    return [] if chosen is None else [chosen]


def _resolve_graveyard_slots(caster, context, count, eligible):
    """The cards *count* chosen graveyard slots name, removed from the graveyard.

    **An index is not an identity** (ROADMAP idiom #11), and a graveyard is the
    hand's case rather than the battlefield's: a card there has no
    ``permanent_id``, and two copies of one card are literally one
    ``CardDefinition`` object, so neither an id nor ``is`` can tell two slots
    apart. What can is the order of removal. Each slot is resolved to its card
    *before* anything leaves the zone, and the removals then run highest index
    first, because popping slot 0 slides every later card down one and would
    hand slot 1 the wrong card - the graveyard spelling of the bug
    :func:`resolve_target_slots` exists for on the battlefield.

    A repeated index collapses: CR 601.2c says one instance of "target" cannot
    name the same object twice, so a client sending ``[0, 0]`` gets one card
    back, not two. A slot that is out of range or names an ineligible card is
    dropped (CR 608.2b) and the rest of the effect still happens; an empty
    answer is a legal outcome of "up to N".
    """
    chosen = context.target_permanent_index
    slots = chosen if isinstance(chosen, list) else ([] if chosen is None else [chosen])
    graveyard = caster.graveyard
    seen: set[int] = set()
    resolved: list[tuple[int, object]] = []
    for slot in slots[:count]:
        if not isinstance(slot, int) or slot in seen:
            continue
        if not (0 <= slot < len(graveyard)) or not eligible(graveyard[slot]):
            continue
        seen.add(slot)
        resolved.append((slot, graveyard[slot]))
    for index, _card in sorted(resolved, key=lambda pair: pair[0], reverse=True):
        graveyard.pop(index)
    # Printed order, not removal order: the hand and the log read left to right.
    return [card for _index, card in resolved]

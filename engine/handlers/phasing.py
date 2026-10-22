"""Phasing (CR 702.26): a permanent treated as though it doesn't exist.

The handler twin of ``engine/grammar/lowering/phasing.py``. Phasing out a
target, the source, a recorded set, an enchanted or a bound creature, a block
pair or every permanent a phrase names, for as long as its source stays; the
simultaneous swap Time and Tide prints; and the "can't phase out" prohibition.
A phased-out permanent has not changed zones (CR 702.26d): the machinery is
``Game.phase_out_permanent``, and the object phases back in at its controller's
next untap step.

Split out of ``zones.py`` at the 2,000-line cap's split round. Nothing here
moves a card between zones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..linked_exile import until_leaves_has_ended
from ..models import Permanent
from ._targets import resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("phase_out_target_creature_until_source_leaves")
def phase_out_target_creature_until_source_leaves(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    if until_leaves_has_ended(game, source_permanent):
        # Oubliette's ruling (2020-08-07), which is CR 610.3b's rule applied to
        # phasing: "If Oubliette leaves the battlefield before its triggered
        # ability resolves, the target creature won't be phased out or tapped."
        game.log.append(
            f"{card.name} left the battlefield before its ability resolved, "
            "so nothing phases out"
        )
        return True, "resolved"
    target_perm = resolve_target_permanent(game, context, predicate=lambda p: p.is_creature)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    owner_index = game.controller_index_of(target_perm)
    if owner_index is None:
        return True, "resolved"
    # By identity throughout: ``list.remove`` compares by value, and Permanent is
    # a dataclass with generated __eq__, so it takes the first *equal* permanent
    # — an opponent's identically-stated copy of the same card — rather than the
    # one that was chosen.
    owner_player = game.players[owner_index]
    game.remove_from_battlefield(target_perm)
    # Auras/Equipment attached to the phased creature phase out with it (CR 702.26h).
    attachments: list[tuple[int, Permanent]] = []
    for seat, player in enumerate(game.players):
        leaving = [
            perm for perm in game.controlled_by(seat)
            if perm.metadata.get("attached_to") is target_perm
        ]
        if leaving:
            game.remove_all_from_battlefield(leaving)
            attachments.extend((seat, perm) for perm in leaving)
    source_permanent.metadata["phased_out_permanent"] = target_perm
    source_permanent.metadata["phased_out_owner_index"] = owner_index
    source_permanent.metadata["phased_out_attachments"] = attachments
    game.log.append(f"{card.name} phases {target_perm.card.name} out")
    return True, "resolved"


@effect_handler("phase_out_target")
def phase_out_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature you don't control phases out." (Teferi, Master of
    Time's −3.) CR 702.26: not a zone change — the machinery is
    Game.phase_out_permanent, and the object returns at its controller's next
    untap step.

    **Not "creature" — whatever the printed noun phrase said.** The predicate
    used to be the resolver's default, ``is_creature``, and Reality Ripple
    ("Target **artifact, creature, or land** phases out") compiled supported,
    offered all three to the picker and then silently did nothing to two of
    them: the handler declined a target the engine had already accepted, logged
    "no valid target" and let the spell resolve. Asked through the same
    ``subject_matches`` the picker enumerated with — with the caster as observer
    (CR 109.5), so Teferi, Master of Time's "creature **you don't control**" is
    tested here too rather than only at announcement.
    """
    from ..subject_filters import subject_matches
    from ._targets import block_pair_permanents

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(context.caster)
    # "Whenever this creature becomes blocked by a creature, put **that
    # creature** on top of its owner's library." (Elven Warhounds.) The
    # permanent is the one the block pair bound, not a chosen target — same
    # zone change, and the subject key is the only thing that differs, which is
    # why it is a payload here rather than a second handler.
    #
    # ``block_pair_permanents`` rather than the stack item's target, because the
    # two halves of the pair are frozen differently and reading the target on
    # the *blocks* half names the source itself.
    if instruction.payload.get("subject") == "block_pair":
        bound = block_pair_permanents(game, context)
        if not bound:
            game.log.append(f"{context.card.name}: the blocking creature has left")
            return True, "resolved"
        target_perm = bound[0]
    else:
        target_perm = resolve_target_permanent(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, described, observer=observer,
                source=context.source_permanent,
            ),
        )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target")
        return True, "resolved"
    game.phase_out_permanent(target_perm)
    return True, "resolved"


@effect_handler("phase_out_recorded_permanents")
def phase_out_recorded_permanents(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…choose a land that player controls, then **the chosen permanents phase
    out**." (Equipoise, CR 702.26.)

    The set an earlier step of this same resolution recorded, read through
    ``recorded_permanent_ids`` — the one reader of the ``permanents_from``
    channel, so this cannot disagree with the twenty other steps that write it
    about whether a record is one id or a list.

    **Anything no longer on the battlefield is skipped**, and that is the
    printed reading rather than a guard against the impossible. Equipoise runs
    its process three times into one record, so the third round's sentence names
    the first two rounds' picks as well — and a phased-out permanent is treated
    as though it does not exist (CR 702.26b), which is exactly a permanent this
    step cannot phase out. Reading the record without the check would push the
    same permanent onto its controller's phased-out pile twice and phase it back
    in as two objects.
    """
    from ._targets import recorded_permanent_ids

    left = 0
    for permanent_id in recorded_permanent_ids(
        context, instruction.payload.get("permanents_from")
    ):
        perm = game.permanent_by_id(permanent_id)
        if perm is None or not game.is_on_battlefield(perm):
            continue
        game.phase_out_permanent(perm)
        left += 1
    game.log.append(f"{context.card.name}: {left} permanent(s) phased out")
    return True, "resolved"


@effect_handler("forbid_phase_out")
def forbid_phase_out(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until your next upkeep, target permanent **can't phase out**."
    (Spatial Binding, CR 702.26.)

    The restriction beside ``phase_out_target``'s action, recorded on the chosen
    permanent by ``engine/phasing_locks.py`` — which is where the sweep that
    ends it is named, and which both phase-out paths ask.

    "**Your** next upkeep" is the ability's controller (CR 109.5), not the
    permanent's, so the seat is frozen here and compared at the sweep. Reading
    it off the target would let a Binding on an opponent's permanent expire on
    the wrong turn.

    The printed noun phrase is re-tested at resolution through the same
    ``subject_matches`` the picker enumerated with, which is Reality Ripple's
    lesson in this same file: a handler taking the resolver's default predicate
    declines targets the engine already accepted.
    """
    from ..phasing_locks import forbid_phase_out as record_lock
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(context.caster) if context.caster in game.players else None
    target_perm = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent,
        ),
    )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target")
        return True, "resolved"
    record_lock(
        target_perm,
        duration=str(instruction.payload.get("duration") or "end_of_turn"),
        seat=observer,
    )
    game.log.append(
        f"{target_perm.card.name} can't phase out ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("phase_out_self")
def phase_out_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature phases out." (Mist Dragon, Crystal Golem, Vaporous Djinn,
    Warping Wurm, Frenetic Efreet.)

    The ability's own source, which is a different question from a target: the
    sentence names nothing to pick, so there is nothing to describe and nothing
    to re-check at resolution. A source that has already left the battlefield
    phases out nothing, which is what ``phase_out_permanent`` reports by
    returning False (CR 702.26 acts on a permanent, and there is none).
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: not on the battlefield to phase out")
        return True, "resolved"
    game.phase_out_permanent(source)
    return True, "resolved"


@effect_handler("phase_out_bound_permanent")
def phase_out_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a creature you control attacks, **it phases out at end of
    combat**." (Teferi's Veil, CR 511.1 / CR 603.7.)

    The object is the one the ability that created this delay bound
    (CR 603.7c), carried by id in the trigger's context — the attacker the
    Veil's own trigger fired on, which by end of combat may have been removed
    from combat, blocked, or renumbered by something else leaving (CR 400.7).
    So it is an id, never an index and never a board search.

    ``phase_out_self``'s twin for a permanent that is *not* the source: the
    Veil is an enchantment and stays where it is, and its own source would be
    an illegal reading of "it" that phases out the enchantment instead of the
    creature.

    **No re-check of the printed noun**, for ``destroy_event_subject``'s stated
    reason one file over: the pronoun re-states the trigger's own noun phrase,
    the condition already decided this creature is what the ability is about,
    and asking again at end of combat would let a creature whose controller
    changed mid-combat escape a phase-out CR 603.7c has already aimed at it.

    A permanent already gone phases out nothing, which is CR 608.2b doing as
    much as it can rather than a failure.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    game.phase_out_permanent(victim)
    return True, "resolved"


@effect_handler("forbid_source_phase_out")
def forbid_source_phase_out(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{U}: Until your next upkeep, **this creature** can't phase out."
    (Ertai's Familiar, CR 702.26.)

    ``forbid_phase_out``'s twin on the ability's own source, and its own kind
    for the reason ``phase_out_self`` is one beside ``phase_out_target``: the
    sentence names nothing to pick, so routing it through the targeted kind
    would raise a picker for a choice CR 602.2b says was never offered and then
    lock whatever the resolution happened to be holding.

    The record and the sweep that ends it are ``engine/phasing_locks.py``'s, so
    a printed window with no sweep behind it refuses at lowering rather than
    being written and never lifted. "**Your** next upkeep" is the ability's
    controller (CR 109.5) — here the same seat as the creature's, but frozen
    from the ability rather than read off the permanent, because that is the
    seat the words name.
    """
    from ..phasing_locks import forbid_phase_out as record_lock

    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: not on the battlefield to lock")
        return True, "resolved"
    seat = (
        game.players.index(context.caster)
        if context.caster in game.players else None
    )
    record_lock(
        source,
        duration=str(instruction.payload.get("duration") or "your_next_upkeep"),
        seat=seat,
    )
    game.log.append(f"{source.card.name} can't phase out ({context.card.name})")
    return True, "resolved"


@effect_handler("phase_in_and_out_matching")
def phase_in_and_out_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Simultaneously, all phased-out creatures phase in and all creatures with
    phasing phase out." (Time and Tide, CR 702.26.)

    **Both sets are read before either is applied**, which is the whole of what
    the printed adverb buys: a creature with phasing that phases in here must
    not be swept straight back out, and one that phases out must not be counted
    as arriving. That is the same simultaneity ``Game.resolve_phasing_for``
    implements for the untap-step event (CR 702.26a), and it is written the same
    way — read, then apply — rather than with a per-permanent flag to keep in
    step.

    The incoming half reads each seat's ``phased_out`` holding list, because a
    phased-out permanent is on no battlefield (CR 702.26b) and no scan of one
    can find it. The outgoing half reads the board through the same
    ``subject_matches`` every other sweep uses, with the caster as observer
    (CR 109.5).

    A phase-out lock (Spatial Binding) is not consulted here: ``phase_out_permanent``
    asks it at the one transition every phase-out passes through, which is
    exactly why that check lives there and not at each call site.
    """
    from ..subject_filters import subject_matches

    payload = instruction.payload
    returning_filter = payload.get("returning") or {}
    leaving_filter = payload.get("leaving") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )

    def _matches(perm, described) -> bool:
        return subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        )

    # Read both sets first — see the docstring.
    returning: list[tuple[int, list]] = []
    for seat, player in enumerate(game.players):
        chosen = [p for p in player.phased_out if _matches(p, returning_filter)]
        if chosen:
            returning.append((seat, chosen))
    leaving = [
        perm for perm in game.all_permanents()
        if _matches(perm, leaving_filter)
    ]

    for seat, permanents in returning:
        game.phase_in_for(seat, permanents=permanents)
    for perm in leaving:
        game.phase_out_permanent(perm)
    game.log.append(
        f"{context.card.name}: "
        f"{sum(len(p) for _, p in returning)} phased in, {len(leaving)} phased out"
    )
    return True, "resolved"


@effect_handler("phase_out_enchanted")
def phase_out_enchanted(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{U}{U}: Enchanted creature phases out." (Vanishing, CR 702.26.)

    The Aura's own attachment, read through ``attached_host`` the way every
    other enchanted-subject handler reads it — no target is chosen, so there
    is nothing to describe and nothing to re-check at resolution.

    **The Aura goes with it and comes back with it.** That is not this
    handler's doing: ``phase_out_permanent`` drags a host's attached Auras
    along (CR 702.26d), so Vanishing phases out beside the creature it
    enchants and phases in attached to the same object — which is why phasing
    an enchanted creature is not the same as removing it, and why CR 702.26j
    is right that no attach or unattach trigger fires either way.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    # Last-known information (CR 608.2h): Vanishing destroyed in response to
    # its own activation still phases out the creature it was on — the ability
    # exists independently of its source (CR 113.7a).
    from ._targets import attached_host

    host = attached_host(game, source)
    if host is None:
        game.log.append(f"{context.card.name}: nothing enchanted to phase out")
        return True, "resolved"
    game.phase_out_permanent(host)
    return True, "resolved"


@effect_handler("phase_out_block_pair")
def phase_out_block_pair(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature and **that creature** phase out." (Dream Fighter.)

    The other half of the block CR 509.3a-d announced. Read through
    ``block_pair_permanents``, the one function that knows how the two fire
    sites bind it — the becomes-blocked half puts the creature in the stack
    item's target, the blocks half targets the *blocker* (so a self-affecting
    trigger can find itself) and carries the pair in ``blocked_permanent_ids``.
    Reading the target on the blocks half would phase out this creature twice
    and its opponent not at all.

    The source's own half of the sentence is a separate ``phase_out_self``
    beside this one, because the union lowers to one statement per phrase.
    CR 702.26a's simultaneity is not at stake: a one-shot phase-out is not the
    keyword's alternation, and the pair was frozen by the trigger before either
    permanent moved.
    """
    from ._targets import block_pair_permanents

    victims = [
        perm for perm in block_pair_permanents(game, context)
        if game.is_on_battlefield(perm)
    ]
    if not victims:
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    for perm in victims:
        game.phase_out_permanent(perm)
    return True, "resolved"


@effect_handler("phase_out_matching")
def phase_out_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"All lands you control phase out." (Taniwha.)

    A sweep over the printed noun phrase, asked through ``subject_matches`` with
    the ability's controller as observer (CR 109.5) so "you control" means the
    same seat here as it does in the picker. The set is fixed before anything
    moves: phasing an Aura out drags its host's other attachments with it
    (CR 702.26g), so a sweep that re-read the board between permanents would
    trip over what its own earlier steps removed.
    """
    from ..subject_filters import subject_matches

    described = instruction.payload.get("filter") or {}
    observer = game.players.index(context.caster)
    victims = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent,
        )
    ]
    for perm in victims:
        if game.is_on_battlefield(perm):
            game.phase_out_permanent(perm)
    game.log.append(f"{context.card.name}: {len(victims)} permanent(s) phased out")
    return True, "resolved"


@effect_handler("phase_out_opponent_creatures")
def phase_out_opponent_creatures(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each creature target opponent controls phases out. Until the end of
    your next turn, they can't phase in." (Teferi, Timeless Voyager's −8.)

    The countdown counts the caster's turn ends: cast on the caster's own turn
    the block survives this turn's end and the caster's next turn's end, which
    is what "the end of your next turn" spans."""
    caster_index = game.players.index(context.caster)
    target = context.target
    if target is None or target is context.caster:
        target = next(
            (game.players[i] for i in game.opponents_of(caster_index)), None
        )
    if target is None:
        return True, "resolved"
    blocked = bool(instruction.payload.get("cant_phase_in_until_your_next_turn"))
    ends = 2 if game.active_player_index == caster_index else 1
    victims = [perm for perm in game.controlled_by(game.players.index(target)) if perm.is_creature]
    for perm in victims:
        if blocked:
            perm.metadata["phase_in_blocked"] = {
                "seat": caster_index,
                "turn_ends_remaining": ends,
            }
        game.phase_out_permanent(perm)
    game.log.append(
        f"{context.card.name}: {len(victims)} creature(s) phased out"
    )
    return True, "resolved"

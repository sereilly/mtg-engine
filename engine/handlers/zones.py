"""Where an object goes when a sentence **puts** it there (CR 400).

The handler side of ``engine/grammar/lowering/zones.py``'s question — which zone
does this object end up in — for the moves that are none of a draw, a discard,
a mill, a search, a reveal, an exile, a return or a shuffle: a permanent put on
top of its owner's library (a target, a sweep, or the source itself), graveyard
cards put on the top or the bottom of a library, and the source put into a
graveyard.

**This was one module of 11,769 lines** — every handler that moved a card
between zones — until the 2,000-line cap's split round cut it along the families
the grammar had already drawn, mostly under their names: ``cards``,
``discards``, ``hand``, ``reveal``, ``naming``, ``search``, ``library``,
``shuffles``, ``returns``, ``reanimation``, ``exile``, ``linked_exile``,
``permissions``, ``ownership`` and ``phasing``. ``_resolve_graveyard_slots``,
which this module and four of those read, went to the ``_targets`` floor beside
its battlefield twin, ``resolve_target_slots``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..exiled_records import source_object
from ..models import Permanent
from ._filters import graveyard_card_matches
from ._targets import (_resolve_graveyard_slots, frozen_that_player_seat,
                       resolve_target_permanent, resolve_target_permanents)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("put_graveyard_cards_on_library_top")
def put_graveyard_cards_on_library_top(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Drafna's Restoration: "Put any number of target artifact cards from
    target player's graveyard on top of their library in any order."

    Two targets on one line — a player, and the cards in their graveyard — so
    the seat comes from the spell's chosen target and the slots index *that*
    player's graveyard rather than the caster's. That is the whole difference
    from the returns above, and it is why the cards are resolved through
    :func:`_resolve_graveyard_slots` with the target player passed in.

    **The order they are laid down in is the order the targets were named
    in** — CR 601.2c chooses the targets in sequence, so the first card named
    ends up on top — **and then the owner of the library is asked** (CR 401.4:
    "the owner of those cards may arrange them in any order"). The naming
    order was the whole of it, on the ground that nothing else on the wire
    carried an ordering. Two things that reading could not say: the arranger
    is the cards' *owner*, who for "a player's graveyard" (Lodestone Bauble)
    need not be the player who named them; and a player naming three cards in
    a picker was never told the order of the clicks was the order of their
    next three draws. ``Game.offer_library_top_order`` asks an interactive
    owner; every other seat keeps the naming order.
    """
    # Whose graveyard, said by the lowering rather than inferred here. "Your
    # graveyard … your library" (Reinforcements) names the ability's controller
    # and chooses no player at all, so reading `context.target` for it would
    # index the *opponent's* graveyard with slots picked out of the caster's —
    # the wrong pile, silently, with the right number of cards moved.
    if instruction.payload.get("graveyard_owner") == "you":
        victim = context.caster
    elif context.target in game.players:
        victim = context.target
    else:
        game.log.append(f"{context.card.name}: no player chosen")
        return True, "resolved"

    def _eligible(card) -> bool:
        # The picker's predicate, not a third spelling of it — the arrangement
        # `returns.return_creature_from_graveyard_to_hand` already
        # makes, and for its reason: the payload and the spec carry the same key
        # names because one is derived from the other, so there is one answer to
        # "may this card be chosen?". This arm read `card_type in type_line`,
        # which is the same answer for the one key it knew and no answer at all
        # for "any card" (Misinformation) or a supertype (Lodestone Bauble).
        return graveyard_card_matches(instruction.payload, card)

    # "Any number" prints no maximum, so the cap is the pile itself; "up to
    # three" prints one, and the description the lowering built carries it.
    described = instruction.payload.get("targets") or {}
    limit = (
        len(victim.graveyard) if described.get("unbounded")
        else min(int(described.get("count") or 1), len(victim.graveyard))
    )
    picked = _resolve_graveyard_slots(victim, context, limit, _eligible)
    if not picked:
        game.log.append(f"{context.card.name}: no card moved out of the graveyard")
        return True, "resolved"
    # Last named first, so the first card the controller chose ends up on top.
    landed = sum(
        1 for card in reversed(picked)
        if game.put_card_into_library(victim, card, position="top")
    )
    game.log.append(
        f"{context.card.name} put {len(picked)} card(s) on top of {victim.name}'s library"
    )
    # CR 401.4: the order is the library owner's. Counted off what landed —
    # a card the funnel diverted (a commander, CR 903.9b) is not in the pile.
    game.offer_library_top_order(victim, landed)
    return True, "resolved"


@effect_handler("put_target_on_library_top")
def put_target_on_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put target creature on top of its owner's library." (Teferi, Timeless
    Voyager's −3); "target artifact or enchantment" (Disempower); "target land"
    (Fallow Earth). A zone change, not a destruction: no dies-trigger fires and
    regeneration cannot save it. The card goes to its *owner's* library
    (CR 400.3), whoever controlled the permanent.

    **The type comes from the printed noun phrase**, asked through the same
    ``subject_matches`` the picker enumerated with. It was pinned to
    ``is_creature`` here, which is Reality Ripple's defect one file over: a
    spell whose target the engine had already accepted, declined at resolution
    with "no valid creature target" and resolved having done nothing.
    """
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(context.caster)
    targets_desc = instruction.payload.get("targets") or {}
    if isinstance(targets_desc, dict) and targets_desc.get("count") not in (None, 1):
        # "Put **two target lands** on top of their owners' libraries." (Plow
        # Under.) A chosen list, resolved strictly per slot the way
        # ``destroy_target_permanent``'s list branch resolves one: a slot whose
        # permanent has left is dropped (CR 608.2b) rather than slid onto
        # another, and the filter is re-asked because a land that stopped being
        # one is no longer what the caster chose.
        #
        # ``bottom_instead_colors`` is not read here and cannot arrive: the
        # lowering refuses the rider on this shape, because "if **that**
        # creature is red" asks a colour of one object and this branch holds
        # several.
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, described, observer=observer,
                source=context.source_permanent,
            ),
        )
        moved: list[str] = []
        for perm in chosen:
            if not game.is_on_battlefield(perm):
                continue
            owner_idx = game.owner_index_of(perm)
            owner = (
                game.players[owner_idx] if owner_idx is not None else context.caster
            )
            game.remove_from_battlefield(perm)
            game._remove_aura_effects(perm)
            game.put_card_into_library(
                owner, perm.card, "top", from_battlefield=perm
            )
            moved.append(perm.card.name)
        game.log.append(
            f"{context.card.name} put {', '.join(moved)} on top of their "
            "owners' libraries"
            if moved else f"{context.card.name}: no valid target"
        )
        return True, "resolved"
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
    owner_idx = game.owner_index_of(target_perm)
    owner = game.players[owner_idx] if owner_idx is not None else context.caster
    # "If that creature is **red**, you may put it on the bottom of its owner's
    # library **instead**." (Ether Well.) One move with two possible ends, so
    # the colour is asked *before* anything moves and the prompt performs the
    # move — putting it on top and then moving it would be two zone changes
    # where the card describes one. The colour is read through layer 5
    # (``effective_colors``), not off the printed card: a creature a Painter's
    # Servant has made red is red (CR 613), and the printed line is not.
    colors = tuple(instruction.payload.get("bottom_instead_colors") or ())
    if colors and any(
        color in target_perm.effective_colors for color in colors
    ):
        game.arm_library_end_choice(
            game.players.index(context.caster), target_perm, owner_idx
            if owner_idx is not None else game.players.index(context.caster),
            context,
        )
        return True, "resolved"
    # "…on **the bottom** of its owner's library." (Mercenary Informer.) The
    # same move to the library's other end; the lowering emits it on this
    # single-target shape only.
    end = "bottom" if instruction.payload.get("library_end") == "bottom" else "top"
    game.remove_from_battlefield(target_perm)
    game._remove_aura_effects(target_perm)
    game.put_card_into_library(
        owner, target_perm.card, end, from_battlefield=target_perm
    )
    where = "on top of" if end == "top" else "on the bottom of"
    game.log.append(
        f"{context.card.name}: {target_perm.card.name} put {where} {owner.name}'s library"
    )
    return True, "resolved"


@effect_handler("put_all_matching_on_library_top")
def put_all_matching_on_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put all enchantments on top of their owners' libraries." (Harmonic
    Convergence.)

    The sweep twin of ``put_target_on_library_top``: no pick, every permanent
    the printed noun phrase names, each onto **its own owner's** library
    (CR 400.3) whoever controlled it. A zone change rather than a destruction,
    so no dies trigger fires and regeneration cannot save one.

    The matched list is taken **before** anything moves, for
    ``returns.return_all_matching``'s reason: a permanent leaving detaches
    its Auras, so a sweep that re-read the board between removals would stop
    matching objects it had already named — and an Aura is exactly what this
    card's noun phrase names most of.

    ``subject_matches`` with CR 109.5's observer, because "you control" and the
    rest of the seat comparisons are answered there and nowhere else; the
    lowering admitted the line only because that is true.
    """
    from ..subject_filters import subject_matches

    swept = instruction.payload.get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    that_player = frozen_that_player_seat(game, context)
    matched = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, swept, observer=observer, source=context.source_permanent,
            that_player=that_player,
        )
    ]
    tucked: list[str] = []
    for perm in matched:
        if not game.is_on_battlefield(perm):
            # It went with something else this same sweep removed — a token
            # ceasing to exist, an Aura falling off its host.
            continue
        owner_idx = game.owner_index_of(perm)
        owner = game.players[owner_idx] if owner_idx is not None else context.caster
        game.remove_from_battlefield(perm)
        game._remove_aura_effects(perm)
        game.put_card_into_library(
            owner, perm.card, "top", from_battlefield=perm
        )
        tucked.append(perm.card.name)
    game.log.append(
        f"{context.card.name} put {', '.join(tucked)} on top of their owners' libraries"
        if tucked else f"{context.card.name}: nothing to put on a library"
    )
    return True, "resolved"


@effect_handler("put_source_card_on_library_top")
def put_source_card_on_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put this creature on top of its owner's library." (Thalakos Mistfolk's
    ``{U}`` ability.) "When this creature dies, you may put it on top of its
    owner's library." (Avenging Angel.)

    The ability's own source, printed with **no source zone** — so this reaches
    whichever zone the object is actually in (CR 608.2), exactly as
    ``returns.return_source_card_to_owners_hand`` does and for its reason.
    Mistfolk's is still on the battlefield when the ability resolves; the
    Angel's is a card in its owner's graveyard, because a dies trigger resolves
    after the creature has already been put there (CR 700.4, CR 603.6d), and a
    handler that looked only at the battlefield would silently do nothing for
    the card that made this shape worth having.

    By identity across every graveyard rather than the resolving seat's:
    CR 404.1 puts a card in its *owner's*, and a creature its controller did not
    own dies into the other player's pile.
    """
    card = context.card
    source = context.source_permanent
    if source is not None and game.is_on_battlefield(source):
        owner_idx = game.owner_index_of(source)
        owner = game.players[owner_idx] if owner_idx is not None else context.caster
        game.remove_from_battlefield(source)
        game._remove_aura_effects(source)
        game.put_card_into_library(owner, card, "top", from_battlefield=source)
        game.log.append(
            f"{card.name} put on top of {owner.name}'s library"
        )
        return True, "resolved"
    for player in game.players:
        for index, held in enumerate(player.graveyard):
            if held is card:
                player.graveyard.pop(index)
                game.put_card_into_library(player, card, "top")
                game.log.append(
                    f"{card.name} put on top of {player.name}'s library"
                )
                return True, "resolved"
    game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


@effect_handler("put_graveyard_card_on_library_bottom")
def put_graveyard_card_on_library_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put target card from your graveyard on the bottom of your library."
    (Epitaph Golem.) Honours the chosen graveyard index, else takes the first
    card — the stale-choice fallback every other graveyard reader uses."""
    caster = context.caster
    if not caster.graveyard:
        game.log.append(f"{context.card.name}: no card in the graveyard to bottom")
        return True, "resolved"
    idx = context.target_permanent_index
    if not (isinstance(idx, int) and 0 <= idx < len(caster.graveyard)):
        idx = 0
    # "Put target **Rebel** card …" (Lin Sivvi, Defiant Hero). A narrowed
    # payload is re-checked against the card in the chosen slot through the one
    # predicate the picker and the activation gate asked, so neither a stale
    # index nor the fallback above can bottom a card the sentence never named
    # (CR 608.2b: an illegal target is not acted on). The empty payload is
    # Epitaph Golem's "target card", which any card answers.
    if instruction.payload and not graveyard_card_matches(
        instruction.payload, caster.graveyard[idx]
    ):
        game.log.append(
            f"{context.card.name}: the chosen card is no longer a legal target"
        )
        return True, "resolved"
    card = caster.graveyard.pop(idx)
    game.put_card_into_library(caster, card)
    game.log.append(f"{context.card.name}: {card.name} put on the bottom of {caster.name}'s library")
    return True, "resolved"


#: The destination a graveyard pick moves its cards to when it is not exile:
#: the bottom of the pile owner's library. Rides the pick's payload and its
#: prompt (``Game.arm_graveyard_exile_pick``), so the client can say where the
#: cards are going and the one answer path knows where to put them.
GRAVEYARD_PICK_TO_LIBRARY_BOTTOM = "library_bottom"


@effect_handler("put_chosen_graveyard_cards_on_library_bottom")
def put_chosen_graveyard_cards_on_library_bottom(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"…sacrifice this creature unless you **put two cards from your
    graveyard on the bottom of your library**." (Gurzigost; Anurid Scavenger
    with one.)

    The targeted bottoming above with nothing announced: the seat picks the
    cards as this resolves, out of its own pile, through the prompt the
    graveyard exile's pick already is — the payload says which cards may be
    picked and how many, and ``destination`` says where they go. With no
    prompt to ask (a headless or AI seat), the pick's stated default is taken
    where it is armed. The offer in front of this is what refuses a pile too
    small to pay (``offers._action_is_takeable``), so a seat reaching
    here holds enough.
    """
    seat = game.players.index(context.caster)
    game.arm_graveyard_exile_pick(
        seat, seat,
        {**instruction.payload, "destination": GRAVEYARD_PICK_TO_LIBRARY_BOTTOM},
        context,
    )
    return True, "resolved"


@effect_handler("put_top_of_graveyard_on_library_bottom")
def put_top_of_graveyard_on_library_bottom(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put the top card of your graveyard on the bottom of your library."
    (Soldevi Digger.)

    The *top* of a graveyard is the card most recently put there (CR 404.1: a
    graveyard is an ordered pile), which in this engine is the last element —
    every path into a graveyard appends. So it is ``pop()``, not the ``pop(0)``
    its targeted neighbour above falls back to: that one is a stale-choice
    default for a card somebody chose, and this one is the printed position.

    An empty graveyard moves nothing. CR 608.2's "as much as possible" — the
    ability still resolves, and the cost was paid at activation either way.
    """
    caster = context.caster
    if not caster.graveyard:
        game.log.append(f"{context.card.name}: no card in the graveyard to bottom")
        return True, "resolved"
    card = caster.graveyard.pop()
    game.put_card_into_library(caster, card)
    game.log.append(
        f"{context.card.name}: {card.name} put on the bottom of "
        f"{caster.name}'s library"
    )
    return True, "resolved"


@effect_handler("put_self_into_zone")
def put_self_into_zone(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put it into your graveyard." — the ability's own source changes zones.

    The source is a permanent or a card in **exile** (All Hallow's Eve, whose
    upkeep trigger finally bins the exiled card once its last scream counter
    has come off), and ``exiled_records.source_object`` is the one reader that
    answers for both.

    The destination is payload, and today the only one the grammar admits is a
    graveyard — see ``lowering/zones._lower_put_source_into_zone``, which
    refuses the rest by name rather than letting a card report itself supported
    and land somewhere else.

    CR 400.3 sends a card to **its owner's** graveyard whatever the effect
    printed, which is why "your graveyard" and "its owner's graveyard" lower to
    the same instruction and the owner lookup happens here.
    """
    zone = str(instruction.payload.get("zone", "graveyard"))
    if zone != "graveyard":  # pragma: no cover - the lowering refuses the rest
        return False, f"no handler puts a source into a {zone}"
    source = source_object(context)
    if source is None:
        game.log.append(f"{context.card.name}: nothing left to move")
        return True, "resolved"
    if isinstance(source, Permanent):
        owner_index = game.owner_index_of(source)
        owner = game.players[owner_index] if owner_index is not None else context.caster
        if not game.is_on_battlefield(source):
            game.log.append(f"{context.card.name}: nothing left to move")
            return True, "resolved"
        game.remove_from_battlefield(source)
        game._permanent_to_graveyard(owner, source)
        return True, "resolved"
    # An exile record. The card leaves exile and the register forgets it, both
    # in the departure seam — and *this* record by name rather than the one the
    # seam would derive, because two copies of the card produce two
    # equal-looking entries and the trigger resolving here fires for exactly
    # one of them. Retiring the other would strand this copy's counters on a
    # card that is no longer there.
    owner = game.players[source.owner_index]
    game.take_card_from_exile(source.owner_index, source.card, record=source)
    game.put_card_into_graveyard(owner, source.card)
    game.log.append(f"{source.card.name} was put into {owner.name}'s graveyard from exile")
    return True, "resolved"

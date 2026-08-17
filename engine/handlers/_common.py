"""Shared helpers for effect handlers.

The leading underscore keeps this module out of the handler-registry import
pattern in ``engine/handlers/__init__.py`` — it registers no handlers, it only
hosts logic the registered handlers share.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable, Sequence

from ..oracle_types import X_FROM_COUNT

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
from ..models import Permanent, PlayerState
from ..search_filters import name_key


def resolve_amount(raw: object, x_value: int | None) -> int:
    """Numeric value of a parsed amount payload; ``"x"`` resolves to the cast's
    X (never negative)."""
    return max(0, x_value or 0) if raw == "x" else int(raw)




def count_from_payload(game: "Game", context: "OracleExecutionContext", spec: dict) -> int:
    """Evaluate an ``x_from_count`` spec at *resolution*.

    ``owner`` names whose zone is read — "you" is the effect's controller,
    "target" the player it points at — which is the only thing a resolution
    knows that a continuous recompute does not. Everything else is
    :func:`evaluate_count`.
    """
    owner = context.caster if spec.get("owner", "you") == "you" else (context.target or context.caster)
    return evaluate_count(game, owner, spec)


def evaluate_count(game: "Game", owner: "PlayerState", spec: dict) -> int:
    """How much the amount a card *computes* currently is, for a named owner.

    CR 608.2: a where-clause is not announced with the spell, it is counted when
    the effect happens — and CR 604.3's characteristic-defining version is
    recounted continuously, which is the same question asked at a different
    moment. **One evaluator for both**, because the alternative is what this
    replaced: the pump handler carried its own graveyard counter under its own
    spelling of the spec (``card_types`` where every other reader says
    ``filter``), so "the number of creature cards in your graveyard" meant two
    things depending on which sentence it was printed in.

    ``filter`` is the ordinary object filter every other consumer agrees on, and
    ``aggregate`` says what to do with the objects it names — count them, or
    take the greatest power among them (Carrion Grub). An aggregate this does
    not know returns 0 rather than guessing, and the lowerings refuse it long
    before that.
    """
    # A count of a *history* rather than of a zone: the creatures counted are
    # exactly the ones no longer on the battlefield, so there is nothing to
    # scan. Per seat, because the game-wide tally cannot answer "under your
    # control" (round 14).
    history = spec.get("history")
    if history == "creatures_died_under_your_control":
        return int(getattr(owner, "creatures_died_under_your_control_this_turn", 0))
    if history is not None:
        return 0
    filt = dict(spec.get("filter") or {})
    aggregate = spec.get("aggregate", "count")
    zone = spec.get("zone", "battlefield")
    if zone == "battlefield":
        seat = game.players.index(owner)
        matched = [
            perm for perm in game.controlled_by(seat)
            if permanent_matches_filter(perm, filt)
        ]
        if aggregate == "greatest_power":
            return max((perm.effective_power for perm in matched), default=0)
        return len(matched)
    cards = getattr(owner, zone, None)
    if cards is None:
        return 0
    matched_cards = [card for card in cards if _card_matches_filter(card, filt)]
    if aggregate == "greatest_power":
        # The *printed* power, because a card outside the battlefield has no
        # computed characteristics at all (CR 613 applies to permanents). A
        # creature card with a characteristic-defining power has none here
        # either, which is CR 604.3's own answer: its P/T is 0 in every zone but
        # the battlefield.
        return max((_printed_power(card) for card in matched_cards), default=0)
    return len(matched_cards)


def _printed_power(card) -> int:
    try:
        return int(card.power)
    except (TypeError, ValueError):
        return 0


def _card_matches_filter(card, filt: dict) -> bool:
    """Whether a *card* — not a permanent — answers a filter payload.

    A card in a zone has no computed characteristics, so the shared matcher
    (which asks ``has_type`` of a battlefield object) cannot answer here. Only
    the printed type union and the card's own name are testable, which is what
    every zone count in this pool asks for; the lowerings refuse anything else
    rather than counting it as if it were not there.
    """
    wanted = filt.get("type_filter")
    wanted_types = tuple(wanted) if isinstance(wanted, (list, tuple)) else ((wanted,) if wanted else ())
    if wanted_types and card.primary_type not in wanted_types:
        return False
    named = filt.get("named")
    # Through `name_key`, so the parser's rendering of a legendary name
    # ("chandra , flame 's catalyst") and Oracle's spelling of it compare equal —
    # the same reduction a search's named restriction already uses.
    return not named or name_key(card.name) == name_key(str(named))


def flip_coin(win_probability: float = 0.5) -> bool:
    """Flip a coin, returning True on a win (CR 705). Draws from the module-level
    RNG that ``run_ai_simulation`` seeds, so a given seed replays identically."""
    return random.random() < win_probability


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


def apply_temp_pt_boost(perm: Permanent, power: int = 0, toughness: int = 0) -> None:
    """Apply an until-end-of-turn P/T change and track it so the cleanup step
    can remove it. Thin wrapper over the single P/T write API in engine/pt.py."""
    from ..pt import add_pt_modifier

    add_pt_modifier(perm, power, toughness, until_eot=True)


def apply_damage_to_creature(
    game: Game,
    perm: Permanent,
    amount: int,
    source,
    log_message: Callable[[int], str] | None = None,
    then: Callable[[int], None] | None = None,
    asks: bool = False,
) -> int:
    """Mark non-combat damage on a single creature and fire its "dealt damage"
    triggers.

    Destruction is not this function's job: lethal damage is a state-based
    action (CR 704.5g, regeneration replacing it per CR 701.19), checked in
    ``check_state_based_actions``. Handlers used to have to call the sweep by
    hand at nine separate sites, and any new damage effect that forgot left a
    lethally damaged creature alive.

    ``log_message`` receives the damage actually dealt, and ``then`` is anything
    further the caller would do with it. Both run *inside* the damage event, not
    after it: the event can stop to ask the affected player which effect applies
    first (CR 616.1e), and while it waits there is nothing to report. Returns
    the amount dealt, which is 0 while suspended."""

    def finish(dealt: int) -> None:
        if log_message is not None:
            game.log.append(log_message(dealt))
        if dealt > 0:
            # Not gated on survival. "Whenever this creature is dealt damage"
            # triggers on the damage (CR 603.2), and whether the creature dies
            # is a state-based action that has not run yet — so the guard that
            # stood here (`damage_marked < effective_toughness`) was reading a
            # rule that does not exist. Harmless for Fungusaur, whose counter on
            # a dying creature does nothing anyway; wrong for Brash Taunter,
            # which is *indestructible* and reflects every point it takes.
            game._fire_dealt_damage_triggers(perm, dealt)
        if then is not None:
            then(dealt)

    return game._mark_damage_on_permanent(perm, amount, source=source, then=finish, asks=asks)


def permanent_effective_colors(perm: Permanent) -> set[str]:
    """The color symbols a permanent currently has.

    Computed through the layer system, so a colour override (the laces) is an
    ordinary layer-5 continuous effect rather than a step in a precedence chain
    written out by hand — and a copy's colours arrive in layer 1 before it, as
    the copiable value CR 707.2a says they are.
    """
    return perm.effective_colors


def graveyard_card_matches(spec: dict, card) -> bool:
    """Whether *card* is a legal choice for a graveyard target described by
    *spec* — or by an instruction payload, which carries the same key names
    because the spec is derived from it.

    ``permanent_matches_filter``'s sibling one zone over, and here for the same
    reason: **one predicate, three readers.** The picker that offers the card,
    the cast-time re-check that admits it (idiom #9) and the handler that takes
    it were three copies, and they disagreed. The re-check asked only "is it a
    creature card?", so Reconstruction — "Return target **artifact** card from
    your graveyard to your hand" — refused every artifact its own picker
    offered, and with no creature in the pile could not be cast at all.

    The narrowed type is containment in the printed type line rather than
    ``primary_type``, because CR 205.2 makes an Ornithopter an artifact card
    *and* a creature card. The bare case keeps ``primary_type``, which is what
    the reanimation handlers ask of the card they put onto the battlefield.
    """
    card_types = tuple(spec.get("card_types") or ())
    if card_types and card.primary_type not in card_types:
        return False
    color = spec.get("graveyard_color_filter")
    if color and color not in card.colors:
        return False
    if card_types or spec.get("any_card"):
        return True
    card_type = spec.get("card_type")
    if card_type is not None:
        return card_type in card.type_line.lower()
    return card.primary_type == "creature"


def permanent_matches_filter(perm: Permanent, payload: dict) -> bool:
    """Whether *perm* satisfies a target-filter payload (the key vocabulary
    produced by ``engine.grammar.ast.ObjectFilter.to_payload``:
    type/subtype/color filters, tapped_only, exclusions).

    Uses has_type/is_creature/effective colors so copies keep all their types
    (a Copy Artifact copy is an Artifact Enchantment), animated lands count as
    creatures, and color overrides are honored. Shared by destroy-target
    resolution, cast validation, and the legality enumerator so they can never
    disagree about what a filter means.
    """
    type_filter = payload.get("type_filter")
    subtype_filter = payload.get("subtype_filter")
    color_filter = payload.get("color_filter")
    tapped_only = payload.get("tapped_only", False)
    exclude_colors = payload.get("exclude_colors") or []
    exclude_types = payload.get("exclude_types") or []

    # Pyramids: "target Aura attached to a land" — only Auras whose enchanted
    # permanent is currently a land qualify.
    if payload.get("attached_to_land"):
        attached = perm.metadata.get("attached_to")
        if attached is None or getattr(getattr(attached, "card", None), "primary_type", "") != "land":
            return False

    def _has_type(name: str) -> bool:
        # is_creature (not the printed line) so animated lands count.
        return perm.is_creature if name == "creature" else perm.has_type(name)

    if type_filter:
        if type_filter == "artifact_or_enchantment":
            if not (perm.has_type("artifact") or perm.has_type("enchantment")):
                return False
        elif isinstance(type_filter, (list, tuple)):
            # A type union ("target artifact, creature, or land") — any match
            # qualifies.
            if not any(_has_type(name) for name in type_filter):
                return False
        elif not _has_type(type_filter):
            return False
    if subtype_filter:
        # A single subtype string, or several OR'd alternatives ("Djinn or
        # Efreet") as a list — any one matching is enough.
        #
        # has_type, not the printed type line: a land turned into a Swamp by
        # Magical Hack / Phantasmal Terrain / Evil Presence IS a Swamp under CR
        # 613 layer 4, and this function promises destroy-target resolution,
        # cast validation and the legality enumerator can never disagree about
        # what a filter means. Reading the printed line made it disagree with
        # layer 4 — the divergence is unreachable in the current pool (no card
        # here filters on a basic land subtype) but reachable the moment one
        # ships.
        subtypes = [subtype_filter] if isinstance(subtype_filter, str) else subtype_filter
        if not any(perm.has_type(s) for s in subtypes):
            return False
    if tapped_only and not perm.tapped:
        return False
    colors = permanent_effective_colors(perm)
    if color_filter and color_filter not in colors:
        return False
    if exclude_colors and any(c in colors for c in exclude_colors):
        return False
    if exclude_types and any(perm.has_type(t) for t in exclude_types):
        return False
    # "non-Spirit creature" (Roaming Ghostlight). has_type, like the positive
    # subtype test above, so a granted or layer-4 subtype excludes too.
    exclude_subtypes = payload.get("exclude_subtypes") or []
    if exclude_subtypes and any(perm.has_type(s) for s in exclude_subtypes):
        return False
    # "with mana value 3 or less" (Eliminate). CR 202.3: a permanent's mana
    # value comes from its mana cost — the ingested cmc; a token's is 0.
    if not _comparison_holds(payload.get("mana_value"),
                             int(getattr(perm.effective_card, "cmc", 0) or 0)):
        return False
    # "with power 4 or greater" (Turret Ogre's intervening-if): the
    # layer-computed stats, so a pumped 2/2 qualifies while it is pumped.
    if not _comparison_holds(payload.get("power"), perm.effective_power):
        return False
    if not _comparison_holds(payload.get("toughness"), perm.effective_toughness):
        return False
    # "with a +1/+1 counter on it" (Tempered Veteran). Asks the counter
    # *record*, not the P/T bonus — a Giant Growth also writes power_bonus, and
    # reading the bonus as the counter would let it qualify.
    if payload.get("with_plus1_counter") and int(perm.metadata.get("plus_counters", 0)) <= 0:
        return False
    # "nontoken permanent" (Lich). CR 111.1: not a card type, so it is its own
    # key rather than an ``exclude_types`` entry.
    if payload.get("nontoken") and perm.metadata.get("is_token", False):
        return False
    # "named <card>" — through `name_key`, so the parser's rendering of the name
    # and Oracle's spelling of it compare equal. The *effective* card, because a
    # Clone's name is the name it copied (CR 707.2).
    named = payload.get("named")
    if named and name_key(perm.effective_card.name) != name_key(str(named)):
        return False
    return True


def _comparison_holds(comparison: dict | None, actual: int) -> bool:
    """Whether *actual* satisfies a lowered ``{op, value}`` bound (absent means
    unrestricted)."""
    if not comparison:
        return True
    bound = int(comparison.get("value", 0))
    op = comparison.get("op")
    if op == "le":
        return actual <= bound
    if op == "lt":
        return actual < bound
    if op == "ge":
        return actual >= bound
    if op == "gt":
        return actual > bound
    if op == "eq":
        return actual == bound
    return False


def pick_target_permanent(
    player: PlayerState | None,
    index: int | None,
    *,
    game: Game | None = None,
    permanent_id: object = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Core "honor the chosen target, else fall back" resolution.

    0. If ``permanent_id`` still names a permanent *player* controls and it
       passes ``predicate``, that is the target. This is the stable answer: the
       id was recorded when the target was chosen (CR 601.2c) and means the same
       permanent however the battlefield has been renumbered since.
    1. Otherwise, if ``index`` is a valid index into ``player``'s battlefield and
       that permanent passes ``predicate`` (default: is a creature), return it.
    2. Otherwise scan ``fallback_players`` (default: just ``player``) for the
       first permanent passing ``predicate``. Pass ``()`` to disable fallback,
       or ``fallback_on_invalid_choice=False`` to skip the fallback only when
       the player explicitly chose an illegal index (the choice fizzles).

    Step 0 is *additive*: when the id no longer resolves — the target died, or
    changed controller — this falls through to exactly the index behaviour it
    has always had, rather than inventing a fizzle the rest of the engine is not
    yet written for. So the id can only turn a wrong answer into a right one.
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    if game is not None and isinstance(permanent_id, int) and player is not None:
        chosen = game.permanent_by_id(permanent_id)
        # Scoped to *player* on purpose: the callers pass the battlefield the
        # target was chosen from ("a creature you control", "target artifact an
        # opponent controls"), and widening that here would be a targeting
        # change wearing an identity change's clothes.
        if chosen is not None and game.controls(player, chosen) and predicate(chosen):
            return chosen
    explicit = isinstance(index, int)
    if explicit and player is not None and 0 <= index < len(player.battlefield):
        candidate = player.battlefield[index]
        if predicate(candidate):
            return candidate
    if explicit and not fallback_on_invalid_choice:
        return None
    if fallback_players is None:
        fallback_players = (player,) if player is not None else ()
    for scan in fallback_players:
        found = next((p for p in scan.battlefield if predicate(p)), None)
        if found is not None:
            return found
    return None


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
    handler signature does."""
    return pick_target_permanent(
        player if player is not None else context.target,
        _one_choice(context.target_permanent_index),
        game=game,
        permanent_id=_one_choice(context.target_permanent_id),
        predicate=predicate,
        fallback_players=fallback_players,
        fallback_on_invalid_choice=fallback_on_invalid_choice,
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

"""Damage **sweeps**: one source dealing damage to every member of a set the
game describes — each creature and each player (Time Bomb), each creature
without flying and each player (Earthquake), each creature with flying and
each player (Hurricane), each attacking creature (Sandstorm), each permanent a
printed noun phrase names (Goblin Shrine), and the creatures a flipped card
lands on (Falling Star).

Nothing is targeted and nobody picks, which is what separates these from
``damage.py``'s ``deal_damage``: every member of the set is dealt damage by the
same source, and how much is one question for the whole family
(``_sweep_amount``). The handler twin of the damage half of
``engine/grammar/lowering/_sweeps.py``.

Split out of ``damage.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..dexterity import flip_lands_on
from ..models import Permanent
from ..named_counters import counters_on
from ._amounts import resolve_amount
from ._common import apply_damage_to_creature, damage_dealer
from ._targets import defending_player_seat
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _sweep_amount(instruction: OracleInstruction, context: OracleExecutionContext) -> int:
    """How much a board sweep deals — a printed number, an announced X, the
    counters on the ability's own source, or a record an earlier step of the
    same effect wrote.

    The third is Time Bomb's ("deals damage equal to the number of time
    counters on it to each creature and each player"), and it is here rather
    than in one of the four sweep handlers because the question is the *amount*
    and not the shape of the sweep. `deal_damage` reads the same key one
    function up; a sweep that could not read it refused the whole line, which
    is what left Time Bomb's only ability doing nothing.

    The fourth is Volcanic Eruption's ("…equal to the number of Mountains put
    into a graveyard this way"): ``amount_from`` names a scratchpad key exactly
    as it does on `deal_damage`, and an absent record deals nothing rather than
    an amount the card never printed.
    """
    from_results = instruction.payload.get("amount_from")
    if from_results is not None:
        return max(0, int((context.results or {}).get(from_results, 0) or 0))
    named = instruction.payload.get("amount_from_named_counters")
    if named is not None:
        source = context.source_permanent
        return counters_on(source, str(named)) if source is not None else 0
    return resolve_amount(instruction.payload.get("amount", 0), context.x_value)


@effect_handler("deal_damage_each_creature_and_player")
def deal_damage_each_creature_and_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    amount = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(game, damage_dealer(context), amount, lambda perm: True)
    game.log.append(f"{card.name} dealt {amount} damage to each creature and each player")
    return True, "resolved"


def _has_flying(perm: Permanent) -> bool:
    """Flying from any source — printed, granted, or granted then removed.
    Reading the grant flags directly would miss whichever route a future card
    uses and would get grant-after-removal backwards (CR 613.9)."""
    return perm.has_keyword("flying")


def _mass_damage_players_and_creatures(game: Game, source, damage: int, creature_predicate) -> None:
    """Earthquake/Hurricane sweep: damage every player, then every creature
    passing the predicate, then destroy the lethally damaged as one SBA batch.

    Through ``apply_damage_to_creature``, never ``_mark_damage_on_permanent``:
    the marking is only half of a damage event, and the other half is
    ``_fire_dealt_damage_triggers``. Every sweep in this file reached for the
    lower call and so dealt damage that nothing could notice — Fungusaur took a
    point from Earthquake and grew no counter across five shipped sets. The
    per-creature triggers are correct here rather than batched: CR 603.2 puts
    one on the stack per creature dealt to, and the state-based sweep that kills
    them still runs once, after."""
    for player in game.players:
        game._deal_damage_to_player(player, damage, source=source)
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.is_creature and creature_predicate(perm):
                apply_damage_to_creature(game, perm, damage, source)


@effect_handler("earthquake_damage")
def earthquake_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(
        game, damage_dealer(context), damage, lambda perm: not _has_flying(perm)
    )
    game.log.append(f"{card.name} dealt {damage} earthquake damage to each non-flying creature and each player")
    return True, "resolved"


@effect_handler("hurricane_damage")
def hurricane_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(game, damage_dealer(context), damage, _has_flying)
    game.log.append(f"{card.name} dealt {damage} hurricane damage to each flying creature and each player")
    return True, "resolved"


@effect_handler("deal_damage_to_random_creatures")
def deal_damage_to_random_creatures(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Damage a randomly chosen handful of creatures, optionally tapping them.

    Falling Star: the creatures a flipped card "lands on" are chosen by
    ``engine.dexterity``, which is where that substitution is explained. Only
    the *count* is this card's — the payload carries it, so a card landing on a
    different number needs no code here.

    The damage goes through ``apply_damage_to_creature`` like any other
    non-combat damage, so shields, replacements, lifelink and "dealt damage"
    triggers all see it, and death is left to the state-based sweep. Tapping
    reads what was **actually dealt**: a creature whose damage was fully
    prevented was not "dealt damage by" the source (CR 615.1), so it does not
    tap.
    """
    card = context.card
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    minimum = int(instruction.payload.get("minimum", 0))
    maximum = int(instruction.payload.get("maximum", 1))
    tap_damaged = bool(instruction.payload.get("tap_damaged", False))

    candidates = [perm for _seat, perm in game.permanents_with_controller() if perm.is_creature]
    hits = flip_lands_on(candidates, minimum=minimum, maximum=maximum)
    if not hits:
        game.log.append(f"{card.name} landed on no creatures")
        return True, "resolved"

    def _hit(perm: Permanent) -> None:
        def _after(dealt: int) -> None:
            if dealt > 0 and tap_damaged:
                game.become_tapped(perm)

        apply_damage_to_creature(
            game, perm, amount, damage_dealer(context),
            log_message=lambda dealt: (
                f"{card.name} landed on {perm.card.name} and dealt {dealt} damage"
            ),
            then=_after,
        )

    for perm in hits:
        _hit(perm)
    return True, "resolved"


@effect_handler("deal_damage_each_attacking_creature")
def deal_damage_each_attacking_creature(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Sandstorm: "deals 1 damage to each attacking creature." Creature-only
    sweep across every battlefield — no player damage — resolved as one SBA
    batch so simultaneous lethal damage kills together."""
    card = context.card
    damage = _sweep_amount(instruction, context)
    struck = 0
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.is_creature and perm.attacking:
                apply_damage_to_creature(game, perm, damage, damage_dealer(context))
                struck += 1
    game.log.append(f"{card.name} dealt {damage} damage to each of {struck} attacking creatures")
    return True, "resolved"


@effect_handler("deal_damage_each_matching")
def deal_damage_each_matching(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Goblin Shrine deals 1 damage to each Goblin creature."

    A sweep over a *described* set, not a chosen one: nothing is targeted and
    nobody picks, so every permanent the printed noun phrase names is dealt to
    (CR 611.2c fixes that set when the effect begins). The set resolves through
    ``subject_matches`` — the one answer for what a printed noun phrase means —
    with the resolving controller as the observer, because "you control" is
    that seat's "you" (CR 109.5). The lowering admits only payloads that matcher
    tests in full, so nothing here can quietly burn a wider board than the card
    prints.

    Resolved as one batch, like the attacking-creature sweep above, so
    simultaneous lethal damage kills together.

    ``per_recipient_count`` is a multiplier taken **once per member** of that
    set: "Baki's Curse deals 2 damage to each creature **for each Aura attached
    to that creature**." It is a separate key from ``x_from_count`` precisely
    because that one holds a single number for the whole resolution — folded
    into it, the count read off the first creature would be dealt to all of
    them. The spec's relations resolve against the permanent being damaged,
    which is what the key's name says and what the ``source=perm`` below hands
    over.
    """
    from ._amounts import evaluate_count
    from ..subject_filters import subject_matches

    card = context.card
    # "…**it** deals damage equal to its power to each blocking creature."
    # (Electryte.) A *bite* over a described set: the amount is a read of the
    # dealer at resolution, not a number the lowering could bake in, which is
    # why `lowering/_bites.py` emits this kind rather than going through
    # `_sweeps` — both of that module's sweeps refuse a computed amount outright.
    #
    # CR 613's computed power, off the `Permanent` and not the card, so a pump
    # between the trigger firing and its resolution counts. A dealer that has
    # left the battlefield deals nothing rather than falling back to a number
    # the card never printed, which is the rule every other amount channel in
    # ``damage.py`` and this file follows.
    biter = (
        context.source_permanent
        if instruction.payload.get("amount_from_source_power")
        else None
    )
    # And the dealer is the permanent whatever the amount was read off
    # (CR 120.7). This used to be ``card`` for every branch but the bite above,
    # so twelve permanents — Pestilence's neighbours in the pool: Fire Ants,
    # Shard Phoenix, Subterranean Spirit, Downdraft, Cinder Giant, Crater
    # Hellion, Floodgate, Goblin Shrine, Goblin Swine-Rider, Heart of Bogardan,
    # Scalding Salamander, Sorrow's Path — swept the board as their printed
    # card. Nothing crashed and nothing was missing: a lifelinking Fire Ants
    # gained no life, a "whenever this creature deals damage" trigger did not
    # fire, and the source kept no record of what it had damaged.
    # ``damage_dealer`` is the one answer; see its docstring for the four
    # readers.
    dealer = damage_dealer(context)
    if instruction.payload.get("amount_from_source_power"):
        damage = max(0, biter.effective_power) if biter is not None else 0
    else:
        damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    described = instruction.payload.get("filter") or {}
    per_recipient = instruction.payload.get("per_recipient_count")
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    # "…each creature **target opponent** controls" (Simoon). A seat this
    # resolution chose (CR 601.2c), which no read of a permanent can supply — so
    # it is handed to the matcher, which refuses the word without one. Before
    # it did, "target opponent" fell through to the matcher's "not you" test and
    # the spell burned **every** opponent's creatures: right in a duel by
    # coincidence, and a strictly larger effect than the card prints the moment
    # a third seat is at the table.
    targeted = (
        game.players.index(context.target)
        if context.target is not None and context.target in game.players
        else None
    )
    # "…and each creature that player **or that planeswalker's controller**
    # controls" (Heart of Bogardan). The one printed clause whose target may be
    # an object rather than a seat, and it names the seat that then means. Read
    # only when the payload says the card printed the word: a sweep that
    # inferred a controller from any permanent target would answer a seat for
    # sentences that never named one, and a seat answered where none was named
    # is a board burned that the card never pointed at.
    if targeted is None and instruction.payload.get("target_controller_if_permanent"):
        chosen = game.permanent_by_id(context.target_permanent_id)
        if chosen is not None:
            targeted = game.controller_index_of(chosen)
    # "…each creature without flying **defending player** controls" (Scalding
    # Salamander). CR 506.2's seat, and the one word in this sentence that no
    # read of the board can answer at resolution: by then the combat the
    # trigger fired in may be over. The fire site froze it (CR 603.10) and every
    # other handler in the pool reads it off the trigger context under this
    # name; this one never asked, so `subject_matches` refused the word — the
    # direction that narrows to nothing — and Exodus's Salamander logged "found
    # nothing to damage" every time its only ability resolved.
    defending = defending_player_seat(game, context)
    struck = []
    for perm in list(game.all_permanents()):
        if not subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent, targeted_player=targeted,
            defending=defending,
        ):
            continue
        dealt = damage
        if per_recipient is not None:
            dealt = damage * evaluate_count(game, caster, per_recipient, source=perm)
            # CR 120.8: a source that *would* deal 0 damage does not deal damage
            # at all — no event, so nothing triggers and no shield is spent. A
            # creature with no Aura on it is not dealt 0 by Baki's Curse, it is
            # not dealt to.
            if dealt <= 0:
                continue
        # The dealer is the permanent (CR 120.7) — for the bite because the
        # sentence made the source the dealer, and for every other branch
        # because the rule does. ``dealer`` already folds a spell back to its
        # printed card, so Pyroclasm is unchanged.
        apply_damage_to_creature(game, perm, dealt, biter if biter is not None else dealer)
        struck.append(f"{perm.card.name} ({dealt})" if per_recipient else perm.card.name)
    if not struck:
        game.log.append(f"{card.name} found nothing to damage")
    elif per_recipient is not None:
        game.log.append(f"{card.name} dealt damage to {', '.join(struck)}")
    else:
        game.log.append(f"{card.name} dealt {damage} damage to {', '.join(struck)}")
    return True, "resolved"

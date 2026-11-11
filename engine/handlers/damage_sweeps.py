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

**Every recipient's event may stop to ask** (CR 616.1e). A creature with two
applicable effects -- Phantom Centaur's counter shield and its protection from
black, under Pestilence -- has its controller choose which applies first, and
that is a question the damage event asks an interactive seat and then re-runs
on the answer (``asks=True``). So each sweep is a resumable loop over its
recipients (:func:`_sweep`): the recipients behind the one that asked are still
dealt to when the answer arrives, and the summary line is the loop's last step.
These sweeps called the damage entry points without ``asks``, so the seat got
the default and never saw the question (Judgment's W1G2 measured it; W2G2).

**The recipients are asked in APNAP order** (CR 616.1's last sentence): a
sweep deals to every recipient at once, so each affected player's choices are
made at the same time — the active player's first, then each other player's
in turn order (``effect_ordering.in_apnap_order``, applied by :func:`_sweep`).
They walked ``game.players``, which asked seat 0 first on every turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import simultaneous_damage
from ..dexterity import flip_lands_on
from ..game_types import single_chosen_id
from ..models import Permanent
from ..named_counters import counters_on
from ..regeneration import deny_regeneration_if_dealt
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


def _sweep(game: Game, recipients, hit, done, *, source, affected=None) -> None:
    """*hit* each of *recipients* in turn and then run *done*, resumably.

    The one loop every sweep here runs, so a recipient whose event stops to
    ask (CR 616.1e) takes the rest of the sweep with it and the answer brings
    it back. *done* -- the summary -- is the loop's own last step
    (``run_resumable``'s ``then``) rather than a line after it, because work
    written after a resumable loop does not run when a step suspends. Must be
    the last thing its caller does.

    The recipients are walked in APNAP order of the seat each one's question
    goes to (``in_apnap_order``; *affected* maps an item to its recipient
    where the item is something else).

    **One simultaneous dealing** (``engine/simultaneous_damage.py``): *source*
    deals its damage to every recipient at once, so a trigger reading the
    event from the source's side — "whenever this deals damage", "whenever a
    red creature or spell deals damage" (Justice's ruling: "If a single source
    does damage to multiple targets at once, Justice will add up all the
    damage done") — is announced once, for the total, as the loop's last step
    finishes the dealing. ``simultaneous_damage.deal_at_once`` is that loop,
    shared with every other effect dealing damage to several recipients."""
    simultaneous_damage.deal_at_once(
        game, recipients, hit, source=source, then=done, affected=affected,
    )


@effect_handler("deal_damage_each_creature_and_player")
def deal_damage_each_creature_and_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    amount = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(
        game, damage_dealer(context), amount, lambda perm: True,
        done=lambda: game.log.append(
            f"{card.name} dealt {amount} damage to each creature and each player"
        ),
        no_regen=bool(instruction.payload.get("no_regen_if_dealt")),
    )
    return True, "resolved"


def _has_flying(perm: Permanent) -> bool:
    """Flying from any source — printed, granted, or granted then removed.
    Reading the grant flags directly would miss whichever route a future card
    uses and would get grant-after-removal backwards (CR 613.9)."""
    return perm.has_keyword("flying")


def _mass_damage_players_and_creatures(
    game: Game, source, damage: int, creature_predicate, done=None,
    *, no_regen: bool = False,
) -> None:
    """Earthquake/Hurricane sweep: damage every player, then every creature
    passing the predicate, then destroy the lethally damaged as one SBA batch.

    Through ``apply_damage_to_creature``, never ``_mark_damage_on_permanent``:
    the marking is only half of a damage event, and the other half is
    ``_fire_dealt_damage_triggers``. Every sweep in this file reached for the
    lower call and so dealt damage that nothing could notice — Fungusaur took a
    point from Earthquake and grew no counter across five shipped sets. The
    per-creature triggers are correct here rather than batched: CR 603.2 puts
    one on the stack per creature dealt to, and the state-based sweep that kills
    them still runs once, after.

    One resumable loop (:func:`_sweep`) and then *done* -- each event free to
    stop and ask its recipient's controller which effect applies first (CR
    616.1e), seat by seat in APNAP order: the active player and their
    creatures, then the next player and theirs. The creatures are the ones
    the predicate names as the sweep begins (Earthquake's ruling: "whether or
    not a creature is without flying is only checked on resolution"); they
    were read off the board after the players had been dealt to.

    *no_regen* is the printed "Creatures dealt damage this way can't be
    regenerated this turn" (Flamebreak; CR 701.19c), stamped on each creature
    the sweep **actually dealt damage to** — inside its event, as the damage is
    dealt, so before the state-based check that would destroy it. A creature
    whose damage was all prevented was not dealt damage this way (CR 615.1)
    and may still be regenerated."""
    creatures = [
        perm for perm in game.all_permanents()
        if perm.is_creature and creature_predicate(perm)
    ]

    def hit(item) -> None:
        if isinstance(item, Permanent):
            if game.is_on_battlefield(item):
                apply_damage_to_creature(
                    game, item, damage, source, asks=True,
                    then=(
                        lambda dealt, perm=item: deny_regeneration_if_dealt(perm, dealt)
                    ) if no_regen else None,
                )
            return
        game._deal_damage_to_player(item, damage, source=source, asks=True)

    _sweep(game, [*game.players, *creatures], hit, done, source=source)


@effect_handler("earthquake_damage")
def earthquake_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(
        game, damage_dealer(context), damage, lambda perm: not _has_flying(perm),
        done=lambda: game.log.append(
            f"{card.name} dealt {damage} earthquake damage to each non-flying "
            "creature and each player"
        ),
        no_regen=bool(instruction.payload.get("no_regen_if_dealt")),
    )
    return True, "resolved"


@effect_handler("hurricane_damage")
def hurricane_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(
        game, damage_dealer(context), damage, _has_flying,
        done=lambda: game.log.append(
            f"{card.name} dealt {damage} hurricane damage to each flying "
            "creature and each player"
        ),
        no_regen=bool(instruction.payload.get("no_regen_if_dealt")),
    )
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
            asks=True,
        )

    _sweep(game, hits, _hit, None, source=damage_dealer(context))
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
    struck = [
        perm
        for player in game.players
        for perm in list(player.battlefield)
        if perm.is_creature and perm.attacking
    ]
    _sweep(
        game, struck,
        lambda perm: apply_damage_to_creature(
            game, perm, damage, damage_dealer(context), asks=True,
        ),
        lambda: game.log.append(
            f"{card.name} dealt {damage} damage to each of {len(struck)} "
            "attacking creatures"
        ),
        source=damage_dealer(context),
    )
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
        chosen = game.permanent_by_id(single_chosen_id(context.target_permanent_id))
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
    # The set is fixed as the effect begins (CR 611.2c), with each member's
    # amount: one list, then one resumable loop over it.
    recipients = []
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
        recipients.append((perm, dealt))
    # "…X damage divided evenly, rounded down, among all creatures target
    # opponent controls." (Dwarven Catapult.) The share is X over the set the
    # sweep just found — counted now, at resolution (the card's 2004-10-04
    # ruling) — and a share of 0 is no damage dealt at all (CR 120.8; the
    # 2014-02-01 ruling: "If the targeted opponent controls more than X
    # creatures, no damage will be dealt to any of them").
    if instruction.payload.get("divided_evenly") and recipients:
        damage = damage // len(recipients)
        recipients = (
            [(perm, damage) for perm, _whole in recipients] if damage > 0 else []
        )
    struck = [
        f"{perm.card.name} ({dealt})" if per_recipient else perm.card.name
        for perm, dealt in recipients
    ]

    def hit(entry) -> None:
        perm, dealt = entry
        # The dealer is the permanent (CR 120.7) — for the bite because the
        # sentence made the source the dealer, and for every other branch
        # because the rule does. ``dealer`` already folds a spell back to its
        # printed card, so Pyroclasm is unchanged.
        apply_damage_to_creature(
            game, perm, dealt, biter if biter is not None else dealer, asks=True,
        )

    def summary() -> None:
        if not struck:
            game.log.append(f"{card.name} found nothing to damage")
        elif per_recipient is not None:
            game.log.append(f"{card.name} dealt damage to {', '.join(struck)}")
        else:
            game.log.append(f"{card.name} dealt {damage} damage to {', '.join(struck)}")

    _sweep(
        game, recipients, hit, summary, affected=lambda entry: entry[0],
        source=biter if biter is not None else dealer,
    )
    return True, "resolved"

"""Shared *actions* for effect handlers.

The leading underscore keeps this module out of the handler-registry import
pattern in ``engine/handlers/__init__.py`` — it registers no handlers, it only
hosts logic the registered handlers share.

**It was 3,838 lines until the 2,000-line cap's split round**, holding two kinds
of thing under one name: what a handler *reads* — what a filter payload means,
what a printed amount counts to, which object a sentence names — and what a
handler *does* the same way several others do. The reads left for four floors,
each a subject a reader can name, and each reading only the ones before it in
this list:

* ``_chosen`` — a word whose meaning was chosen earlier ("of the chosen color",
  "of that type", "with the same name as that spell") turned into filter keys;
* ``_filters`` — whether a card, a permanent or a seat answers a filter payload;
* ``_targets`` — which object or seat a resolving instruction names: its chosen
  targets and roles, a record an earlier step wrote, and the back-references a
  sentence prints ("enchanted creature", "defending player", "that player");
* ``_amounts`` — a printed quantity counted at resolution.

None of them reads this module. What stayed here are the actions: a permanent
returned to its owner's hand, a coin flipped, a P/T change with a lifetime,
damage marked on a creature and the object that deals it.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable


if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
from ..models import Permanent

# Re-exported, and not an API: an importer pulls a name from the floor it lives
# in. Each name below is pulled from here by a module another group of the same
# split round was cutting in parallel (``engine/legality.py``,
# ``engine/mixins/stack/choices.py``, ``engine/ai_policy.py``,
# ``engine/ai_valuation.py``, ``engine/activation_restrictions.py``,
# ``engine/cast_restrictions.py``), mostly from inside functions that round was
# moving, so the import lines could not move with this split without a merge
# conflict on every one. Four modules ``tests/engine/test_module_size.py``
# still holds at their size pull some of them from here too
# (``engine/handlers/control_flow.py``, ``engine/handlers/stack.py``,
# ``engine/mixins/permanent_state.py``, ``engine/mixins/stack/activation.py``):
# one import statement there would have become several, and a held module may
# not grow. Each name goes when its last importer is repointed — the import
# hygiene guard fails a re-export nobody pulls.
from ._amounts import count_from_payload, evaluate_count, resolve_amount
from ._chosen import CHOSEN_CARD_TYPE, _resolve_chosen_subtype
from ._filters import (_card_matches_filter, _comparison_holds,
                       excluded_graveyard_slot, graveyard_card_matches,
                       graveyard_slots_matching, permanent_matches_filter,
                       state_holds)
from ._targets import attached_host, resolve_target_permanent


def return_permanent_to_owners_hand(game, permanent, fallback_owner=None):
    """Take one permanent off the battlefield into its owner's hand (CR 400.3).

    The whole of what "return <permanent> to its owner's hand" *does*, in one
    place, because five callers perform it and each of them used to spell it
    out: the single bounce, the several-targets bounce, the sweep, the chosen
    bounce and the untap-step replacement. Three spellings of one move is three
    chances for one of them to forget something.

    The per-turn ledger Barrin reads (``permanents_to_hand_this_turn``) is
    **not** one of the things this does. It was, bumped here by hand — which
    is how every return that did not come through this helper went uncounted.
    ``put_card_into_hand`` writes it, at the same line that announces the
    move, so a permanent diverted to the command zone (CR 903.9b) or sent
    elsewhere by a CR 614 replacement is not counted and a token, which is
    put into the hand before it ceases to exist, is.

    *fallback_owner* is the seat used when CR 108.3's owner cannot be derived,
    which for a permanent on the battlefield is nothing that happens — it is
    there so a caller that has an obvious answer states it rather than the
    helper inventing one.

    Returns the player whose hand it went to, which every caller logs.
    """
    owner_idx = game.owner_index_of(permanent)
    owner = game.players[owner_idx] if owner_idx is not None else fallback_owner
    if owner is None:
        owner = game.players[0]
    game.put_card_into_hand(owner, permanent.card, from_battlefield=permanent)
    game.remove_from_battlefield(permanent)
    return owner


def flip_coin(win_probability: float = 0.5) -> bool:
    """Flip a coin, returning True on a win (CR 705). Draws from the module-level
    RNG that ``run_ai_simulation`` seeds, so a given seed replays identically."""
    return random.random() < win_probability


def flip_coin_for(game: Game, flipper, *, flip=None) -> bool:
    """A coin flip *flipper* **wins or loses** (CR 705.2), announced.

    The seam for every flip a player can win. CR 705.2 draws the line this
    function is named for: an effect that "cares only about whether the coin
    comes up heads or tails" (Mana Clash) has no winner — it goes on calling
    :func:`flip_coin` — and for every other flip "only the player who flips the
    coin wins or loses". So the announcement carries one seat, the flipper's,
    and "Whenever **you** win a coin flip" (Chance Encounter) hears exactly the
    flips its controller made and won, which is the card's own ruling ("Your
    opponent losing a flip does not count as you winning one").

    One draw from the same RNG, in the same place the bare call made it, so a
    seeded game replays the flips it always did. The trigger goes on the stack
    behind the object that is resolving, as every event announced part-way
    through a resolution does.

    *flip* is the **caller's own coin** — each handler module passes the
    ``flip_coin`` it imported. That is not decoration: a module's ``flip_coin``
    is the name a dozen tests rig ("engine.handlers.control_flow.flip_coin"),
    and a seam that drew from its own module's coin instead would have made
    every one of those rigs a patch on a name nothing calls. A name a test
    patches is an interface, exactly as a log line is.
    """
    won = (flip or flip_coin)()
    if won and flipper is not None:
        seat = next(
            (index for index, player in enumerate(game.players) if player is flipper),
            None,
        )
        if seat is not None:
            from ..events import emit

            emit(game, "you_win_coin_flip", seat=seat)
    return won


def apply_temp_pt_boost(
    perm: Permanent, power: int = 0, toughness: int = 0, *, until: str = "end_of_turn"
) -> None:
    """Apply a P/T change that ends at *until* and track it so that duration's
    sweep can remove it. Thin wrapper over the single P/T write API in
    engine/pt.py; *until* names a channel in ``pt.TEMPORARY_PT_CHANNELS``."""
    from ..pt import add_pt_modifier

    add_pt_modifier(perm, power, toughness, until=until)


def damage_dealer(context: "OracleExecutionContext"):
    """The object a resolving effect deals its damage **as** (CR 120.7).

    CR 608.2h says it in one sentence: "If an ability states that an object does
    something, it's the object as it exists — or as it most recently existed
    — that does it, **not the ability**." CR 120.7 then makes that object the
    source of the damage, and CR 113.7a is why the ability outliving its source
    changes nothing.

    So a permanent's activated or triggered ability deals damage as the
    *permanent*, never as the card the ability is printed on.
    ``context.card`` is the card as printed: one immutable object handed out
    once per copy by the deck builder, shared by every copy in the process and
    controlled by nobody. Four readers ask the source what it is, and the
    printed card answers none of them —

    * lifelink (CR 702.15b) reads a keyword off the source, and
      ``damage_events.lifelink_life_gained`` returns 0 for anything with no
      ``has_keyword``;
    * a "deals damage" trigger narrowed by ``damager_self`` or by a noun phrase
      compares the source *by identity* against a permanent
      (``events.py``), and a card matches nothing;
    * ``_announce`` publishes ``event_subject_permanent_id`` only for a source
      with an id, so "…deals that much damage to **that creature**" cannot name
      the dealer;
    * ``damage_events.DAMAGED_THIS_GAME`` is kept *on the source permanent*, so
      a card-sourced event writes no record at all.

    A spell is its own source (CR 109.5) and has no permanent — which is
    exactly what ``source_permanent is None`` says, and so is a trigger that
    fired from a graveyard (``events.graveyard_trigger_events`` sets it None on
    purpose). Both fall through to the card, which is the truth for them and
    the behaviour every spell in the pool already had.

    A permanent that has **left** still answers: Shard Phoenix sacrifices
    itself to pay for the ability that sweeps and Floodgate's whole trigger is
    its own departure. CR 608.2h reads such a source's last known information,
    which is the detached ``Permanent`` — not the printed card.

    The seat is *not* this question. ``damage_events.damage_source_seat``
    already derives it for a card source by falling through to
    ``Game.resolving_seats``, which is why "a source you control" was right
    while everything above was wrong: one of the four readers had its own
    answer and the other three did not.
    """
    source_permanent = context.source_permanent
    return source_permanent if source_permanent is not None else context.card


def apply_damage_to_creature(
    game: Game,
    perm: Permanent,
    amount: int,
    source,
    log_message: Callable[[int], str] | None = None,
    then: Callable[[int], None] | None = None,
    asks: bool = False,
    unpreventable: bool = False,
    cant_be_prevented: bool = False,
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

    return game._mark_damage_on_permanent(
        perm, amount, source=source, then=finish, asks=asks,
        unpreventable=unpreventable, cant_be_prevented=cant_be_prevented,
    )

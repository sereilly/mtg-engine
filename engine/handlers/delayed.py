"""A resolving spell or ability creating a **delayed triggered ability**
(CR 603.7): "at the beginning of the next end step, …", "when that creature
dies this turn, …".

What the entry is *about* is bound here, while the creating effect still
knows it — the permanent, the player, the card, the number — and everything
else is payload. ``engine/delayed_triggers.py`` holds the entry, the events it
watches and the firing; this module is the seam between a resolving stack
object and that registry.

The handler twin of ``engine/grammar/lowering/delayed.py``. Split out of
``board_misc.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..delayed_triggers import END_OF_TURN, DelayedTrigger, arm_delayed_trigger
from ..tokens import CREATED_TOKEN_RESULT_KEY
from ._chosen import (COLOR_CHOSEN_THIS_WAY_KEY,
                      resolve_color_chosen_in_resolution)
from ._targets import attached_host, block_pair_permanents, bound_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("create_delayed_trigger")
def create_delayed_trigger(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A resolving spell or ability creating a delayed triggered ability
    (CR 603.7) — Basri Ket's −2, Mana Drain's mana, Reincarnation's death
    watch. Every field of the entry is payload; what it is *about* is bound
    here, while the creating effect still knows.

    ``engine/delayed_triggers.py`` holds the entry, the registry of events that
    have a fire site, and the one routine that fires them.
    """
    payload = instruction.payload
    seat = game.players.index(context.caster)
    # CR 603.7c: "that creature" is the permanent this spell targeted, read now
    # — by resolution time of the *delayed* ability it may be in a graveyard,
    # and an index would by then address whatever slid into its slot.
    bound_id = None
    watched_id = None
    # "…when **Stangg** leaves the battlefield" / "…when **that token** leaves
    # the battlefield" (Stangg). The opener names an object this effect already
    # holds rather than one it chose, so there is no target to resolve: the
    # source is on the context, and the token is the id the token maker wrote
    # to the scratchpad a step ago.
    #
    # An id that is not there arms **nothing**. Left unbound the entry would
    # match the *first* permanent to leave the battlefield, which is the
    # widening every bound-object payload in this engine exists to prevent.
    watches = payload.get("watches")
    if watches is not None:
        if watches == "source":
            watched_id = (
                context.source_permanent.permanent_id
                if context.source_permanent is not None else None
            )
        elif watches == "created_token":
            recorded = (context.results or {}).get(CREATED_TOKEN_RESULT_KEY)
            watched_id = recorded if isinstance(recorded, int) else None
        if watched_id is None:
            game.log.append(
                f"{context.card.name} had no permanent to watch"
            )
            return True, "no object"
    recorded_key = payload.get("binds_recorded")
    if recorded_key is not None:
        # "…**Exile it** at the beginning of the next end step." (Shallow
        # Grave, Zirilan of the Claw.) CR 603.7c's object, read out of the
        # record an earlier step of *this* resolution wrote — the permanent
        # it put onto the battlefield, which nothing targeted and which does
        # not exist until that step runs.
        #
        # An empty record arms **nothing**, for `watches`' reason one branch
        # up: an unbound entry would answer to the first permanent the event
        # names, which is the widening every bound payload here prevents.
        ids = (context.results or {}).get(str(recorded_key))
        if isinstance(ids, int):
            ids = (ids,)
        bound_id = next(
            (found for found in (ids or ()) if isinstance(found, int)), None
        )
        if bound_id is None:
            game.log.append(
                f"{context.card.name} had no permanent to be about"
            )
            return True, "no object"
    elif payload.get("binds_event_subject"):
        # "Whenever a creature you control attacks, **it** phases out at end of
        # combat." (Teferi's Veil.) CR 603.7c's object again, and a third place
        # to read it from: the ability is created by a *trigger*, and the object
        # it is about is the one that trigger's own event was about — an
        # attacker the fire site stamped by id (CR 603.10) and never made the
        # stack item's target.
        #
        # So neither branch above can find it. ``binds_recorded`` reads a step
        # of this resolution's scratchpad and there is no such step;
        # ``binds_target`` resolves the stack item's target and the announcement
        # named none, which would arm an entry about nothing while the card
        # compiled clean. The lowering is what decides which of the three
        # applies, from the *creating* event, and refuses an event that freezes
        # no object.
        #
        # The literal key, for the reason `binds_player` below spells its own:
        # the fire sites write it and the handler layer does not import from the
        # grammar's lowering package.
        recorded = (context.trigger_context or {}).get("event_subject_permanent_id")
        if not isinstance(recorded, int):
            game.log.append(f"{context.card.name} had no permanent to be about")
            return True, "no object"
        bound_id = recorded
    elif payload.get("binds_block_pair"):
        # "Whenever this creature blocks a creature, return **that creature**
        # to its owner's hand at end of combat." (Wall of Tears.) CR 603.7c's
        # object once more, and the fourth place a creating ability can have
        # put it: a block announcement records the pair under
        # ``blocked_permanent_ids`` and makes the stack item's target the
        # ability's *own* creature, so ``binds_target`` beside this would bind
        # the blocker — the card bouncing itself.
        #
        # ``block_pair_permanents`` is the one reader of that difference, the
        # same one every immediate block-pair effect goes through. Exactly one,
        # because an entry names one object: the lowering's ``binds_block_pair``
        # gate already requires a narrowed condition (CR 509.3c/509.3d), which
        # is what makes the pair a single creature, and a firing that somehow
        # named several arms nothing rather than picking one arbitrarily.
        pair = block_pair_permanents(game, context)
        if len(pair) != 1:
            game.log.append(
                f"{context.card.name} had no single creature to be about"
            )
            return True, "no object"
        bound_id = pair[0].permanent_id
    elif payload.get("binds_attached_host"):
        # "When enchanted creature attacks, return **it** and this Aura to
        # their owners' hands at end of combat." (Contempt.) CR 603.7c's object
        # a fifth time, and the fifth place a creating ability can have put it:
        # the trigger is an *Aura's*, so the words name the permanent it is
        # attached to — which no fire site stamps, and which the attached
        # fire sites never make the stack item's target either. Both readings
        # beside this one would arm an entry about nothing.
        #
        # Resolved **here**, as the trigger resolves, rather than left for the
        # effect to ask at end of combat. That is the rule itself: the delayed
        # ability is about the creature the Aura was on when it was created, so
        # an Aura destroyed in between still returns that creature — where a
        # handler reading the attachment at fire time would find none and
        # quietly do nothing.
        host = attached_host(game, context.source_permanent)
        if host is None:
            game.log.append(f"{context.card.name} was attached to nothing")
            return True, "no object"
        bound_id = host.permanent_id
    elif payload.get("binds_target"):
        # The **innermost** binding, not the resolution's target list: inside
        # "for each of those creatures, … destroy that creature at end of
        # combat" (Winter's Chill) the ability is created once per creature and
        # is about that one. Outside a loop this is the target the spell chose,
        # which is every other card that arms one.
        bound = bound_permanent(game, context)
        if bound is None:
            # The target is gone (CR 608.2b): there is nothing for the delayed
            # ability to be about, so none is created.
            game.log.append(f"{context.card.name} had no creature to watch")
            return True, "no target"
        bound_id = bound.permanent_id
    # The two roles are one object on every card that names only one, which is
    # every card but War Barge. Collapsed here rather than at the comparison, so
    # the entry states outright what it watches and what it is about instead of
    # leaving one of them to be inferred.
    if bound_id is None:
        bound_id = watched_id
    if watched_id is None:
        watched_id = bound_id
    # CR 608.2h's last-known information, frozen at creation. The resolution
    # scratchpad *is* what
    # this effect's earlier steps knew — Mana Drain's countered spell and its
    # mana value — and by the time the ability fires, a phase or a turn later,
    # not one of those objects is still where it was. Frozen whole rather than
    # key by key, because a list of which values a delayed ability might read
    # is a list that goes stale the moment a new one prints.
    # What the *creating* ability knew is both halves: its own scratchpad and
    # the context its fire site froze. "Whenever a creature dealt damage by this
    # creature this turn dies, put that card onto the battlefield … at the
    # beginning of the next end step" (Seraph) reads the dead card out of the
    # second half, and only the second half — a trigger's context is not a
    # resolution record and nothing had ever carried it across a delay.
    #
    # The trigger context goes *under* the scratchpad, so a value this
    # resolution actually produced wins over one the event merely reported.
    captured = {**(context.trigger_context or {}), **(context.results or {})}
    # "Choose target opponent. … When it regenerates this way, **that player**
    # may draw a card." (Soldevi Sentry.) The seat an earlier step of this same
    # resolution chose, read out of the scratchpad under the one key a chosen
    # player is ever written to. An entry that binds a player and has none
    # arms nothing, for the reason a bound *object* that is gone does: the
    # ability would otherwise be about whichever seat the firing resolution
    # happened to carry.
    bound_seat = None
    binds_player = payload.get("binds_player")
    if binds_player:
        # The literal, for the reason `choose_permanent` above spells it: the
        # key is declared in `grammar/lowering/_record_keys.CHOSEN_PLAYER`, and the
        # handler layer does not import from the grammar's lowering package.
        #
        # "…at the beginning of **their** next upkeep" (Sabertooth Cobra) binds
        # a seat the creating *trigger* named rather than one an earlier step
        # chose, so the key says which record — the damage event's frozen
        # recipient, stamped by `damage_events._announce`. Two records, one
        # field, and the payload is what says which: read as the chosen-player
        # one it would find nothing and arm no ability at all.
        # Three records, one field, and the payload is what says which. Read as
        # each other none of them finds anything and the ability is armed about
        # nobody, so the miss is loud rather than a default seat.
        if binds_player == "damaged_player":
            recorded = (context.trigger_context or {}).get("defending_player_index")
        elif binds_player == "exiled_spell_controller":
            # "Target spell's controller exiles it … at the beginning of each of
            # **that player's** upkeeps" (Ertai's Meddling). The seat an earlier
            # step of *this* resolution wrote down when it took the spell off the
            # stack — the controller a card in exile no longer has (CR 108.4).
            #
            # The literal, for the reason the two beside it spell theirs: the key
            # is declared in ``engine/exiled_records.py`` beside the reader that
            # answers it, and the handler layer does not import from the
            # grammar's lowering package.
            recorded = (context.results or {}).get("exiled_spell_controller")
        elif binds_player == "event_subject_player":
            # "Whenever a player casts a spell, they may pay {1}. If the player
            # does, **they** draw a card at the beginning of the next end
            # step." (Horn of Plenty.) The seat the *creating trigger's* event
            # froze (CR 603.10), which is the one record that says who cast:
            # the resolution's own player is whoever the fire site defaulted
            # to, so the Horn's controller paid and an opponent drew.
            recorded = (context.trigger_context or {}).get("event_subject_player")
            if recorded is None:
                # …and where no trigger froze one (an entry armed outside a
                # firing), CR 603.7c's default below: the player this
                # resolution was about.
                recorded = next(
                    (seat for seat, seated in enumerate(game.players)
                     if seated is context.target),
                    None,
                )
        elif binds_player == "target_player":
            # "…the end step of **that player's** next turn" behind "target
            # player exiles …" (Suppress); "**Target player** draws a card at
            # the beginning of the next turn's upkeep" (Sapphire Charm); "**That
            # player** draws a card …" (Lodestone Bauble). A fourth record and
            # the plainest: the seat this resolution itself holds — the one the
            # spell or ability announced (CR 601.2c/602.2b), frozen now because
            # the firing resolution a turn later holds a default instead. By
            # identity, because a `PlayerState` compares by value and two seats
            # holding the same cards match each other.
            recorded = next(
                (i for i, seated in enumerate(game.players)
                 if seated is context.target),
                None,
            )
        else:
            recorded = (context.results or {}).get("chosen_player")
        if not isinstance(recorded, int) or not (0 <= recorded < len(game.players)):
            game.log.append(f"{context.card.name} had no player to watch")
            return True, "no player"
        bound_seat = recorded
    else:
        # CR 603.7c for every entry no record above seats: the player this
        # resolution was *about* — its own target, or the seat an offer was
        # put to — is the player a delayed "that player" names, frozen now.
        #
        # It used to be left unbound, and an unbound trigger's target is the
        # seat opposite its controller (``_run_stack_item_resolution``'s
        # default for a resolution that names nobody). So "…from a player's
        # graveyard on top of their library. **That player** draws a card at
        # the beginning of the next turn's upkeep" (Lodestone Bauble) drew
        # for the opponent whenever it was aimed at its controller's own
        # graveyard, "**Target player** draws a card at the beginning of the
        # next turn's upkeep" (Sapphire Charm) did the same aimed at oneself,
        # and Horn of Plenty paid for the other player's card — each right
        # exactly when the named player happened to be the opponent, which is
        # the half a two-player test tries first.
        #
        # For a resolution that named nobody the context's target *is* that
        # default, so the entry carries the seat it would have been given at
        # fire time and nothing else changes; an effect that does not read a
        # target player never looks. By identity: a ``PlayerState`` compares
        # by value, and two seats holding equal state match each other.
        bound_seat = next(
            (
                index for index, seated in enumerate(game.players)
                if seated is context.target
            ),
            None,
        )
    # "Choose a color. Whenever this creature becomes blocked by a creature
    # **of that color** this turn, …" (Zombie Boa.) CR 608.2d's choice, made by
    # an earlier step of this resolution and spent **now** into the ordinary
    # ``color_filter`` — the entry outlives the scratchpad the colour was
    # written to, so a filter still carrying the phrase at fire time would be
    # asked of a resolution that never chose anything. Through the one reader
    # of that phrase, so "of that color" means here what it means in a count or
    # a sweep.
    #
    # A phrase nothing answered arms **nothing**, for the reason an unbound
    # object does one screen up: both matchers refuse the key outright, so the
    # entry would wait all turn for a creature that cannot exist.
    narrowings = {
        key: resolve_color_chosen_in_resolution(
            dict(payload.get(key) or {}), context
        )
        for key in ("subject_filter", "agent_filter")
    }
    if any(COLOR_CHOSEN_THIS_WAY_KEY in found for found in narrowings.values()):
        game.log.append(f"{context.card.name} had no chosen color to watch for")
        return True, "no color"
    arm_delayed_trigger(game, DelayedTrigger(
        bound_player_index=bound_seat,
        controller_index=seat,
        event=payload.get("event", "creatures_attack"),
        instruction=payload.get("instruction"),
        source_name=context.card.name,
        card=context.card,
        bound_permanent_id=bound_id,
        bound_as_target=bool(payload.get("bound_as_target")),
        watched_permanent_id=watched_id,
        # CR 603.7d's source, frozen now: an activated ability's own permanent
        # is what "this creature" means when the delay finally fires.
        source_permanent_id=(
            context.source_permanent.permanent_id
            if context.source_permanent is not None else None
        ),
        captured=captured,
        # "…whenever **a creature you control with power 2 or less** attacks"
        # (Subira). The narrowing travels as the same filter payload every
        # other one does; the fire sites ask `subject_matches`, which has the
        # seat "you control" needs. Empty means no narrowing.
        subject_filter=narrowings["subject_filter"],
        agent_filter=narrowings["agent_filter"],
        once=bool(payload.get("once")),
        duration=payload.get("duration", END_OF_TURN),
        batch=bool(payload.get("batch")),
        nontoken=bool(payload.get("nontoken")),
    ))
    game.log.append(f"{context.card.name} created a delayed triggered ability")
    return True, "resolved"

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

from ..cast_timing import CAST_AT_INSTANT_SPEED
from ..delayed_triggers import (CARRY_OUT_DELAYED_MARK,
                                DELAYED_MARK_PERMANENT_IDS, END_OF_TURN,
                                WHILE_EXILED_THIS_WAY, DelayedTrigger,
                                arm_delayed_trigger, delayed_ability_text)
from ..text_changes import spell_text_card
from ..tokens import CREATED_TOKEN_RESULT_KEY
from ._common import return_permanent_to_owners_hand
from ._chosen import (COLOR_CHOSEN_THIS_WAY_KEY,
                      resolve_color_chosen_in_resolution)
from ._targets import attached_host, block_pair_permanents, bound_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _creating_words(game: Game, context: OracleExecutionContext) -> str:
    """What the object creating a delayed trigger **says** — the words the
    delayed ability's own sentence is read from: a resolving spell's with
    its text changes (``OracleExecutionContext.text_card``, CR 612), an
    ability's own printed line (``ability_text``), else its source
    permanent's text through the layers (CR 613.1c). Empty when none is
    known, and the stack item then keeps its card's name."""
    if context.text_card is not None:
        return context.text_card.oracle_text or ""
    if context.ability_text:
        return context.ability_text
    if context.source_permanent is not None:
        return context.source_permanent.effective_card.oracle_text or ""
    if game.resolving_stack_item is not None:
        return spell_text_card(game.resolving_stack_item).oracle_text or ""
    return ""


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
        # ``blocked_permanent_ids`` and names the ability's *own* creature as
        # the object it is about (handed to the effect as its target), so
        # ``binds_target`` beside this would bind the blocker — the card
        # bouncing itself.
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
    if payload.get("duration") == WHILE_EXILED_THIS_WAY:
        # "**For as long as any of those cards remain exiled,** …" (Dimensional
        # Breach.) The cards the step in front exiled, one exile record each —
        # registered now, while this resolution still knows which cards and
        # whose (CR 603.7c), and frozen into the scratchpad the capture below
        # copies, so every firing asks the same records. CR 611.2b: with no
        # card exiled the duration never starts and the ability does nothing,
        # so none is created.
        from .exiled_returns import exiled_this_way_records

        if not exiled_this_way_records(game, context):
            game.log.append(
                f"{context.card.name} exiled no cards, so its delayed ability "
                "is never created"
            )
            return True, "no cards"
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
        ability_text=delayed_ability_text(_creating_words(game, context)),
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


#: The step each mark is announced in, as its log lines name it; every mark
#: not listed is the end step's. "The controller of the permanent it becomes
#: sacrifices it at the beginning of the next cleanup step" (Mirage's flash
#: Auras) is the cleanup step's.
_MARK_STEPS = {
    "destroy_at_end_of_combat": "end of combat",
    CAST_AT_INSTANT_SPEED: "cleanup",
}


@effect_handler(CARRY_OUT_DELAYED_MARK)
def carry_out_delayed_mark(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A delayed triggered ability recorded as a **mark**, resolving (CR
    603.7): "destroy that creature at end of combat" (Cockatrice), "…at the
    beginning of the next end step" (Dragon Whelp's sacrifice, Berserk's and
    Nettling Imp's destructions, Rakalite's return), "…the controller of the
    permanent it becomes sacrifices it at the beginning of the next cleanup
    step" (Mirage's flash Auras).

    The step that names the mark announced it (``delayed_triggers.
    delayed_mark_events``); this is what it does when it resolves, and it is
    what the step's inline sweep used to do before anybody had priority:

    * **CR 603.7c** — the permanents it names are the ones the mark was on, by
      id; one that left the battlefield is a new object and is not affected.
    * ``if_attacked`` is the printed condition — "destroy that creature **if it
      attacked this turn**" (Berserk, True), "…**if it didn't attack this
      turn**" (Nettling Imp, False) — asked as the ability resolves.
    * ``destroy`` is CR 701.8 (regeneration and indestructible answer it, and
      the cause is this ability's controller, CR 603.7d–e); ``sacrifice`` is
      CR 701.21a, and ``sacrificed_by: "you"`` is the bare imperative — this
      ability's controller sacrifices it, and cannot if they no longer control
      it; ``bounce`` returns it to its owner's hand.

    Several permanents (one effect marked a set, Maddening Imp) leave in one
    event (CR 603.10a).
    """
    payload = instruction.payload
    mark = str(payload.get("mark", ""))
    action = str(payload.get("action", "destroy"))
    when = _MARK_STEPS.get(mark, "end step")
    ids = (context.trigger_context or {}).get(DELAYED_MARK_PERMANENT_IDS) or ()
    victims = [
        permanent for permanent in (game.permanent_by_id(pid) for pid in ids)
        if permanent is not None and game.controller_index_of(permanent) is not None
    ]
    condition = payload.get("if_attacked")
    if condition is not None:
        victims = [
            permanent for permanent in victims
            if bool(permanent.metadata.get("attacked_this_turn")) == bool(condition)
        ]
    if not victims:
        game.log.append(f"{context.card.name}: nothing to {action} at {when}")
        return True, "resolved"
    seat = game.players.index(context.caster) if context.caster in game.players else None
    with game.leaving_together():
        if action == "destroy":
            by_seat: dict[int, list] = {}
            for permanent in victims:
                by_seat.setdefault(game.controller_index_of(permanent), []).append(permanent)
            for controller, doomed in by_seat.items():
                def _on_destroy(permanent, _died) -> None:
                    if mark == "destroy_at_end_of_combat":
                        # "…**if that creature was destroyed this way**"
                        # (Infinite Authority), asked at the next end step: the
                        # destruction is recorded where it happens, not
                        # inferred later from absence.
                        game.destroyed_at_end_of_combat_this_turn.append(
                            permanent.permanent_id
                        )
                    game.log.append(f"{permanent.card.name} was destroyed at {when}")

                game._destroy_swept_permanents(
                    game.players[controller],
                    lambda candidate, doomed=doomed: any(candidate is p for p in doomed),
                    on_destroy=_on_destroy,
                )
        elif action == "sacrifice":
            sacrificing = []
            for permanent in victims:
                controller = game.controller_index_of(permanent)
                if payload.get("sacrificed_by") == "you" and controller != seat:
                    # CR 701.21a: "A player can't sacrifice … a permanent they
                    # don't control" — Sneak Attack's ruling (2020-08-07): "You
                    # sacrifice the creature only if you still control it."
                    game.log.append(
                        f"{context.card.name}: {context.caster.name} doesn't "
                        f"control {permanent.card.name} and can't sacrifice it"
                    )
                    continue
                sacrificing.append((controller, permanent))
            for permanent in game.sacrifice_permanents([p for _c, p in sacrificing]):
                controller = next(c for c, p in sacrificing if p is permanent)
                game.log.append(
                    f"{game.players[controller].name} sacrificed "
                    f"{permanent.card.name} at {when}"
                )
        elif action == "bounce":
            for permanent in victims:
                owner = return_permanent_to_owners_hand(game, permanent)
                game.log.append(
                    f"{permanent.card.name} returned to "
                    f"{owner.name if owner is not None else 'its owner'}'s hand at {when}"
                )
    return True, "resolved"

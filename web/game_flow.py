"""Priority and phase advancement: the game moving forward between
HTTP requests.

:func:`_advance_phase` is the engine of the whole app. It runs the next step's
turn-based actions and keeps going until something has to stop it — a seat that
holds priority, a pending decision, an outstanding combat assignment. The AI
stepping functions sit here rather than in a module of their own because they
are the *same* loop seen from the other side: an AI seat is one that never
stops, so driving it is calling this until a human is owed something.
"""

from __future__ import annotations

from fastapi import HTTPException

from engine.ai_combat import declare_ai_blockers

from engine.ai_actions import cast_announcement, spell_being_cast, zone_being_cast_from
from engine.ai_policy import (
    choose_cast_action,
    choose_combat_instant_cast_action,
)
from engine.ai_abilities import choose_activation_action
from engine.ai_foreign_activations import choose_foreign_activation_action
from engine.ai_hand_activations import choose_hand_activation_action
from engine.ai_graveyard_activations import (
    activate_chosen_graveyard_ability,
    choose_graveyard_activation_action,
)
from engine.ai_payment import tap_planned_lands
from engine.ai_priority import act_at_priority
from engine.ai_special_actions import special_action_before_combat

from .prompts import auto_resolve_ai_prompts
from .session_store import Session

from .seats import (
    _ai_should_hold,
    _hold_priority_for_human,
    _seat_type,
    _self_should_hold,
    _winner,
)
from .turn_steps import (
    _cleanup_discard_requirement,
    _clear_cleanup_selection,
    _finish_beginning_phase,
    _leave_step,
    _resume_deferred_upkeep,
    _start_next_turn,
)
from .combat_prompts import (
    _ai_assign_combat_damage,
    _ai_declare_attackers,
    _ai_resolve_raging_river,
    _band_blocker_assignment_pending,
    _banding_assignment_pending,
    _multiblock_split_pending,
)


def settle_before_observation(session: Session) -> None:
    """Take the decisions the game owes before any client can look at it.

    Both of these lived inside ``_serialize_state``, which meant the function
    named for turning the game into JSON was the function that moved cards
    between players — and so ``GET /state`` was not a read. They are here
    because they are the same family as everything else in this module: an AI
    seat's forced decision, and the game settling once it is over.

    They are *not* simply deletable, which is why this is a move rather than a
    removal. Both are lazy settlements of a transition the game has already
    entered, and the human's next action is gated on the result:

    * **Raging River** — the human's prompt sequencing runs defender-then-attacker,
      so an AI on either side must lock its division before the prompt renders.
      If this only ran on the action path, the prompt the human needs in order
      to act would be the thing waiting on the human to act.
    * **Ante (CR 407.2)** — the engine settles the ante zone itself when a
      state-based action or a concession decides the game. This covers the web
      layer's *own* (Lich-aware) reading of who has lost, which the engine does
      not make.

    Both are idempotent, so calling this on every observation costs nothing
    after the first. That is what lets it sit in front of the serializer rather
    than being threaded through every mutating path and forgotten on one.
    """
    win = _winner(session)
    if win is not None:
        session.status = "finished"
        if win >= 0:
            session.game.award_ante_to_winner(win)

    _ai_resolve_raging_river(session)


def _auto_resolve_ai_pending(session: Session) -> None:
    """Answer every prompt an AI seat owes, with that kind's recorded default.

    One loop over the queue, so a newly registered prompt is covered by
    construction. This was twelve near-identical functions — one per prompt,
    each re-deriving the seat and calling a bespoke resolver — and the two the
    list was missing (Aladdin's Lamp, Ring of Ma'rûf) would have stalled a seat
    handed from a human to the AI. A missing entry does not misbehave; it hangs
    the game on that seat forever.
    """
    auto_resolve_ai_prompts(session.game, lambda seat: _seat_type(session, seat))


def _person_besides(session: Session, seat: int) -> bool:
    """Whether a person sits at the table beside *seat* — the table at which
    an object *seat* puts on the stack is answered by a priority round rather
    than resolved on the spot."""
    return any(
        _seat_type(session, s) == "human"
        for s in range(len(session.game.players))
        if s != seat
    )


def _ai_holds_priority(game, seat: int) -> bool:
    """Whether *seat* may cast or activate now: CR 117.1a lets a player do
    either only while holding priority.

    A seat another one is recorded holding priority for does not. Nobody
    recorded is the active player's window in a step that gives one — except
    where the step's turn-based action is still owed: CR 117.3a gives priority
    in a step "after any turn-based actions … have been dealt with", and in
    the declare attackers and declare blockers steps that action is the
    declaration itself (CR 508.1, 509.1), so until it is made nobody holds
    priority. ``_ai_step`` asked only "does another seat hold it?", so an AI
    in its own declare blockers step, waiting on a person's blocks, activated
    Pemmin's Aura and cycled Shoreline Ranger before a single blocker was
    declared (SCG Phase 5, smoke game 1, turn 11).
    """
    holder = game.priority_player_index
    if holder is not None:
        return holder == seat
    if seat != game.active_player_index or not game._receives_priority(game.current_step):
        return False
    if game.current_turn_phase == "combat":
        if game.current_step == "declare_attackers" and not game.combat_attackers_locked:
            return False
        if game.current_step == "declare_blockers" and not game.combat_blockers_locked:
            return False
    return True


def _hand_priority_round(session: Session, seat: int, result) -> bool:
    """After *seat* acted with priority: when the act put an object on the
    stack, give priority round the table (CR 117.3c: the actor receives it
    again, and passes it on; CR 117.4: the object resolves only once every
    player has passed in succession). True when the round was handed on — the
    AI's step is paused and a person may respond.

    The AI's prompts the announcement owes (a mode, a target) are answered
    first, so the object is whole before anybody is asked about it.
    """
    game = session.game
    _auto_resolve_ai_pending(session)
    if not getattr(result, "supported", False) or not game.stack:
        return False
    game.note_priority_action_taken(seat)
    _run_priority_exchange(session, seat)
    return True


def _doors_spent(session: Session) -> set:
    """The activation doors ``_ai_step`` has gone through in the step the
    game is in (``Session.ai_doors_spent``), reset as the step changes."""
    game = session.game
    where = (game.turn, game.current_turn_phase, game.current_step)
    if not session.ai_doors_spent or session.ai_doors_spent[0] != where:
        session.ai_doors_spent = (where, set())
    return session.ai_doors_spent[1]


def _ai_step(session: Session) -> bool:
    """Run one AI action for the current turn.

    Returns True when the AI has nothing more to do this turn (caller should end
    the turn).  Returns False when the AI put an object on the stack and passed
    priority to a human opponent — the turn must NOT be ended yet; the human
    must act first.

    **Every door that puts an object on the stack hands priority round** at a
    table with a person (``_hand_priority_round``): the cast, an ability of a
    permanent (its own or another seat's), of a card in hand (cycling), of a
    card in the graveyard, and a special action whose consequence triggered
    (turning a face-down creature face up). The cast alone did, through
    ``queue_from_hand``; the four activation doors called the engine and
    settled at once, so Pemmin's Aura's untap, Gilded Light's and Eternal
    Dragon's cycling resolved on the AI's turn with nobody passing
    (CR 117.3c, 117.4).
    """
    seat = session.current_turn
    game = session.game

    _auto_resolve_ai_pending(session)

    has_human_opponent = _person_besides(session, seat)

    if game.priority_player_index is not None and game.priority_player_index != seat:
        return False
    # Nobody holds priority while a declaration is owed (CR 117.3a, 508.1,
    # 509.1): nothing to do in this request; the caller's advance makes the
    # declaration or waits for the person who owes it.
    if not _ai_holds_priority(game, seat):
        return True

    # **The seat's own upkeep is a priority window it answers**, for an
    # ability of a card in its graveyard ("Activate only during your
    # upkeep": Hammer of Bogardan, Necrosavant): the upkeep stopped here for
    # it (`turn_steps._resolve_upkeep_step`), and the answer is the
    # simulator's own (`engine.ai_priority`). Nothing the main phase plays is
    # played here; with nothing done, the step is left.
    if game.current_turn_phase == "beginning" and game.current_step == "upkeep":
        return not _ai_answer_priority(session, seat)

    # **An object on the stack and the AI holding priority over it** — its own
    # trigger, or what a resolution left: the seat answers priority as the
    # exchange answers it (`engine.ai_priority.act_at_priority`, which lets
    # the seat's own object resolve) and passes, so the person beside it is
    # asked before anything resolves (CR 117.3d, 117.4). Nothing a main phase
    # plays is played over a stack; the step's advance used to drain it.
    if game.stack and has_human_opponent:
        if game.priority_player_index is None:
            game.start_priority_window(seat)
        act = act_at_priority(game, seat)
        if act is not None and act.supported:
            game.note_priority_action_taken(seat)
        _auto_resolve_ai_pending(session)
        _run_priority_exchange(session, seat)
        return False

    # choose_cast_action covers sorcery-speed plays (enchantments, sorceries,
    # creatures, artifacts, lands), which are legal only during the active player's
    # main phase with an empty stack. Without this guard the AI would, e.g., drop an
    # enchantment during the combat damage step. Instants are handled separately via
    # _ai_respond_to_priority / the declare-blockers window.
    sorcery_speed_ok = (
        game.active_player_index == seat
        and game.current_step in ("precombat_main", "postcombat_main")
        and not game.stack
    )
    # **Anywhere but the seat's own main phase with an empty stack, the AI
    # answers priority the way every AI seat handed priority does**
    # (`engine.ai_priority.act_at_priority`: an instant or a flash spell, an
    # ability at instant speed, an ability of a card in its graveyard — each
    # in the moments `instant_speed_window` names), and an object it puts on
    # the stack goes round the table like any other. The main phase's doors
    # below are the main phase's: asked in combat, their battlefield chooser
    # passed over every tapped permanent, so the AI's blocked attacker never
    # regenerated (Krosan Warchief, smoke game 2), and nothing cast the active
    # AI's combat trick after a person's blocks (CR 509.2 gives it priority
    # first). This is the simulator's answer in the same windows.
    if not sorcery_speed_ok:
        act = act_at_priority(game, seat)
        if act is not None and act.supported:
            game.note_priority_action_taken(seat)
            _auto_resolve_ai_pending(session)
            if has_human_opponent and game.stack:
                _run_priority_exchange(session, seat)
                return False
        return True

    cast_action = choose_cast_action(game, seat) if sorcery_speed_ok else None
    if cast_action is not None:
        # `hand_index` indexes the zone `from_zone` names — the hand, the
        # command zone for a commander cast (CR 903.8), or a graveyard, an
        # exile or a library an effect has opened (CR 601.3: a flashback card)
        # — through the one reader the simulator's executor shares.
        cast_zone = zone_being_cast_from(game, seat, cast_action)
        # The spell the policy chose, which for a split card is one half of
        # the zone's card (CR 709.3) — see `ai_actions.spell_being_cast`.
        card_to_cast = spell_being_cast(cast_zone, cast_action)
        # The payment, through the executor the AI simulator shares
        # (`engine.ai_payment.tap_planned_lands`): each planned land tapped for
        # the colour the plan counted on, by the mana ability that makes it.
        # What comes back is the action as it reads once paid for: a source
        # sacrificed for mana renumbers the slots the announcement names.
        cast_action = tap_planned_lands(game, seat, cast_action)

        # The announcement, whole, through the one function that turns a
        # `CastAction` into a cast (`engine.ai_actions.cast_announcement`): the
        # seat and the object, X, the alternative cost (CR 118.9), the
        # division (CR 601.2d), the optional costs and the **mode**
        # (CR 601.2b). Each executor in this file spelled those out for itself
        # and they had drifted — the two instant executors below forwarded
        # neither an optional cost nor an alternative one — which is how a
        # mode would have reached two of the four.
        if has_human_opponent:
            result = game.queue_from_hand(
                seat, card_to_cast.name, **cast_announcement(cast_action),
            )
            if result.supported:
                game.note_priority_action_taken(seat)
                # NOTE (frontend FFA pass): route through the priority-exchange
                # cascade rather than a bare engine pass. In a 3+ player (FFA)
                # game, the seat right after `seat` in turn order may be a
                # second AI player rather than the human — only this cascade
                # (already used by the "pass_priority" action handler) drives
                # that seat's response instead of stalling with priority stuck
                # on an AI seat no client action can ever advance.
                _run_priority_exchange(session, seat)
                return False  # paused — human has priority over the spell on the stack
        else:
            game.cast_from_hand(
                seat, card_to_cast.name, **cast_announcement(cast_action),
            )
            _auto_resolve_ai_pending(session)

    # The activation doors below take the engine's **queue** form at a table
    # with a person — the object stays on the stack and priority goes round
    # (`_hand_priority_round`) — and the settling form at a table of AI seats
    # alone, which nobody is asked at. `activate_from_hand` and
    # `activate_from_graveyard` are queue forms at every table.
    activate = (
        game.queue_permanent_ability if has_human_opponent
        else game.activate_permanent_ability
    )

    # Each door once in a step (`_doors_spent`): a door that paused for the
    # round is not asked again when the next `ai_step` comes back to this one.
    spent = _doors_spent(session)

    activation_action = (
        choose_activation_action(game, seat) if "battlefield" not in spent else None
    )
    if activation_action is not None:
        spent.add("battlefield")
        activation_action = tap_planned_lands(game, seat, activation_action)
        result = activate(
            seat,
            activation_action.permanent_name,
            target_player_index=activation_action.target_player_index,
            permanent_index=activation_action.permanent_index,
            target_permanent_index=activation_action.target_permanent_index,
            target_role_refs=activation_action.target_role_refs,
            cost_hand_index=activation_action.cost_hand_index,
            # The word a "Choose flying, …" cost announces, when the policy
            # named one (Phyrexian Splicer, `ai_abilities._keyword_walk_order`).
            chosen_keyword=activation_action.chosen_keyword,
            # A land's non-mana ability by its index; None (the engine's
            # first) for everything else — see `ai_abilities._abilities_weighed`.
            ability_index=activation_action.ability_index,
            # The X an "{X}…:" cost announces, when the policy sized one.
            x_value=activation_action.x_value,
        )
        if has_human_opponent and _hand_priority_round(session, seat, result):
            return False
        _auto_resolve_ai_pending(session)

    # An ability activated from the seat's **hand** (CR 113.6j) — cycling. The
    # engine's other activation entry point, so it is a second pass rather than
    # a branch in the one above; after it, so the lands the payment is planned
    # against are the ones the cast and the battlefield activation left alone.
    hand_activation = (
        choose_hand_activation_action(game, seat) if "hand" not in spent else None
    )
    if hand_activation is not None:
        spent.add("hand")
        hand_activation = tap_planned_lands(game, seat, hand_activation)
        result = game.activate_from_hand(
            seat,
            hand_activation.card_name,
            ability_index=hand_activation.ability_index,
            hand_index=hand_activation.hand_index,
        )
        if has_human_opponent and _hand_priority_round(session, seat, result):
            return False
        _auto_resolve_ai_pending(session)

    # An ability activated from the seat's **graveyard** (CR 113.6b/m) — the
    # engine's third activation door, through the chooser and the executor
    # the simulator shares (`engine.ai_graveyard_activations`). Until the kg3
    # round no AI seat used one: a Whiteout or a Glory in an AI's graveyard
    # stayed there.
    graveyard_activation = (
        choose_graveyard_activation_action(game, seat) if "graveyard" not in spent else None
    )
    if graveyard_activation is not None:
        spent.add("graveyard")
        result = activate_chosen_graveyard_ability(game, seat, graveyard_activation)
        if has_human_opponent and _hand_priority_round(session, seat, result):
            return False
        _auto_resolve_ai_pending(session)

    # An ability on a permanent **another seat controls** that this one may
    # activate (CR 602.1b, "Any player may activate this ability") — a human's
    # Volrath's Dungeon, Ribbon Snake or Task Mage Assembly. Last, so it spends
    # only mana the seat's own plays left. The permanent is counted into its
    # controller's battlefield (`source_controller_index`); the lands are the
    # activator's.
    foreign_activation = (
        choose_foreign_activation_action(game, seat) if "foreign" not in spent else None
    )
    if foreign_activation is not None:
        spent.add("foreign")
        foreign_activation = tap_planned_lands(game, seat, foreign_activation)
        result = activate(
            seat,
            foreign_activation.permanent_name,
            target_player_index=foreign_activation.target_player_index,
            permanent_index=foreign_activation.permanent_index,
            target_permanent_index=foreign_activation.target_permanent_index,
            ability_index=foreign_activation.ability_index,
            source_controller_index=foreign_activation.source_controller_index,
        )
        if has_human_opponent and _hand_priority_round(session, seat, result):
            return False
        _auto_resolve_ai_pending(session)

    # A CR 116.2d offer that buys one of the seat's creatures its attack this
    # turn (Volrath's Curse, Lost in Thought), or turning a face-down creature
    # face up (CR 116.2b) — a special action, taken with priority and before
    # combat, through the chooser and the executor the simulator shares
    # (`engine.ai_special_actions`). The chooser asks only in the seat's own
    # main phase with its combat ahead. A special action uses no stack
    # (CR 116.1), but what it sets off does ("When this creature is turned
    # face up", CR 702.37e): CR 116.3 gives the seat priority again, and the
    # trigger is answered by a round like any other object.
    taken = special_action_before_combat(game, seat) if "special" not in spent else None
    if taken is not None:
        spent.add("special")
        _choice, refusal = taken
        if has_human_opponent and refusal is None and game.stack:
            _auto_resolve_ai_pending(session)
            game.note_priority_action_taken(seat)
            _run_priority_exchange(session, seat)
            return False
        _auto_resolve_ai_pending(session)

    return True


def _ai_respond_to_priority(session: Session, seat: int) -> str | None:
    """An AI seat handed priority by the exchange: the simulator's answer to
    priority (`engine.ai_priority.act_at_priority` — its windows, its
    choosers, each one's executor: an instant, an ability at instant speed,
    an ability of a card in the graveyard), then a pass.

    This was a copy of a third of that answer: it cast an instant whenever
    it was handed priority, in any step, and never activated anything — so
    no web AI seat used a regeneration shield in front of a burn spell, a
    Glory in its graveyard, or Swooping Talon's toggle (CLAUDE.md: the
    simulator plays the engine's turn, never a copy of it)."""
    game = session.game
    if not game.has_priority(seat):
        return None

    act = act_at_priority(game, seat)
    if act is not None and act.supported:
        game.note_priority_action_taken(seat)

    if game.has_priority(seat):
        return game.pass_priority(seat)
    return None


def _ai_answer_priority(session: Session, seat: int) -> bool:
    """The active AI seat's answer to its own priority (its upkeep): what
    `engine.ai_priority.act_at_priority` does, put on the stack and handed
    round the table (`_run_priority_exchange`) so a human may respond before
    it resolves. True when something went on the stack."""
    act = act_at_priority(session.game, seat)
    if act is None or not act.supported:
        return False
    session.game.note_priority_action_taken(seat)
    _run_priority_exchange(session, seat)
    return True


def _round_over_ai_objects(session: Session, seat: int) -> bool:
    """After the AI seat *seat*'s turn-based action (its attack declaration)
    set off its triggers at a table with a person: priority to *seat*
    (CR 508.2), which passes it on, so the person is asked over the objects
    before they resolve (CR 117.4). True when the round was handed on — the
    caller stops, and the step is left once every player has passed with the
    stack empty (CR 500.2)."""
    game = session.game
    if _seat_type(session, seat) != "ai" or not _person_besides(session, seat):
        return False
    _auto_resolve_ai_pending(session)
    if not game.stack:
        return False
    if game.priority_player_index is None:
        game.start_priority_window(seat)
    if game.priority_player_index != seat:
        return False
    _run_priority_exchange(session, seat)
    return True


def _round_from_the_active_player(session: Session) -> None:
    """Start the priority round of a step whose declaration has just been
    made, with the active player (CR 509.2): a person holding it is asked by
    their client; an AI answers it as every AI seat handed priority does and
    passes it on (`_run_priority_exchange`)."""
    game = session.game
    active = game.active_player_index
    _auto_resolve_ai_pending(session)
    if game.priority_player_index is None:
        game.start_priority_window(active)
    if _seat_type(session, active) != "ai" or not game.has_priority(active):
        return
    act = act_at_priority(game, active)
    if act is not None and act.supported:
        game.note_priority_action_taken(active)
    _run_priority_exchange(session, active)


def _auto_advance_after_all_passed(session: Session, pass_result: str | None) -> None:
    if pass_result != "all_passed_empty":
        return

    # A decision somebody still owes holds the turn where it is. An AI seat's
    # prompts were answered by _auto_resolve_ai_pending before this ran, so what
    # is left is a human's — and advancing the step past it would resolve it
    # into a board that has already moved on. This named Word of Command alone,
    # which was the only prompt anyone had been bitten by; the rest of the queue
    # is the same fact about a different card. A prompt that blocks nothing
    # (``hand_reveal``) is a notification and holds nothing, which is what
    # ``holds_priority`` says.
    if session.game.waiting_prompt() is not None:
        return

    # Advance turn structure automatically after both players pass with an empty stack.
    _advance_phase(session)


def _run_priority_exchange(session: Session, acting_seat: int) -> None:
    result = session.game.pass_priority(acting_seat)

    while True:
        _auto_resolve_ai_pending(session)
        _auto_advance_after_all_passed(session, result)

        if result == "awaiting_choice":
            # The resolution stopped to ask somebody something, so nobody has
            # priority until they answer (CR 117.3b) and the object stays on the
            # stack. An AI chooser's prompt was answered by
            # _auto_resolve_ai_pending above — the object has left the stack —
            # so priority can go round again on its behalf. A human's is still
            # owed: stop here and surface it. Asking the queue rather than the
            # optional-pay list is what makes that true of the search, the
            # discard and the mode choice as well.
            chooser = session.game.priority_player_index
            still_owed = chooser is not None and session.game.waiting_prompt(chooser)
            if not still_owed and chooser is not None and _seat_type(session, chooser) == "ai":
                result = session.game.pass_priority(chooser)
                continue
            break

        ai_priority_seat = session.game.priority_player_index
        if (
            result == "passed"
            and ai_priority_seat is not None
            and _seat_type(session, ai_priority_seat) == "ai"
            and (ai_priority_seat != session.current_turn or bool(session.game.stack))
        ):
            result = _ai_respond_to_priority(session, ai_priority_seat)
            continue

        break


def _advance_ai_turn(session: Session) -> None:
    """Advance the AI's turn through its non-main steps after it has finished acting
    in the current step.

    Pauses to hand a human priority at any step they flagged on the phase rail. Stops
    when a new main phase begins (so the AI can cast there on the next step), when the
    turn ends, or when human input is required (e.g. declaring blockers).
    """
    for _safety in range(20):
        game = session.game
        step = game.current_step

        # **An AI step never advances a human's turn**, and the place that is
        # true by construction is here rather than at each caller. This loop
        # read `prev_turn` below, *inside* itself, so a caller that had already
        # crossed the turn boundary handed it the next player's precombat main
        # phase and it walked that into combat: `ai_step` at the AI's end step
        # (reached whenever the human passed priority in the AI's second main
        # phase) did exactly that, and the human's turn began at Declare
        # Attackers. The caller now checks the turn it stepped as well, which
        # is the precise statement for two AI seats in a row; this is the
        # backstop no later caller can forget.
        if _seat_type(session, session.current_turn) != "ai":
            return
        if game.is_game_over():
            return

        if _ai_should_hold(session, step):
            # Resolve the active player's turn-based action (declaring attackers)
            # before handing priority to the human.
            if step == "declare_attackers":
                _ai_declare_attackers(session)
            if _hold_priority_for_human(session):
                return

        prev_turn = session.current_turn
        prev_phase = game.current_turn_phase
        prev_step = step
        _advance_phase(session)

        if session.current_turn != prev_turn:
            return  # the AI's turn has ended
        if (
            session.game.current_turn_phase == prev_phase
            and session.game.current_step == prev_step
        ):
            return  # stuck waiting for human input (e.g. declare blockers)
        # Stop at a main phase so the AI casts there (driven by the next ai_step).
        if session.game.current_step in ("precombat_main", "postcombat_main"):
            return


def _advance_phase(session: Session) -> None:
    game = session.game
    # A decision somebody still owes holds the turn structure where it is.
    # AI seats answer theirs with the kind's default first, so what is left is
    # a human's — and advancing past it would resolve it into a board that has
    # already moved on. This named Word of Command by hand while
    # _auto_advance_after_all_passed asked the queue, and the AI-turn path
    # (_advance_ai_turn) reaches here without passing through that function:
    # an AI's Mind Rot resolved, the human's discard was armed, and the turn
    # walked on. Word of Command's own ``is_open`` reproduces the old
    # "chosen, but not yet finished" distinction.
    _auto_resolve_ai_pending(session)
    if game.waiting_prompt() is not None:
        return
    # CR 104.1: a game that has ended goes no further. The engine's rail stops
    # on its own; this is the web layer's turn loop stopping with it, rather
    # than walking an ended game into its end step and the next turn.
    if game.is_game_over():
        return
    phase = game.current_turn_phase
    step = game.current_step

    if phase == "beginning" and step in ("upkeep", "draw"):
        # The phase-rail upkeep window has closed — resolve the upkeep itself now,
        # prompting for the trigger decisions deliberately deferred past it. Runs
        # before close_beginning_step so the step's own end (which empties mana
        # pools, CR 500.5) doesn't strand mana the player floated to pay with.
        if step == "upkeep" and session.upkeep_decisions_deferred:
            _resume_deferred_upkeep(session, session.current_turn)
            return
        # Resume after a held upkeep/draw step on the AI's turn: close it and move on,
        # holding again at the draw step if the human flagged it.
        if not _leave_step(session, game.close_beginning_step):
            return
        # The draw step, through the one function that runs it for every
        # road (`turn_steps._finish_beginning_phase`): Island Sanctuary's
        # question, Nafs Asp's answers, the phase-rail holds — and **the draw
        # step's own window**, which can stop on a question (a draw trigger's
        # "you may", CR 608.2). This branch was a copy of that function
        # without its last check, so a draw-step trigger still owed its
        # answer was carried into the main phase on the stack (CR 500.2).
        if step == "upkeep":
            _finish_beginning_phase(session, session.current_turn)
            return
        game.enter_next_turn_phase("beginning")
        return

    if phase == "precombat_main":
        # Left the engine's way, so a question its window stops on holds the
        # phase (CR 608.2) — see `_leave_step`.
        if not _leave_step(session, game._close_current_priority_step):
            return
        # The turn's plan decides, not this line: normally the combat phase, but
        # an effect resolved during this main phase may have added one after it
        # (CR 500.8 - Relentless Assault).
        game.enter_next_turn_phase("precombat_main")
        _clear_cleanup_selection(session)
        return
    if phase == "combat":
        if (
            step == "combat_damage"
            and not game.combat_damage_resolved
            and _seat_type(session, game.active_player_index) == "ai"
        ):
            # No human is assigning damage for the active AI. Resolve combat damage
            # with a sensible default assignment so a multi-blocked attacker (which
            # the engine defers for manual assignment) doesn't deadlock the step.
            _ai_assign_combat_damage(session)
        elif (
            step == "combat_damage"
            and not game.combat_damage_resolved
            and _seat_type(session, game.active_player_index) == "human"
            and game._needs_manual_damage_assignment()
            and not game._manual_assignment_has_declared_multiblock()
            and not _banding_assignment_pending(session)
            and not _band_blocker_assignment_pending(session)
            and not _multiblock_split_pending(session)
        ):
            # A human attacker declared a band whose block propagated to a single
            # shared blocker (CR 702.22h), but no band member has banding to route
            # (so there is no CR 702.22k choice) — auto-resolve a sensible default
            # instead of looping forever waiting for an assignment that can't arrive.
            # When there IS a 702.22k choice, _band_blocker_assignment_pending keeps
            # this from firing so the active player's dialog can resolve it instead.
            auto = game._build_auto_damage_assignment()
            game.resolve_all_combat_damage(game.active_player_index, attacker_damage=auto)
        if step == "declare_attackers" and not game.combat_attackers_locked:
            _ai_declare_attackers(session)
            # The AI's declaration set off its attack triggers: CR 508.2
            # gives the active player priority, and the objects resolve only
            # once every player has passed (CR 117.4) — so the person is
            # asked over them rather than the step's window draining them.
            if _round_over_ai_objects(session, game.active_player_index):
                return
        if step == "declare_blockers":
            combat_state = game.get_combat_state()
            # CR 802.4: with 2+ defending players (FFA), each declares in APNAP
            # order — _pending_block_declarer() names whichever one is up next,
            # not a single fixed defender.
            defender_index = game._pending_block_declarer()
            # CR 509.1a's chooser, which is the defending player unless "You
            # choose which creatures block this combat" (Melee) moved it. The
            # *declaration* is still the defender's — the engine keeps taking it
            # under their seat — so only the seat that has to be prompted
            # changes, and that is the seat whose kind decides whether the AI
            # answers here or the rail waits for a person.
            chooser_index = (
                game.block_chooser_index(defender_index)
                if isinstance(defender_index, int) else None
            )
            if isinstance(defender_index, int) and _seat_type(session, chooser_index) == "ai":
                if not combat_state.get("blockers_locked", False):
                    # **The declaration and its fallback chain live in
                    # `engine/ai_combat.py`**, the way the attack side's have
                    # since W2G4 and for the same reason: the AI simulator makes
                    # the same declaration, a refused one is silent — nothing
                    # spent, no rule broken, the defender simply does not block
                    # — and a second copy of the chain here would be a second
                    # place for that silence to live. It was one, and what it
                    # hid was every declaration-wide block restriction the
                    # chooser could not see (Caverns of Despair, Orcish
                    # Conscripts, Mogg Flunkies, Okk). Camouflage is routed
                    # inside it, because the pile resolution is that same
                    # declaration replaced (CR 509.1a).
                    ok = declare_ai_blockers(game, defender_index)
                    if not ok:
                        # Safety valve: never let AI declaration failures deadlock combat progression.
                        game.combat_blockers = {}
                        game.combat_blockers_locked = True
                        game._prune_combat_state()
                    # The declaration may have been made *for* this seat by
                    # another (Melee). Casting an instant afterwards is the
                    # defender's own priority action, so it is offered only to
                    # an AI defender — reaching for a human's hand because an
                    # AI chose their blocks would be the substitution spilling
                    # past the one decision the card moves.
                    instant_action = (
                        choose_combat_instant_cast_action(game, defender_index)
                        if _seat_type(session, defender_index) == "ai" else None
                    )
                    # **At a table with a person, the defender's trick and
                    # its block triggers wait for priority.** CR 509.2 gives
                    # the *active* player priority once blockers are
                    # declared; the defender casts when it is handed
                    # priority in turn (CR 117.3d), and a block trigger
                    # resolves once every player has passed (CR 117.4). The
                    # instant was cast here through ``cast_from_hand`` — a
                    # settling cast, by a seat that did not hold priority —
                    # and the triggers were drained by the step's window:
                    # neither ever gave the person a pass. Now the round
                    # starts with the active player, and the defender's
                    # answer is the one every AI seat gives when handed
                    # priority (``_ai_respond_to_priority``).
                    if (instant_action is not None or game.stack) and _person_besides(
                        session, defender_index
                    ):
                        _round_from_the_active_player(session)
                        return
                    if instant_action is not None:
                        card_to_cast = spell_being_cast(
                            zone_being_cast_from(
                                game, defender_index, instant_action
                            ),
                            instant_action,
                        )
                        instant_action = tap_planned_lands(
                            game, defender_index, instant_action
                        )
                        game.cast_from_hand(
                            defender_index, card_to_cast.name,
                            **cast_announcement(instant_action),
                        )
                        return
                    # CR 509.2: declaring blockers opened a priority window for the
                    # active player. When a human attacker flagged the declare-blockers
                    # stop on the phase rail, hold here so they can respond to the
                    # blocks (combat tricks, block triggers on the stack) instead of
                    # skipping straight to combat damage; the client advances again
                    # once they pass priority or hit Next Phase.
                    if (
                        game.combat_attackers
                        and game.priority_player_index is not None
                        and _self_should_hold(session, "declare_blockers")
                    ):
                        return
        # CR 510.4: the combat-damage step opens a priority window after damage is
        # dealt. The engine normally auto-resolves that window and skips straight to
        # end-of-combat when no manual damage assignment is needed — which silently
        # ignores a combat_damage stop flagged on the phase rail. When either the
        # active human (self) or a human opponent flagged it, tell the engine to hold
        # the step open instead of skipping.
        hold_damage = _self_should_hold(session, "combat_damage") or _ai_should_hold(
            session, "combat_damage"
        )
        # Through `_leave_step`: a step whose window stopped on an AI seat's
        # question is answered and left in this request, and one that stopped
        # on a human's waits here for the answer (CR 608.2, CR 500.2).
        _leave_step(
            session,
            lambda: game.advance_combat_phase(allow_damage_skip=not hold_damage),
        )
        # On the AI's turn the engine leaves priority with the active AI; hand it to
        # the human so they can act at the step they flagged (mirrors the upkeep/draw
        # and declare-blockers holds). On the human's own turn the active player is
        # already the human, so this is a no-op.
        if (
            hold_damage
            and game.current_turn_phase == "combat"
            and game.current_step == "combat_damage"
            and game.combat_damage_resolved
            and _seat_type(session, game.active_player_index) != "human"
        ):
            _hold_priority_for_human(session)
        return
    if phase == "postcombat_main":
        if not _leave_step(session, game._close_current_priority_step):
            return
        # Normally the ending phase; an extra combat phase added after this one
        # (CR 500.8) is entered here instead of being recorded and lost.
        game.enter_next_turn_phase("postcombat_main")
        _clear_cleanup_selection(session)
        return
    if step == "end":
        if not _leave_step(session, game.close_end_step):
            return
        should_defer_cleanup = _seat_type(session, session.current_turn) == "human"
        cleanup_completed = game.resolve_cleanup_step(
            session.current_turn,
            defer_discard_selection=should_defer_cleanup,
        )
        if not cleanup_completed:
            session.cleanup_required_discards = _cleanup_discard_requirement(session)
            session.cleanup_selected_indices = []
            return
        _start_next_turn(session)
        return
    if step == "cleanup":
        if _cleanup_discard_requirement(session) > 0:
            raise HTTPException(status_code=400, detail="select cleanup discards before advancing")
        _start_next_turn(session)
        return

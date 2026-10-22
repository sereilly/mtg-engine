"""What a declaration of attackers or blockers must, may not, or must pay to
include (CR 508.1c-d and h, CR 509.1b-d), as resolving effects arm it.

The handler side of three grammar families: ``lowering/requirements.py`` (the
"attacks / blocks … if able" requirements, and the end-step destruction of a
creature that did not attack), ``lowering/prohibitions.py`` ("can't be
blocked", "can't be blocked by …") and the restrictions and permissions
``lowering/combat.py`` lowers ("can't attack / block", "can block any number",
"can block an additional creature", "attacks as though it didn't have
defender", "attacking doesn't cause it to tap"), plus the turn-scoped
declaration tolls of ``lowering/_declaration_costs.py``. Each handler only
**arms** a mark: nothing is declared when one resolves, and the declare
attackers and declare blockers steps are what read the marks back.

Split out of ``combat.py`` at the 2,000-line cap's split round. ``combat.py``
keeps a combat already under way — who is in it, who is blocked, and how its
damage is assigned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._targets import (recorded_permanent_ids, attached_host, bound_permanent,
                       names_a_target_list as _names_a_list,
                       resolve_target_permanent, resolve_target_permanents)
from .registry import effect_handler
from ..destruction_events import mark_delayed_destruction
from ..mana_payment import mana_cost_label
from ..combat_permissions import (ADDITIONAL_BLOCKS_UNTIL_EOT,
                                  CAN_BLOCK_ANY_NUMBER_UNTIL_EOT,
                                  MUST_BLOCK_ALL_UNTIL_EOT,
                                  MUST_BLOCK_ATTACKERS_UNTIL_EOT,
                                  ATTACK_AS_THOUGH_NO_DEFENDER,
                                  CANT_ATTACK_UNTIL_EOT,
                                  CANT_BLOCK_ATTACKERS_UNTIL_EOT,
                                  MUST_BLOCK_UNTIL_EOT,
                                  CANT_BLOCK_UNTIL_EOT)
from ..turn_state import (CANT_ATTACK_ON_SEAT_TURN_KEY,
                          THAT_PLAYERS_NEXT_TURN,
                          DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY,
                          MUST_ATTACK_ON_SEAT_TURN_KEY,
                          seats_next_turn_window)

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent
    from ..oracle import OracleInstruction


@effect_handler("cant_attack_during_controllers_next_turn")
def cant_attack_during_controllers_next_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Wall of Dust: "Whenever this creature blocks a creature, that creature
    can't attack during its controller's next turn."

    "That creature" is the blocked attacker, resolved by the stable ids the
    blocks fire site recorded on the trigger (CR 509.3f fixed the set at
    declaration; an id that no longer resolves is a creature that left, and a
    creature that returns is a new object the sentence never named — CR 400.7).
    The stamp names the creature's controller *as the trigger resolves* and
    that seat's next turn ordinal; ``can_attack`` refuses exactly while that
    turn is the current one, and a later turn walks past the stamp with
    nothing to sweep.
    """
    stamped = []
    for permanent_id in (context.trigger_context or {}).get("blocked_permanent_ids") or ():
        perm = game.permanent_by_id(permanent_id)
        if perm is None:
            continue
        seat = game.controller_index_of(perm)
        if seat is None:
            continue
        perm.metadata[CANT_ATTACK_ON_SEAT_TURN_KEY] = seats_next_turn_window(
            game, seat
        )
        stamped.append((perm, seat))
    if stamped:
        for perm, seat in stamped:
            game.log.append(
                f"{perm.card.name} can't attack during "
                f"{game.players[seat].name}'s next turn ({context.card.name})"
            )
    else:
        game.log.append(f"{context.card.name} block trigger found no blocked creature")
    return True, "resolved"


@effect_handler("grant_unlimited_blocking")
def grant_unlimited_blocking(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Blaze of Glory: "Target creature defending player controls can block any number
    # of creatures this turn. It blocks each attacking creature this turn if able."
    # Honor the chosen creature; fall back to the first only for AI/headless play.
    card = context.card
    blocker = resolve_target_permanent(game, context)
    if blocker is not None:
        # Lets it block any number of attackers (_max_blocks_for) and requires it to
        # block each attacker it can (enforced when blocks are declared).
        blocker.metadata[CAN_BLOCK_ANY_NUMBER_UNTIL_EOT] = True
        blocker.metadata[MUST_BLOCK_ALL_UNTIL_EOT] = True
        game.log.append(f"{card.name}: {blocker.card.name} can block any number of creatures this turn")
    else:
        game.log.append(f"{card.name} found no creature to grant unlimited blocking")
    return True, "resolved"


def forced_attacker_is_legal(game: Game, permanent: Permanent) -> bool:
    """Whether *permanent* is the creature this template may name: "target
    non-Wall creature **the active player has controlled continuously since the
    beginning of the turn**" (Nettling Imp, Norritt, Arcum's Whistle).

    Every clause narrows, and each was being dropped. The seat is the active
    player's, because the card exists to make somebody attack on *their* turn;
    the continuity is what keeps a creature that arrived this turn out, which is
    the difference between this and Siren's Call. Read off
    ``summoning_sickness_turn`` — the same record ``Game.can_attack`` asks —
    rather than a second one, because a permanent that entered this turn is
    exactly a permanent its controller has not had since the turn began.

    One reader, asked by the handler that marks the creature and by the legality
    gate that offers the picker its candidates, so the list a player is shown
    and the list the engine accepts cannot differ.
    """
    if not permanent.is_creature or permanent.has_type("wall"):
        return False
    if game.controller_index_of(permanent) != game.active_player_index:
        return False
    return permanent.metadata.get("summoning_sickness_turn") != game.turn


@effect_handler("mark_non_wall_target_to_attack")
def mark_non_wall_target_to_attack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose target non-Wall creature the active player has controlled
    continuously since the beginning of the turn. That creature attacks this
    turn if able. Destroy it at the beginning of the next end step if it didn't
    attack this turn."

    **The chosen creature**, which this used to ignore: it scanned the target
    player's battlefield and marked the first non-Wall creature it found, so a
    player who picked the Hill Giant got the Grizzly Bears marked instead. The
    card said "choose target" and the engine chose for them.
    """
    chosen = resolve_target_permanent(
        game, context,
        predicate=lambda perm: forced_attacker_is_legal(game, perm),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        game.log.append(f"{context.card.name}: no legal creature to force into combat")
        return True, "resolved"
    chosen.metadata["must_attack_until_eot"] = True
    mark_delayed_destruction(game, chosen, "destroy_if_did_not_attack_eot")
    game.log.append(f"{chosen.card.name} marked to attack this turn")
    return True, "resolved"


@effect_handler("force_target_to_attack_until_eot")
def force_target_to_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature attacks this turn if able." (Boiling Blood.)

    CR 508.1a's requirement for one turn on the creature the caster chose
    (CR 601.2c), through the same ``must_attack_until_eot`` mark
    ``declare_attackers_step`` already reads — so "if able" keeps meaning what
    it means everywhere else and a creature that cannot legally attack simply
    does not.

    No destroy rider. The sibling kind one function up (Nettling Imp's) carries
    one because *its* card prints one, and folding the two would have made this
    spell kill a creature that stayed home.

    The printed noun phrase is re-asked here, not only at announcement: a target
    that stopped being a creature between the two is no longer the thing the
    card names (CR 608.2b), and asking it through ``subject_matches`` is what
    keeps the picker's list and this resolution's one list.
    """
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    chosen = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        game.log.append(
            f"{context.card.name}: its target is gone (608.2b)"
        )
        return True, "resolved"
    chosen.metadata["must_attack_until_eot"] = True
    game.log.append(f"{chosen.card.name} must attack this turn if able")
    return True, "resolved"


@effect_handler("force_bound_to_attack_until_eot")
def force_bound_to_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This artifact deals 1 damage to target creature. **That creature**
    attacks this turn if able." (Bullwhip.)

    The same CR 508.1d requirement as the targeted kind above, on the object an
    earlier step of this resolution already acted on rather than on a second
    choice. ``bound_permanent`` is the reader every "that creature" goes
    through, so a requirement inside a loop names the iteration's object and one
    outside it names the ability's own target (CR 601.2c) -- and no picker is
    involved either way, which is the whole difference from the kind above.

    No noun phrase is re-tested: the sentence in front of this one already found
    the creature, and asking again would be a second reading of one choice.
    Whether it is still a creature is the requirement's own business -- the mark
    means nothing on a permanent that cannot attack, and "if able" is what makes
    that harmless.
    """
    chosen = bound_permanent(game, context)
    if chosen is None:
        game.log.append(
            f"{context.card.name}: nothing left for the attack requirement"
        )
        return True, "resolved"
    chosen.metadata["must_attack_until_eot"] = True
    game.log.append(f"{chosen.card.name} must attack this turn if able")
    return True, "resolved"


@effect_handler("force_bound_to_block_until_eot")
def force_bound_to_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Untap target creature you don't control. **That creature blocks this
    turn if able.**" (Provoke.)

    CR 509.1c's weakest requirement, for one turn, on the creature the sentence
    in front of this one untapped: block *something* it legally can. The
    narrowed kind below records **which** attacker is owed; this one records
    only that a block is, which is why it is a flag rather than a list -- there
    is no pair here, and an empty list would compel nobody.

    ``bound_permanent`` is the reader every "that creature" goes through, so
    the pronoun means the ability's own target outside a loop and the
    iteration's object inside one, and no picker is involved either way.

    Nothing is re-tested: the untap in front of it already found the creature,
    and "if able" is what makes the mark harmless on one that cannot block.
    """
    chosen = bound_permanent(game, context)
    if chosen is None:
        game.log.append(
            f"{context.card.name}: nothing left for the block requirement"
        )
        return True, "resolved"
    chosen.metadata[MUST_BLOCK_UNTIL_EOT] = True
    game.log.append(f"{chosen.card.name} blocks this turn if able")
    return True, "resolved"


@effect_handler("force_target_to_block_until_eot")
def force_target_to_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature blocks this creature this turn if able." (Trumpeting
    Armodon.)

    CR 509.1c's requirement for one turn on the creature the caster chose
    (CR 601.2c), aimed at **one named attacker** — the ability's own source.
    Recorded on the compelled creature as that attacker's ``permanent_id``,
    which the declare-blockers step reads and the cleanup sweep clears.

    By id, and appended rather than assigned: two activations name two
    attackers and the creature owes both blocks as far as the rules allow, and
    an attacker that leaves and returns is a new object (CR 400.7) whose new id
    the old requirement no longer names.

    The printed noun phrase is re-asked here, not only at announcement, for the
    reason the attack twin gives: a target that stopped being a creature
    between the two is no longer the thing the card names (CR 608.2b).

    With no source on the battlefield there is no attacker for the requirement
    to be about, so nothing is recorded — a mark with no id in it would be a
    "block anything" requirement the card never prints.
    """
    from ..subject_filters import subject_matches

    attacker = context.source_permanent
    if attacker is None or not game.is_on_battlefield(attacker):
        game.log.append(
            f"{context.card.name}: its own attacker has left, so nothing is "
            "compelled to block"
        )
        return True, "resolved"
    # "Defending player chooses an untapped creature they control. **That
    # creature** blocks this creature this turn if able." (Crashing Boars.) The
    # creature an earlier step of this same resolution chose, read out of the
    # scratchpad by id — nothing was targeted, so there is no announcement to
    # resolve and nothing to re-check: the prompt's own candidate rule already
    # enforced the printed noun phrase, and re-asking it here would be a second
    # reading of a set the card only ever describes once.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key:
        for permanent_id in recorded_permanent_ids(context, recorded_key):
            perm = game.permanent_by_id(permanent_id)
            if perm is None:
                continue
            _owe_block(game, perm, attacker, context)
        return True, "resolved"
    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    chosen = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer, source=attacker,
        ),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        game.log.append(f"{context.card.name}: its target is gone (608.2b)")
        return True, "resolved"
    _owe_block(game, chosen, attacker, context)
    return True, "resolved"


def _owe_block(game: Game, blocker, attacker, context) -> None:
    """Record that *blocker* owes *attacker* a block this turn (CR 509.1c).

    One body for both ways the creature is named — a target the caster chose
    (Trumpeting Armodon) and one an earlier step of the resolution recorded
    (Crashing Boars) — because what is recorded does not depend on which. By
    id, and appended rather than assigned: two activations name two attackers
    and the creature owes both blocks as far as the rules allow, and an
    attacker that leaves and returns is a new object (CR 400.7) whose new id
    the old requirement no longer names.
    """
    owed = list(blocker.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ())
    if attacker.permanent_id not in owed:
        owed.append(attacker.permanent_id)
    blocker.metadata[MUST_BLOCK_ATTACKERS_UNTIL_EOT] = owed
    game.log.append(
        f"{blocker.card.name} blocks {attacker.card.name} this turn if able"
    )


@effect_handler("force_subject_to_block_until_eot")
def force_subject_to_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…all creatures with magnet counters on them block **that creature** this
    turn if able." (Magnetic Web.)

    The unnarrowed twin of the requirement above: every creature the printed
    noun phrase describes, on every battlefield, rather than one the caster
    chose. Same record and same enforcement — the attacker's ``permanent_id``
    on each compelled creature — so nothing new decides what "if able" means.

    ``attacker: "bound"`` is the creature the trigger's event was about, read
    out of the frozen trigger context by id (CR 400.7). The lowering refuses
    the pronoun under an event that records no attacker, so a missing id here
    is an attacker that has already left rather than a sentence nobody read.

    Through ``subject_matches`` with the ability's controller as CR 109.5's
    "you", the one reader of a printed noun phrase — and over
    ``all_permanents``, because the sentence scopes to no seat: a Magnetic Web
    attacker is on the *active* player's battlefield and the creatures compelled
    to block it are on everybody else's.
    """
    from ..subject_filters import subject_matches

    if instruction.payload.get("attacker") == "bound":
        bound = (context.trigger_context or {}).get("event_subject_permanent_id")
        attacker = game.permanent_by_id(bound) if isinstance(bound, int) else None
    else:
        attacker = context.source_permanent
    if attacker is None or not game.is_on_battlefield(attacker):
        game.log.append(
            f"{context.card.name}: the attacker has left, so nothing is "
            "compelled to block"
        )
        return True, "resolved"
    described = instruction.payload.get("subject") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    compelled = 0
    for perm in game.all_permanents():
        if perm is attacker or not perm.is_creature:
            continue
        if not subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        ):
            continue
        owed = list(perm.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ())
        if attacker.permanent_id not in owed:
            owed.append(attacker.permanent_id)
        perm.metadata[MUST_BLOCK_ATTACKERS_UNTIL_EOT] = owed
        compelled += 1
    game.log.append(
        f"{compelled} creature(s) block {attacker.card.name} this turn if able "
        f"({context.card.name})"
    )
    return True, "resolved"


def _windowed_seat(game, context, window) -> int | None:
    """The seat a payload ``window`` names, or None when nothing recorded one.

    One name today (``turn_state.THAT_PLAYERS_NEXT_TURN``) and one record: the
    player an earlier step of this same resolution asked to choose. Read here
    rather than at each of the three call sites so the requirement, the
    restriction and the end-step destruction cannot come to disagree about
    which turn "that turn" is — they are three sentences about one window,
    computed from one record inside one resolution, so they agree by
    construction rather than by comparison.
    """
    if window != THAT_PLAYERS_NEXT_TURN:
        return None
    seat = (context.results or {}).get("chosen_player")
    if isinstance(seat, int) and 0 <= seat < len(game.players):
        return seat
    return None


def _recorded_subject_permanents(game, context, payload):
    """The permanents a named step of this resolution recorded, still on the
    battlefield.

    ``subject_from`` is the plural of ``binds_recorded`` one file over: the
    sentence names "**the chosen creatures**" rather than a class, so the set is
    the answer an earlier step wrote and not something re-read off the board.
    Survivors only, by the same ``permanent_id`` resolution every other reader
    of a recorded set uses — a creature that has left is not there to be
    required to attack.
    """
    recorded = (context.results or {}).get(str(payload.get("subject_from"))) or ()
    found = []
    for entry in recorded:
        permanent = (
            entry if hasattr(entry, "permanent_id")
            else game.permanent_by_id(entry) if isinstance(entry, int) else None
        )
        if permanent is not None and game.is_on_battlefield(permanent):
            found.append(permanent)
    return found


@effect_handler("force_subject_to_attack_until_eot")
def force_subject_to_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Non-Wall creatures the active player controls attack this turn if able.
    At the beginning of the next end step, destroy each of those creatures that
    didn't attack this turn." (Maddening Imp.)

    The unnarrowed twin of ``force_target_to_attack_until_eot`` and the exact
    mirror of ``force_subject_to_block_until_eot`` beside it: every creature the
    printed noun phrase describes, on every battlefield, rather than one the
    caster chose. Same ``must_attack_until_eot`` mark the declare-attackers step
    already reads, so nothing new decides what "if able" means.

    Over ``all_permanents`` rather than one seat's battlefield, because the
    phrase scopes itself: "the active player controls" is a filter word
    (CR 102.1) that ``subject_matches`` answers, and reading the seat here as
    well would be a second opinion about which creatures the card names. That
    second opinion is what this replaces: ``force_active_player_creatures_to_attack``
    had ``active_player_index`` written into it and was reachable only by
    Siren's Call's name, so Maddening Imp — printing the identical sentence
    with one extra narrowing — got nothing from it.

    ``destroy_if_absent`` is the printed tail, and it is the same
    ``destroy_if_did_not_attack_eot`` mark Nettling Imp's fused handler sets and
    the end step already sweeps (``engine/phases/end_step.py``). Set at
    resolution rather than looked up at the end step, which is what makes
    "those creatures" mean the set that was marked and not whatever the noun
    phrase would describe a turn later.
    """
    from ..subject_filters import subject_matches

    payload = instruction.payload
    described = payload.get("subject") or {}
    destroy = bool(payload.get("destroy_if_absent"))
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    # "**During that player's next turn**, the chosen creatures attack if able."
    # (Oracle en-Vec.) Two payload keys over the same requirement: which turn it
    # holds for, and where the set came from. A window nobody recorded a seat
    # for does nothing rather than compelling the set on this turn, which is a
    # requirement a turn early and in the wrong player's favour.
    window = payload.get("window")
    seat = _windowed_seat(game, context, window) if window else None
    if window and seat is None:
        game.log.append(f"{context.card.name}: no player's turn to name")
        return True, "resolved"
    stamp = seats_next_turn_window(game, seat) if seat is not None else None
    if payload.get("subject_from"):
        subjects = _recorded_subject_permanents(game, context, payload)
    else:
        subjects = [
            perm for perm in game.all_permanents()
            if perm.is_creature and subject_matches(
                game, perm, described,
                observer=observer, source=context.source_permanent,
            )
        ]
    marked: list[str] = []
    for perm in subjects:
        if stamp is not None:
            perm.metadata[MUST_ATTACK_ON_SEAT_TURN_KEY] = dict(stamp)
            if destroy:
                mark_delayed_destruction(
                    game, perm, DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY,
                    dict(stamp),
                )
        else:
            perm.metadata["must_attack_until_eot"] = True
            if destroy:
                mark_delayed_destruction(
                    game, perm, "destroy_if_did_not_attack_eot"
                )
        marked.append(perm.card.name)
    if marked:
        when = (
            f"during {game.players[seat].name}'s next turn"
            if stamp is not None else "this turn"
        )
        game.log.append(
            f"{context.card.name} forces {', '.join(marked)} to attack {when}"
        )
    else:
        game.log.append(
            f"{context.card.name} resolved with no creatures to force into combat"
        )
    return True, "resolved"


@effect_handler("force_self_to_attack_until_eot")
def force_self_to_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…this creature deals 3 damage to you **and attacks this turn if able**."
    (Kookus.)

    CR 508.1a's requirement for one turn, on the ability's own source. The mark
    is the one ``declare_attackers`` already reads, so nothing new decides what
    "if able" means: a creature that cannot legally attack simply does not, and
    the requirement is met as far as the rules allow.

    Not the printed static ``engine/combat_restrictions.py`` reads for "attacks
    **each combat** if able" — that one lasts as long as the permanent is on the
    battlefield, and this ends with the turn (CR 611.2a), which is why the mark
    is the until-end-of-turn one and not a text claim.

    A source that has left the battlefield marks nothing: there is no permanent
    to require anything of, and CR 608.2 does as much as it can.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: nothing left to make attack")
        return True, "resolved"
    source.metadata["must_attack_until_eot"] = True
    game.log.append(f"{source.card.name} must attack this turn if able")
    return True, "resolved"


@effect_handler("destroy_subject_at_end_step_if_it_didnt_attack")
def destroy_subject_at_end_step_if_it_didnt_attack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"At the beginning of the next end step, destroy each of those creatures
    that didn't attack this turn." (Maddening Imp.) "…destroy all non-Wall
    creatures that player controls that didn't attack this turn. Ignore this
    effect for each creature the player didn't control continuously since the
    beginning of the turn." (Siren's Call.)

    The delayed half of the attack requirement, over the set a printed noun
    phrase describes. It arms the ``destroy_if_did_not_attack_eot`` mark the end
    step already sweeps (``engine/phases/end_step.py``) — the same mark Nettling
    Imp's fused handler sets for one creature — so nothing new decides when the
    destruction happens or whether regeneration is offered.

    **Marked now, swept later**, which is what makes the words mean what they
    say: "those creatures" is the set as it stood when the ability resolved, and
    a creature that arrives afterwards is not one of them however well it
    matches the phrase. Re-reading the noun phrase at the end step would be a
    second, later answer to a question CR 608.2 asked once.

    The two cards' sets differ from their own requirements' and from each
    other's — Siren's Call compels *every* creature the active player controls
    and destroys only the non-Walls it has controlled since the turn began — so
    the description travels in the payload rather than being inherited from the
    requirement beside it.
    """
    from ..subject_filters import subject_matches

    payload = instruction.payload
    described = payload.get("subject") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    # "At the beginning of **that turn's** end step, destroy each of **the
    # chosen creatures** that didn't attack this turn." (Oracle en-Vec.) The
    # same two keys the requirement above reads, and the same window computed
    # the same way from the same record — "that turn" is the turn the sentence
    # in front of it named, and both resolve inside one resolution, so the two
    # arithmetics cannot disagree.
    window = payload.get("window")
    seat = _windowed_seat(game, context, window) if window else None
    if window and seat is None:
        game.log.append(f"{context.card.name}: no player's turn to name")
        return True, "resolved"
    stamp = seats_next_turn_window(game, seat) if seat is not None else None
    if payload.get("subject_from"):
        subjects = _recorded_subject_permanents(game, context, payload)
    else:
        subjects = [
            perm for perm in game.all_permanents()
            if perm.is_creature and subject_matches(
                game, perm, described,
                observer=observer, source=context.source_permanent,
            )
        ]
    marked: list[str] = []
    for perm in subjects:
        if stamp is not None:
            mark_delayed_destruction(
                game, perm, DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY,
                dict(stamp),
            )
        else:
            mark_delayed_destruction(game, perm, "destroy_if_did_not_attack_eot")
        marked.append(perm.card.name)
    if marked:
        game.log.append(
            f"{context.card.name}: {', '.join(marked)} will be destroyed at end "
            "step if they didn't attack"
        )
    else:
        game.log.append(
            f"{context.card.name} resolved with no creatures to mark for the "
            "end-step destruction"
        )
    return True, "resolved"


@effect_handler("grant_unblockable_to_self")
def grant_unblockable_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature can't be blocked this turn." (Ghostly Pilferer.)

    The ability's own source, so nothing is chosen and nothing is resolved. A
    source that has already left the battlefield grants nothing rather than
    falling back to a scan, which would make some other creature unblockable.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: nothing to make unblockable")
        return True, "resolved"
    source.metadata["cant_be_blocked_until_eot"] = True
    game.log.append(f"{source.card.name} can't be blocked this turn")
    return True, "resolved"


#: The scratchpad key the unblockable grant records its creatures under. One
#: name, because the handler writes it and ``lowering/_records._PRODUCES``
#: declares it, and a second spelling would make the lowering's gate vacuous
#: while the record sat unread.
UNBLOCKABLE_PERMANENTS = "unblockable_permanents"


@effect_handler("grant_unblockable_to_target")
def grant_unblockable_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't be blocked this turn." (Teleport) / "…with
    **power 2 or less**…" (Dwarven Warriors) / "**X target creatures** with
    power 2 or less…" (Runed Arch) / "…**you control**…" (Goblin Sappers).

    One handler for all four, because the only difference between them is the
    noun phrase, and a noun phrase is something ``subject_matches`` answers.
    Dwarven Warriors used to have a handler of its own with "power 2 or less"
    written into its source — and again into ``legality.py``'s enumerator — so
    every other printing of the template refused.

    The filter is re-tested **here** and not only by the picker: CR 608.2b's
    check at resolution is what stops a creature that has been pumped past the
    bound since activation from being made unblockable, and a target the picker
    offered is not a target the effect still applies to.
    """
    from ..subject_filters import subject_matches

    described = {
        key: value for key, value in instruction.payload.items()
        if key != "targets"
    }
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )

    def _legal(perm: Permanent) -> bool:
        return perm.is_creature and subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        )

    # "X target creatures" resolves a *list*, and strictly: a per-slot fallback
    # would silently make one creature unblockable twice where the player chose
    # two (`resolve_target_permanents`).
    if _names_a_list(instruction):
        chosen = resolve_target_permanents(game, context, predicate=_legal)
    else:
        one = resolve_target_permanent(game, context, predicate=_legal)
        chosen = [one] if one is not None else []
    if not chosen:
        game.log.append(f"{context.card.name}: no creature to make unblockable")
        return True, "resolved"
    for target_creature in chosen:
        target_creature.metadata["cant_be_blocked_until_eot"] = True
        game.log.append(f"{target_creature.card.name} can't be blocked this turn")
    # "…can't be blocked this turn. **Destroy it** … at end of combat." (Goblin
    # Sappers.) The sentence after this one names what this one chose, and the
    # scratchpad is where it reads it — the same record a tap or an untap
    # writes, under the same shape (ids, never indices), so the lowering that
    # gates on "did an earlier step of this effect name a permanent?" asks one
    # question of all three.
    context.results[UNBLOCKABLE_PERMANENTS] = [
        perm.permanent_id for perm in chosen
    ]
    return True, "resolved"


@effect_handler("target_cant_block_until_eot")
def target_cant_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't block this turn." (Panic.)

    The mirror of ``grant_unblockable_to_target`` above — that one stops a
    creature *being* blocked, this one stops it blocking — and the same shape:
    a mark on the one permanent the spell chose, swept with the turn by
    ``_EOT_METADATA_KEYS``, read by the blocker gate.

    Not the blanket ``cant_block_until_eot`` beside it: that arms a board-wide
    filter, and a targeted restriction routed through it would reach every
    creature its noun phrase describes.

    "**Up to three target creatures** can't block this turn." (Panic Attack.)
    The same mark on each creature of a chosen list, resolved strictly — a
    per-slot fallback would mark one creature twice where the player chose
    two, and a slot whose creature left is simply not affected (CR 608.2b).
    """
    if _names_a_list(instruction):
        chosen = resolve_target_permanents(
            game, context, predicate=lambda p: p.is_creature
        )
        if not chosen:
            game.log.append(f"{context.card.name}: no creature to stop blocking")
        for each in chosen:
            each.metadata[CANT_BLOCK_UNTIL_EOT] = True
            game.log.append(f"{each.card.name} can't block this turn")
        return True, "resolved"
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda p: p.is_creature
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no creature to stop blocking")
        return True, "resolved"
    target_creature.metadata[CANT_BLOCK_UNTIL_EOT] = True
    game.log.append(f"{target_creature.card.name} can't block this turn")
    return True, "resolved"


@effect_handler("attached_cant_block_until_eot")
def attached_cant_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{R}: **Enchanted creature** can't block this turn." (Manacles of Decay.)

    ``target_cant_block_until_eot``'s mark on a creature nobody chose: the
    permanent the ability's own source is attached to, read as the ability
    resolves (CR 303.4) rather than at activation — an Aura moved in response
    restricts the creature it is on now, which is what "enchanted creature"
    means whenever it is read.

    Last-known attachment when the Aura has left since (CR 608.2h): the ability
    is independent of its source once on the stack (CR 113.7a), and the
    creature it was on is still the creature the words named. With no host at
    all there is nothing to mark, and the ability resolves to nothing.

    Swept with the turn by ``_EOT_METADATA_KEYS`` and read by the blocker gate,
    exactly as the targeted mark is — one key, so the two cannot disagree about
    when it ends.
    """
    host = attached_host(game, context.source_permanent)
    if host is None or not game.is_on_battlefield(host) or not host.is_creature:
        game.log.append(f"{context.card.name}: no enchanted creature to stop blocking")
        return True, "resolved"
    host.metadata[CANT_BLOCK_UNTIL_EOT] = True
    game.log.append(f"{host.card.name} can't block this turn")
    return True, "resolved"


@effect_handler("target_cant_attack_until_eot")
def target_cant_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't attack this turn." (Change of Heart.)

    The attacking twin of ``target_cant_block_until_eot`` above, and the same
    shape: a mark on the one permanent the spell chose, swept with the turn by
    ``_EOT_METADATA_KEYS``, read by ``declare_attackers_step.can_attack``.

    Not the blanket ``cant_attack_until_eot`` beside it -- that arms a
    board-wide filter, and a targeted restriction routed through it would
    ground every creature its noun phrase describes.

    The printed noun phrase is re-asked here, not only at announcement, for the
    reason every other targeted combat mark gives: a target that stopped being
    a creature between the two is no longer what the card names (CR 608.2b).
    """
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    target_creature = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: its target is gone (608.2b)")
        return True, "resolved"
    target_creature.metadata[CANT_ATTACK_UNTIL_EOT] = True
    game.log.append(f"{target_creature.card.name} can't attack this turn")
    return True, "resolved"


@effect_handler("target_cant_block_source_until_eot")
def target_cant_block_source_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't block this creature this turn." (Duct Crawler.)

    CR 509.1b's denial narrowed to one named attacker — the ability's own
    source — and the exact mirror of ``force_target_to_block_until_eot`` above,
    down to why it is recorded the way it is: the forbidden attacker's
    ``permanent_id`` appended to a list on the restricted creature, because two
    activations name two attackers and both denials hold, and because an
    attacker that leaves and returns is a new object (CR 400.7) whose new id
    the old denial does not name.

    With no source on the battlefield there is no attacker for the denial to be
    about, so nothing is recorded — a mark with no id in it would be a "can't
    block at all" this card never prints.
    """
    from ..subject_filters import subject_matches

    attacker = context.source_permanent
    if attacker is None or not game.is_on_battlefield(attacker):
        game.log.append(
            f"{context.card.name}: its own attacker has left, so nothing is "
            "denied a block"
        )
        return True, "resolved"
    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    chosen = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer, source=attacker,
        ),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        game.log.append(f"{context.card.name}: its target is gone (608.2b)")
        return True, "resolved"
    denied = list(chosen.metadata.get(CANT_BLOCK_ATTACKERS_UNTIL_EOT) or ())
    if attacker.permanent_id not in denied:
        denied.append(attacker.permanent_id)
    chosen.metadata[CANT_BLOCK_ATTACKERS_UNTIL_EOT] = denied
    game.log.append(
        f"{chosen.card.name} can't block {attacker.card.name} this turn"
    )
    return True, "resolved"


@effect_handler("grant_additional_blocks_until_eot")
def grant_additional_blocks_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"That creature can block up to two additional creatures this turn."
    (Yare.)

    CR 509.1b's block-count ceiling raised on one permanent for one turn. A
    record on the creature, read by ``_max_blocks_for`` beside the printed
    static it already counts and swept with the turn by ``_EOT_METADATA_KEYS``
    -- the arrangement every other granted combat permission here uses.

    It **adds**, because CR 509.1b's restrictions are cumulative in both
    directions: two grants on one creature are two more attackers, and a
    creature that already blocks an additional one by its own printed line
    keeps that too. Assignment rather than addition would have made the second
    copy of the spell do nothing.

    ``subject: "source"`` is the ability's own permanent ("{W}: This creature
    can block an additional creature this turn.", Mounted Archers). Resolved
    explicitly rather than through ``resolve_target_permanent``, whose
    no-target fallback scans the battlefield -- an activated ability names no
    target, so the fallback would grant the permission to whichever creature
    the scan reached first.
    """
    if instruction.payload.get("subject") == "source":
        blocker = context.source_permanent
    else:
        blocker = resolve_target_permanent(
            game, context, predicate=lambda p: p.is_creature
        )
    if blocker is None:
        game.log.append(
            f"{context.card.name}: no creature to grant extra blocks to"
        )
        return True, "resolved"
    extra = max(0, int(instruction.payload.get("count", 1)))
    blocker.metadata[ADDITIONAL_BLOCKS_UNTIL_EOT] = (
        int(blocker.metadata.get(ADDITIONAL_BLOCKS_UNTIL_EOT, 0)) + extra
    )
    game.log.append(
        f"{blocker.card.name} can block {extra} additional creature(s) this turn"
    )
    return True, "resolved"


@effect_handler("grant_cant_be_blocked_by_until_eot")
def grant_cant_be_blocked_by_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't be blocked by Walls this turn." (Tower of
    Coireall.)

    The granted twin of the static restriction `engine/combat_restrictions.py`
    derives, and the *same* record the blockers step reads: the class of blocker
    is a filter payload either way, so a card printing another subtype, colour
    or card type needs no code here and no branch there.

    Not folded into ``grant_unblockable_to_target``: that one makes the creature
    unblockable by everything, and a narrowing this handler dropped would hand
    the card the larger effect silently.
    """
    from ..combat_restrictions import grant_blocker_restriction

    described = instruction.payload.get("blocker_filter") or {}
    if not described:
        # A restriction with no class behind it would be the unnarrowed one.
        game.log.append(f"{context.card.name}: no blocker class to restrict")
        return True, "resolved"
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda p: p.is_creature,
        fallback_on_invalid_choice=False,
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no creature to restrict")
        return True, "resolved"
    grant_blocker_restriction(target_creature, described)
    game.log.append(
        f"{target_creature.card.name} can't be blocked by matching creatures "
        f"this turn ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("grant_cant_be_blocked_except_by_until_eot")
def grant_cant_be_blocked_except_by_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't be blocked this turn except by Walls." (Joven's
    Tools.)

    The granted twin of ``cant_be_blocked_except_by``, the static
    `engine/combat_restrictions.py` derives — and the **inverse** of
    ``grant_cant_be_blocked_by_until_eot`` beside it, not a flag on it: that one
    names blockers the creature is safe from and leaves the rest of the board
    able to block, this one names the only blockers there are. A record read as
    the other would turn one card into the other's opposite.

    An empty union would allow nothing at all rather than everything, which is
    a strictly larger effect than the card prints — so it refuses to arm rather
    than arming a whitelist nobody can satisfy. The lowering already declines
    the phrase; this is the second half of that rule, where a payload built by
    anything else arrives.
    """
    from ..combat_restrictions import grant_blocker_whitelist

    allowed = [
        described
        for described in (instruction.payload.get("allowed_blockers") or ())
        if described
    ]
    if not allowed:
        game.log.append(f"{context.card.name}: no blocker class to allow")
        return True, "resolved"
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda p: p.is_creature,
        fallback_on_invalid_choice=False,
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no creature to restrict")
        return True, "resolved"
    grant_blocker_whitelist(target_creature, allowed)
    game.log.append(
        f"{target_creature.card.name} can't be blocked this turn except by "
        f"matching creatures ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("cant_attack_until_eot")
def cant_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Creatures can't attack this turn." (Festival.)

    The attack twin of ``cant_block_until_eot`` below: a blanket restriction the
    attack gate (``declare_attackers_step.can_attack``) tests for the rest of
    the turn, swept at cleanup. State plus a reader, never a flag stamped per
    creature — a creature entering after this resolves cannot attack either,
    which per-permanent flags would miss.
    """
    payload = instruction.payload
    entry = {
        "filter": dict(payload.get("filter") or {}),
        "source_name": context.card.name,
        # How many cleanups the window survives — 1 for every printed "this
        # turn", 2 for "this turn and next turn" (Peace Talks). Carried from
        # the payload rather than assumed, because the sweep is subtraction and
        # an assumed 1 ends the longer window a whole turn early.
        "remaining_turns": int(payload.get("remaining_turns", 1)),
    }
    # "**During that player's next turn**, … other creatures can't attack."
    # (Oracle en-Vec.) A turn that has not started, so the entry carries a
    # window stamp instead of a countdown — see ``phases/cleanup_step``, where
    # subtracting this turn's cleanup from it would end the restriction the turn
    # before it applied.
    window = payload.get("window")
    if window:
        seat = _windowed_seat(game, context, window)
        if seat is None:
            game.log.append(f"{context.card.name}: no player's turn to name")
            return True, "resolved"
        entry["on_seat_turn"] = seats_next_turn_window(game, seat)
    # "**Other** creatures can't attack" — other than the set an earlier step of
    # this resolution chose. Frozen now because that is when the choice was made
    # (CR 608.2), and by id because the entry outlives the resolution that wrote
    # it and a creature that leaves and returns is a new object the sentence
    # never named (CR 400.7). The restriction itself is deliberately *not*
    # frozen: CR 611.2c gives a rules-modifying effect the objects that arrive
    # later too, which is what the game-level entry is for.
    excepted = payload.get("except_from")
    if excepted:
        entry["except_permanent_ids"] = [
            permanent.permanent_id
            for permanent in _recorded_subject_permanents(
                game, context, {"subject_from": excepted}
            )
        ]
    game.attack_restrictions_until_eot.append(entry)
    game.log.append(f"{context.card.name}: the named creatures can't attack")
    return True, "resolved"


@effect_handler("cant_block_until_eot")
def cant_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Creatures without flying can't block this turn." (Destructive
    Tampering's second mode.) Arms a blanket restriction the blocker gate
    (``_can_block_attacker``) tests for the rest of the turn; cleanup sweeps
    it. State plus a reader, never a flag stamped per creature — a creature
    entering after this resolves is restricted too, which per-permanent flags
    would miss."""
    game.blocking_restrictions_until_eot.append({
        "filter": dict(instruction.payload.get("filter") or {}),
        "source_name": context.card.name,
    })
    game.log.append(f"{context.card.name}: the named creatures can't block this turn")
    return True, "resolved"


#: The two turn-scoped declaration tolls, mapped to the list each is filed in
#: and the word a log line uses. One table because the two handlers below differ
#: in nothing else: CR 508.1h and CR 509.1d are the same rule on two sides of
#: combat, and the *readers* are what tell them apart.
_PAY_TOLL_LISTS: dict[str, tuple[str, str]] = {
    "creatures_cant_attack_unless_pay_until_eot": (
        "attack_restrictions_until_eot", "attack",
    ),
    "creatures_cant_block_unless_pay_until_eot": (
        "blocking_restrictions_until_eot", "block",
    ),
}


def _arm_declaration_toll(game, instruction, context, kind: str):
    """File a "creatures can't <verb> unless their controller pays <cost>" toll.

    It goes in the very list the blanket prohibitions use, and that is the
    decision worth writing down: CR 508.1c and CR 509.1b make "can't attack"
    and "can't attack **unless some condition is met**" one rule, so one list is
    "what this turn forbids" and the cost is what the condition asks for. The
    two gates skip an entry carrying ``mana`` — a toll is not a ban, and a
    payable one forbids nothing — and the two *cost* readers pick it up
    instead. Cleanup already sweeps the list, so the window needs nothing new.

    **The cost is resolved here and stored concrete.** The ability announced X
    as it was activated (CR 601.2b, reached through CR 602.2b) and that number
    is fixed while the ability is on the stack (CR 107.3a) and so, once it has
    resolved, for the life of the effect; the declaration readers charge
    ``int()`` off the entry
    and would raise on a string, and a toll re-resolved at the declaration would
    read whichever X the *next* activation announced. A toll announced at X=0 is
    filed all the same and costs nothing, which is what the card says.
    """
    list_name, verb = _PAY_TOLL_LISTS[kind]
    cost = {
        symbol: max(0, int(context.x_value or 0)) if amount == "x" else int(amount)
        for symbol, amount in (instruction.payload.get("mana") or {}).items()
    }
    entry = {
        "filter": dict(instruction.payload.get("subject") or {}),
        # **The flag, not the cost, is what says this is a toll.** An entry
        # announced at X=0 owes {0}, which is a real and legal answer
        # (CR 107.3a: the choice is the activator's, and 0 is one of them) —
        # and a gate that told a toll from a ban by "does it carry
        # a price" would read that entry as a prohibition and ground every
        # creature the noun phrase names. The two readers key on this instead.
        "toll": True,
        "mana": {symbol: amount for symbol, amount in cost.items() if amount},
        "source_name": context.card.name,
    }
    getattr(game, list_name).append(entry)
    game.log.append(
        f"{context.card.name}: the named creatures can't {verb} this turn "
        f"unless their controller pays {mana_cost_label(entry['mana']) or '{0}'} "
        f"for each"
    )
    return True, "resolved"


@effect_handler("creatures_cant_attack_unless_pay_until_eot")
def creatures_cant_attack_unless_pay_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"This turn, creatures can't attack unless their controller pays {X} for
    each attacking creature they control." (War Tax.) CR 508.1h."""
    return _arm_declaration_toll(
        game, instruction, context, "creatures_cant_attack_unless_pay_until_eot"
    )


@effect_handler("creatures_cant_block_unless_pay_until_eot")
def creatures_cant_block_unless_pay_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"This turn, creatures can't block unless their controller pays {X} for
    each blocking creature they control." (War Cadence.) CR 509.1d."""
    return _arm_declaration_toll(
        game, instruction, context, "creatures_cant_block_unless_pay_until_eot"
    )


@effect_handler("attack_as_though_no_defender_until_eot")
def attack_as_though_no_defender_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"…can attack this turn as though it didn't have defender."
    (Wall of Wonder.)

    CR 609.4: the permission is stamped on the permanent rather than the
    keyword being removed, so the creature still *has* defender for everything
    that asks — what "creatures with defender" counts, what a defender-narrowed
    filter matches, what layer 6 reports to the web payload. The key is swept
    by the cleanup step (``_EOT_METADATA_KEYS``), which is the whole of "this
    turn".
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    source.metadata[ATTACK_AS_THOUGH_NO_DEFENDER] = True
    game.log.append(
        f"{source.card.name} can attack this turn as though it didn't have defender"
    )
    return True, "resolved"


@effect_handler("exempt_from_attack_tapping")
def exempt_from_attack_tapping(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Attacking doesn't cause creatures you control to tap this combat if
    Johan is untapped." (Johan; CR 508.1f.)

    Arms a standing exemption rather than doing anything now — nothing is
    tapped or untapped when this resolves, and the creatures it is about have
    not been declared yet. ``engine/attack_tapping.py`` holds it, the declare
    attackers step asks it, and the end of combat step ends it.

    The gate is bound to the **source permanent by id**: "if Johan is untapped"
    is about this Johan (CR 400.7), so a Johan that leaves and returns does not
    inherit the exemption his earlier self armed. With no source on the
    battlefield there is nothing for the gate to be about, and the effect
    refuses rather than arming an exemption that could never apply — or, worse,
    one whose gate is silently dropped.
    """
    from ..attack_tapping import AttackTapExemption, arm_attack_tap_exemption

    gate_filter = dict(instruction.payload.get("gate_filter") or {})
    source = context.source_permanent
    if gate_filter and source is None:
        return False, "ability not implemented"
    seat = game.players.index(context.caster)
    arm_attack_tap_exemption(game, AttackTapExemption(
        controller_index=seat,
        subject_filter=dict(instruction.payload.get("filter") or {}),
        gate_permanent_id=source.permanent_id if gate_filter else None,
        gate_filter=gate_filter,
        source_name=context.card.name if context.card is not None else "an effect",
    ))
    game.log.append(
        f"attacking doesn't cause those creatures to tap this combat "
        f"({context.card.name if context.card is not None else 'an effect'})"
    )
    return True, "resolved"

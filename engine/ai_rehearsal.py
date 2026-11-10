"""What one cast does to a seat's position, found by carrying the cast out
on a scratch copy of the game.

:func:`rehearse` asks the engine rather than guessing: it takes a copy on
which what the asking seat cannot see is dealt again (``ai_scratch_copy``:
``scratch_copy``, ``conceal_from``, CR 400.2), carries the candidate out,
resolves it on defaults, and reads the table right after and once the turn
has run out — with its combat fought, where the cast comes before one
(:func:`run_out_the_turn`) — against the same copy with nothing cast, read
once per decision inside :func:`deliberating`. Each reading is a standing
per seat (``ai_standing.seat_standing``, in the one unit "larger" is said
in) and a digest of everything a player could point at
(:func:`position_digest`): what the cast did is the swing between two
standings (``ai_standing.swing_worth``) and whether the two digests differ
by more than the spell's own trip (:func:`same_position`). The seeded RNG is
saved and restored around every rehearsal, so a seed still reproduces a run.
A rehearsal that raises is "cannot be weighed" to the policy and a line in
``REHEARSALS_RAISED`` to the simulator, which reports it; and a table owing
the rest of a resolution is not copied at all
(``ai_scratch_copy.mid_resolution``).

Two readers ask it, and that is why it is in the valuation family and not
beside the policy's weights: the policy, which predicts with it, and the mode
census (``tests/ai/test_ai_mode_chooser_census.py``), which makes the cast
for real on a board of its own and reads it as a rehearsal would
(:func:`run_out_the_turn`, :func:`position_digest`). Two prices from two
functions would be a census asking the scorer whether the scorer is right.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .ai_scratch_copy import _scratch, held_for_an_answer, mid_resolution
from .ai_player_control import served_seat
from .ai_standing import CARD_WORTH, standing_swing, standings, swing_worth
from .ai_weighed_cast import permitted_casts
from .text_changes import spell_text_card


# --- Rehearsal: what a cast would do, asked of the engine ---------------------

#: What every cast changes whatever it does — the zones the spell itself moves
#: through (read separately), the mana that paid for it, the turn's count of
#: spells. Left in, a resolution that did nothing still reads as a change.
#: Mana the spell *makes* is read where it can be told from mana the spell
#: cost: across its resolution (:func:`_rehearse`).
_PLAYER_BOOKKEEPING = frozenset({
    "hand", "graveyard", "library", "exile", "mana_pool", "battlefield",
    "spells_cast_this_turn",
    # How many turn records (``engine/turn_replacements.py``) the seat has
    # ever armed — the counter that gives each one its CR 614.5 identity, not
    # an effect. The records themselves are read (``_turn_replacements``) and
    # are gone once the turn is; the counter never goes back down, so read as
    # a field it made every such spell a lasting change: Flaring Pain ("Damage
    # can't be prevented this turn") was cast into an empty board, twice.
    "_turn_replacements_armed",
    # When each graveyard card arrived (``engine/graveyard_order.py``, the
    # CR 613.7d timestamp of a static that functions from a graveyard). It
    # moves whenever ``graveyard`` does, which is already bookkeeping here; read
    # as a field it made every spell that resolves into a graveyard a lasting
    # change, and Blind Fury and Plagiarize were cast into empty boards again.
    "graveyard_arrivals",
})
#: The same for the game's own fields: the table itself (read separately),
#: the log, the stack and who has priority, and the per-turn ledgers a cast
#: writes whether or not it does anything.
_GAME_BOOKKEEPING = frozenset({
    "players", "log", "stack", "priority_player_index", "priority_pass_count",
    "prompt_driver", "interactive_seats", "enforce_mana_costs",
    "resolving_seats", "resolving_stack_item", "pending_choices",
    "current_phase", "current_turn_phase", "current_step",
    # Which step's leaving stopped part-way for an answer (CR 500.2): where
    # the turn is, like the three fields above, not anything a cast did.
    "held_step",
    # Read apart, by the names of the cards each permission covers
    # (`_permission_entries`), so that the one a cast spends can be told
    # apart from what the cast did.
    "cast_permissions",
    # "Did this seat cast a spell during its last turn" (Arboria, CR 506.3),
    # folded out of `spells_cast_this_turn` as the next turn begins — which
    # is where the end-of-turn reading is taken (`untap_for_the_next_turn`),
    # so every cast would read as having changed it.
    "last_own_turn_activity",
    # How many cards each seat held as the turn began (Mindstorm Crown,
    # `begin_turn_bookkeeping`). Nothing a cast does writes it, but a reading
    # taken "as the next turn begins" (`untap_for_the_next_turn`, the combat
    # trick census's `lasting_digest`) records the hand the cast left — and
    # the hand is already digested by name, with the spell's own trip put back
    # (`same_position`). Read as a field it counted that trip a second time,
    # so every cast was a lasting change.
    "hand_sizes_at_turn_start",
    # What each step left owed as the next began (``ai_simulator.
    # _SimulatedGame._steps_left_owing``): the simulator's honesty
    # instrument, kept in the instance's ``__dict__`` and so only a simulated
    # game's. Read as a field it was a difference between the simulator's
    # positions and the web's, and two scratch copies whose run-out left a
    # step around something differently "changed" by the count alone (the
    # census over sim_fingerprint's runs: read in every digest, different in
    # four rehearsals, no answer moved).
    "_w2g6_steps_left_owing",
})

#: Rehearsals that **raised**, by what was being rehearsed and what the
#: engine raised: ``"Lightning Bolt: KeyError: 'amount' (damage.py:212 in
#: deal_damage)"`` -> how many times.
#:
#: A rehearsal that raises answers None, and a policy reads None as "this
#: could not be weighed" — which is right for a game somebody is playing (a
#: crash in a copy is not a crash in the game) and is also a **silence**:
#: before a cast was rehearsed, the same exception was raised by the real
#: cast and stopped a simulated run on the spot, which is how a
#: crash-on-cast card used to be found. So each one is written down here,
#: process-wide, and the simulator reads what its own run added
#: (``SimulationReport.rehearsals_raised``): a raised rehearsal is a crash
#: the game was spared, not a quiet "no". Nothing in the engine reads this
#: to decide anything.
REHEARSALS_RAISED: Counter = Counter()


def _note_raised(what: "str | None", raised: BaseException) -> None:
    """Write one raised rehearsal into ``REHEARSALS_RAISED``: what was being
    carried out, the exception, and the innermost frame it came from."""
    import os
    import traceback

    frames = traceback.extract_tb(raised.__traceback__)
    where = ""
    if frames:
        last = frames[-1]
        where = f" ({os.path.basename(last.filename)}:{last.lineno} in {last.name})"
    REHEARSALS_RAISED[
        f"{what or 'a rehearsal'}: {type(raised).__name__}: {raised}{where}"
    ] += 1


_REHEARSING: ContextVar[bool] = ContextVar("ai_rehearsing", default=False)
_DELIBERATION: ContextVar["dict | None"] = ContextVar("ai_deliberation", default=None)

#: How many passes the rehearsal gives a stack to empty and a combat to end.
_REHEARSAL_PASSES = 8
#: Under this, a swing is no swing: the standings are sums of floats.
_NO_SWING = 1e-9


@dataclass(frozen=True)
class Rehearsal:
    """What one cast did, carried out on a scratch copy of the game.

    ``accepted``
        the engine took the cast (False: it was refused, and ``refusal`` says
        why — a cast this policy must not propose);
    ``changed``
        the resolution changed anything at all on the table or in the turn's
        records, beyond the spell's own trip from hand to graveyard;
    ``now`` / ``lasting``
        the caster's ``ai_standing.standing_swing`` against the same table
        with nothing cast — as the board stood right after the resolution, and
        with the turn's temporary effects over;
    ``swing``
        ``ai_standing.swing_worth`` of the two;
    ``fleeting``
        everything it changed is **gone by the end of the turn**: no standing
        differs then and nothing on the table does (a pump that has worn off,
        a shield nothing hit, a Fog) — where a change no standing prices and
        that is still there (a permanent's colour, the order of a library) is
        not;
    ``made_mana``
        some of what it changed is mana in a pool, which is fleeting by
        nature and is not nothing: it is what the next cast is paid with;
    ``through_combat``
        the turn was run out **with its combat played** (:func:`rehearse`'s
        *through_combat*), and ``now`` is ``lasting``: what the cast was
        worth once the fight it was made before had been fought;
    ``combat_ahead``
        once the cast had resolved, the caster's turn still had a combat
        phase to come (:func:`_combat_ahead`) — the one a precombat cast is
        made before, or one the cast itself added;
    ``creature_ahead``
        once the cast had resolved, the caster controlled a creature
        (:func:`has_a_creature_to_fight_with`) — something that fight could
        be fought with, the cast's own doing included: "Until end of turn,
        target land becomes a 3/3 creature" (Animate Land) on a board of
        lands is a fight that only the cast makes possible;
    ``opened_a_cast``
        once it had resolved, the caster could cast something from outside
        its hand it could not before (CR 601.3: "you may play cards from your
        graveyard this turn") — fleeting like mana, and like mana not
        nothing: it is spent on a cast this rehearsal is not a rehearsal of.
        Only a cast the caster **could make** there and then
        (:func:`_could_make_now`): one nobody can pay for is spent on nothing;
    ``blocks_added``
        read through the fight, a block was declared on the cast's copy that
        the copy with nothing cast did not declare — the reason to act before
        the blocks rather than after them (:func:`pays_before_the_blocks`);
    ``declarations_changed``
        read through the fight, the attackers or the blocks declared on the
        cast's copy are not those the copy with nothing cast declared — an
        attack it adds, a block it adds, deters or prevents (a tapped
        blocker). Where they are the same, what the cast does to the fight is
        what it does to a combat whose declarations it did not touch, and an
        ability can wait for the blocks to be known
        (``ai_activation_rehearsal._read_through_the_fight``);
    ``reordered_only``
        everything it changed is **the order of a library**: a shuffle (CR
        701.24a, "so that no player knows their order") of the same cards —
        Feldon's Cane over an empty graveyard, which CR 701.24c shuffles all
        the same. Read only for an action with no spell's trip to take out
        (an activation); a digest compares libraries in order, so this is
        otherwise a lasting change no seat can count on.
    """

    accepted: bool
    changed: bool = False
    now: float = 0.0
    lasting: float = 0.0
    refusal: str = ""
    fleeting: bool = False
    made_mana: bool = False
    through_combat: bool = False
    combat_ahead: bool = False
    opened_a_cast: bool = False
    creature_ahead: bool = False
    blocks_added: bool = False
    declarations_changed: bool = False
    reordered_only: bool = False

    @property
    def swing(self) -> float:
        return swing_worth(self.now, self.lasting)


def rehearsing() -> bool:
    """Whether the code asking is running **inside** a rehearsal — on a
    scratch copy whose every prompt is being answered by default. A chooser
    reached from there (a default that asks the policy) must not rehearse
    again."""
    return _REHEARSING.get()


@contextmanager
def deliberating():
    """One decision's worth of rehearsals.

    Every candidate a chooser weighs is measured against the same table with
    nothing cast, and that reading costs a copy of the game — so it is taken
    once per decision and kept for the length of this block. Outside one,
    each rehearsal takes its own.
    """
    if _DELIBERATION.get() is not None:
        yield
        return
    token = _DELIBERATION.set({})
    try:
        yield
    finally:
        _DELIBERATION.reset(token)


def _settle_scratch(game) -> None:
    """Empty the stack of a scratch copy, answering what each object asks —
    and check state-based actions (CR 704.3) once it is empty: a creature
    dealt lethal damage is on the battlefield until they are, and a reading
    taken before would count it as alive."""
    for _ in range(_REHEARSAL_PASSES):
        game._resolve_priority_window()
        game.auto_resolve_pending_choices()
        game.check_state_based_actions()
        if not game.stack and not game.pending_choices:
            return


def combat_is_still_to_come(game, seat: int) -> bool:
    """Whether *seat* is in a main phase of its own turn with nothing on the
    stack and a combat phase still to come this turn — the moment a cast is
    made **before** a fight, and the only one a rehearsal can play that
    fight out from (:func:`_combat_ahead`)."""
    return game.active_player_index == seat and _combat_ahead(game)


def blocks_owed(game) -> bool:
    """Whether *game* is in a declare-attackers step whose attackers are
    declared and whose blocks are not — whatever is on the stack. A copy
    made here owes the blocks once its stack has resolved, so a rehearsal
    that does not fight the rest of the combat (:func:`_fight_the_combat`)
    reads a combat that deals no damage at all: a response to an attack
    trigger (kg3) was read that way."""
    return (
        game.current_turn_phase == "combat"
        and game.current_step == "declare_attackers"
        and bool(game.combat_attackers)
        and game.combat_attackers_locked
        and not game.combat_blockers_locked
        and not game.is_game_over()
    )


def blocks_still_to_come(game) -> bool:
    """Whether *game* is in a declare-attackers step whose attackers are
    declared and whose blocks are not, with nothing on the stack — CR 508.2's
    priority, before CR 509.1's declaration (:func:`blocks_owed`, the stack
    empty). The one moment a creature can be cast to block with, or an
    ability used to change who can block whom, and the moment a rehearsal
    plays the rest of that combat out from (:func:`_fight_the_combat`), the
    blocks declared by the policy."""
    return blocks_owed(game) and not game.stack


def _combat_ahead(game) -> bool:
    """Whether *game* is in a main phase with nothing on the stack and a
    combat phase in what is left of its turn's plan (CR 500.1; CR 500.8 adds
    one: "after this main phase, there is an additional combat phase",
    Relentless Assault). Read without planning the turn, which asking the
    game would do (``Game._remaining_turn_phases``)."""
    from .mixins._constants import phases_after

    if game.stack or game.pending_choices or game.is_game_over():
        return False
    if game.current_turn_phase not in ("precombat_main", "postcombat_main"):
        return False
    plan = getattr(game, "turn_phases_remaining", None)
    if plan is None:
        plan = phases_after(game.current_turn_phase)
    return "combat" in plan


def has_a_creature_to_fight_with(game, seat: int) -> bool:
    """Whether *seat* controls a creature at all. With none there is no
    attack to declare whatever is cast first — a spell that *makes* one has
    left something behind and is not asked about the fight — so the second
    reading would be the first, at the price of a combat on two copies."""
    return any(permanent.is_creature for permanent in game.controlled_by(seat))


def priced_by_the_fight(now: float, lasting: float, fleeting: bool) -> bool:
    """Whether a cast made before the turn's combat is one a reading with no
    combat in it cannot price: some of its good is gone by the end of the
    turn — all of it (*fleeting*), or more of it than is left (*now* above
    *lasting*). A removal spell, a draw, a discard are priced by what they
    leave.

    The policy asks it before reading a cast a second time with the fight
    fought (``ai_scoring._weighed_through_the_fight``), and the censuses ask
    it of the casts they make for real — one definition of which casts the
    fight is part of the price of.
    """
    return bool(fleeting) or now > lasting + _NO_SWING


def pays_before_the_blocks(first: "Rehearsal | None", fought: "Rehearsal | None") -> bool:
    """Whether an action weighed in the declare-attackers step
    (:func:`blocks_still_to_come`) is one to take **there**: read through the
    fight (*fought*) it adds a block (``blocks_added``), and it leaves the
    seat better off than the same action read with no fight (*first*) — a
    creature's body alone, which it would be worth cast in the end step.

    Anything that adds no block can wait for the declare-blockers step, where
    the blocks are known: a Fog, a removal spell, the attacker's own pump. An
    ambusher that blocks nothing, or blocks to lose more than it is worth, is
    held for the end step."""
    if fought is None or not fought.accepted or not fought.blocks_added:
        return False
    floor = first.lasting if first is not None and first.accepted else 0.0
    return fought.lasting > max(0.0, floor) + _NO_SWING


def run_out_the_turn(
    game, *, through_combat: bool = False, seat: "int | None" = None,
) -> frozenset:
    """Take *game* — a scratch copy (``ai_scratch_copy.scratch_copy``) — to
    the end of its turn the way a rehearsal does: with its combat fought first if
    *through_combat* (the active seat's attack and the blocks declared by
    the policies that would declare them), then CR 514's cleanup. For a
    reader that makes a cast for real and wants it priced as a rehearsal
    would price it — *seat*, the seat whose cast it is, answering its
    priority after the blocks as a rehearsal's seat does
    (:func:`_fight_priority_driver`). Returns the blocks the fight declared
    (``ai_combat.CombatOutcome.blocks_declared``)."""
    return _run_out_the_turn(game, through_combat=through_combat, seat=seat)


def _in_a_block(game, seat: int) -> bool:
    """Whether a creature *seat* controls is in a block this combat: one of
    its attackers blocked, where it is the active seat, or one of its
    creatures blocking, where it defends (``ai_combat.declared_block_pairs``)."""
    from .ai_combat import declared_block_pairs

    active = game.active_player_index
    return any(
        (seat == active or defender == seat) and declared_block_pairs(game, defender)
        for defender in range(len(game.players))
        if defender != active
    )


def _fight_priority_driver(table, seat: int):
    """The priority driver a scratch copy fights its combat with
    (:func:`_fight_the_combat`): *seat* — the seat the rehearsal is for —
    activates in the declare-blockers step, once the blocks are in and the
    stack is empty, what it would there in the game
    (``ai_policy.choose_instant_speed_activation``, the activation door of
    ``ai_priority.act_at_priority``'s ``"combat"`` window: the pump on a
    blocked attacker, the redirect that wins a block, the regeneration in
    front of a lethal one), **once per combat**.

    **Abilities, not spells.** An instant held for after the blocks is a
    card the main phase could spend another way, and the cast chooser does
    not price that: with the copy casting Healing Salve's shield after the
    blocks, the shield mode was held — and the life mode, read with no fight
    behind it, was cast for three life in its place (measured, kg5). An
    ability costs no card, so holding it gives nothing else up.

    A copy's priority was passed by everybody (the simulator's driver
    answers only for its own table), so a rehearsal through a fight read the
    combat as if nothing could be done in it — and a trick that is worth most
    after the blocks was worth buying only before them: Zealous Inquisitor's
    redirect was bought in the first main phase because, on the copy with
    nothing bought, the Bears blocked and traded and the redirect was never
    raised there (the Known-gaps "AI leftovers" entry, kg4).

    Its choosers rehearse what they propose, and this table is itself a
    rehearsal's: they are asked **one level down**
    (``ai_prompt_picks._one_level_deeper``) and never a second — a fight
    read inside that level is answered by nobody, as every copy's was. Only
    *seat* acts: every other hand on the copy was dealt again out of what
    *seat* cannot see (``ai_scratch_copy.conceal_from``), and a trick drawn
    from a guessed hand is a guess. And only where a creature of *seat*'s is
    in a block (:func:`_in_a_block`): an unblocked attacker's pump is a
    reading a fight with no block in it already takes in the real
    declare-blockers step, and the deeper level is the dearest thing a
    rehearsal does."""
    answered: set = set()

    def drive(game, asked: int) -> bool:
        if game is not table or asked != seat or game.stack:
            return False
        if not (
            game.current_turn_phase == "combat"
            and game.current_step == "declare_blockers"
            and game.combat_attackers
            and game.combat_blockers_locked
        ):
            return False
        combat = tuple(game.combat_attackers)
        if combat in answered or not _in_a_block(game, seat):
            return False
        answered.add(combat)
        from .ai_player_control import plays_for_another
        from .ai_policy import (activate_chosen_ability, choose_instant_speed_activation,
                                holds_an_ability_it_could_activate)
        from .ai_prompt_picks import _one_level_deeper

        with _one_level_deeper():
            if rehearsing() or plays_for_another(game, seat):
                return False
            if not holds_an_ability_it_could_activate(game, seat):
                return False
            action = choose_instant_speed_activation(game, seat)
            if action is None:
                return False
            result = activate_chosen_ability(game, seat, action)
        return bool(getattr(result, "supported", False))

    return drive


def _fight_the_combat(game, attacks: "set | None" = None, *, seat: "int | None" = None) -> frozenset:
    """Play a scratch copy's combat phases from the main phase it is in: the
    active seat's attack, the blocks, the damage — each declared by the
    policy that would declare it in a game nobody is asked about
    (``ai_combat.run_ai_combat_phase``, the simulator's own driver) — and
    every further combat the turn's plan holds (CR 500.8), each entered the
    way the turn enters it. Returns ``(blocker id, attacker id)`` for every
    block declared on the way.

    The one place a rehearsal lets something be *decided* on the way to the
    end of the turn, and it is asked for by name (:func:`rehearse`'s
    *through_combat*) on the cast and on the table it is measured against
    alike. What it buys is the difference a precombat cast makes to the
    fight: three more damage from a Giant Growth, none at all under the
    caster's own Fog.

    **A combat already under way is finished first**, from the step it is
    in: asked in the declare-attackers step (:func:`blocks_still_to_come`),
    the attack stands and the blocks are what the policy declares — with the
    creature an ambush cast, or the block an ability made possible. Run out
    with nothing decided, that combat dealt no damage at all: the blocks
    were owed, and the walk stopped at them.

    *attacks*, where given, is filled with the ``permanent_id`` of every
    attacker declared on the way (``CombatOutcome.attackers_declared``).

    *seat*, where given, is the seat the rehearsal is for, and it answers
    its priority in each declare-blockers step on the way
    (:func:`_fight_priority_driver`) — so what it holds for after the blocks
    is part of the fight it is weighed through. Without it (a census's
    :func:`run_out_the_turn`) the copy's priority is passed, as before.
    """
    from .ai_combat import CombatOutcome, run_ai_combat_phase

    if seat is not None:
        previous = game.priority_driver
        game.priority_driver = _fight_priority_driver(game, seat)
        try:
            return _fight_the_combat(game, attacks)
        finally:
            game.priority_driver = previous
    outcome = CombatOutcome()
    if game.current_turn_phase == "combat" and not game.is_game_over():
        run_ai_combat_phase(game, game.active_player_index, outcome=outcome)
        _settle_scratch(game)
    for _ in range(_REHEARSAL_PASSES):
        if not _combat_ahead(game):
            break
        before = (game.current_turn_phase, repr(game.turn_phases_remaining))
        if game.current_turn_phase != "precombat_main":
            # A combat added after this main phase: entered through the
            # turn's own successor, so a skip of it (CR 500.11) is spent.
            if game.enter_next_turn_phase() != "combat":
                break
        run_ai_combat_phase(game, game.active_player_index, outcome=outcome)
        _settle_scratch(game)
        if (game.current_turn_phase, repr(game.turn_phases_remaining)) == before:
            break
    if attacks is not None:
        attacks |= outcome.attackers_declared
    return frozenset(outcome.blocks_declared)


def _run_out_the_turn(
    game, *, through_combat: bool = False, attacks: "set | None" = None,
    seat: "int | None" = None,
) -> frozenset:
    """Take a scratch copy to the end of its turn: a combat whose blocks are
    already declared deals its damage, the end step's triggers fire
    (CR 513.1: "at the beginning of the next end step" — a card exiled
    until then goes back to its owner's hand, a token made for the turn
    goes), then CR 514's cleanup ends every "until end of turn" effect and
    removes marked damage.

    Nothing is *decided* on the way — no attack is declared, no block made —
    so what is read afterwards is what the cast left, and not what a policy
    then did with it. *through_combat* is the exception, asked for by name:
    the turn's combat is fought first (:func:`_fight_the_combat`), and the
    blocks it declared are returned (none, without it). *seat* answers its priority
    in that fight (:func:`_fight_the_combat`).
    """
    blocks = _fight_the_combat(game, attacks, seat=seat) if through_combat else frozenset()
    for _ in range(_REHEARSAL_PASSES):
        if game.current_turn_phase != "combat" or game.is_game_over():
            break
        step = game.current_step
        game.advance_combat_phase()
        game.auto_resolve_pending_choices()
        if game.current_step == step:
            break
    if game.is_game_over():
        return blocks
    if game.current_turn_phase != "ending" and not game.stack:
        game.resolve_end_step(game.active_player_index)
        _settle_scratch(game)
        if game.is_game_over():
            return blocks
    game.resolve_cleanup_step(game.active_player_index)
    _settle_scratch(game)
    return blocks


def position_digest(game) -> dict:
    """Everything a resolution could have changed on *game*, in comparable
    pieces: per seat its hand and graveyard (by name), the size of its
    library, every other field it carries and each permanent it controls;
    then the game's own fields. The bookkeeping every cast writes is left
    out. Two tables built the same way (two scratch copies of one game)
    digest alike exactly when nothing a player could point at differs —
    see :func:`same_position` for the comparison across one cast.
    """
    seats = []
    for seat, player in enumerate(game.players):
        seats.append({
            "hand": sorted(card.name for card in player.hand),
            "graveyard": sorted(card.name for card in player.graveyard),
            # By name, as a graveyard is: a spell cast out of exile, or
            # exiled as it resolves (a flashback, CR 702.34a), is a trip to
            # be told apart from what the spell did (`same_position`).
            "exile": sorted(card.name for card in player.exile),
            # In order: a tutor that puts its find on top, or a spell that
            # arranges the next three draws, has changed something.
            "library": [card.name for card in player.library],
            "fields": {
                # The sideboard by name, as a graveyard is — a Wish's pick
                # leaving it is a change — rather than as the repr of every
                # card a simulated seat holds there, which is the rest of
                # its set (`limited_deck.limited_sideboard`).
                key: (
                    repr(sorted(card.name for card in value))
                    if key == "sideboard" else repr(value)
                )
                for key, value in vars(player).items()
                if key not in _PLAYER_BOOKKEEPING
            },
            "battlefield": sorted(
                (
                    permanent.permanent_id, permanent.card.name,
                    repr(sorted(
                        (key, repr(value))
                        for key, value in vars(permanent).items() if key != "card"
                    )),
                    permanent.is_creature and permanent.effective_power,
                    permanent.is_creature and permanent.effective_toughness,
                )
                for permanent in game.controlled_by(seat)
            ),
        })
    return {
        "seats": seats,
        "game": {
            key: repr(
                _ledger_entries(value) if key == "damage_ledger"
                else _untap_lock_entries(game, value) if key == "untap_step_locks"
                else value
            )
            for key, value in vars(game).items()
            if key not in _GAME_BOOKKEEPING
        },
        "permissions": _permission_entries(game),
    }


def _permission_entries(game) -> list:
    """Every standing permission to cast or play from outside a hand
    (CR 601.3, ``game.cast_permissions``) as ``(what it is, the names of the
    cards it covers)``: the names None for a grant over a whole zone, sorted
    otherwise — which is what one use of it is spent from
    (``cast_permissions.consume``)."""
    entries = []
    for permission in getattr(game, "cast_permissions", None) or ():
        cards = getattr(permission, "cards", None)
        rest = repr(sorted(
            (key, repr(value)) for key, value in vars(permission).items()
            if key != "cards"
        ))
        entries.append((
            rest, None if cards is None else sorted(card.name for card in cards),
        ))
    return sorted(entries, key=repr)


def _untap_lock_entries(game, locks) -> list:
    """The untap-step locks (``engine/untap_step_locks.py``) as what each one
    holds down on the board now: ``(seat, steps, permanent ids)`` for every
    lock binding at least one permanent of that seat.

    A lock is a record on the game, so it changed ``vars(game)`` on every
    resolution, whatever it bound — and a "Creatures target player controls
    don't untap …" (Misstep) aimed at a board with no creature then read as a
    lasting change, so the AI cast it into nothing (MRD W2G4's sim
    differential: the per-permanent marker it replaced changed nothing there,
    and the AI never cast it). Read as what it binds, a lock over nothing is
    no change, and one over a creature is the change the marker was.
    """
    from .subject_filters import subject_matches

    entries = []
    for lock in locks or ():
        bound = sorted(
            permanent.permanent_id
            for permanent in game.controlled_by(lock.seat)
            if subject_matches(game, permanent, lock.described, observer=lock.observer)
        )
        if bound:
            entries.append((lock.seat, lock.steps, tuple(bound)))
    return sorted(entries)


def _ledger_entries(ledger):
    """The damage a turn's ledger records, without the list of spells cast
    beside it — which every cast adds to whatever it does."""
    return getattr(ledger, "entries", ledger)


#: The zones of a seat a spell's own trip runs between, in the order the
#: end of it is looked for: where a resolved spell goes (a graveyard; exile,
#: for a flashback; a hand, bought back), then a library.
_SPELL_ZONES = ("graveyard", "exile", "hand", "library")


def same_position(
    untouched: dict, after: dict, *, spell_name: str | None = None,
    caster: int | None = None, spell_zone: str = "hand",
    spell_seat: int | None = None,
) -> bool:
    """Whether *after* — a :func:`position_digest` taken once *caster* has
    cast *spell_name* out of *spell_zone* and it has resolved — is
    *untouched* with nothing but the spell's own trip in between: from a
    hand to a graveyard, or under a permission (CR 601.3) from a graveyard
    to exile (a flashback), from exile or a library's top to a graveyard —
    in *spell_seat*'s zones where the pile is not the caster's own (a card in
    an opponent's exile goes to its owner's graveyard, CR 400.3)."""
    if not _same_fields(untouched["game"], after["game"]):
        return False
    permissions = list(untouched.get("permissions", ()))
    if spell_name is not None and spell_zone != "hand":
        # The use of the permission the cast was made under, spent as a hand
        # card is: one occurrence of the card out of the first grant that
        # names it, and the grant gone when it names nothing more.
        permissions = _spend_one_use(permissions, spell_name)
    if permissions != list(after.get("permissions", ())):
        return False
    trip_seat = caster if spell_seat is None else spell_seat
    for seat, (was, now) in enumerate(zip(untouched["seats"], after["seats"])):
        zones = {zone: list(now.get(zone, ())) for zone in _SPELL_ZONES}
        if seat == trip_seat and spell_name is not None and spell_zone in zones:
            _put_the_spell_back(was, zones, spell_name, spell_zone)
        if (
            any(zones[zone] != list(was.get(zone, ())) for zone in _SPELL_ZONES)
            or not _same_fields(was["fields"], now["fields"])
            or now["battlefield"] != was["battlefield"]
        ):
            return False
    return True


def _libraries_unordered(digest: dict) -> dict:
    """*digest* (:func:`position_digest`) with each seat's library read as the
    cards it holds, in no order (``Rehearsal.reordered_only``)."""
    return {
        **digest,
        "seats": [
            {**seat, "library": sorted(seat.get("library", ()))}
            for seat in digest["seats"]
        ],
    }


def _spend_one_use(entries: list, name: str) -> list:
    """*entries* (`_permission_entries`) with one use of a grant naming the
    card *name* spent, as ``cast_permissions.consume`` spends it."""
    spent = []
    done = False
    for rest, names in entries:
        if not done and names is not None and name in names:
            names = list(names)
            names.remove(name)
            done = True
            if not names:
                continue
        spent.append((rest, names))
    return sorted(spent, key=repr)


def _put_the_spell_back(was: dict, zones: dict, name: str, origin: str) -> None:
    """Undo, in *zones* (one seat's, read once a spell has resolved), the
    spell's own trip: back into *origin* as many copies as left it, and out
    of the zones that gained one — and nothing more, so a copy that was in a
    graveyard before the cast is not taken for the one that arrived. A spell
    bought back (CR 702.27a) never left its hand, and has no trip."""
    spent = list(was.get(origin, ())).count(name) - zones[origin].count(name)
    if spent <= 0:
        return
    if origin == "library":
        # Cast off the top (CR 601.3: Future Sight, Mystic Snake's hosts).
        zones["library"] = [name] * spent + zones["library"]
    else:
        zones[origin] = sorted([*zones[origin], *[name] * spent])
    for zone in _SPELL_ZONES:
        if zone == origin:
            continue
        arrived = zones[zone].count(name) - list(was.get(zone, ())).count(name)
        while arrived > 0 and spent > 0:
            zones[zone].remove(name)
            arrived -= 1
            spent -= 1


#: How an attribute nothing has written yet reads once something has cleared
#: it: a record the engine creates on first use and empties afterwards is not
#: a difference between a table that used it and one that never did.
_EMPTY_READINGS = frozenset({
    "None", "False", "0", "0.0", "''", "[]", "()", "{}", "set()", "frozenset()",
})


def _same_fields(was: dict, now: dict) -> bool:
    """Whether two ``{field: repr}`` readings agree, a field only one of them
    has counting as empty on the other."""
    for key in was.keys() | now.keys():
        if was.get(key, None) == now.get(key, None):
            continue
        if key in was and key in now:
            return False
        if (was.get(key) or now.get(key)) not in _EMPTY_READINGS:
            return False
    return True


def _measured(game, *, through_combat: bool = False, seat: "int | None" = None) -> dict:
    """A scratch copy read twice: as it stands, then run out to the end of
    its turn (with its combat fought, if *through_combat*, *seat* answering
    its priority after the blocks). The copy itself is kept beside the
    readings, for the one more that is taken only when it is needed
    (:func:`_lasting_digest`)."""
    reading = {
        "digest": position_digest(game),
        "now": standings(game, now=True),
    }
    reading["attacks"] = set()
    reading["blocks"] = _run_out_the_turn(
        game, through_combat=through_combat, attacks=reading["attacks"], seat=seat,
    )
    reading["lasting"] = standings(game, now=False)
    reading["table"] = game
    return reading


def _lasting_digest(reading: dict) -> dict:
    """:func:`position_digest` of a measured copy **once its turn has run
    out** — read on first asking and kept. Whether anything a cast changed is
    still changed by then is a question only some casts raise (the ones no
    standing shows a lasting difference for), and a digest is not free.

    Read with the record of **what damage was dealt** left out
    (:func:`forget_damage_history`): by the end of the turn the damage
    itself is gone (CR 514.2), and what it did — a life lost, a creature
    dead — is in the table already. And as the next turn begins: the
    opponent's permanents as its untap step will leave them, and every
    "this turn" record that turn's bookkeeping resets reset
    (:func:`untap_for_the_next_turn`)."""
    if "lasting_digest" not in reading:
        forget_damage_history(reading["table"])
        untap_for_the_next_turn(reading["table"])
        reading["lasting_digest"] = position_digest(reading["table"])
    return reading["lasting_digest"]


def untap_for_the_next_turn(game) -> None:
    """Untap, on a scratch copy whose turn has run out, what the next turn's
    untap step untaps (CR 502.3): the permanents of the player that turn is
    for — in a two-player game with no extra turn to come, the active
    player's opponent.

    A tap of an opposing creature after the turn's fight was over, or before
    a fight it took no part in, was a change that lasted to the end of the
    turn and to nothing after it: Twiddle, Tidal Bore, Winter Blast, Chain
    Stasis cast at a creature with nothing left to block, at the base score.
    A permanent its untap step would *not* untap is told apart from one it
    would by what keeps it tapped, which is a record of its own ("doesn't
    untap during its controller's next untap step") or a static ability on
    the table; the first is still in the digest, and the second is the
    approximation, read as untapped. With more than two seats, or an extra
    turn queued (CR 500.7), the next untap step is not this one's to guess,
    and nothing is untapped.

    The same turn's **bookkeeping** is run too (``Game.begin_turn_bookkeeping``,
    the one both drivers call as a turn begins): every "this turn" record it
    resets — creatures that died, lands played, cards drawn — is a record of
    a turn that is over, and a token made for the turn and sacrificed at its
    end step "changed" how many creatures died this turn and nothing else
    (Tidal Wave, cast in its caster's own main phase).
    """
    if len(game.players) != 2 or getattr(game, "extra_turn_queue", None):
        return
    if game.is_game_over():
        return
    upcoming = 1 - game.active_player_index
    for permanent in game.controlled_by(upcoming):
        permanent.tapped = False
    game.begin_turn_bookkeeping(upcoming)


def forget_damage_history(game) -> None:
    """Drop, from a scratch copy whose turn has run out, the two records of
    damage that outlive the damage: the turn's ledger of who dealt what
    (``damage_ledger``, cleared at the next turn's start) and each source's
    "who have I damaged this game" (``damage_events.DAMAGED_THIS_GAME``).

    Left in, a fight that went differently by nothing anybody could point at
    was a change that lasted: the caster's own Fog in its main phase, under
    which its 2/2 attacked into a 0/4 Wall and dealt it nothing instead of
    two damage that cleanup would have removed, "changed" two records and was
    cast at the base score. The Fallen's "each opponent … it has dealt damage
    to this game" is the one reader of the second, and is the price.
    """
    from .damage_events import DAMAGED_THIS_GAME

    ledger = getattr(game, "damage_ledger", None)
    entries = getattr(ledger, "entries", None)
    if isinstance(entries, list):
        entries.clear()
    for permanent in [
        *game.all_permanents(),
        *(permanent for player in game.players for permanent in player.phased_out),
    ]:
        permanent.metadata.pop(DAMAGED_THIS_GAME, None)


def _untouched(
    game, seat: int, *, carried=None, detach: bool = False, without=None,
    without_key=None, through_combat: bool = False,
) -> dict:
    """The table with nothing cast: whatever is on the stack resolves, and
    the turn runs out. What every candidate of one decision is measured
    against (:func:`deliberating`).

    *without* prepares that table when "nothing" has to be arranged, and
    *without_key* says which arrangement it is, for the reading to be kept
    under: a triggered ability whose mode is the question is taken off the
    copy's stack, since an ability with no mode chosen never resolves
    (CR 700.2b); a cast paid for by tapping lands is compared with a table on
    which those lands are tapped too, so that the payment is not mistaken for
    something the spell did.
    """
    cache = _DELIBERATION.get()
    # Per seat: the table with nothing cast is the table as *seat* can know
    # it, and two seats do not see the same one.
    slot = ("untouched", seat, id(carried), detach, without_key, through_combat)
    if cache is not None and slot in cache:
        return cache[slot]
    clone, carried = _scratch(game, carried, detach, seat)
    if without is not None:
        without(clone, carried)
    _settle_scratch(clone)
    could_cast = _casts_open(clone, seat)
    reading = _measured(clone, through_combat=through_combat, seat=seat)
    reading["could_cast"] = could_cast
    if cache is not None:
        cache[slot] = reading
    return reading


def _casts_open(game, seat: int) -> frozenset:
    """``(zone, spell)`` for every cast *seat* may make from outside its hand
    right now (:func:`permitted_casts`)."""
    return frozenset(
        (permitted.zone, permitted.spell.name) for permitted in permitted_casts(game, seat)
    )


def _mana_value_on_the_stack(game) -> int:
    """The mana value of the object on top of *game*'s stack — X included
    (CR 202.3e) — or 0 with nothing there: what a cast just put on the stack
    was charged, read before it resolves — off what the spell says
    (``text_changes.spell_text_card``), the reader every stack object's
    characteristics go through."""
    if not game.stack:
        return 0
    item = game.stack[-1]
    card = spell_text_card(item)
    value = int(float(getattr(card, "cmc", 0) or 0))
    x_count = (getattr(card, "mana_cost", "") or "").upper().count("{X}")
    return value + x_count * int(getattr(item, "x_value", 0) or 0)


def _made_more_mana_than_it_cost(clone, seat: int, pools: list, cost: int) -> bool:
    """Whether a resolution on *clone* left *seat* more mana than the cast
    was charged (*cost*, its mana value): the mana that **appeared** in
    *seat*'s pool across the resolution (*pools* is every pool as the
    payment left it), above what paying for it took out.

    A ritual is mana gone by the end of the turn because it is spent, on a
    cast this rehearsal is not a rehearsal of — so the mana it made is not
    nothing (``Rehearsal.made_mana``). Only mana **beyond its price** is
    that: "Target player activates a mana ability of each land they control
    … you add the mana lost this way" (Drain Power) at an opponent with one
    Island pays {U}{U} for {U}, and was proposed at the base score for the
    one mana it "made" (the idle census, kg3). Dark Ritual makes three for
    one. Mana appearing in another seat's pool is nothing this seat spends.
    """
    was = pools[seat] if 0 <= seat < len(pools) else {}
    appeared = sum(
        max(0, int(amount or 0) - int(was.get(symbol, 0) or 0))
        for symbol, amount in clone.players[seat].mana_pool.items()
    )
    return appeared > cost


def _opened_a_cast(game, seat: int, could_cast: frozenset, spell_name) -> bool:
    """Whether *game* — a copy on which a cast of *spell_name* has just
    resolved — lets *seat* make a cast from outside its hand that the table
    with nothing cast did not (*could_cast*, :func:`_casts_open`), its own card
    aside, **and that it could make now** (:func:`_could_make_now`).

    A flashback card cast from a hand is a graveyard card its owner may cast,
    and that is the card spent, not a cast gained. A permission over cards the
    seat cannot pay for is a permission spent on nothing: Shaman's Trance
    opening three {50} cards in an opponent's graveyard, with forty mana
    floating, was proposed for it at ``SPELL_BASE_SCORE`` (the ODY zone-cast
    census, measured at the Judgment integration chain)."""
    return any(
        permitted.spell.name != spell_name
        and (permitted.zone, permitted.spell.name) not in could_cast
        and _could_make_now(game, seat, permitted)
        for permitted in permitted_casts(game, seat)
    )


def _could_make_now(game, seat: int, permitted) -> bool:
    """Whether *seat* could make the cast *permitted* (a ``PermittedCast``) on
    *game* as it stands — the engine's own gates, asked in the order the cast
    path asks them, none of them a rehearsal:

    * nothing forbids it (CR 601.3, ``cast_prohibition``, which also binds a
      land play);
    * it is the time for it: a land drop left at sorcery timing for a land
      (CR 305.1–305.2), sorcery timing (CR 307.1) unless the spell may be cast
      as an instant (``casts_at_instant_speed``);
    * the price can be paid — the alternative cost the permission requires
      through the cast path's gate for what it asks beside mana (CR 601.2h),
      and the mana through the payment planner (``ai_payment._cost_for`` under
      the permission, CR 601.2f over it; ``_plan_land_taps``) out of what the
      seat has left. An X is priced at 0, the least it may announce.
    """
    from .ai_payment import _cost_for, _paying_for, _plan_land_taps
    from .ai_weighed_cast import casting_under
    from .cast_prohibitions import cast_prohibition
    from .cast_timing import a_sorcery_could_be_cast, casts_at_instant_speed

    spell = permitted.spell
    if cast_prohibition(game, seat, spell, from_zone=permitted.zone) is not None:
        return False
    if spell.primary_type == "land":
        return a_sorcery_could_be_cast(game, seat) and game._may_play_another_land(seat)
    if not (
        casts_at_instant_speed(spell, game, seat) or a_sorcery_could_be_cast(game, seat)
    ):
        return False
    own_graveyard_slot = (
        permitted.index
        if permitted.zone == "graveyard" and permitted.owner_seat == seat else None
    )
    if permitted.cost is not None and game._unpayable_alternative_cost(
        seat, spell, permitted.cost, spell_hand_index=None,
        spell_graveyard_slot=own_graveyard_slot,
    ) is not None:
        return False
    if not game.enforce_mana_costs:
        return True
    player = game.players[seat]
    with casting_under(permitted), _paying_for(spell):
        return _plan_land_taps(game, player, _cost_for(game, player, spell, None)) is not None


def rehearse(
    game, seat: int, perform, *, spell_name: str | None = None,
    leaves_hand: bool = True, key=None, carried=None, detach: bool = False,
    without=None, without_key=None, label: str | None = None,
    through_combat: bool = False, spell_zone: str | None = None,
    spell_seat: int | None = None,
) -> "Rehearsal | None":
    """Carry *perform* out on a scratch copy of *game* and report what it did
    to *seat*'s position — or None when no rehearsal could be run.

    *perform* takes the copy and makes one cast on it exactly as an executor
    would (``ai_policy`` hands the announcement it is about to propose),
    returning the engine's result. The copy then resolves its stack with
    every prompt on its default, is read (:func:`position_digest`,
    ``ai_standing.standings``), is run out to the end of its turn and is read
    again. The same two readings of the table **with nothing cast** are what it is
    compared with.

    **Why a rehearsal and not a table of effect families.** The valuation
    this replaced was a set of probes on a card's text, and the obvious next
    step — a value per instruction kind — is the same list one layer down:
    the pool's instants and sorceries resolve 265 kinds, and a kind with no
    entry would score the flat number an unread word did. Carrying the
    compiled program out is the one reading that covers every kind there is
    and every kind still to come: a -2/-2 is weighed against its target's
    toughness because the engine applies it and the creature dies or does
    not; a destroy counts what it removes because that permanent is gone from
    the standing; a discard at an empty hand is worth nothing because nothing
    moved.

    **What it must not do is look ahead, or look at what is hidden.** On the
    copy every library is in a random order and every other player's hand is
    dealt again out of what *seat* cannot tell apart
    (``ai_scratch_copy.conceal_from``), and its randomness is reseeded
    (``ai_scratch_copy._rehearsal_seed``) — so a draw, a discard that takes "a noncreature, nonland card", a search's shuffle or a
    coin flip in a rehearsal says what such a cast is *like*, never what the
    real one will turn up; the real game's random sequence is put back exactly
    as it was. What a rehearsal does see is what the seat sees: the table,
    its own hand, how many cards everybody else is holding.

    None rather than a guess when it cannot run: from inside another
    rehearsal (:func:`rehearsing`), on a table that is part-way through a
    resolution (``ai_scratch_copy.mid_resolution``), or when the copy raises
    — a crash in a rehearsal is not a crash in the game, and is not nothing either:
    it is written into ``REHEARSALS_RAISED`` under *spell_name* (or *label*,
    for an answer that is not a cast), which a simulated run reports and
    fails on.

    *carried* is an object copied with the game and handed to *perform*
    beside the copy — the prompt being answered, which holds its own stack
    object. *detach* rehearses on a copy cut loose from a resolution the
    original is in the middle of (``ai_scratch_copy._detach``), for an
    answer that is its own stack object — or, as ``"abstract"``, on one that owes nothing at
    all, for a question about a card rather than about this moment; and
    *without* arranges the table "with nothing done" where that takes
    arranging (:func:`_untouched`).

    Asked once per *key* in a deliberation (:func:`deliberating`): a chooser
    that weighs a target and then builds the cast that names it is asking the
    same question twice, and a rehearsal costs a cast.

    *spell_zone* is the zone a spell cast **under a permission** is cast
    out of (CR 601.3: a graveyard, an exile, a library's top), whose trip
    out of it (in *spell_seat*'s zones, for a pile that is not the
    caster's) is the cast's own and not something it did — a flashback Fog
    that only exiled itself changed as little as one cast from a hand. A
    hand cast is *leaves_hand*'s, and a card the seat does not hold is
    neither: its arrival in a graveyard is read as a change.

    **No combat is fought on the way to the end of the turn** — unless
    *through_combat* asks for it, on the cast and on the table it is compared
    with alike (:func:`_fight_the_combat`). That is a second, dearer reading
    for the casts the first one cannot price: one made before the fight
    whose whole trace is over by the end of the turn (``Rehearsal.fleeting``),
    or whose good is. A pump was worth ``TEMPORARY_SHARE`` of the body it
    lent whether or not anything was then done with it, and a Fog cast in
    its caster's own main phase measured as nothing and was cast.
    """
    asked = dict(
        spell_name=spell_name, leaves_hand=leaves_hand, carried=carried,
        detach=detach, without=without, without_key=without_key, label=label,
        through_combat=through_combat, spell_zone=spell_zone,
        spell_seat=spell_seat,
    )
    cache = _DELIBERATION.get()
    if cache is None or key is None:
        return _rehearse(game, seat, perform, **asked)
    slot = ("rehearsal", key)
    if slot not in cache:
        cache[slot] = _rehearse(game, seat, perform, **asked)
    return cache[slot]


def _rehearse(
    game, seat: int, perform, *, spell_name: str | None = None,
    leaves_hand: bool = True, carried=None, detach: bool = False, without=None,
    without_key=None, label: str | None = None, through_combat: bool = False,
    spell_zone: str | None = None, spell_seat: int | None = None,
) -> "Rehearsal | None":
    """:func:`rehearse`, uncached."""
    import random

    if _REHEARSING.get():
        return None
    if held_for_an_answer(game) and detach != "abstract":
        return None
    if mid_resolution(game) and not detach:
        return None
    token = _REHEARSING.set(True)
    real_sequence = random.getstate()
    try:
        untouched = _untouched(
            game, seat, carried=carried, detach=detach, without=without,
            without_key=without_key, through_combat=through_combat,
        )
        clone, copied = _scratch(game, carried, detach, seat)
        result = perform(clone) if carried is None else perform(clone, copied)
        # Paid for, and not yet resolved: what is in each pool now is what
        # the cost left there. Mana that **appears** after this is the
        # spell's doing (a ritual is a cast), which the digest cannot say —
        # it leaves the pools out, since paying moves them too. Mana that
        # goes is not: "unless they pay {1}", paid, is a spell that did
        # nothing and cost a mana more.
        pools = [dict(player.mana_pool) for player in clone.players]
        cost = _mana_value_on_the_stack(clone)
        if not getattr(result, "supported", False):
            return Rehearsal(
                accepted=False, refusal=str(getattr(result, "details", "") or ""),
            )
        _settle_scratch(clone)
        # Whether a fight is still to come once the cast has resolved — read
        # off the copy, because a cast can be what adds one.
        combat_ahead = clone.active_player_index == seat and _combat_ahead(clone)
        # …and whether there is anything to fight it with, read off the same
        # copy: a cast can be what makes the creature (Animate Land).
        creature_ahead = has_a_creature_to_fight_with(clone, seat)
        made_mana = _made_more_mana_than_it_cost(clone, seat, pools, cost)
        opened_a_cast = _opened_a_cast(
            clone, seat, untouched["could_cast"], spell_name,
        )
        reading = _measured(clone, through_combat=through_combat, seat=seat)
        # Weighed for the seat that makes *seat*'s decisions (CR 723.5): itself,
        # unless another player controls it this turn (Mindslaver), whose
        # standing a choice made for it is then measured by.
        served = served_seat(game, seat)
        now = standing_swing(untouched["now"], reading["now"], served)
        lasting = standing_swing(untouched["lasting"], reading["lasting"], served)
        # The zone the spell's own trip starts in: the hand it is spent from,
        # or the one a permission let it be cast out of; none for a card the
        # seat does not hold.
        zone = "hand" if leaves_hand else spell_zone
        returned = spell_name if zone is not None else None
        # Whether anything changed is read off the table, with the spell's own
        # trip taken out (`same_position`) — and before the card is accounted
        # for below, or a spell bought back with nothing else done would read
        # as a change worth a card.
        changed = made_mana or not same_position(
            untouched["digest"], reading["digest"], spell_name=returned, caster=seat,
            spell_zone=zone or "hand", spell_seat=spell_seat,
        )
        # Whether the libraries' order is all of it (``Rehearsal.
        # reordered_only``): the same digests with every library read as the
        # cards it holds. Only where no spell made a trip, whose undoing reads
        # a library's top.
        reordered_only = (
            changed and not made_mana and returned is None
            and same_position(
                _libraries_unordered(untouched["digest"]),
                _libraries_unordered(reading["digest"]), caster=seat,
            )
        )
        # Whether any of it is still there once the turn is over. Asked of
        # the table only where the standings leave it open — a lasting swing
        # is a lasting change — because the answer costs a digest of each
        # copy. "Leave it open" is a lasting swing of nothing but the spell's
        # own card: the card spent and nothing else, or (a spell bought back,
        # CR 702.27a) not even that. The table then says which it is — a
        # card drawn in place of the one spent is a hand that differs.
        #
        # **A game that ended on both copies has no "end of the turn"** to
        # read: CR 514's cleanup never runs on it, so every "until end of
        # turn" record the cast left is still on the table and the digests
        # differ by it alone. With the same standings — both copies over the
        # same way — what the cast changed bought nothing that lasts: a +0/+0
        # Wirewood Pride before an attack that was lethal without it read as a
        # lasting change and was cast (ONS W1G7; seed 11, black, game 6).
        ended = untouched["table"].is_game_over() and reading["table"].is_game_over()
        # The spell's own card, read off the standings by where its trip
        # started: from a hand it is spent (a card down) or bought back
        # (CR 702.27a: even); from a zone a permission opened (CR 601.3) it
        # ends in a graveyard or an exile (even) or is bought back into its
        # owner's hand — a card up for the caster, or down when the pile was
        # an opponent's (CR 400.3). The digest below decides whether that is
        # all there is; this only says when to ask it. Without the last case
        # a Mind Games bought back out of an exile always read as lasting, so
        # a target whose fight left nothing was weighed as one that left the
        # card, and the cast from the exile named another target than the
        # same cast from the hand (the zone-cast census, LGN promotion).
        if leaves_hand:
            own_card: tuple = (-CARD_WORTH,)
        elif spell_zone is not None:
            own_card = (CARD_WORTH if spell_seat in (None, seat) else -CARD_WORTH,)
        else:
            own_card = ()
        fleeting = (
            changed
            and (
                abs(lasting) < _NO_SWING
                or any(abs(lasting - card) < _NO_SWING for card in own_card)
            )
            and (ended or same_position(
                _lasting_digest(untouched), _lasting_digest(reading),
                spell_name=returned, caster=seat, spell_zone=zone or "hand",
                spell_seat=spell_seat,
            ))
        )
        if leaves_hand:
            # The card a cast is made with is spent by every cast, so it is
            # not part of what this one did: it is given back. A spell that
            # comes back to the hand by itself (buyback, CR 702.27a) is then a
            # card to the good, which is what its price is weighed against.
            now += CARD_WORTH
            lasting += CARD_WORTH
        if through_combat:
            # Read once the fight is over: there is no "right after" to tell
            # from "at the end of the turn" that the fight has not passed
            # through, so the lasting reading is the measure.
            now = lasting
        return Rehearsal(
            accepted=True, changed=changed, now=now, lasting=lasting,
            fleeting=fleeting, made_mana=made_mana, through_combat=through_combat,
            combat_ahead=combat_ahead, opened_a_cast=opened_a_cast,
            creature_ahead=creature_ahead,
            blocks_added=bool(reading["blocks"] - untouched["blocks"]),
            declarations_changed=(
                reading["attacks"] != untouched["attacks"]
                or reading["blocks"] != untouched["blocks"]
            ),
            reordered_only=reordered_only,
        )
    except Exception as raised:
        _note_raised(label or spell_name, raised)
        return None
    finally:
        random.setstate(real_sequence)
        _REHEARSING.reset(token)


__all__ = [
    "REHEARSALS_RAISED",
    "Rehearsal",
    "blocks_owed",
    "blocks_still_to_come",
    "combat_is_still_to_come",
    "forget_damage_history",
    "untap_for_the_next_turn",
    "has_a_creature_to_fight_with",
    "pays_before_the_blocks",
    "position_digest",
    "priced_by_the_fight",
    "rehearse",
    "rehearsing",
    "run_out_the_turn",
    "same_position",
]

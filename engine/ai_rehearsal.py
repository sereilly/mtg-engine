"""The measure: what a seat's position is worth, and what one cast does to
it, found by carrying the cast out on a scratch copy of the game.

**"Larger" is said here, once** (the comment over the worth constants says
why). A position is :func:`seat_standing` — life, priced in tiers, cards in
hand, and :func:`permanent_worth` read through the layers — and what a cast
does is the swing between two standings, what lasts counted in full and
what ends this turn at ``TEMPORARY_SHARE`` (:func:`swing_worth`).

:func:`rehearse` asks the engine rather than guessing: it copies the game
(:func:`scratch_copy`), deals what the asking seat cannot see again
(:func:`conceal_from`, CR 400.2), carries the candidate out, resolves it on
defaults, and reads the table right after and once the turn has run out —
with its combat fought, where the cast comes before one
(:func:`run_out_the_turn`) — against the same copy with nothing cast, read
once per decision inside :func:`deliberating`. The seeded RNG is saved and
restored around every rehearsal, so a seed still reproduces a run. A
rehearsal that raises is "cannot be weighed" to the policy and a line in
``REHEARSALS_RAISED`` to the simulator, which reports it; and a table owing
the rest of a resolution is not copied at all (:func:`mid_resolution`).

Two readers ask the measure, and that is why it is in the valuation family
and not beside the policy's weights: the policy, which predicts with it, and
the mode census (``tests/ai/test_ai_mode_chooser_census.py``), which makes
the cast for real on a board of its own and measures with it. Two prices from
two functions would be a census asking the scorer whether the scorer is
right.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .ai_weighed_cast import permitted_casts


# --- The measure: what a seat's position is worth -----------------------------
#
# **"Larger" is said here, once.** Which of two castable bullets takes the
# larger thing off the opposing board or adds the larger thing to its caster's
# own, which of two legal targets is the better one, whether a cast does
# anything at all — each is a comparison of two positions, and a comparison
# needs one unit. The unit is the life-equivalent the toll prices already use
# (``ai_prompts._toll_loss_price``): a point of life near twenty is worth one.
# (Those prices are an older list in the same unit and put a card at two; the
# two lists answer different questions and nothing here reconciles them.)
#
# Two readers ask it, and that is why it lives in this module rather than
# beside the weights in ``ai_policy``: the policy, which *rehearses* a cast
# (:func:`rehearse`) and prices what it changed; and the mode census
# (``tests/ai/test_ai_mode_chooser_census.py``), which makes the cast for real
# on a board of its own and prices what that changed. Two prices from two
# functions would be a census asking the scorer whether the scorer is right.
#
# What it reads is the board as the layers compute it — never a card's text.

#: A card in hand: about four life. The old cast weight said the same thing in
#: another place ("worth exactly 4.0 per net card", `ai_scoring._score_cast`).
CARD_WORTH = 4.0
#: What any permanent is worth just by being one, before its stats and its
#: cost are added: the card it is. **Never less than that card in a hand**,
#: or returning a permanent to its owner's hand would measure as a gift to
#: its owner — which is what a floor of two and a half made of every bounce
#: aimed at something that had cost nothing. A Mox is worth a card.
PERMANENT_WORTH = CARD_WORTH
#: The same floor for a token, which is not a card: nothing was spent from a
#: hand to make it and nothing comes back if it leaves (CR 111.7). So a 2/2
#: destroyed outweighs a 2/2 token made, by the card that was under it.
TOKEN_WORTH = 1.5
#: A land on top of that: the card and the land drop it took.
LAND_WORTH = 1.5
#: How many lands a seat is counted as needing, and what one beyond them is
#: worth: half a life. The same six ``ai_casts.BUYBACK_PERMANENTS_KEPT``
#: keeps before a seat pays a buyback in lands — a seventh land is the one a
#: seat gives up for a card, and the one a Stone Rain is wasted on.
LANDS_WORTH_KEEPING = 6
SPARE_LAND_WORTH = 0.5
#: A creature's body, per point.
POWER_WORTH = 1.4
TOUGHNESS_WORTH = 1.1
#: An evasion ability, per point of the power it carries past a blocker.
EVASION_WORTH = 0.5
#: Any other combat keyword, flat.
COMBAT_KEYWORD_WORTH = 1.0
#: How much of a creature's body is missing while it is tapped: all of it —
#: it neither attacks nor blocks until it untaps, which is what a body is
#: for. A reading of the board **now** only; the card under it is still
#: there, and so is whatever it does without tapping.
TAPPED_SHARE = 1.0
#: How much a change that is gone by the end of the turn counts for against
#: one that is still there: a +3/+3 until end of turn is a quarter of a
#: +3/+3 counter, a creature phased out a quarter of a creature destroyed.
TEMPORARY_SHARE = 0.25
#: A seat that has lost, or will at its next draw.
LOST = 1000.0

_EVASION_KEYWORDS = frozenset({
    "flying", "fear", "shadow", "horsemanship", "menace", "landwalk",
    "swampwalk", "forestwalk", "islandwalk", "mountainwalk", "plainswalk",
    "desertwalk",
})
_COMBAT_KEYWORDS = frozenset({
    "first strike", "double strike", "trample", "vigilance", "lifelink",
    "deathtouch", "indestructible", "reach", "protection", "hexproof",
    "shroud", "banding", "flanking", "rampage",
})

#: Life is worth more the less of it there is: ``(up to this total, each
#: point)``, and the last rate for everything above the last tier. Three
#: damage is three at twenty life and six at five; five life gained at twenty
#: is two and a half, which is why it loses to a dead creature.
_LIFE_TIERS = ((5, 2.0), (10, 1.5), (20, 1.0))
_LIFE_ABOVE = 0.5


def life_worth(life: int) -> float:
    """What a life total is worth: concave, and ``-LOST`` at zero or less."""
    if life <= 0:
        return -LOST
    worth, floor = 0.0, 0
    for ceiling, rate in _LIFE_TIERS:
        if life <= floor:
            break
        worth += (min(life, ceiling) - floor) * rate
        floor = ceiling
    if life > floor:
        worth += (life - floor) * _LIFE_ABOVE
    return worth


def permanent_worth(permanent, *, now: bool = True) -> float:
    """What *permanent* is worth to whoever controls it.

    The floor every permanent has, what it cost, and for a creature its body
    and its keywords — all read through CR 613's accessors, so a creature
    under a +3/+3 is worth the 5/5 it currently is and one that lost flying
    is worth what is left.

    *now* is the board as it stands this instant: a tapped creature counts
    for less (``TAPPED_SHARE``). ``now=False`` is the reading for what will
    still be true once the turn's temporary effects are over, where a tap is
    not a difference.
    """
    from .layer_bridge import computed_abilities

    # What it cost, read as CR 613 reads it: a Clone is worth the mana value
    # of what it copies (CR 707.2).
    worth = (
        TOKEN_WORTH if permanent.metadata.get("is_token") else PERMANENT_WORTH
    ) + float(permanent.effective_card.cmc or 0)
    if permanent.has_type("land"):
        worth += LAND_WORTH
    if not permanent.is_creature:
        return worth
    power = max(0, permanent.effective_power)
    body = power * POWER_WORTH + max(0, permanent.effective_toughness) * TOUGHNESS_WORTH
    abilities = computed_abilities(permanent)
    body += power * EVASION_WORTH * len(_EVASION_KEYWORDS & abilities)
    body += COMBAT_KEYWORD_WORTH * len(_COMBAT_KEYWORDS & abilities)
    if now and permanent.tapped and not permanent.attacking:
        # An attacker is tapped because it is fighting: its body is in use,
        # not missing.
        body *= 1.0 - TAPPED_SHARE
    return worth + body


def seat_standing(game, seat: int, *, now: bool = True) -> float:
    """What *seat*'s position is worth: its life, the cards in its hand and
    the permanents it controls (:func:`permanent_worth`).

    A seat that has lost is ``-LOST``, and so — less by half, so that a real
    loss still ranks below it — is one with no library left to draw from
    (CR 704.5b on its next draw). ``now=False`` also counts what has phased
    out: CR 702.26 brings it back.
    """
    player = game.players[seat]
    if player.lost or player.life <= 0:
        return -LOST
    worth = life_worth(player.life) + CARD_WORTH * len(player.hand)
    if not player.library:
        worth -= LOST / 2
    lands = 0
    for permanent in game.controlled_by(seat):
        worth += permanent_worth(permanent, now=now)
        lands += bool(permanent.has_type("land"))
    if not now:
        for permanent in player.phased_out:
            worth += permanent_worth(permanent, now=False)
    # Each land beyond the ones a seat needs is worth `SPARE_LAND_WORTH`, not
    # a card and a land drop.
    worth -= max(0, lands - LANDS_WORTH_KEEPING) * (
        PERMANENT_WORTH + LAND_WORTH - SPARE_LAND_WORTH
    )
    return worth


def standing_swing(before: tuple, after: tuple, seat: int) -> float:
    """How far *seat* moved against the rest of the table between two
    readings (one standing per seat): its own change less every other
    seat's."""
    return sum(
        (after[index] - before[index]) * (1.0 if index == seat else -1.0)
        for index in range(len(before))
    )


def swing_worth(now: float, lasting: float) -> float:
    """One number for a change measured twice — as the board stood right
    after it (*now*) and with the turn's temporary effects over (*lasting*).

    What lasts counts in full; what is there now and gone by then counts for
    ``TEMPORARY_SHARE`` of itself. **This is what "larger" means**, for the
    policy choosing between two casts and for the census judging the choice.
    """
    return lasting + TEMPORARY_SHARE * (now - lasting)


def standings(game, *, now: bool = True) -> tuple:
    """:func:`seat_standing` for every seat, in seat order."""
    return tuple(
        seat_standing(game, seat, now=now) for seat in range(len(game.players))
    )


# --- Rehearsal: what a cast would do, asked of the engine ---------------------

#: What every cast changes whatever it does — the zones the spell itself moves
#: through (read separately), the mana that paid for it, the turn's count of
#: spells. Left in, a resolution that did nothing still reads as a change.
#: Mana the spell *makes* is read where it can be told from mana the spell
#: cost: across its resolution (:func:`_rehearse`).
_PLAYER_BOOKKEEPING = frozenset({
    "hand", "graveyard", "library", "exile", "mana_pool", "battlefield",
    "spells_cast_this_turn",
})
#: The same for the game's own fields: the table itself (read separately),
#: the log, the stack and who has priority, and the per-turn ledgers a cast
#: writes whether or not it does anything.
_GAME_BOOKKEEPING = frozenset({
    "players", "log", "stack", "priority_player_index", "priority_pass_count",
    "prompt_driver", "interactive_seats", "enforce_mana_costs",
    "resolving_seats", "resolving_stack_item", "pending_choices",
    "current_phase", "current_turn_phase", "current_step",
    # Read apart, by the names of the cards each permission covers
    # (`_permission_entries`), so that the one a cast spends can be told
    # apart from what the cast did.
    "cast_permissions",
    # "Did this seat cast a spell during its last turn" (Arboria, CR 506.3),
    # folded out of `spells_cast_this_turn` as the next turn begins — which
    # is where the end-of-turn reading is taken (`untap_for_the_next_turn`),
    # so every cast would read as having changed it.
    "last_own_turn_activity",
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
        the caster's :func:`standing_swing` against the same table with
        nothing cast — as the board stood right after the resolution, and
        with the turn's temporary effects over;
    ``swing``
        :func:`swing_worth` of the two;
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
    ``opened_a_cast``
        once it had resolved, the caster could cast something from outside
        its hand it could not before (CR 601.3: "you may play cards from your
        graveyard this turn") — fleeting like mana, and like mana not
        nothing: it is spent on a cast this rehearsal is not a rehearsal of.
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


def _every_card(game):
    """Every card object a zone of *game* holds. A `CardDefinition` is
    immutable and shared — a deck is one object per printing, repeated — so a
    scratch copy shares them too rather than copying a library card by card."""
    for player in game.players:
        for zone in (
            player.hand, player.library, player.graveyard, player.exile,
            getattr(player, "command_zone", ()) or (),
        ):
            yield from zone
        for permanent in player.phased_out:
            yield permanent.card
    for permanent in game.all_permanents():
        yield permanent.card
    for item in game.stack:
        card = getattr(item, "card", None)
        if card is not None:
            yield card


def mid_resolution(game) -> bool:
    """Whether *game* is part-way through carrying something out — an object
    resolving, a loop with steps still owed (``resume_stack``), a resolution
    held for an answer, a CR 616.1 choice outstanding.

    Such a table is not copied as it stands. What it owes is recorded as
    continuations — closures over the game they were made on — and a copy of
    one would run its remaining steps on the **original**. A policy asked in
    that moment gets no rehearsal and falls back to its stated default,
    unless what it is asking can be answered on a copy cut loose from the
    resolution (:func:`_detach`).
    """
    return bool(
        game.resume_stack
        or game.resolving_stack_item is not None
        or game.resolving_seats
        or held_for_an_answer(game)
    )


def held_for_an_answer(game) -> bool:
    """The part of :func:`mid_resolution` no copy can be cut loose from: a
    resolution **waiting on somebody** — a CR 616.1 choice outstanding, an
    object held on the stack for an interactive seat, a queued prompt that
    carries its own continuation. Each of those is a closure the copy would
    still be holding."""
    return bool(
        game.pending_replacement_choices
        or any(
            getattr(item, "finish_resolution", None) is not None
            or getattr(item, "resolution_held", False)
            for item in game.stack
        )
        or any(
            callable(value)
            for choice in game.pending_choices
            for value in choice.data.values()
        )
    )


def _detach(game, *, owing_nothing: bool = False) -> None:
    """Cut a scratch copy loose from the resolution its original is in the
    middle of: nothing is resolving on the copy and no loop has steps owed.

    For a question whose answer is its own stack object — the mode of a
    triggered ability, chosen as the ability is put on the stack (CR 603.3c)
    while the spell that caused it is still resolving. The copy never finishes
    that spell; what it carries out is the ability, in each mode, and the
    modes are compared with each other.

    *owing_nothing* goes further, for a question about **a card in the
    abstract** — what is this one worth to hold, asked by a search part-way
    through its own resolution: every prompt the copy was owed and every
    object held on its stack for an answer is dropped unanswered. Those are
    the continuations :func:`held_for_an_answer` refuses a copy over, and
    with nothing left to invoke them they are never run.
    """
    game.resolving_stack_item = None
    game.resolving_seats = []
    game.resume_stack = []
    if owing_nothing:
        game.pending_choices = []
        game.pending_replacement_choices = []
        game.stack = [
            item for item in game.stack
            if getattr(item, "finish_resolution", None) is None
            and not getattr(item, "resolution_held", False)
        ]


def scratch_copy(game):
    """A copy of *game* a cast can be carried out on with nothing reaching
    the original: every seat non-interactive, so each prompt takes its kind's
    default, as it does for a seat the engine plays.

    **When** a prompt is answered is the game's own arrangement and is left
    as it is: a table with a `prompt_driver` (the simulator's) answers each
    one as it is armed, a table without (a web game) once the stack has
    emptied — and a spell whose steps ask two things in a row comes out
    differently under the two. A copy that answered on a schedule of its own
    rehearsed a different cast from the one the executor then made.

    Mana is enforced on the copy exactly as it is on the game. What the
    rehearsed cast itself costs is the planner's question and whoever
    rehearses it supplies that mana (``ai_scoring._rehearse_announcement``);
    everything else that is paid for on the way — "counter that spell unless
    its controller pays {3}", "that player may pay {2}{U}" — is paid out of
    what each seat really has, or the tax every such spell levies would be
    one anybody could afford and the spell would measure as nothing.

    The copy is `copy.deepcopy`, the one `engine/game_history.py` already
    takes for the web app's undo, with the card objects shared
    (:func:`_every_card`).
    """
    return scratch_copy_with(game, None)[0]


def scratch_copy_with(game, carried):
    """:func:`scratch_copy`, and *carried* copied **with** it: an object that
    refers into the game (a prompt holding its stack object) comes back
    referring into the copy."""
    import copy

    memo = {id(card): card for card in _every_card(game)}
    clone, carried = copy.deepcopy((game, carried), memo)
    clone.interactive_seats = set()
    return clone, carried


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


def run_out_the_turn(game, *, through_combat: bool = False) -> None:
    """Take *game* — a scratch copy (:func:`scratch_copy`) — to the end of
    its turn the way a rehearsal does: with its combat fought first if
    *through_combat* (the active seat's attack and the blocks declared by
    the policies that would declare them), then CR 514's cleanup. For a
    reader that makes a cast for real and wants it priced as a rehearsal
    would price it."""
    _run_out_the_turn(game, through_combat=through_combat)


def _fight_the_combat(game) -> None:
    """Play a scratch copy's combat phases from the main phase it is in: the
    active seat's attack, the blocks, the damage — each declared by the
    policy that would declare it in a game nobody is asked about
    (``ai_combat.run_ai_combat_phase``, the simulator's own driver) — and
    every further combat the turn's plan holds (CR 500.8), each entered the
    way the turn enters it.

    The one place a rehearsal lets something be *decided* on the way to the
    end of the turn, and it is asked for by name (:func:`rehearse`'s
    *through_combat*) on the cast and on the table it is measured against
    alike. What it buys is the difference a precombat cast makes to the
    fight: three more damage from a Giant Growth, none at all under the
    caster's own Fog.
    """
    from .ai_combat import run_ai_combat_phase

    for _ in range(_REHEARSAL_PASSES):
        if not _combat_ahead(game):
            return
        before = (game.current_turn_phase, repr(game.turn_phases_remaining))
        if game.current_turn_phase != "precombat_main":
            # A combat added after this main phase: entered through the
            # turn's own successor, so a skip of it (CR 500.11) is spent.
            if game.enter_next_turn_phase() != "combat":
                return
        run_ai_combat_phase(game, game.active_player_index)
        _settle_scratch(game)
        if (game.current_turn_phase, repr(game.turn_phases_remaining)) == before:
            return


def _run_out_the_turn(game, *, through_combat: bool = False) -> None:
    """Take a scratch copy to the end of its turn: a combat whose blocks are
    already declared deals its damage, the end step's triggers fire
    (CR 513.1: "at the beginning of the next end step" — a card exiled
    until then goes back to its owner's hand, a token made for the turn
    goes), then CR 514's cleanup ends every "until end of turn" effect and
    removes marked damage.

    Nothing is *decided* on the way — no attack is declared, no block made —
    so what is read afterwards is what the cast left, and not what a policy
    then did with it. *through_combat* is the exception, asked for by name:
    the turn's combat is fought first (:func:`_fight_the_combat`).
    """
    if through_combat:
        _fight_the_combat(game)
    for _ in range(_REHEARSAL_PASSES):
        if game.current_turn_phase != "combat" or game.is_game_over():
            break
        step = game.current_step
        game.advance_combat_phase()
        game.auto_resolve_pending_choices()
        if game.current_step == step:
            break
    if game.is_game_over():
        return
    if game.current_turn_phase != "ending" and not game.stack:
        game.resolve_end_step(game.active_player_index)
        _settle_scratch(game)
        if game.is_game_over():
            return
    game.resolve_cleanup_step(game.active_player_index)
    _settle_scratch(game)


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
                key: repr(value) for key, value in vars(player).items()
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
            key: repr(_ledger_entries(value) if key == "damage_ledger" else value)
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


def _measured(game, *, through_combat: bool = False) -> dict:
    """A scratch copy read twice: as it stands, then run out to the end of
    its turn (with its combat fought, if *through_combat*). The copy itself
    is kept beside the readings, for the one more that is taken only when it
    is needed (:func:`_lasting_digest`)."""
    reading = {
        "digest": position_digest(game),
        "now": standings(game, now=True),
    }
    _run_out_the_turn(game, through_combat=through_combat)
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


def _rehearsal_seed(game) -> int:
    """The seed a rehearsal's own randomness runs on: a function of the
    position, so a seed still reproduces a run, and nothing to do with the
    game's real sequence — a coin flipped in a rehearsal is a sample, never a
    look at the flip to come."""
    return 7919 * int(getattr(game, "turn", 0) or 0) + len(game.log)


def _card_order(card) -> tuple:
    """Where a card sorts among the cards of a hidden zone: by what it is,
    never by where it was. Two cards that sort alike are the same card to
    anything a rehearsal reads (a deck is one object per printing, repeated)."""
    return (card.name, str(getattr(card, "oracle_id", "") or ""))


def conceal_from(game, seat: int) -> None:
    """Replace what *seat* cannot see on *game* — a scratch copy — with
    something it **could** be (CR 400.2: a library and a hand are hidden
    zones).

    A rehearsal carries a cast out, and a copy of the game is a copy of
    everything in it: the next card of every library, and every card in every
    other player's hand. Read as they stand, a rehearsed Duress knows whether
    there is a card for it to take and a rehearsed Brainstorm knows what it
    will draw — a decision made on what the seat was never shown.

    So, on the copy and before anything is cast on it:

    * **every library is put in a random order** — the seat's own included,
      since it knows what is in it and not where;
    * **each other player's hand is dealt again**, out of that player's hand
      and library pooled: the same number of cards, drawn from everything the
      seat cannot tell apart.

    Each pool is sorted by what the cards are (:func:`_card_order`) before it
    is shuffled, and the shuffle runs on the rehearsal's own seed
    (:func:`_rehearsal_seed`). That is what makes this **exactly** blind
    rather than roughly so: the redeal is a function of *which* cards are
    hidden and of nothing about *where* they are, so two games that differ
    only in which of them an opponent is holding rehearse the same cast the
    same way (``tests/ai/test_ai_hidden_information_census.py``). Shuffled
    from the order they stood in, a fixed permutation of the real hand and
    library would still have dealt the real hand back some of the time.

    **What the seat may see is left where it is**, through the two seams that
    say so for a viewer in the browser: a hand a standing effect reveals to
    it (``revealed_hands.hand_revealed_to`` — Telepathy, Revelation), and the
    top card of a library that is played revealed or that its owner may look
    at (``library_top.top_is_public`` / ``top_is_visible``) — and the top card
    of its own library an effect lets it **play** (CR 601.3: Conspicuous
    Snoop, Radha, Temporal Aperture), which the permission names to it; dealt
    away, a rehearsed cast of it was refused on every copy and a free cast off
    the top was never proposed.

    What this does not know is what the seat has *been shown and remembers*:
    a card it looked at with a Duress of its own two turns ago, one it
    bounced to that hand, the three it put back with a Brainstorm. Nothing in
    the engine keeps that record — a reveal is an event (``record_reveal``),
    not a standing fact about a card — so every such card is dealt back into
    the unknown. A seat holding a prompt keeps its hand as it is: the prompt
    may name cards in it by position.
    """
    import random

    from .library_top import top_is_public, top_is_visible
    from .revealed_hands import hand_revealed_to

    from .cast_permissions import playable_from_zones

    def playable_on_top(index) -> bool:
        return any(
            entry.get("zone") == "library" and entry.get("index") == 0
            for entry in playable_from_zones(game, index)
        )

    owing = {choice.player_index for choice in game.pending_choices}
    for index, player in enumerate(game.players):
        library = player.library
        seen_on_top = library[:1] if (
            (top_is_visible(game, index) or playable_on_top(index))
            if index == seat else top_is_public(game, index)
        ) else []
        hidden = library[len(seen_on_top):]
        deals_hand = (
            index != seat
            and index not in owing
            and not hand_revealed_to(game, index, seat)
        )
        if deals_hand:
            hidden = [*player.hand, *hidden]
        hidden.sort(key=_card_order)
        random.shuffle(hidden)
        if deals_hand:
            held = len(player.hand)
            player.hand[:] = hidden[:held]
            hidden = hidden[held:]
        library[:] = [*seen_on_top, *hidden]


def _scratch(game, carried, detach, seat):
    """One scratch copy set up for *seat*'s rehearsal: detached if asked
    (``True``, or ``"abstract"`` for :func:`_detach`'s *owing_nothing*), its
    randomness on the rehearsal's own seed and everything *seat* cannot see
    dealt again (:func:`conceal_from`)."""
    import random

    clone, carried = scratch_copy_with(game, carried)
    if detach:
        _detach(clone, owing_nothing=detach == "abstract")
    random.seed(_rehearsal_seed(game))
    conceal_from(clone, seat)
    return clone, carried


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
    reading = _measured(clone, through_combat=through_combat)
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
    :func:`standings`), is run out to the end of its turn and is read again.
    The same two readings of the table **with nothing cast** are what it is
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
    dealt again out of what *seat* cannot tell apart (:func:`conceal_from`),
    and its randomness is reseeded (:func:`_rehearsal_seed`) — so a draw, a
    discard that takes "a noncreature, nonland card", a search's shuffle or a
    coin flip in a rehearsal says what such a cast is *like*, never what the
    real one will turn up; the real game's random sequence is put back exactly
    as it was. What a rehearsal does see is what the seat sees: the table,
    its own hand, how many cards everybody else is holding.

    None rather than a guess when it cannot run: from inside another
    rehearsal (:func:`rehearsing`), on a table that is part-way through a
    resolution (:func:`mid_resolution`), or when the copy raises — a crash
    in a rehearsal is not a crash in the game, and is not nothing either:
    it is written into ``REHEARSALS_RAISED`` under *spell_name* (or *label*,
    for an answer that is not a cast), which a simulated run reports and
    fails on.

    *carried* is an object copied with the game and handed to *perform*
    beside the copy — the prompt being answered, which holds its own stack
    object. *detach* rehearses on a copy cut loose from a resolution the
    original is in the middle of (:func:`_detach`), for an answer that is its
    own stack object — or, as ``"abstract"``, on one that owes nothing at
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
        if not getattr(result, "supported", False):
            return Rehearsal(
                accepted=False, refusal=str(getattr(result, "details", "") or ""),
            )
        _settle_scratch(clone)
        # Whether a fight is still to come once the cast has resolved — read
        # off the copy, because a cast can be what adds one.
        combat_ahead = clone.active_player_index == seat and _combat_ahead(clone)
        made_mana = any(
            int(amount or 0) > int(was.get(symbol, 0) or 0)
            for was, player in zip(pools, clone.players)
            for symbol, amount in player.mana_pool.items()
        )
        # A cast it opened, its own card aside: a flashback card cast from a
        # hand is a graveyard card its owner may cast, and that is the card
        # spent, not a cast gained.
        opened_a_cast = any(
            name != spell_name
            for _zone, name in _casts_open(clone, seat) - untouched["could_cast"]
        )
        reading = _measured(clone, through_combat=through_combat)
        now = standing_swing(untouched["now"], reading["now"], seat)
        lasting = standing_swing(untouched["lasting"], reading["lasting"], seat)
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
        # Whether any of it is still there once the turn is over. Asked of
        # the table only where the standings leave it open — a lasting swing
        # is a lasting change — because the answer costs a digest of each
        # copy. "Leave it open" is a lasting swing of nothing but the spell's
        # own card: the card spent and nothing else, or (a spell bought back,
        # CR 702.27a) not even that. The table then says which it is — a
        # card drawn in place of the one spent is a hand that differs.
        fleeting = (
            changed
            and (
                abs(lasting) < _NO_SWING
                or (leaves_hand and abs(lasting + CARD_WORTH) < _NO_SWING)
            )
            and same_position(
                _lasting_digest(untouched), _lasting_digest(reading),
                spell_name=returned, caster=seat, spell_zone=zone or "hand",
                spell_seat=spell_seat,
            )
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
        )
    except Exception as raised:
        _note_raised(label or spell_name, raised)
        return None
    finally:
        random.setstate(real_sequence)
        _REHEARSING.reset(token)


__all__ = [
    "CARD_WORTH",
    "REHEARSALS_RAISED",
    "Rehearsal",
    "conceal_from",
    "combat_is_still_to_come",
    "forget_damage_history",
    "untap_for_the_next_turn",
    "has_a_creature_to_fight_with",
    "permanent_worth",
    "position_digest",
    "priced_by_the_fight",
    "rehearse",
    "rehearsing",
    "seat_standing",
    "standing_swing",
    "standings",
    "swing_worth",
    "run_out_the_turn",
    "same_position",
    "scratch_copy",
]

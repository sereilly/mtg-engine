"""What a proposal is worth: a cast rehearsed and scored, an ability scored,
a card weighed in the abstract.

**A spell is worth what it does.** :func:`_rehearse_announcement` carries
the cast a candidate would announce out on a scratch copy of the game
(``ai_rehearsal.rehearse``), the way the executors carry it out, and
:func:`_score_cast` prices the swing it measured. A cast that changes
nothing that outlasts the turn, or leaves its caster plainly worse off, is
not proposed (:func:`_worth_proposing`, ``HARM_FLOOR``); a precombat cast is
read again with the turn's fight fought (:func:`_weighed_through_the_fight`);
and a library-top setup, the one change a standing cannot see, is priced by
the draws it chooses (:func:`_chosen_draw_worth`). A permanent is worth what
it is, and an ability what its instruction does (:func:`_score_activation`).

**A card is worth what casting it would be**, asked in the abstract by the
choosers that pick a card rather than cast one — a search, a scry, a library
rearranged (:func:`_score_tutor_choice`). That question asks which seat the
card would be aimed at, and the seat chooser for a spell that names a player
asks what each cast is worth, so :func:`_choose_target_for_spell` is here
with it: the two call each other. The X a cast announces
(:func:`_pick_x_value`) is here for the same reason.

:func:`choose_attack_target` — which opponent — is the lowest of the
policy's heuristics, asked by nearly every chooser, and sits here as the
floor they share.

The weights are tuning, like every number in the policy; *which cards a
weight reaches* is the valuation modules' to derive.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
import re

from .ai_weighed_cast import SPELL_TYPES, cast_weighed, spell_text
from .ai_target_sides import (
    entry_trigger_seat_side,
    spell_seat_side,
    spell_target_side,
)
from .ai_rehearsal import (
    CARD_WORTH,
    Rehearsal,
    deliberating,
    has_a_creature_to_fight_with,
    priced_by_the_fight,
    rehearse,
    rehearsing,
)
from .ai_valuation import (
    cards_drawn_by_controller,
    is_mana_ability,
    library_top_setups,
    mana_ability_amount,
)
from .cast_costs import additional_costs, cast_announces_x
from .classifier import classify_card
from .faces import castable_faces
from .game import Game
from .models import CardDefinition, Permanent, PlayerState
from .oracle import OracleInstruction, compile_card_oracle
from .search_filters import search_matches
from .targeting import spec_roles
from .ai_mana_sources import _MANA_SYMBOLS
from .ai_payment import (
    tap_planned_lands,
    _cost_for,
    _charged_in_place_of_mana_cost,
    _max_affordable_x,
    _plan_land_taps,
)
from .ai_actions import (
    CastAction,
    cast_announcement,
    _zone_seat,
    _OFFERS_ANNOUNCED,
    _announced_mode,
    _announced_steps,
    _cast_zone,
    _cast_spec,
    _announces_any_offer,
)


def choose_attack_target(game: Game, player_index: int) -> int:
    """MVP multiplayer opponent-choice heuristic: attack/target whichever living
    opponent has the least life, tying broken by lowest seat index (deterministic
    for tests/seeded simulations). Intentionally simple — no board-state or
    threat-assessment awareness; deeper multiplayer AI tactics are future work.
    In a 2-player game this is always just the other seat."""
    opponents = game.opponents_of(player_index)
    if not opponents:
        return player_index
    return min(opponents, key=lambda idx: (game.players[idx].life, idx))


#: What an instant or sorcery scores before anything it does is counted. The
#: sum the old weights made of "a card" (1.5) and "a spell" (2.0).
SPELL_BASE_SCORE = 3.5
#: The most a measured swing moves a score either way: a cast that wins the
#: game outranks everything, and by a number that still adds and compares.
SWING_CAP = 60.0
#: A cast measured to leave its caster this much worse off is not proposed:
#: half a life. Not zero, so that a measure a hair under nothing (a point of
#: power lent to an opposing blocker for a turn) does not hold a card for
#: ever; and no lower, because the casts between here and a life and a half
#: were all the same cast — a sweep or a shrink landing on the caster alone.
HARM_FLOOR = -0.5


#: What a card a cast puts **on top of its caster's own library** is worth,
#: as a share of how much better it is than the card the draw would otherwise
#: have been (`_chosen_draw_worth`) — that difference held to a card either
#: way (``CARD_WORTH``), the unit a standing counts a hand in, so a chosen
#: draw is never worth more than a card in hand. A share, because it is a draw
#: brought forward and not a card in hand: the turn it is drawn is a turn
#: away, and the draw it displaces was a card too.
CHOSEN_DRAW_SHARE = 0.5
#: How many of the draws a library-top setup decides are counted. The first
#: few are the ones a seat plans for; past them a stack of finds is a turn
#: order nobody is weighing.
CHOSEN_DRAWS_COUNTED = 2


#: The mana of each kind a rehearsed cast is lent to pay for itself: more
#: than any spell in the pool can ask for at any X the planner sizes.
_REHEARSAL_MANA = 40

#: Set while a card is being weighed **in the abstract** — what is this one
#: worth to hold — rather than as a cast to make now (`_score_tutor_choice`).
#: The question is asked by a search part-way through its own resolution, a
#: moment no cast can be rehearsed in, and it is not about that moment: the
#: rehearsal runs on a copy that owes nothing (``ai_rehearsal.rehearse``'s
#: ``detach="abstract"``).
_IN_THE_ABSTRACT: ContextVar[bool] = ContextVar("ai_in_the_abstract", default=False)


#: Set by `ai_casts._cast_candidate_sized` while it builds a candidate at one size of
#: an X paid in life: the X `_pick_x_value` announces in place of the largest
#: the seat's reserve allows.
_LIFE_X_ASKED: ContextVar["tuple | None"] = ContextVar("ai_life_x_asked", default=None)


def _held_as(player, card: CardDefinition) -> "CardDefinition | None":
    """The card in *player*'s hand that *card* is a spell of — itself, or the
    split card it is one half of (CR 709.3) — or None when the hand holds no
    such card."""
    return next(
        (
            held for held in player.hand
            for face in castable_faces(held)
            if face is card or face == card
        ),
        None,
    )


def _announcement(
    card: CardDefinition,
    *,
    target: int,
    caster: int,
    permanent_index: "int | list[int] | None" = None,
    permanent_ids: "list[int] | None" = None,
    x_value: int | None = None,
) -> dict:
    """What a cast of the candidate being built announces when it names
    *target* (and the permanent given), in `cast_announcement`'s own shape —
    so a rehearsal of a half-built candidate and of the finished `CastAction`
    are one question asked once.

    **Out of the zone being weighed** (`ai_weighed_cast.cast_weighed`), and
    under the permission that opens it, as the finished cast is made: a
    target chosen for a flashback card was rehearsed as the same card put in
    the hand and cast from there, which arrives in a graveyard it never left
    — a change every time — so its targets were weighed by a different
    reading from the one its cast then got (``_rehearse_announcement``'s
    *spell_zone*)."""
    offers = _OFFERS_ANNOUNCED.get()
    under = cast_weighed(card)
    return cast_announcement(CastAction(
        card_name=card.name,
        target_player_index=target,
        x_value=x_value,
        land_tap_indices=(),
        score=0.0,
        hand_index=0,
        target_permanent_index=permanent_index,
        target_permanent_ids=permanent_ids,
        optional_cost_payments=(
            dict(offers) if _announces_any_offer(card, offers) else None
        ),
        mode_index=_announced_mode(card),
        from_zone=_cast_zone(card),
        zone_seat=_zone_seat(caster, under),
        alternative_cost=under is not None and under.alternative_cost,
    ))


def _rehearse_announcement(
    game: Game, seat: int, card: CardDefinition, announcement: dict,
    *, planned: "CastAction | None" = None, through_combat: bool = False,
) -> Rehearsal | None:
    """What casting *card* with *announcement* would do, carried out on a
    scratch copy of the game (``ai_rehearsal.rehearse``) — or None when no
    rehearsal can be run.

    The cast is the executors' own: ``queue_from_hand`` with the keywords
    `cast_announcement` produces, and the copy then resolves it. A card the
    seat does not hold (a chooser asked about a spell in the abstract) is put
    in the copy's hand first, and then its leaving is not a card the cast
    cost.

    **The mana is the executors' too, once there is a plan.** *planned* is
    the finished `CastAction`: its lands are tapped on the copy for the
    colours it planned (`tap_planned_lands`) and the cast pays out of them,
    which is every executor's two lines — so what the caster has left to
    spend while the spell resolves is what it will really have left. Chain
    Stasis is the card that notices: its copies are paid for one after
    another until the mana runs out, and one mana more is a creature left
    tapped instead of untapped.

    Before there is a plan — a target is weighed before any land is — the
    spell's own mana is **lent**: the copy's caster is handed a pool to pay
    out of and has it taken back the moment the spell is on the stack.
    Either way mana stays enforced for everything the resolution then asks
    anyone to pay.

    *through_combat* runs the turn out with its combat fought, on the cast
    and on the table it is compared with (``ai_rehearsal.rehearse``) — the
    second reading `_weighed_through_the_fight` asks for.
    """
    if rehearsing():
        return None
    from_hand = announcement.get("from_zone", "hand") == "hand"
    in_hand = _held_as(game.players[seat], card) if from_hand else None
    held = not from_hand or in_hand is not None
    # The name the card goes by in a hand and a graveyard, which for a half
    # of a split card is the whole card's (CR 709.4).
    zone_name = in_hand.name if in_hand is not None else card.name

    def perform(table):
        player = table.players[seat]
        if not held:
            table.put_card_into_hand(player, card)
        if planned is not None:
            tap_planned_lands(table, seat, planned)
            return table.queue_from_hand(seat, card.name, **announcement)
        floating = dict(player.mana_pool)
        for symbol in _MANA_SYMBOLS:
            player.mana_pool[symbol] = int(floating.get(symbol, 0) or 0) + _REHEARSAL_MANA
        try:
            return table.queue_from_hand(seat, card.name, **announcement)
        finally:
            player.mana_pool.clear()
            player.mana_pool.update(floating)

    def paid_for(table, _carried) -> None:
        # The table the planned cast is compared with: the same lands
        # tapped, and the mana they made let go — so a tapped land, and
        # whatever tapping it set off, is on both sides and is not read as
        # something the spell did.
        pool = table.players[seat].mana_pool
        floating = dict(pool)
        tap_planned_lands(table, seat, planned)
        pool.clear()
        pool.update(floating)

    taps = planned is not None and bool(planned.land_tap_indices)
    rehearsal = rehearse(
        game, seat, perform, spell_name=zone_name,
        leaves_hand=from_hand and held,
        # Cast out of a zone a permission opens (CR 601.3): its trip out of
        # that zone is the cast's own, as a hand card's is.
        spell_zone=None if from_hand else announcement.get("from_zone"),
        # ...in the pile's owner's zones (the permission being weighed says
        # whose; an announcement does not carry it).
        spell_seat=(
            None if from_hand or cast_weighed(card) is None
            else cast_weighed(card).owner_seat
        ),
        # Everything that tells two rehearsals of one decision apart: the
        # announcement, and — once there is one — the plan that pays for it.
        # One card priced twice (a free cast that takes a kicker is priced
        # again as an ordinary one, `ai_casts._priced_candidate`) announces the same
        # thing over two different payments, and the lands left untapped are
        # part of what the resolution has to spend.
        key=(
            seat, card.name, held,
            (planned.land_tap_indices, planned.land_tap_colors)
            if planned is not None else None,
            repr(sorted(announcement.items())), through_combat,
        ),
        without=paid_for if taps else None,
        without_key=(
            ("paid", planned.land_tap_indices, planned.land_tap_colors)
            if taps else None
        ),
        detach="abstract" if _IN_THE_ABSTRACT.get() else False,
        through_combat=through_combat,
    )
    # **What a standing cannot see: the next draws, chosen.** "Search your
    # library for a card, then shuffle and put that card on top" (Vampiric,
    # Mystical, Enlightened and Worldly Tutor; Insidious Dreams' X cards;
    # Scouting Trek) leaves every card where a standing counts it — the
    # finds are still in the library — so the rehearsal read a cast that
    # moved nothing: Vampiric Tutor was its 2 life and no more, and never
    # proposed; Insidious Dreams was its discards. The order of a library is
    # a change the rehearsal sees and does not price, so the price is added
    # here, for the casts whose program sets the top up
    # (`ai_valuation.library_top_setups`), as a change that lasts.
    if rehearsal is not None and rehearsal.accepted and not _IN_THE_ABSTRACT.get():
        worth = _chosen_draw_worth(game, seat, card, announcement.get("x_value"))
        if worth:
            rehearsal = replace(
                rehearsal, now=rehearsal.now + worth, lasting=rehearsal.lasting + worth,
            )
    return rehearsal


def _chosen_draw_worth(
    game: Game, seat: int, card: CardDefinition, x_value: "int | None",
) -> float:
    """What the library-top setup a cast of *card* makes is worth to *seat*:
    for each of the next `CHOSEN_DRAWS_COUNTED` draws it decides, a
    `CHOSEN_DRAW_SHARE` of how much better the card it puts there is than the
    library's average card — the draw a seat that cast nothing would make.

    The cards are the ones the seat's own search would find (`search_matches`
    over the payload, best first by `_score_tutor_choice`, the scorer the
    search's pick asks), out of the cards its library holds — which the seat
    knows, though not their order: it is its own deck, and the search is a
    look through it. Signed: a setup whose finds are worse than an average
    draw (Scouting Trek's lands with lands enough on the table) is worth less
    than nothing. No per-card table: which casts set the top up is the
    compiled program's (`ai_valuation.library_top_setups`).
    """
    setups = library_top_setups(card, x_value)
    if not setups:
        return 0.0
    library = list(game.players[seat].library)
    if not library:
        return 0.0
    scores = [_score_tutor_choice(game, seat, held) for held in library]
    average = sum(scores) / len(scores)
    taken: set[int] = set()
    chosen: list[float] = []
    for payload, count in setups:
        wanted = len(library) if count is None else count
        matching = sorted(
            (
                (score, index) for index, (held, score) in enumerate(zip(library, scores))
                if index not in taken and search_matches(held, payload)
            ),
            key=lambda entry: (-entry[0], entry[1]),
        )
        for score, index in matching[:wanted]:
            taken.add(index)
            chosen.append(score)
    # The finds go on top in the order the seat names, best first. Each is
    # read against the average card and held to a card either way: the score
    # is a cast's, and a standing counts a card in hand as `CARD_WORTH`.
    chosen.sort(reverse=True)
    return CHOSEN_DRAW_SHARE * sum(
        max(-CARD_WORTH, min(CARD_WORTH, score - average))
        for score in chosen[:CHOSEN_DRAWS_COUNTED]
    )


def _names_an_unweighed_seat(
    game: Game, seat: int, card: CardDefinition
) -> bool:
    """Whether a cast nobody could rehearse would name a player out of
    several with nothing having weighed which.

    "Target player discards two cards" has no side to read off its program:
    which player is `_choose_target_for_spell`'s rehearsal of each seat, and
    with no rehearsal to be had (the table is part-way through a resolution;
    the copy raised) every seat scores alike and the tie is the caster's.
    Such a cast is held for a moment it can be measured in. A spell that
    names an object, or nobody, is aimed by what its program says and is
    proposed unmeasured, as it always was.
    """
    return len(_seats_the_cast_may_name(game, seat, card)) > 1


def _worth_proposing(rehearsal: Rehearsal | None) -> bool:
    """Whether a rehearsed cast is one to propose: the engine took it, it
    changed something **that outlasts the turn**, and it did not leave its
    caster plainly worse off.

    A cast whose every trace is gone by the end of the turn
    (``Rehearsal.fleeting``) changed something and bought nothing: a pump on
    a creature that then did not fight, a shield nothing came for, a Fog in
    its caster's own main phase with no attack to stop — each was proposed,
    at ``SPELL_BASE_SCORE``, and cast whenever nothing scored higher. Mana is
    the exception (``made_mana``): it is gone by the end of the turn *because
    it is spent*, on a cast this rehearsal is not a rehearsal of — and so is
    a cast it opens (``opened_a_cast``: Yawgmoth's Will, Recoup).

    A cast nobody could rehearse (None) is proposed as it always was.
    """
    if rehearsal is None:
        return True
    if not (rehearsal.accepted and rehearsal.changed):
        return False
    if _leaves_nothing(rehearsal):
        return False
    return rehearsal.swing >= HARM_FLOOR


def _weighed_through_the_fight(
    game: Game, seat: int, card: CardDefinition, announcement: dict,
    rehearsal: Rehearsal | None, *, planned: "CastAction | None" = None,
) -> Rehearsal | None:
    """*rehearsal* — of casting *card* with *announcement* (paid for as
    *planned*, once there is a plan), a cast made before the turn's combat —
    read again **with that combat fought**, where the first reading cannot
    price it; otherwise *rehearsal* as it is.

    A rehearsal runs its copy to the end of the turn with nothing declared on
    the way, so what a precombat cast does *to the fight* is not in it: a
    Giant Growth is a quarter of a +3/+3 whether the creature then attacks
    for three more or stays home, Hatred is the life it cost, and a Fog in
    its caster's own main phase — which stops the caster's own attack — is a
    cast that harmed nobody. The second reading plays the attack, the blocks
    and the damage on both copies (``ai_rehearsal.rehearse``'s
    *through_combat*) and what it measures is what is left when the turn is
    over: the damage that got through, the creature that died or did not.

    Asked only where it can change the answer, because it is a whole combat
    on two copies: the seat's own precombat main phase
    (``Rehearsal.combat_ahead``: or a postcombat one in which the cast adds
    a combat), and a cast some of whose good is gone by
    the end of the turn — all of it (``fleeting``), or more of it than is
    left (``now`` above ``lasting``). A removal spell, a draw, a discard are
    priced by what they leave and are not asked twice.

    Asked by the cast being built and by the choosers that pick its target
    (`ai_targets._best_target`, `ai_targets._better_than_the_seat`), because which creature a
    shield or a pump goes on is a question about the fight too: "prevent the
    next 3 damage that would be dealt to any target this turn" on the 2/2
    about to trade is a creature saved, and on its controller is nothing.
    """
    if (
        rehearsal is None
        or not rehearsal.accepted
        or not rehearsal.changed
        or rehearsal.through_combat
        # A fight still to come once the cast has resolved — the turn's own,
        # or one the cast added (CR 500.8: Relentless Assault).
        or not rehearsal.combat_ahead
    ):
        return rehearsal
    if not priced_by_the_fight(rehearsal.now, rehearsal.lasting, rehearsal.fleeting):
        return rehearsal
    if (rehearsal.made_mana or rehearsal.opened_a_cast) and not priced_by_the_fight(
        rehearsal.now, rehearsal.lasting, False,
    ):
        # A ritual: what it left is mana, and no fight spends it. One that
        # also lends something for the turn — "gain control of target
        # creature until end of turn … add two mana" (Traitorous Greed) — is
        # the creature it attacks with, and is read with the fight.
        return rehearsal
    if not has_a_creature_to_fight_with(game, seat):
        # Nothing to attack with: the fight is the turn as already read.
        return rehearsal
    fought = _rehearse_announcement(
        game, seat, card, announcement, planned=planned, through_combat=True,
    )
    return rehearsal if fought is None else fought


def _leaves_nothing(rehearsal: Rehearsal) -> bool:
    """Whether a rehearsed cast that changed something left none of it by the
    end of the turn — mana aside, which is gone because it is spent, and a
    cast it opened, for the same reason (`_worth_proposing`'s reading, for a
    chooser comparing targets)."""
    return (
        rehearsal.fleeting and not rehearsal.made_mana
        and not rehearsal.opened_a_cast
    )


def _pays_x_in_life(card: CardDefinition) -> bool:
    """Whether *card*'s X is announced as life to pay (CR 107.3a, CR 119.4):
    "As an additional cost to cast this spell, pay X life." """
    return any(cost.pay_life_x for cost in additional_costs(card))


#: `_score_tutor_choice`'s answers for one position: ``{"at": stamp, (seat,
#: card name): score}``. A search weighs every card it may find, a library is
#: mostly repeats, and weighing a spell is a rehearsal — so each card is
#: weighed once for as long as the position stands.
_TUTOR_SCORES: dict = {}


def _score_tutor_choice(game: Game, player_index: int, card: CardDefinition) -> float:
    """What *card* is worth to *player_index* to have: the score casting it
    would get, in the abstract (`_IN_THE_ABSTRACT`), with what the seat's
    lands say about when.

    For the choosers that pick a card rather than cast one — a search, a
    scry, a library rearranged. A spell's worth is what a rehearsal of it
    measures on this board; it was the cast scorer's probes on the card's
    text, which went when the cast scorer stopped reading text.
    """
    stamp = (
        id(game), len(game.log), game.turn,
        tuple((seat.life, len(seat.hand), len(seat.battlefield)) for seat in game.players),
    )
    if _TUTOR_SCORES.get("at") != stamp:
        _TUTOR_SCORES.clear()
        _TUTOR_SCORES["at"] = stamp
    key = (player_index, card.name)
    if key not in _TUTOR_SCORES:
        token = _IN_THE_ABSTRACT.set(True)
        try:
            with deliberating():
                _TUTOR_SCORES[key] = _tutor_score(game, player_index, card)
        finally:
            _IN_THE_ABSTRACT.reset(token)
    return _TUTOR_SCORES[key]


def _tutor_score(game: Game, player_index: int, card: CardDefinition) -> float:
    player = game.players[player_index]
    opponent_index = choose_attack_target(game, player_index)
    opponent = game.players[opponent_index]

    # Cards the engine cannot cast would strand in hand.
    if not classify_card(card).supported:
        return -50.0

    x_value = _pick_x_value(game, player, card)
    target = _choose_target_for_spell(card, player_index, game, x_value)
    score = _score_cast(game, player_index, card, target, x_value)

    lands_available = sum(
        1 for perm in game.controlled_by(player) if perm.card.primary_type == "land"
    ) + sum(
        1 for hand_card in player.hand if hand_card.primary_type == "land"
    )
    if card.primary_type == "land":
        # Lands are only worth tutoring when mana-screwed.
        if lands_available < 3:
            score += 4.0 - lands_available
        else:
            score -= 4.0
    elif game.enforce_mana_costs:
        required = _cost_for(game, player, card, x_value if x_value is not None else 0)
        if _plan_land_taps(game, player, required) is not None:
            score += 3.0  # castable as soon as it reaches hand
        else:
            available = sum(
                player.mana_pool.get(symbol, 0) for symbol in _MANA_SYMBOLS
            ) + sum(
                1 for permanent in game.controlled_by(player)
                if permanent.card.primary_type == "land" and not permanent.tapped
            )
            score -= min(5.0, max(0.0, float(card.cmc) - available))

    # A tutored burn spell that closes the game outranks everything else.
    damage = _extract_damage(card)
    if target == opponent_index and 0 < opponent.life <= damage:
        score += 15.0

    return score


def _permanent_value(permanent: Permanent) -> float:
    return permanent.effective_power * 1.4 + permanent.effective_toughness * 1.1 + float(permanent.card.cmc)


def _choose_target_for_spell(
    card: CardDefinition, caster_index: int, game: Game, x_value: int | None = None
) -> int:
    # Whose permanent the spell's object target should be, when the compiled
    # program says (`ai_target_sides.spell_target_side`). Asked first, and it is
    # an answer in its own right: the side is a claim about what the effect
    # does to its target, never about which card printed it, and it costs no
    # rehearsal. "Target creature can't attack or block this turn" is aimed
    # across the table because the kind hampers what it names.
    side = spell_target_side(card)
    if side == "you":
        return caster_index
    if side == "opponent":
        return choose_attack_target(game, caster_index)
    # A permanent spell's seat is its entry trigger's "target player" (the
    # cast names it), and the score below cannot read a trigger: its tie-break
    # hands a creature spell's seat to the caster, which is how Abyssal Horror
    # made its own controller discard two cards. Read off the trigger this
    # announcement will fire (`_OFFERS_ANNOUNCED`: a Battlemage's discard exists
    # only for a cast that paid for it).
    if entry_trigger_seat_side(card, _OFFERS_ANNOUNCED.get()) == "opponent":
        return choose_attack_target(game, caster_index)
    # …and a seat that trigger may **not** name is never announced, whatever
    # the trigger does to it. "When this creature enters, **target opponent**
    # gains control of it" (Sleeper Agent), "…target opponent reveals their
    # hand" (Mesmeric Fiend, Kitesail Freebooter), "…target opponent draws
    # two cards" (Lord of Tresserhorn): no side to read, so the seat fell to
    # the caster below — an announcement the trigger set aside as it was put
    # on the stack (CR 603.3d) and chose again, seven permanents in the pool
    # each logging a refusal nobody made. The seats are the trigger's own
    # list (`Game.entry_trigger_cast_targets`), the one the cast picker and
    # that push both read, so the seat named is one the trigger accepts.
    legal_seats = _entry_trigger_seats(game, caster_index, card)
    if legal_seats and caster_index not in legal_seats:
        wanted = choose_attack_target(game, caster_index)
        return wanted if wanted in legal_seats else legal_seats[0]
    # No side to read: a spell that names a **player** ("target player draws
    # three cards", "…loses 4 life and you gain 4 life", "…discards a card").
    # Each seat the announcement may name is weighed (`_score_spell_target`)
    # and the best one taken. This was a set of
    # probes on the card's text — "draw" for the caster, "damage" for an
    # opponent — and a sentence outside them tied, which is how the caster
    # came to discard to its own Mind Rot.
    seats = _seats_the_cast_may_name(game, caster_index, card)
    if len(seats) < 2:
        return seats[0] if seats else caster_index
    # Where the seats measure alike, the one the effect's family says
    # (`ai_target_sides.spell_seat_side`): the opponent's, for anything that is
    # not a gift.
    favoured = (
        caster_index if spell_seat_side(card) == "you"
        else choose_attack_target(game, caster_index)
    )
    best_seat, best_score = favoured, None
    for seat in sorted(seats, key=lambda seat: (seat != favoured, seat)):
        score = _score_spell_target(card, caster_index, seat, game, x_value)
        if best_score is None or score > best_score:
            best_seat, best_score = seat, score
    return best_seat


def _entry_trigger_seats(
    game: Game, caster_index: int, card: CardDefinition
) -> list[int]:
    """The seats a cast of the **permanent** *card* may name for its entry
    trigger's player target — empty for a spell, and for a permanent whose
    cast names no trigger's player.

    Asked of the engine's own list (`Game.entry_trigger_cast_targets`: the
    targets the trigger could choose for itself, CR 603.3d), under the offers
    this announcement takes (`_OFFERS_ANNOUNCED`, CR 702.33g), so it is the
    seats the push accepts and not a reading of the printed words.
    """
    if card.primary_type in SPELL_TYPES:
        return []
    legal = game.entry_trigger_cast_targets(
        caster_index, card, optional_cost_payments=_OFFERS_ANNOUNCED.get() or {},
    )
    return sorted({
        int(entry["seat"]) for entry in legal or ()
        if entry.get("kind") == "player" and isinstance(entry.get("seat"), int)
    })


#: Cast specs whose announcement names a **seat**: a player, or a pile of
#: cards that is one player's (a graveyard, a hand).
_SEAT_NAMING_SPECS = frozenset({
    "player", "player_or_planeswalker", "any", "opponent",
    "graveyard_creature", "hand_card",
})


def _seats_the_cast_may_name(
    game: Game, caster_index: int, card: CardDefinition
) -> list[int]:
    """The seats a cast of the candidate being built may name, off the
    engine's own enumeration — empty for a card whose announcement names no
    seat (a permanent, an untargeted spell, one aimed at an object).

    For a spell only: a permanent's instruction list mirrors its *abilities*
    (``ai_weighed_cast.SPELL_TYPES``), and the seat a creature spell carries is
    its entry trigger's, which `_choose_target_for_spell` reads before this.
    """
    if card.primary_type not in SPELL_TYPES:
        return []
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec.get("kind") not in _SEAT_NAMING_SPECS:
        return []
    if spec_roles(spec):
        return []
    legal = game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    )
    seats = {
        int(entry["seat"]) for entry in legal
        if entry.get("kind") != "permanent" and isinstance(entry.get("seat"), int)
    }
    return sorted(seats)


def _score_spell_target(
    card: CardDefinition,
    caster_index: int,
    target_index: int,
    game: Game,
    x_value: int | None = None,
) -> float:
    """What casting *card* at seat *target_index* is worth to its caster: the
    swing a rehearsal of that cast measures (``ai_rehearsal.rehearse``), in
    the standing's own units.

    A seat-only announcement — the engine picks the object for a spell that
    names one, as it does for any cast that names none. A cast the engine
    refuses there scores far below any it accepts, and one that changes
    nothing scores nothing.

    This was eight probes on the card's text and three on its program: the
    word "draw" was worth five, "gain" and "life" a share of the life lost,
    "target opponent" three, a destroy two plus one and a half per permanent
    the seat happened to control. A sentence outside them scored zero for
    both seats.
    """
    if card.primary_type not in SPELL_TYPES:
        # A permanent: the seat is its own controller's unless an entry
        # trigger says otherwise, which the caller has already read.
        return 1.0 if target_index == caster_index else 0.0
    rehearsal = _rehearse_announcement(
        game, caster_index, card,
        _announcement(card, target=target_index, caster=caster_index, x_value=x_value),
    )
    if rehearsal is None:
        return 0.0
    if not rehearsal.accepted:
        return -SWING_CAP
    return max(-SWING_CAP, min(SWING_CAP, rehearsal.swing))


def _score_cast(
    game: Game, caster_index: int, card: CardDefinition, target_index: int,
    x_value: int | None, rehearsal: Rehearsal | None = None,
) -> float:
    """What a cast is worth against the other casts the seat could make.

    **A spell is worth what it does**: `SPELL_BASE_SCORE` and the swing its
    rehearsal measured (*rehearsal*; a spell nobody could rehearse scores the
    base alone). **A permanent is worth what it is**: its type and, for a
    creature, its printed body — weights, and tuning like every other number
    in this module.
    """
    caster = game.players[caster_index]

    if card.primary_type == "land":
        untapped_lands = sum(
            1
            for perm in game.controlled_by(caster)
            if perm.card.primary_type == "land" and not perm.tapped
        )
        return 1.0 if untapped_lands < 4 else 0.2

    if card.primary_type in SPELL_TYPES:
        score = SPELL_BASE_SCORE
        if rehearsal is not None and rehearsal.accepted:
            score += max(-SWING_CAP, min(SWING_CAP, rehearsal.swing))
        elif rehearsal is None:
            # Nobody has measured it: a card being weighed where it lies (a
            # search's pick, the top of a library) rather than as a cast.
            score += _score_spell_target(card, caster_index, target_index, game, x_value)
    else:
        score = 1.5
        if card.primary_type == "creature":
            score += 1.2
            score += _creature_stat(card, "power") * 0.7
            score += _creature_stat(card, "toughness") * 0.4
            if target_index == caster_index:
                score += 1.0
        if card.primary_type in {"artifact", "enchantment"}:
            score += 0.8
        if x_value is not None:
            score += min(4.0, x_value * 0.6)

    # A mana source is worth playing early when there is something to spend the
    # mana on, and worth nothing at all when mana costs are not enforced. True
    # of every Mox, Sol Ring and Basalt Monolith here; only Black Lotus was named.
    if mana_ability_amount(card) is not None:
        if game.enforce_mana_costs:
            hand_nonlands = sum(1 for hand_card in caster.hand if hand_card.primary_type != "land")
            score += 2.0 if hand_nonlands >= 2 else 0.5
        else:
            score -= 2.0

    return score


def _score_activation(
    game: Game,
    player_index: int,
    instruction: OracleInstruction,
    target_index: int,
) -> float:
    """Score one activated ability. The *source permanent* is deliberately not a
    parameter: the last thing that read it asked for its name, and everything an
    activation is worth is in the instruction it puts on the stack."""
    score = 1.0

    if instruction.kind == "deal_damage":
        # A *defined* amount ("…equal to the number of pain counters removed
        # this way", Torture Chamber) is the payload's "x", and this was
        # ``int("x")``: a ValueError out of the chooser, which killed the whole
        # simulated run — and the web app's AI step — the first time a seat
        # held one untapped in a main phase. One is the floor every other
        # unread amount here gets.
        raw_amount = instruction.payload.get("amount", 1)
        amount = (
            raw_amount if isinstance(raw_amount, int) and not isinstance(raw_amount, bool)
            else int(raw_amount) if isinstance(raw_amount, str) and raw_amount.isdigit()
            else 1
        ) or 1
        target_player = game.players[target_index]
        effective_damage = max(0, amount - target_player.damage_prevention_pool)
        if effective_damage == 0:
            return -10.0
        score += 5.0 + effective_damage
        if target_index == choose_attack_target(game, player_index) and target_player.life <= effective_damage:
            score += 10.0
    elif instruction.kind == "draw_target_cards":
        score += 5.0 if target_index == player_index else 0.0
    elif is_mana_ability(instruction):
        score += 2.5
    elif instruction.kind == "grant_banding_to_target":
        score += 0.5
    else:
        score += 1.5

    # Drawing more cards than the library holds loses the game (CR 704.5b). This
    # was ``permanent.card.name == "Jayemdae Tome" and not library`` — that card's
    # one-card draw spelled out, so Jandor's Ring drew the AI to death.
    drawn = cards_drawn_by_controller(instruction)
    if drawn is not None and len(game.players[player_index].library) < drawn:
        return -100.0

    return score


def _extract_damage(card: CardDefinition) -> int:
    program = compile_card_oracle(card)
    for instruction in _announced_steps(card, program):
        if instruction.kind == "deal_damage":
            amount = instruction.payload.get("amount")
            if isinstance(amount, int):
                return amount
    match = re.search(r"deals? (\d+) damage", spell_text(card))
    if match:
        return int(match.group(1))
    return 0


def _creature_stat(card: CardDefinition, key: str) -> int:
    raw_value = str(card.raw.get(key, "0"))
    return int(raw_value) if raw_value.isdigit() else 0


#: Life a seat keeps back when the X it announces is paid in life ("As an
#: additional cost to cast this spell, pay X life") — the reserve the buyback
#: and foreign-activation prices keep, for the same reason.
X_LIFE_RESERVE = 10


def _pick_x_value(
    game: Game, player: PlayerState, card: CardDefinition,
    extra_generic: int = 0, hand_index: int | None = None,
) -> int | None:
    """The X this seat announces for *card* (CR 107.3a), or None where the card
    asks for none.

    **The mana cost is only one of the four places CR 107.3a names**, and this
    asked only that one. Fire Covenant ({1}{B}{R}, "pay X life"), Infernal
    Harvest ({1}{B}, "return X Swamps") and Haunting Misery ({1}{B}{B}, "exile
    X creature cards") print no {X} anywhere, so the AI announced nothing, the
    cast fell back to the 0 an unmade CR 107.3a announcement reads as here, and
    all three shipped spells resolved
    doing precisely nothing — legal, since 0 is a choice, and invisible to both
    honesty checks: the cast is not refused and it does interact. This is the
    same one-place-short reading ``cast_announces_x`` was written for on the
    browser's side of the question, so it is the same reader that answers it.

    The ceiling is not the mana pool for those: it is a life total or a board or
    a hand, and ``_additional_cost_x_ceiling`` is what
    ``_unpayable_additional_cost`` will measure the announcement against — asked
    here so the policy announces exactly what the cast will accept.

    *hand_index* is which copy is being cast, and it matters to the ceiling: the
    spell is on the stack before its costs are paid (CR 601.2a), so it cannot be
    one of the cards discarded for Firestorm's "discard X cards". Omitted by the
    two callers that are pricing a card rather than casting one, where an X one
    too high is a bound and not an announcement.
    """
    if "{X}" not in card.mana_cost.upper():
        if not cast_announces_x(card, from_zone=_cast_zone(card)):
            return None
        seat = next(
            (i for i, seated in enumerate(game.players) if seated is player), 0
        )
        bound = game._additional_cost_x_ceiling(
            seat, card, from_zone=_cast_zone(card), spell_hand_index=hand_index,
        )
        if bound is None:
            return None
        # **The ceiling is what the cast will accept, not what a seat should
        # pay.** For "pay X life" it is the seat's whole life total (CR 119.4
        # lets a player pay all of it), so the announcement was X = 20 at 20
        # life: Fire Covenant and Hatred each paid their caster down to zero,
        # and the game was lost to the state-based check behind the spell
        # (CR 704.5a). The same reserve every other life price in this policy
        # keeps (`ai_casts.BUYBACK_LIFE_RESERVE`); with nothing above it the X is 0 and
        # the caller does not propose the cast.
        if _pays_x_in_life(card):
            bound = min(bound, max(0, player.life - X_LIFE_RESERVE))
            # A smaller size asked for by `ai_casts._cast_candidate_sized`, which
            # weighs each one.
            asked = _LIFE_X_ASKED.get()
            if asked is not None and asked[0] is card and 0 < asked[1] < bound:
                return asked[1]
        return bound

    if "{X}" not in _charged_in_place_of_mana_cost(card)[0].upper():
        # CR 107.3b: "If a player is casting a spell that has an {X} in its
        # mana cost, the value of X isn't defined by the text of that spell,
        # and an effect lets that player cast that spell while paying neither
        # its mana cost nor an alternative cost that includes X, then the only
        # legal choice for X is 0." A flashback cost with no X in it, a waiver.
        # The cast path resolves exactly that; the caller does not propose an
        # X of nothing.
        return 0
    max_x = _max_affordable_x(game, player, card, extra_generic)
    return max_x

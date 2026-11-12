"""What a cast that names **several** targets names — one pick per slot, or
one per role.

``ai_targets`` answers a cast with one target (one object, a spell on the
stack, an Aura's host, a graveyard card an exile denies); an announcement
naming several is a different shape, asked of the same candidate being built
(its mode, its offers, its zone: ``ai_actions``) and chosen out of the same
enumeration the browser's picker is built from, so nothing proposed is a
target the cast gate refuses:

* **several targets** (:func:`_choose_several_targets`) — "up to N", "X
  target …", "another target … for each additional {1}{R} you paid": the
  most the announcement allows, each slot on the board its step wants
  (``ai_slot_sides.several_target_slot_sides``), the cards out of a
  graveyard the ones worth most back
  (``ai_graveyard_returns.ranked_graveyard_slots``);
* **roles** (:func:`_choose_role_targets`) — "target creature and target
  land", "any number of target opponents": a chain walked depth-first over
  the picker's own tree (:func:`_role_chain`), each role on the side the step
  spending it wants (``ai_slot_sides.role_target_sides``), announced one
  entry per role (:func:`_role_answer`, ``CastAction.target_role_refs``).

Its twin among the valuation readers is ``ai_slot_sides`` — which board each
slot or role belongs on — as ``ai_target_sides`` is ``ai_targets``'. The role
chooser is asked by ``ai_scoring`` too, reached late
(``engine/late_modules.py``), so a roles spell weighed in the abstract is the
cast the seat would make.
"""

from __future__ import annotations

from .ai_target_sides import best_counted_target_seat, spell_target_side
from .ai_slot_sides import (
    announced_roles_loop_side,
    role_target_sides,
    several_target_slot_sides,
)
from .ai_standing import permanent_worth
from .ai_graveyard_returns import ranked_graveyard_slots
from .per_color_targets import ONE_TARGET_PER_COLOR, one_per_color_slots
from .game import Game
from .target_roles import OPTIONAL_ROLE, PER_OPPONENT_ROLE
from .models import CardDefinition
from .oracle import compile_card_oracle
from .oracle_types import cost_target_count
from .targeting import cast_target_slot, instructions_as_announced, spec_roles
from .ai_actions import (
    _OFFERS_ANNOUNCED,
    _announced_mode,
    _announced_steps,
    _cast_zone,
    _cast_spec,
)
from .ai_scoring import _announcement, _rehearse_announcement, _choose_target_for_spell


def _preferred_role_option(
    options: list[dict], caster_index: int, card: CardDefinition, game: Game
) -> dict:
    """Which of one role's legal answers this seat takes.

    The first, for every role whose object is on a battlefield — the policy
    :func:`_choose_role_targets` documents, safe because the walk has already
    dropped any first choice that leaves a later role with nothing.

    **A seat is the exception, and it is a valuation rather than a policy
    weight.** "Lunge deals 2 damage to target creature and 2 damage to target
    player or planeswalker" offers every living seat for its player role, and
    the caster's own is first in the list — so taking the first burned the
    caster for two. Which seat a spell wants is a question the policy already
    answers for every one-target spell (:func:`_choose_target_for_spell`,
    scoring the caster against the seat the attack policy picks), and the roles
    walk is the same question about the same card: asking it here is one
    reader of one answer rather than a second rule about who to point a spell
    at.

    The preference is applied only when that seat is one the walk offered, so
    a role narrowed to "target **opponent**" is never widened by it — and the
    first option stays the answer whenever it is not.
    """
    if not options or options[0].get("kind") != "player":
        return options[0]
    # …and where the seat is the one a **count** is taken on ("…in excess of
    # the number of creatures target opponent controls", Superior Numbers),
    # which seat is the one the count comes out best on
    # (``ai_target_sides.best_counted_target_seat``): every option is already
    # an opponent, so the side is settled and only the number is left.
    program = compile_card_oracle(card)
    counted = best_counted_target_seat(
        game, caster_index,
        instructions_as_announced(
            card, program, _OFFERS_ANNOUNCED.get() or {},
            mode_index=_announced_mode(card),
        ),
        [option.get("seat") for option in options], card,
    )
    if counted is not None:
        return next(option for option in options if option.get("seat") == counted)
    wanted = _choose_target_for_spell(card, caster_index, game)
    return next(
        (option for option in options if option.get("seat") == wanted), options[0]
    )


def _choose_role_targets(
    game: Game, caster_index: int, card: CardDefinition
):
    """Pick one target per **role** for a spell naming several kinds of target:
    ``(seat, slots, ids, stack, refs)`` (`_role_answer`; *refs* is the
    announcement, `CastAction.target_role_refs`).

    ``None`` when *card* names no roles at all — every other spell in the pool —
    and ``()`` when it names them and no chain this seat would announce exists,
    which is a refusal rather than an absence: CR 601.2c fills every role or
    the spell is not cast.

    The chain comes from ``cast_target_spec``, the same walk the browser's
    picker is handed, so the AI and a human seat are offered exactly the same
    choices — a first choice leaving a later role with nothing is not in the
    list.

    **Which of a role's legal answers is a valuation, per role**
    (``ai_slot_sides.role_target_sides``). Taking the first option at each level
    was the whole policy, and the first option is the first board in seat
    order: Withdraw returned two of its caster's own creatures, Fumarole
    destroyed its caster's creature and land, Lunge burned its caster's
    creature — fifteen spells across both manifest roles, measured on a
    mirrored board. Each role is now answered from the side the step that
    spends it wants, and a role with no legal answer on that side is no chain
    at all: the alternative is a denial aimed at the caster's own board or a
    gift at an opponent's, the single-target chooser's rule
    (`ai_targets._choose_single_object_target`) and for its reason.

    The walk backtracks, because a side makes a first pick able to strand a
    later role the unfiltered walk had an answer for ("another target
    creature" with the only other opposing creature already taken is still
    answered by the *other* order).
    """
    if not spec_roles(_cast_spec(card, compile_card_oracle(card))):
        return None
    # Under the same announcement the roles test above read (CR 702.33g): a
    # kicked Falling Timber names two creatures and an unkicked one names one,
    # and a chain walked off the other cast's spec is a list of the wrong
    # length — proposed, refused, and proposed again next turn.
    offers = _OFFERS_ANNOUNCED.get()
    # ...and under the mode being weighed (`_announced_mode`): asked with no
    # mode the game answers "modal" and walks no chain, which is why Reign of
    # Chaos — two bullets, both of them roles — was never cast by an AI seat.
    announced = game.cast_target_spec(
        caster_index, card, optional_cost_payments=offers,
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
    )
    options = announced.get("valid_targets") or []
    sides = role_target_sides(card, offers)
    # "Choose any number of target players or planeswalkers. For each of them,
    # … deals damage …" (Kaboom!): every role is aimed where the loop's body
    # says, seats included (``ai_slot_sides.announced_roles_loop_side``) —
    # read as sideless, the walk named the caster's own seat first.
    looped = announced_roles_loop_side(card)
    if looped is not None and not any(sides):
        sides = (looped,) * len(spec_roles(announced))
    optional = optional_role_levels(spec_roles(announced))
    picks = _role_chain(
        options, sides, 0, caster_index, card, game,
        optional=optional,
        best_first=per_opponent_role_levels(spec_roles(announced)),
    )
    if picks is not None and _every_role_an_optional_seat(spec_roles(announced), optional):
        # "**Any number of** target opponents each discard their hands, then
        # draw seven cards." (Wheel and Deal.) The walk answers every role it
        # can, so it named every opponent — and how many to name is the whole
        # decision: an opponent holding two cards is handed five, one holding
        # nine loses two, and naming nobody leaves the spell's own "Draw a
        # card". Each length the chain can stop at, none included, is
        # rehearsed, and the best is announced (`_weighed_seat_prefix`).
        return _weighed_seat_prefix(game, caster_index, card, picks)
    if not picks:
        return ()
    return _role_answer(game, caster_index, picks)


def role_ref(game: Game, pick: dict) -> "dict | None":
    """One role's answer in the announcement's own per-role spelling
    (``target_role_refs``, which `casting._cast_onto_stack` translates with
    `_role_announcement_stamps`): a ``seat``, ``{"stack": True}``, a
    ``graveyard_seat`` / ``graveyard_index`` pair, or a ``permanent_id`` —
    None where a permanent has none (nothing the gate would accept).

    `ai_abilities._choose_activation_role_targets`' ``ref_of`` for a cast."""
    kind = pick.get("kind")
    if kind == "player":
        return {"seat": pick.get("seat")}
    if kind == "stack":
        return {"stack": True}
    if kind == "graveyard":
        return {
            "graveyard_seat": pick.get("seat"),
            "graveyard_index": pick.get("index"),
        }
    permanent_id = game.permanent_id_of(game.permanent_at(pick.get("seat"), pick.get("index")))
    return {"permanent_id": permanent_id} if isinstance(permanent_id, int) else None


def _role_answer(game: Game, caster_index: int, picks: list):
    """A chain of role *picks* as `_choose_role_targets` answers it:
    ``(seat, slots, ids, stack, refs)`` — or ``()`` where no announcement can
    carry it.

    **The announcement is *refs*** (`CastAction.target_role_refs`), one entry
    per role: the only spelling that can say two players (Wheel and Deal's
    opponents, Kaboom!'s players) or a card in a graveyard (Cruel Revival's
    "up to one target Zombie card from your graveyard"). A cast had no such
    field, so an AI seat named at most one player in a chain of seat roles and
    stopped Cruel Revival's chain before its Zombie card — the positional id
    list would have read the card's graveyard slot as a battlefield slot.

    The other four are what every cast has always carried and every gate the
    candidate builders ask still reads, derived from the same picks: a
    **player** role's seat and a **stack** role's spell travel off the
    positional lists, held as ``None`` there because those lists are
    positional in role order; a graveyard role likewise. The seat is the first
    player named, else the first board a permanent role is on (the ids address
    the boards a roles spell spans, CR 400.7); *stack* is the one spell a stack
    role names (`target_stack_index`).
    """
    off_board = ("player", "stack", "graveyard")
    ids = [
        None if pick.get("kind") in off_board
        else game.permanent_id_of(game.permanent_at(pick["seat"], pick["index"]))
        for pick in picks
    ]
    if not all(value is None or isinstance(value, int) for value in ids):
        return ()
    seats = [pick["seat"] for pick in picks if pick.get("kind") == "player"]
    spells = [
        len(game.stack) - 1 - pick["stack_index"]
        for pick in picks if pick.get("kind") == "stack"
    ]
    if len(spells) > 1:
        # Two stack roles would be one spell named twice. Skipped rather than
        # cast.
        return ()
    refs = [role_ref(game, pick) for pick in picks]
    if any(ref is None for ref in refs):
        return ()
    seat = seats[0] if seats else next(
        (pick["seat"] for pick in picks if pick.get("kind") not in off_board),
        caster_index,
    )
    indices = [
        None if pick.get("kind") in off_board else pick["index"] for pick in picks
    ]
    return seat, indices, ids, (spells[0] if spells else None), refs


def _names_x_targets(card: CardDefinition) -> bool:
    """Whether *card*'s cast names "**X** target …" for an X its caster
    announces — the spec's ``x_targets`` on a slot printed as an exact count
    (Winter Blast), not "up to X" (Reap, whose X is counted off the board and
    answered by ``Game.announced_cast_x``)."""
    program = compile_card_oracle(card)
    slot = cast_target_slot(
        card, program, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    )
    if slot is None or not slot[0].get("x_targets"):
        return False
    described = (slot[1].payload or {}).get("targets")
    return isinstance(described, dict) and described.get("quantifier") == "exactly"


def _every_role_an_optional_seat(roles, optional: frozenset) -> bool:
    """Whether every role of an announcement is a **player** a cast may leave
    unnamed — "any number of target opponents" (Wheel and Deal), the chain of
    optional seat roles ``target_roles.any_number_of_opponents_roles`` builds."""
    roles = list(roles or ())
    return bool(roles) and all(
        position in optional and isinstance(role, dict) and role.get("kind") == "player"
        for position, role in enumerate(roles)
    )


def _weighed_seat_prefix(game: Game, caster_index: int, card: CardDefinition, picks):
    """`_choose_role_targets`' answer for a chain of optional seat roles: the
    first *n* of the walk's *picks* (every seat it would name, in its order),
    for the *n* whose cast leaves the caster furthest ahead — rehearsed one
    length at a time (`_rehearse_announcement`), naming nobody included.

    Ties go to the shorter announcement; a length nobody could rehearse is not
    weighed, and with none weighable the walk's full answer stands, as it did.
    The shape is the one every roles answer has: ``(seat, slots, ids, stack,
    refs)``, with no seat at all for a cast that names none (the engine reads
    an announcement of no seat and no object as naming no opponent) and every
    seat named in *refs*, one per role — so a prefix of two opponents is two
    seats (CR 601.2c), which this stopped at before a cast could carry a
    seat per role.
    """
    def shaped(chosen):
        seats = [pick["seat"] for pick in chosen]
        return (
            seats[0] if seats else None,
            [None] * len(chosen), [None] * len(chosen), None,
            [{"seat": seat} for seat in seats] or None,
        )

    best, best_swing = None, None
    for length in range(len(picks) + 1):
        answer = shaped(picks[:length])
        rehearsal = _rehearse_announcement(
            game, caster_index, card,
            _announcement(
                game, card, target=answer[0], caster=caster_index,
                permanent_index=answer[1], permanent_ids=answer[2],
                role_refs=answer[4],
            ),
        )
        if rehearsal is None or not rehearsal.accepted:
            continue
        if best_swing is None or rehearsal.swing > best_swing + 1e-9:
            best, best_swing = answer, rehearsal.swing
    if best is None:
        return shaped(picks) if picks else ()
    return best


def optional_role_levels(roles) -> frozenset:
    """The positions of *roles* an announcement may leave unanswered
    (``target_roles.OPTIONAL_ROLE``, Primal Might's "up to one" fight)."""
    return frozenset(
        position for position, role in enumerate(roles or ())
        if isinstance(role, dict) and role.get(OPTIONAL_ROLE)
    )


def per_opponent_role_levels(roles) -> frozenset:
    """The positions of *roles* that are one opponent's permanents
    (``target_roles.PER_OPPONENT_ROLE``, Blatant Thievery's "target permanent
    that player controls")."""
    return frozenset(
        position for position, role in enumerate(roles or ())
        if isinstance(role, dict) and PER_OPPONENT_ROLE in role
    )


def _role_chain(
    options: list[dict], sides, level: int, caster_index: int,
    card: CardDefinition, game: Game, *, optional: frozenset = frozenset(),
    best_first: frozenset = frozenset(),
) -> "list[dict] | None":
    """One pick per role from *options* down, each on the side its role wants
    (``sides[level]``) — or None when no such chain exists.

    Depth-first over the engine's own tree, so every chain it can return is one
    the cast gate accepts. A level offering seats is answered by
    `_preferred_role_option` alone, as it always was; a level offering
    permanents tries each on the wanted side in the enumeration's order.

    **An optional role** (*optional*, by level) is answered where it can be and
    left unanswered where it cannot: "…then it fights **up to one** target
    creature you don't control" with nothing on the other side to fight is
    still a pump the gate accepts, and a chain that refused it would leave
    Primal Might in hand. Only trailing roles are ever optional — Primal
    Might's last, or every role of Wheel and Deal's "any number of target
    opponents", which this walk answers at every level it can (so it names
    every opponent; stopping early is a choice it does not weigh)
    (``target_descriptions._slot_roles_spec``), so stopping there is the
    announcement ending.
    """
    if not options:
        return []
    want = sides[level] if level < len(sides) else None
    if options[0].get("kind") == "player" and want not in ("you", "opponent"):
        candidates = [_preferred_role_option(options, caster_index, card, game)]
    elif options[0].get("kind") == "stack":
        # A spell role is answered with a spell somebody else controls: every
        # step in the pool that spends one counters it, and a seat that
        # countered its own spell to deal the damage beside it has paid for
        # two cards to get half of one. Topmost first, the engine's own order.
        depth = len(game.stack)
        candidates = [
            option for option in options
            if 0 <= depth - 1 - option["stack_index"] < depth
            and game.stack[depth - 1 - option["stack_index"]].caster_index
            != caster_index
        ]
    elif want in ("you", "opponent"):
        # A seat option is on its own side, as a permanent is on its
        # controller's — a level offering both (a player-or-planeswalker role)
        # is narrowed as one board.
        candidates = [
            option for option in options
            if option.get("kind") not in ("permanent", "player")
            or (option.get("seat") == caster_index) == (want == "you")
        ]
    else:
        candidates = options
    if level in best_first:
        # **One opponent's permanents, and one of them is the spell's**
        # (Blatant Thievery: "only one permanent from each player"). Every
        # candidate is on the board the role is for, so which one is the whole
        # decision — and the enumeration's order is the battlefield's, which
        # puts the lands first: the seat took a Swamp from a table of
        # creatures. The most valuable first (``ai_standing.permanent_worth``,
        # what a permanent is worth to whoever controls it), stable.
        candidates = sorted(
            candidates,
            key=lambda option: -_role_option_worth(game, option),
        )
    elif candidates and all(option.get("kind") == "graveyard" for option in candidates):
        # **A card in a graveyard** ("Return up to one target Zombie card from
        # your graveyard to your hand", Cruel Revival) — a role no cast could
        # announce before a cast carried ``target_role_refs``, so no chain
        # reached one. The pile's order is when each card arrived, not what it
        # is worth: the card with the greatest mana value first, stable — the
        # activation side's pick for "target card from a graveyard"
        # (`ai_abilities._activation_candidate`).
        candidates = sorted(
            candidates, key=lambda option: -_graveyard_option_value(game, option),
        )
    for pick in candidates:
        rest = _role_chain(
            pick.get("next") or [], sides, level + 1, caster_index, card, game,
            optional=optional, best_first=best_first,
        )
        if rest is not None:
            return [pick, *rest]
    return [] if level in optional else None


def _role_option_worth(game: Game, option: dict) -> float:
    """What the permanent a role option names is worth, 0 for anything else."""
    if option.get("kind") != "permanent":
        return 0.0
    permanent = game.permanent_at(option.get("seat"), option.get("index"))
    return permanent_worth(permanent) if permanent is not None else 0.0


def _graveyard_option_value(game: Game, option: dict) -> float:
    """The mana value of the graveyard card a role option names, 0 when the
    slot holds none."""
    pile = game.players[option.get("seat")].graveyard
    index = option.get("index")
    held = pile[index] if isinstance(index, int) and 0 <= index < len(pile) else None
    return float(getattr(held, "cmc", 0) or 0)


def _choose_several_targets(
    game: Game, caster_index: int, card: CardDefinition,
    *, x_value: int | None = None, preferred_seat: int | None = None,
) -> tuple[int, list[int], list[int] | None] | tuple[()] | None:
    """Pick ``(seat, [permanent_index, …], [permanent_id, …] | None)`` for a spell
    naming several targets, None when the card names no such choice, or ``()``
    when it names an exact number the board cannot supply.

    Which cards this reaches is *derived*, never a list of names: the compiled
    program carries the maximum (``engine/targeting.py``'s ``max_targets``), so a
    card printed with the same template is covered the day it is ingested. The
    cheap derivation is asked first and the expensive enumeration only when it
    says yes, because this runs for every card in hand on every AI decision.

    Taking the maximum is the whole policy, and it is a policy rather than a
    rule: "up to N" may legally choose fewer, but every printed card carrying
    this template gives a benefit per target, so more is better. A card that
    ever wants fewer needs a valuation, not a special case here.
    """
    program = compile_card_oracle(card)
    spec = _cast_spec(card, program)
    maximum = (spec or {}).get("max_targets")
    # "Return **up to X** target cards from your graveyard to your hand, where X
    # is the number of black permanents target opponent controls **as you cast
    # this spell**." (Reap.) The count is a board count, so the card-only
    # derivation above cannot carry it — it reports ``x_targets``, "however many
    # the announced X pays for" — and a chooser that stopped there named no
    # targets at all, which is a spell that resolves every game and does
    # nothing. Asked of the game through the *same* reader the announcement gate
    # and the browser's picker use, so the AI never proposes a count CR 601.2c
    # then refuses.
    #
    # Derived, not name-keyed: any card printing the same tail is covered the
    # day it is ingested. A spell whose X the *caster* announces (Shattered
    # Crypt's {X} cost) has no answer here and keeps the behaviour it had.
    # …counted on the opponent this seat names: Reap's "target opponent" is a
    # target of the same announcement (``target_descriptions.
    # ANNOUNCED_SEAT``) and every legal one fixes a different X, so which
    # to name is the one whose X is largest (``best_counted_target_seat``). It
    # rides the cast's seat field — the pile is the caster's own whatever it
    # says — so it is the seat this chooser returns.
    counted_seat = None
    counted_options = (
        game._announced_seats(caster_index, card, spec)
        if (spec or {}).get("own_graveyard_only") else None
    )
    if counted_options:
        counted_seat = best_counted_target_seat(
            game, caster_index,
            instructions_as_announced(
                card, program, _OFFERS_ANNOUNCED.get() or {},
                mode_index=_announced_mode(card),
            ),
            sorted(
                counted_options,
                key=lambda seat: seat != game._default_opposing_seat(caster_index),
            ),
            card,
        )
    announced = (
        game.announced_cast_x(
            caster_index, card, mode_index=_announced_mode(card), seat=counted_seat,
        )
        if (spec or {}).get("x_targets") else None
    )
    # "Exile **two** target artifacts" (Dust to Dust): a printed count is the
    # number, not a ceiling (CR 601.2c) — the spec's ``exact_targets``, which
    # the browser's confirm has always waited for and the cast gate now counts
    # (`legality_cast_gates.cast_target_count_refusal`). Read here for every branch below;
    # it was read only for the cost-sized one, so this chooser named one
    # creature for "two target creatures" whenever one was all the side held.
    exact = bool((spec or {}).get("exact_targets"))
    sized_by_x = False
    if announced is not None:
        if announced < 1:
            # CR 601.2c: naming nothing is a legal announcement for an "up to"
            # spell, and it is what the caller does when this returns None — so
            # the honest answer at X=0 is "no several-target choice to make".
            return None
        maximum = announced
        exact = False
    elif (
        (spec or {}).get("x_targets")
        and isinstance(x_value, int) and x_value >= 1
        and _names_x_targets(card)
    ):
        # "Tap **X** target creatures" (Winter Blast): up to the X the lands
        # can pay, and the caller then announces the X this board filled. With
        # nothing to name there is no cast worth an X of one or more.
        maximum = x_value
        sized_by_x = True
    elif not isinstance(maximum, int) or maximum <= 1:
        # "Destroy target artifact. For each additional {1}{R} you paid, destroy
        # **another** target artifact…" (Primitive Justice): the count is fixed
        # by CR 601.2b's announcement — the candidate being built's own
        # (`_OFFERS_ANNOUNCED`), read through the reader the announcement gate
        # sizes it by. With nothing taken it is the base alone, and it can be
        # one. One is still a number this chooser has to answer: CR 601.2c
        # refuses an announcement that names no target
        # (`legality_cast_gates.cast_target_refusal`), and a several-target handler has no
        # resolution-time board scan to fall into the way a single-target one
        # does. Without this the seat re-proposes the spell every turn and is
        # refused every turn, which is exactly what `refused_casts` counts.
        maximum = cost_target_count(
            (spec or {}).get("cost_targets"), _OFFERS_ANNOUNCED.get() or {}
        ) or 0
        if maximum < 1:
            return None
        exact = bool((spec or {}).get("exact_targets"))
    # Enumerated for the announcement being built, like the spec above: the
    # game's own picker reads an unanswered offer as declined (CR 702.33g), so
    # asked without it a kicked-only several-target part -- Nightscape
    # Battlemage's "return up to two target nonblack creatures" -- had a
    # maximum of two and a candidate list of none, and fell through to the
    # one-target chooser.
    legal = game.cast_target_spec(
        caster_index, card, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
    ).get("valid_targets") or []
    by_seat: dict[int, list[int]] = {}
    # A graveyard card is not a permanent and has no `permanent_id`; its slots
    # are indices into one player's graveyard, so they are collected under that
    # seat and sent as indices. Same stated policy - take the maximum - because
    # the per-target benefit argument is the same.
    wanted_kind = (
        "graveyard" if (spec or {}).get("kind") == "graveyard_creature" else "permanent"
    )
    for entry in legal:
        if entry.get("kind") != wanted_kind:
            continue
        by_seat.setdefault(int(entry["seat"]), []).append(int(entry["index"]))
    if not by_seat:
        # An X-sized list with nothing to name has no announcement at an X of
        # one or more (`()`), where every other shape hands on to the
        # one-target chooser as it always has.
        return () if sized_by_x else None
    if wanted_kind == "graveyard":
        # The cards worth most back first, not the pile's order (kg5).
        by_seat = ranked_graveyard_slots(game, caster_index, by_seat, _announced_steps(card, program))
        if (spec or {}).get(ONE_TARGET_PER_COLOR):
            # "For each color, return up to one target card of that color"
            # (All Suns' Dawn): the best card of each colour the pile can
            # fill, in rank order — never two the cast gate refuses together.
            by_seat = {
                pile: one_per_color_slots(game, pile, slots)
                for pile, slots in by_seat.items()
            }

    if sized_by_x or announced is not None:
        # **…and "up to X target creatures, where X is one plus the number of
        # cards named Aether Burst in all graveyards"** (`announced`): the same
        # one printed instance of the word, with its X counted off the board
        # instead of paid for. It fell through to the several-slot default at
        # the bottom of this function — "the caster's own board, because every
        # card carrying the template gives a benefit per target" — which for
        # this one is a bounce: the seat returned its own creatures to its own
        # hand. (Reap, the other card on this branch, names cards in its
        # caster's graveyard and has no second board to land on.)
        #
        # "X target …" is one printed instance of the word, so every slot wants
        # the same board — and which board is the reading the **one-target**
        # chooser has always made for these cards (`spell_target_side`, then
        # the score's seat), because until the count gate they reached that
        # chooser: the seat named one permanent for an X of five. Same seat
        # order, more of its permanents, so a tap or a destroy sized by X is
        # aimed where it was and never at the caster's own board by the
        # several-target default below.
        side = spell_target_side(card)
        others = sorted(seat for seat in by_seat if seat != caster_index)
        if side == "you":
            order = [caster_index]
        elif side == "opponent":
            order = others
        else:
            order = [
                seat for seat in dict.fromkeys(
                    [preferred_seat, caster_index, *others]
                ) if seat is not None
            ]
        seat = next((seat for seat in order if by_seat.get(seat)), None)
        if seat is None:
            return ()
        if counted_seat is not None:
            # The cards out of the caster's own pile, the seat field naming the
            # opponent the X was counted on.
            return counted_seat, by_seat[seat][:maximum], None
        return seat, by_seat[seat][:maximum], None

    # Which board each slot wants, derived from the compiled program rather than
    # from the card's name. A card whose slots all want the same thing — every
    # one printed before Rookie Mistake — takes the single-seat path below
    # unchanged, so this is byte-identical for Basri's Acolyte and Basri's Aegis.
    sides = several_target_slot_sides(
        program,
        instructions_as_announced(
            card, program, _OFFERS_ANNOUNCED.get() or {},
            mode_index=_announced_mode(card),
        ),
    )
    if sides and len(set(sides)) > 1:
        picks: list[tuple[int, int]] = []
        # Slots that name a side first, so a slot with no preference cannot
        # take the one permanent a later slot needed (Deadshot's "another
        # target creature" with a single opposing creature on the table).
        slot_order = sorted(
            range(maximum),
            key=lambda index: (index >= len(sides) or sides[index] is None, index),
        )
        placed: dict[int, tuple[int, int]] = {}
        for index in slot_order:
            want = sides[index] if index < len(sides) else None
            if want == "you":
                order = [caster_index]
            elif want == "opponent":
                order = sorted(s for s in by_seat if s != caster_index)
            else:
                order = [caster_index] + sorted(s for s in by_seat if s != caster_index)
            chosen = next(
                (
                    (seat, slot)
                    for seat in order
                    for slot in by_seat.get(seat, [])
                    if (seat, slot) not in placed.values()
                ),
                None,
            )
            if chosen is not None:
                placed[index] = chosen
        picks = [placed[index] for index in sorted(placed)]
        if len(picks) < maximum and (
            exact or sorted(placed) != list(range(len(placed)))
        ):
            # A slot whose side holds nothing legal. The slots of such a spell
            # are different effects ("target creature gets +0/+2 and another
            # target creature gets -2/-0"), so leaving one out from the middle
            # shifts each later effect onto the wrong slot — not proposed. A
            # trailing "up to one" left empty (Primal Might with no opposing
            # creature) is still an announcement the card prints.
            return ()
        if picks:
            ids = []
            for seat, slot in picks:
                permanent = game.permanent_at(game.players[seat], slot)
                ids.append(None if permanent is None else permanent.permanent_id)
            if all(isinstance(value, int) for value in ids):
                # `target_player_index` still has to be a seat; the ids are what
                # actually address the two boards (CR 400.7), and `_stack_push`
                # respects supplied ids over a re-derivation from one seat.
                return picks[0][0], [slot for _, slot in picks], ids

    # A side every slot agrees on is still an answer, and the fallback below has
    # always assumed the caster's own board. Rookie Mistake needed slots that
    # *disagree*; a several-target tap has slots that agree on the opponent, and
    # reading only the disagreement left the AI tapping its own creatures. Still
    # one seat, so the ids stay unnecessary and every card whose slots agree on
    # "you" is byte-identical.
    if sides and set(sides) == {"opponent"}:
        opponents = sorted(seat for seat in by_seat if seat != caster_index)
        if opponents:
            if exact and len(by_seat[opponents[0]]) < maximum:
                # A count the announcement fixed and this board cannot fill
                # (a Primitive Justice paid twice with one artifact to aim
                # at): `()`, so the caller declines this announcement and
                # tries the next smaller one.
                return ()
            return opponents[0], by_seat[opponents[0]][:maximum], None
        # Every slot wants an opponent's permanent and no opponent has one. The
        # fallback below would aim them at the caster's own, which for an
        # "up to" denial (Panic Attack, Tidal Surge) is a spell spent on
        # hampering the seat that cast it.
        return ()
    if sides and set(sides) == {"you"} and caster_index not in by_seat:
        # …and the gift the other way round: every slot wants the caster's own
        # permanent and the caster has none, so the fallback below would put
        # Basri's Aegis' counters on an opponent's creatures.
        return ()

    # One seat's worth: the index list is positional on a single battlefield
    # (`target_player_index` names whose), so a cross-seat spread needs the ids
    # above. Taking the maximum from the caster's own board is the whole policy
    # where no slot names a side: "up to N" may legally choose fewer, but every
    # card carrying that template gives a benefit per target, so more is better.
    seat = caster_index if caster_index in by_seat else min(by_seat)
    if exact and len(by_seat[seat]) < maximum:
        return ()
    return seat, by_seat[seat][:maximum], None

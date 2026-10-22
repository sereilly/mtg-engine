"""What a cast the policy proposes names as its target.

One chooser for each shape of announcement, each asked of the candidate
being built (its mode, its offers, its zone: ``ai_actions``) and each choosing
out of the engine's own enumeration — the list a person's picker is built
from — so nothing proposed is a target the cast gate refuses:

* **one object** (:func:`_choose_single_object_target`) — the candidates the
  effect would act on, look-alikes dropped, each rehearsed and the one that
  does most kept (:func:`_best_target`); and for a spell that may name a
  player or a permanent, whether the permanent beats the seat
  (:func:`_better_than_the_seat`);
* **several targets** and **roles** (:func:`_choose_several_targets`,
  :func:`_choose_role_targets`) — one pick per slot or per role, each on the
  side its step wants (``ai_target_sides``);
* **a spell on the stack** (:func:`_guarded_stack_target`,
  :func:`_chosen_stack_target`), and "a source of your choice" (CR 609.7a,
  :func:`_choose_damage_source`), which is chosen rather than targeted;
* **an Aura's host** (:func:`_choose_aura_target`), and the host of an Aura
  put onto the battlefield without a cast (:func:`choose_returning_aura_host`,
  CR 303.4f);
* **a card in a graveyard** an exile effect denies
  (:func:`_graveyard_denial_target`, on the cast's road and the activation's).

A divided spell's targets and shares are ``ai_divisions``'; the player a
spell names is ``ai_scoring._choose_target_for_spell``'s, which a card's
abstract worth asks too.
"""

from __future__ import annotations

import re

from .ai_weighed_cast import SPELL_TYPES
from .ai_target_sides import (
    entry_trigger_target_side,
    role_target_sides,
    several_target_slot_sides,
    spell_denies_its_own_target,
    spell_target_side,
)
from .ai_rehearsal import has_a_creature_to_fight_with, permanent_worth
from .ai_prompt_readers import (
    exiles_a_graveyard_target,
    graveyard_denial_order,
)
from .game import Game
from .mixins.stack import (
    aura_enchant_noun,
    enchant_noun_seat,
    permanent_matches_enchant_noun,
)
from .target_restrictions import forbidden_target
from .models import CardDefinition
from .oracle import compile_card_oracle
from .oracle_types import cost_target_count
from .targeting import (
    GRAVEYARD_TARGET_KIND,
    cast_target_slot,
    instructions_as_announced,
    spec_roles,
)
from .cost_pickers import spec_is_a_cost
from .ai_actions import (
    _OFFERS_ANNOUNCED,
    _announced_mode,
    _announced_steps,
    _cast_zone,
    _cast_spec,
)
from .ai_scoring import (
    choose_attack_target,
    _announcement,
    _rehearse_announcement,
    _weighed_through_the_fight,
    _leaves_nothing,
    _choose_target_for_spell,
)
from .ai_cast_gates import _targets_are_optional


#: How many distinct targets one cast is rehearsed at. A rehearsal is a cast,
#: and a board of forty permanents is not forty questions worth asking.
TARGETS_WEIGHED = 8


def _graveyard_denial_target(
    game: Game, player_index: int, legal
) -> "tuple[int, int] | None":
    """``(pile's seat, slot)`` — the card an "exile target card from a
    graveyard" is aimed at — or None to name nothing.

    *legal* is the picker's own list for the announcement (``valid_targets``).
    A card in **another seat's** pile, the ones its owner could still cast
    from there first (`ai_prompt_readers.graveyard_denial_order`), then seat and
    pile order. None when no other seat's pile holds a legal card: the
    announcement is then what it always was — a seat and no slot, which the
    handler answers.

    **Why the policy names it at all.** A bare announcement falls to the
    handler's scan, "the first graveyard with a card in it, in seat order" —
    so the seat in chair 0 exiled a card of its own with Coffin Purge, Cremate,
    Headstone, Crypt Creeper, Steamclaw, Grave Robbers and Scavenging Ooze,
    and the seat in chair 1 exiled its opponent's, off one board. A graveyard
    card is announced as a seat and a slot in that seat's pile, the spelling
    the cast and activation gates check (`targeting.GRAVEYARD_TARGET_KIND`).
    """
    by_seat: dict[int, list[int]] = {}
    for entry in legal or ():
        if entry.get("kind") != "graveyard":
            continue
        seat = int(entry["seat"])
        if seat != player_index:
            by_seat.setdefault(seat, []).append(int(entry["index"]))
    for seat in sorted(by_seat):
        ordered = graveyard_denial_order(game, seat, by_seat[seat])
        if not ordered:
            continue
        # One card, not "up to three": among the cards its owner could no
        # longer cast anyway, the one of greatest mana value — what a
        # recursion would most want back, and what an exile that pays its
        # source for the card (Scavenging Ooze's creature) is worth most
        # against. The castable ones stay first, whatever they cost.
        from .flashback import has_flashback

        pile = game.players[seat].graveyard
        first = ordered[0]
        if not has_flashback(pile[first], game=game, owner_seat=seat):
            first = max(
                ordered,
                key=lambda slot: (float(getattr(pile[slot], "cmc", 0) or 0), -slot),
            )
        return seat, first
    return None


def _cast_graveyard_denial(
    game: Game, player_index: int, card: CardDefinition
) -> "tuple[int, int] | None":
    """`_graveyard_denial_target` for the cast candidate being built: the
    spell's own spec and steps (its mode, its offers, the zone it leaves),
    and the picker's list for that announcement."""
    program = compile_card_oracle(card)
    if not _one_graveyard_card_is_denied(
        _cast_spec(card, program), _announced_steps(card, program)
    ):
        return None
    legal = game.cast_target_spec(
        player_index, card, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
    ).get("valid_targets") or []
    return _graveyard_denial_target(game, player_index, legal)


def _one_graveyard_card_is_denied(spec, instructions) -> bool:
    """Whether an announcement described by *spec* names exactly **one card in
    a graveyard** and the steps behind it exile that card — the shape
    `_graveyard_denial_target` answers."""
    return (
        isinstance(spec, dict)
        and spec.get("kind") == GRAVEYARD_TARGET_KIND
        and not spec_roles(spec)
        and not spec_is_a_cost(spec)
        and not spec.get("max_targets")
        and not spec.get("x_targets")
        and exiles_a_graveyard_target(instructions)
    )


#: Printed phrases that make an Aura's effect a cost to whoever controls its
#: host, so it belongs on an opponent's permanent. Text probes, and tuning
#: like every other weight in this module.
_HARMFUL_AURA_MARKERS = (
    "gets -",
    "doesn't untap",
    "tap enchanted",
    "you control enchanted",
    "can't attack",
    "can't block",
)
#: …and the Auras whose whole effect is a price charged to **the host's
#: controller** rather than to the host: "this Aura deals 1 damage to that
#: player" (Wanderlust, Cursed Land, Warp Artifact), "…to that land's
#: controller" (Psychic Venom), "its controller loses life equal to its power"
#: (Death Watch). None of them printed a phrase the list above reads, so the
#: AI cast every one of them onto its **own** permanent — 21 of the 22 shipped
#: Auras printing one, measured with a host of every kind on both boards — and
#: paid the damage itself every upkeep. Read the same way from a Licid's text.
_HARMFUL_AURA_PATTERN = re.compile(
    r"damage to (?:that player|its controller|that [a-z]+'s controller)"
    r"|(?:that player|its controller) loses (?:\d+|x|life)"
)


def _aura_harms_its_host(card: CardDefinition) -> bool:
    """Whether *card*'s text, as an Aura, works against the permanent it
    enchants and that permanent's controller — so the AI puts it on an
    opponent's permanent rather than its own.

    One reader for the two ways an Aura gets a host: cast onto one
    (`_choose_aura_target`), and a permanent that *becomes* one and attaches
    itself (`ai_valuation.source_becomes_an_aura`, the Licids), where the
    activation chooser asks the same question of the same text.
    """
    text = (card.oracle_text or "").lower()
    return (
        any(marker in text for marker in _HARMFUL_AURA_MARKERS)
        or _HARMFUL_AURA_PATTERN.search(text) is not None
    )


def choose_returning_aura_host(game: Game, seat: int, card: CardDefinition, legal: list):
    """Which of *legal* an Aura card that *seat* is putting onto the
    battlefield enchants, where the effect names no host (CR 303.4f:
    Replenish, Cleansing Meditation).

    The cast chooser's question asked of a choice that is not a target: an
    Aura whose text works against its host (``_aura_harms_its_host``) goes on
    a permanent somebody else controls, any other on *seat*'s own. A
    preference, not a filter — with only the other side's permanents legal,
    one of them is still the answer — and stable, so board order breaks every
    tie and a seed still reproduces a run.

    The answer for every seat nobody asks, and the default of the prompt an
    interactive seat is asked (``permanent_choice`` with ``default_prefers:
    "returning_aura_host"``), so a seat answered for lands where this would.
    """
    harmful = _aura_harms_its_host(card)
    ranked = sorted(
        legal,
        key=lambda host: (game.controller_index_of(host) == seat) == harmful,
    )
    return ranked[0]


def _choose_aura_target(game: Game, caster_index: int, card: CardDefinition) -> tuple[int, int] | None:
    """Pick (player_index, permanent_index) for an Aura's enchant target.

    Harmful auras go on an opponent's permanent, beneficial ones on the caster's.
    Returns None when the preferred player has no legal target — the Aura is
    unplayable this turn rather than cast onto a permanent that helps the enemy.
    """
    noun = aura_enchant_noun(card)
    if noun is None:
        return None
    harmful = _aura_harms_its_host(card)
    target_player_index = choose_attack_target(game, caster_index) if harmful else caster_index
    # "Enchant creature **you control**" (Cocoon): however "harmful" the text
    # reads, the clause forbids an opponent's permanent — the same gate the
    # cast path applies (CR 601.2c), asked here so the AI never spends a turn
    # on a cast the game then refuses.
    seat_clause = enchant_noun_seat(noun)
    if seat_clause == "you":
        target_player_index = caster_index
    elif seat_clause == "opponent" and target_player_index == caster_index:
        target_player_index = choose_attack_target(game, caster_index)
    for permanent_index, permanent in enumerate(game.players[target_player_index].battlefield):
        # The spell's own printed targeting restriction (CR 601.2c). Asked here
        # as well as at the cast, and through the same function: a choice only
        # the cast path refuses is an AI turn spent on an action the game then
        # rejects, and a human seat offered a target it cannot take.
        if forbidden_target(game, card, permanent, caster_index):
            continue
        # CR 702.16b: an Aura with a quality cannot be cast targeting a
        # permanent with protection from it. Asked through the cast path's own
        # function for the same reason `forbidden_target` is, one line up — and
        # it was missing, so the AI would pick a creature wearing White Ward for
        # a white Aura, be refused, and pick it again next turn. Invisible until
        # the simulator started building decks that contain both.
        if not game._can_be_targeted(permanent, card, caster_index=caster_index):
            continue
        if permanent_matches_enchant_noun(permanent, noun):
            return target_player_index, permanent_index
    return None


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
    caster for two. Which seat a spell wants is a question this module already
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
    wanted = _choose_target_for_spell(card, caster_index, game)
    return next(
        (option for option in options if option.get("seat") == wanted), options[0]
    )


def _choose_role_targets(
    game: Game, caster_index: int, card: CardDefinition
):
    """Pick one target per **role** for a spell naming several kinds of target.

    ``None`` when *card* names no roles at all — every other spell in the pool —
    and ``()`` when it names them and no chain this seat would announce exists,
    which is a refusal rather than an absence: CR 601.2c fills every role or
    the spell is not cast.

    The chain comes from ``cast_target_spec``, the same walk the browser's
    picker is handed, so the AI and a human seat are offered exactly the same
    choices — a first choice leaving a later role with nothing is not in the
    list.

    **Which of a role's legal answers is a valuation, per role**
    (``ai_target_sides.role_target_sides``). Taking the first option at each level
    was the whole policy, and the first option is the first board in seat
    order: Withdraw returned two of its caster's own creatures, Fumarole
    destroyed its caster's creature and land, Lunge burned its caster's
    creature — fifteen spells across both manifest roles, measured on a
    mirrored board. Each role is now answered from the side the step that
    spends it wants, and a role with no legal answer on that side is no chain
    at all: the alternative is a denial aimed at the caster's own board or a
    gift at an opponent's, the single-target chooser's rule
    (`_choose_single_object_target`) and for its reason.

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
    options = game.cast_target_spec(
        caster_index, card, optional_cost_payments=offers,
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
    ).get("valid_targets") or []
    picks = _role_chain(
        options, role_target_sides(card, offers), 0, caster_index, card, game,
    )
    if not picks:
        return ()
    # A **player** role's answer is the seat itself (Donate's "target player"),
    # and it fills no slot in the positional id list — the seat travels on the
    # field every cast already carries, which is what the resolution reads back.
    # Held as ``None`` in both lists rather than dropped, because those lists
    # are positional in role order and a short one shifts every slot after it.
    #
    # A **stack** role's answer ("Counter target spell and … deals 3 damage to
    # target creature", Suffocating Blast) is held the same way and for the
    # same reason: the spell travels on ``target_stack_index``, the one field
    # a cast names a stack object on.
    off_board = ("player", "stack")
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
    if len(seats) > 1 or len(spells) > 1:
        # Two player roles would be one seat sent twice, which the resolution
        # refuses on the other side of the same fact — and two stack roles one
        # spell. Skipped rather than cast.
        return ()
    # The seat is still sent for every other roles spell too, because every cast
    # carries one; the *ids* are what address the two boards a roles spell may
    # span (CR 400.7).
    seat = seats[0] if seats else next(
        (pick["seat"] for pick in picks if pick.get("kind") not in off_board),
        caster_index,
    )
    indices = [
        None if pick.get("kind") in off_board else pick["index"] for pick in picks
    ]
    return seat, indices, ids, (spells[0] if spells else None)


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


def _role_chain(
    options: list[dict], sides, level: int, caster_index: int,
    card: CardDefinition, game: Game,
) -> "list[dict] | None":
    """One pick per role from *options* down, each on the side its role wants
    (``sides[level]``) — or None when no such chain exists.

    Depth-first over the engine's own tree, so every chain it can return is one
    the cast gate accepts. A level offering seats is answered by
    `_preferred_role_option` alone, as it always was; a level offering
    permanents tries each on the wanted side in the enumeration's order.
    """
    if not options:
        return []
    want = sides[level] if level < len(sides) else None
    if options[0].get("kind") == "player":
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
        candidates = [
            option for option in options
            if option.get("kind") != "permanent"
            or (option.get("seat") == caster_index) == (want == "you")
        ]
    else:
        candidates = options
    for pick in candidates:
        rest = _role_chain(
            pick.get("next") or [], sides, level + 1, caster_index, card, game,
        )
        if rest is not None:
            return [pick, *rest]
    return None


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
    announced = (
        game.announced_cast_x(caster_index, card, mode_index=_announced_mode(card))
        if (spec or {}).get("x_targets") else None
    )
    # "Exile **two** target artifacts" (Dust to Dust): a printed count is the
    # number, not a ceiling (CR 601.2c) — the spec's ``exact_targets``, which
    # the browser's confirm has always waited for and the cast gate now counts
    # (`legality.cast_target_count_refusal`). Read here for every branch below;
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
        # (`legality.cast_target_refusal`), and a several-target handler has no
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


#: Cast specs whose legal answers are not permanents on a battlefield — a
#: player, a spell, a card in a graveyard or a hand, a choice of modes. The
#: single-object chooser below has nothing to say about them.
_NOT_OBJECT_SPECS = frozenset({
    "none", "modal", "player", "stack", "graveyard_creature", "hand_card",
    "spell_or_permanent",
})


def _choose_single_object_target(
    game: Game, caster_index: int, card: CardDefinition, preferred_seat: int,
    *, x_value: int | None = None,
):
    """Name the one permanent a one-object-target spell is cast at:
    ``(seat, index, [permanent_id])``, ``()`` when the side the effect wants
    holds no legal target, or None when *card* is not such a spell.

    **Which permanent is the one the cast does most at.** Every legal target
    on the side the effect wants is a different cast, so each is rehearsed
    (`_best_target`) and the largest swing named: the creature a -2/-2 kills
    rather than the one it only shrinks, the dearest thing a destroy may
    take, the body a pump does most on. This named the first legal permanent
    in battlefield order — whichever the seat happened to play first.

    A spell that may name **a player or a permanent** ("any target") is
    weighed the same way against the seat it would otherwise be aimed at:
    three damage is worth a creature it kills more often than it is worth
    three life (`_better_than_the_seat`).

    The cast used to name a **seat** and leave the permanent to the handler's
    board scan — the headless convention, which W1G2 measured 156 of 182
    creature-targeting spells accepting. Two ways that resolved doing nothing,
    both measured in NEM's simulation: a handler with no scan to fall into
    (Sivvi's Valor: "its target is gone"), and a seat with no permanent the
    printed noun admits (Topple aimed at a seat whose creatures were not the
    greatest). Naming the permanent out of the engine's own enumeration — the
    list the browser's picker offers a human — answers both, and the first
    legal permanent on the seat is the one the scan would have taken.

    Which seat is ``ai_target_sides.spell_target_side``: a side the effect wants
    with nothing legal on it is ``()``, because the alternative is aiming a
    denial at the caster's own board or a gift at an opponent's. With no side,
    *preferred_seat* (the score's choice) first and then any seat — a spell that
    can only do something on the other board is cast there rather than at
    nothing. A spec offering a **player** is left alone: "any target" damage is
    aimed at a face by the seat it already carries.
    """
    program = compile_card_oracle(card)
    spec = _cast_spec(card, program)
    # "Target spell **or permanent**" (the five Laces): on a battlefield the
    # answer is a permanent like any other, and a cast that named only a seat
    # left the handler to find one on it — the caster's own, which with
    # nothing of the caster's there was a cast that did nothing.
    spell_or_permanent = isinstance(spec, dict) and spec.get("kind") == "spell_or_permanent"
    if (
        not isinstance(spec, dict)
        or (spec.get("kind") in _NOT_OBJECT_SPECS and not spell_or_permanent)
        or spec_roles(spec)
        or _targets_are_optional(_announced_steps(card, program))
        # A spell with **no target**, whose derived spec is the picker for its
        # printed cost ("…, sacrifice a creature. Draw two cards."). A payment
        # is not a target (CR 601.2b vs 601.2c): naming the creature here put
        # an id on the *target* channel for a spell that has none, which is not
        # where the cost path reads its payer from — and the permanent named is
        # the one about to leave.
        or spec_is_a_cost(spec)
    ):
        return None
    legal = game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        # The announcement *spec* was derived under (CR 702.33g), so the
        # per-candidate probe judges each permanent against that same spec.
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        # ...and the mode (CR 601.2b): the probe reads the chosen mode's own
        # instruction, so a list asked with none is mode 0's list.
        mode_index=_announced_mode(card),
    )
    if spell_or_permanent:
        # The spells on offer are `_guarded_stack_target`'s and the engine's.
        legal = [entry for entry in legal if entry.get("kind") == "permanent"]
    if not legal:
        return None
    # A seat among the answers: "any target", "target player or planeswalker".
    names_a_seat = any(entry.get("kind") != "permanent" for entry in legal)
    legal = [entry for entry in legal if entry.get("kind") == "permanent"]
    if names_a_seat:
        if not legal or card.primary_type not in SPELL_TYPES:
            return None
        return _better_than_the_seat(
            game, caster_index, card, legal, preferred_seat, x_value
        )
    if spell_denies_its_own_target(card):
        # "Return target permanent you control to its owner's hand"
        # (Scapegoat): a denial the printed words aim at the caster's own
        # board, which this policy has no rescue to time it for.
        return ()
    if spec.get("source_of_choice"):
        return _choose_damage_source(game, caster_index, legal)
    # "Destroy target permanent **if it's blue**" (Pyroblast): every permanent
    # is a legal target and only a blue one is destroyed. Named from the ones
    # the effect would reach, and not cast when it would reach none and do
    # nothing else (`_reached_by_the_effect`).
    legal = _reached_by_the_effect(game, caster_index, card, legal)
    if not legal:
        return ()
    # A permanent's entry trigger, whose target this engine names as the
    # permanent is cast: `spell_target_side` has nothing to read for it.
    side = spell_target_side(card) or entry_trigger_target_side(card)
    others = [seat for seat in range(len(game.players)) if seat != caster_index]
    if side == "you":
        order = [caster_index]
    elif side == "opponent":
        first = choose_attack_target(game, caster_index)
        order = [first] + [seat for seat in others if seat != first]
    else:
        order = [preferred_seat] + [
            seat for seat in [caster_index, *others] if seat != preferred_seat
        ]
    candidates = _target_candidates(game, legal, order)
    if not candidates:
        return ()
    return _best_target(game, caster_index, card, candidates, x_value)


def _target_candidates(game: Game, legal: list[dict], order: list[int]) -> list[tuple]:
    """*legal* — one-object candidates off the engine's own list — as
    ``(seat, index, [permanent_id])``, the seats in *order* and each seat's
    permanents as the enumeration lists them."""
    candidates: list[tuple] = []
    for seat in order:
        for entry in legal:
            if entry.get("seat") != seat:
                continue
            permanent_id = game.permanent_id_of(game.permanent_at(seat, entry["index"]))
            if isinstance(permanent_id, int):
                candidates.append((seat, entry["index"], [permanent_id]))
    return candidates


def _distinct_targets(game: Game, candidates: list[tuple]) -> list[tuple]:
    """*candidates* with look-alikes dropped — two untapped Forests are one
    question — and at most `TARGETS_WEIGHED` of them kept: the first in
    order, then the dearest (``ai_rehearsal.permanent_worth``) and the
    frailest, since the target a spell does most at is as often the one it
    can just kill as the one worth most."""
    seen: set = set()
    distinct: list[tuple] = []
    for candidate in candidates:
        permanent = game.permanent_by_id(candidate[2][0])
        if permanent is None:
            continue
        creature = bool(permanent.is_creature)
        look = (
            candidate[0], permanent.card.name, permanent.tapped,
            creature and permanent.effective_power,
            creature and permanent.effective_toughness,
            permanent.damage_marked, permanent.attacking, permanent.blocked,
            tuple(sorted(permanent.metadata)),
        )
        if look in seen:
            continue
        seen.add(look)
        distinct.append((candidate, permanent, creature))
    if len(distinct) <= TARGETS_WEIGHED:
        return [candidate for candidate, _permanent, _creature in distinct]
    kept: list[int] = [0]
    by_worth = sorted(
        range(len(distinct)),
        key=lambda slot: (-permanent_worth(distinct[slot][1]), slot),
    )
    by_frailty = sorted(
        (slot for slot in range(len(distinct)) if distinct[slot][2]),
        key=lambda slot: (distinct[slot][1].effective_toughness, slot),
    )
    for dear, frail in zip(by_worth, by_frailty + by_worth):
        for slot in (dear, frail):
            if slot not in kept and len(kept) < TARGETS_WEIGHED:
                kept.append(slot)
    return [distinct[slot][0] for slot in sorted(kept)]


def _best_target(
    game: Game, caster_index: int, card: CardDefinition, candidates: list[tuple],
    x_value: int | None,
):
    """The candidate whose cast does most (``ai_rehearsal.rehearse``), the
    earlier one on a tie — or ``()`` when every one of them is a cast the
    engine refuses or that changes nothing.

    One candidate is not rehearsed here: there is nothing to choose, and the
    cast built from it is rehearsed where it is scored. Neither is anything
    when no rehearsal can be run; the first candidate is then the answer it
    always was.
    """
    distinct = _distinct_targets(game, candidates)
    if len(distinct) <= 1:
        return distinct[0] if distinct else candidates[0]
    best = None
    best_swing = None
    rehearsed = False
    for seat, index, ids in distinct:
        # "Destroy target artifact with mana value X": the target fixes X.
        implied = (
            game._x_implied_by_target(card, seat, index, None)
            if x_value is not None else None
        )
        announcement = _announcement(
            card, target=seat, caster=caster_index, permanent_index=index,
            permanent_ids=ids, x_value=x_value if implied is None else implied,
        )
        rehearsal = _weighed_through_the_fight(
            game, caster_index, card, announcement,
            _rehearse_announcement(game, caster_index, card, announcement),
        )
        if rehearsal is None:
            continue
        rehearsed = True
        if not rehearsal.accepted or not rehearsal.changed or _leaves_nothing(rehearsal):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = (seat, index, ids), rehearsal.swing
    if best is not None:
        return best
    return () if rehearsed else distinct[0]


def _better_than_the_seat(
    game: Game, caster_index: int, card: CardDefinition, legal: list[dict],
    preferred_seat: int, x_value: int | None,
):
    """For a spell that may name a player **or** a permanent: the permanent
    whose cast is measured to do more than naming the seat alone, or None to
    keep the seat.

    The permanents weighed are on the side the seat choice already says the
    effect is for — an opponent's when the seat is one (damage), the
    caster's own when it is the caster's (a shield).
    """
    hostile = preferred_seat != caster_index
    seats = [
        seat for seat in range(len(game.players))
        if (seat != caster_index) == hostile
    ]
    order = [preferred_seat] + [seat for seat in seats if seat != preferred_seat]
    candidates = _distinct_targets(game, _target_candidates(game, legal, order))
    if not candidates:
        return None
    at_seat = _announcement(
        card, target=preferred_seat, caster=caster_index, x_value=x_value,
    )
    at_the_seat = _weighed_through_the_fight(
        game, caster_index, card, at_seat,
        _rehearse_announcement(game, caster_index, card, at_seat),
    )
    if at_the_seat is None:
        return None
    if (
        at_the_seat.accepted and at_the_seat.fleeting
        and game.current_turn_phase != "combat"
        and not (
            at_the_seat.combat_ahead
            and has_a_creature_to_fight_with(game, caster_index)
        )
    ):
        # Aimed at the player it is over with the turn, and with no combat
        # still to come this reading has no damage in it for it to stop or to
        # add to: what may name "any target" is damage, which a player keeps,
        # or a shield — and a shield with nothing coming is as much nothing
        # on a creature as on its controller. So the permanents are not each
        # rehearsed to learn that, and the seat stands. Before the caster's
        # own fight they are: the 2/2 about to trade is what a shield is for.
        return None
    best = None
    best_swing = (
        at_the_seat.swing
        if at_the_seat.accepted and not _leaves_nothing(at_the_seat) else None
    )
    for seat, index, ids in candidates:
        announcement = _announcement(
            card, target=seat, caster=caster_index, permanent_index=index,
            permanent_ids=ids, x_value=x_value,
        )
        rehearsal = _weighed_through_the_fight(
            game, caster_index, card, announcement,
            _rehearse_announcement(game, caster_index, card, announcement),
        )
        if (
            rehearsal is None or not rehearsal.accepted or not rehearsal.changed
            or _leaves_nothing(rehearsal)
        ):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = (seat, index, ids), rehearsal.swing
    return best


#: `if_then` conditions that are a property of **the permanent the spell
#: targets** — the clause is on the effect, not on the target phrase, so the
#: engine's picker rightly offers every permanent (CR 608.2b reads the printed
#: target phrase, and Pyroblast's says no colour) and a target that fails it
#: is one the spell does nothing to.
#:
#: Named, where "evaluate whatever condition is there" would be shorter,
#: because a condition about something *else* (was this spell kicked, did a
#: creature die this turn) cannot be asked before the cast exists, and
#: answering it early would withhold spells for a reason that is not true. A
#: kind left off costs the old behaviour and nothing more.
_TARGET_GUARDS = frozenset({
    "target_is_color", "target_shares_most_common_color",
    # "Counter target spell **if it was kicked**" (Ertai's Trickery): CR
    # 702.33d's fact about the *targeted* spell, which is on the stack to be
    # asked. Not `was_kicked`, which is about this one.
    "target_was_kicked",
    # "Destroy target nonland permanent **if another permanent with the same
    # name is on the battlefield**" (Winnow) — `_is_a_target_guard` admits the
    # kind only in that spelling; "a card with the same name as that spell"
    # (Bazaar of Wonders) is about a spell some trigger fired on.
    "same_named_object",
    # "Counter target spell if it shares a color with a creature you control."
    # (Jaded Response.) A property of the spell the cast names, read against
    # the caster's own board as it stands — askable before the cast exists.
    "target_shares_color_with_matching",
})


def _is_a_target_guard(condition) -> bool:
    """Whether *condition* is a `_TARGET_GUARDS` clause about the object the
    spell targets."""
    if not isinstance(condition, dict) or condition.get("kind") not in _TARGET_GUARDS:
        return False
    if condition.get("kind") == "same_named_object":
        return condition.get("same_name_as") == "target"
    return True


def _reached_by_the_effect(
    game: Game, caster_index: int, card: CardDefinition, legal: list[dict]
) -> list[dict]:
    """The entries of *legal* — one-object candidates, off the engine's own
    list — that the candidate being built would actually **do something to**.

    All of them, for every spell whose effect is not guarded by a condition on
    its target (`_TARGET_GUARDS`). For one that is: the permanents the guard
    holds for, asked of the engine's own evaluator
    (`control_flow.evaluate_condition`) with that permanent as the target — so
    the policy and the resolution cannot disagree about what "if it's blue"
    means, layers and all. When the guard holds for none of them the answer
    is empty only if the guarded step is the whole spell; where the spell
    does something else as well ("…Draw a card at the beginning of the next
    turn's upkeep", Soul Rend) the candidates stand, because the cast is not
    nothing.

    This surfaced with the mode chooser and was true before it: an AI seat
    holding Hydroblast or Pyroblast in its main phase now weighs "Destroy
    target permanent if it's red", and across ten seeded Ice Age games it
    cast that at ten permanents of the wrong colour — a legal cast and a card
    spent on nothing. Soul Rend and Barrin's Unmaking, which print no mode,
    were aimed the same way all along.
    """
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    guards, whole_spell = _target_guards(card, on_a_spell=False)
    if not guards:
        return legal

    def reached(entry: dict) -> bool:
        permanent = game.permanent_at(entry["seat"], entry["index"])
        if permanent is None:
            return False
        context = OracleExecutionContext(
            caster=game.players[caster_index],
            target=game.players[entry["seat"]],
            card=card,
            target_permanent_index=entry["index"],
            target_permanent_id=game.permanent_id_of(permanent),
        )
        return any(evaluate_condition(game, context, guard) for guard in guards)

    kept = [entry for entry in legal if reached(entry)]
    if kept or whole_spell:
        return kept
    return legal


def _target_guards(card: CardDefinition, *, on_a_spell: bool) -> "tuple[list[dict], bool]":
    """``(conditions, whole_spell)``: the `_TARGET_GUARDS` conditions that
    guard the candidate being built's steps, for a target on the stack
    (*on_a_spell*) or on the battlefield — and whether those guarded steps
    are **everything** the spell does, so that a target every guard fails for
    is a cast that does nothing at all.

    A guard with an ``else`` arm is not one: the spell does something either
    way, and which is better is a valuation this does not make.
    """
    steps = _announced_steps(card, compile_card_oracle(card))
    guards = [
        condition
        for step in steps
        if step.kind == "if_then"
        and not (step.payload or {}).get("else")
        and _is_a_target_guard(condition := (step.payload or {}).get("condition"))
        and (condition.get("target") == "spell") == on_a_spell
    ]
    return guards, bool(guards) and len(guards) == len(steps)


def _guarded_stack_target(game: Game, caster_index: int, card: CardDefinition):
    """The spell on the stack a cast whose effect is guarded by a condition
    on **that spell** should name — its engine (bottom-first) stack index;
    ``()`` when the guard holds for no spell the cast may name and the guarded
    step is the whole spell; None for every other cast, which names nothing
    and is answered by the engine as it always was.

    `_reached_by_the_effect` for the other zone a target can be in. "Counter
    target spell **if it's blue**" (Pyroblast, Hydroblast, Burnout) may be
    announced at any spell, and the web AI's priority response announced it at
    whatever was on top: a Pyroblast spent on a green creature spell, on the
    tree before the mode chooser and after it. The topmost spell the guard
    holds for, off the engine's own list of what the announcement may name.
    """
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    guards, whole_spell = _target_guards(card, on_a_spell=True)
    if not guards:
        return None
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec.get("kind") != "stack":
        return None
    depth = len(game.stack)
    reached: list[int] = []
    for entry in game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    ):
        top_first = entry.get("stack_index")
        if entry.get("kind") != "stack" or not isinstance(top_first, int):
            continue
        index = depth - 1 - top_first
        if not 0 <= index < depth:
            continue
        item = game.stack[index]
        context = OracleExecutionContext(
            caster=game.players[caster_index],
            target=game.players[item.caster_index],
            card=card,
            stack_target=item,
        )
        if any(evaluate_condition(game, context, guard) for guard in guards):
            reached.append(index)
    if reached:
        return max(reached)
    return () if whole_spell else None


def _chosen_stack_target(
    game: Game, caster_index: int, card: CardDefinition, target_seat: int,
):
    """Which spell on the stack a cast whose target **is** a spell names, where
    `_guarded_stack_target` has no guard to choose by: its engine
    (bottom-first) stack index, ``()`` when no candidate is worth casting at,
    or None for a cast that targets no spell.

    **Each candidate is a different cast, so each is rehearsed** and the
    largest swing named, as `_best_target` does for a permanent. With one
    candidate there is nothing to choose and it is named as it is. This left
    the choice to the engine's default for a bare announcement — the first
    entry of the picker's list, with the caster's own seat's first — which
    was harmless while a seat answered only one spell, and became a
    misplay the day it could answer a response: a seat whose spell was met
    by a Confound cast Gainsay ("Counter target blue spell") at **its own**
    blue Aura beneath it, and the Confound fizzled over a spell that was
    gone anyway.
    """
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec.get("kind") != "stack":
        return None
    depth = len(game.stack)
    candidates: list[int] = []
    for entry in game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    ):
        top_first = entry.get("stack_index")
        if entry.get("kind") != "stack" or not isinstance(top_first, int):
            continue
        index = depth - 1 - top_first
        if 0 <= index < depth and index not in candidates:
            candidates.append(index)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    best = None
    best_swing = None
    rehearsed = False
    # Topmost first, so a tie names the spell most recently cast.
    for index in sorted(candidates, reverse=True):
        announcement = {
            **_announcement(card, target=target_seat, caster=caster_index),
            "target_stack_index": index,
        }
        rehearsal = _rehearse_announcement(game, caster_index, card, announcement)
        if rehearsal is None:
            continue
        rehearsed = True
        if not rehearsal.accepted or not rehearsal.changed or _leaves_nothing(rehearsal):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = index, rehearsal.swing
    if best is not None:
        return best
    return () if rehearsed else max(candidates)


def _choose_damage_source(game: Game, caster_index: int, legal: list[dict]):
    """Name "a source of your choice" (CR 609.7a) for a spell that shields
    against one: ``(seat, index, [permanent_id])``, or ``()`` when no source on
    the table is one this seat would want to name.

    A source is not a target, so no effect has a *side* for it
    (``spell_target_side`` is None) and the chooser above took the first legal
    permanent on the caster's own seat — its own first land. Legal, and a card
    spent on nothing: three of seven simulated Samite Ministrations, and every
    Reverse Damage, Eye for an Eye, Shadowbane, Reflect Damage and
    Invulnerability an AI seat ever cast.

    The choice is the one the engine makes for a seat that names nothing
    (``handlers/prevention.default_damage_source``, written for the activated
    half of the same phrase): the opposing source most likely to deal damage
    this turn. Asked of that function rather than restated, and then held to
    the announcement's own enumeration — where the printed phrase narrows what
    may be chosen, the same rule is applied to what it admits. With no
    opposing creature there is nothing worth shielding against and the card is
    kept for a board that has one.
    """
    from .handlers.prevention import default_damage_source

    by_id: dict[int, tuple[int, int]] = {}
    for entry in legal:
        permanent = game.permanent_at(entry["seat"], entry["index"])
        permanent_id = game.permanent_id_of(permanent)
        if isinstance(permanent_id, int):
            by_id[permanent_id] = (entry["seat"], entry["index"])
    chosen = default_damage_source(game, caster_index)
    chosen_id = getattr(chosen, "permanent_id", None)
    if chosen_id in by_id:
        seat, index = by_id[chosen_id]
        return seat, index, [chosen_id]
    admitted = [
        permanent
        for permanent_id, (seat, _index) in by_id.items()
        if seat != caster_index
        and (permanent := game.permanent_by_id(permanent_id)) is not None
        and permanent.is_creature
    ]
    if not admitted:
        return ()
    best = max(
        admitted,
        key=lambda perm: (bool(perm.attacking), perm.effective_power, -perm.permanent_id),
    )
    seat, index = by_id[best.permanent_id]
    return seat, index, [best.permanent_id]

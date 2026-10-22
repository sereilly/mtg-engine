"""The proposals the AI's choosers return, and the one place each becomes an
announcement.

A chooser answers with an action — :class:`CastAction` (a spell, out of
whichever zone a permission opens), :class:`ActivationAction` (an ability of
a permanent), :class:`HandActivationAction` (an ability of a card in a hand,
CR 113.6j) — and an executor turns it into the engine's call. **That turn is
made here, once**: :func:`cast_announcement` is every keyword a cast
announces (CR 601.2b–d), and :func:`zone_being_cast_from` /
:func:`spell_being_cast` are which pile and which spell. There were five
executors, each spelling the forwarding out for itself, until a field added
to the action was five places to remember it; ``tests/ai/test_ai_mode_chooser.py``
and ``tests/ai/test_ai_zone_casts.py`` hold every site to these.

**And the candidate being built**, before it is an action: the answer to its
optional costs (``_OFFERS_ANNOUNCED``), its mode (:func:`_announced_mode`,
which reads ``ai_weighed_cast.considering_mode``) and the zone it leaves
(:func:`_cast_zone`). Each is one fact about one candidate, set around the
single call that builds it, and every chooser that derives a spec or walks
a spell's steps asks through :func:`_cast_spec` / :func:`_announced_steps` —
so none of them can read mode 0, or a cast from the hand, by leaving a
keyword out.

The floor of the policy: it imports none of the modules beside it, and they
all read it.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from .ai_weighed_cast import PermittedCast, cast_weighed, mode_considered
from .ai_valuation import cast_offers
from .faces import castable_faces, spell_named
from .game import Game
from .models import CardDefinition
from .targeting import announced_mode_instructions, derive_cast_spec


@dataclass(frozen=True)
class CastAction:
    card_name: str
    target_player_index: int
    x_value: int | None
    land_tap_indices: tuple[int, ...]
    score: float
    hand_index: int
    # One chosen permanent, or several for a spell that names "up to N target"
    # objects. The same shape ``queue_from_hand`` and the stack already speak, so
    # the executors in web/game_flow.py forward it unchanged.
    target_permanent_index: int | list[int] | None = None
    # The same choices as stable ids, when the slots do not all sit on one
    # battlefield. ``target_permanent_index`` is positional on
    # ``target_player_index``, so a two-board pick (Rookie Mistake's "target
    # creature … another target creature") cannot be expressed by it — the gap
    # round 40 closed on the wire, arriving here through the AI.
    target_permanent_ids: list[int] | None = None
    # Which zone ``hand_index`` indexes into, in the vocabulary the cast path
    # already speaks (`_cast_onto_stack`'s `from_zone`). "command" is a
    # commander cast (CR 903.8); "graveyard" / "exile" / "library" a cast an
    # effect permits (CR 601.3: flashback, Yawgmoth's Will, an Elkin Bottle's
    # card — `ai_weighed_cast.permitted_casts`). Every executor forwards it
    # unchanged and finds the card through `zone_being_cast_from`.
    from_zone: str = "hand"
    # CR 118.9: pay an alternative cost rather than the spell's mana cost.
    # True on the one shape built from an unpayable mana cost (a printed
    # alternative cost this board can pay — `ai_cast_gates._alternative_cost_is_payable`)
    # and on a cast made under a permission that *requires* one (CR 118.9b,
    # CR 702.34a: flashback), where it is also what tells the cast path which
    # permission is meant (`PermittedCast.alternative_cost`).
    alternative_cost: bool = False
    # CR 601.2d's announcement, for a spell that divides damage or counters
    # among its targets: ``(seat, permanent index or None[, share])`` per
    # target, the same list the browser's division prompt sends. The field did
    # not exist, so **every** divided spell the AI cast announced no division at
    # all — Spoils of War, Contagion and Bounty of the Hunt resolved putting no
    # counters anywhere, and Pyrokinesis, Fire Covenant and Dwarven Catapult,
    # which name only creatures, dealt their damage to a player's face. See
    # `ai_divisions.choose_divided_targets`.
    divided_targets: list[tuple] | None = None
    # The colour to ask each land in ``land_tap_indices`` for, position for
    # position (`ai_payment._plan_land_taps`). The tap seam takes one
    # (`tap_land_for_mana(chosen_color=…)`) and every executor sent the default
    # "G", so a dual or a land under Harvest Mage made whatever that default
    # mapped to rather than what the plan had counted on. Empty means no
    # colour was planned, and an executor keeps the seam's default.
    land_tap_colors: tuple[str, ...] = ()
    # CR 601.2b's optional additional costs this cast takes, as the map the
    # cast path reads (``optional_cost_payments``: canonical symbols -> times).
    # None for every candidate that takes none. The field did not exist, so no
    # AI seat ever paid a buyback or a kicker: a kicked-only half of a card was
    # text the simulator could not reach. See `ai_casts._cast_candidate`.
    optional_cost_payments: dict[str, int] | None = None
    # CR 601.2b's other announcement: which mode of a "Choose one —" spell
    # this cast names, in the engine's own spelling (`queue_from_hand`'s
    # ``mode_index``, which becomes `StackItem.chosen_mode_index`). None for a
    # spell with no mode to choose and for one whose mode an opponent chooses
    # (CR 700.2e). The field did not exist, so every modal spell an AI seat
    # cast was announced with no mode, which the engine resolves as the first
    # bullet: 34 of the pool's 88 modes were reachable, and a Charm whose first
    # bullet had nothing to point at was a card the seat held all game. See
    # `ai_casts._cast_candidate`.
    mode_index: int | None = None
    # ...and the same announcement for a "Choose one **or more** —" spell that
    # takes several (Sublime Epiphany), in the shape `queue_from_hand`'s
    # ``mode_choices`` takes them: one dict per chosen mode, each carrying its
    # own seat and slot. None for every cast naming a single mode, which is
    # every other one -- the engine reads one entry exactly as it reads
    # ``mode_index``, so a single mode is never spelled this way.
    mode_choices: list[dict] | None = None
    # The spell on the stack this cast names (CR 601.2c), as the engine's own
    # bottom-first index (`queue_from_hand`'s ``target_stack_index``). None is
    # "name nothing", which is every cast this policy made before and still
    # every cast whose effect is not guarded by a condition on that spell: the
    # engine then answers with the spell on top. Set where which spell matters
    # — "Counter target spell **if it's blue**" (`ai_targets._guarded_stack_target`).
    target_stack_index: int | None = None
    # Whose copy of ``from_zone`` ``hand_index`` indexes into, when that is not
    # the caster's own: "Search target opponent's library for a card and exile
    # it. … you may play that card" (Grinning Totem) leaves the card in the
    # *searched* player's exile pile (this engine keeps one per owner). None
    # is the caster's own, which is every other cast. **Not an announcement**
    # — the cast path finds the pile for itself, by the permission — so
    # `cast_announcement` does not carry it; it is for the executor, which
    # reads the card off the zone (`zone_being_cast_from`).
    zone_seat: int | None = None


@dataclass(frozen=True)
class ActivationAction:
    permanent_name: str
    permanent_index: int
    target_player_index: int
    land_tap_indices: tuple[int, ...]
    score: float
    # The chosen permanent on `target_player_index`'s battlefield, for an
    # ability that targets one (an equip's creature). None for the abilities
    # whose handlers pick for themselves, which is every other one this policy
    # activates today.
    target_permanent_index: int | None = None
    # One chosen object per **role**, for an ability naming several targets of
    # different kinds (Goblin Welder's artifact and artifact card). The field
    # beside this one cannot carry them: they may sit on two battlefields, or —
    # here for the first time — in two different *zones*, which one seat and one
    # index cannot say. None for every other ability.
    target_role_refs: list[dict] | None = None
    # See `CastAction.land_tap_colors`.
    land_tap_colors: tuple[str, ...] = ()
    # Whose battlefield the permanent is on, when that is **not** the
    # activator's: "Any player may activate this ability" (CR 602.1b). None is
    # the activator's own — every action but `ai_abilities.choose_foreign_activation_action`'s.
    # `permanent_index` counts into this seat's battlefield, which is what
    # `activate_permanent_ability(source_controller_index=…)` reads it against.
    source_controller_index: int | None = None
    # Which of the permanent's usable abilities. None is the engine's default
    # (the first one it can pay for); a foreign activation names it, because
    # the ability worth activating on an opponent's Flailing Soldier is its
    # *second* ("-1/-1"), not its first ("+1/+1").
    ability_index: int | None = None
    # Which card in hand pays a "Discard a card" cost (CR 602.2b's choice).
    # None is the engine's default, the first card the cost admits. Named only
    # to discard a card with **madness** whose madness cost the seat can pay
    # beside the ability (`ai_abilities._madness_discard_index`): the discard is then a
    # cast for less rather than a card spent (CR 702.35a).
    cost_hand_index: int | None = None


@dataclass(frozen=True)
class HandActivationAction:
    """An ability activated from a card **in the seat's hand** (CR 113.6j).

    Cycling (CR 702.29a) is why this exists: 34 of Urza's Saga's cards compile
    to "[Cost], Discard this card: Draw a card.", and every one of them is a
    card an AI seat holds and never plays. A seat with no way to reach the hand
    is a seat doing nothing with a third of the set — the same shape a refused
    cast makes, but quieter, because nothing is even proposed.

    A separate action from :class:`ActivationAction` rather than a nullable
    field on it, because the two are executed by different engine entry points
    (``activate_from_hand`` takes no permanent, no target and no summoning
    sickness) and every existing reader of ``ActivationAction`` would have had
    to learn which shape it was holding.
    """

    card_name: str
    hand_index: int
    ability_index: int
    land_tap_indices: tuple[int, ...]
    score: float
    # See `CastAction.land_tap_colors`.
    land_tap_colors: tuple[str, ...] = ()


def cast_announcement(action: CastAction) -> dict:
    """Everything *action* announces (CR 601.2b–d), as the keywords
    ``Game.queue_from_hand`` / ``cast_from_hand`` take it by.

    **The one place a `CastAction` becomes a cast.** There are five executors
    — the simulator's main phase, and in ``web/game_flow`` the AI step's two
    arms, the priority response and the declare-blockers instant — and each
    spelled the forwarding out for itself, so a field added to the action was
    five places to remember it. They had drifted: the two instant executors
    forwarded neither an optional cost nor an alternative one. The mode is the
    field that made five copies one function, because a mode dropped by an
    executor is not refused — it is quietly cast as the first bullet, aimed at
    the target chosen for another.

    The card's name is not here: the spell is `spell_being_cast`'s, which
    reads the zone.
    """
    return {
        "target_player_index": action.target_player_index,
        "target_permanent_index": action.target_permanent_index,
        "target_permanent_ids": action.target_permanent_ids,
        "x_value": action.x_value,
        "from_zone": action.from_zone,
        # CR 118.9. Dropped, the cast falls back to a mana cost the policy has
        # already established this seat cannot pay, and is refused.
        "alternative_cost": action.alternative_cost,
        # CR 601.2d: the division is part of the announcement, and a cast that
        # drops it is refused now that the gate asks for one.
        "divided_targets": action.divided_targets,
        # CR 601.2b's optional costs (a kicker): the plan tapped the lands for
        # them, and a cast that drops the announcement pays the printed cost
        # and leaves the rest in the pool.
        "optional_cost_payments": action.optional_cost_payments,
        # CR 601.2b's mode. See `CastAction.mode_index`.
        "mode_index": action.mode_index,
        "mode_choices": action.mode_choices,
        "target_stack_index": action.target_stack_index,
    }


def _zone_seat(player_index: int, under: "PermittedCast | None") -> "int | None":
    """`CastAction.zone_seat` for a cast made under *under*: the pile's owner
    when that is not the caster (Grinning Totem), None otherwise."""
    if under is None or under.owner_seat == player_index:
        return None
    return under.owner_seat


def hand_spells(player) -> "list[tuple[int, CardDefinition]]":
    """Every spell *player*'s hand could be cast as, with the hand position of
    the card it is on: ``(hand_index, spell)``.

    One entry per single-face card and **one per half of a split card**
    (CR 709.3 — the player chooses which half, and CR 709.3a evaluates only
    that half). So every chooser that walks a hand asking "should I cast
    this?" scores a split card as the two spells it is and proposes the better
    one, with nothing else to learn: the spell is a ``CardDefinition`` like any
    other, and its ``name`` is what the executor casts
    (:func:`spell_being_cast`).
    """
    return [
        (hand_index, spell)
        for hand_index, card in enumerate(player.hand)
        for spell in castable_faces(card)
    ]


def spell_being_cast(zone, action: "CastAction") -> CardDefinition:
    """The spell *action* proposes out of *zone* (a hand, a command zone).

    ``action.hand_index`` finds the card and ``action.card_name`` says which
    spell it is cast as — the card itself for a single-face card, the chosen
    half for a split card. Every executor reads this rather than the zone
    card's own name, which for a split card names no spell and is refused
    (CR 709.3).
    """
    held = zone[action.hand_index]
    return spell_named(held, action.card_name) or held


def zone_being_cast_from(game: Game, seat: int, action: "CastAction") -> list:
    """The pile ``action.hand_index`` indexes: *seat*'s hand for an ordinary
    cast, and otherwise whatever ``action.from_zone`` names — the command zone
    (CR 903.8), or a graveyard, an exile or a library an effect has opened
    (CR 601.3), which is the caster's own unless ``action.zone_seat`` says
    whose.

    **The one place an executor finds the card a `CastAction` proposes**, for
    `cast_announcement`'s reason. Each of the five executors picked the zone
    for itself — "the command zone for a commander cast, the hand for
    everything else" — so a cast proposed from a graveyard would have been
    read off the *hand* at the graveyard's index and cast as whatever card sat
    there.
    """
    player = game.players[seat if action.zone_seat is None else action.zone_seat]
    if action.from_zone == "command":
        return player.command_zone
    if action.from_zone in ("graveyard", "exile", "library"):
        return getattr(player, action.from_zone)
    return player.hand


#: CR 601.2b's optional-cost answer the candidate *being built* would announce,
#: for the target choosers underneath `ai_casts._cast_candidate`. CR 702.33g makes a
#: kicked-only part's targets depend on it, so every chooser has to read the
#: same spec the announcement will be checked against -- and they take a card,
#: not an announcement. A context variable rather than a parameter on five
#: functions: it is one fact about one candidate, set and reset around the
#: single call that builds it, and None (every card that prints no kicker)
#: reads exactly the spec those choosers read before.
_OFFERS_ANNOUNCED: ContextVar["dict[str, int] | None"] = ContextVar(
    "ai_offers_announced", default=None
)


def _announced_mode(card: CardDefinition) -> int | None:
    """CR 601.2b's *mode* answer for the candidate being built: the mode
    *card* is being weighed in, or None for a spell that names none.

    The mode's twin of `_OFFERS_ANNOUNCED`, and it lives one module down
    (`ai_weighed_cast.considering_mode`) because the valuation readers there need
    it too. **Every engine question a cast chooser asks about a spell takes
    this beside the offers** — the spec, the picker's list, the
    no-legal-target gate, the steps the announcement will run — and
    `tests/ai/test_ai_mode_chooser.py` fails a call in this module that asks
    one of them without it, so a chooser added later cannot read mode 0 by
    leaving a keyword out.
    """
    return mode_considered(card)


def _announced_steps(card: CardDefinition, program) -> tuple:
    """The steps the candidate being built will resolve: the weighed mode's
    for a modal spell (`_announced_mode`), *program*'s own otherwise.

    For the choosers that walk instructions rather than ask for a spec.
    ``program.instructions`` is mode 0's for a modal card, which is what each
    of them read.
    """
    return announced_mode_instructions(program, _announced_mode(card))


def _cast_zone(card: CardDefinition) -> str:
    """The zone the candidate being built would be cast from: "hand", or the
    zone of the permission *card* is being weighed under
    (`ai_weighed_cast.casting_under`).

    The zone's twin of `_announced_mode`, and held to the same rule by
    `tests/ai/test_ai_zone_casts.py`: **every engine question a cast chooser
    asks that takes a ``from_zone`` is passed this one.** A spell cast out of a
    graveyard is not a card in that graveyard by the time its targets are
    chosen (CR 601.2a), so a Morgue Theft weighed from the graveyard with the
    hand's spec would count itself as the creature card it may return; a
    prohibition may bind one zone; an additional cost may be printed for one.
    """
    weighed = cast_weighed(card)
    return "hand" if weighed is None else weighed.zone


def _cast_spec(card: CardDefinition, program):
    """`derive_cast_spec` for the candidate being built (see
    `_OFFERS_ANNOUNCED`, `_announced_mode` and `_cast_zone`)."""
    return derive_cast_spec(
        card, program, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
    )


def _announces_any_offer(card: CardDefinition, offers: "dict[str, int] | None") -> bool:
    """Whether *offers* takes anything *card* actually offers, mana or not."""
    if not offers:
        return False
    keys = {offer.key for offer in cast_offers(card)}
    return any(int(times or 0) > 0 and key in keys for key, times in offers.items())

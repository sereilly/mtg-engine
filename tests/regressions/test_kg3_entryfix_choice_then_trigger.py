"""A permanent that asks "as it enters" and triggers "when it enters", on every
road onto the battlefield, at a person's table and at a table nobody asks.

CR 614.12a: "If a replacement effect that modifies how a permanent enters the
battlefield requires a choice, that choice is made before the permanent enters
the battlefield." CR 603.6a: "Enters-the-battlefield abilities trigger when a
permanent enters the battlefield." CR 603.3: once triggered, the ability is put
on the stack "the next time a player would receive priority". So for Brass
Herald ("As this creature enters, choose a creature type. / When this creature
enters, reveal the top four cards â€¦") and Traveler's Cloak ("As this Aura
enters, choose a land type. / When this Aura enters, draw a card.") the order is
fixed: the choice, then the entry, then the trigger â€” a stack object of its own
whose source is the permanent, resolving with the choice already made.

``kg3/entry`` made a person's choice wait (``engine/entry_awaiting.py``): the
permanent is on no battlefield until the answer, and its entry trigger fires at
the answer, from the answer funnel (``_finish_answered_entries``). The
whole-pool census (``tests/engine/test_entry_trigger_stack_census.py``) drives
three roads; this drives the **class** â€” every shipped permanent printing both
lines, derived from the pool, never named â€” down every road a card of its type
takes: cast; put from a hand by an ability; a token copy; a copy-as-enters; a
reanimation; one event putting several onto the battlefield; exiled and returned
at the next end step; exiled and returned at once (Flicker). An Aura's roads are
its own: cast onto a creature, put from a hand attached, put from a graveyard
attached, one event (Replenish), and Flicker — after which it enchants a host
its owner chose as it returned (CR 303.4f).

Each row holds, at both tables:

* the trigger's instruction ran **once**, from its own stack object (the object
  resolving had the entered permanent as its source), and **never inside the
  entry** (``_apply_self_enters_battlefield_triggers`` on the call stack);
* the permanent ends on the battlefield with its choice recorded.

And at a person's table, while the choice is owed: the permanent is on no
battlefield, its trigger neither on the stack nor run, a creature's arrival
unseen by Soul Warden â€” and the record afterwards is the person's answer (one
that is not the prompt's default, so a default standing in for it shows).

Validated backwards (``scratch/kg3/entryfix``): with the answer's completion of
the entry made to run the trigger inline, all 13 person rows fail; with every
entry announcing its trigger inline, all 26; with entries never waiting (the
tree before ``kg3/entry``), all 13 person rows fail on the wait. And two roads
found defects of their own, each fixed beside its own test. The copy road: a
Clone cast naming the creature to copy by ``target_permanent_ids`` alone, with
no slot, recorded no copy choice (``_resolve_card``) and copied the first
creature on the board — the Soul Warden, not the Brass Herald it named
(``test_kg3_entryfix_copy_choice_by_id.py``). The Flicker road: "then return it"
read "it" as Flicker itself, so nothing came back, and an Aura put back that way
chose no host (``test_kg3_entryfix_flicker_returns_it.py``). On those trees the
rows fail at both tables.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.regressions.test_kg3_entry_choice_census import _choosers

_C = {card.name: card for card in load_catalog()}
_ENTRY_CONDITIONS = frozenset({"enters_battlefield", "enters_or_dies"})
WARDEN = "Soul Warden"

#: Two shipped permanents print both lines (November 2026). A floor.
_MIN_CLASS = 2


def _entry_trigger_kinds(card) -> frozenset:
    program = compile_card_oracle(card)
    if not program.supported:
        return frozenset()
    return frozenset(
        trigger.instruction.kind for trigger in program.triggered_abilities
        if trigger.condition.kind in _ENTRY_CONDITIONS
        and trigger.supported and trigger.instruction is not None
    )


def _the_class() -> list:
    """Every shipped permanent with an "as it enters" choice and an entry
    trigger â€” off the pool, so a card ingested later joins by itself."""
    choosers = set(_choosers())
    return sorted(
        {
            whole_card(unit).name: whole_card(unit)
            for unit in compilation_units(_C.values())
            if whole_card(unit).name in choosers and _entry_trigger_kinds(unit)
        }.values(),
        key=lambda card: card.name,
    )


# -- the table ----------------------------------------------------------------


def _table(person: bool) -> Game:
    library = [_C["Obsianus Golem"], _C["Forest"], _C["Grizzly Bears"], _C["Island"]]
    game = Game(players=[
        PlayerState(name="P0", library=library + [_C["Plains"]] * 12),
        PlayerState(name="P1", library=[_C["Plains"]] * 16),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0} if person else set()
    game._sync_control()
    _place(game, 1, WARDEN)
    return game


def _place(game: Game, seat: int, card) -> Permanent:
    permanent = Permanent(card=_C[card] if isinstance(card, str) else card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _settle_defaults(game)
    # Placed before the road, so a creature it activates is not summoning sick.
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _settle_defaults(game: Game) -> None:
    for _ in range(100):
        owed = game.waiting_prompt()
        if owed is not None:
            game.take_choice_default(owed)
        elif game.stack:
            game.resolve_top_of_stack(pause_for_choices=game.holds_for_answers())
        elif game.pending_choices:
            game.auto_resolve_pending_choices()
        else:
            return


# -- the roads ----------------------------------------------------------------
#
# Each sets the table up and returns ``(act, end_step)``: the action that puts
# the card onto seat 0's battlefield, and whether the road finishes at the next
# end step.


def _cast(game, card):
    if "Aura" in card.type_line:
        bears = _place(game, 0, "Grizzly Bears")
        game.players[0].hand = [card]
        return lambda: game.queue_from_hand(
            0, card.name, target_permanent_ids=[bears.permanent_id]
        ), False
    game.players[0].hand = [card]
    return lambda: game.queue_from_hand(0, card.name), False


def _put_from_hand_by_an_ability(game, card):
    """Quicksilver Amulet: "You may put a creature card from your hand onto
    the battlefield." """
    _place(game, 0, "Quicksilver Amulet")
    game.players[0].hand = [card]
    return lambda: game.activate_permanent_ability(0, "Quicksilver Amulet"), False


def _token_copy(game, card):
    """Dance of Many: "create a token that's a copy of target nontoken
    creature" â€” the token is the card as it enters (CR 707.5)."""
    original = _place(game, 1, card)
    game.players[0].hand = [_C["Dance of Many"]]
    return lambda: game.queue_from_hand(
        0, "Dance of Many", target_permanent_ids=[original.permanent_id]
    ), False


def _copy_as_it_enters(game, card):
    """Clone: "You may have this creature enter as a copy of any creature on
    the battlefield" â€” it enters as the card, and asks what the card asks."""
    original = _place(game, 1, card)
    game.players[0].hand = [_C["Clone"]]
    return lambda: game.queue_from_hand(
        0, "Clone", target_permanent_ids=[original.permanent_id]
    ), False


def _reanimation(game, card):
    """Zombify: "Return target creature card from your graveyard to the
    battlefield." """
    game.players[0].graveyard = [card]
    game.players[0].hand = [_C["Zombify"]]
    return lambda: game.queue_from_hand(
        0, "Zombify", target_player_index=0, target_permanent_index=0
    ), False


def _one_event(game, card):
    """Living Death puts the card and a Grizzly Bears onto the battlefield
    together (CR 603.6a); Replenish, for an Aura, beside a creature to
    enchant."""
    if "Aura" in card.type_line:
        _place(game, 0, "Grizzly Bears")
        game.players[0].graveyard = [card]
        game.players[0].hand = [_C["Replenish"]]
        return lambda: game.queue_from_hand(0, "Replenish"), False
    game.players[0].graveyard = [card, _C["Grizzly Bears"]]
    game.players[0].hand = [_C["Living Death"]]
    return lambda: game.queue_from_hand(0, "Living Death"), False


def _exiled_and_returned(game, card):
    """Liberate: "Exile target creature you control. Return that card to the
    battlefield under its owner's control at the beginning of the next end
    step." """
    permanent = _place(game, 0, card)
    game.players[0].hand = [_C["Liberate"]]
    return lambda: game.queue_from_hand(
        0, "Liberate", target_permanent_ids=[permanent.permanent_id]
    ), True


def _flickered(game, card):
    """Flicker: "Exile target nontoken permanent, then return it to the
    battlefield under its owner's control." — an Aura comes back attached to a
    host its owner chooses as it enters (CR 303.4f)."""
    if "Aura" in card.type_line:
        bears = _place(game, 0, "Grizzly Bears")
        game.players[0].hand = [card]
        assert game.queue_from_hand(
            0, card.name, target_permanent_ids=[bears.permanent_id]
        ).supported
        _settle_defaults(game)
        permanent = next(p for p in game.controlled_by(0) if p.card is card)
    else:
        permanent = _place(game, 0, card)
    game.players[0].hand = [_C["Flicker"]]
    return lambda: game.queue_from_hand(
        0, "Flicker", target_permanent_ids=[permanent.permanent_id]
    ), False


def _put_from_hand_attached(game, card):
    """Academy Researchers: "you may put an Aura card from your hand onto the
    battlefield attached to this creature." """
    game.players[0].hand = [_C["Academy Researchers"], card]
    return lambda: game.queue_from_hand(0, "Academy Researchers"), False


def _put_from_a_graveyard_attached(game, card):
    """Iridescent Drake: "put target Aura card from a graveyard onto the
    battlefield under your control attached to this creature." """
    game.players[0].graveyard = [card]
    game.players[0].hand = [_C["Iridescent Drake"]]
    return lambda: game.queue_from_hand(0, "Iridescent Drake"), False


CREATURE_ROADS = {
    "cast": _cast,
    "put_from_hand_by_an_ability": _put_from_hand_by_an_ability,
    "token_copy": _token_copy,
    "copy_as_it_enters": _copy_as_it_enters,
    "reanimation": _reanimation,
    "one_event": _one_event,
    "exiled_and_returned": _exiled_and_returned,
    "flickered": _flickered,
}
AURA_ROADS = {
    "cast": _cast,
    "put_from_hand_attached": _put_from_hand_attached,
    "put_from_a_graveyard_attached": _put_from_a_graveyard_attached,
    "one_event": _one_event,
    "flickered": _flickered,
}


def _roads_for(card) -> dict:
    if "Creature" in card.type_line:
        return CREATURE_ROADS
    if "Aura" in card.type_line:
        return AURA_ROADS
    return {}


# -- the drive ----------------------------------------------------------------


def _answer_for(choice) -> tuple[dict, str | None, str | None]:
    """A person's answer that is not the prompt's default: the response, the
    record it writes and the value. Other shapes keep the default."""
    data = choice.data
    if data.get("needs_land_type"):
        word = next(w for w in ("island", "swamp") if w != str(data.get("default_land_type")).lower())
        return {"land_type": word}, "chosen_land_type", word
    if data.get("needs_creature_type"):
        word = next(w for w in ("golem", "elf") if w != str(data.get("default_creature_type")).lower())
        return {"creature_type": word.capitalize()}, "chosen_creature_type", word
    return {}, None, None


class _Watch:
    """The dispatch, recorded: every instruction of *kinds* run, with whether
    an entry was announcing it, the permanent it ran for and the stack object
    resolving at the time."""

    def __init__(self, game, kinds):
        self.runs: list[tuple[bool, object, object]] = []
        depth = [0]
        announce = game._apply_self_enters_battlefield_triggers
        execute = game._execute_oracle_instruction

        def watched_announce(*args, **kwargs):
            depth[0] += 1
            try:
                return announce(*args, **kwargs)
            finally:
                depth[0] -= 1

        def watched_execute(instruction, context, *args, **kwargs):
            if instruction.kind in kinds:
                resolving = game.resolving_items[-1] if game.resolving_items else None
                self.runs.append((bool(depth[0]), context.source_permanent, resolving))
            return execute(instruction, context, *args, **kwargs)

        game._apply_self_enters_battlefield_triggers = watched_announce
        game._execute_oracle_instruction = watched_execute


def _subject_waiting(game, card):
    """The record of *card*'s entry under seat 0 waiting for its choice."""
    return next(
        (record for record in game.entries_in_progress
         if record.finish is not None and record.controller_index == 0
         and record.permanent.effective_card.name == card.name),
        None,
    )


def _drive(card, road, person: bool) -> list[str]:
    """Put *card* onto seat 0's battlefield by *road*; what went wrong."""
    game = _table(person)
    act, end_step = _roads_for(card)[road](game, card)
    kinds = _entry_trigger_kinds(card)
    # The objects themselves, not their ids: a permanent that dies frees its id.
    before = list(game.all_permanents())
    warden_life = game.players[1].life
    watch = _Watch(game, kinds)
    where = f"{card.name} [{road}, {'a person' if person else 'nobody asked'}]"
    wrong: list[str] = []
    result = act()
    if not result.supported:
        return [f"{where}: refused: {result.details}"]

    waited = 0
    answered: tuple[str | None, str | None] = (None, None)
    ended = False
    for _ in range(200):
        record = _subject_waiting(game, card)
        if record is not None:
            waited += 1
            subject = record.permanent
            if game.is_on_battlefield(subject):
                wrong.append(f"{where}: on the battlefield while its choice is owed")
            if any(item.source_permanent is subject and item.ability_instruction is not None
                   and item.ability_instruction.kind in kinds for item in game.stack):
                wrong.append(f"{where}: its entry trigger is on the stack before the choice")
            if any(source is subject for _, source, _ in watch.runs):
                wrong.append(f"{where}: its entry trigger ran before the choice")
            if "Creature" in subject.effective_card.type_line and game.players[1].life != warden_life:
                wrong.append(f"{where}: Soul Warden saw it enter before the choice")
            owed = next(
                choice for choice in game.pending_choices
                if choice.data.get("_entering_permanent") is subject
            )
            response, key, value = _answer_for(owed)
            if not game.resolve_pending_choice(owed.kind, owed.player_index, **response):
                return wrong + [f"{where}: the person's answer {response} was refused"]
            answered = (key, value)
            continue
        owed = game.waiting_prompt()
        if owed is not None:
            game.take_choice_default(owed)
        elif game.stack:
            game.resolve_top_of_stack(pause_for_choices=game.holds_for_answers())
        elif game.pending_choices:
            game.auto_resolve_pending_choices()
        elif end_step and not ended:
            ended = True
            game.resolve_end_step(0)
        else:
            break

    subjects = [
        permanent for permanent in game.controlled_by(0)
        if not any(permanent is present for present in before)
        and permanent.effective_card.name == card.name
    ]
    if len(subjects) != 1:
        newcomers = [
            f"{permanent.card.name} as {permanent.effective_card.name}"
            for permanent in game.controlled_by(0)
            if not any(permanent is present for present in before)
        ]
        return wrong + [
            f"{where}: {len(subjects)} newcomer(s) of it on the battlefield "
            f"(seat 0's newcomers: {newcomers})"
        ]
    subject = subjects[0]
    if person and not waited:
        wrong.append(f"{where}: the entry did not wait for the person's choice")
    if not person and waited:
        wrong.append(f"{where}: an entry waited at a table nobody is asked at")
    key, value = answered
    if key is not None and subject.metadata.get(key) != value:
        wrong.append(f"{where}: recorded {subject.metadata.get(key)!r}, the person chose {value!r}")
    if not any(name.startswith("chosen") for name in subject.metadata):
        wrong.append(f"{where}: no choice recorded")
    if "Aura" in card.type_line:
        host = subject.metadata.get("attached_to")
        if host is None or not game.is_on_battlefield(host):
            wrong.append(f"{where}: the Aura enchants nothing (CR 303.4f)")
    runs = [(inside, resolving) for inside, source, resolving in watch.runs if source is subject]
    if len(runs) != len(kinds):
        wrong.append(f"{where}: its entry trigger ran {len(runs)} time(s)")
    for inside, resolving in runs:
        if inside:
            wrong.append(f"{where}: its entry trigger was carried out inside the entry")
        if resolving is None or resolving.source_permanent is not subject:
            wrong.append(f"{where}: its entry trigger ran from no stack object of its own")
    if game.entries_in_progress:
        wrong.append(f"{where}: an entry is still on its way")
    return wrong


def _census(person: bool) -> tuple[int, list[str]]:
    the_class = _the_class()
    assert len(the_class) >= _MIN_CLASS, [card.name for card in the_class]
    rows = 0
    wrong: list[str] = []
    for card in the_class:
        roads = _roads_for(card)
        if not roads:
            wrong.append(f"{card.name}: no road in this census reaches a {card.type_line}")
        for road in roads:
            rows += 1
            wrong.extend(_drive(card, road, person))
    return rows, wrong


def test_a_persons_choice_comes_first_and_the_trigger_after_it_on_every_road():
    rows, wrong = _census(person=True)
    assert not wrong, "\n".join(wrong)
    # Brass Herald's eight roads and Traveler's Cloak's five.
    assert rows >= 13, rows


def test_a_seat_nobody_asks_enters_at_once_and_triggers_on_every_road():
    rows, wrong = _census(person=False)
    assert not wrong, "\n".join(wrong)
    assert rows >= 13, rows

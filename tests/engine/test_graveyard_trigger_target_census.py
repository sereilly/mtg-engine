"""Every triggered ability in the pool whose target is a card in a graveyard.

CR 115.1d: a triggered ability's targets "are chosen as the ability is put on
the stack; see rule 603.3d". For a permanent on the battlefield this engine has
done that since Floral Spuzzem. For a **card in a graveyard** it did not: the
kind was left out of the chooser on the ground that such a target "reaches the
resolution through its own path", and that path was each handler taking the
first card its noun phrase admitted. So

* nobody was ever asked — Gravedigger entering beside three creature cards
  took the first of them for a player who could see all three;
* the cast's announcement was held to no list as the trigger went on the
  stack, where a battlefield target is (``cast_announcement_fault``);
* and a named card exiled **in response to the trigger** was read as "no card
  was announced": the handler took the next one. CR 608.2b says the ability
  doesn't resolve.

Driven here for every such trigger: put on the stack under a seat that is
asked, under a seat that is not, answered with a card that is not the default,
and with the named card exiled in response. The table's two graveyards hold
different cards, so which pile a card came out of is readable off its name.

Validated backwards: with ``resolution._names_a_graveyard_target`` answering
False (no graveyard card is chosen on the stack, the tree as it was) eight of
these ten tests fail. The defaulted-seat test names all eighteen triggers as
choosing nothing; the cast-road response test names **all fourteen** entry
triggers as returning another card; and the two put-road response tests cannot
reach a chosen card at all, which is their floor firing (0 examined) rather
than a finding.

Two earlier measurements of the response defect said five and then six of
thirteen. Both were taken on a table whose graveyards held one instant, one
enchantment, one land: with nothing else of its kind to take, Scrivener read as
correct. ``_YARDS`` holds two of each for that reason.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import names_a_target
from engine.targeting import GRAVEYARD_TARGET_KIND, derive_instruction_spec
from tests.helpers import resolve_stack

#: Floors, because a sweep that reaches nothing passes. On the day: 18 targeted
#: (14 of them entry triggers) and 3 that derive the same spec and target
#: nothing (Harvest Wurm, Animate Dead, Dance of the Dead).
_MIN_TARGETED = 16
_MIN_ENTRY = 12
_MIN_ANSWERED_OFF_DEFAULT = 12

_LIBRARY = ("Forest", "Craw Wurm", "Plains", "Mox Pearl", "Swamp", "Mountain", "Island", "Terror") * 3
#: Two of everything a trigger in the pool asks for, in the controller's own
#: pile: a census whose table holds one instant cannot show Scrivener taking
#: the *other* instant, and the first two measurements of this defect counted
#: six cards for exactly that reason (it is fourteen).
_YARDS = (
    ("Hill Giant", "Lightning Bolt", "Ornithopter", "Holy Strength", "Swamp",
     "Wrath of God", "Circle of Protection: Red", "Serra Angel", "Shock", "Fireball",
     "Mountain", "Mox Pearl", "Prodigal Sorcerer"),
    ("Grizzly Bears", "Counterspell", "Sol Ring", "Pacifism", "Forest",
     "Mind Rot", "Crusade", "Air Elemental"),
)


@pytest.fixture(scope="module")
def _pool(catalog):
    pool: dict = {}
    for unit in compilation_units(catalog):
        pool.setdefault(unit.name, unit)
    return pool


@pytest.fixture(scope="module")
def _mercenaries(catalog):
    """Two Mercenary cards for the one trigger that asks for the subtype
    (Strongarm Thug), found rather than named so the fixture cannot rot."""
    found = [
        card for card in catalog
        if "Mercenary" in (card.type_line or "") and "Creature" in card.type_line
        and card.name != "Strongarm Thug"
    ]
    assert len(found) >= 2
    return sorted(found, key=lambda card: card.name)[:2]


def _rows(pool) -> list:
    """``(card, trigger, spec, targeted)`` for every supported triggered
    ability whose derived target is a card in a graveyard."""
    found = []
    for card in sorted(pool.values(), key=lambda c: c.name):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trigger in program.triggered_abilities:
            step = trigger.instruction
            if step is None or not trigger.supported:
                continue
            spec = derive_instruction_spec([step])
            if spec and spec.get("kind") == GRAVEYARD_TARGET_KIND:
                found.append((card, trigger, spec, names_a_target(trigger.source_line)))
    return found


def _table(pool, mercenaries, *, interactive=(), hand=()) -> Game:
    game = Game(players=[
        PlayerState(
            "A", library=[pool[n] for n in _LIBRARY], hand=list(hand),
            graveyard=[pool[n] for n in _YARDS[0]] + list(mercenaries),
        ),
        PlayerState(
            "B", library=[pool[n] for n in _LIBRARY],
            graveyard=[pool[n] for n in _YARDS[1]],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _drain(game) -> None:
    for _ in range(6):
        resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _yards(game):
    return tuple(tuple(card.name for card in player.graveyard) for player in game.players)


def _left(before, after) -> list[tuple[str, int]]:
    """``(name, pile)`` for every card that left a graveyard."""
    gone = []
    for pile in (0, 1):
        remaining = list(after[pile])
        for name in before[pile]:
            if name in remaining:
                remaining.remove(name)
            else:
                gone.append((name, pile))
    return gone


def _fire(game, card, trigger) -> Permanent:
    """Put *trigger* on the stack with nothing announced for it: an entry
    trigger by its permanent entering without a cast, any other by the seam
    every fire site ends at."""
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, source, None)
    if trigger.condition.kind == "enters_battlefield":
        return source
    _drain(game)
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=source, instruction=trigger.instruction,
        effect_kind=trigger.effect_kind, ability_text=trigger.source_line,
    )
    return source


def _object(game, trigger):
    return next(
        (item for item in game.stack if item.ability_instruction is trigger.instruction), None
    )


def _prompt(game, trigger):
    return next(
        (
            choice for choice in game.pending_choices_of("trigger_target")
            if choice.data["_trigger_item"].ability_instruction is trigger.instruction
        ),
        None,
    )


def _offers(prompt) -> list[tuple[int, int, str]]:
    return [
        (entry["seat"], entry["graveyard_index"], entry["name"])
        for entry in prompt.data["targets"] if entry["kind"] == "graveyard"
    ]


def test_the_pool_still_prints_what_this_census_is_about(_pool):
    rows = _rows(_pool)
    targeted = [row for row in rows if row[3]]
    entry = [row for row in targeted if row[1].condition.kind == "enters_battlefield"]

    assert len(targeted) >= _MIN_TARGETED, [row[0].name for row in targeted]
    assert len(entry) >= _MIN_ENTRY, [row[0].name for row in entry]
    assert {"Gravedigger", "Karmic Guide", "Necromancy", "Junk Diver"} <= {
        row[0].name for row in targeted
    }
    # …and the three that share the spec and choose nothing on the stack.
    assert {"Harvest Wurm", "Animate Dead", "Dance of the Dead"} <= {
        row[0].name for row in rows if not row[3]
    }


def test_a_seat_that_can_be_asked_is_asked_and_its_answer_is_the_card_that_moves(
    _pool, _mercenaries,
):
    """The prompt is armed as the trigger goes on the stack, lists what the
    engine's own enumeration lists — for an entry trigger, exactly what the
    cast's picker lists — and the answer is honoured: the **last** card
    offered moves, which is never the one a scan would have taken, and no
    other card leaves a graveyard."""
    asked = off_default = 0
    findings: list[str] = []
    for card, trigger, spec, targeted in _rows(_pool):
        if not targeted:
            continue
        label = f"{card.name} [{trigger.condition.kind}]"
        game = _table(_pool, _mercenaries, interactive={0})
        before = _yards(game)
        _fire(game, card, trigger)
        prompt = _prompt(game, trigger)
        if prompt is None:
            findings.append(f"{label}: nobody was asked")
            continue
        asked += 1
        offers = _offers(prompt)
        item = prompt.data["_trigger_item"]
        if trigger.condition.kind == "enters_battlefield":
            probe = _table(_pool, _mercenaries, hand=[card])
            picker = probe.cast_target_spec(0, card, optional_cost_payments={})
            listed = sorted(
                (entry["seat"], entry["index"]) for entry in picker.get("valid_targets") or ()
            )
            if listed != sorted((seat, slot) for seat, slot, _name in offers):
                findings.append(f"{label}: the prompt and the cast picker list different cards")
        seat, slot, name = offers[-1]
        if not game.confirm_trigger_target(0, seat=seat, graveyard_index=slot):
            findings.append(f"{label}: the answer was refused")
            continue
        if game.pending_choices_of("trigger_target"):
            findings.append(f"{label}: still owed after the answer")
        if not item.targets_chosen or item.target_graveyard_card is None:
            findings.append(f"{label}: the answer is not on the stack object")
        if f"targets {name} in {game.players[seat].name}'s graveyard" not in game.log[-1]:
            findings.append(f"{label}: the choice was not logged ({game.log[-1]!r})")
        _drain(game)
        gone = _left(before, _yards(game))
        if gone != [(name, seat)]:
            findings.append(f"{label}: named {name} in pile {seat}; {gone} left a graveyard")
        elif len(offers) > 1:
            off_default += 1

    assert asked >= _MIN_TARGETED, f"only {asked} triggers asked"
    assert off_default >= _MIN_ANSWERED_OFF_DEFAULT, f"only {off_default} answered off the default"
    assert not findings, "\n".join(findings)


def test_a_seat_nobody_asks_takes_the_card_the_resolution_used_to_find(_pool, _mercenaries):
    """The default is the pick each handler made before the choice moved to
    the push — the first card the phrase admits in the standing opposing
    seat's pile where the phrase reaches any graveyard, in the only pile on
    offer otherwise — so choosing here changes what a *player* is asked and
    nothing a seat nobody asks does. The choice is now made, stamped and
    logged as the ability goes on the stack."""
    examined = 0
    findings: list[str] = []
    for card, trigger, spec, targeted in _rows(_pool):
        if not targeted:
            continue
        label = f"{card.name} [{trigger.condition.kind}]"
        game = _table(_pool, _mercenaries)
        before = _yards(game)
        _fire(game, card, trigger)
        item = _object(game, trigger)
        if item is None:
            findings.append(f"{label}: not on the stack")
            continue
        examined += 1
        stamp = item.target_graveyard_card
        if stamp is None or not item.targets_chosen:
            findings.append(f"{label}: nothing was chosen as it went on the stack")
            continue
        own_only = bool(spec.get("own_graveyard_only"))
        if stamp.seat != (0 if own_only else 1):
            findings.append(f"{label}: chose from pile {stamp.seat}")
        _drain(game)
        gone = _left(before, _yards(game))
        if gone != [(stamp.card.name, stamp.seat)]:
            findings.append(f"{label}: chose {stamp.card.name}; {gone} left a graveyard")

    assert examined >= _MIN_TARGETED
    assert not findings, "\n".join(findings)


@pytest.mark.parametrize("interactive", [(), (0,)], ids=["defaulted", "answered"])
def test_the_named_card_exiled_in_response_is_not_replaced_by_another(
    _pool, _mercenaries, interactive,
):
    """CR 608.2b: "A target that's no longer in the zone it was in when it was
    targeted is illegal. … If all its targets … are now illegal, the spell or
    ability doesn't resolve." The trigger is on the stack with its card
    chosen; the card is exiled in response; nothing else leaves a graveyard,
    nothing is still owed, and the log says why."""
    examined = 0
    findings: list[str] = []
    for card, trigger, spec, targeted in _rows(_pool):
        if not targeted:
            continue
        label = f"{card.name} [{trigger.condition.kind}]"
        game = _table(_pool, _mercenaries, interactive=set(interactive))
        _fire(game, card, trigger)
        prompt = _prompt(game, trigger)
        if prompt is not None:
            seat, slot, _name = _offers(prompt)[0]
            assert game.confirm_trigger_target(0, seat=seat, graveyard_index=slot), label
        item = _object(game, trigger)
        if item is None or item.target_graveyard_card is None:
            findings.append(f"{label}: no chosen card on the stack")
            continue
        examined += 1
        stamp = item.target_graveyard_card
        pile = game.players[stamp.seat]
        exiled = pile.graveyard.pop(game.graveyard_index_of(stamp))
        pile.exile.append(exiled)
        before = _yards(game)
        _drain(game)
        gone = _left(before, _yards(game))
        if gone:
            findings.append(f"{label}: {stamp.card.name} was exiled and {gone} moved instead")
        if game.stack or game.pending_choices:
            findings.append(f"{label}: something is still owed")
        if not any("no longer in the graveyard (608.2b)" in line for line in game.log[-4:]):
            findings.append(f"{label}: no 608.2b line in {game.log[-3:]}")

    assert examined >= _MIN_TARGETED
    assert not findings, "\n".join(findings)


def test_a_card_named_at_the_cast_and_exiled_in_response_to_the_trigger_is_not_replaced(
    _pool, _mercenaries,
):
    """The same rule on the cast road, which is the road the defect was
    measured on: the permanent is cast naming a card, resolves, and its
    trigger is on the stack carrying that card when the card is exiled. Every
    one of the fourteen entry triggers returned the card beside it — the
    trigger carried a stamp, the stamp re-located to nothing, and each handler
    read "no slot" as leave to take the next card its phrase admits."""
    examined = 0
    findings: list[str] = []
    for card, trigger, spec, targeted in _rows(_pool):
        if not targeted or trigger.condition.kind != "enters_battlefield":
            continue
        probe = _table(_pool, _mercenaries, hand=[card])
        listed = [
            (entry["seat"], entry["index"])
            for entry in probe.cast_target_spec(0, card, optional_cost_payments={}).get("valid_targets") or ()
        ]
        if not listed:
            continue
        seat, slot = listed[0]
        game = _table(_pool, _mercenaries, hand=[card])
        named = game.players[seat].graveyard[slot]
        assert game.queue_from_hand(
            0, card.name, target_player_index=seat, target_permanent_index=slot,
        ).supported, card.name
        game.resolve_top_of_stack()
        item = _object(game, trigger)
        if item is None or item.target_graveyard_card is None:
            findings.append(f"{card.name}: the trigger is not on the stack with its card")
            continue
        examined += 1
        pile = game.players[seat]
        pile.exile.append(pile.graveyard.pop(pile.graveyard.index(named)))
        before = _yards(game)
        _drain(game)
        gone = _left(before, _yards(game))
        if gone:
            findings.append(f"{card.name}: {named.name} was exiled and {gone} moved instead")

    assert examined >= _MIN_ENTRY, f"only {examined} examined"
    assert not findings, "\n".join(findings)


def test_a_card_the_cast_named_stands_and_one_that_left_is_chosen_again(_pool, _mercenaries):
    """The cast road, where this engine names an entry trigger's target as the
    permanent is cast. A card the trigger could choose rides the object and
    nobody is asked twice. One that left the pile while the permanent spell
    waited is not there to be named when the trigger goes on the stack — which
    is when CR 603.3d chooses — so the trigger chooses then, from what is
    there: its controller is asked, and is never offered the card that left.
    """
    stood = rechosen = 0
    findings: list[str] = []
    for card, trigger, spec, targeted in _rows(_pool):
        if not targeted or trigger.condition.kind != "enters_battlefield":
            continue
        if "Aura" in (card.type_line or ""):
            continue
        label = card.name
        probe = _table(_pool, _mercenaries, hand=[card])
        listed = [
            (entry["seat"], entry["index"])
            for entry in probe.cast_target_spec(0, card, optional_cost_payments={}).get("valid_targets") or ()
        ]
        if len(listed) < 2:
            continue
        seat, slot = listed[0]

        # Named, and still there: it stands.
        game = _table(_pool, _mercenaries, interactive={0}, hand=[card])
        named = game.players[seat].graveyard[slot]
        before = _yards(game)
        assert game.queue_from_hand(
            0, card.name, target_player_index=seat, target_permanent_index=slot,
        ).supported, label
        game.resolve_top_of_stack()
        item = _object(game, trigger)
        if item is None or _prompt(game, trigger) is not None:
            findings.append(f"{label}: a card named at the cast was asked for again")
            continue
        if not item.targets_chosen or item.target_graveyard_card.card is not named:
            findings.append(f"{label}: the cast's card is not the trigger's chosen target")
        _drain(game)
        if _left(before, _yards(game)) != [(named.name, seat)]:
            findings.append(f"{label}: named {named.name}; {_left(before, _yards(game))} moved")
        else:
            stood += 1

        # Named, and exiled in response to the permanent spell.
        game = _table(_pool, _mercenaries, interactive={0}, hand=[card])
        assert game.queue_from_hand(
            0, card.name, target_player_index=seat, target_permanent_index=slot,
        ).supported, label
        pile = game.players[seat]
        pile.exile.append(pile.graveyard.pop(slot))
        game.resolve_top_of_stack()
        prompt = _prompt(game, trigger)
        if prompt is None:
            findings.append(f"{label}: the named card left and nobody was asked")
            continue
        offers = _offers(prompt)
        if not offers or any(
            game.players[s].graveyard[i] is not None and (s, i) == (seat, slot)
            and game.players[s].graveyard[i] is named
            for s, i, _n in offers
        ):
            findings.append(f"{label}: the card that left is still on offer")
        again_seat, again_slot, again_name = offers[-1]
        before = _yards(game)
        assert game.confirm_trigger_target(0, seat=again_seat, graveyard_index=again_slot), label
        _drain(game)
        if _left(before, _yards(game)) != [(again_name, again_seat)]:
            findings.append(f"{label}: chose {again_name}; {_left(before, _yards(game))} moved")
        else:
            rechosen += 1

    assert stood >= 8 and rechosen >= 8, (stood, rechosen)
    assert not findings, "\n".join(findings)


def test_a_slot_the_trigger_could_not_choose_is_set_aside_at_the_push(_pool, _mercenaries):
    """Gravedigger cast naming a **Lightning Bolt** in its controller's pile —
    not a creature card, and only a script can name it, the picker never
    offers it. The trigger cannot choose it (CR 603.3d), so the announcement
    is set aside as the trigger goes on the stack, it says so, and its
    controller is asked for a card it can."""
    digger = _pool["Gravedigger"]
    trigger = next(
        t for t in compile_card_oracle(digger).triggered_abilities
        if t.condition.kind == "enters_battlefield"
    )
    game = _table(_pool, _mercenaries, interactive={0}, hand=[digger])
    bolt = _YARDS[0].index("Lightning Bolt")

    assert game.queue_from_hand(
        0, "Gravedigger", target_player_index=0, target_permanent_index=bolt,
    ).supported
    game.resolve_top_of_stack()

    assert any("can't target what was named as it was cast" in line for line in game.log[-3:])
    prompt = _prompt(game, trigger)
    assert prompt is not None
    assert "Lightning Bolt" not in [name for _s, _i, name in _offers(prompt)]
    assert not game.confirm_trigger_target(0, seat=0, graveyard_index=bolt)
    assert _prompt(game, trigger) is prompt, "a refused answer leaves it owed"


def test_no_legal_card_takes_a_targeted_trigger_off_the_stack(_pool):
    """CR 603.3d: "If a choice is required when the triggered ability goes on
    the stack but no legal choices can be made for it … the ability is simply
    removed from the stack." Gravedigger beside empty graveyards used to
    resolve into "No creature to return"."""
    digger = _pool["Gravedigger"]
    game = Game(players=[
        PlayerState("A", library=[_pool["Forest"]] * 10),
        PlayerState("B", library=[_pool["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, Permanent(card=digger), None)

    assert game.stack == []
    assert "it has no legal target (603.3d)" in game.log[-1]


def test_a_graveyard_card_the_line_does_not_call_a_target_is_not_chosen_on_the_stack(_pool):
    """The printed-word half of the gate. Harvest Wurm's "sacrifice it unless
    you return a basic land card from your graveyard to your hand" derives the
    same spec as Gravedigger and targets nothing: nobody is asked as it goes on
    the stack, and with no basic land card to return it still resolves — and
    is sacrificed — where a targeted ability would have been removed."""
    wurm = _pool["Harvest Wurm"]
    game = Game(players=[
        PlayerState("A", library=[_pool["Forest"]] * 10),
        PlayerState("B", library=[_pool["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    source = Permanent(card=wurm)
    game._put_permanent_onto_battlefield(0, source, None)

    assert len(game.stack) == 1 and not game.pending_choices_of("trigger_target")
    assert not game.stack[0].targets_chosen
    _drain(game)
    assert not game.is_on_battlefield(source)
    assert [card.name for card in game.players[0].graveyard] == ["Harvest Wurm"]

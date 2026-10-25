"""Census: every damage loop in ``engine/handlers`` asks CR 616.1e's question
and resumes at the right recipient.

CR 616.1: when two or more prevention or replacement effects would modify how
one event affects a player or an object, the affected player — or the affected
object's controller — chooses one to apply (616.1e: any of them may be chosen),
and the process repeats (616.1f). The engine asks that through
``damage_events.deal_damage``'s ``restart``, which ``asks=True`` builds; the
answer re-runs the one damage event, and ``engine/resumption.py`` brings back
the work behind it.

Judgment's W2G2 converted the six sweep kinds (``damage_sweeps.py``,
``test_jud_w2g2_sweep_order_census.py``) and left sixteen damage calls in
``engine/handlers`` that passed no ``asks`` — five of them loops over several
recipients — plus, as round ``kg`` measured, four places that asked from a plain
``for`` or from two calls in a row, so the recipients behind the one that asked
were dealt to *before* the answer (the fights, the bite-backs, The Fallen).

Every case here is one site, driven with a card from the pool that compiles to
it (every card carrying the kind is tried until one reaches the recipient). The
recipient that asks holds two applicable prevention effects — a "prevent the
next 3" pool and a counting pool (Temper's shape), two shields from two sources
whose order is visible — and its controller, seat 0, is interactive. Each case
checks:

* the default seat is not asked, and its run is the reference board;
* the interactive seat **is** asked, and when it is, every recipient in front
  of the one that asked has been dealt to exactly once (its reference state)
  and the one that asked and every one behind it not yet;
* answering with the first option — the default — leaves exactly the
  reference board, with nothing owed and the loop's last line written;
* answering with the second option is honoured: the recipient that asked
  differs, and every other recipient is still dealt to.

On the base every case was dealt without asking, or asked with the recipients
behind it already dealt to.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.damage_events import DAMAGED_THIS_GAME
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import OracleInstruction, compiled_units
from engine.shields import add_shield, make_counting_pool, make_numeric_pool, shields_on
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _instructions(value):
    if isinstance(value, OracleInstruction):
        yield value
        for sub in (value.payload or {}).values():
            yield from _instructions(sub)
    elif isinstance(value, (tuple, list)):
        for sub in value:
            yield from _instructions(sub)
    elif isinstance(value, dict):
        for sub in value.values():
            yield from _instructions(sub)


def _carriers(match, cards=None) -> list[tuple]:
    """Every (card, instruction) in the pool whose instruction *match* accepts,
    one per card."""
    found, seen = [], set()
    for card, program in compiled_units(_POOL.values() if cards is None else cards):
        if not program.supported or card.name in seen:
            continue
        roots = list(program.instructions)
        roots += [a.instruction for a in program.activated_abilities if a.instruction]
        roots += [t.instruction for t in program.triggered_abilities if t.instruction]
        for root in roots:
            hit = next((i for i in _instructions(root) if match(i)), None)
            if hit is not None:
                found.append((card, hit))
                seen.add(card.name)
                break
    return found


def _kind(kind):
    return lambda instruction: instruction.kind == kind


def _recipient(value):
    return lambda instruction: (
        instruction.kind == "deal_damage"
        and (instruction.payload or {}).get("recipient") == value
    )


def _several(instruction) -> bool:
    targets = (instruction.payload or {}).get("targets") or {}
    return (
        instruction.kind == "deal_damage" and isinstance(targets, dict)
        and isinstance(targets.get("count"), int) and targets["count"] > 1
    )


def _that_player(instruction) -> bool:
    targets = (instruction.payload or {}).get("targets") or {}
    return (
        instruction.kind == "deal_damage" and isinstance(targets, dict)
        and (targets.get("filter") or {}).get("controller") == "that_player"
    )


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _game(interactive: bool, seats: int = 2) -> Game:
    game = Game(players=[
        PlayerState(f"P{index}", library=[_POOL["Island"]] * 5)
        for index in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(1)
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    game.pending_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _arm_two(recipient) -> None:
    """Two applicable prevention effects from two sources: a plain pool and a
    pool that puts a +1/+1 counter down for each point it absorbs. Either may
    apply first (CR 616.1e), and which did is visible afterwards."""
    add_shield(recipient, make_numeric_pool(3, source_name="Plain Pool"))
    add_shield(recipient, make_counting_pool(3, "+1/+1", source_name="Counting Pool"))


def _snap(game: Game, thing) -> tuple:
    shields = tuple(sorted((s.kind, s.amount) for s in shields_on(thing)))
    if isinstance(thing, PlayerState):
        return ("player", thing.life, shields)
    return (
        thing.card.name, game.is_on_battlefield(thing), thing.damage_marked,
        int(thing.metadata.get("plus_counters", 0) or 0),
        thing.metadata.get("loyalty_counters"), shields,
    )


def _execute(game, card, instruction, **context) -> None:
    context.setdefault("caster", game.players[1])
    context.setdefault("target", game.players[0])
    game._execute_oracle_instruction(
        instruction, OracleExecutionContext(card=card, **context),
    )


# ---------------------------------------------------------------------------
# One driver per site: build the board, return (recipients in the loop's order,
# the index of the one that asks, the run)
# ---------------------------------------------------------------------------


def _wave(game, card, instruction):
    """Each creature bites itself: the board's order, seat 0 first."""
    front = _put(game, 0, "Grizzly Bears")
    asker = _put(game, 0, "Grizzly Bears")
    behind = _put(game, 1, "Grizzly Bears")
    _arm_two(asker)
    order = [p for p in game.all_permanents() if p in (front, asker, behind)]
    return order, order.index(asker), lambda: _execute(game, card, instruction)


def _recorded(game, card, instruction):
    """Each of the creatures an earlier step recorded, in the record's order."""
    front = _put(game, 1, "Air Elemental")
    asker = _put(game, 0, "Air Elemental")
    behind = _put(game, 1, "Air Elemental")
    for creature in (front, asker, behind):
        creature.attacking = True
    _arm_two(asker)
    key = instruction.payload.get("permanents_from")
    record = [front.permanent_id, asker.permanent_id, behind.permanent_id]
    return [front, asker, behind], 1, lambda: _execute(
        game, card, instruction, x_value=2, results={key: record},
    )


def _the_fallen(game, card, instruction):
    """Each opponent it has damaged, then each planeswalker: three seats, the
    source on seat 2, its record naming seat 1 before seat 0."""
    source = _put(game, 2, card.name)
    walker = _put(game, 1, "Chandra, Heart of Fire")
    _arm_two(game.players[0])
    source.metadata[DAMAGED_THIS_GAME] = {
        "seats": [1, 0], "permanents": [walker.permanent_id],
    }
    return (
        [game.players[1], game.players[0], walker], 1,
        lambda: _execute(
            game, card, instruction, caster=game.players[2],
            source_permanent=source,
        ),
    )


def _several_targets(game, card, instruction):
    """Each of two target creatures, in the order they were named."""
    front = _put(game, 1, "Grizzly Bears")
    asker = _put(game, 0, "Grizzly Bears")
    _arm_two(asker)
    return [front, asker], 1, lambda: _execute(
        game, card, instruction,
        target_permanent_id=[front.permanent_id, asker.permanent_id],
    )


def _index_list(game, card, instruction):
    """Fireball's undivided fallback: a list of named slots, highest first."""
    behind = _put(game, 0, "Grizzly Bears")
    asker = _put(game, 0, "Grizzly Bears")
    _arm_two(asker)
    return [asker, behind], 0, lambda: _execute(
        game, card, instruction, caster=game.players[1], target=game.players[0],
        x_value=4,
        target_permanent_index=[
            game.battlefield_index_of(behind), game.battlefield_index_of(asker),
        ],
        target_permanent_id=[behind.permanent_id, asker.permanent_id],
    )


def _that_player_target(game, card, instruction):
    asker = _put(game, 0, "Grizzly Bears")
    _arm_two(asker)
    source = _put(game, 1, card.name)
    return [asker], 0, lambda: _execute(
        game, card, instruction, source_permanent=source,
        target_permanent_id=[asker.permanent_id],
        trigger_context={"event_subject_player": 0, "amount": 1},
    )


def _bound_permanent(game, card, instruction):
    asker = _put(game, 0, "Grizzly Bears")
    _arm_two(asker)
    source = _put(game, 1, card.name)
    return [asker], 0, lambda: _execute(
        game, card, instruction, source_permanent=source,
        trigger_context={"bound_permanent_id": asker.permanent_id},
    )


def _event_subject(game, card, instruction):
    asker = _put(game, 0, "Grizzly Bears")
    _arm_two(asker)
    source = _put(game, 1, card.name)
    return [asker], 0, lambda: _execute(
        game, card, instruction, source_permanent=source,
        trigger_context={"event_subject_permanent_id": asker.permanent_id, "amount": 1},
    )


def _upkeep_toll(game, card, instruction):
    """The synthetic upkeep-damage instruction (Juzám Djinn's toll)."""
    source = _put(game, 0, card.name)
    _arm_two(game.players[0])
    return [game.players[0]], 0, lambda: _execute(
        game, card, instruction, caster=game.players[0], source_permanent=source,
        trigger_context={"victim_player_index": 0, "amount": 1},
    )


def _simulacrum(game, card, instruction):
    asker = _put(game, 0, "Grizzly Bears")
    _arm_two(asker)
    game.players[0].damage_taken_this_turn = 2
    return [asker], 0, lambda: _execute(
        game, card, instruction, caster=game.players[0], target=game.players[0],
        target_permanent_id=[asker.permanent_id],
    )


def _bite_back(game, card, instruction):
    """"That creature deals damage equal to its power to this creature": the
    ability's source is the recipient that asks. The record is a sequence by
    its channel's definition (``_targets.recorded_permanent_ids``) and the
    pool's sentences put one biter in it; two make the loop observable — the
    second bite must wait for the first one's answer."""
    source = _put(game, 0, card.name)
    _arm_two(source)
    if instruction.payload.get("cards_from") is not None:
        exiled = [_POOL["Grizzly Bears"], _POOL["Scryb Sprites"]]
        game.players[1].exile.extend(exiled)
        results = {instruction.payload["cards_from"]: exiled}
    else:
        biters = [_put(game, 1, "Grizzly Bears"), _put(game, 1, "Scryb Sprites")]
        results = {
            instruction.payload["permanents_from"]: [b.permanent_id for b in biters],
        }
    return [source], 0, lambda: _execute(
        game, card, instruction, caster=game.players[0], source_permanent=source,
        results=results,
    )


def _bite_player(game, card, instruction):
    """"That creature deals damage equal to its power to its controller", with
    two recorded biters for ``_bite_back``'s reason."""
    biters = [_put(game, 0, "Grizzly Bears"), _put(game, 0, "Scryb Sprites")]
    _arm_two(game.players[0])
    key = instruction.payload["permanents_from"]
    return [game.players[0]], 0, lambda: _execute(
        game, card, instruction, results={key: [b.permanent_id for b in biters]},
    )


def _two_target_fight(game, card, instruction):
    """Seat 1's creature fights seat 0's: the first half — the one that asks —
    is dealt to seat 0's, and the second, to seat 1's, must wait for it."""
    fighter = _put(game, 1, "Grizzly Bears")
    opponent = _put(game, 0, "Grizzly Bears")
    _arm_two(opponent)
    return [opponent, fighter], 0, lambda: _execute(
        game, card, instruction, caster=game.players[1], target=game.players[0],
        x_value=0,
        target_permanent_id=[fighter.permanent_id, opponent.permanent_id],
    )


def _source_fight(game, card, instruction):
    fighter = _put(game, 1, card.name)
    opponent = _put(game, 0, "Grizzly Bears")
    _arm_two(opponent)
    return [opponent, fighter], 0, lambda: _execute(
        game, card, instruction, caster=game.players[1], target=game.players[0],
        source_permanent=fighter, target_permanent_id=[opponent.permanent_id],
    )


def _self_damage(game, card, instruction):
    """The two-event kind no card compiles to any more (its sentences lower to
    a ``sequence``); driven with its own payload so the code it still holds is
    held to the rule."""
    asker = _put(game, 0, "Grizzly Bears")
    _arm_two(asker)
    _arm_two(game.players[1])
    return [asker, game.players[1]], 0, lambda: _execute(
        game, card, instruction, caster=game.players[1], target=game.players[0],
        target_permanent_id=[asker.permanent_id],
    )


#: (label, the instructions the pool carries for the site, its driver, players)
_CASES = (
    ("each_matching_bites_itself", _kind("each_matching_bites_itself"), _wave, 2),
    ("deal_damage_to_recorded_permanents",
     _kind("deal_damage_to_recorded_permanents"), _recorded, 2),
    ("deal_damage_to_those_damaged_this_game",
     _kind("deal_damage_to_those_damaged_this_game"), _the_fallen, 3),
    ("deal_damage: each of several targets", _several, _several_targets, 2),
    ("deal_damage: target that player controls", _that_player, _that_player_target, 2),
    ("deal_damage: the bound permanent", _recipient("bound_permanent"), _bound_permanent, 2),
    ("deal_damage: the event's subject", _recipient("event_subject"), _event_subject, 2),
    ("simulacrum_redirect", _kind("simulacrum_redirect"), _simulacrum, 2),
    ("bound_bites_source", _kind("bound_bites_source"), _bite_back, 2),
    ("bound_bites_player", _kind("bound_bites_player"), _bite_player, 2),
    ("target_fights_target", _kind("target_fights_target"), _two_target_fight, 2),
    ("source_fights_target", _kind("source_fights_target"), _source_fight, 2),
    ("prepare_then_interact (fight)",
     lambda i: i.kind == "prepare_then_interact" and i.payload.get("mode") == "fight",
     _two_target_fight, 2),
)

#: Sites no compiled card reaches as such: Fireball's instruction without the
#: division its cast announces, the upkeep toll the upkeep registry builds, and
#: a fused kind no sentence lowers to any more.
_SYNTHETIC = (
    ("deal_damage: Fireball's index list", "Fireball",
     lambda card: _carriers(_kind("deal_damage"), [card])[0][1], _index_list, 2),
    ("deal_damage_to_player (the upkeep toll)", "Juzám Djinn",
     lambda card: OracleInstruction("deal_damage_to_player", "", {}), _upkeep_toll, 2),
    ("deal_damage_and_self_damage", "Grizzly Bears",
     lambda card: OracleInstruction(
         "deal_damage_and_self_damage", "", {"amount": 1, "self_damage": 1},
     ), _self_damage, 2),
)


def _rows():
    for label, match, driver, seats in _CASES:
        yield label, _carriers(match), driver, seats
    for label, name, build, driver, seats in _SYNTHETIC:
        card = _POOL[name]
        yield label, [(card, build(card))], driver, seats


def _run(driver, card, instruction, seats, *, interactive: bool):
    game = _game(interactive, seats)
    recipients, asker, run = driver(game, card, instruction)
    before = [_snap(game, r) for r in recipients]
    mark = len(game.log)
    run()
    return game, recipients, asker, before, mark


def _answer(game, option: int) -> None:
    choice = game.pending_choice_of("effect_order")
    assert game.resolve_pending_choice("effect_order", choice.player_index, option_index=option)


def _answer_all(game, first: int) -> None:
    """Answer the question with *first*, and any later one (a second recipient
    asking) with the default."""
    _answer(game, first)
    while game.pending_choice_of("effect_order") is not None:
        _answer(game, 0)


def _lines(game, mark: int) -> list[str]:
    """What the effect wrote, without the question and its answer."""
    return [
        line for line in game.log[mark:]
        if "which effect applies first" not in line
        and not (line.startswith("P") and " applies " in line and line.endswith(" first"))
    ]


def _settle(game) -> None:
    """CR 704.3's check, which the answer path makes once the resumed
    resolution is over and a direct execution never reaches."""
    game.check_state_based_actions()


def test_every_damage_loop_asks_and_resumes_at_the_recipient_that_asked():
    unreached, unasked, early, unfinished, unhonoured = [], [], [], [], []
    examined = 0
    for label, carriers, driver, seats in _rows():
        assert carriers, f"no card in the pool carries {label!r}: the census is blind to it"
        for card, instruction in carriers:
            examined += 1
            ref, ref_recipients, asker, before, mark = _run(
                driver, card, instruction, seats, interactive=False,
            )
            dealt = [_snap(ref, r) for r in ref_recipients]
            if dealt[asker] == before[asker]:
                continue  # this card's instruction does not reach the recipient
            assert not ref.pending_choices, f"{label} ({card.name}): a default seat was asked"
            _settle(ref)
            reference = [_snap(ref, r) for r in ref_recipients]
            ref_lines = _lines(ref, mark)

            game, recipients, asker, _, mark = _run(
                driver, card, instruction, seats, interactive=True,
            )
            asked = [c for c in game.pending_choices if c.kind == "effect_order"]
            if not asked:
                unasked.append(f"{label} ({card.name})")
                break
            assert asked[0].player_index == 0
            now = [_snap(game, r) for r in recipients]
            expected = dealt[:asker] + before[asker:]
            if now != expected:
                early.append(f"{label} ({card.name}): {now} != {expected}")
                break
            if len(asked) != 1:
                # The event behind the one that asked ran too, and asked its
                # own question before the first was answered.
                early.append(f"{label} ({card.name}): {len(asked)} questions at once")
                break
            _answer_all(game, 0)
            _settle(game)
            after = [_snap(game, r) for r in recipients]
            if after != reference:
                unfinished.append(f"{label} ({card.name}): {after} != {reference}")
            if game.resume_stack or game.pending_choices:
                unfinished.append(
                    f"{label} ({card.name}): {len(game.resume_stack)} step(s) owed, "
                    f"{[c.kind for c in game.pending_choices]} queued"
                )
            if _lines(game, mark) != ref_lines:
                unfinished.append(
                    f"{label} ({card.name}): wrote {_lines(game, mark)}, not {ref_lines}"
                )

            other, recipients, asker, _, _ = _run(
                driver, card, instruction, seats, interactive=True,
            )
            _answer_all(other, 1)
            _settle(other)
            honoured = [_snap(other, r) for r in recipients]
            if honoured[asker] == reference[asker] or (
                honoured[:asker] + honoured[asker + 1:]
                != reference[:asker] + reference[asker + 1:]
            ):
                unhonoured.append(f"{label} ({card.name}): {honoured} vs {reference}")
            break
        else:
            unreached.append(label)

    assert examined >= len(_CASES) + len(_SYNTHETIC)
    # One assertion over every finding, so a red run names each defect at once.
    findings = {
        "no card carrying these reached the recipient": unreached,
        "dealt to a recipient with two applicable effects without asking its "
        "controller (CR 616.1e)": unasked,
        "the recipients behind the one that asked were dealt to before the "
        "answer, or the ones in front of it were not": early,
        "the loop did not finish after the answer": unfinished,
        "the second option was not honoured": unhonoured,
    }
    assert not any(findings.values()), "\n".join(
        f"{what}: {rows}" for what, rows in findings.items() if rows
    )


# ---------------------------------------------------------------------------
# On the real paths
# ---------------------------------------------------------------------------


def _counters(permanent) -> int:
    return int(permanent.metadata.get("plus_counters", 0) or 0)


def _pool_left(recipient) -> int:
    return sum(s.amount or 0 for s in shields_on(recipient) if s.kind == "prevent_next_n")


def test_wave_of_reckoning_cast_asks_at_the_phantom_and_finishes_after_the_answer():
    """Wave of Reckoning cast through the stack. Seat 0's Phantom Centaur bites
    itself for 5 with two effects applicable: its own counter shield and a
    "prevent the next 3" pool. The creature in front of it has bitten when the
    question is asked, the one behind it has not; the answer is honoured, the
    rest bite, the summary is written once and the sorcery reaches the
    graveyard only then (CR 608.2n)."""
    for pick, pool_left, phantom_counters in (("next n damage", 0, 2), ("remove a counter", 3, 2)):
        game = _game(interactive=True)
        front = _put(game, 0, "Grizzly Bears")
        phantom = _put(game, 0, "Phantom Centaur")
        behind = _put(game, 1, "Grizzly Bears")
        add_shield(phantom, make_numeric_pool(3, source_name="Healing Salve"))
        game.players[1].hand.append(_POOL["Wave of Reckoning"])
        assert _counters(phantom) == 3

        assert game.cast_from_hand(1, "Wave of Reckoning").supported
        game.resolve_top_of_stack(pause_for_choices=True)
        choice = game.pending_choice_of("effect_order")
        assert choice is not None and choice.player_index == 0
        assert front.damage_marked == 2, "the creature in front of the Phantom has bitten"
        assert behind.damage_marked == 0, "the creature behind it has not"
        assert _counters(phantom) == 3 and _pool_left(phantom) == 3
        assert any(item.card.name == "Wave of Reckoning" for item in game.stack), (
            "the sorcery is still resolving while its damage waits (CR 608.2)"
        )

        labels = [str(option).lower() for option in choice.data["options"]]
        index = next(i for i, label in enumerate(labels) if pick in label)
        assert game.resolve_pending_choice("effect_order", 0, option_index=index)
        resolve_stack(game)

        assert _pool_left(phantom) == pool_left
        assert _counters(phantom) == phantom_counters
        assert phantom.damage_marked == 0
        assert not game.is_on_battlefield(front) and not game.is_on_battlefield(behind)
        summary = [line for line in game.log if line.startswith("Wave of Reckoning: each creature")]
        assert len(summary) == 1
        assert any(card.name == "Wave of Reckoning" for card in game.players[1].graveyard)
        assert game.resume_stack == [] and game.pending_choices == []


def test_mana_clash_asks_each_time_and_flips_no_coin_twice(monkeypatch):
    """Mana Clash's rounds, with the coins rigged: tails/tails, heads/tails,
    heads/heads. The opponent holds two applicable pools and is asked at each
    of its two damage events; the caster's damage in front of the first is
    dealt, no coin is flipped again on the answer (the re-run is of the one
    damage event), and the round after the answer is the next round."""
    coins = iter([False, False, True, False, True, True])
    monkeypatch.setattr("engine.handlers.damage.flip_coin", lambda: next(coins))
    game = _game(interactive=True)
    caster, opponent = game.players[1], game.players[0]
    _arm_two(opponent)
    game.players[1].hand.append(_POOL["Mana Clash"])

    assert game.cast_from_hand(1, "Mana Clash", target_player_index=0).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    flips = lambda: [line for line in game.log if "flipped" in line]
    assert game.pending_choice_of("effect_order", 0) is not None
    assert len(flips()) == 1
    assert caster.life == 19 and opponent.life == 20

    assert game.resolve_pending_choice("effect_order", 0, option_index=0)
    assert game.pending_choice_of("effect_order", 0) is not None, "round two asks again"
    assert len(flips()) == 2
    assert caster.life == 19

    assert game.resolve_pending_choice("effect_order", 0, option_index=0)
    resolve_stack(game)
    assert len(flips()) == 3
    assert opponent.life == 20 and caster.life == 19
    assert game.log.count("Mana Clash: both coins came up heads after 3 flip(s)") == 1
    assert next(coins, None) is None, "every rigged coin was flipped exactly once"
    assert game.resume_stack == [] and game.pending_choices == []

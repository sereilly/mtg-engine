"""The four prompt defaults that still ranked by position behind a
preference (kg4 ``defaults`` left them): what a seat nobody asks discards,
which permanent it picks for a resolving effect (one, or several), and which
cards out of its hand it names for a later step.

Each is answered now by a reader in ``engine/ai_prompt_picks.py``:

* ``discard`` — ``discard_order``: a payable madness card first, then the
  cards least worth holding (``held_worth``), under ``order_discard``'s
  penalty preference. Mind Rot took the first two cards in hand.
* ``permanent_choice`` / ``permanent_set_choice`` — ``permanent_pick_order``:
  the side of the step reading the pick's record (``recorded_pick_side``),
  then ``permanent_worth`` on that side. The Abyss destroyed the creature
  that had been out longest, Drop of Honey the first tied creature (its
  controller's own), Curfew returned a seat's first creature, Demonic
  Hordes' opponent took the first land.
* ``choose_cards_in_hand`` — ``hand_pick_order``: what the step reading the
  pick does with the cards. Sylvan Library put back the first two drawn,
  Noxious Vapors spared the first card of each colour.

Each census walks every compilation unit that arms its prompt
(``faces.compilation_units``) on a table where the first candidate offered is
the worse pick, and asserts a floor on what it examined. Validated
backwards: every board and every census fails on ``243f72df`` (the base),
where each default took the first thing offered.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_prompt_picks import mana_breadth, permanent_pick_side, recorded_pick_side
from engine.ai_prompt_readers import discard_spares_a_penalty
from engine.ai_standing import permanent_worth
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.handlers.permanent_choices import _chooser_seat, permanent_choice_candidates
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _table(*, seats=2, interactive=(), enforce=False) -> Game:
    game = Game(players=[PlayerState(name=f"P{seat}") for seat in range(seats)])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game, seat, card, *, tapped=False) -> Permanent:
    permanent = Permanent(card=card, tapped=tapped)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _drain(game) -> None:
    for _ in range(8):
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def _steps(instruction):
    yield instruction
    for value in (instruction.payload or {}).values():
        if hasattr(value, "kind"):
            yield from _steps(value)
        elif isinstance(value, (list, tuple)):
            for child in value:
                if hasattr(child, "kind"):
                    yield from _steps(child)


def _arming(kinds):
    """``(unit, step)`` for each supported unit's first step of *kinds* per
    record it writes."""
    found, seen = [], set()
    for unit in compilation_units(load_catalog()):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [a.instruction for a in program.activated_abilities if a.instruction is not None]
        roots += [t.instruction for t in program.triggered_abilities if t.instruction is not None]
        for root in roots:
            for step in _steps(root):
                key = (unit.name, step.kind, (step.payload or {}).get("result_key"))
                if step.kind in kinds and key not in seen:
                    seen.add(key)
                    found.append((unit, step))
    return found


# -- discard --------------------------------------------------------------------


def test_mind_rot_discards_the_spare_lands_not_the_dragon(catalog_by_name):
    """"Target player discards two cards." The first card in hand was the
    first discarded: the Shivan Dragon its three Mountains are building
    towards went, beside a fourth land."""
    game = _table()
    for _ in range(3):
        _put(game, 1, catalog_by_name["Mountain"])
    game.players[1].hand = [catalog_by_name["Shivan Dragon"]] + [catalog_by_name["Mountain"]] * 3
    game.players[0].hand = [catalog_by_name["Mind Rot"]]
    assert game.cast_from_hand(0, "Mind Rot", target_player_index=1).supported
    _drain(game)
    assert _names(game.players[1].hand) == ["Shivan Dragon", "Mountain"], game.log[-6:]
    assert _names(game.players[1].graveyard) == ["Mountain", "Mountain"]


def test_an_interactive_seat_answered_for_discards_the_same_cards(catalog_by_name):
    """The queued prompt's own default — the path a test's drain or a
    timed-out seat takes — is the same reader."""
    game = _table(interactive=(1,))
    for _ in range(3):
        _put(game, 1, catalog_by_name["Mountain"])
    game.players[1].hand = [catalog_by_name["Shivan Dragon"]] + [catalog_by_name["Mountain"]] * 3
    game.players[0].hand = [catalog_by_name["Mind Rot"]]
    assert game.cast_from_hand(0, "Mind Rot", target_player_index=1).supported
    assert game.pending_choices_of("discard", 1)
    _drain(game)
    assert _names(game.players[1].hand) == ["Shivan Dragon", "Mountain"], game.log[-6:]


_DISCARD_KINDS = frozenset({
    "discard_target_cards", "discard_controller_cards", "each_opponent_discards_cards",
    "each_player_discards_a_card", "draw_then_discard_self",
})


def test_every_chosen_discard_keeps_the_card_worth_holding(catalog_by_name):
    """Every chosen discard the pool prints, executed for seats nobody asks
    holding a Shivan Dragon ahead of three lands with three on the
    battlefield: whoever discards keeps the Dragon — except where the
    sentence behind prices which card went (Strongarm Tactics' creature),
    whose own preference goes first."""
    examined, wrong = [], []
    for unit, step in _arming(_DISCARD_KINDS):
        payload = step.payload or {}
        if payload.get("filter") or payload.get("up_to") or payload.get("any_number"):
            continue
        if discard_spares_a_penalty(unit) is not None:
            continue
        if payload.get("who") or payload.get("from_drawn") or payload.get("x_from_count_per_recipient"):
            continue
        game = _table()
        hand = [catalog_by_name["Shivan Dragon"]] + [catalog_by_name["Mountain"]] * 3
        for seat in (0, 1):
            for _ in range(3):
                _put(game, seat, catalog_by_name["Mountain"])
            game.players[seat].hand = list(hand)
            game.players[seat].library = [catalog_by_name["Island"]] * 6
        context = OracleExecutionContext(
            caster=game.players[0], target=game.players[1], card=unit,
        )
        game._execute_oracle_instruction(step, context)
        _drain(game)
        moved = [seat for seat in (0, 1) if len(game.players[seat].hand) != len(hand)]
        if not moved or any(len(game.players[seat].hand) == 0 for seat in moved):
            continue
        examined.append(unit.name)
        for seat in moved:
            if "Shivan Dragon" not in _names(game.players[seat].hand):
                wrong.append((unit.name, seat, _names(game.players[seat].hand)))
    assert len(examined) >= 10, examined
    assert wrong == [], wrong


# -- permanent_choice -------------------------------------------------------------


def test_the_abyss_destroys_the_cheapest_creature_of_the_seat_choosing(catalog_by_name):
    """"At the beginning of each player's upkeep, destroy target nonartifact
    creature that player controls of their choice." The upkeep's player gives
    up its least: the Llanowar Elves, not the Craw Wurm that entered first."""
    game = _table()
    _put(game, 0, catalog_by_name["The Abyss"])
    _put(game, 1, catalog_by_name["Craw Wurm"])
    _put(game, 1, catalog_by_name["Llanowar Elves"])
    game.players[1].library = [catalog_by_name["Forest"]] * 5
    game.active_player_index = 0
    game.start_turn(1)
    _drain(game)
    assert _names(p.card for p in game.controlled_by(1)) == ["Craw Wurm"], game.log[-8:]
    assert "Llanowar Elves" in _names(game.players[1].graveyard)


def test_drop_of_honey_destroys_the_opponent_s_tied_creature(catalog_by_name):
    """"…destroy the creature with the least power … If two or more creatures
    are tied for least power, you choose one of them." Its controller's own
    1/1 was on the battlefield first, and was the one destroyed."""
    game = _table()
    _put(game, 0, catalog_by_name["Drop of Honey"])
    _put(game, 0, catalog_by_name["Llanowar Elves"])
    _put(game, 1, catalog_by_name["Llanowar Elves"])
    _put(game, 1, catalog_by_name["Craw Wurm"])
    game.players[0].library = [catalog_by_name["Forest"]] * 5
    game.active_player_index = 1
    game.start_turn(0)
    _drain(game)
    assert _names(p.card for p in game.controlled_by(0)) == ["Drop of Honey", "Llanowar Elves"], game.log[-8:]
    assert _names(p.card for p in game.controlled_by(1)) == ["Craw Wurm"]


def test_demonic_hordes_opponent_takes_the_dual_land(catalog_by_name):
    """"…unless you pay {B}{B}{B}, tap Demonic Hordes and sacrifice a land of
    an opponent's choice." The opponent took the first land on the board."""
    game = _table(enforce=True)
    _put(game, 0, catalog_by_name["Demonic Hordes"])
    _put(game, 0, catalog_by_name["Plains"])
    tundra = _put(game, 0, catalog_by_name["Tundra"])
    game.players[0].library = [catalog_by_name["Plains"]] * 5
    game.active_player_index = 1
    game.start_turn(0)
    _drain(game)
    assert not game.is_on_battlefield(tundra), game.log[-8:]
    assert _names(p.card for p in game.controlled_by(0)) == ["Demonic Hordes", "Plains"]


def _expected_pick(game, chooser: int, side: str, live: list):
    def worth(perm):
        return (permanent_worth(perm), mana_breadth(game, perm))

    own = [perm for perm in live if game.controller_index_of(perm) == chooser]
    other = [perm for perm in live if game.controller_index_of(perm) != chooser]
    if side == "opponent":
        return max(other, key=worth) if other else min(own, key=worth)
    return max(own, key=worth) if own else min(other, key=worth)


def _board_for(game, catalog_by_name, side: str, cheap: str, dear: str) -> None:
    """Two candidates per seat, arranged so the first offered is the worse
    pick for *side*: the chooser's (seat 0) dear one first where the step
    works against the pick, its cheap one first where it works for it."""
    first, second = (dear, cheap) if side == "opponent" else (cheap, dear)
    _put(game, 0, catalog_by_name[first])
    _put(game, 0, catalog_by_name[second])
    _put(game, 1, catalog_by_name[second])
    _put(game, 1, catalog_by_name[first])


_PAIRS = (("Llanowar Elves", "Craw Wurm"), ("Plains", "Tundra"))


def _census_context(game, unit, chooser_word):
    caster = 1 if chooser_word == "opponent" else 0
    return OracleExecutionContext(
        caster=game.players[caster], target=game.players[1 - caster], card=unit,
        trigger_context={
            "event_subject_player": 0, "event_subject_controller": 0,
            "trigger_defending_player_index": 0,
        },
        results={"chosen_player": 0},
    )


def test_every_permanent_pick_follows_the_side_its_step_works_for(catalog_by_name):
    """Every ``choose_permanent`` the pool prints whose record a step reads
    for a side: armed for a seat nobody asks on a board where the first
    candidate offered is the worse pick, the pick is somebody else's dearest
    (or the chooser's own cheapest) where the step works against it, and the
    chooser's own dearest where it works for it."""
    examined, wrong = [], []
    for unit, step in _arming({"choose_permanent"}):
        payload = dict(step.payload or {})
        if payload.get("at_random"):
            continue
        for cheap, dear in _PAIRS:
            game = _table()
            probe = _census_context(game, unit, payload.get("chooser"))
            side = permanent_pick_side(game, 0, payload, probe, payload["result_key"])
            if side is None:
                break
            _board_for(game, catalog_by_name, side, cheap, dear)
            context = _census_context(game, unit, payload.get("chooser"))
            chooser = _chooser_seat(game, payload, context)
            if chooser != 0:
                continue
            live = permanent_choice_candidates(game, payload, context)
            if len(live) < 2:
                continue
            payload.pop("only_on_tie", None)
            game.arm_permanent_choice(
                0, card_name=unit.name, prompt="", result_key=payload["result_key"],
                payload=payload, context=context, candidates=live,
            )
            game.auto_resolve_pending_choices()
            picked = game.permanent_by_id(context.results.get(payload["result_key"]))
            expected = _expected_pick(game, 0, side, live)
            examined.append(unit.name)
            if picked is not expected:
                wrong.append((unit.name, side, getattr(getattr(picked, "card", None), "name", None),
                              game.controller_index_of(picked) if picked else None))
            break
    assert len(examined) >= 12, examined
    assert wrong == [], wrong


def test_the_recorded_pick_s_side_is_read_off_the_step_behind_it(catalog_by_name):
    """The reader's answer for the shapes the pool prints, one card each:
    against the pick (a destroy, an exile, a -1/-1 counter, a tap, a forced
    block, a sacrifice, a gift to somebody else, a control change) and for
    it (a +1/+1 counter, an untap, a pick a sweep spares); none where only
    a condition reads it or two steps read it for opposite sides."""
    game = _table()
    expected = {
        "The Abyss": "opponent", "Drop of Honey": "opponent", "Wormfang Crab": "opponent",
        "Tourach's Chant": "opponent", "Koskun Falls": "opponent", "Crashing Boars": "opponent",
        "Retribution": "opponent", "Juxtapose": "opponent", "Risky Move": "opponent",
        "Erithizon": "you", "Ley Line": "you", "Rising Waters": "you",
        "Guard Dogs": None, "Desperate Gambit": None,
        "Curfew": "opponent", "Bull Elephant": "opponent", "Equipoise": "opponent",
        "Raiding Party": "you", "Mist of Stagnation": "you",
    }
    read = {}
    for unit, step in _arming({"choose_permanent", "choose_permanents"}):
        if unit.name in expected and unit.name not in read:
            context = OracleExecutionContext(
                caster=game.players[0], target=game.players[1], card=unit,
            )
            read[unit.name] = recorded_pick_side(game, 0, context, step.payload["result_key"])
    assert read == expected


# -- permanent_set_choice ---------------------------------------------------------


def test_curfew_returns_each_seat_s_cheapest_creature(catalog_by_name):
    """"Each player returns a creature they control to its owner's hand."
    Each seat's first creature went, a Craw Wurm beside Llanowar Elves."""
    game = _table()
    for seat in (0, 1):
        _put(game, seat, catalog_by_name["Craw Wurm"])
        _put(game, seat, catalog_by_name["Llanowar Elves"])
    game.players[0].hand = [catalog_by_name["Curfew"]]
    assert game.cast_from_hand(0, "Curfew").supported
    _drain(game)
    for seat in (0, 1):
        assert _names(p.card for p in game.controlled_by(seat)) == ["Craw Wurm"], game.log[-8:]
        assert "Llanowar Elves" in _names(game.players[seat].hand)


def test_every_permanent_set_pick_follows_the_side_its_step_works_for(catalog_by_name):
    """Every ``choose_permanents`` with a side, one pick out of the chooser's
    own two, the worse first: where the step takes the picks (a return to
    hand, a tap, a phasing) the cheaper goes, where it keeps them (Raiding
    Party's survivors, Mist of Stagnation's untaps) the dearer."""
    examined, wrong = [], []
    for unit, step in _arming({"choose_permanents"}):
        payload = dict(step.payload or {})
        if payload.get("default_none") or payload.get("same_number_as") is not None:
            continue
        for cheap, dear in _PAIRS:
            game = _table()
            probe = _census_context(game, unit, None)
            side = permanent_pick_side(game, 0, payload, probe, payload["result_key"])
            if side is None:
                break
            first, second = (dear, cheap) if side == "opponent" else (cheap, dear)
            mine = [_put(game, 0, catalog_by_name[first]), _put(game, 0, catalog_by_name[second])]
            context = _census_context(game, unit, None)
            payload["chooser"] = 0
            live = permanent_choice_candidates(game, payload, context)
            if [perm.permanent_id for perm in live] != [perm.permanent_id for perm in mine]:
                continue
            context.results[payload["result_key"]] = []
            game.arm_permanent_set_choice(
                0, card_name=unit.name, prompt="", result_key=payload["result_key"],
                payload=payload, context=context, candidates=live, up_to=1,
            )
            game.auto_resolve_pending_choices()
            picked = context.results.get(payload["result_key"]) or []
            # The board puts the worse pick first, so the better is second.
            expected = mine[1]
            examined.append(unit.name)
            if len(picked) != 1 or picked[0] is not expected:
                wrong.append((unit.name, side, _names(p.card for p in picked)))
            break
    assert len(examined) >= 10, examined
    assert wrong == [], wrong


# -- choose_cards_in_hand ---------------------------------------------------------


def test_sylvan_library_puts_back_the_lands_it_drew(catalog_by_name):
    """"…choose two cards in your hand drawn this turn. For each of those
    cards, pay 4 life or put the card on top of your library." At 3 life the
    cards go back, and the first two drawn this turn went — the Shivan Dragon
    its Mountains are building towards (the draw step's card) among them."""
    game = _table()
    game.players[0].life = 3
    for _ in range(3):
        _put(game, 0, catalog_by_name["Mountain"])
    _put(game, 0, catalog_by_name["Sylvan Library"])
    game.players[0].library = (
        [catalog_by_name["Shivan Dragon"]] + [catalog_by_name["Mountain"]] * 2
        + [catalog_by_name["Island"]] * 5
    )
    game.players[1].library = [catalog_by_name["Island"]] * 5
    game.active_player_index = 1
    # Not the game's first turn, whose draw step the player going first skips
    # (CR 103.8a): the draw step's card is the first drawn this turn.
    game.turn = 5
    game.start_turn(0)
    _drain(game)
    held = _names(game.players[0].hand)
    assert held.count("Shivan Dragon") == 1, game.log[-10:]
    assert _names(game.players[0].library[:2]) == ["Mountain", "Mountain"], game.log[-10:]


def test_noxious_vapors_spares_each_colour_s_dearest_card(catalog_by_name):
    """"Each player reveals their hand, chooses one card of each color from
    it, then discards all other nonland cards." The first green card in hand
    was the one spared, Llanowar Elves over a Craw Wurm."""
    game = _table()
    game.players[1].hand = [catalog_by_name["Llanowar Elves"], catalog_by_name["Craw Wurm"]]
    game.players[0].hand = [catalog_by_name["Noxious Vapors"]]
    assert game.cast_from_hand(0, "Noxious Vapors").supported
    _drain(game)
    assert _names(game.players[1].hand) == ["Craw Wurm"], game.log[-8:]
    assert _names(game.players[1].graveyard) == ["Llanowar Elves"]

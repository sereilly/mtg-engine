"""Every split damage sentence in the pool asks its CR 616.1 questions in
APNAP order — the behavioural half of the one-dealing census.

``tests/engine/test_kg3_dealings_one_dealing_census.py`` holds every printed
damage sentence the lowering splits into steps to a ``sequence`` marked
``oracle_types.ONE_DEALING`` (one simultaneous dealing, CR 608.2f). This runs
each of those sequences — both manifest roles, every ability and spell that
carries one — at a two-seat table where it has the most to ask: both players
and each seat's creatures (a white flyer, a green creature, a blue flyer) each
carry two prevention effects large enough to stay applicable for every chunk,
mid-combat (the active seat's creatures attacking and blocked, the other
seat's blocking), both seats interactive. Every chunk's damage event then
asks its affected player which effect applies first (CR 616.1e), and the
order the seats are asked in must be APNAP order (CR 616.1's last sentence,
101.4): never back to a seat earlier in the turn order. Each sentence is run
with each seat active.

Validated backwards on 313bd09d, where ``control_flow._in_apnap_order``
ordered a sentence's *steps* and only when each named one recipient it could
read before running: ten of the eighty runs went back a seat — Disorder,
Kaervek's Hex, Tropical Storm and Warpath with either seat active, Bellowing
Fiend's trigger and its spell row with its controller active. The driven
boards are ``tests/rules/test_kg4_dealings_split_sentence_apnap.py``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from engine.oracle_types import ONE_DEALING, OracleInstruction
from engine.shields import add_shield, make_counting_pool, make_numeric_pool

_POOL = load_cards(manifest_set_paths(include_measured=True))
_BY_NAME = {card.name: card for card in _POOL}
#: One creature of each colour and evasion the marked sentences' sweeps name
#: (white, green — nonblack, all three — and blue with flying, flying).
_PALETTE = ("Serra Angel", "Grizzly Bears", "Mahamoti Djinn")
#: Runs, each sentence once with each seat active: kg4 `dealings` made 80 (40
#: marked sequences on 27 cards), 61 of which asked both seats.
_EXAMINED_FLOOR = 72
_BOTH_SEATS_FLOOR = 50


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _is_spell(card) -> bool:
    return "Instant" in card.type_line or "Sorcery" in card.type_line


def _marked():
    for unit in compilation_units(_POOL):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        roots = [ability.instruction for ability in program.activated_abilities]
        roots += [trig.instruction for trig in program.triggered_abilities]
        roots.append(tuple(program.instructions))
        for root in roots:
            for instruction in _walk(root):
                if instruction.kind == "sequence" and instruction.payload.get(ONE_DEALING):
                    yield unit, instruction


def _contend(recipient) -> None:
    add_shield(recipient, make_numeric_pool(10, source_name="Test Pool A"))
    add_shield(recipient, make_counting_pool(10, "+1/+1", source_name="Test Pool B"))


def _board(unit, active: int):
    island = _BY_NAME["Island"]
    game = Game(players=[
        PlayerState(f"P{seat}", library=[island] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    creatures: dict[int, list[Permanent]] = {0: [], 1: []}
    for seat in (0, 1):
        for name in _PALETTE:
            permanent = Permanent(card=_BY_NAME[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            creatures[seat].append(permanent)
    game._sync_control()
    game.start_turn(active)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    other = 1 - active
    ok, why = game.declare_attackers(
        active, [game.battlefield_index_of(p) for p in creatures[active]],
        defending_player_index=other,
    )
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(other, {
        game.battlefield_index_of(blocker): game.battlefield_index_of(attacker)
        for blocker, attacker in zip(creatures[other], creatures[active])
    })
    assert ok, why
    source = None
    if not _is_spell(unit):
        # The permanent the sentence is printed on, on seat 0's side: "itself"
        # and "you" are seat 0's, and Heart of Bogardan's X reads its age
        # counters (2 → X = 2).
        source = Permanent(card=unit)
        game._put_permanent_onto_battlefield(0, source, None)
        source.metadata["summoning_sickness_turn"] = -99
        add_counters(source, "age", 2)
        game._sync_control()
    for recipient in [*game.players, *creatures[0], *creatures[1]] + (
        [source] if source is not None else []
    ):
        _contend(recipient)
    game.interactive_seats = {0, 1}
    return game, source


def _asked(unit, sequence, active: int) -> tuple[list[int], Game]:
    game, source = _board(unit, active)
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=unit,
        source_permanent=source, x_value=2,
        # Bellowing Fiend's "that creature's controller": the seat its
        # damage event hit, frozen by the damage seam (CR 603.10).
        trigger_context={"damaged_permanent_controller": 1},
    )
    game._execute_oracle_instruction(sequence, context)
    asked: list[int] = []
    for _ in range(64):
        owed = [choice for choice in game.pending_choices if choice.kind == "effect_order"]
        if not owed:
            break
        seat = owed[0].player_index
        asked.append(seat)
        assert game.resolve_pending_choice("effect_order", seat, option_index=0)
    assert not game.pending_choices, (unit.name, game.pending_choices)
    assert game.simultaneous_damage is None, unit.name
    return asked, game


def test_every_split_sentence_asks_its_seats_in_apnap_order():
    examined, both, out_of_order, names = 0, 0, [], set()
    for unit, sequence in _marked():
        for active in (0, 1):
            asked, game = _asked(unit, sequence, active)
            examined += 1
            names.add(unit.name)
            rank = [game.apnap_seats().index(seat) for seat in asked]
            if len(set(asked)) == 2:
                both += 1
            if rank != sorted(rank):
                out_of_order.append(f"{unit.name} (P{active} active): asked {asked}")
    assert examined >= _EXAMINED_FLOOR, examined
    assert both >= _BOTH_SEATS_FLOOR, both
    # The four shapes kg3 left asking in printed order are in what was run.
    assert {"Disorder", "Kaervek's Hex", "Warpath", "Bellowing Fiend"} <= names, sorted(names)
    assert not out_of_order, (
        "a split damage sentence asked a seat after a later one in the turn "
        "order (CR 616.1, 101.4): every chunk of one dealing is dealt at once, "
        "so the active player's questions about all of it come first:\n  "
        + "\n  ".join(out_of_order)
    )

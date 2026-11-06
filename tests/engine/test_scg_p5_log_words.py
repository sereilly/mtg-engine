"""The log lines and prompt words a person reads say who did what, in the
order it happened (SCG Phase 5, the words items).

Each was read off a browser session and each is a class:

1. **A draw logged as the card drawing.** "Riptide Survivor drew 3 card",
   "Spark Spray drew 0 card": the player draws (CR 121.1). Asked of every log
   line the engine writes about a draw: the drawer is a player and the count
   reads "card(s)".
2. **A delayed trigger labelled with its card's name twice.** The stack and
   the trigger-order prompt write "<card>: <ability text>", and a delayed
   trigger's ability text was its card's name — "Dimensional Breach:
   Dimensional Breach". Asked of every card in the pool that creates one.
3. **A prompt's sentence naming the wrong kind of object.** Pemmin's Aura's
   activated "choose one" was "choose a mode for the triggered ability". Asked
   of every prompt whose sentence names "triggered ability": every site that
   arms it is on a triggered ability's road.
4. **Mana logged before the tap that made it.** "Temple of the False God
   produced {C}{C}" came before "tapped". Asked of every land in the pool
   with a mana ability, tapped once through the one tap seam.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_ROOT = Path(__file__).resolve().parents[2]
_ENGINE = _ROOT / "engine"
_POOL = {card.name: card for card in load_catalog()}


def _engine_sources():
    for path in sorted(_ENGINE.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Draws.
# ---------------------------------------------------------------------------

#: An f-string draw line whose drawer is a card: ``{card.name} drew``.
_CARD_DRAWS = re.compile(r"""f["'][^"'\n]*\{(?:[\w.]*card[\w.]*|source[\w.]*)\} drew\b""")
#: A draw line counting a variable in the bare singular or plural.
_BARE_COUNT = re.compile(r"""\} drew \{[^{}]+\} cards?["')]""")


def test_no_draw_line_names_a_card_as_the_drawer():
    found = []
    examined = 0
    for path, text in _engine_sources():
        for number, line in enumerate(text.splitlines(), 1):
            if " drew " not in line or "log" not in text:
                continue
            examined += " drew " in line and ("f\"" in line or "f'" in line)
            if _CARD_DRAWS.search(line) or _BARE_COUNT.search(line):
                found.append(f"{path.relative_to(_ROOT)}:{number}: {line.strip()}")
    assert examined >= 10, examined
    assert not found, "\n".join(found)


def test_riptide_survivors_draw_names_its_controller():
    """The report's line, played: the drawer, a count, and the card that made
    them draw."""
    game = Game(players=[
        PlayerState(name="P0", library=[_POOL["Island"]] * 6, hand=[_POOL["Island"]] * 2),
        PlayerState(name="P1", library=[_POOL["Island"]] * 6),
    ])
    from engine.game_types import OracleExecutionContext
    from engine.handlers import EFFECT_HANDLERS
    from engine.oracle import OracleInstruction

    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=_POOL["Riptide Survivor"],
    )
    EFFECT_HANDLERS["draw_controller_cards"](
        game, OracleInstruction("draw_controller_cards", payload={"amount": 2}), context,
    )
    assert "P0 drew 2 card(s) (Riptide Survivor)" in game.log, game.log
    assert not any(line.startswith("Riptide Survivor drew") for line in game.log)


# ---------------------------------------------------------------------------
# 2. Delayed triggers.
# ---------------------------------------------------------------------------


def _creates_a_delayed_trigger(program) -> bool:
    def walk(instruction) -> bool:
        if instruction is None:
            return False
        if instruction.kind == "create_delayed_trigger":
            return True
        for value in instruction.payload.values():
            values = value if isinstance(value, (list, tuple)) else (value,)
            if any(hasattr(v, "kind") and hasattr(v, "payload") and walk(v) for v in values):
                return True
        return False

    roots = list(program.instructions) + [
        getattr(ability, "instruction", None)
        for ability in list(program.activated_abilities) + list(program.triggered_abilities)
    ]
    return any(walk(root) for root in roots)


@pytest.mark.full
def test_every_delayed_trigger_in_the_pool_carries_its_own_words():
    from engine.delayed_triggers import delayed_ability_text

    creators = [
        card for card in compilation_units(_POOL.values())
        if compile_card_oracle(card).supported and _creates_a_delayed_trigger(compile_card_oracle(card))
    ]
    wordless = [
        card.name for card in creators
        if (delayed_ability_text(card.oracle_text or "") or card.name) == card.name
    ]
    assert len(creators) >= 150, len(creators)
    # Debt of Loyalty's "if it regenerates this way" opens no CR 603.7a
    # sentence; it keeps its card's name, as every delayed trigger did.
    assert set(wordless) <= {"Debt of Loyalty"}, wordless


def test_dimensional_breachs_upkeep_trigger_says_what_it_does():
    """Cast through the engine: the delayed trigger that fires in the next
    upkeep is on the stack with its sentence, not its card's name."""
    from engine.delayed_triggers import DELAYED_EVENTS  # noqa: F401  (the table exists)
    from tests.helpers import resolve_stack

    library = [_POOL["Island"]] * 6
    game = Game(players=[
        PlayerState(name="P0", library=list(library), hand=[_POOL["Dimensional Breach"]]),
        PlayerState(name="P1", library=list(library)),
    ])
    game._put_permanent_onto_battlefield(1, Permanent(card=_POOL["Grizzly Bears"]), None)
    game.turn = 3
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(0)
    assert game.queue_from_hand(0, "Dimensional Breach").supported
    resolve_stack(game)
    game.turn += 1
    game.active_player_index = 1
    game.begin_turn_bookkeeping(1)
    game.resolve_untap_step(1)
    game.resolve_upkeep(1, defer_priority=True)
    texts = [item.ability_text for item in game.stack if item.card.name == "Dimensional Breach"]
    assert texts, game.log[-8:]
    assert all(text and text != "Dimensional Breach" and "upkeep" in text for text in texts), texts


# ---------------------------------------------------------------------------
# 3. A prompt's sentence and the objects that arm it.
# ---------------------------------------------------------------------------

#: Where a triggered ability's own prompts are armed: its target and mode as
#: it is put on the stack (CR 603.3c-d) and its order (CR 603.3b).
_TRIGGER_ROADS = {
    "engine/mixins/stack/trigger_targets.py",
    "engine/mixins/stack/choices/triggers.py",
    "engine/trigger_order.py",
}
_ARMED = re.compile(r"""arm_pending_choice\(\s*(?:\n\s*)?(?:"(\w+)"|([A-Z_]+))""")


def test_a_prompt_that_says_triggered_ability_is_armed_only_by_one():
    from engine.pending_choices import CHOICE_SPECS as SPECS
    import engine.trigger_order as trigger_order

    constants = {"ORDER_TRIGGERS": trigger_order.ORDER_TRIGGERS}
    naming = {
        kind for kind, spec in SPECS.items()
        if "triggered abilit" in (spec.blocked_detail or "")
    }
    assert naming, "no prompt names a triggered ability"
    wrong = []
    for path, text in _engine_sources():
        relative = path.relative_to(_ROOT).as_posix()
        for match in _ARMED.finditer(text):
            kind = match.group(1) or constants.get(match.group(2) or "")
            if kind in naming and relative not in _TRIGGER_ROADS:
                line = text.count("\n", 0, match.start()) + 1
                wrong.append(f"{relative}:{line} arms {kind}: {SPECS[kind].blocked_detail!r}")
    assert not wrong, "\n".join(wrong)


# ---------------------------------------------------------------------------
# 4. Mana and the tap that made it.
# ---------------------------------------------------------------------------


def _tap(game: Game, land: Permanent) -> bool:
    """Tap *land* for mana by the road a player takes: the land tap, or —
    for a mana ability that road refuses (Temple of the False God's "Activate
    only if you control five or more lands") — its activation (CR 106.12's
    three roads share ``Game._land_tapped_for_mana``)."""
    if not game.is_on_battlefield(land):
        return False  # a land that sacrifices another to enter, alone here
    if game.tap_land_for_mana(0, land.card.name, permanent_id=land.permanent_id):
        return True
    result = game.activate_permanent_ability(
        0, land.card.name, permanent_index=game.battlefield_index_of(land),
    )
    return bool(result.supported) and land.tapped


def _mana_lands() -> list[str]:
    return sorted({
        card.name for card in compilation_units(_POOL.values())
        if card.primary_type == "land" and compile_card_oracle(card).supported
        and "add" in (card.oracle_text or "").lower()
    })


@pytest.mark.full
def test_every_land_logs_its_tap_before_what_it_made():
    wrong = []
    tapped = 0
    for name in _mana_lands():
        game = Game(players=[
            PlayerState(name="P0", library=[_POOL["Island"]] * 4),
            PlayerState(name="P1", library=[_POOL["Island"]] * 4),
        ])
        land = Permanent(card=_POOL[name])
        game._put_permanent_onto_battlefield(0, land, None)
        land.tapped = False  # a land that enters tapped is tapped for mana here
        # Temple of the False God's "Activate only if you control five or
        # more lands": four more beside it.
        for _ in range(4):
            game._put_permanent_onto_battlefield(0, Permanent(card=_POOL["Plains"]), None)
        game.active_player_index = 0
        game._set_phase_and_step("precombat_main", "precombat_main")
        game.start_priority_window(0)
        mark = len(game.log)
        if not _tap(game, land):
            continue
        lines = game.log[mark:]
        tap = next((i for i, line in enumerate(lines) if line == f"P0 tapped {name} for mana"), None)
        if tap is None:
            continue  # the road taken was not a mana ability (a manland's animation)
        tapped += 1
        made = next((i for i, line in enumerate(lines) if line.startswith(f"{name} produced")), None)
        if made is not None and made < tap:
            wrong.append(f"{name}: {lines}")
    assert tapped >= 100, tapped
    assert not wrong, "\n".join(wrong)


def test_temple_of_the_false_god_logs_the_tap_first():
    game = Game(players=[
        PlayerState(name="P0", library=[_POOL["Island"]] * 4),
        PlayerState(name="P1", library=[_POOL["Island"]] * 4),
    ])
    temple = Permanent(card=_POOL["Temple of the False God"])
    game._put_permanent_onto_battlefield(0, temple, None)
    for _ in range(4):
        game._put_permanent_onto_battlefield(0, Permanent(card=_POOL["Plains"]), None)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(0)
    mark = len(game.log)
    assert _tap(game, temple)
    lines = game.log[mark:]
    assert lines.index("P0 tapped Temple of the False God for mana") < next(
        i for i, line in enumerate(lines) if "produced" in line
    ), lines

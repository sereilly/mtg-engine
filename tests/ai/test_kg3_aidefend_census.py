"""Pool-wide censuses behind the declare-attackers window (kg3 `aidefend`).

**The defect, measured on the base (link 49f558ae).** The simulator answered
no priority in the declare-attackers step (`ai_simulator.
_instant_speed_window`), a rehearsal started there declared no blocks, and
the activation chooser skipped every ability hampering its own source and
every tapped permanent. On that tree each census below reads **zero**: no
flash creature cast before the blocks, no ability activated there, no
own-source hamper raised in front of a removal spell — which is the backwards
validation (rerun with the window closed and the hamper skip restored, each
floor fails).

Each census builds one board per card, so that the subject is the only thing
that can change the outcome, drives it through the engine's own combat walk
(`ai_combat.run_ai_combat_phase`) or cast path, and holds **invariants** over
what the AI did there plus a **floor** on how much was examined and how much
was done. What a board could not credit is measured, not asserted (the
report lists it).
"""
from __future__ import annotations

import random
import re
from dataclasses import replace

import pytest

from engine import ai_simulator
from engine.ai_combat import CombatOutcome, run_ai_combat_phase
from engine.ai_valuation import _effect_steps, hampers_its_own_source
from engine.cast_timing import casts_at_instant_speed
from engine.faces import compilation_units
from engine.mana_abilities import is_mana_ability
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _mk_creature_card, _nosick

pytestmark = pytest.mark.full

_BASIC = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


def _table(cards, boards, hands=((), ())):
    # The real game's randomness on a fixed seed, as every board is built: a
    # coin flip on it (Bottle of Suleiman's) otherwise falls by whatever ran
    # before this board in the process — the census's verdict on it with it
    # (kg4/determinism). A rehearsal's own sample is seeded apart
    # (``ai_scratch_copy._rehearsal_seed``).
    random.seed(1337)
    players = [
        PlayerState(name=name, hand=list(hand), library=[cards["Forest"]] * 8)
        for name, hand in zip(("AI-A", "AI-B"), hands)
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = 0
    placed = {}
    for seat, board in enumerate(boards):
        for card, tapped in board:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
            permanent.tapped = tapped
            placed.setdefault(card.name, permanent)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, report, placed


def _attack_and_fight(game):
    """AI-A's one creature attacks AI-B; the combat is walked to its end.
    Returns the blocks the defender declared (``(blocker id, attacker id)``)."""
    while game.current_step != "declare_attackers":
        game.advance_combat_phase()
    slot = game.battlefield_index_of(next(p for p in game.controlled_by(0) if p.is_creature))
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why
    outcome = CombatOutcome()
    run_ai_combat_phase(game, 0, outcome=outcome)
    return outcome.blocks_declared


def _lands(cards, symbols) -> list:
    names, generic = [], 0
    for symbol, amount in symbols:
        if symbol in _BASIC:
            names += [_BASIC[symbol]] * amount
        elif symbol in ("generic", "C") or str(symbol).isdigit():
            generic += amount
    names += [names[0] if names else "Plains"] * generic
    return [(cards[name], False) for name in names]


def _cost_symbols(mana_cost: str):
    for symbol in re.findall(r"\{([^}]+)\}", mana_cost or ""):
        yield (symbol, 1) if not symbol.isdigit() else ("generic", int(symbol))


@pytest.fixture(scope="module")
def cards(catalog):
    return {card.name: card for card in catalog}


# --- every flash creature -------------------------------------------------------

#: Flash creatures the AI rightly does **not** cast to block on the paying
#: board, with the reason. Held both ways below: an entry must be examined and
#: must indeed be declined.
_DECLINES = {
    "Fleetfoot Panther": (
        "its entry returns a green or white creature its controller controls to "
        "hand, and on this board the only one is itself"
    ),
}


@pytest.fixture(scope="module")
def flash_census(cards, catalog):
    """Per creature castable at instant speed by its own text: the paying
    board (an invented vanilla it kills and survives: power = its toughness
    - 1, toughness = its power) and the flier board (the same with flying).

    Whether the creature **could block** the flier is the engine's answer,
    asked of it on the battlefield beside the attacker
    (``Game._can_block_attacker``, CR 509.1b) — never assumed: a creature
    with reach can (CR 702.17b, Tangle Spider), and this read "none of them
    can" until Darksteel shipped one."""
    rows = {}
    for card in compilation_units(catalog):
        if card.primary_type != "creature" or not casts_at_instant_speed(card):
            continue
        if not compile_card_oracle(card).supported:
            continue
        power = int(card.raw.get("power") or 0)
        toughness = int(card.raw.get("toughness") or 0)
        attacker = _mk_creature_card("Census Attacker", max(0, toughness - 1), max(1, power))
        flier = replace(attacker, oracle_text="Flying", keywords=("Flying",))
        row = {}
        probe, _report, placed = _table(cards, ([(flier, False)], [(card, False)]))
        could_block = probe._can_block_attacker(placed[card.name], placed[flier.name])
        for label, aimed in (("pays", attacker), ("flier", flier)):
            game, report, _placed = _table(
                cards, ([(aimed, False)], _lands(cards, _cost_symbols(card.mana_cost))),
                hands=((), (card,)),
            )
            _attack_and_fight(game)
            row[label] = {
                "before_blocks": report.casts_before_blocks,
                "kept": any(p.card.name == card.name for p in game.controlled_by(1)),
                "attacker_dead": not any(
                    p.card.name == "Census Attacker" for p in game.controlled_by(0)
                ),
                "raised": dict(report.rehearsals_raised),
            }
        row["flier"]["could_block"] = could_block
        rows[card.name] = row
    return rows


def test_every_flash_creature_ambushes_where_a_block_pays(flash_census):
    """On the paying board each flash creature is cast in the declare-attackers
    step, blocks, kills the attacker and lives — except the named declines.
    Zero on the base tree, where that window was passed without asking."""
    ambushed = {name for name, row in flash_census.items() if row["pays"]["before_blocks"]}
    assert len(flash_census) >= 15, sorted(flash_census)
    assert set(_DECLINES) <= set(flash_census), sorted(set(_DECLINES) - set(flash_census))
    assert not ambushed & set(_DECLINES), sorted(ambushed & set(_DECLINES))
    missed = sorted(set(flash_census) - ambushed - set(_DECLINES))
    assert missed == [], missed
    for name in ambushed:
        row = flash_census[name]["pays"]
        assert row["kept"] and row["attacker_dead"], (name, row)
    assert all(not row["pays"]["raised"] for row in flash_census.values())


def test_no_flash_creature_is_cast_before_a_block_it_cannot_make(flash_census):
    """Against a flier it cannot block (the engine's block legality, CR
    509.1b), casting before the blocks adds no block: nothing is cast there
    (the end step is where such a body goes). One that can — reach, CR
    702.17b — is a block the cast makes, and is the paying board's question.
    The floor: the flier board examined creatures that cannot block it."""
    unable = {name for name, row in flash_census.items() if not row["flier"]["could_block"]}
    assert len(unable) >= 15, sorted(unable)
    cast = sorted(name for name in unable if flash_census[name]["flier"]["before_blocks"])
    assert cast == [], cast


# --- every ability that could add a block ---------------------------------------


def _block_shape(step) -> str | None:
    """Which way one step of an ability could add a block, read off its kind
    and payload: a creature token, an untap (its source's or another's),
    flying or reach granted (its source's or another's), flying taken from
    the attacker, a permanent animated — or None."""
    kind = step.kind
    words = " ".join(str(value) for value in (step.payload or {}).values()).lower()
    own = "self" in kind or "source" in kind
    if "token" in kind:
        return "token"
    if kind.startswith("untap"):
        return "untap_self" if own else "untap"
    if "animate" in kind or "becomes_creature" in kind:
        return "animate"
    evasive = "flying" in kind or "reach" in kind or "flying" in words or "reach" in words
    if evasive and ("grant" in kind or "gain" in kind):
        return "evasion_self" if own else "evasion"
    if ("remove" in kind or "lose" in kind) and "flying" in words:
        return "remove_flying"
    return None


def _ability_board(cards, card, ability, shape, *, window_open):
    """The defender holds *card* and the lands for *ability*; the attacker is
    an invented 0/1 (a flier where the shape is about flying). A helper 2/2
    stands beside the source where the shape needs one, tapped for an untap.
    With *window_open* False the declare-attackers window is closed — the
    control board, whose blocks are those the defender had without it."""
    attacker = _mk_creature_card("Census Attacker", 0, 1)
    if shape in ("evasion", "evasion_self", "remove_flying"):
        attacker = replace(attacker, oracle_text="Flying", keywords=("Flying",))
    defender = [(card, shape == "untap_self")]
    if shape in ("untap", "evasion", "remove_flying"):
        defender.append((_mk_creature_card("Census Helper", 2, 2), shape == "untap"))
    symbols = [(symbol, int(amount or 0)) for symbol, amount in dict(ability.cost.mana).items()]
    defender += _lands(cards, [*symbols, ("U", 1), ("W", 1)])
    game, report, _placed = _table(cards, ([(attacker, False)], defender))
    if not window_open:
        game.priority_driver = None
    blocks = _attack_and_fight(game)
    return report, blocks


@pytest.fixture(scope="module")
def ability_census(cards, catalog):
    rows = {}
    for card in compilation_units(catalog):
        program = compile_card_oracle(card)
        if not program.supported or "Aura" in (card.type_line or ""):
            continue
        usable = usable_activated_abilities(program)
        if "land" in (card.type_line or "").lower():
            weighed = [a for a in usable if a.instruction is not None and not is_mana_ability(a)]
        else:
            weighed = usable[:1]
        for ability in weighed:
            if ability.instruction is None:
                continue
            shapes = sorted({_block_shape(step) for step in _effect_steps(ability.instruction)} - {None})
            if not shapes:
                continue
            report, blocks = _ability_board(cards, card, ability, shapes[0], window_open=True)
            row = {
                "shape": shapes[0],
                "before_blocks": report.activations_at_instant_speed.get("declare_attackers", 0),
                "blocks": blocks,
                "raised": dict(report.rehearsals_raised),
            }
            if row["before_blocks"]:
                _report, row["control_blocks"] = _ability_board(
                    cards, card, ability, shapes[0], window_open=False,
                )
            rows[(card.name, ability.source_line)] = row
    return rows


#: Activated before the blocks and adding none, each with why. Bottle of
#: Suleiman flips a coin: won, a 5/5 flying Djinn that blocks; lost, 5 damage
#: to its controller. The rehearsal's sample of the flip is its own
#: (``ai_scratch_copy._rehearsal_seed``, read off what every seat can count since
#: kg4) and won; the board's flip, on the seed ``_table`` fixes, lost. The AI
#: weighs a flip on one sample of it, not on its odds.
#:
#: Wirefly Hive (DST) is the same flip: "{3}, {T}: Flip a coin. If you win the
#: flip, create a 2/2 colorless Insect artifact creature token with flying
#: named Wirefly. If you lose the flip, destroy all permanents named Wirefly."
#: Traced at its promotion (each flip marked by ``ai_rehearsal.rehearsing``):
#: the rehearsal's two readings (as it stands, and through the fight) both
#: won, the board's one flip lost — "Wirefly Hive: lost the coin flip", no
#: token, no block — exactly Bottle's three flips.
_COIN = "a coin flip: the rehearsal's sample won it, the board's flip lost it"
_ADDED_NOTHING = {"Bottle of Suleiman": _COIN, "Wirefly Hive": _COIN}


def test_every_ability_activated_before_the_blocks_adds_a_block(ability_census):
    """The window's own rule held on the real board: each ability the AI
    activated in the declare-attackers step left the defender declaring a
    block the same board with the window closed did not declare. And the
    floors: the census examined the pool's shapes, and the window was used —
    zero on the base tree."""
    activated = {key: row for key, row in ability_census.items() if row["before_blocks"]}
    assert len(ability_census) >= 150, len(ability_census)
    assert len(activated) >= 40, sorted(name for name, _line in activated)
    added_nothing = sorted(
        name for (name, _line), row in activated.items()
        if not row["blocks"] - row["control_blocks"]
    )
    assert added_nothing == sorted(_ADDED_NOTHING), added_nothing
    shapes = {row["shape"] for row in activated.values()}
    assert {"token", "animate", "evasion_self", "evasion", "untap_self", "remove_flying"} <= shapes
    assert all(not row["raised"] for row in ability_census.values())


# --- an own-source hamper in front of a removal spell ---------------------------


@pytest.fixture(scope="module")
def rescue_census(cards, catalog):
    """Per creature whose weighed ability hampers its own source
    (``ai_valuation.hampers_its_own_source``): AI-A casts Swords to
    Plowshares at it with the defender's lands up for the ability."""
    rows = {}
    for card in compilation_units(catalog):
        if card.primary_type != "creature":
            continue
        usable = usable_activated_abilities(compile_card_oracle(card))
        ability = usable[0] if usable else None
        if ability is None or not hampers_its_own_source(ability.instruction):
            continue
        symbols = [(s, int(a or 0)) for s, a in dict(ability.cost.mana).items()]
        game, report, placed = _table(
            cards, ([(cards["Plains"], False)], [(card, False), *_lands(cards, symbols)]),
            hands=((cards["Swords to Plowshares"],), ()),
        )
        target = placed[card.name]
        game.players[0].mana_pool["W"] = 1
        result = game.cast_from_hand(
            0, "Swords to Plowshares", target_permanent_ids=[target.permanent_id],
        )
        assert result.supported, (card.name, result.details)
        rows[card.name] = {
            "responded": report.activations_at_instant_speed.get("response", 0),
            "saved": game.is_on_battlefield(target)
            or any(p is target for p in game.players[1].phased_out),
            "raised": dict(report.rehearsals_raised),
        }
    return rows


def test_an_own_hamper_raised_in_response_saves_its_source(rescue_census):
    """Every own-source hamper the AI raised in response to the Swords saved
    the creature (a phase-out, a shroud), and none was raised that did not;
    floors on both. Zero on the base tree, where the chooser skipped them."""
    responded = {name for name, row in rescue_census.items() if row["responded"]}
    assert len(rescue_census) >= 8, sorted(rescue_census)
    assert {"Rainbow Efreet", "Deep Spawn"} <= responded, sorted(responded)
    assert len(responded) >= 3, sorted(responded)
    wasted = sorted(name for name in responded if not rescue_census[name]["saved"])
    assert wasted == [], wasted
    assert all(not row["raised"] for row in rescue_census.values())

"""Krark's Thumb's "ignore one" is asked — every flip the pool makes (kg5 `coins`).

"If you would flip a coin, instead flip two coins and ignore one." The
flipper chooses which coin to ignore, seeing every coin first — the card's
rulings: 2019-01-25, "You will know the results of all simultaneous flips
before choosing which to ignore"; 2004-10-04, "If you and your opponent both
flip at the same time, you can see your opponent's result before choosing
which result to keep". The engine always kept the win (or heads) and never
asked, though cards in the pool reward the losing flip: wave 1's probe cast
Puppet's Verdict under a Thumb with one coin won and one lost, and the
caster's own Llanowar Elves and Grizzly Bears died while the opponent's Craw
Wurm lived.

**The census** walks every compiled flip site in the shipped pool — each
instruction of a kind in :data:`FLIP_SITES`, nested ones included, over
``compilation_units`` — and runs it with a Thumb at a seat a person decides
for and coins rigged so that seat's flip comes up one win and one loss. Every
site must owe that seat the ``ignore_coin`` prompt **before anything reads the
flip** (the resolution suspends, CR 608.2), and the loss kept must be what the
site goes on with. A floor holds how many cards it drove. A second census
holds the table honest: every card whose text flips a coin compiles to at
least one :data:`FLIP_SITES` kind, so a flip of a new kind fails here rather
than going unasked.

**Validated backwards**: with nobody asked (``asks_a_person`` answering no —
the base's behaviour, every flip keeping the win at once), the census names
every site it drove; on the base tree it cannot even arm the prompt, which
did not exist.

The boards beside it are the ones the entry names, driven as it names them:
Puppet's Verdict under the Thumb both ways and at a seat nobody asks; the win
announced only for the coin kept (Chance Encounter); the runs asked mid-way
(Squee's Revenge, Crazed Firecat, Mana Clash's rounds, Fiery Gambit); two
Thumbs on two sides of one simultaneous flip asked in APNAP order
(CR 101.4), the second seeing what the first kept (101.4b); Mijae Djinn's
attack.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.handlers._common import COIN_FACES_BY_SEAT
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from engine.oracle_types import COIN_FLIPS_MADE, COIN_FLIPS_WON
from tests.helpers import settle

_POOL = {card.name: card for card in load_catalog()}

#: Every instruction kind whose handler flips a coin. The census below drives
#: each instance the pool compiles; ``test_every_coin_flipping_card_compiles_a_flip_site``
#: keeps the table from missing one.
FLIP_SITES = frozenset({
    "flip_coin",
    "flip_coins_until_loss",
    "coin_flip_stakes_loop",
    "coin_flip_damage_loop",
    "coin_flip_remove_attacker_and_tap",
    "coin_flip_remove_blocker",
})

#: The modules whose ``flip_coin`` is the coin their flips draw — the name a
#: test rigs (``handlers/_common.flip_coins_for``'s *flip*).
_COIN_MODULES = (
    "engine.handlers.control_flow",
    "engine.handlers.damage",
    "engine.handlers.combat",
    "engine.handlers.coin_runs",
)

#: How many pool cards the census must drive: 36 compile a flip site (37 sites)
#: at kg5.
_CARDS_FLOOR = 30


def card(name: str):
    return _POOL[name]


def rig_coins(monkeypatch, results):
    """Every flip's coins come up *results* in order (True: a win, or heads),
    then wins once they run out. Returns the list of coins drawn."""
    import importlib

    queue = list(results)
    drawn: list[bool] = []

    def coin(win_probability: float = 0.5) -> bool:
        drawn.append(queue.pop(0) if queue else True)
        return drawn[-1]

    for module in _COIN_MODULES:
        monkeypatch.setattr(importlib.import_module(module), "flip_coin", coin)
    return drawn


def table(*, mine=(), theirs=(), hand=(), interactive=(0,)) -> Game:
    """Seat 0 active in its first main phase; *interactive* names the seats a
    person decides for."""
    players = [
        PlayerState(name="Alice", hand=[card(n) for n in hand],
                    library=[card("Plains")] * 8),
        PlayerState(name="Bob", library=[card("Island")] * 8),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            put(game, seat, name)
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return game


def put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def owed_keeps(game: Game) -> list:
    return list(game.pending_choices_of("ignore_coin"))


def keep(game: Game, seat: int, won: bool) -> None:
    assert game.confirm_ignore_coin(seat, won), game.pending_choices


# ---------------------------------------------------------------------------
# The census: every flip site the pool compiles
# ---------------------------------------------------------------------------


def _instructions(obj):
    """Every ``OracleInstruction`` under *obj*, nested ones included."""
    if obj is None:
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _instructions(item)
        return
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _instructions(value)
        return
    if isinstance(getattr(obj, "kind", None), str) and hasattr(obj, "payload"):
        yield obj
        yield from _instructions(obj.payload)
        return
    for attribute in ("instruction", "instructions"):
        if hasattr(obj, attribute):
            yield from _instructions(getattr(obj, attribute))


def _program_instructions(unit):
    program = compile_card_oracle(unit)
    yield from _instructions(program.instructions)
    for ability in (*program.activated_abilities, *program.triggered_abilities):
        yield from _instructions(ability)


def flip_sites():
    """``[(card, instruction)]``: each distinct flip site of each pool card."""
    found = []
    for unit in compilation_units(load_catalog()):
        seen = set()
        for instruction in _program_instructions(unit):
            if instruction.kind not in FLIP_SITES:
                continue
            key = (instruction.kind, repr(sorted(instruction.payload.items())))
            if key in seen:
                continue
            seen.add(key)
            found.append((unit, instruction))
    return found


def attack_with(game: Game, seat: int, name: str) -> Permanent:
    """*name* (already on *seat*'s battlefield) attacks the other seat; the
    declaration's triggers are on the stack, unresolved — at a table a person
    sits at, the attacker holds priority with them there."""
    mine = game.players[seat].battlefield
    slot = next(i for i, p in enumerate(mine) if p.card.name == name)
    game.active_player_index = seat
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(seat, [slot], defending_player_index=1 - seat)
    assert ok, why
    return mine[slot]


def _drive_by_combat(game: Game, unit, instruction):
    """The two combat hooks, on their own road: the creature attacks (or
    blocks) and its trigger resolves. The result is read off the board."""
    put(game, 0, unit.name)
    if instruction.kind == "coin_flip_remove_attacker_and_tap":
        attack_with(game, 0, unit.name)
    else:
        put(game, 1, "Grizzly Bears")
        attack_with(game, 1, "Grizzly Bears")
        game.advance_combat_phase()
        assert game.current_step == "declare_blockers", game.current_step
        mine = game.players[0].battlefield
        blocker = next(i for i, p in enumerate(mine) if p.card.name == unit.name)
        ok, why = game.declare_blockers(0, {blocker: 0})
        assert ok, why
    settle(game, defaults=False)


def drive_site(unit, instruction, *, asked=True):
    """One flip site at a Thumb seat whose first flip is a win and a loss.

    Returns ``(game, context, prompt)``: the prompt owed first (None when
    nobody was asked) and the context the site ran in (None for a combat hook,
    which runs on the stack). *asked* False is the base: nobody asked."""
    game = table(mine=("Krark's Thumb",))
    if not asked:
        game.asks_a_person = lambda seat: False
    if instruction.kind in ("coin_flip_remove_attacker_and_tap", "coin_flip_remove_blocker"):
        _drive_by_combat(game, unit, instruction)
        keeps = owed_keeps(game)
        return game, None, keeps[0] if keeps else None
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=unit,
        trigger_context={"event_subject_player": 0},
    )
    # "Choose a number. Flip a coin that many times …" (Squee's Revenge): the
    # number an earlier step chose.
    if instruction.payload.get("amount_from"):
        context.results[str(instruction.payload["amount_from"])] = 3
    game._execute_oracle_instruction(instruction, context)
    keeps = owed_keeps(game)
    return game, context, keeps[0] if keeps else None


def _first_flip_coins(instruction) -> list[bool]:
    """The coins that make seat 0's first flip a win and a loss: seat 0 flips
    first everywhere (APNAP with seat 0 active; Mana Clash's caster), and an
    opponent's one coin after it comes up heads."""
    return [True, False, True]


def _lost_was_kept(game: Game, context, instruction) -> str | None:
    """What is wrong with the board after seat 0 kept the **loss**, or None."""
    kind, payload = instruction.kind, instruction.payload
    alice, bob = game.players
    if kind == "flip_coin" and payload.get("flipper") == "each_player":
        faces = context.results.get(COIN_FACES_BY_SEAT)
        return None if faces and faces[0] == "tails" else f"faces {faces}"
    if kind == "flip_coin":
        return None if context.results.get("coin_flip") is False else "coin_flip not a loss"
    if kind == "flip_coins_until_loss":
        made, won = context.results.get(COIN_FLIPS_MADE), context.results.get(COIN_FLIPS_WON)
        ok = context.results.get("coin_flip") is False and made == 1 and won == 0
        return None if ok else f"run made {made} won {won}"
    if kind == "coin_flip_stakes_loop":
        return None if (alice.life, bob.life) == (19, 21) else f"lives {alice.life}/{bob.life}"
    if kind == "coin_flip_damage_loop":
        return None if (alice.life, bob.life) == (19, 20) else f"lives {alice.life}/{bob.life}"
    name = instruction.kind
    creature = next((p for p in alice.battlefield if p.card.name != "Krark's Thumb"), None)
    if name == "coin_flip_remove_attacker_and_tap":
        return None if creature is not None and creature.tapped and not creature.attacking else "attacker stayed"
    return None if creature is not None and not creature.is_blocking else "blocker stayed"


def _not_yet_read(context, instruction) -> bool:
    """Whether nothing has read the flip yet: the record the site writes is
    absent while its keep is owed (CR 608.2)."""
    if context is None:
        return True
    if instruction.payload.get("flipper") == "each_player":
        return COIN_FACES_BY_SEAT not in context.results
    return "coin_flip" not in context.results


def unasked_sites(monkeypatch, *, asked=True) -> tuple[list[str], int]:
    """The census: ``(defects, cards driven)``."""
    defects: list[str] = []
    cards = set()
    for unit, instruction in flip_sites():
        cards.add(unit.name)
        label = f"{unit.name} [{instruction.kind} {dict(instruction.payload)}]"
        rig_coins(monkeypatch, _first_flip_coins(instruction))
        game, context, prompt = drive_site(unit, instruction, asked=asked)
        if prompt is None:
            defects.append(f"{label}: the Thumb's seat was not asked which coin to keep")
            continue
        if prompt.player_index != 0 or prompt.data.get("coins", [])[:2] not in (
            ["won", "lost"], ["heads", "tails"],
        ):
            defects.append(f"{label}: asked {prompt.player_index} about {prompt.data.get('coins')}")
            continue
        if not _not_yet_read(context, instruction):
            defects.append(f"{label}: the flip was read before the coin was kept")
            continue
        keep(game, 0, False)
        settle(game)
        wrong = _lost_was_kept(game, context, instruction)
        if wrong:
            defects.append(f"{label}: the kept loss was not what it went on with ({wrong})")
    return defects, len(cards)


def test_every_flip_site_asks_the_thumbs_seat_which_coin_to_keep(monkeypatch):
    defects, driven = unasked_sites(monkeypatch)
    assert driven >= _CARDS_FLOOR, driven
    assert defects == []


def test_with_nobody_asked_the_census_names_every_site(monkeypatch):
    """Backwards: the base kept the win at once and asked nobody; the census
    names every site it drives."""
    defects, driven = unasked_sites(monkeypatch, asked=False)
    assert driven >= _CARDS_FLOOR
    assert len(defects) == len(flip_sites())
    assert all("was not asked" in defect for defect in defects)


def test_every_coin_flipping_card_compiles_a_flip_site():
    """The table is the pool's: every card whose text has a player flip a
    coin compiles at least one :data:`FLIP_SITES` kind. The Thumb itself
    replaces flips and Chance Encounter hears them; neither flips."""
    examined, missing = 0, []
    for unit in compilation_units(load_catalog()):
        text = (unit.oracle_text or "").lower()
        if "flip" not in text or "coin" not in text:
            continue
        if "if you would flip a coin" in text or "whenever you win a coin flip" in text:
            continue
        examined += 1
        if not any(i.kind in FLIP_SITES for i in _program_instructions(unit)):
            missing.append(unit.name)
    assert examined >= _CARDS_FLOOR, examined
    assert missing == []


def _coin_calls():
    """``[(module, function, callee)]``: every call in ``engine/`` of the flip
    seam (``flip_coins_for``) or of a module's coin (``flip_coin``), named by
    the function it is made in."""
    import ast
    from pathlib import Path

    engine = Path(__file__).resolve().parents[2] / "engine"
    found = []
    for path in sorted(engine.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                callee = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if callee in ("flip_coins_for", "flip_coin"):
                    found.append((path.relative_to(engine).as_posix(), function.name, callee))
    return found


def test_every_flip_goes_through_the_one_question():
    """No flip reaches the coins except through ``coin_runs.flip_together``,
    which asks: the seam's one caller is that function, and no module calls a
    coin itself — each hands its ``flip_coin`` to the seam as *flip*."""
    calls = _coin_calls()
    assert calls == [("handlers/coin_runs.py", "flip_together", "flip_coins_for")], calls


# ---------------------------------------------------------------------------
# The boards the entry names
# ---------------------------------------------------------------------------


def _verdict(monkeypatch, *, interactive=(0,)):
    rig_coins(monkeypatch, [True, False])
    game = table(
        hand=("Puppet's Verdict",),
        mine=("Krark's Thumb", "Llanowar Elves", "Grizzly Bears"),
        theirs=("Craw Wurm",), interactive=interactive,
    )
    assert game.cast_from_hand(0, "Puppet's Verdict").supported
    return game


def _names(permanents) -> list[str]:
    return sorted(p.card.name for p in permanents)


def test_puppets_verdict_keeping_the_loss_destroys_the_big_creatures(monkeypatch):
    """The wave-1 probe's board: the caster keeps the lost coin, and "If you
    lose the flip, destroy all creatures with power 3 or greater" happens."""
    game = _verdict(monkeypatch)
    prompt = settle(game, defaults=False)
    assert prompt is not None and prompt.kind == "ignore_coin"
    assert prompt.data["coins"] == ["won", "lost"]
    assert prompt.data["ignored_by"] == ["Krark's Thumb"]
    # The spell waits on the stack for the answer (CR 608.2).
    assert [item.card.name for item in game.stack] == ["Puppet's Verdict"]
    assert game.waiting_prompt() is not None
    keep(game, 0, False)
    settle(game)
    assert _names(game.players[0].battlefield) == ["Grizzly Bears", "Krark's Thumb", "Llanowar Elves"]
    assert game.players[1].battlefield == []
    assert "Puppet's Verdict: Alice won 1 of 2 coins and keeps the loss (Krark's Thumb)" in game.log
    assert "Puppet's Verdict: lost the coin flip" in game.log


def test_puppets_verdict_keeping_the_win_destroys_the_small_ones(monkeypatch):
    game = _verdict(monkeypatch)
    keep(game, 0, True) if settle(game, defaults=False) else pytest.fail("not asked")
    settle(game)
    assert _names(game.players[0].battlefield) == ["Krark's Thumb"]
    assert _names(game.players[1].battlefield) == ["Craw Wurm"]
    assert "Puppet's Verdict: won the coin flip" in game.log


def test_a_seat_nobody_asks_keeps_the_win_as_it_always_did(monkeypatch):
    game = _verdict(monkeypatch, interactive=())
    assert settle(game, defaults=False) is None
    assert _names(game.players[0].battlefield) == ["Krark's Thumb"]
    assert "Puppet's Verdict: won the coin flip" in game.log


def test_coins_that_agree_ask_nothing(monkeypatch):
    rig_coins(monkeypatch, [False, False])
    game = table(hand=("Puppet's Verdict",), mine=("Krark's Thumb", "Llanowar Elves"),
                 theirs=("Craw Wurm",))
    game.cast_from_hand(0, "Puppet's Verdict")
    assert settle(game, defaults=False) is None
    assert game.players[1].battlefield == []


def test_an_answer_naming_a_result_no_coin_came_up_is_refused(monkeypatch):
    """The choice is among the coins, never of the outcome: a malformed
    answer leaves the prompt owed."""
    game = _verdict(monkeypatch)
    choice = settle(game, defaults=False)
    assert not game.resolve_pending_choice("ignore_coin", 0, keep="lost")
    assert owed_keeps(game) == [choice]


def test_the_win_is_announced_only_for_the_coin_kept(monkeypatch):
    """"Whenever you win a coin flip, put a luck counter" (Chance
    Encounter) hears the kept coin: a kept loss is no win, though one of the
    coins won (CR 705.2: only the flipper wins or loses)."""
    for won, counters in ((False, 0), (True, 1)):
        rig_coins(monkeypatch, [True, False])
        game = table(hand=("Puppet's Verdict",),
                     mine=("Krark's Thumb", "Chance Encounter"))
        game.cast_from_hand(0, "Puppet's Verdict")
        settle(game, defaults=False)
        keep(game, 0, won)
        settle(game)
        encounter = next(p for p in game.players[0].battlefield if p.card.name == "Chance Encounter")
        assert counters_on(encounter, "luck") == counters, won


def test_a_bounded_run_asks_at_each_flip_and_goes_on_from_the_answer(monkeypatch):
    """Squee's Revenge, three flips chosen: the first flip's win kept, the
    second's loss kept — the run stops there, asked twice mid-loop, and "if
    you win all the flips" reads the loss."""
    rig_coins(monkeypatch, [True, False, True, False])
    game = table(mine=("Krark's Thumb",))
    unit = card("Squee's Revenge")
    run = next(i for i in _program_instructions(unit) if i.kind == "flip_coins_until_loss")
    context = OracleExecutionContext(caster=game.players[0], target=game.players[1], card=unit)
    context.results[str(run.payload["amount_from"])] = 3
    game._execute_oracle_instruction(run, context)
    keep(game, 0, True)
    assert len(owed_keeps(game)) == 1, "the second flip was not asked"
    assert COIN_FLIPS_MADE not in context.results
    keep(game, 0, False)
    assert owed_keeps(game) == []
    assert (context.results["coin_flip"], context.results[COIN_FLIPS_MADE],
            context.results[COIN_FLIPS_WON]) == (False, 2, 1)
    assert "Squee's Revenge: 2 of 3 flip(s) made, the last one lost" in game.log


def test_crazed_firecat_counts_the_wins_kept(monkeypatch):
    """"Flip a coin until you lose a flip. Put a +1/+1 counter on this
    creature for each flip you won." Two wins kept, then a loss kept."""
    rig_coins(monkeypatch, [True, False] * 3)
    game = table(mine=("Krark's Thumb",), hand=("Crazed Firecat",))
    game.cast_from_hand(0, "Crazed Firecat")
    for answer in (True, True, False):
        prompt = settle(game, defaults=False)
        assert prompt is not None and prompt.kind == "ignore_coin"
        keep(game, 0, answer)
    settle(game)
    firecat = next(p for p in game.players[0].battlefield if p.card.name == "Crazed Firecat")
    assert counters_on(firecat, "+1/+1") == 2


def test_mana_clash_asks_each_round_and_deals_for_the_tails_kept(monkeypatch):
    """Round one: Alice's two coins are heads and tails, Bob's heads — she
    keeps tails and takes 1; round two both come up heads and it ends."""
    rig_coins(monkeypatch, [True, False, True])
    game = table(mine=("Krark's Thumb",), hand=("Mana Clash",))
    game.cast_from_hand(0, "Mana Clash", target_player_index=1)
    prompt = settle(game, defaults=False)
    assert prompt.kind == "ignore_coin" and prompt.data["wins"] is False
    assert prompt.data["coins"] == ["heads", "tails"]
    assert prompt.data["others"] == [{"seat": 1, "name": "Bob", "coins": ["heads"], "kept": "heads"}]
    keep(game, 0, False)
    settle(game)
    assert (game.players[0].life, game.players[1].life) == (19, 20)
    assert "Mana Clash: both coins came up heads after 2 flip(s)" in game.log


def test_two_thumbs_are_asked_in_turn_order_each_seeing_the_earlier_keep(monkeypatch):
    """"Each player flips a coin. Each player whose coin comes up tails
    sacrifices a creature" (Goblin Assassin) with a Thumb on each side: every
    coin is flipped first, then Alice (active) chooses, then Bob, who sees
    what she kept (CR 101.4, 101.4b)."""
    rig_coins(monkeypatch, [True, False, False, True])
    game = table(mine=("Krark's Thumb", "Llanowar Elves"),
                 theirs=("Krark's Thumb", "Grizzly Bears"), interactive=(0, 1))
    unit = card("Goblin Assassin")
    each = next(i for i in _program_instructions(unit)
                if i.kind == "flip_coin" and i.payload.get("flipper") == "each_player")
    context = OracleExecutionContext(caster=game.players[0], target=game.players[1], card=unit)
    game._execute_oracle_instruction(each, context)
    first = owed_keeps(game)
    assert [c.player_index for c in first] == [0]
    assert first[0].data["others"] == [
        {"seat": 1, "name": "Bob", "coins": ["tails", "heads"], "kept": None},
    ]
    keep(game, 0, False)
    second = owed_keeps(game)
    assert [c.player_index for c in second] == [1]
    assert second[0].data["others"] == [
        {"seat": 0, "name": "Alice", "coins": ["heads", "tails"], "kept": "tails"},
    ]
    keep(game, 1, True)
    assert context.results[COIN_FACES_BY_SEAT] == {0: "tails", 1: "heads"}


def test_mijae_djinn_keeping_the_loss_is_removed_from_combat_and_tapped(monkeypatch):
    rig_coins(monkeypatch, [True, False])
    game = table(mine=("Krark's Thumb", "Mijae Djinn"))
    attack_with(game, 0, "Mijae Djinn")
    prompt = settle(game, defaults=False)
    assert prompt is not None and prompt.kind == "ignore_coin"
    keep(game, 0, False)
    settle(game)
    djinn = next(p for p in game.players[0].battlefield if p.card.name == "Mijae Djinn")
    assert djinn.tapped and not djinn.attacking
    assert "Mijae Djinn lost the coin flip: removed from combat and tapped" in game.log


def test_fiery_gambit_asks_the_coin_then_the_next_flip(monkeypatch):
    """"Flip a coin until you lose a flip or choose to stop flipping." The
    keep comes first, then the offer to flip again (its ruling, 2004-12-01:
    "After each flip, you choose whether to continue flipping")."""
    rig_coins(monkeypatch, [True, False])
    game = table(mine=("Krark's Thumb", "Grizzly Bears"), hand=("Fiery Gambit",))
    bears = game.players[0].battlefield[1]
    game.cast_from_hand(0, "Fiery Gambit", target_permanent_index=1, target_player_index=0)
    prompt = settle(game, defaults=False)
    assert prompt is not None and prompt.kind == "ignore_coin"
    keep(game, 0, True)
    offer = settle(game, defaults=False)
    assert offer is not None and offer.kind == "flip_again"
    assert game.confirm_flip_again(0, False)
    settle(game)
    assert bears not in game.players[0].battlefield


def test_planar_chaos_asks_the_caster_and_counters_on_the_loss_kept(monkeypatch):
    """"Whenever a player casts a spell, **that player** flips a coin. If they
    lose the flip, counter that spell." The caster's own Thumb doubles the
    caster's flip: kept loss, the spell is countered; kept win, it resolves."""
    for won, countered in ((False, True), (True, False)):
        rig_coins(monkeypatch, [True, False])
        game = table(mine=("Krark's Thumb", "Planar Chaos"), hand=("Grizzly Bears",))
        game.cast_from_hand(0, "Grizzly Bears")
        prompt = settle(game, defaults=False)
        assert prompt is not None and prompt.kind == "ignore_coin", won
        keep(game, 0, won)
        settle(game)
        assert ("Grizzly Bears" in [c.name for c in game.players[0].graveyard]) is countered
        assert f"Planar Chaos: Alice {'won' if won else 'lost'} the coin flip" in game.log


def test_chaotic_goos_may_flip_asks_after_the_yes(monkeypatch):
    """"At the beginning of your upkeep, you may flip a coin. If you win the
    flip, put a +1/+1 counter on this creature. If you lose the flip, remove
    a +1/+1 counter." The offer, then the coin, then the counter the kept coin
    names — the "if" sentences wait for the keep."""
    for won, counters in ((False, 2), (True, 4)):
        rig_coins(monkeypatch, [True, False])
        game = table(mine=("Krark's Thumb",))
        goo = put(game, 0, "Chaotic Goo")
        unit = card("Chaotic Goo")
        upkeep = compile_card_oracle(unit).triggered_abilities[0]
        context = OracleExecutionContext(caster=game.players[0], target=game.players[1],
                                         card=unit, source_permanent=goo)
        game._execute_oracle_instruction(upkeep.instruction, context)
        assert game.confirm_optional_pay(0, accept=True)
        assert [c.kind for c in game.pending_choices] == ["ignore_coin"]
        assert counters_on(goo, "+1/+1") == 3
        keep(game, 0, won)
        settle(game)
        assert counters_on(goo, "+1/+1") == counters, won


def test_fighting_chance_asks_once_for_each_blocker_in_turn(monkeypatch):
    """"For each blocking creature, flip a coin. If you win the flip, prevent
    all combat damage that would be dealt by that creature this turn." Two
    blockers, two flips: the loop stops at each keep and goes on from it."""
    rig_coins(monkeypatch, [True, False, True, False])
    game = table(mine=("Krark's Thumb", "Llanowar Elves", "Llanowar Elves"),
                 theirs=("Grizzly Bears", "Grizzly Bears"))
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0, 1], defending_player_index=0)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(0, {1: 0, 2: 1})
    assert ok, why
    settle(game)
    unit = card("Fighting Chance")
    each = next(i for i in _program_instructions(unit) if i.kind == "for_each")
    context = OracleExecutionContext(caster=game.players[0], target=game.players[1], card=unit)
    game._execute_oracle_instruction(each, context)
    assert len(owed_keeps(game)) == 1
    keep(game, 0, True)
    assert len(owed_keeps(game)) == 1, "the second blocker's flip was not asked"
    keep(game, 0, False)
    assert owed_keeps(game) == []
    tail = game.log[game.log.index("Fighting Chance: won the coin flip"):]
    assert "Fighting Chance: lost the coin flip" in tail
    assert sum("is prevented (Fighting Chance)" in line for line in tail) == 1

"""A sweep whose payload is its own filter reaches both sides (SCG W2G3).

``ai_valuation.reaches_both_sides`` is what makes the main-phase ability
chooser rehearse an effect instead of scoring it flat (a flat 2.5 for any
"other" effect, read as aimed at an opponent). It read a sweep only where the
lowering nests the noun phrase under ``filter`` ("Return all …"); the four
sweeps whose lowering writes the phrase **flat in the payload**
(``tap_all_matching``, ``untap_all_matching``, ``destroy_all_matching``,
``exile_all_matching``) read as aimed, so Thundercloud Elemental's "{3}{U}:
Tap all creatures with toughness 2 or less" tapped its own controller's
Mercurial Kite in the main phase (W1G9, seeded games), and Kill Switch tapped
its controller's own artifacts with nothing of the opponent's to stop.

Validated backwards: on ``843cf32a`` the census names eighteen abilities
(W1G9's fourteen, less Samite Alchemist's targeted one, plus four its
``type_filter`` probe could not see: Apocalypse Chime, Hakim, Llanowar Druid
and Ugin) and both drives activate.
"""

from __future__ import annotations

from engine.ai_abilities import choose_activation_action
from engine.ai_valuation import _effect_steps, reaches_both_sides
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import _nosick

#: How many seatless flat sweeps the census must find: the base read
#: seventeen across both roles.
_FLAT_SWEEP_FLOOR = 14

#: The census's own reading of a flat noun phrase, kept apart from the
#: valuation's (``ai_valuation.SWEEP_CLASS_KEYS``) so that it judges it: the
#: keys that say what kind of permanent a phrase names, and the keys that put
#: a seat in it.
_CLASS_KEYS = frozenset({
    "type_filter", "subtype_filter", "color_filter", "colored_only",
    "original_expansion",
})
_SEAT_KEYS = frozenset({"controller", "owner", "owner_or_controller"})


def _seatless_flat_sweep(ability) -> bool:
    """Whether *ability* targets nothing (the targeting module's own answer,
    ``derive_activation_spec``) and some step of it names a class of
    permanent flat in its payload with no seat anywhere in it — "Tap all
    creatures without flying", "Destroy all other enchantments"."""
    if ability.instruction is None or derive_activation_spec(ability) is not None:
        return False
    for step in _effect_steps(ability.instruction):
        payload = step.payload or {}
        if (
            "filter" not in payload
            and _CLASS_KEYS & set(payload)
            and not _SEAT_KEYS & set(payload)
        ):
            return True
    return False


def test_every_seatless_flat_sweep_reads_as_reaching_both_sides(set_pool):
    pool = [*load_catalog(), *set_pool("SCG").values()]
    examined, read_aimed = [], []
    seen: set[str] = set()
    for card in pool:
        if card.name in seen:
            continue
        seen.add(card.name)
        for unit in compilation_units([card]):
            for ability in compile_card_oracle(unit).activated_abilities:
                if not _seatless_flat_sweep(ability):
                    continue
                examined.append(unit.name)
                if not reaches_both_sides(ability.instruction):
                    read_aimed.append(f"{unit.name}: {ability.source_line}")
    assert len(examined) >= _FLAT_SWEEP_FLOOR, examined
    assert not read_aimed, read_aimed


def test_a_flat_sweep_with_a_seat_in_it_is_still_aimed():
    """"{T}: Tap all lands you control" (Chimeric Idol's) and "Untap all
    creatures you control" (Aggravated Assault's) put a seat in the phrase."""
    for name in ("Chimeric Idol", "Aggravated Assault"):
        card = next(card for card in load_catalog() if card.name == name)
        abilities = compile_card_oracle(card).activated_abilities
        assert abilities and not any(
            reaches_both_sides(ability.instruction) for ability in abilities
        ), name


def _table(set_pool, own, other) -> Game:
    pool = {**{card.name: card for card in load_catalog()}, **set_pool("SCG")}
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat, names in ((0, own), (1, other)):
        for name in names:
            game.players[seat].battlefield.append(_nosick(Permanent(card=pool[name])))
        game.players[seat].library = [pool["Island"]] * 10
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(0)
    return game


def test_thundercloud_elemental_does_not_tap_its_own_kite_for_nothing(set_pool):
    """Only seat 0's Mercurial Kite (a 2/1) has toughness 2 or less: the sweep
    taps nothing but the seat's own flier, and is not activated."""
    game = _table(
        set_pool,
        ["Thundercloud Elemental", "Mercurial Kite", *["Island"] * 4],
        ["Hill Giant"],
    )
    assert choose_activation_action(game, 0) is None


def test_thundercloud_elemental_still_taps_the_blockers_in_its_way(set_pool):
    """The same sweep over three small blockers of the opponent's and nothing
    small of its own is a sweep worth making before the attack."""
    game = _table(
        set_pool,
        ["Thundercloud Elemental", "Hill Giant", *["Island"] * 4],
        ["Llanowar Elves", "Grizzly Bears", "Grizzly Bears"],
    )
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Thundercloud Elemental"


def test_kill_switch_does_not_tap_only_its_own_artifacts(set_pool):
    game = _table(
        set_pool,
        ["Kill Switch", "Ornithopter", "Ornithopter", "Island", "Island"],
        ["Grizzly Bears"],
    )
    assert choose_activation_action(game, 0) is None

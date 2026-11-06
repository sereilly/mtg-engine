"""Every price the wire shows a caster is the price the payment takes
(SCG Phase 5, C3).

Under Goblin Warchief ("Goblin spells you cast cost {1} less to cast"), Goblin
Brigand's hand badge — ``effective_mana_cost`` — read ``{1}{R}`` while the
payment asked for ``{R}``. The badge folded in the cost **increases** alone
(``spell_cost_tax``): every reduction was paid and never shown, and a
flashback card's graveyard badge missed a coloured tax and a board reduction.

**The census is every cost-modifier source in the pool** (each card a
"… spells cost {N} more / less to cast" line of which the cast path reads,
``cost_modifier_lines.cost_modifiers_for``), on either seat's battlefield,
against the spells it changes the price of — and one it does not — with the
hand badge (``web/serialization._serialize_card``) asked beside what the cast
path actually takes out of a full mana pool. The modifier families: a type
(the Warchiefs), a colour (the Medallions), a mana value (Krosan Drover), a
coloured-only reduction (Edgewalker), a generic tax (Gloom, Sphere of
Resistance) and a coloured one (Derelor). A zone cast's price (a flashback
card's badge, and ``ways``' price in ``castable_from_zones``) is asked for a
flashback spell under every one.
"""

from __future__ import annotations

import copy

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.cost_modifier_lines import cost_modifiers_for
from engine.cost_modifiers import cost_reduction_for_cast, spell_cost_tax, spell_symbol_tax
from engine.faces import compilation_units, face_cards
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from tests.helpers import stable_sample
from web.serialization import _serialize_card

_POOL = {card.name: card for card in load_catalog()}
_SYMBOLS = ("W", "U", "B", "R", "G", "C")
#: Flashback spells that name no target, for the graveyard price.
_FLASHBACK_PROBES = ("Call of the Herd", "Moment's Peace")
#: The pool's cost-modifier sources measured on this tree; a floor, so a
#: census that stopped finding them fails rather than passing over nothing.
_SOURCE_FLOOR = 40


def _sources() -> list[str]:
    return sorted({
        card.name for card in compilation_units(_POOL.values())
        if any(modifier.applies_to == "cast" for modifier in cost_modifiers_for(card.oracle_text or ""))
        and card.primary_type != "instant" and card.primary_type != "sorcery"
    })


def _probe_candidates() -> list:
    """Spells a census can cast with no answer owed: no target, no X, no
    additional or alternative cost, one face."""
    found = []
    for card in sorted(_POOL.values(), key=lambda c: c.name):
        text = (card.oracle_text or "").lower()
        if (
            card.primary_type in ("land",)
            or face_cards(card)
            or not card.mana_cost
            or "{x}" in card.mana_cost.lower()
            or "additional cost" in text
            or "rather than pay" in text
            or "aura" in card.type_line.lower()
            or "target" in text.split("\n")[0] and card.primary_type in ("instant", "sorcery")
        ):
            continue
        program = compile_card_oracle(card)
        if not program.supported or derive_cast_spec(card, program) is not None:
            continue
        found.append(card)
    return found


_CANDIDATES = _probe_candidates()


def _table(source: str, source_seat: int, caster: int) -> Game:
    library = [_POOL["Island"]] * 10
    game = Game(players=[
        PlayerState(name="P0", library=list(library)),
        PlayerState(name="P1", library=list(library)),
    ])
    game.enforce_mana_costs = True
    game.turn = 3
    game.active_player_index = caster
    game._set_phase_and_step("precombat_main", "precombat_main")
    permanent = Permanent(card=_POOL[source])
    game._put_permanent_onto_battlefield(source_seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.start_priority_window(caster)
    return game


def _moved(game: Game, caster: int, card) -> bool:
    return bool(
        spell_cost_tax(game, caster, card)[0]
        or any(spell_symbol_tax(game, caster, card)[0].values())
        or cost_reduction_for_cast(game, caster, card)[0]
    )


def _spent(game: Game, caster: int, card, *, from_graveyard: bool = False) -> dict | None:
    """What the cast path takes out of a pool of ten of every mana, on a copy
    of *game*: ``{symbol: count}``, or None when the cast was refused."""
    table = copy.deepcopy(game)
    player = table.players[caster]
    player.mana_pool = {symbol: 10 for symbol in _SYMBOLS}
    if from_graveyard:
        player.graveyard = [card]
        result = table.queue_from_hand(caster, card.name, from_zone="graveyard")
    else:
        player.hand = [card]
        result = table.queue_from_hand(caster, card.name)
    if not result.supported:
        return None
    return {symbol: 10 - player.mana_pool.get(symbol, 0) for symbol in _SYMBOLS}


def _pips(label: str) -> tuple[int, dict]:
    """``(total mana, coloured pips)`` of a printed cost string."""
    import re

    total = 0
    pips: dict = {}
    for token in re.findall(r"\{([^}]+)\}", label or ""):
        if token.isdigit():
            total += int(token)
        elif token != "X":
            total += 1
            pips[token] = pips.get(token, 0) + 1
    return total, pips


def _disagrees(label: str, spent: dict) -> bool:
    total, pips = _pips(label)
    if total != sum(spent.values()):
        return True
    return any(spent.get(symbol, 0) < count for symbol, count in pips.items())


def _rows():
    rows = []
    for source in _sources():
        for source_seat in (0, 1):
            rows.append((source, source_seat))
    return rows


@pytest.mark.full
def test_every_hand_badge_is_the_price_the_cast_pays():
    sources = _sources()
    assert len(sources) >= _SOURCE_FLOOR, len(sources)
    wrong: list[str] = []
    asked = moved = 0
    for source, source_seat in _rows():
        caster = 0
        game = _table(source, source_seat, caster)
        affected = [card for card in _CANDIDATES if _moved(game, caster, card)][:3]
        unaffected = next((card for card in _CANDIDATES if not _moved(game, caster, card)), None)
        for card in affected + ([unaffected] if unaffected is not None else []):
            spent = _spent(game, caster, card)
            if spent is None:
                continue
            asked += 1
            moved += card in affected
            badge = _serialize_card(card, game, caster)["effective_mana_cost"]
            if _disagrees(badge, spent):
                wrong.append(f"{source} (seat {source_seat}) / {card.name}: badge {badge}, paid {spent}")
    assert asked >= 100 and moved >= 40, (asked, moved)
    assert not wrong, "\n".join(wrong)


def test_the_badge_reads_every_reduction_family():
    """The quick pass's rows: one source per family, both seats."""
    wrong: list[str] = []
    for source, probe in (
        ("Goblin Warchief", "Goblin Brigand"),     # a creature type
        ("Pearl Medallion", "Serra Angel"),        # a colour
        ("Krosan Drover", "Craw Wurm"),            # a mana value
        ("Edgewalker", "Daru Healer"),             # a coloured-only reduction
        ("Gloom", "Serra Angel"),                  # a generic tax
        ("Sphere of Resistance", "Grizzly Bears"),  # a tax on every spell
    ):
        for caster in (0, 1):
            game = _table(source, 0, caster)
            card = _POOL[probe]
            spent = _spent(game, caster, card)
            assert spent is not None, (source, probe, caster)
            badge = _serialize_card(card, game, caster)["effective_mana_cost"]
            if _disagrees(badge, spent):
                wrong.append(f"{source} / {probe} (caster {caster}): badge {badge}, paid {spent}")
    assert not wrong, "\n".join(wrong)


@pytest.mark.parametrize("probe", _FLASHBACK_PROBES)
def test_a_flashback_price_is_what_its_cast_pays_under_every_source(probe):
    """The graveyard badge of a flashback spell (CR 118.9d: the increases and
    reductions apply to the flashback cost too) under every modifier source
    that moves it, sampled in the quick pass."""
    from web.state_view import _zone_cast_price
    from engine.cast_permissions import permission_for

    card = _POOL[probe]
    wrong: list[str] = []
    asked = 0
    for source, source_seat in _rows():
        if not stable_sample(f"{probe}/{source}/{source_seat}", 4):
            continue
        game = _table(source, source_seat, 0)
        game.players[0].graveyard = [card]
        spent = _spent(game, 0, card, from_graveyard=True)
        if spent is None:
            continue
        asked += 1
        badge = _serialize_card(card, game, 0, from_zone="graveyard")["effective_mana_cost"]
        permission = permission_for(game, 0, card, "graveyard")
        price = _zone_cast_price(game, 0, card, permission)
        for name, label in (("badge", badge), ("ways price", price)):
            if _disagrees(label, spent):
                wrong.append(f"{source} (seat {source_seat}) / {probe} {name} {label}, paid {spent}")
    assert asked >= 5, asked
    assert not wrong, "\n".join(wrong)

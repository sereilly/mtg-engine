"""Urza's Destiny creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: eight new trigger conditions and what announces them ---
import pytest

from engine import Game
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack


def _g4_card(name: str, type_line: str = "Creature - Test", power="1", toughness="1",
             oracle_text: str = "", colors=()) -> CardDefinition:
    """A plain fixture card, with a colour and a printed type line together."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=colors, color_identity=colors,
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": power, "toughness": toughness},
    )


def _g4_duel(library: int = 9) -> Game:
    """Two seats with stocked libraries and mana enforcement off."""
    seats = [
        PlayerState(name=name,
                    library=[_g4_card(f"{name}-lib{i}") for i in range(library)],
                    hand=[], battlefield=[])
        for name in ("A", "B")
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    return game


def _g4_settle(game: Game, *, accept: bool = True) -> None:
    """Resolve the stack and answer every optional offer it queues.

    A "may" is answered by a prompt on the pending-choice queue (CR 603.5: the
    choice is made as the ability resolves), and answering one can arm another —
    Rayne's second sentence is a second offer behind the first. So this
    alternates rather than draining once, and it is bounded rather than a
    ``while``, which is the hazard ``resolve_stack`` documents.
    """
    for _ in range(8):
        resolve_stack(game)
        owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
        if not owed:
            return
        for choice in owed:
            game.resolve_pending_choice(
                choice.kind, choice.player_index, accept=accept
            )


def _g4_uds(set_pool, name: str) -> CardDefinition:
    return set_pool("UDS")[name]


@pytest.mark.parametrize("name", [
    "Goblin Marshal", "Hunting Moa", "Phyrexian Negator",
    "Telepathic Spies", "Rayne, Academy Chancellor",
])
def test_w1g4_creatures_compile_supported(set_pool, name):
    assert compile_card_oracle(_g4_uds(set_pool, name)).supported


def test_goblin_marshal_makes_goblins_when_it_enters(set_pool):
    game = _g4_duel()
    marshal = Permanent(card=_g4_uds(set_pool, "Goblin Marshal"))
    game._put_permanent_onto_battlefield(0, marshal, None)
    _g4_settle(game)
    tokens = [p for p in list(game.controlled_by(0)) if p.card.name == "Goblin Token"]
    assert len(tokens) == 2


def test_goblin_marshal_makes_goblins_when_it_dies(set_pool):
    """The **other** half of one printed condition (CR 603.1b).

    The entry half is carried out inline and this half goes on the stack
    (CR 603.3), which is why ``enters_or_dies`` is one kind named at two fire
    sites rather than a compiler alias for either one.
    """
    game = _g4_duel()
    marshal = Permanent(card=_g4_uds(set_pool, "Goblin Marshal"))
    game.players[0].battlefield.append(marshal)
    game._sync_control()
    game._permanent_to_graveyard(game.players[0], marshal)
    _g4_settle(game)
    tokens = [p for p in list(game.controlled_by(0)) if p.card.name == "Goblin Token"]
    assert len(tokens) == 2


@pytest.mark.parametrize("half", ["enters", "dies"])
def test_hunting_moa_counters_a_creature_on_both_halves(set_pool, half):
    game = _g4_duel()
    bear = Permanent(card=_g4_card("G4 Bear"))
    game.players[0].battlefield.append(bear)
    game._sync_control()
    moa = Permanent(card=_g4_uds(set_pool, "Hunting Moa"))
    if half == "enters":
        game._put_permanent_onto_battlefield(0, moa, 0)
    else:
        game.players[0].battlefield.append(moa)
        game._sync_control()
        game._permanent_to_graveyard(game.players[0], moa)
    _g4_settle(game)
    assert bear.metadata.get("plus_counters") == 1


@pytest.mark.parametrize("dealt,expected", [(1, 1), (2, 2), (3, 3)])
def test_phyrexian_negator_sacrifices_that_many(set_pool, dealt, expected):
    """"…sacrifice **that many** permanents" is the damage the event carried.

    Parametrized over three amounts because the whole claim is that the number
    is the event's rather than a printed one: a lowering that emitted a fixed
    count would pass at exactly one of these.
    """
    game = _g4_duel()
    negator = Permanent(card=_g4_uds(set_pool, "Phyrexian Negator"))
    game.players[0].battlefield.append(negator)
    for index in range(5):
        game.players[0].battlefield.append(Permanent(card=_g4_card(f"G4 Chaff{index}")))
    game._sync_control()
    before = len(list(game.controlled_by(0)))
    game._fire_dealt_damage_triggers(negator, dealt)
    for _ in range(10):
        resolve_stack(game)
        if not game.pending_choices:
            break
        game.auto_resolve_pending_choices()
    assert before - len(list(game.controlled_by(0))) == expected


def test_telepathic_spies_reads_an_opponents_hand(set_pool):
    game = _g4_duel()
    game.players[1].hand.extend([_g4_card("G4 Held1"), _g4_card("G4 Held2")])
    spies = Permanent(card=_g4_uds(set_pool, "Telepathic Spies"))
    game._put_permanent_onto_battlefield(0, spies, 1)
    _g4_settle(game)
    reveal = next(c for c in game.pending_choices if c.kind == "hand_reveal")
    assert reveal.player_index == 0
    assert reveal.data["target_index"] == 1
    assert sorted(reveal.data["card_names"]) == ["G4 Held1", "G4 Held2"]


def test_telepathic_spies_carries_the_opponent_only_narrowing(set_pool):
    """CR 115.4 through the payload: "target **opponent**" carries
    ``opponents_only``, and the picker is what refuses the caster's own seat.

    The lowering that admits the word is only correct because the flag survives
    into the payload — a reading that dropped it would offer the caster their
    own hand, which is the failure the old refusal stood in for.
    """
    program = compile_card_oracle(_g4_uds(set_pool, "Telepathic Spies"))
    instruction = program.triggered_abilities[0].instruction
    assert instruction.payload["targets"]["opponents_only"] is True


def _g4_rayne_board(set_pool, *, enchanted: bool = False):
    game = _g4_duel()
    rayne = Permanent(card=_g4_uds(set_pool, "Rayne, Academy Chancellor"))
    game.players[0].battlefield.append(rayne)
    if enchanted:
        aura = Permanent(card=_g4_card("G4 Aura", "Enchantment - Aura",
                                       oracle_text="Enchant creature"))
        game.players[0].battlefield.append(aura)
        attach_aura(aura, rayne)
    game._sync_control()
    return game, rayne


_G4_BOLT = "G4 Bolt deals 3 damage to target player."
_G4_ZAP = "G4 Zap deals 2 damage to target creature."


def test_rayne_draws_when_an_opponent_targets_you(set_pool):
    """The **player** half of CR 603.2's "becomes the target of".

    Nothing announced a targeted seat before this card: the targeting
    announcement looped permanents alone, so the condition could compile
    perfectly and never fire on half of what it names.
    """
    game, _rayne = _g4_rayne_board(set_pool)
    game.players[1].hand.append(_g4_card("G4 Bolt", "Instant", oracle_text=_G4_BOLT))
    before = len(game.players[0].hand)
    game.cast_from_hand(1, "G4 Bolt", target_player_index=0)
    _g4_settle(game)
    assert len(game.players[0].hand) - before == 1


def test_rayne_draws_when_an_opponent_targets_your_permanent(set_pool):
    game, _rayne = _g4_rayne_board(set_pool)
    bear = Permanent(card=_g4_card("G4 Bear"))
    game.players[0].battlefield.append(bear)
    game._sync_control()
    game.players[1].hand.append(_g4_card("G4 Zap", "Instant", oracle_text=_G4_ZAP))
    before = len(game.players[0].hand)
    game.cast_from_hand(
        1, "G4 Zap", target_player_index=0,
        target_permanent_index=game.players[0].battlefield.index(bear),
    )
    _g4_settle(game)
    assert len(game.players[0].hand) - before == 1


def test_rayne_ignores_a_spell_its_own_controller_cast(set_pool):
    """"…an **opponent** controls" (CR 109.5). Dropped, Rayne would draw off
    every spell its controller aimed at their own board."""
    game, _rayne = _g4_rayne_board(set_pool)
    bear = Permanent(card=_g4_card("G4 Bear"))
    game.players[0].battlefield.append(bear)
    game._sync_control()
    game.players[0].hand.append(_g4_card("G4 Zap", "Instant", oracle_text=_G4_ZAP))
    before = len(game.players[0].hand)
    game.cast_from_hand(
        0, "G4 Zap", target_player_index=0,
        target_permanent_index=game.players[0].battlefield.index(bear),
    )
    _g4_settle(game)
    # One card left the hand to be cast and none was drawn.
    assert len(game.players[0].hand) == before - 1


def test_rayne_ignores_an_opponent_targeting_their_own_permanent(set_pool):
    """"…**you or a permanent you control**". The seat narrowing is on the
    *targeted* object, not on the spell alone."""
    game, _rayne = _g4_rayne_board(set_pool)
    bear = Permanent(card=_g4_card("G4 Bear"))
    game.players[1].battlefield.append(bear)
    game._sync_control()
    game.players[1].hand.append(_g4_card("G4 Zap", "Instant", oracle_text=_G4_ZAP))
    before = len(game.players[0].hand)
    game.cast_from_hand(
        1, "G4 Zap", target_player_index=1,
        target_permanent_index=game.players[1].battlefield.index(bear),
    )
    _g4_settle(game)
    assert len(game.players[0].hand) == before


def test_rayne_draws_a_second_card_while_enchanted(set_pool):
    """CR 303.4b: the permanent an Aura is attached to is *enchanted*."""
    game, _rayne = _g4_rayne_board(set_pool, enchanted=True)
    game.players[1].hand.append(_g4_card("G4 Bolt", "Instant", oracle_text=_G4_BOLT))
    before = len(game.players[0].hand)
    game.cast_from_hand(1, "G4 Bolt", target_player_index=0)
    _g4_settle(game)
    assert len(game.players[0].hand) - before == 2


def test_rayne_draws_nothing_when_the_offer_is_declined(set_pool):
    """CR 603.5: the ability triggers and goes on the stack either way; the
    choice belongs to the resolution."""
    game, _rayne = _g4_rayne_board(set_pool, enchanted=True)
    game.players[1].hand.append(_g4_card("G4 Bolt", "Instant", oracle_text=_G4_BOLT))
    before = len(game.players[0].hand)
    game.cast_from_hand(1, "G4 Bolt", target_player_index=0)
    _g4_settle(game, accept=False)
    assert len(game.players[0].hand) == before

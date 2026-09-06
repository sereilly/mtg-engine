"""Tempest instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G5: Interdict counters an ability and shuts the permanent down ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.spell_prohibitions import clear_turn_spell_prohibitions
from engine.targeting import derive_cast_spec

_W1G5_PINGER = "{T}: This creature deals 1 damage to any target."


def _w1g5i_pinger(name):
    raw = {"name": name, "type_line": "Creature — Wizard", "power": "1", "toughness": "1"}
    return CardDefinition(
        name=name, mana_cost="", type_line="Creature — Wizard",
        oracle_text=_W1G5_PINGER, cmc=0.0, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw=raw, power="1", toughness="1",
    )


def _w1g5i_board(set_pool):
    pinger = Permanent(card=_w1g5i_pinger("Pinger"))
    spare = Permanent(card=_w1g5i_pinger("Spare"))
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("TMP")["Interdict"]]),
        PlayerState(name="P2", battlefield=[pinger, spare]),
    ])
    game.enforce_mana_costs = False
    game._settle()
    for permanent in (pinger, spare):
        permanent.metadata["summoning_sickness_turn"] = -99
    return game, pinger, spare


def test_w1g5_interdict_counters_an_ability_and_bans_its_source(set_pool):
    """"Counter target activated ability from an artifact, creature,
    enchantment, or land. That permanent's activated abilities can't be
    activated this turn."

    Both sentences, because either alone is a card doing half its job: the
    counter is what the spell targets, and the ban is a *back-reference* to the
    permanent behind the ability — an object nothing else can name once the
    ability has left the stack (CR 113.7a).

    The spare permanent is the narrowing: CR 602.5c bans one permanent's
    abilities, not its controller's, and a ban recorded per seat would shut
    that one down too.
    """
    game, pinger, _spare = _w1g5i_board(set_pool)

    assert game.queue_permanent_ability(
        1, "Pinger", ability_index=0, target_player_index=0,
    ).supported
    assert len(game.stack) == 1

    result = game.cast_from_hand(0, "Interdict", target_stack_index=0)
    assert result.supported, result.details
    while game.stack:
        game.resolve_top_of_stack()

    assert game.players[0].life == 20, "the ability was countered"

    pinger.tapped = False
    refused = game.activate_permanent_ability(
        1, "Pinger", ability_index=0, target_player_index=0,
    )
    assert not refused.supported, "the source is shut down for the turn"

    allowed = game.activate_permanent_ability(
        1, "Spare", permanent_index=1, ability_index=0, target_player_index=0,
    )
    assert allowed.supported, "only that permanent, not its controller"


def test_w1g5_interdicts_ban_ends_with_the_turn(set_pool):
    """"…this turn." The record is armed on the game and dropped at the turn
    boundary, which is the whole reason the lowering refuses any other window:
    a longer one would be a ban nothing lifts."""
    game, pinger, _spare = _w1g5i_board(set_pool)

    assert game.queue_permanent_ability(
        1, "Pinger", ability_index=0, target_player_index=0,
    ).supported
    game.cast_from_hand(0, "Interdict", target_stack_index=0)
    while game.stack:
        game.resolve_top_of_stack()

    clear_turn_spell_prohibitions(game)
    pinger.tapped = False
    assert game.activate_permanent_ability(
        1, "Pinger", ability_index=0, target_player_index=0,
    ).supported, game.log


def test_w1g5_interdict_offers_a_picker_over_the_four_printed_types(set_pool):
    """`picker_sweep`'s Roots-class finding: the text names a choice and the
    derivation offered none, so the client sent a bare cast the engine then
    refused. All four printed types ride the spec — a list read as one type
    would offer the caster fewer abilities than the card admits."""
    card = set_pool("TMP")["Interdict"]
    spec = derive_cast_spec(card, compile_card_oracle(card))
    assert spec == {
        "kind": "stack",
        "stack_ability_kinds": ["activated"],
        "stack_ability_source_types": ["artifact", "creature", "enchantment", "land"],
    }

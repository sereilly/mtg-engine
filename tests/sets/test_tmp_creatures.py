"""Tempest creatures.

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


# --- W1G5: the tuck, all three printed subjects ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g5c_card(name, type_line, text="", power=None, toughness=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text=text,
        cmc=0.0, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw=raw,
        power=str(power) if power is not None else None,
        toughness=str(toughness) if toughness is not None else None,
    )


def _w1g5c_game(mine, theirs):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game._settle()
    for permanent in list(mine) + list(theirs):
        permanent.metadata["summoning_sickness_turn"] = -99
    return game


def test_w1g5_a_creature_tucks_itself_off_the_battlefield():
    """"{U}: Put this creature on top of its owner's library." (Thalakos
    Mistfolk.)

    Tested on an invented card carrying only that line, deliberately: Mistfolk
    itself is unsupported until *shadow* lands (W1G1), and a test that waited
    for the other half would be testing two things. What this asserts is the
    tuck's own subject — the source, which is not a target and must not reach
    the picker.
    """
    probe = Permanent(card=_w1g5c_card(
        "Mistfolk Probe", "Creature — Illusion",
        "{U}: Put this creature on top of its owner's library.",
        power=1, toughness=1,
    ))
    game = _w1g5c_game([probe], [])

    result = game.activate_permanent_ability(0, "Mistfolk Probe", ability_index=0)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert list(game.controlled_by(0)) == []
    assert [card.name for card in game.players[0].library] == ["Mistfolk Probe"]


def test_w1g5_avenging_angel_may_tuck_itself_out_of_the_graveyard(set_pool):
    """"When this creature dies, you may put it on top of its owner's library."

    The same *subject* as Mistfolk's — the noun parser marks the pronoun
    ``is_source`` — reached from a different zone: a dies trigger resolves with
    the card already in a graveyard (CR 404.1), so a handler that looked only
    at the battlefield would silently do nothing here.
    """
    angel = Permanent(card=set_pool("TMP")["Avenging Angel"])
    game = _w1g5c_game([angel], [])

    angel.damage_marked = 99
    game.check_state_based_actions()
    assert [card.name for card in game.players[0].graveyard] == ["Avenging Angel"]
    while game.stack:
        game.resolve_top_of_stack()

    assert game.confirm_optional_pay(0, accept=True)
    assert game.players[0].graveyard == [], game.log
    assert [card.name for card in game.players[0].library] == ["Avenging Angel"]


def test_w1g5_avenging_angel_declined_stays_in_the_graveyard(set_pool):
    """The offer is a "may" and both branches are real. A card that always
    tucked would report exactly the same instruction."""
    angel = Permanent(card=set_pool("TMP")["Avenging Angel"])
    game = _w1g5c_game([angel], [])

    angel.damage_marked = 99
    game.check_state_based_actions()
    while game.stack:
        game.resolve_top_of_stack()

    assert game.confirm_optional_pay(0, accept=False)
    assert [card.name for card in game.players[0].graveyard] == ["Avenging Angel"]
    assert game.players[0].library == []


def test_w1g5_elven_warhounds_tucks_the_creature_that_blocked_it(set_pool):
    """"Whenever this creature becomes blocked by a creature, put that creature
    on top of its owner's library."

    The third subject: the other half of the pair the trigger bound, which is
    neither the source nor a target. The blocker goes to **its owner's**
    library (CR 400.3), not the ability controller's — the assertion that would
    fail if the tuck read the wrong seat.
    """
    hounds = Permanent(card=set_pool("TMP")["Elven Warhounds"])
    blocker = Permanent(card=_w1g5c_card(
        "Bear", "Creature — Bear", power=2, toughness=2,
    ))
    game = _w1g5c_game([hounds], [blocker])
    game.active_player_index = 0

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: [0]})[0]
    while game.stack:
        game.resolve_top_of_stack()

    assert list(game.controlled_by(1)) == [], game.log
    assert [card.name for card in game.players[1].library] == ["Bear"]
    assert game.players[0].library == [], "the blocker's owner, not the tucker's"


def test_w1g5_a_bare_becomes_blocked_trigger_refuses_the_tuck():
    """CR 509.3c/509.3d. "Becomes blocked" with no noun phrase fires **once**
    however many creatures blocked, so "that creature" names no one of them —
    and the fire site would hand over an arbitrary blocker. The narrowed
    spelling Elven Warhounds prints is what makes the pronoun answerable, so
    the unnarrowed one refuses rather than tucking whichever creature came
    first.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability
    import pytest as _pytest

    node = parse_line(
        "Whenever this creature becomes blocked, put that creature on top of "
        "its owner's library."
    )
    with _pytest.raises(LoweringError):
        lower_ability(node)

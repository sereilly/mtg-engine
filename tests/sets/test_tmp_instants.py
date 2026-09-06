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


# --- W1G1: shadow (CR 702.28) ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def _w1g1_cast(spell, caster_board, opponent_board, *, target_index):
    """Cast *spell* from hand at ``caster_board[target_index]`` and resolve it."""
    p0 = PlayerState(
        name="P0",
        battlefield=[_nosick(Permanent(card=c)) for c in caster_board],
        life=20, hand=[spell], library=[spell] * 3,
    )
    p1 = PlayerState(
        name="P1",
        battlefield=[_nosick(Permanent(card=c)) for c in opponent_board],
        life=20,
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    game.cast_from_hand(
        0, spell.name, target_permanent_index=target_index, target_player_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    return game, p0, p1


def test_w1g1_shadow_rift_grants_shadow_and_draws(set_pool):
    """"Target creature gains shadow until end of turn. Draw a card."

    Shadow Rift **compiled and reported supported before this round**, on its
    second sentence alone: the grant produced no instruction at all, so the card
    drew a card and did nothing else, and `picker_sweep` reported it as the
    Roots class because a program with no targeting instruction derives no cast
    picker. That was one failure with two symptoms, not two failures — the
    picker finding cleared the moment the grant lowered.

    Driven through a game rather than asserted off the program for that exact
    reason: the compiled instruction is what was missing, and asserting its
    presence is a weaker claim than asserting the block it changes.
    """
    tmp = set_pool("TMP")
    rift = tmp["Shadow Rift"]
    assert [i.kind for i in compile_card_oracle(rift).instructions] == [
        "grant_target_keyword_until_eot", "draw_controller_cards",
    ]

    game, p0, p1 = _w1g1_cast(
        rift, [tmp["Trained Armodon"]], [tmp["Trained Armodon"]], target_index=0
    )
    attacker = p0.battlefield[0]
    blocker = p1.battlefield[0]

    assert game._has_keyword(attacker, "shadow")
    assert not game._can_block_attacker(blocker, attacker)
    assert len(p0.hand) == 1, "the second sentence still draws"


def test_w1g1_reality_anchor_takes_shadow_away(set_pool):
    """"Target creature loses shadow until end of turn. Draw a card."

    The mirror of Shadow Rift and the same pre-round defect: supported on the
    draw, the removal producing nothing. Aimed at a *printed* shadow creature,
    because that is the use the card is printed for — the Soltari attacker is
    made blockable, which is a change no assertion about the instruction list
    would have caught if the layer-6 removal had failed to reach the block gate.
    """
    tmp = set_pool("TMP")
    anchor = tmp["Reality Anchor"]
    assert [i.kind for i in compile_card_oracle(anchor).instructions] == [
        "remove_target_keyword_until_eot", "draw_controller_cards",
    ]

    game, p0, p1 = _w1g1_cast(
        anchor, [tmp["Soltari Foot Soldier"]], [tmp["Trained Armodon"]],
        target_index=0,
    )
    attacker = p0.battlefield[0]
    blocker = p1.battlefield[0]

    assert not game._has_keyword(attacker, "shadow")
    assert game._can_block_attacker(blocker, attacker)
    assert len(p0.hand) == 1


def test_w1g1_reality_anchor_also_frees_a_shadow_creature_to_block(set_pool):
    """The *other* half of what Reality Anchor does, which is the half CR
    702.28b's second prohibition creates.

    Losing shadow does not only make a creature blockable; it makes it able to
    block. An engine that implemented shadow as one-way evasion would pass the
    test above and fail this one, and the card would be doing half its job with
    nothing red.
    """
    tmp = set_pool("TMP")
    game, p0, p1 = _w1g1_cast(
        tmp["Reality Anchor"], [tmp["Soltari Foot Soldier"]],
        [tmp["Trained Armodon"]], target_index=0,
    )
    soltari = p0.battlefield[0]
    ordinary_attacker = p1.battlefield[0]

    assert game._can_block_attacker(soltari, ordinary_attacker)

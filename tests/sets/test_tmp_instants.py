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


# --- W1G1: the removal handler's missing noun phrase ---


def test_w1g1_reality_anchor_will_not_strip_a_noncreature(set_pool):
    """Found by driving eight AI games, not by any census.

    `remove_target_keyword_until_eot` resolved with `predicate=lambda p: True`
    — "the damage target may be a planeswalker, so no creature predicate" — and
    read the printed noun phrase not at all. So when the AI named a *player*
    where the spell wants a creature, the fallback scan took whatever permanent
    it reached first and **Reality Anchor stripped shadow from a Circle of
    Protection**. Its grant twin was fixed for exactly this a set earlier and
    has `granted_target_legal`; the removal twin kept its own reading, which is
    the "two handlers for one printed sentence" shape that helper's docstring
    is about.

    Two rigs, because the fallback scan is legitimate and only its *blindness*
    was the bug: with a legal creature on the board the scan should find it,
    and with none it should find nothing rather than settle for an enchantment.
    The illegal permanent is placed **first** in both, so a scan that ignores
    the phrase reaches it before anything else.
    """
    tmp = set_pool("TMP")

    def cast_with_no_permanent_named(battlefield):
        p0 = PlayerState(
            name="P0",
            battlefield=[_nosick(Permanent(card=tmp[name])) for name in battlefield],
            life=20, hand=[tmp["Reality Anchor"]],
            library=[tmp["Trained Armodon"]] * 4,
        )
        game = Game(players=[p0, PlayerState(name="P1", life=20)])
        game.enforce_mana_costs = False
        game._sync_control()
        # The shape the AI produced: a player named, no permanent.
        game.cast_from_hand(0, "Reality Anchor", target_player_index=0)
        while game.stack:
            game.resolve_top_of_stack()
        return game, p0

    # No creature at all: the enchantment must not be taken as a substitute.
    game, _ = cast_with_no_permanent_named(["Circle of Protection: Shadow"])
    assert any("no valid target to strip" in line for line in game.log)
    assert not any("Circle of Protection: Shadow loses" in line for line in game.log)

    # A creature behind it: the scan finds the creature, not the enchantment.
    game, p0 = cast_with_no_permanent_named(
        ["Circle of Protection: Shadow", "Soltari Foot Soldier"]
    )
    soltari = p0.battlefield[1]
    assert not game._has_keyword(soltari, "shadow")
    assert any("Soltari Foot Soldier loses shadow" in line for line in game.log)

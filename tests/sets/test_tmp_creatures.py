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


# --- W1G1: shadow (CR 702.28) ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def _w1g1_duel(p0_cards, p1_cards):
    """Two battlefields, no summoning sickness, mana enforcement off."""
    p0 = PlayerState(name="P0"); p1 = PlayerState(name="P1")
    for card in p0_cards:
        p0.battlefield.append(_nosick(Permanent(card=card)))
    for card in p1_cards:
        p1.battlefield.append(_nosick(Permanent(card=card)))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p0, p1


#: The fourteen printed shadow creatures the keyword round alone makes
#: playable — every one of them was unsupported on the keyword line and on
#: nothing else.
W1G1_SHADOW_CREATURES = (
    "Soltari Crusader", "Soltari Foot Soldier", "Soltari Monk", "Soltari Priest",
    "Soltari Trooper", "Soltari Lancer",
    "Thalakos Dreamsower", "Thalakos Seer", "Thalakos Sentry",
    "Dauthi Marauder", "Dauthi Mercenary", "Dauthi Mindripper",
    "Dauthi Horror", "Dauthi Slayer",
)

#: The three that print shadow **and** a second line this group declined, with
#: the line each still refuses on. They are listed rather than dropped because
#: an unsupported program records no static lines at all: a sweep that only
#: asserted "shadow is a static line" would have to skip them silently, and the
#: assertion that survives is about *which* line is still refusing.
W1G1_SHADOW_CREATURES_STILL_REFUSING = {
    "Dauthi Ghoul":
        "Whenever a creature with shadow dies, put a +1/+1 counter on this creature.",
    "Soltari Guerrillas":
        "{0}: The next time this creature would deal combat damage to an "
        "opponent this turn, it deals that damage to target creature instead.",
    "Thalakos Mistfolk":
        "{U}: Put this creature on top of its owner's library.",
}


@pytest.mark.parametrize("name", W1G1_SHADOW_CREATURES)
def test_w1g1_every_printed_shadow_creature_records_the_keyword(set_pool, name):
    """The fourteen cards whose keyword line was the whole refusal.

    Asserted as a **static line** as well as as supported: a card is supported
    when *any* of its lines is, so "supported" alone would go green for
    Soltari Crusader on its pump ability with the keyword still refused.
    """
    card = set_pool("TMP")[name]
    program = compile_card_oracle(card)
    assert program.supported, f"{name} is still unsupported"
    assert "shadow" in program.static_lines, (
        f"{name} does not record shadow as a keyword line"
    )


@pytest.mark.parametrize(
    "name,line", sorted(W1G1_SHADOW_CREATURES_STILL_REFUSING.items())
)
def test_w1g1_the_three_declines_no_longer_refuse_on_shadow(set_pool, name, line):
    """The declines, pinned to the line they are actually declined for.

    Each of these three refused on `Shadow` before this round and refuses on its
    *second* line after it, so the assertion is on the refusal's **subject**:
    that is what makes the decline a work-list entry another group can pick up,
    and what fails loudly if a later round makes one of them refuse for a new
    reason instead of clearing it.
    """
    program = compile_card_oracle(set_pool("TMP")[name])
    assert not program.supported
    assert line in program.reason, (
        f"{name} refuses on {program.reason!r}, not on the declined line"
    )


def test_w1g1_two_shadow_creatures_block_each_other_normally(set_pool):
    """The pairing shadow permits, on printed cards.

    Soltari Priest is 2/1 with protection from red and shadow. Two creatures
    that both have it block each other exactly as ordinary creatures do — the
    restriction is a mismatch, not a prohibition on shadow itself, and a
    reading that refused every block involving shadow would pass the two
    negative assertions below and fail here.
    """
    priest = set_pool("TMP")["Soltari Priest"]
    trooper = set_pool("TMP")["Soltari Trooper"]
    ghoul = set_pool("TMP")["Dauthi Ghoul"]
    game, p0, p1 = _w1g1_duel([ghoul, trooper], [priest])
    dauthi_attacker, soltari_attacker = p0.battlefield
    blocker = p1.battlefield[0]

    assert game._can_block_attacker(blocker, soltari_attacker)
    assert game._can_block_attacker(blocker, dauthi_attacker)


def test_w1g1_shadow_is_a_drawback_as_well_as_evasion(set_pool):
    """CR 702.28b's second half on printed cards, both directions.

    The reminder text is one sentence — "can block **or** be blocked by only
    creatures with shadow" — and an implementation that only stopped ground
    creatures blocking a Soltari would have made every one of these seventeen
    cards strictly better than printed. Nothing in the support census, the
    hollow-line report or `parse_coverage` can see that difference.
    """
    tmp = set_pool("TMP")
    priest = tmp["Soltari Priest"]
    # A Tempest vanilla, so no *other* evasion is in the picture: Bayou
    # Dragonfly stood here first and has flying, which is a second reason a
    # block is refused and would have made this test pass for the wrong one.
    ground = tmp["Trained Armodon"]
    game, p0, p1 = _w1g1_duel([ground, priest], [priest, ground])
    ground_attacker, shadow_attacker = p0.battlefield
    shadow_blocker, ground_blocker = p1.battlefield

    assert not game._can_block_attacker(shadow_blocker, ground_attacker)
    assert not game._can_block_attacker(ground_blocker, shadow_attacker)


def test_w1g1_heartwood_dryad_blocks_shadow_and_keeps_its_ordinary_blocks(set_pool):
    """"This creature can block creatures with shadow as though it had shadow."

    Two assertions, and the second is the one a shadow *grant* would fail: the
    Dryad is a ground creature and must still be able to block ground
    creatures. CR 609.4 confines the "as though" to the stated effect.
    """
    tmp = set_pool("TMP")
    dryad = tmp["Heartwood Dryad"]
    priest = tmp["Soltari Priest"]
    ground = tmp["Trained Armodon"]   # a vanilla: no flying to confound it
    game, p0, p1 = _w1g1_duel([priest, ground], [dryad])
    shadow_attacker, ground_attacker = p0.battlefield
    blocker = p1.battlefield[0]

    assert game._can_block_attacker(blocker, shadow_attacker)
    assert game._can_block_attacker(blocker, ground_attacker)
    assert not game._has_keyword(blocker, "shadow")


def test_w1g1_wall_of_diffusion_keeps_defender_and_gains_the_permission(set_pool):
    """The same sentence on a Wall, so the two lines are read together: the
    keyword line still classifies (defender) and the static line still derives.
    A card is supported when *any* of its lines is, so the assertion is on both.
    """
    wall = set_pool("TMP")["Wall of Diffusion"]
    program = compile_card_oracle(wall)

    assert program.supported
    assert "defender" in program.static_lines
    assert [i.kind for i in program.instructions if i.kind != "keyword_line"] == [
        "can_block_as_though_it_had"
    ]

    # Soltari **Trooper**, not Priest: the Wall is red and the Priest has
    # protection from red (CR 702.16f), so that pairing is refused for a second
    # and entirely correct reason — a test that used it would have gone green
    # against a shadow permission that did nothing at all.
    trooper = set_pool("TMP")["Soltari Trooper"]
    game, p0, p1 = _w1g1_duel([trooper], [wall])
    assert game._can_block_attacker(p1.battlefield[0], p0.battlefield[0])


def test_w1g1_soltari_emissary_grants_itself_shadow_in_a_game(set_pool):
    """"{W}: This creature gains shadow until end of turn."

    Driven through the real activation and resolution path rather than asserted
    off the compiled program: the whole point of the keyword round is that a
    grant of it now *does* something, and a card that compiles the right
    instruction and changes no block is exactly the failure the compiled-program
    assertion cannot see.
    """
    emissary = _nosick(Permanent(card=set_pool("TMP")["Soltari Emissary"]))
    p0 = PlayerState(name="P0", battlefield=[emissary], life=20, mana_pool={"W": 1})
    blocker = _nosick(Permanent(card=set_pool("TMP")["Trained Armodon"]))
    p1 = PlayerState(name="P1", battlefield=[blocker], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()

    assert game._can_block_attacker(blocker, emissary)

    game.activate_permanent_ability(0, "Soltari Emissary", ability_index=0)
    while game.stack:
        game.resolve_top_of_stack()

    assert game._has_keyword(emissary, "shadow")
    assert not game._can_block_attacker(blocker, emissary)


def test_w1g1_dauthi_horror_and_dauthi_slayer_were_only_ever_the_keyword(set_pool):
    """The two cards whose *second* lines the brief called gaps.

    Both are already implemented by `engine/combat_restrictions.py` — "can't be
    blocked by white creatures" and "attacks each combat if able" are rows in
    that table and have been. The grammar refuses both sentences, which is what
    a refusal census reports, and the derivation table runs *after* the grammar
    refuses. So the refusal site named a layer that was never going to answer.
    """
    horror = compile_card_oracle(set_pool("TMP")["Dauthi Horror"])
    slayer = compile_card_oracle(set_pool("TMP")["Dauthi Slayer"])

    assert horror.supported and slayer.supported
    assert any(
        i.kind == "cant_be_blocked_by"
        and i.payload["blocker_filters"] == [
            {"type_filter": "creature", "color_filter": "W"}
        ]
        for i in horror.instructions
    )
    assert any(i.kind == "must_attack_each_combat" for i in slayer.instructions)

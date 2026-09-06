"""Tempest enchantments (Auras included — the printed type is the axis).

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


def test_w1g1_dauthi_embrace_grants_shadow_to_a_creature_in_a_game(set_pool):
    """"{B}{B}: Target creature gains shadow until end of turn."

    A repeatable grant, so the assertion is on the block it changes rather than
    on the instruction it compiles — and on *both* halves of CR 702.28b, because
    the creature it makes unblockable is thereby also unable to block. That
    second consequence is the one a player notices and the one an evasion-only
    reading would have got wrong.
    """
    tmp = set_pool("TMP")
    embrace = _nosick(Permanent(card=tmp["Dauthi Embrace"]))
    bear = _nosick(Permanent(card=tmp["Trained Armodon"]))
    p0 = PlayerState(
        name="P0", battlefield=[embrace, bear], life=20, mana_pool={"B": 2}
    )
    blocker = _nosick(Permanent(card=tmp["Trained Armodon"]))
    p1 = PlayerState(name="P1", battlefield=[blocker], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()

    assert game._can_block_attacker(blocker, bear)

    game.activate_permanent_ability(
        0, "Dauthi Embrace", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    while game.stack:
        game.resolve_top_of_stack()

    assert game._has_keyword(bear, "shadow")
    assert not game._can_block_attacker(blocker, bear)
    assert not game._can_block_attacker(bear, blocker), (
        "CR 702.28b's second half: the creature it just made evasive can no "
        "longer block a creature without shadow"
    )


def test_w1g1_dauthi_embrace_may_target_an_opponents_creature(set_pool):
    """The ability says "target creature", not "target creature you control",
    and the drawback half of shadow is what makes that a *removal* of a blocker.

    Asserted because the picker is derived from the compiled program: a
    `type_filter` narrowed to the controller's own board would have made the
    card unable to do the thing it is most often played for, and the compiled
    payload is the only place that narrowing would show.
    """
    program = compile_card_oracle(set_pool("TMP")["Dauthi Embrace"])
    ability = program.activated_abilities[0]

    assert ability.instruction.kind == "grant_target_keyword_until_eot"
    assert ability.instruction.payload["keywords"] == ("shadow",)
    assert ability.instruction.payload["targets"]["filter"] == {
        "type_filter": "creature"
    }


# --- W1G1: Circle of Protection: Shadow (CR 615.8/615.9) ---

from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import _damage_dealt


def _w1g1_cop_rig(set_pool):
    """Circle of Protection: Shadow in play, a shadow creature and a ground
    creature on the other side."""
    tmp = set_pool("TMP")
    cop = _nosick(Permanent(card=tmp["Circle of Protection: Shadow"]))
    p0 = PlayerState(name="P0", battlefield=[cop], life=20, mana_pool={"C": 5})
    shadowy = _nosick(Permanent(card=tmp["Soltari Priest"]))
    ground = _nosick(Permanent(card=tmp["Trained Armodon"]))
    p1 = PlayerState(name="P1", battlefield=[shadowy, ground], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    game.activate_permanent_ability(
        0, "Circle of Protection: Shadow", ability_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    return game, p0, shadowy, ground


def test_w1g1_circle_of_protection_shadow_arms_the_noun_phrase_not_the_type(set_pool):
    """"{1}: The next time a creature of your choice **with shadow** would deal
    damage to you this turn, prevent that damage."

    The other six Circles narrow by a colour or by a card type, and both of
    those are fields on the shield that CR 615.9 rechecks. This one narrows by a
    **keyword**, which `source_has_type` cannot answer — so a payload reusing
    `prevention_source_type` would have armed a shield against *every creature
    source*, with the word the card is named for dropped. The compiled payload
    is asserted because that is where the drop would be invisible: the card
    would report supported, produce a real instruction and prevent the wrong
    damage.
    """
    program = _w1g1_compile(set_pool("TMP")["Circle of Protection: Shadow"])

    assert program.supported
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "grant_prevention_shield"
    assert ability.instruction.payload == {
        "amount": 1,
        "protection_kind": "source_subject",
        "source_filter": {"type_filter": "creature", "with_keywords": ["shadow"]},
    }


def test_w1g1_circle_of_protection_shadow_prevents_only_a_shadow_source(set_pool):
    """Both directions in one game, because the narrowing is the card.

    A Circle that prevented every creature's damage would pass any test that
    only checked the shadow attacker, and it is the exact shape the payload
    above would have produced.
    """
    game, p0, shadowy, ground = _w1g1_cop_rig(set_pool)

    assert _damage_dealt(game, p0, 2, source=shadowy, combat=True) == 0
    # The shield is spent; arm a fresh one for the negative half.
    game.players[0].mana_pool["C"] = 5
    game.activate_permanent_ability(
        0, "Circle of Protection: Shadow", ability_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert _damage_dealt(game, p0, 3, source=ground, combat=True) == 3


def test_w1g1_the_shield_is_rechecked_when_the_damage_would_be_dealt(set_pool):
    """CR 615.9: the recorded property is rechecked against the source at
    damage time, not locked in when the shield was armed.

    Reality Anchor can take the shadow off the creature the Circle was pointed
    at between the activation and the combat damage step, and the shield must
    then let the damage through — which is only true because the phrase is
    tested through `subject_matches` (layer 6) rather than snapshotted.
    """
    from engine.keywords import remove_keyword

    game, p0, shadowy, ground = _w1g1_cop_rig(set_pool)
    remove_keyword(shadowy, "shadow", duration="end_of_turn")

    assert _damage_dealt(game, p0, 2, source=shadowy, combat=True) == 2


def test_w1g1_a_keyword_shield_the_engine_cannot_test_refuses(set_pool):
    """The refusing half of the same gate, written before trusting it.

    `subject_matches` reads a keyword off layer 6 and answers "no" for every
    source when nothing implements the word — so a Circle naming an
    unimplemented keyword would prevent **nothing** while reporting supported.
    That is the narrowing direction rather than the widening one, and it is
    still a card doing something other than what it prints.
    """
    from engine.grammar import compile_line

    good = compile_line(
        "{1}: The next time a creature of your choice with shadow would deal "
        "damage to you this turn, prevent that damage.",
        card_name="Probe",
    )
    assert good.instructions

    bad = compile_line(
        "{1}: The next time a creature of your choice with ward would deal "
        "damage to you this turn, prevent that damage.",
        card_name="Probe",
    )
    assert not bad.instructions
    assert "ward" in (bad.failure_reason or "")

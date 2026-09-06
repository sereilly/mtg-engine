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


# --- W1G3: board-wide characteristic statics (Humility, Light of Day) ---
# CR 613's characteristic layers over a *set* of permanents rather than one.
# Humility is the layer-order card: CR 613.1f puts the ability removal in
# layer 6 and CR 613.4b puts the base-P/T setting in layer 7b, so what a
# creature keeps depends on which layer and which timestamp gave it.
import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.pt import add_pt_counters
from engine.trigger_utils import iter_triggered_abilities


def _w1g3_stage(set_pool, cards, names, *, enforce_mana=False):
    """*names* — resolved from TMP first, then the LEA pool — on seat 0."""
    tmp = set_pool("TMP")
    seats = [PlayerState(name="A"), PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = enforce_mana
    for name in names:
        perm = Permanent(card=tmp.get(name) or cards[name])
        perm.metadata["summoning_sickness_turn"] = -99
        seats[0].battlefield.append(perm)
    game._recompute_continuous_effects()
    return game, seats


def test_w1g3_humility_and_light_of_day_compile(set_pool):
    for name in ("Humility", "Light of Day"):
        program = compile_card_oracle(set_pool("TMP")[name])
        assert program.supported, (name, program.reason)


@pytest.mark.parametrize("kind", ["keyword", "activated", "triggered", "static"])
def test_w1g3_humility_removes_every_kind_of_ability(set_pool, cards, kind):
    """CR 613.1f says "abilities", and an ability is four different things
    downstream: a keyword layer 6 holds, an activated ability read off the
    compiled program, a triggered one read off the card, and a static one
    re-derived from the text on every recompute. A removal wired into the
    keyword channel alone reaches only the first."""
    if kind == "keyword":
        game, seats = _w1g3_stage(set_pool, cards, ["Humility", "Serra Angel"])
        assert not seats[0].battlefield[1].has_keyword("flying")
    elif kind == "activated":
        game, seats = _w1g3_stage(set_pool, cards, ["Humility", "Rod of Ruin"])
        # An *artifact* keeps its ability — Humility names creatures.
        assert compile_card_oracle(
            seats[0].battlefield[1].effective_card
        ).activated_abilities
        game, seats = _w1g3_stage(set_pool, cards, ["Humility", "Demonic Hordes"])
        assert not compile_card_oracle(
            seats[0].battlefield[1].effective_card
        ).activated_abilities
    elif kind == "triggered":
        game, seats = _w1g3_stage(set_pool, cards, ["Humility", "Demonic Hordes"])
        assert list(iter_triggered_abilities(game, condition_kinds={"upkeep_self"})) == []
        bare, _ = _w1g3_stage(set_pool, cards, ["Demonic Hordes"])
        assert list(iter_triggered_abilities(bare, condition_kinds={"upkeep_self"}))
    else:
        game, seats = _w1g3_stage(
            set_pool, cards,
            ["Humility", "Lord of Atlantis", "Merfolk of the Pearl Trident"],
        )
        merfolk = seats[0].battlefield[2]
        assert (merfolk.effective_power, merfolk.effective_toughness) == (1, 1)
        bare, bare_seats = _w1g3_stage(
            set_pool, cards, ["Lord of Atlantis", "Merfolk of the Pearl Trident"]
        )
        unhumbled = bare_seats[0].battlefield[1]
        assert (unhumbled.effective_power, unhumbled.effective_toughness) == (2, 2)


def test_w1g3_humility_sets_base_pt_at_layer_7b_not_7c(set_pool, cards):
    """CR 613.4b before CR 613.4c: the 1/1 is a floor, not a ceiling. A +1/+1
    counter still applies over it, which is the half a "make it 1/1" written at
    the wrong sublayer would silently swallow."""
    game, seats = _w1g3_stage(set_pool, cards, ["Humility", "Serra Angel"])
    angel = seats[0].battlefield[1]
    assert (angel.effective_power, angel.effective_toughness) == (1, 1)
    add_pt_counters(angel, "+1/+1", 1)
    game._recompute_continuous_effects()
    assert (angel.effective_power, angel.effective_toughness) == (2, 2)


def test_w1g3_an_ability_granted_after_humility_survives(set_pool, cards):
    """CR 613.3 — layer 6 applies in timestamp order, so a later grant wins.
    That is why the removal is folded in *before* the grants in
    ``Permanent.effective_card`` rather than over the finished text."""
    game, seats = _w1g3_stage(set_pool, cards, ["Humility", "Grizzly Bears"])
    bear = seats[0].battlefield[1]
    assert not bear.has_keyword("flying")

    banner = Permanent(card=CardDefinition(
        name="Sky Banner", mana_cost="{2}", cmc=2.0, type_line="Enchantment",
        oracle_text="All creatures have flying.", colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw={},
    ))
    seats[0].battlefield.append(banner)
    game._recompute_continuous_effects()
    assert bear.has_keyword("flying")
    assert (bear.effective_power, bear.effective_toughness) == (1, 1)


def test_w1g3_humility_ends_with_its_source(set_pool, cards):
    """CR 611.3b — derived from the source recorded on each permanent, so the
    enchantment leaving gives every ability back with nothing to undo."""
    game, seats = _w1g3_stage(set_pool, cards, ["Humility", "Serra Angel"])
    angel = seats[0].battlefield[1]
    assert angel.effective_card.oracle_text == ""
    game.remove_from_battlefield(seats[0].battlefield[0])
    game._recompute_continuous_effects()
    assert angel.has_keyword("flying")
    assert (angel.effective_power, angel.effective_toughness) == (4, 4)


def test_w1g3_light_of_day_grounds_black_creatures_both_ways(set_pool, cards):
    """One printed sentence, two prohibitions (CR 506.4 / CR 509.1b), one
    subject — so both halves come off one ``CombatRestriction`` and cannot
    disagree about which creatures the noun phrase names."""
    tmp = set_pool("TMP")

    def _perm(name):
        perm = Permanent(card=tmp.get(name) or cards[name])
        perm.metadata["summoning_sickness_turn"] = -99
        return perm

    black, white = _perm("Scathe Zombies"), _perm("Pearled Unicorn")
    blocker_black, blocker_white = _perm("Scathe Zombies"), _perm("Pearled Unicorn")
    seats = [
        PlayerState(name="A", battlefield=[_perm("Light of Day"), black, white]),
        PlayerState(name="B", battlefield=[blocker_black, blocker_white]),
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    game.active_player_index = 0

    assert not game.can_attack(black, 0)
    assert game.can_attack(white, 0)
    assert not game._can_block_attacker(blocker_black, white)
    assert game._can_block_attacker(blocker_white, white)


def test_w1g3_the_can_attack_or_block_row_refuses_a_self_reference():
    """`_printed_noun` answers ``{"type_filter": "creature"}`` for "this
    creature" and "enchanted creature" alike, so the row is anchored on the
    plural head noun — a `.+` subject would read a restriction printed about
    one creature as a ban on every creature on the board."""
    from engine.combat_restrictions import combat_restriction_for

    assert combat_restriction_for("black creatures can't attack or block") is not None
    assert combat_restriction_for("this creature can't attack or block") is None
    assert combat_restriction_for("enchanted creature can't attack or block") is None

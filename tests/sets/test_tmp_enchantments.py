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

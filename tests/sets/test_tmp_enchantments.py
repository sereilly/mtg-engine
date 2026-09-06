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


# --- W1G4: triggered abilities the engine had never fired ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.tokens import make_token_card


def _w1g4_upkeep(board):
    """One turn's beginning phase for seat 0, with *board* on its battlefield."""
    p1 = PlayerState(name="P1", battlefield=list(board))
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return game, p1


def _w1g4_perm(card, *, token: bool = False):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    if token:
        perm.metadata["is_token"] = True
    return perm


def _w1g4_token(name, subtype, colors):
    return _w1g4_perm(
        make_token_card(
            name=name, power=2, toughness=2,
            type_line=f"Creature - {subtype}", colors=colors,
        ),
        token=True,
    )


# -- Sarcomancy -------------------------------------------------------------


def test_sarcomancy_burns_its_controller_with_no_zombie_out(set_pool):
    """"At the beginning of your upkeep, if there are no Zombies on the
    battlefield, this enchantment deals 1 damage to you."

    CR 603.4's intervening-if over a *board* count. The line compiled and
    reported supported before this round while producing no instruction at all
    — `--hollow-lines` was the only instrument that could see it, because a
    card is supported when any of its lines is and the enters-trigger above
    this one always was.
    """
    game, p1 = _w1g4_upkeep([_w1g4_perm(set_pool("TMP")["Sarcomancy"])])

    assert p1.life == 19


def test_sarcomancy_is_silent_while_a_zombie_is_on_the_battlefield(set_pool):
    """The half a dropped condition would get wrong in the *loud* direction:
    an intervening-if that parses and is then discarded makes the trigger fire
    always, which is an ability that works more often than the card allows.
    """
    game, p1 = _w1g4_upkeep([
        _w1g4_perm(set_pool("TMP")["Sarcomancy"]),
        _w1g4_token("Zombie Token", "Zombie", ("B",)),
    ])

    assert p1.life == 20


def test_sarcomancy_counts_zombies_on_any_battlefield(set_pool):
    """"on the battlefield" names the zone, not a seat: an opponent's Zombie
    stops the damage exactly as your own does. This is the difference between
    the `on_battlefield` condition and the `controls` one beside it.
    """
    p1 = PlayerState(
        name="P1", battlefield=[_w1g4_perm(set_pool("TMP")["Sarcomancy"])]
    )
    p2 = PlayerState(
        name="P2", battlefield=[_w1g4_token("Zombie Token", "Zombie", ("B",))]
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert p1.life == 20


# -- Spirit Mirror ----------------------------------------------------------


def test_spirit_mirror_makes_a_reflection_when_none_is_out(set_pool):
    """"At the beginning of your upkeep, if there are no Reflection tokens on
    the battlefield, create a 2/2 white Reflection creature token."
    """
    game, p1 = _w1g4_upkeep([_w1g4_perm(set_pool("TMP")["Spirit Mirror"])])

    reflections = [p for p in p1.battlefield if p.card.name == "Reflection Token"]
    assert len(reflections) == 1
    assert (
        reflections[0].effective_power,
        reflections[0].effective_toughness,
    ) == (2, 2)


def test_spirit_mirror_makes_no_second_reflection(set_pool):
    """The card's whole point: one Reflection, replaced rather than
    accumulated. Without the condition the upkeep would mint one every turn.
    """
    game, p1 = _w1g4_upkeep([
        _w1g4_perm(set_pool("TMP")["Spirit Mirror"]),
        _w1g4_token("Reflection Token", "Reflection", ("W",)),
    ])

    assert sum(1 for p in p1.battlefield if p.card.name == "Reflection Token") == 1


def test_spirit_mirror_reads_the_token_narrowing(set_pool):
    """"no Reflection **tokens**" — a nontoken Reflection does not stop it.
    The narrowing rides the noun phrase into the condition's filter, so this
    is the test that the phrase was not flattened to "no Reflections".
    """
    program = set_pool("TMP")["Spirit Mirror"]
    from engine.oracle import compile_card_oracle

    trigger = next(
        t for t in compile_card_oracle(program).triggered_abilities
        if t.condition.kind == "upkeep_self"
    )
    gate = trigger.instruction.payload["intervening_if"]
    assert gate["kind"] == "on_battlefield"
    assert gate["filter"]["token_only"] is True
    assert (gate["count"], gate["op"]) == (0, "eq")


# -- Sadistic Glee ----------------------------------------------------------


def test_sadistic_glee_grows_its_host_when_a_creature_dies(set_pool):
    """"Whenever a creature dies, put a +1/+1 counter on enchanted creature."

    Grammar-clean before this round: the line parsed, lowered and reached a
    real handler. What refused it was the *Aura support gate* — an Aura whose
    effect line nothing claims is reported unsupported by design, and no row
    named the death dispatcher. The row is the whole fix, and it is honest
    because that dispatcher scans `permanents_with_controller()`, so an Aura
    watching the whole board is enqueued exactly like a creature watching it.
    """
    from engine.auras import attach_aura
    from engine import load_cards
    from engine.card_loader import manifest_set_path

    lea = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
    host = _w1g4_perm(lea["Grizzly Bears"])
    glee = _w1g4_perm(set_pool("TMP")["Sadistic Glee"])
    victim = _w1g4_perm(lea["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[host, glee])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    attach_aura(glee, host)
    game.start_turn(0)
    game._settle()
    assert (host.effective_power, host.effective_toughness) == (2, 2)

    victim.damage_marked = 99
    game.check_state_based_actions()
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert (host.effective_power, host.effective_toughness) == (3, 3)


# -- Death Pits of Rath -----------------------------------------------------


def _w1g4_combat(p1_board, p2_board):
    p1 = PlayerState(name="P1", battlefield=list(p1_board))
    p2 = PlayerState(name="P2", battlefield=list(p2_board))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()   # declare blockers
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()
    game.advance_combat_phase()   # combat damage
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return game, p1, p2


def test_death_pits_of_rath_destroys_a_damaged_creature(set_pool):
    """"Whenever a creature is dealt damage, destroy it. It can't be
    regenerated."

    A **third dispatch scope** for one event: the damage fire site scanned the
    damaged permanent's own abilities and its attachments, and nothing else on
    the board — so a condition both front-end tables could read had no observer
    that could hear it. A 4/4 that trades one point of damage for a 2/2 walks
    away; with the Pits out it does not.
    """
    from engine import load_cards
    from engine.card_loader import manifest_set_path

    lea = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
    beater = _w1g4_perm(lea["Force of Nature"])
    _, p1, p2 = _w1g4_combat(
        [beater, _w1g4_perm(set_pool("TMP")["Death Pits of Rath"])],
        [_w1g4_perm(lea["Granite Gargoyle"])],
    )

    assert not any(p.card.name == "Force of Nature" for p in p1.battlefield)
    assert not p2.battlefield


def test_a_creature_survives_the_same_combat_without_death_pits(set_pool):
    """The control: without the enchantment the attacker lives, so the test
    above is measuring the Pits and not the combat damage step."""
    from engine import load_cards
    from engine.card_loader import manifest_set_path

    lea = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
    _, p1, p2 = _w1g4_combat(
        [_w1g4_perm(lea["Force of Nature"])],
        [_w1g4_perm(lea["Granite Gargoyle"])],
    )

    assert any(p.card.name == "Force of Nature" for p in p1.battlefield)


# --- W1G5: Legacy's Allure's counter bound and Recycle's hand size ---

from engine import Game, PlayerState
from engine.hand_size import maximum_hand_size
from engine.models import CardDefinition, Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec


def _w1g5e_card(name, type_line, power=None, toughness=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text="",
        cmc=0.0, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw=raw,
        power=str(power) if power is not None else None,
        toughness=str(toughness) if toughness is not None else None,
    )


def _w1g5e_game(mine, theirs):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game._settle()
    return game


def _w1g5e_allure(set_pool, counters, victim_power):
    allure = Permanent(card=set_pool("TMP")["Legacy's Allure"])
    victim = Permanent(card=_w1g5e_card(
        "Beast", "Creature — Beast", power=victim_power, toughness=victim_power,
    ))
    game = _w1g5e_game([allure], [victim])
    add_counters(allure, "treasure", counters)
    return game, allure, victim


def test_w1g5_legacys_allure_takes_a_creature_within_its_counter_bound(set_pool):
    """"Sacrifice this enchantment: Gain control of target creature with power
    less than or equal to the number of treasure counters on this enchantment."

    The bound is a count on the ability's own **source**, which the pure filter
    matcher cannot reach — so it is answered where the source is in hand, and a
    caller without one narrows to nothing rather than to every creature.
    """
    game, _allure, victim = _w1g5e_allure(set_pool, counters=3, victim_power=2)

    result = game.activate_permanent_ability(
        0, "Legacy's Allure", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert game.controller_index_of(victim) == 0, game.log


def test_w1g5_legacys_allure_refuses_a_creature_over_its_counter_bound(set_pool):
    """The half a dropped narrowing loses. With one counter, a 2-power creature
    is not a legal target (CR 601.2c/602.2b), and the refusal comes *before*
    the cost — so the enchantment is still on the battlefield afterwards."""
    game, allure, victim = _w1g5e_allure(set_pool, counters=1, victim_power=2)

    result = game.activate_permanent_ability(
        0, "Legacy's Allure", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert not result.supported
    assert allure in game.controlled_by(0), "nothing was sacrificed"
    assert game.controller_index_of(victim) == 1


def test_w1g5_legacys_allure_offers_a_picker(set_pool):
    """The other half of the same defect: `picker_sweep` reported "says
    'target', derivation offers no picker" because the ability compiled to no
    instruction at all, leaving `derive_activation_spec` nothing to read."""
    program = compile_card_oracle(set_pool("TMP")["Legacy's Allure"])
    ability = program.activated_abilities[0]
    assert ability.instruction is not None, "the line is no longer hollow"
    assert derive_activation_spec(ability) == {"kind": "creature"}


def test_w1g5_recycle_sets_its_controllers_maximum_hand_size(set_pool):
    """"Your maximum hand size is two." (CR 402.2.)

    Three assertions because the sentence names one seat: the controller is
    limited, the opponent is not, and CR 611.3a ends the limit with the
    enchantment. That last one is what separates a derived static from the
    stamped field that left Library of Leng's permission on a destroyed
    permanent's controller for the rest of the game.
    """
    recycle = Permanent(card=set_pool("TMP")["Recycle"])
    game = _w1g5e_game([recycle], [])

    assert maximum_hand_size(game, 0) == 2
    assert maximum_hand_size(game, 1) == 7, "the sentence names one seat"

    game.players[0].hand.extend(
        _w1g5e_card(f"Card {index}", "Instant") for index in range(5)
    )
    game.active_player_index = 0
    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == 2, game.log

    game.remove_from_battlefield(recycle)
    assert maximum_hand_size(game, 0) == 7, "CR 611.3a: the static ends with it"


# --- W2G4: the linked pile a hand is swapped with ---

from engine import Game, PlayerState
from engine.linked_exile import linked_entries
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g4_card(name, type_line, text=""):
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text=text,
        cmc=0.0, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "oracle_text": text},
    )


def _w2g4_game(permanents, *, hand=(), library=(), interactive=(0,)):
    seats = [
        PlayerState(name="P0", battlefield=list(permanents), hand=list(hand),
                    library=list(library)),
        PlayerState(name="P1"),
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    return game


def _w2g4_upkeep(game, seat=0):
    """One upkeep step for *seat*, with its triggers resolved off the stack.

    The loop stops on an owed prompt as well as on an empty stack, and that is
    the engine working rather than a guard: a prompt armed part-way through a
    resolution keeps its stack object *on* the stack until it is answered
    (CR 608.2, CR 117.3b), so a bare `while game.stack` here spins for ever on
    any card that asks its controller something. Call it again after answering
    to carry on where it stopped.
    """
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    _w2g4_drain(game)


def _w2g4_drain(game):
    """Resolve the stack down to the first owed prompt.

    Its own function because a targeted trigger needs it *twice*: once to reach
    the "choose your target" prompt (CR 603.3d) and again after the answer. A
    second ``resolve_upkeep`` would put the trigger on the stack a second time.
    """
    while game.stack and not game.pending_choices:
        game.resolve_top_of_stack()


def test_duplicity_swaps_the_whole_hand_for_the_pile_it_already_holds(set_pool):
    """`At the beginning of your upkeep, you may exile all cards from your hand
    face down. If you do, put all other cards you own exiled with this
    enchantment into your hand.`

    The last hollow line in the set: the ability part compiled with no
    instruction behind it at all. "All **other**" is the piece that makes it
    work — other than the cards this same resolution just exiled — so the
    enchantment hands back the *previous* pile rather than the one it has this
    instant taken away. Read the other way it would give back exactly what it
    took and the card would do nothing.
    """
    from engine.linked_exile import link_exiled_card

    dup = Permanent(card=set_pool("TMP")["Duplicity"])
    old_pile = [_w2g4_card(f"Old{i}", "Instant") for i in range(3)]
    hand = [_w2g4_card(f"New{i}", "Instant") for i in range(2)]
    game = _w2g4_game([dup], hand=hand)
    for card in old_pile:
        game.players[0].exile.append(card)
        link_exiled_card(dup, card, 0, face_down=True)

    program = compile_card_oracle(dup.card)
    upkeep = next(
        t for t in program.triggered_abilities
        if t.condition.kind == "upkeep_self"
    )
    assert upkeep.instruction is not None, (
        "this ability part compiled with no instruction behind it"
    )

    _w2g4_upkeep(game)
    # The offer is a **price** — the hand is what it spends — so a headless
    # seat declines it (`ai_valuation.SELF_PAYMENT_KINDS`) and the swap only
    # happens for a seat that says yes.
    assert game.confirm_optional_pay(0, accept=True)

    assert sorted(c.name for c in game.players[0].hand) == [
        "Old0", "Old1", "Old2",
    ]
    # The new hand is the pile now, and only it — the old three left exile.
    assert sorted(e["card"].name for e in linked_entries(dup)) == ["New0", "New1"]
    assert sorted(c.name for c in game.players[0].exile) == ["New0", "New1"]


def test_duplicity_does_not_hand_back_another_players_cards(set_pool):
    """"…cards **you own**…" narrows the sweep, and it is the whole of what
    stops a player who has taken the enchantment from pulling its previous
    controller's cards out of exile."""
    from engine.linked_exile import link_exiled_card

    dup = Permanent(card=set_pool("TMP")["Duplicity"])
    theirs = _w2g4_card("Theirs", "Instant")
    mine = _w2g4_card("Mine", "Instant")
    game = _w2g4_game([dup], hand=[_w2g4_card("New0", "Instant")])
    game.players[1].exile.append(theirs)
    link_exiled_card(dup, theirs, 1, face_down=True)
    game.players[0].exile.append(mine)
    link_exiled_card(dup, mine, 0, face_down=True)

    _w2g4_upkeep(game)
    assert game.confirm_optional_pay(0, accept=True)

    assert [c.name for c in game.players[0].hand] == ["Mine"]
    assert [c.name for c in game.players[1].exile] == ["Theirs"]
    assert any(e["card"].name == "Theirs" for e in linked_entries(dup)), (
        "the other player's card is still exiled with the enchantment"
    )


def test_duplicity_is_offered_as_a_price_so_a_headless_seat_declines(set_pool):
    """A new offered-action kind is free until somebody says it is not, and the
    failure is silent: the cost is lowered *into* the offered action, where the
    affordability test cannot see it.

    Left out of `SELF_PAYMENT_KINDS`, a headless seat exiles its whole hand
    every upkeep — the exact shape `_default_optional_pay`'s docstring records
    for the sacrifice and the ante.
    """
    dup = Permanent(card=set_pool("TMP")["Duplicity"])
    hand = [_w2g4_card("New0", "Instant")]
    game = _w2g4_game([dup], hand=hand, interactive=())

    _w2g4_upkeep(game)

    assert [c.name for c in game.players[0].hand] == ["New0"]
    assert not linked_entries(dup)


def test_precognition_looks_at_the_targeted_opponents_top_card(set_pool):
    """`At the beginning of your upkeep, you may look at the top card of target
    opponent's library. If you do, you may put that card on the bottom of that
    player's library.`

    Two pieces the brief named, and both turned out smaller than they read.
    `look_at_library_top_then_bottom` has existed since Coral Fighters; what
    refused was the *seat* — the one card printing a targeted look happened to
    say "player", so "target opponent" was declined by name. And "you may put
    that card on the bottom" is that production's own tail, four words short of
    reading Precognition's "If you do," join.
    """
    pre = Permanent(card=set_pool("TMP")["Precognition"])
    game = _w2g4_game([pre], interactive=(0,))
    game.players[1].library = [
        _w2g4_card("Top", "Instant"), _w2g4_card("Under", "Instant"),
    ]

    _w2g4_upkeep(game)
    # The trigger targets, so the seat names its opponent as it goes on the
    # stack (CR 603.3d) before anything is looked at.
    assert game.confirm_trigger_target(0, seat=1)
    _w2g4_drain(game)
    assert game.confirm_optional_pay(0, accept=True)

    scry = next(iter(game.pending_choices_of("scry")))
    assert scry.player_index == 0, "the enchantment's controller does the looking"
    assert scry.data["library_index"] == 1, "…at the *opponent's* library"
    assert scry.data["top_count"] == 1
    assert game.confirm_scry(0, card_order=[0], bottom_count=1)

    assert [c.name for c in game.players[1].library] == ["Under", "Top"]


def test_precognition_may_leave_the_card_where_it_is(set_pool):
    """"You **may** put that card on the bottom" — leaving it on top is a legal
    outcome and is the whole reason the sentence is a decision rather than a
    move."""
    pre = Permanent(card=set_pool("TMP")["Precognition"])
    game = _w2g4_game([pre], interactive=(0,))
    game.players[1].library = [
        _w2g4_card("Top", "Instant"), _w2g4_card("Under", "Instant"),
    ]

    _w2g4_upkeep(game)
    assert game.confirm_trigger_target(0, seat=1)
    _w2g4_drain(game)
    assert game.confirm_optional_pay(0, accept=True)
    assert game.confirm_scry(0, card_order=[0], bottom_count=0)

    assert [c.name for c in game.players[1].library] == ["Top", "Under"]

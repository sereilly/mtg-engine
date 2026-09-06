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

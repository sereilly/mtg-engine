"""A permanent sees its own death, and "this creature or another X" is a union.

Two defects one Onslaught card (Rotlung Reanimator: "Whenever this creature or
another Cleric dies, create a 2/2 black Zombie creature token") needed fixed
before it could work, each one already wrong on shipped cards.

**CR 603.10a: a leaves-the-battlefield ability looks back in time.** The two
board-wide death scans (``_fire_permanent_dies_triggers``,
``_fire_creature_dies_triggers``) iterated the battlefield, and the single
destroy and the sacrifice take the permanent off it *before* announcing the
death, while the sweeps announce first. So a permanent's own board-wide death
trigger — Basri's Lieutenant's "this creature or another creature you control
dies", Tablet of Epityr's "an artifact you control is put into a graveyard",
Soulcatcher's "a creature with flying dies" — fired when a Wrath killed it and
not when a Murder did. ``Game._death_observers`` hands the dead permanent to
both scans whichever order its caller removed it in.

**"This creature or another Rogue you control" names the source by identity**
(CR 201.5), whatever its types. Both front ends read it as "a Rogue you
control" — the union folded into the phrase by dropping "another" — which is
the same set only while the source is itself a Rogue. Thieves' Guild Enforcer
entering under a Conspiracy naming Goblin milled nobody.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.pt import add_plus1_counters
from engine.subject_filters import subject_matches
from tests.helpers import _nosick, resolve_stack

_SELF_SEEN_KINDS = frozenset({"creature_you_control_dies", "permanent_dies"})


def _alone(card) -> tuple[Game, PlayerState, Permanent]:
    """*card* entered onto an empty battlefield through the entry funnel, so it
    carries the seats a real entry stamps (its base controller, and so its
    owner once it has left)."""
    p1 = PlayerState(name="P1", library=[card] * 3)
    p2 = PlayerState(name="P2", library=[card] * 3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    perm = _nosick(Permanent(card=card))
    game._put_permanent_onto_battlefield(0, perm, None)
    resolve_stack(game)
    game.pending_choices.clear()
    return game, p1, perm


def _self_seen_triggers(card, game, perm):
    """The board-wide death triggers of *card* whose own death they describe."""
    for trig in compile_card_oracle(card).triggered_abilities:
        condition = trig.condition
        if condition is None or condition.kind not in _SELF_SEEN_KINDS:
            continue
        if trig.instruction is None:
            continue
        payload = condition.payload
        # Narrowings about the cause or the pile, which a lone permanent its
        # controller owns, destroyed by nothing, does not satisfy.
        if payload.get("dying_cause") or payload.get("dying_graveyard_owner") not in (None, "your"):
            continue
        if condition.kind == "creature_you_control_dies" and not perm.is_creature:
            continue
        if condition.kind == "permanent_dies" and not (
            payload.get("dying_includes_source")
            or subject_matches(game, perm, payload.get("dying_filter"), observer=0, source=perm)
        ):
            continue
        yield trig


def _announced(game) -> list[str]:
    """Every trigger the game announces from here on, by its printed line —
    recorded where the death scans hand their events over, so a trigger that
    then resolves at once (or waits on a prompt) still counts."""
    heard: list[str] = []
    batch = game._enqueue_triggered_batch

    def recording(events, *args, **kwargs):
        heard.extend(str(event.get("ability_text") or "") for event in events)
        return batch(events, *args, **kwargs)

    game._enqueue_triggered_batch = recording
    return heard


def _census(kill) -> tuple[int, list[str]]:
    examined, silent = 0, []
    seen: set[str] = set()
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        if card.name in seen:
            continue
        seen.add(card.name)
        game, p1, perm = _alone(card)
        triggers = list(_self_seen_triggers(card, game, perm))
        if not triggers:
            continue
        # "…if it had a +1/+1 counter on it" (Basri's Lieutenant).
        add_plus1_counters(perm)
        examined += 1
        heard = _announced(game)
        kill(game, p1, perm)
        for trig in triggers:
            if trig.source_line not in heard:
                silent.append(f"{card.name}: {trig.source_line}")
    return examined, silent


def test_every_board_wide_death_trigger_sees_its_own_destruction():
    examined, silent = _census(
        lambda game, p1, perm: game._destroy_target_permanent(p1, target_permanent_index=0)
    )
    # Basri's Lieutenant, Tablet of Epityr, Urza's Miter, Dauthi Ghoul, Jinxed
    # Ring, Scrapheap, Liability, Soulcatcher, Rotlung Reanimator on this pool.
    assert examined >= 8, examined
    assert not silent, "\n".join(silent)


def test_every_board_wide_death_trigger_sees_its_own_sacrifice():
    examined, silent = _census(lambda game, p1, perm: game.sacrifice_permanent(perm))
    assert examined >= 8, examined
    # "…if it wasn't sacrificed" (Urza's Miter) is the one that must not fire.
    assert silent == [
        line for line in silent if line.startswith("Urza's Miter:")
    ], "\n".join(silent)


def test_basris_lieutenant_knights_its_own_destruction(set_pool):
    """The M21 test drives the move in the sweep's order (graveyard, then
    removal); a Murder removes first, and the Knight was never made."""
    for kill in (
        lambda game, p1, perm: game._destroy_target_permanent(p1, target_permanent_index=0),
        lambda game, p1, perm: game.sacrifice_permanent(perm),
    ):
        game, p1, lieutenant = _alone(set_pool("M21")["Basri's Lieutenant"])
        add_plus1_counters(lieutenant)
        kill(game, p1, lieutenant)
        game._settle()
        resolve_stack(game)
        assert [p.card.name for p in p1.battlefield] == ["Knight Token"]


def _conspiracy(game, seat, word, set_pool):
    conspiracy = Permanent(card=set_pool("MMQ")["Conspiracy"])
    game.players[seat].battlefield.append(conspiracy)
    game._initialize_permanent_state(conspiracy, seat, None)
    conspiracy.metadata["chosen_creature_type"] = word
    game.check_state_based_actions()
    return conspiracy


def test_a_source_that_is_no_rogue_still_answers_this_creature(set_pool):
    """Thieves' Guild Enforcer entering as a Goblin (Conspiracy, CR 205.1a)
    is still "this creature": each opponent mills two."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Thieves' Guild Enforcer"]], library=[pool["Island"]] * 5)
    p2 = PlayerState(name="P2", library=[pool["Island"]] * 10)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    _conspiracy(game, 0, "goblin", set_pool)

    game.cast_from_hand(0, "Thieves' Guild Enforcer")
    game._settle()
    resolve_stack(game)

    enforcer = next(p for p in p1.battlefield if p.card.name == "Thieves' Guild Enforcer")
    assert enforcer.has_type("goblin") and not enforcer.has_type("rogue")
    assert len(p2.graveyard) == 2


def test_another_goblin_under_the_same_conspiracy_is_not_a_rogue(set_pool):
    """The union's other half is still the printed phrase: a second creature
    entering as a Goblin is not "another Rogue you control"."""
    pool = set_pool("M21")
    enforcer = _nosick(Permanent(card=pool["Thieves' Guild Enforcer"]))
    p1 = PlayerState(
        name="P1", battlefield=[enforcer], hand=[pool["Gale Swooper"]],
        library=[pool["Island"]] * 5,
    )
    p2 = PlayerState(name="P2", library=[pool["Island"]] * 10)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._settle()
    _conspiracy(game, 0, "goblin", set_pool)

    game.cast_from_hand(0, "Gale Swooper")
    game._settle()
    resolve_stack(game)
    assert p2.graveyard == []


def test_tablet_of_epityr_sees_another_artifact_shattered(set_pool):
    """"Whenever an artifact **you control** is put into a graveyard from the
    battlefield" asked of an artifact a Shatter has already removed: the seat
    it last had is the controller (CR 603.10a), and the Tablet's "you may pay
    {1}" is offered. On the tree before, the control seam answered no seat for
    the removed artifact and the Tablet saw only the artifacts a sweep killed."""
    atq, lea = set_pool("ATQ"), set_pool("LEA")
    p1 = PlayerState(
        name="P1",
        hand=[atq["Tablet of Epityr"], atq["Ornithopter"], lea["Shatter"]],
        library=[lea["Forest"]] * 5,
    )
    p2 = PlayerState(name="P2", library=[lea["Forest"]] * 5, hand=[lea["Shatter"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    for name in ("Tablet of Epityr", "Ornithopter"):
        game.cast_from_hand(0, name)
        resolve_stack(game)
    ornithopter = next(p for p in p1.battlefield if p.card.name == "Ornithopter")
    heard = _announced(game)

    assert game.cast_from_hand(
        0, "Shatter", target_player_index=0, target_permanent_ids=[ornithopter.permanent_id],
    ).supported
    resolve_stack(game)
    assert "Ornithopter" in [c.name for c in p1.graveyard]
    assert any(line.startswith("Whenever an artifact you control") for line in heard)

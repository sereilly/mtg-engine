"""'At the beginning of the next end step, <verb> **it**' behind a sentence
that targeted or made a permanent (found at INV W2G2, driving Spinal Embrace).

The *fronted* spelling of the sentence
``test_end_step_pronoun_names_what_was_made`` covers in its trailing one. A
delay whose opener names only a step leaves its pronoun to the sentence in
front, and the grammar read it as the bare source pronoun:

* **Apprentice Necromancer** (UDS, shipped): "Return target creature card from
  your graveyard to the battlefield. That creature gains haste. At the
  beginning of the next end step, sacrifice it." compiled the delayed half to
  ``sacrifice_self`` — and the Necromancer's own cost has already sacrificed
  it, so the ability logged "nothing left to sacrifice" and every creature it
  raised stayed for the rest of the game. Supported, every sentence claimed.

``sentence_rebinding._rebind_step_delay`` points the pronoun at the permanent
the earlier sentence was about, which lowers to the bound sacrifice the
explicit "sacrifice that creature" spelling already reached.
"""

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import face_cards
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _necromancer_table(set_pool):
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    necromancer = Permanent(card=set_pool("UDS")["Apprentice Necromancer"])
    game._put_permanent_onto_battlefield(0, necromancer, None)
    necromancer.metadata["summoning_sickness_turn"] = -99
    game.players[0].graveyard.append(set_pool("LEA")["Craw Wurm"])
    return game


def _mine(game) -> list[str]:
    return sorted(
        permanent.effective_card.name
        for permanent in game.controlled_by(game.players[0])
    )


def test_apprentice_necromancer_sacrifices_what_it_raised(set_pool):
    game = _necromancer_table(set_pool)

    assert game.activate_permanent_ability(0, "Apprentice Necromancer").supported
    resolve_stack(game)
    assert _mine(game) == ["Craw Wurm"]

    game.resolve_end_step(0)
    resolve_stack(game)

    assert _mine(game) == []
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Apprentice Necromancer", "Craw Wurm",
    ]


def test_apprentice_necromancer_cannot_sacrifice_a_creature_it_lost(set_pool):
    """CR 701.21a: "A player can't sacrifice … a permanent they don't control."
    The delayed ability's controller is the one told to sacrifice."""
    from engine.control import change_control

    game = _necromancer_table(set_pool)
    game.activate_permanent_ability(0, "Apprentice Necromancer")
    resolve_stack(game)
    (wurm,) = game.controlled_by(game.players[0])
    change_control(wurm, 1, source=wurm)
    game._sync_control()

    game.resolve_end_step(0)
    resolve_stack(game)

    assert game.is_on_battlefield(wurm)
    assert game.controller_index_of(wurm) == 1


def _delay_kinds(text: str, type_line: str = "Instant") -> list[tuple[str, dict]]:
    """(inner kind, the delay's binding keys) for every delayed trigger *text*
    compiles to."""
    program = compile_card_oracle(
        _mk_card(name="Probe", mana_cost="{1}", type_line=type_line, oracle_text=text)
    )
    assert program.supported, text
    found = []
    for instruction in _walk(program.instructions):
        if instruction.kind != "create_delayed_trigger":
            continue
        inner = [step.kind for step in _walk((instruction.payload["instruction"],))]
        binds = {
            key: value for key, value in instruction.payload.items()
            if key.startswith("binds")
        }
        found.append((inner[0] if len(inner) == 1 else inner[1], binds))
    return found


def _walk(instructions):
    for instruction in instructions:
        yield instruction
        for value in instruction.payload.values():
            nested = value if isinstance(value, (list, tuple)) else (value,)
            yield from _walk(
                [item for item in nested if hasattr(item, "kind") and hasattr(item, "payload")]
            )


def test_the_pronoun_behind_a_step_names_the_target_in_front():
    assert _delay_kinds(
        "Target creature gets +2/+2 until end of turn. "
        "At the beginning of the next end step, sacrifice it."
    ) == [("sacrifice_bound_permanent", {"binds_target": True})]
    assert _delay_kinds(
        "Gain control of target creature until end of turn. "
        "At the beginning of the next end step, destroy it."
    ) == [("destroy_bound_permanent", {"binds_target": True})]


def test_the_pronoun_behind_a_step_with_nothing_in_front_still_names_the_source():
    """No earlier sentence chose or made a permanent, so "it" is the ability's
    own source — Dark Maze's reading, which must not move."""
    assert _delay_kinds(
        "{0}: This creature gets +1/+1 until end of turn. "
        "At the beginning of the next end step, sacrifice it.",
        type_line="Creature — Wall",
    ) == [("sacrifice_self", {"binds_target": False})]


def test_a_player_or_any_target_in_front_is_not_an_antecedent():
    """"it" needs one *object* in front of it. "Any target" may be a player
    (Scars of the Veteran's handler reads its own shield record instead), and
    two targets are not one."""
    assert _delay_kinds(
        "{T}: This creature deals 1 damage to any target. "
        "At the beginning of the next end step, sacrifice it.",
        type_line="Creature — Wall",
    ) == [("sacrifice_self", {"binds_target": False})]


# --- the census ------------------------------------------------------------

_SELF_KINDS = {"sacrifice_self", "destroy_self", "exile_self"}

#: Kinds that leave a permanent for a later "it" to name: a step that put one
#: onto the battlefield, or took or untapped a single target.
_LEAVES_A_PERMANENT = {
    "reanimate_creature", "gain_control_of_target", "gain_control_until_eot",
    "untap_target_permanent", "put_card_from_hand_onto_battlefield",
}


def _source_delays_behind_a_permanent(card) -> tuple[int, list[str]]:
    """(delays examined, the ones acting on the source behind a step that left
    a permanent) over every program *card* compiles to."""
    program = compile_card_oracle(card)
    examined, hits = 0, []
    for instruction in _walk(program.instructions):
        if instruction.kind != "sequence":
            continue
        steps = list(instruction.payload.get("steps") or ())
        for index, step in enumerate(steps):
            if step.kind != "create_delayed_trigger":
                continue
            examined += 1
            if step.payload.get("event") != "next_end_step":
                continue
            inner = {one.kind for one in _walk((step.payload["instruction"],))}
            before = {earlier.kind for earlier in steps[:index]}
            if inner & _SELF_KINDS and before & _LEAVES_A_PERMANENT:
                hits.append(card.name)
    return examined, hits


def test_no_shipped_step_delay_behind_a_made_or_taken_permanent_acts_on_its_source():
    """The class, pool-wide: a ``next_end_step`` delay created behind a step
    that left a permanent must not sacrifice / destroy / exile the *source*.

    Validated backwards — on the tree before the rebinder this named
    Apprentice Necromancer — and floored, so a census that stopped finding
    delayed triggers at all cannot pass as a clean pool.
    """
    seen = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            for face in (face_cards(card) or (card,)):
                seen.setdefault(face.name, face)
    examined, hits = 0, []
    for card in seen.values():
        count, found = _source_delays_behind_a_permanent(card)
        examined += count
        hits.extend(found)

    assert examined >= 60, f"only {examined} delayed triggers examined"
    assert hits == [], hits

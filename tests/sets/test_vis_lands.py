"""Per-card tests for Visions' lands.

See tests/sets/README.md for the convention: get cards through
``set_pool("VIS")`` / ``set_cards("VIS")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block headed
``# --- W<wave>G<n>: <topic> ---`` and puts **its own imports at the top of its
own block**, not in a shared header. That is deliberate. The mechanical merge
for this file is "take ours, append the branch's block", and a branch that added
an import to a shared header loses it in exactly that move.

Do not edit the text above this paragraph, and do not edit an earlier group's
block.
"""

from __future__ import annotations


# --- W1G5: the pronoun's type test (Griffin Canyon) ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec


def _g5_canyon(set_pool):
    """Griffin Canyon, a tapped Griffin and a bystander, all able to act."""
    vis, mir, lea = set_pool("VIS"), set_pool("MIR"), set_pool("LEA")
    canyon = Permanent(card=vis["Griffin Canyon"])
    griffin = Permanent(card=mir["Ekundu Griffin"])
    bystander = Permanent(card=lea["Grizzly Bears"])
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[canyon, griffin, bystander],
            library=[lea["Island"]] * 6,
        ),
        PlayerState(name="P2", library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    for permanent in (canyon, griffin, bystander):
        permanent.metadata["summoning_sickness_turn"] = -99
    griffin.tapped = True
    return game, canyon, griffin, bystander


def test_griffin_canyons_second_ability_is_no_longer_hollow(set_pool):
    """"{T}: Untap target Griffin. If it's a creature, it gets +1/+1 until end
    of turn."

    The card reported **supported** on its mana ability alone while this line
    produced no instruction at all and the activation picker offered nothing —
    two independent failures on one line, and only ``--hollow-lines`` and
    ``picker_sweep.py`` could see either.

    The refusal was in the *lowering*: "if it's a creature" parses as the clause
    Track Down prints, which asks about a card an earlier sentence revealed, and
    with no reveal in front of it the condition rightly refused. The parse
    cannot tell the two apart — Prophecy prints "reveal the top card …, if it's
    a land" and this prints "untap target Griffin, if it's a creature" — so what
    separates them is the *producer*, which is only in view at lowering.
    """
    program = compile_card_oracle(set_pool("VIS")["Griffin Canyon"])
    untap = [
        ability for ability in program.activated_abilities
        if "untap" in ability.normalized_effect
    ]
    assert len(untap) == 1
    assert untap[0].supported, untap[0].normalized_effect
    assert untap[0].instruction is not None

    steps = untap[0].instruction.payload["steps"]
    assert steps[0].kind == "untap_target_permanent"
    assert steps[1].payload["condition"] == {
        "kind": "target_is_type", "card_types": ["creature"],
        "type_match": "any", "negated": False, "target": "permanent",
    }

    # The picker half. This was `None`, which is the exact value the client
    # tests to decide whether to ask for a target — the Roots class.
    assert derive_activation_spec(untap[0]) == {
        "kind": "creature", "filter": {"subtype_filter": "griffin"},
    }


def test_griffin_canyon_untaps_and_pumps_the_griffin_it_named(set_pool):
    """The Rock Hydra test: drive it and read the board."""
    game, _canyon, griffin, bystander = _g5_canyon(set_pool)

    result = game.activate_permanent_ability(
        0, "Griffin Canyon", ability_index=1,
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(griffin),
    )
    assert result.supported
    game.resolve_stack()

    assert not griffin.tapped
    assert (griffin.effective_power, griffin.effective_toughness) == (3, 3)
    # The bystander is not a Griffin and took nothing.
    assert (bystander.effective_power, bystander.effective_toughness) == (2, 2)


def test_the_canyons_mana_ability_still_works(set_pool):
    """The line that made the card read "supported" while the other did
    nothing. It is still the first ability and it still adds {C}."""
    program = compile_card_oracle(set_pool("VIS")["Griffin Canyon"])
    assert program.activated_abilities[0].instruction.payload == {
        "pips": (("C", 1),),
    }

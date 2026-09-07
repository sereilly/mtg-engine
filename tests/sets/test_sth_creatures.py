"""Stronghold creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: damage prevention, redirection and damage-event triggers ---
import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import _nosick


def _w1g1_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g1_bear(name="Bear", power=2, toughness=2):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


#: The sentence all five en-Kor creatures print, word for word.
_W1G1_EN_KOR = (
    "{0}: The next 1 damage that would be dealt to this creature this turn "
    "is dealt to target creature you control instead."
)
_W1G1_EN_KOR_NAMES = (
    "Lancers en-Kor", "Nomads en-Kor", "Shaman en-Kor", "Spirit en-Kor",
    "Warrior en-Kor",
)


@pytest.mark.parametrize("name", _W1G1_EN_KOR_NAMES)
def test_every_en_kor_compiles_the_shared_redirect(set_pool, name):
    """The set's largest cards-per-sentence cluster: five creatures, one printed
    line between them.

    Parametrized rather than written five times because that is the claim worth
    making — the production is the *sentence*, so a card that reached this
    behaviour by any other route (a hook, a near-miss template) would be a
    second implementation of one line. The payload assertion is the narrowing:
    "you control" is re-checked at resolution, and a description that lost it
    would let an en-Kor push its damage onto an opponent's creature.
    """
    card = set_pool("STH")[name]
    assert _W1G1_EN_KOR in card.oracle_text
    program = compile_card_oracle(card)

    assert program.supported
    ability = next(
        a for a in program.activated_abilities
        if a.instruction.kind == "redirect_next_damage_from_source_until_eot"
    )
    assert ability.instruction.payload["amount"] == 1
    assert ability.instruction.payload["targets"]["filter"] == {
        "type_filter": "creature", "controller": "you",
    }
    # The picker the activation raises, which is the other half of "you
    # control": an ability offering an opponent's creatures would let the
    # player announce a target the handler then refuses.
    assert derive_activation_spec(ability) == {"kind": "creature", "own_only": True}


def test_nomads_en_kor_moves_one_point_onto_the_creature_it_named(set_pool):
    """"{0}: The next 1 damage that would be dealt to this creature this turn is
    dealt to target creature you control instead."

    A redirect, not a shield: the damage is still dealt in full by the same
    source and only its recipient changes for the one point the record covers.
    So the assertion is on all three numbers — the point landing on the taker,
    nothing extra marked on the en-Kor, and the *remainder* staying where it was
    aimed. A record that ate the whole event would be a shield wearing a
    redirect's name, and free of a Kor that costs {0} to activate.
    """
    game = _w1g1_duel()
    p1, _ = game.players
    kor = _nosick(Permanent(card=set_pool("STH")["Nomads en-Kor"]))
    taker = _nosick(Permanent(card=_w1g1_bear("Taker", toughness=5)))
    p1.battlefield.extend([kor, taker])

    result = game.activate_permanent_ability(
        0, "Nomads en-Kor", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported

    game._mark_damage_on_permanent(kor, 3)

    assert taker.damage_marked == 1, "one point moved, as the card counts them"
    assert kor.damage_marked == 2, "and the rest landed where it was aimed"


def test_an_en_kor_can_only_aim_at_a_creature_its_controller_controls(set_pool):
    """"target creature **you control**" (CR 109.5: the activating player's
    "you").

    The printed narrowing is only done when something enforces it, and it is
    enforced twice — the picker offers one seat's creatures and the handler
    re-checks the phrase at resolution (CR 608.2b). This is the second half: an
    activation naming an opponent's creature redirects nothing rather than
    stapling a free damage-mover onto every board in the game.
    """
    game = _w1g1_duel()
    p1, p2 = game.players
    kor = _nosick(Permanent(card=set_pool("STH")["Warrior en-Kor"]))
    theirs = _nosick(Permanent(card=_w1g1_bear("Their Bear", toughness=5)))
    p1.battlefield.append(kor)
    p2.battlefield.append(theirs)

    game.activate_permanent_ability(
        0, "Warrior en-Kor", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game._mark_damage_on_permanent(kor, 3)

    assert theirs.damage_marked == 0
    assert kor.damage_marked == 3


def test_shaman_en_kor_moves_a_chosen_sources_damage_onto_itself(set_pool):
    """"{1}{W}: The next time a source of your choice would deal damage to
    target creature this turn, that damage is dealt to this creature instead."

    Two announcements in one activation, and the test is written to separate
    them: the **creature** is a target (CR 601.2c) and the **source** is
    CR 615.8's choice, which is not a target at all. Being a "next time" rather
    than a counted pool, the whole instance moves however large it is — three
    points here, so a record that carried an ``amount`` of 1 would leave two
    behind.

    Only the chosen source's damage moves. The second assertion is the one that
    matters: a record armed against every source would make one activation of a
    two-mana ability protect the creature from the whole turn.
    """
    game = _w1g1_duel()
    p1, p2 = game.players
    shaman = _nosick(Permanent(card=set_pool("STH")["Shaman en-Kor"]))
    friend = _nosick(Permanent(card=_w1g1_bear("Friend", toughness=5)))
    chosen = _nosick(Permanent(card=_w1g1_bear("Chosen Source")))
    bystander = _nosick(Permanent(card=_w1g1_bear("Bystander")))
    p1.battlefield.extend([shaman, friend])
    p2.battlefield.extend([chosen, bystander])

    program = compile_card_oracle(shaman.card)
    ability_index = next(
        i for i, a in enumerate(program.activated_abilities)
        if a.instruction.kind
        == "redirect_chosen_source_damage_off_target_until_eot"
    )
    result = game.activate_permanent_ability(
        0, "Shaman en-Kor", permanent_index=0, ability_index=ability_index,
        target_player_index=0, target_permanent_index=1,
        source_seat=1, source_permanent_index=0,
    )
    assert result.supported

    game._mark_damage_on_permanent(friend, 3, source=chosen)
    assert friend.damage_marked == 0, "the whole instance moved, not one point"
    assert shaman.damage_marked == 3

    game._mark_damage_on_permanent(friend, 2, source=bystander)
    assert friend.damage_marked == 2, "another source's damage is not the card's"
    assert shaman.damage_marked == 3

"""Invasion sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: split cards ---
import pytest as _w1g2_pytest

from engine import Game as _W1G2SorceryGame
from engine.card_loader import manifest_set_path as _w1g2_manifest_set_path
from engine.faces import face_cards as _w1g2_sorcery_faces
from engine.models import Permanent as _W1G2SorceryPermanent
from engine.models import PlayerState as _W1G2SorceryPlayerState
from engine.oracle import compile_card_oracle as _w1g2_sorcery_compile
from engine.targeting import derive_cast_spec as _w1g2_sorcery_cast_spec


def _w1g2_sorcery_duel(set_pool):
    """Two seats that pay for what they cast — the halves of a split card are
    told apart by their costs (CR 709.3a)."""
    filler = set_pool("LEA")["Forest"]
    game = _W1G2SorceryGame(players=[
        _W1G2SorceryPlayerState(name="P0", library=[filler] * 10),
        _W1G2SorceryPlayerState(name="P1", library=[filler] * 10),
    ])
    game.enforce_mana_costs = True
    w1g2_sorcery_seats = (game, game.players[0], game.players[1])
    return w1g2_sorcery_seats


def _w1g2_sorcery_permanent(game, set_pool, seat, name, code="LEA"):
    w1g2_sorcery_entered = _W1G2SorceryPermanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, w1g2_sorcery_entered, None)
    return w1g2_sorcery_entered


def test_w1g2_the_two_sorcery_split_cards_compile_one_spell_per_half(set_pool):
    expected = {
        "Pain // Suffering": [("Pain", "{B}", {"kind": "player"}),
                              ("Suffering", "{3}{R}", {"kind": "land"})],
        "Assault // Battery": [("Assault", "{R}", {"kind": "any"}),
                               ("Battery", "{3}{G}", None)],
    }
    for name, halves in expected.items():
        card = set_pool("INV")[name]
        assert _w1g2_sorcery_compile(card).supported
        found = [
            (half.name, half.mana_cost,
             _w1g2_sorcery_cast_spec(half, _w1g2_sorcery_compile(half)))
            for half in _w1g2_sorcery_faces(card)
        ]
        assert found == halves, name
        assert all(half.type_line == "Sorcery" for half in _w1g2_sorcery_faces(card))


def test_w1g2_pain_makes_the_target_player_discard_a_card_of_their_choice(set_pool):
    """`Target player discards a card.` The **discarding** player chooses
    (CR 701.9a), so an interactive seat is asked; one card leaves that hand."""
    game, p0, p1 = _w1g2_sorcery_duel(set_pool)
    game.interactive_seats = {1}
    split = set_pool("INV")["Pain // Suffering"]
    p0.hand.append(split)
    p1.hand.extend([set_pool("LEA")["Grizzly Bears"], set_pool("LEA")["Lightning Bolt"]])
    p0.mana_pool["B"] = 1

    assert game.queue_from_hand(0, "Pain", target_player_index=1).supported
    game.resolve_top_of_stack()
    owed = next(iter(game.pending_choices_of("discard")))
    assert owed.player_index == 1 and owed.data["count"] == 1
    assert len(p1.hand) == 2, "nothing is discarded until P1 chooses"
    assert p0.graveyard == [], "CR 608.2n: Pain is not binned mid-resolution"
    game.auto_resolve_pending_choices()
    game._settle()

    assert len(p1.hand) == 1 and len(p1.graveyard) == 1
    assert game.stack == [] and p0.graveyard == [split]
    assert p0.mana_pool["B"] == 0


def test_w1g2_suffering_destroys_a_land_and_only_a_land(set_pool):
    """`Destroy target land.` For {3}{R}; a creature is refused unpaid."""
    game, p0, p1 = _w1g2_sorcery_duel(set_pool)
    land = _w1g2_sorcery_permanent(game, set_pool, 1, "Forest")
    bears = _w1g2_sorcery_permanent(game, set_pool, 1, "Grizzly Bears")
    split = set_pool("INV")["Pain // Suffering"]
    p0.hand.append(split)
    p0.mana_pool["R"] = 4

    refused = game.cast_from_hand(0, "Suffering", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and p0.mana_pool["R"] == 4

    assert game.cast_from_hand(0, "Suffering", target_permanent_ids=[land.permanent_id]).supported
    assert [card.name for card in p1.graveyard] == ["Forest"]
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Grizzly Bears"]
    assert p0.mana_pool["R"] == 0 and p0.graveyard == [split]


def test_w1g2_assault_deals_two_damage_to_a_creature_or_a_player(set_pool):
    """`Assault deals 2 damage to any target.` The self-reference is the
    **half's** name — the reason a half compiles as a card of its own — and the
    spell is red: it is not green (CR 709.3b)."""
    game, p0, p1 = _w1g2_sorcery_duel(set_pool)
    bears = _w1g2_sorcery_permanent(game, set_pool, 1, "Grizzly Bears")
    split = set_pool("INV")["Assault // Battery"]
    p0.hand.extend([split, split])
    p0.mana_pool["R"] = 2

    assert game.queue_from_hand(0, "Assault", target_permanent_ids=[bears.permanent_id]).supported
    assert tuple(game._stack_item_colors(game.stack[-1])) == ("R",)
    game._settle()
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]

    assert game.cast_from_hand(0, "Assault", target_player_index=1).supported
    assert p1.life == 18
    assert "Assault resolved and moved to graveyard" in game.log
    assert p0.graveyard == [split, split] and p0.mana_pool["R"] == 0


def test_w1g2_battery_creates_a_three_three_green_elephant(set_pool):
    """`Create a 3/3 green Elephant creature token.` For {3}{G}, with no
    target to choose."""
    game, p0, _p1 = _w1g2_sorcery_duel(set_pool)
    split = set_pool("INV")["Assault // Battery"]
    p0.hand.append(split)
    p0.mana_pool["G"] = 4

    assert game.cast_from_hand(0, "Battery").supported

    (elephant,) = game.controlled_by(0)
    assert elephant.metadata.get("is_token")
    assert (elephant.effective_power, elephant.effective_toughness) == (3, 3)
    assert set(elephant.effective_colors) == {"G"}
    assert elephant.has_type("creature") and "Elephant" in elephant.effective_card.type_line
    assert p0.graveyard == [split] and p0.mana_pool["G"] == 0


@_w1g2_pytest.mark.slow
def test_w1g2_the_ai_casts_split_cards_as_halves_without_a_refusal():
    """The simulator deals whole split cards and its policy scores each half as
    the spell it is (`ai_policy.hand_spells`), pays for the one it picks and
    casts it by the half's name. A policy that proposed the *card* would be
    refused every turn (CR 709.3), and a half that reached a graveyard without
    becoming the whole card again would fail the zone-conservation audit under
    a name the deck never held."""
    from engine.ai_simulator import run_ai_simulation

    names = [
        "Assault // Battery", "Pain // Suffering", "Spite // Malice",
        "Stand // Deliver", "Wax // Wane",
    ]
    halves = {half for name in names for half in name.split(" // ")}
    report = run_ai_simulation(
        [_w1g2_manifest_set_path("INV", include_measured=True)],
        games=6, seed=77, max_turns=16, required_cards=names,
    )

    cast = {
        half for half in halves
        if any(f" cast {half} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 4, f"only {sorted(cast)} were cast"
    refused = [
        key for key in report.refused_casts
        if key.split(":")[0] in halves | set(names)
    ]
    assert refused == []
    leaks = [
        issue.message for issue in report.issues
        if any(half in issue.message for half in halves)
        and "Unsupported card" not in issue.message
    ]
    w1g2_no_half_leaked = leaks == []
    assert w1g2_no_half_leaked, leaks

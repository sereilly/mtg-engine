"""Census: "is the player this cast names helped by it?" — one answer, two readers.

Two callers have to aim a cast at a seat with nothing else to go on:

* the **web route's default** for a cast whose announcement named no seat
  (``web/action_helpers._default_target``): the caster's own where the spell
  gives something to the player it names, the opposing one otherwise;
* the **AI's tie-break** between seats a rehearsal measures alike
  (``ai_valuation.spell_seat_side``, under ``ai_policy._choose_target_for_spell``).

Each had its own derivation — a private ``_SEAT_GIFT_KINDS`` in
``engine/targeting.py`` and another, with different contents, in
``engine/ai_valuation.py`` — introduced by two branches of one round. So the
same card could be a gift on one road and not on the other: "untap all lands
target player controls" (Early Harvest) was the AI's own and a person's
opponent's; "target player draws three cards" (Ancestral Recall) was a gift
by list for a person and nobody's for the AI.

It is one derivation now (``ai_valuation.cast_helps_the_player_it_names``)
and this sweep holds the two readers to it: every supported instant and
sorcery — each mode of a caster-chosen modal one — whose first described slot
admits a player, both readers asked.

Validated backwards on the tree with two lists: **23 of 178** disagreed —
ten "target player gains life", eight "target player draws", the two untaps
(Early Harvest, and Reins of Power, which prints "target opponent"), a
reflecting shield (Honorable Passage), Juxtapose and Leeches. After: none,
and ``GIFTS`` below is what both say.

One kind was in neither list: ``grant_extra_turn``. An AI seat holding Time
Warp gave the extra turn to its opponent, and a person's cast that named no
seat did the same.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine import Game, PlayerState
from engine.ai_valuation import considering_mode, spell_seat_side
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from engine.targeting import _first_described_slot, announced_mode_instructions
from web import action_helpers

#: The spec kinds whose candidates include a player's face.
SEAT_SPEC_KINDS = frozenset({"player", "player_or_planeswalker", "any"})

#: The instruction kinds, in a player-admitting first slot, that both readers
#: call a gift to the player named — the whole list, so that a kind joining or
#: leaving it is a line in a diff.
GIFTS = frozenset({
    "draw_target_cards", "target_gains_life", "grant_extra_turn",
    "untap_all_matching", "grant_prevention_shield",
    "grant_reflecting_prevention_shield",
    "remove_all_counters_from_target_player",
    # "Creatures target player controls get +1/+1 until end of turn." (Day,
    # of Night // Day.) A gift by its family; reached once a split card's
    # half named its player as a target.
    "buff_creatures_global",
})


def _pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


POOL = _pool()


def population() -> list:
    """``(card, mode, spec, instruction)`` for every supported instant and
    sorcery — each mode of a caster-chosen modal one — whose first described
    slot admits a player."""
    found = []
    for name in sorted(POOL):
        card = POOL[name]
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        chooses = bool(program.modes) and program.mode_chooser is None
        for mode in (range(len(program.modes)) if chooses else (None,)):
            slot = _first_described_slot(announced_mode_instructions(program, mode))
            if slot is None or slot[0].get("kind") not in SEAT_SPEC_KINDS:
                continue
            found.append((card, mode, slot[0], slot[1]))
    return found


def web_says_gift(card, mode) -> bool:
    """The web route's default seat for a cast of *card* that named none is
    the caster's own."""
    players = [PlayerState(name="P1"), PlayerState(name="P2")]
    players[0].hand.append(card)
    game = Game(players=players)
    request = SimpleNamespace(from_zone=None, mode_index=mode)
    return action_helpers._default_target(game, 0, card.name, request) == 0


def ai_says_gift(card, mode) -> bool:
    """The AI's tie-break for *card*, weighed in *mode*, is the caster's own
    seat."""
    with considering_mode(card, mode):
        return spell_seat_side(card) == "you"


def census() -> list:
    return [
        {
            "card": card.name, "mode": mode, "kind": instruction.kind,
            "opponents_only": bool(spec.get("opponents_only")),
            "web": web_says_gift(card, mode), "ai": ai_says_gift(card, mode),
        }
        for card, mode, spec, instruction in population()
    ]


def tag(row) -> tuple:
    return (row["card"], row["mode"])


@pytest.fixture(scope="module")
def rows() -> list:
    return census()


def test_the_sweep_examined_the_pool(rows):
    """The floor: a sweep that reaches nothing passes everything."""
    assert len(rows) >= 170
    assert len({row["kind"] for row in rows}) >= 45
    # ...and both answers are in it, on both readers.
    assert sum(row["web"] for row in rows) >= 25
    assert sum(not row["web"] for row in rows) >= 120


def test_the_two_readers_agree(rows):
    disagree = {
        tag(row): (row["kind"], f"web={row['web']}", f"ai={row['ai']}")
        for row in rows if row["web"] != row["ai"]
    }
    assert disagree == {}


def test_what_is_a_gift_is_the_named_list(rows):
    """By kind, so the list is readable: every row both readers call a gift
    is one of ``GIFTS``, and every row of one of those kinds is a gift unless
    the card prints "target **opponent**"."""
    assert {row["kind"] for row in rows if row["web"]} == GIFTS
    withheld = {
        tag(row) for row in rows
        if row["kind"] in GIFTS and not row["web"] and not row["opponents_only"]
    }
    assert withheld == set()


@pytest.mark.parametrize("name, mode", [
    # The untap the AI knew and the web default did not.
    ("Early Harvest", None),
    # Draws and life, which the web default knew and the AI's reading did not.
    ("Ancestral Recall", None), ("Stream of Life", None), ("Healing Salve", 0),
    # A shield, by its family.
    ("Healing Salve", 1), ("Honorable Passage", None),
    # "Target player takes an extra turn after this one": in neither list.
    ("Time Warp", None),
])
def test_a_gift_is_a_gift_on_both_roads(name, mode):
    card = POOL[name]
    assert web_says_gift(card, mode) and ai_says_gift(card, mode), name


@pytest.mark.parametrize("name, mode", [
    ("Mana Short", None), ("Mind Twist", None), ("Lightning Bolt", None),
    # "Target **opponent**": the caster is not a seat the phrase admits.
    ("Reins of Power", None),
    # A choice made off the named player's board is not a gift to them.
    ("Juxtapose", None),
    # "…that player loses 5 life **and you gain 5 life**": the gain is the
    # caster's, in a later step, and is not about the player named.
    ("Rhystic Syphon", None),
])
def test_anything_else_is_the_opponents_on_both_roads(name, mode):
    card = POOL[name]
    assert not web_says_gift(card, mode) and not ai_says_gift(card, mode), name


def test_an_ai_seat_takes_its_own_extra_turn():
    """Time Warp, "Target player takes an extra turn after this one", in an
    AI seat's hand. An extra turn shows in no standing, so the two seats
    measured alike and the tie went to the opponent: the seat paid five mana
    to give a turn away."""
    from engine.ai_policy import cast_announcement, choose_cast_action
    from tests.helpers import resolve_stack

    forest = POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[POOL["Time Warp"]], library=[forest] * 10),
        PlayerState(name="Opp", hand=[forest], library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    action = choose_cast_action(game, 0)
    assert action is not None and action.target_player_index == 0
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    assert list(game.extra_turn_queue) == [0]


if __name__ == "__main__":
    rows = census()
    disagree = [row for row in rows if row["web"] != row["ai"]]
    print(f"rows: {len(rows)}  kinds: {len({row['kind'] for row in rows})}  "
          f"web gifts: {sum(row['web'] for row in rows)}  "
          f"ai gifts: {sum(row['ai'] for row in rows)}  disagree: {len(disagree)}")
    for row in disagree:
        print("  ", tag(row), row["kind"], f"web={row['web']}", f"ai={row['ai']}")
    print("gift kinds:", sorted({row["kind"] for row in rows if row["web"] and row["ai"]}))

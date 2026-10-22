"""An AI seat that exiles a card from "a graveyard" takes it from an
opponent's — whichever chair the seat is in.

Three roads led to the wrong pile, and they shared one rule, *the first
graveyard in seat order*:

* "Exile up to three target cards from **a single graveyard**" (Decompose,
  Rapid Decay, Ebony Charm; Carrion Beetles' and Famished Ghoul's abilities)
  leaves the pile to a prompt, whose default for a seat nobody asks was the
  first live pile;
* "Exile **target card from a graveyard**" as a spell (Coffin Purge, Cremate,
  Headstone) and as an ability (Crypt Creeper, Steamclaw, Grave Robbers,
  Scavenging Ooze) was announced by the policy as a seat and no slot, and the
  handler's fallback for a bare announcement scans the seats in order.

So an AI in chair 0 exiled its own graveyard — its own flashback cards, its
own cards toward threshold — and the same AI in chair 1 exiled its
opponent's, off the same board. W1G6 reported the first road; the census here
found the second and counts both: **eleven cards** on the tree before the
change, every one of them wrong from chair 0 and right from chair 1. (The
four on the first road have since been made an *announcement* by a sibling
group — CR 601.2c, named when the spell is cast — which takes the prompt off
their road; the default it leaves behind, for the same sentence under a
trigger, is the one stated here.)

The sweep plays every supported card in both manifest roles whose program
exiles a graveyard card somebody chooses, as the AI in each chair, and asks
which pile a card left. Validated backwards: with the two defaults restored it
names them.
"""
from __future__ import annotations

import random

import pytest

from engine import Game, PlayerState, ai_policy
from engine.ai_policy import (cast_announcement, choose_activation_action,
                              choose_cast_action, spell_being_cast,
                              tap_planned_lands)
from engine.ai_valuation import (GRAVEYARD_DENIAL_KINDS, _walk_program,
                                 denied_graveyard_pile,
                                 exiles_a_graveyard_target,
                                 graveyard_denial_order)
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import castable_faces
from engine.game_types import OracleExecutionContext
from engine.handlers import EFFECT_HANDLERS
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import announced_mode_instructions
from tests.helpers import _mk_card, _nosick, resolve_stack

POOL = load_cards(manifest_set_paths(include_measured=True))
BY_NAME: dict = {}
for _card in POOL:
    BY_NAME.setdefault(_card.name, _card)

_COST = "{50}"  # more than any rig holds: these are targets, not casts


def _yard(tag: str) -> list:
    """What one graveyard holds, named for the seat that owns it."""
    return [
        _mk_card(name=f"{tag} Buried Beast", mana_cost=_COST,
                 type_line="Creature - Beast", colors=("G",), power=3, toughness=3),
        _mk_card(name=f"{tag} Buried Instant", mana_cost=_COST, type_line="Instant",
                 oracle_text="Draw a card.", colors=("U",)),
        _mk_card(name=f"{tag} Buried Sorcery", mana_cost=_COST, type_line="Sorcery",
                 oracle_text="Draw a card.", colors=("R",)),
        _mk_card(name=f"{tag} Buried Artifact", mana_cost=_COST, type_line="Artifact"),
    ]


def _zoo(tag: str) -> list:
    return [
        _mk_card(name=f"{tag} Bear", type_line="Creature - Bear", colors=("G",)),
        _mk_card(name=f"{tag} Relic", type_line="Artifact"),
    ]


def rig(held, seat: int, *, yards=None):
    """A game with the AI in chair *seat*, *held* in its hand, eight mana of
    each colour floating, and a graveyard for each seat ("AI …" / "Opp …")."""
    forest = BY_NAME["Forest"]
    players = []
    for index in (0, 1):
        tag = "AI" if index == seat else "Opp"
        pile = _yard(tag) if yards is None else list(yards[tag])
        players.append(PlayerState(
            name=tag, library=[forest] * 10, graveyard=pile,
            battlefield=[_nosick(Permanent(card=card)) for card in _zoo(tag)],
        ))
    game = Game(players=players)
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = seat
    game._sync_control()
    players[seat].mana_pool.update({symbol: 8 for symbol in "WUBRG"})
    if held is not None:
        players[seat].hand.append(held)
    return game


def _settle(game) -> None:
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    game.auto_resolve_pending_choices()


def play(held, spell, seat: int, *, yards=None):
    """Cast *spell* as the AI in chair *seat* through its own choosers, and —
    for a permanent — activate it once. Returns the game, or None when the
    seat does not make the play."""
    game = rig(held, seat, yards=yards)
    action = choose_cast_action(game, seat)
    if action is None or action.card_name != spell.name:
        return None
    zone = ai_policy.zone_being_cast_from(game, seat, action)
    tap_planned_lands(game, seat, action)
    result = game.cast_from_hand(
        seat, spell_being_cast(zone, action).name, **cast_announcement(action),
    )
    _settle(game)
    if not result.supported:
        return None
    if spell.primary_type in ("instant", "sorcery"):
        return game
    for permanent in game.controlled_by(seat):
        if permanent.card.name == spell.name:
            permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].mana_pool.update({symbol: 8 for symbol in "WUBRG"})
    activation = choose_activation_action(game, seat)
    if activation is None or activation.permanent_name != spell.name:
        return game
    tap_planned_lands(game, seat, activation)
    game.activate_permanent_ability(
        seat, activation.permanent_name,
        target_player_index=activation.target_player_index,
        permanent_index=activation.permanent_index,
        target_permanent_index=activation.target_permanent_index,
        target_role_refs=activation.target_role_refs,
    )
    _settle(game)
    return game


def piles_exiled_from(game) -> set[str]:
    """Whose planted graveyard cards are now in exile: ``{"AI", "Opp"}``."""
    return {
        card.name.split(" ")[0]
        for player in game.players for card in player.exile
        if " Buried " in card.name
    }


def chooses_whose_graveyard(spell) -> bool:
    """Whether *spell*'s program exiles a graveyard card its controller picks
    the pile of: a targeted card "from a graveyard", or cards "from a single
    graveyard"."""
    program = compile_card_oracle(spell)
    steps = list(_walk_program(program))
    # A modal spell's later bullets are not in ``instructions`` (those are
    # mode 0's): "• Exile up to three target cards from a single graveyard."
    # is Ebony Charm's second.
    for index in range(len(program.modes or ())):
        steps.extend(announced_mode_instructions(program, index))
    for instruction in steps:
        if instruction.kind in GRAVEYARD_DENIAL_KINDS:
            return True
        if (
            instruction.kind == "exile_cards_from_graveyard"
            and (instruction.payload or {}).get("graveyard_owner") == "chosen"
        ):
            return True
    return False


def census() -> list[dict]:
    rows = []
    for held in POOL:
        for spell in castable_faces(held):
            if not compile_card_oracle(spell).supported:
                continue
            if not chooses_whose_graveyard(spell):
                continue
            for seat in (0, 1):
                random.seed(20261012)
                game = play(held, spell, seat)
                rows.append({
                    "card": spell.name, "seat": seat, "played": game is not None,
                    "from": set() if game is None else piles_exiled_from(game),
                })
    return rows


# --- the sweep ------------------------------------------------------------------

@pytest.fixture(scope="module")
def rows() -> list:
    return census()


def test_the_sweep_examined_the_cards_that_choose_a_graveyard(rows):
    """The floor: the eleven the old defaults got wrong, at least, and each
    actually played from both chairs."""
    cards = {row["card"] for row in rows}
    assert len(cards) >= 11, sorted(cards)
    assert {"Coffin Purge", "Decompose", "Rapid Decay", "Scavenging Ooze",
            "Carrion Beetles", "Famished Ghoul", "Steamclaw"} <= cards
    exiled = {row["card"] for row in rows if row["from"]}
    assert len(exiled) >= 11, sorted(exiled)


def test_graveyard_denial_takes_the_opponents_pile_from_either_chair(rows):
    wrong = sorted(
        f"{row['card']} from chair {row['seat']}: exiled from {sorted(row['from'])}"
        for row in rows if "AI" in row["from"]
    )
    assert wrong == []


def test_the_chair_does_not_change_what_a_card_does(rows):
    """The shape of the defect, stated on its own: one card, one board, two
    chairs, two different piles."""
    by_card: dict = {}
    for row in rows:
        by_card.setdefault(row["card"], {})[row["seat"]] = (row["played"], row["from"])
    differ = sorted(name for name, seats in by_card.items() if seats[0] != seats[1])
    assert differ == []


#: The cards a bare announcement of **one** targeted graveyard card sent to the
#: AI's own pile from chair 0 — the handler's seat-order scan.
_ONE_TARGET_WRONG_BEFORE = {
    "Coffin Purge", "Cremate", "Crypt Creeper", "Grave Robbers", "Headstone",
    "Scavenging Ooze", "Steamclaw",
}
#: …and the four whose pile was the prompt's default ("from a single
#: graveyard"). On a tree where those cards are *announced* rather than picked
#: at resolution, the prompt is no longer on their road and they are not in
#: the wrong set either way — so the backwards test below holds them to
#: "nothing outside the eleven", not to being there.
#:
#: Gravegouger (Torment: "When this creature enters, exile up to two target
#: cards from a single graveyard") joined them in Torment's second wave
#: (W2G2). Its pile was the resolution prompt's until then, and this backwards
#: check could demand it; its cards are announced now — by the AI as it casts
#: the creature, through the same chooser Decompose's cast uses — so with the
#: old defaults restored it reaches the opponent's pile from both chairs, and
#: it is held to "nothing outside" like the four.
_SINGLE_PILE_WRONG_BEFORE = {
    "Carrion Beetles", "Decompose", "Famished Ghoul", "Gravegouger", "Rapid Decay",
}


def test_the_sweep_names_the_defect_with_the_old_defaults_restored(monkeypatch):
    """Backwards: put "the first pile in seat order" back on both roads and
    the sweep must name the cards — every one wrong from chair 0 and right
    from chair 1, which is why nobody playing the AI from the guest's seat
    saw it. A sweep that read clean here would be a sweep that reads nothing."""
    from engine import ai_valuation
    from engine.mixins.stack import activation as activation_path
    from engine.mixins.stack import card_activation as card_activation_path
    from engine.mixins.stack import casting as casting_path

    monkeypatch.setattr(
        ai_valuation, "denied_graveyard_pile",
        lambda player_index, piles: (list(piles) or [None])[0],
    )
    monkeypatch.setattr(ai_policy, "_graveyard_denial_target", lambda *args: None)
    # …and the engine's own answer to an announcement naming nothing, which
    # since R3 is the picker's first entry in standing order — the opposing
    # pile first — rather than the handler's scan in seat order. Left on, it
    # puts the denial in the right pile whatever the policy does.
    # Asked on both activation roads: a permanent's and a graveyard card's
    # (``card_activation.activate_from_graveyard``).
    for path in (activation_path, card_activation_path):
        monkeypatch.setattr(
            path, "default_activation_target", lambda *a, **k: None
        )
    monkeypatch.setattr(
        casting_path, "default_cast_target", lambda *a, **k: (None, False)
    )

    old = census()

    wrong = {r["card"] for r in old if "AI" in r["from"] and r["seat"] == 0}
    assert _ONE_TARGET_WRONG_BEFORE <= wrong, sorted(_ONE_TARGET_WRONG_BEFORE - wrong)
    assert wrong <= (_ONE_TARGET_WRONG_BEFORE | _SINGLE_PILE_WRONG_BEFORE), sorted(wrong)
    assert [r["card"] for r in old if "AI" in r["from"] and r["seat"] == 1] == []


# --- the decisions ----------------------------------------------------------------

def test_every_denial_kind_is_a_registered_handler():
    """A kind renamed out from under the set stops matching in silence."""
    assert GRAVEYARD_DENIAL_KINDS <= set(EFFECT_HANDLERS)


def test_the_pile_a_seat_denies_is_not_its_own_unless_there_is_no_other():
    assert denied_graveyard_pile(0, [0, 1]) == 1
    assert denied_graveyard_pile(1, [0, 1]) == 0
    assert denied_graveyard_pile(0, [0]) == 0
    assert denied_graveyard_pile(2, [0, 1, 2]) == 0
    assert denied_graveyard_pile(0, []) is None


def test_the_cards_their_owner_could_still_cast_go_first(set_pool):
    """Firebolt in a graveyard is a spell its owner still holds (CR 702.34a).
    The pick a seat nobody asks makes out of **another** seat's pile takes it
    before the cards in front of it; a pile with no flashback card is taken in
    pile order as it always was. The seat's **own** pile is a price, and gives
    the least valuable up first — the Firebolt last of all
    (``ai_valuation.graveyard_price_order``, Torment's W2G3; it was pile
    order).

    The prompt is armed by hand, so this is about the default and not about
    which card's road reaches it."""
    ody = set_pool("ODY")
    pile = [
        BY_NAME["Grizzly Bears"], BY_NAME["Hill Giant"], BY_NAME["Craw Wurm"],
        BY_NAME["Scryb Sprites"], ody["Firebolt"],
    ]

    # Decompose's own description of what it may exile ("up to three …
    # cards"), so the pick is offered exactly the cards the card names.
    payload = compile_card_oracle(ody["Decompose"]).instructions[0].payload
    assert payload.get("count") == 3 and payload.get("up_to")

    def pick(owner_seat: int) -> list[str]:
        yards = {"AI": [], "Opp": []}
        yards["AI" if owner_seat == 0 else "Opp"] = list(pile)
        game = rig(None, 0, yards=yards)
        context = OracleExecutionContext(
            caster=game.players[0], target=game.players[owner_seat],
            card=ody["Decompose"],
        )
        game.arm_graveyard_exile_pick(0, owner_seat, dict(payload), context)
        game.auto_resolve_pending_choices()
        assert game.pending_choices == []
        return sorted(card.name for card in game.players[owner_seat].exile)

    assert pick(1) == ["Firebolt", "Grizzly Bears", "Hill Giant"]
    assert pick(0) == ["Grizzly Bears", "Hill Giant", "Scryb Sprites"]
    game = rig(None, 0, yards={"AI": [], "Opp": list(pile)})
    assert graveyard_denial_order(game, 1, [0, 1, 2, 3, 4]) == [4, 0, 1, 2, 3]
    assert graveyard_denial_order(game, 1, [0, 1]) == [0, 1]


def test_a_single_target_names_the_flashback_card(set_pool):
    """Coffin Purge exiles one card: the opponent's Firebolt, not the first
    card in their pile — and not a card of the caster's own."""
    ody = set_pool("ODY")
    yards = {
        "AI": [BY_NAME["Grizzly Bears"]],
        "Opp": [BY_NAME["Hill Giant"], ody["Firebolt"], BY_NAME["Craw Wurm"]],
    }
    for seat in (0, 1):
        game = rig(ody["Coffin Purge"], seat, yards=yards)
        action = choose_cast_action(game, seat)
        assert action.card_name == "Coffin Purge"
        assert (action.target_player_index, action.target_permanent_index) == (1 - seat, 1)
        game = play(ody["Coffin Purge"], ody["Coffin Purge"], seat, yards=yards)
        opponent = game.players[1 - seat]
        assert [card.name for card in opponent.exile] == ["Firebolt"]
        assert [card.name for card in game.players[seat].graveyard][:1] == ["Grizzly Bears"]


def test_with_no_card_in_another_pile_the_announcement_is_what_it_was(set_pool):
    """Nothing to deny: the policy names no slot, as before, and the handler
    answers. (Whether the spell is worth casting then is another question.)"""
    ody = set_pool("ODY")
    yards = {"AI": [BY_NAME["Grizzly Bears"]], "Opp": []}
    game = rig(ody["Coffin Purge"], 0, yards=yards)

    action = choose_cast_action(game, 0)

    assert action is None or action.target_permanent_index is None


def test_an_exile_of_a_graveyard_target_is_recognised_through_wrappers(set_pool):
    ody = set_pool("ODY")
    assert exiles_a_graveyard_target(compile_card_oracle(ody["Coffin Purge"]).instructions)
    assert exiles_a_graveyard_target(compile_card_oracle(BY_NAME["Cremate"]).instructions)
    assert not exiles_a_graveyard_target(compile_card_oracle(BY_NAME["Raise Dead"]).instructions)
    assert not exiles_a_graveyard_target(compile_card_oracle(ody["Firebolt"]).instructions)


if __name__ == "__main__":
    found = census()
    cards = sorted({row["card"] for row in found})
    print(f"cards that choose a graveyard to exile from: {len(cards)}")
    for name in cards:
        seats = {row["seat"]: row for row in found if row["card"] == name}
        print(f"   {name}: " + "; ".join(
            f"chair {seat}: {'not played' if not seats[seat]['played'] else sorted(seats[seat]['from']) or 'nothing exiled'}"
            for seat in (0, 1)
        ))
    wrong = sorted({row["card"] for row in found if "AI" in row["from"]})
    print(f"exiled from the AI's own pile: {len(wrong)} {wrong}")

"""Regression: an activated ability naming "X target …" names at most X.

CR 601.2c (reached through CR 602.2b) fixes the number of targets from the X
announced at CR 601.2b. The cast side has sized that list from the announced X
for a long time; the activation side did not, and the handlers behind these
abilities act on every slot they are handed. So with X = 1 and two targets
named:

* **Candelabra of Tawnos** untapped two lands for {1};
* **Orcish Settlers** destroyed two lands for {1}{1}{R};
* **Runed Arch** made two creatures unblockable for {1};
* **Alexi, Zephyr Mage** (Prophecy, the round that found it) bounced both.

Nothing crashed, every card reported supported, and no compiled program was
wrong — only running a card could see it. The gate is
``legality.activation_target_refusal``'s ``x_value``: the announced X becomes the
same ``max_targets`` a defined X (the verse cycle) already became.

The sweep asks the whole pool rather than the cards above, and carries a floor
on how many abilities it examined, so a derivation that stopped reporting
``x_targets`` cannot pass it by examining nothing.
"""

from __future__ import annotations

from engine.faces import compilation_units
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import _mk_card, _nosick, resolve_stack

#: Abilities the sweep found when it was written (6 shipped + Alexi). Lower it
#: only with a reason: a smaller count means the census lost cards, not that
#: the pool got smaller.
_FLOOR = 7


def _announced_x_target_abilities():
    pool = compilation_units(load_cards(manifest_set_paths(include_measured=True)))
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None:
                continue
            spec = derive_activation_spec(ability) or {}
            cost_clause = (ability.source_line or "").lower().split(":", 1)[0]
            if spec.get("x_targets") and "{x}" in cost_clause:
                yield card, index


def _board(source_card):
    """The source on seat 0 with a hand to pay a discard; on seat 1, two of each
    kind of object the pool's "X target" lines name — tapped lands for an untap,
    small creatures for Runed Arch's "power 2 or less"."""
    bait = []
    for tapped in (True, True, False, False):
        land = _nosick(Permanent(card=_mk_card(name="Bait Land", type_line="Land")))
        land.tapped = tapped
        bait.append(land)
    for _ in range(2):
        bait.append(_nosick(Permanent(card=_mk_card(
            name="Bait Creature", type_line="Creature - Human", power=1, toughness=1,
        ))))
    filler = _mk_card(name="Filler", type_line="Creature - Human", power=1, toughness=1)
    game = Game(players=[
        PlayerState(
            name="P0", battlefield=[_nosick(Permanent(card=source_card))],
            hand=[filler] * 3,
        ),
        PlayerState(name="P1", battlefield=bait),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def test_an_announced_x_caps_the_targets_an_activation_names():
    examined = 0
    overreached: list[str] = []
    for card, index in _announced_x_target_abilities():
        game = _board(card)
        spec = game.activation_target_spec(0, 0, ability_index=index)
        named = [
            game.permanent_at(t["seat"], t["index"]).permanent_id
            for t in spec.get("valid_targets") or []
            if t.get("kind") == "permanent" and t.get("seat") == 1
        ][:2]
        assert len(named) == 2, f"{card.name}: the bait offers no two targets"
        examined += 1
        result = game.queue_permanent_ability(
            0, card.name, ability_index=index, target_player_index=1,
            x_value=1, target_permanent_ids=named,
        )
        if result.supported:
            overreached.append(card.name)
            continue
        assert "too many targets" in result.details, (card.name, result.details)
        assert game.stack == [], f"{card.name}: refused, so nothing is on the stack"

    assert examined >= _FLOOR, f"examined only {examined} abilities"
    assert not overreached, (
        "activated with X = 1 while naming two targets: " + ", ".join(overreached)
    )


def test_an_activation_naming_x_targets_still_resolves_against_all_of_them():
    """The other half: X = 2 with two named is the printed ability, and it acts
    on both — the gate narrows the announcement, not the effect."""
    pool = {card.name: card for card in load_cards(manifest_set_paths())}
    game = _board(pool["Candelabra of Tawnos"])
    tapped = [p for p in game.players[1].battlefield if p.tapped]
    result = game.queue_permanent_ability(
        0, "Candelabra of Tawnos", target_player_index=1, x_value=2,
        target_permanent_ids=[p.permanent_id for p in tapped],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert not any(p.tapped for p in tapped)

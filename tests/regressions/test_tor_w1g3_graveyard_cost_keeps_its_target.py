"""An activation that exiles graveyard cards to pay for itself still targets
the graveyard card it named (CR 601.2c, then CR 601.2h).

"{2}{B}{B}, {T}, Exile two cards from your graveyard: Return target creature
card from your graveyard to your hand." (Cabal Surgeon.) The target is a
*slot* in a graveyard, and the stack object's stamp of which card that slot
holds was taken as the object was pushed — after the cost had already taken
cards out of the same pile. Found driving Torment's linked-exile drive list:
with Lightning Bolt and Giant Growth above the targeted Grizzly Bears and a
Hill Giant beneath it, exiling the two named cards returned the **Hill Giant**,
and with no cards named the default ate the targeted Bears itself.

The census walks every supported card in both manifest roles whose activated
ability pays a graveyard-exile cost and targets a graveyard card (one card on
the day: Cabal Surgeon), plants fillers the cost can take *above* the target
and a decoy beneath it, and asks what the object on the stack names. Validated
backwards with the activation path and the stack stamp checked out at the
wave's base: the census named Cabal Surgeon for both payments (the stack
named no card at all), and each behavioural test below failed — the cost that
ate its own target returned the Hill Giant beneath it instead of fizzling.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.handlers._filters import (_card_matches_filter,
                                      graveyard_card_matches)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import graveyard_target_spec
from tests.helpers import resolve_stack

_POOL = compilation_units(load_cards(manifest_set_paths(include_measured=True)))
_BY_NAME: dict = {}
for _card in _POOL:
    _BY_NAME.setdefault(_card.name, _card)

#: Cards a planted graveyard is built from, in this order of preference.
_CANDIDATES = (
    "Lightning Bolt", "Giant Growth", "Dark Ritual", "Ancestral Recall",
    "Grizzly Bears", "Hill Giant", "Craw Wurm", "Island", "Swamp",
)


def _shapes():
    found = []
    for card in _BY_NAME.values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(program.activated_abilities):
            cost = ability.cost
            if cost is None or cost.exile_filter is None:
                continue
            if cost.exile_zone != "graveyard" or cost.exile_count == "any":
                continue
            spec = graveyard_target_spec(card, None, instruction=ability.instruction)
            if spec is not None:
                found.append((card, index, ability, spec))
    return found


def _board(card, ability, spec):
    """Seat 0: *card* on the battlefield, and a graveyard holding enough cost
    fodder above the target and a decoy that also answers the target's
    description beneath it."""
    cost = ability.cost
    wanted = int(cost.exile_count or 1)
    cards = [_BY_NAME[name] for name in _CANDIDATES if name in _BY_NAME]
    target = next(c for c in cards if graveyard_card_matches(spec, c))
    decoy = next(
        c for c in cards if c is not target and graveyard_card_matches(spec, c)
    )
    fodder = [
        c for c in cards
        if c is not target and c is not decoy
        and not graveyard_card_matches(spec, c)
        and _card_matches_filter(c, cost.exile_filter or {})
    ][:wanted]
    assert len(fodder) == wanted, card.name
    graveyard = [*fodder, target, decoy]
    p0 = PlayerState(name="P0", graveyard=graveyard, library=[_BY_NAME["Swamp"]] * 5)
    p1 = PlayerState(name="P1", library=[_BY_NAME["Swamp"]] * 5)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return game, target, len(fodder)


def _activate(game, card, index, slot, **costs):
    before = len(game.stack)
    # The queue form, which leaves the object on the stack to be read.
    result = game.queue_permanent_ability(
        0, card.name, target_player_index=0, target_permanent_index=slot,
        ability_index=index, **costs,
    )
    assert result.supported, (card.name, game.log[-3:])
    pushed = game.stack[before:]
    assert pushed, card.name
    return pushed[-1]


def test_every_graveyard_cost_activation_keeps_the_card_it_targeted():
    shapes = _shapes()
    assert len(shapes) >= 1, "the sweep found no ability of this shape"
    findings = []
    for card, index, ability, spec in shapes:
        for named_costs in (True, False):
            game, target, above = _board(card, ability, spec)
            costs = {"cost_graveyard_indices": list(range(above))} if named_costs else {}
            item = _activate(game, card, index, above, **costs)
            stamp = item.target_graveyard_card
            named = getattr(stamp, "card", None)
            if named is not target:
                findings.append(
                    f"{card.name} ({'named' if named_costs else 'default'} cost): "
                    f"targeted {target.name}, the stack names "
                    f"{getattr(named, 'name', None)}"
                )
    assert not findings, "\n".join(findings)


def test_cabal_surgeon_returns_the_creature_it_targeted(set_pool):
    surgeon = set_pool("TOR")["Cabal Surgeon"]
    lea = set_pool("LEA")
    p0 = PlayerState(
        name="P0",
        graveyard=[lea["Lightning Bolt"], lea["Giant Growth"], lea["Hill Giant"],
                   lea["Grizzly Bears"]],
        library=[lea["Swamp"]] * 5,
    )
    game = Game(players=[p0, PlayerState(name="P1", library=[lea["Swamp"]] * 5)])
    game.enforce_mana_costs = False
    permanent = Permanent(card=surgeon)
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99

    game.activate_permanent_ability(
        0, "Cabal Surgeon", target_player_index=0, target_permanent_index=3,
        cost_graveyard_indices=[0, 1],
    )
    resolve_stack(game)

    assert [c.name for c in p0.hand] == ["Grizzly Bears"]
    assert [c.name for c in p0.graveyard] == ["Hill Giant"]
    assert sorted(c.name for c in p0.exile) == ["Giant Growth", "Lightning Bolt"]


def test_a_cost_that_eats_the_target_leaves_the_ability_nothing_to_return(set_pool):
    """CR 601.2h lets the payer exile the targeted card as part of the cost;
    the ability then has no legal target and is removed as it resolves
    (CR 608.2b) — it does not go looking for another creature card."""
    surgeon = set_pool("TOR")["Cabal Surgeon"]
    lea = set_pool("LEA")
    p0 = PlayerState(
        name="P0",
        graveyard=[lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Hill Giant"]],
        library=[lea["Swamp"]] * 5,
    )
    game = Game(players=[p0, PlayerState(name="P1", library=[lea["Swamp"]] * 5)])
    game.enforce_mana_costs = False
    permanent = Permanent(card=surgeon)
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99

    game.activate_permanent_ability(
        0, "Cabal Surgeon", target_player_index=0, target_permanent_index=0,
        cost_graveyard_indices=[0, 1],
    )
    resolve_stack(game)

    assert p0.hand == []
    assert [c.name for c in p0.graveyard] == ["Hill Giant"]
    assert any("608.2b" in line for line in game.log[-3:]), game.log[-3:]


def test_the_default_payment_spares_the_target(set_pool):
    """A payer who names no cards is not choosing to exile its own target: the
    default fills from the pile with the target last."""
    surgeon = set_pool("TOR")["Cabal Surgeon"]
    lea = set_pool("LEA")
    p0 = PlayerState(
        name="P0",
        graveyard=[lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Giant Growth"]],
        library=[lea["Swamp"]] * 5,
    )
    game = Game(players=[p0, PlayerState(name="P1", library=[lea["Swamp"]] * 5)])
    game.enforce_mana_costs = False
    permanent = Permanent(card=surgeon)
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99

    game.activate_permanent_ability(
        0, "Cabal Surgeon", target_player_index=0, target_permanent_index=0,
    )
    resolve_stack(game)

    assert [c.name for c in p0.hand] == ["Grizzly Bears"]
    assert sorted(c.name for c in p0.exile) == ["Giant Growth", "Lightning Bolt"]

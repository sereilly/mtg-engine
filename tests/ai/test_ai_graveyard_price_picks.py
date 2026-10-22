"""A seat paying a price out of its **own** graveyard gives up the least
valuable cards there (``ai_prompt_readers.graveyard_price_order``).

Every default pick out of a seat's own pile went in pile order: the bottom
card first, whatever it was. Torment's W1G4 saw it where the brief named it —
an opponent paying Carrion Rats' toll ("any player may exile a card from
their graveyard") exiled the first card of its pile, a flashback spell as
soon as a land — and the same default stood behind every other own-pile
price in the pool: a toll's (Rotting Giant, Gurzigost), an "if you do"
(Ichorid), a replacement's (Nefarious Lich), an activation cost (Grim
Lavamancer, Organ Grinder) and a spell's additional cost (Haunting Misery,
whose default took the *top* of the pile instead — the other end, and no
more a choice).

The weight is ``graveyard_denial_order``'s reading turned round: a card its
owner could still cast from there (flashback) goes last, then mana value, the
ranking Forgotten Lore's default already gives a pile an opponent picks from.
Where the effect reads **which** card its cost exiled (Necropolis: "X is the
exiled card's mana value") the cards are not a plain price, and the pick is
left as it was (``ai_prompt_readers.reads_what_its_cost_exiled``).

Each behaviour test below was run on the tree before the weight (053649ac)
and failed there with the pile-order pick.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_prompt_readers import graveyard_price_order, reads_what_its_cost_exiled
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import additional_costs
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

ME, OPP = 0, 1


def _pool() -> dict:
    cards: dict = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards


POOL = _pool()
SWAMP = POOL["Swamp"]
#: A flashback spell, a dear creature, a land and a cheap spell — the pile
#: every test gives up a price from, in this order.
PILE = ("Deep Analysis", "Shivan Dragon", "Forest", "Giant Growth")


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def _table(*, mine=(), theirs=()) -> Game:
    game = Game(players=[
        PlayerState(name="P1", library=[SWAMP] * 10),
        PlayerState(name="P2", library=[SWAMP] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = ME
    game.players[ME].graveyard = [POOL[name] for name in mine]
    game.players[OPP].graveyard = [POOL[name] for name in theirs]
    return game


def _put(game, seat, name) -> Permanent:
    permanent = Permanent(card=POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


# -- the census: every own-pile price in the pool, and the one that is not ----

def _own_pile_price_sites(card) -> list[str]:
    """Where *card*'s program picks cards out of its controller's own
    graveyard: the prompt-armed picks, an activation cost, a cast cost."""
    program = compile_card_oracle(card)
    found = []
    everything = [
        *program.instructions,
        *(ability.instruction for ability in program.activated_abilities),
        *(ability.instruction for ability in program.triggered_abilities),
    ]

    def walk(step):
        payload = getattr(step, "payload", None)
        if not isinstance(payload, dict):
            return
        if step.kind == "exile_cards_from_graveyard" and payload.get(
            "graveyard_owner"
        ) in ("you", "offered_player") and not payload.get("targets"):
            found.append("pick")
        if step.kind == "put_chosen_graveyard_cards_on_library_bottom":
            found.append("pick")
        for value in payload.values():
            for child in value if isinstance(value, (list, tuple)) else (value,):
                if hasattr(child, "kind"):
                    walk(child)

    for step in everything:
        if step is not None:
            walk(step)
    for ability in program.activated_abilities:
        cost = ability.cost
        if cost.exile_filter is not None and cost.exile_zone == "graveyard":
            found.append(
                "reads" if reads_what_its_cost_exiled((ability.instruction,))
                else "activation"
            )
    if any(
        getattr(cost, "exile_graveyard_filter", None) is not None
        for cost in additional_costs(card)
    ):
        found.append(
            "reads" if reads_what_its_cost_exiled(program.instructions) else "cast"
        )
    return found


def test_every_own_pile_pick_in_the_pool_is_a_price_but_one():
    """The weight is right only where the cards are a payment. Over the pool
    (shipped and measured), the own-pile picks — the prompt, an activation
    cost, a spell's additional cost — and the one whose effect reads which
    card it took. A second reader is the day the default has to learn it."""
    sites = {}
    for name in sorted(POOL):
        card = POOL[name]
        if not compile_card_oracle(card).supported:
            continue
        found = _own_pile_price_sites(card)
        if found:
            sites[name] = set(found)
    assert len(sites) >= 25, len(sites)
    readers = {name for name, found in sites.items() if "reads" in found}
    assert readers == {"Necropolis"}, sorted(readers)
    for name in ("Carrion Rats", "Rotting Giant", "Ichorid", "Gurzigost",
                 "Grim Lavamancer", "Organ Grinder", "Haunting Misery",
                 "Skeletal Scrying", "Decaying Soil"):
        assert name in sites, name


def test_the_order_puts_a_flashback_card_last_and_a_land_first():
    game = _table(mine=PILE)
    ordered = graveyard_price_order(game, ME, [0, 1, 2, 3])
    assert [PILE[slot] for slot in ordered] == [
        "Forest", "Giant Growth", "Shivan Dragon", "Deep Analysis",
    ]


# -- the picks -----------------------------------------------------------------

def test_carrion_rats_toll_is_paid_with_the_cheapest_card():
    """The brief's case: the defending seat takes the offer out of its own
    pile and gives up the Forest. Before: Deep Analysis, the bottom card —
    a spell it could still have cast."""
    game = _table(theirs=PILE)
    _put(game, ME, "Carrion Rats")
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    ok, why = game.declare_attackers(ME, [0], defending_player_index=OPP)
    assert ok, why
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert _names(game.players[OPP].exile) == ["Forest"]
    assert _names(game.players[OPP].graveyard) == [
        "Deep Analysis", "Shivan Dragon", "Giant Growth",
    ]


def test_nefarious_lich_damage_is_paid_with_the_cheapest_cards():
    """Three damage becomes three cards out of the Lich's controller's
    graveyard, and the one kept is the flashback spell. Before: the bottom
    three, Deep Analysis first."""
    game = _table(mine=PILE)
    _put(game, ME, "Nefarious Lich")
    game.players[OPP].hand = [POOL["Lightning Bolt"]]
    game.active_player_index = OPP
    result = game.cast_from_hand(OPP, "Lightning Bolt", target_player_index=ME)
    assert result.supported, result.details
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.players[ME].life == 20
    assert sorted(_names(game.players[ME].exile)) == [
        "Forest", "Giant Growth", "Shivan Dragon",
    ]
    assert _names(game.players[ME].graveyard) == ["Deep Analysis"]


def test_grim_lavamancer_exiles_the_cheapest_two():
    """"{R}, {T}, Exile two cards from your graveyard": the Forest and the
    Giant Growth. Before: Deep Analysis and the Dragon, the bottom two."""
    game = _table(mine=PILE)
    _put(game, ME, "Grim Lavamancer")
    result = game.activate_permanent_ability(ME, "Grim Lavamancer", target_player_index=OPP)
    assert result.supported, result.details
    assert sorted(_names(game.players[ME].exile)) == ["Forest", "Giant Growth"]
    assert _names(game.players[ME].graveyard) == ["Deep Analysis", "Shivan Dragon"]
    assert game.players[OPP].life == 18


def test_necropolis_still_takes_the_card_in_pile_order():
    """Not a price: "put X +0/+1 counters on this, where X is the exiled
    card's mana value". The pick is left as it was — the first creature card
    in the pile — rather than the cheapest, which would be the worst."""
    game = _table(mine=("Grizzly Bears", "Shivan Dragon"))
    _put(game, ME, "Necropolis")
    result = game.activate_permanent_ability(ME, "Necropolis")
    assert result.supported, result.details
    assert _names(game.players[ME].exile) == ["Grizzly Bears"]


def test_haunting_misery_exiles_the_cheapest_creature_card():
    """"As an additional cost to cast this spell, exile X creature cards from
    your graveyard": X = 1 gives up the Bears. Before: the top of the pile,
    the Dragon."""
    game = _table(mine=("Grizzly Bears", "Shivan Dragon"))
    game.players[ME].hand = [POOL["Haunting Misery"]]
    result = game.cast_from_hand(ME, "Haunting Misery", x_value=1, target_player_index=OPP)
    assert result.supported, result.details
    resolve_stack(game)
    assert _names(game.players[ME].exile) == ["Grizzly Bears"]
    assert game.players[OPP].life == 19

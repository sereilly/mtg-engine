"""Per-card tests for Legends' enchantments, round 36 onward.

`test_legends_enchantments.py` reached 2,549 of the 2,600-line guard, so this
round's card starts a second file rather than pushing it over — the same split
`test_legends_instants_round_35_onward.py` already made.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _creature(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _takklemaggot(set_pool):
    """Takklemaggot on an opponent's 1/1, with a creature on each side to move
    to. Returns (game, aura, host, spare, mine)."""
    aura = Permanent(card=set_pool("LEG")["Takklemaggot"])
    mine = Permanent(card=_creature("Mine", 4, 4))
    host = Permanent(card=_creature("Host", 1, 1))
    spare = Permanent(card=_creature("Spare", 3, 3))
    game = Game(players=[
        PlayerState(name="P0", battlefield=[aura, mine]),
        PlayerState(name="P1", battlefield=[host, spare]),
    ])
    game._sync_control()
    attach_aura(aura, host)
    # The seat the trigger asks is the dead creature's controller; making it
    # interactive is what turns the pick into a prompt the test can answer,
    # rather than the deterministic default headless play takes.
    game.interactive_seats = {1}
    return game, aura, host, spare, mine


def _kill_the_host(game, host):
    host.damage_marked = 99
    game.check_state_based_actions()


def test_takklemaggot_is_supported(set_pool):
    assert compile_card_oracle(set_pool("LEG")["Takklemaggot"]).supported


def test_takklemaggot_asks_the_dead_creatures_controller(set_pool):
    """"That creature's controller chooses..." — CR 601.2c does not make the
    choice the ability's controller's, and the seat is the one the death event
    froze: by the time the trigger resolves the creature is a card in a
    graveyard, and a graveyard card has no controller (CR 108.4a)."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)

    pending = game.pending_choices_of("permanent_choice")
    assert len(pending) == 1
    assert pending[0].player_index == 1
    # "If they don't" is a branch the card prints, so the seat may decline.
    assert pending[0].data["optional"]


def test_takklemaggot_returns_attached_to_the_creature_chosen(set_pool):
    """"If the player does, return this card to the battlefield **under your
    control** attached to that creature." The Aura comes back under the
    trigger's controller, not the chooser's, and it is legally attached — so
    CR 704.5m leaves it alone."""
    game, _aura, host, spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    choice = game.pending_choices_of("permanent_choice")[0]
    assert game.confirm_permanent_choice(1, spare.permanent_id)

    returned = next(p for p in game.all_permanents() if p.card.name == "Takklemaggot")
    assert returned.metadata["attached_to"] is spare
    assert game.controller_index_of(returned) == 0
    game.check_state_based_actions()
    assert game.is_on_battlefield(returned)
    assert choice not in game.pending_choices


def test_takklemaggot_reattached_resumes_its_upkeep_counter(set_pool):
    """The returning Aura is an ordinary Aura again: its printed upkeep trigger
    fires on the *new* host's controller's upkeep."""
    game, _aura, host, spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_permanent_choice(1, spare.permanent_id)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    while game.stack:
        game.resolve_top_of_stack()

    assert spare.effective_toughness == 2


def test_takklemaggot_declined_returns_as_a_non_aura_enchantment(set_pool):
    """"If they don't, return this card ... as a non-Aura enchantment. It loses
    'enchant creature' ..." — CR 613 layer 4 takes the subtype and layer 6
    (CR 613.1f) takes the ability, so the CR 704.5m sweep does not see an Aura
    attached to nothing and the permanent stays on the battlefield."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    # Declining is a legal answer, and only because the card printed a branch
    # for it.
    assert game.confirm_permanent_choice(1, None)

    returned = next(p for p in game.all_permanents() if p.card.name == "Takklemaggot")
    assert game.controller_index_of(returned) == 0
    assert not returned.has_type("aura")
    assert returned.has_type("enchantment")
    assert "Enchant creature" not in returned.effective_card.oracle_text
    assert "Enchant" not in returned.effective_card.keywords
    game.check_state_based_actions()
    assert game.is_on_battlefield(returned), "704.5m has no Aura to bin"


def test_takklemaggot_declined_pings_the_player_who_declined(set_pool):
    """The granted quote's "that player" is the seat the trigger asked, and the
    trigger fires on that seat's upkeep alone."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_permanent_choice(1, None)

    for seat in (0, 1):
        game.active_player_index = seat
        game.resolve_upkeep(seat)
        while game.stack:
            game.resolve_top_of_stack()

    assert [player.life for player in game.players] == [20, 19]


def test_takklemaggot_declined_keeps_pinging_each_upkeep(set_pool):
    """CR 603.3: the granted trigger is an ability of the permanent, not a
    one-shot the return performed."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_permanent_choice(1, None)

    for _ in range(3):
        game.active_player_index = 1
        game.resolve_upkeep(1)
        while game.stack:
            game.resolve_top_of_stack()

    assert game.players[1].life == 17


def test_takklemaggot_offers_only_creatures_it_could_enchant(set_pool):
    """"...a creature that this card could enchant" is CR 303.4j asked of the
    card in the graveyard, through the same predicate the attach re-asks — so a
    permanent that is not a creature is never offered."""
    game, _aura, host, _spare, _mine = _takklemaggot(set_pool)
    rock = Permanent(card=CardDefinition(
        name="Rock", mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Rock", "type_line": "Artifact"},
    ))
    game.players[1].battlefield.append(rock)
    game._sync_control()

    _kill_the_host(game, host)
    game.resolve_top_of_stack(pause_for_choices=True)
    choice = game.pending_choices_of("permanent_choice")[0]

    offered = {p.card.name for p in game.live_permanent_choices(choice)}
    assert offered == {"Mine", "Spare"}

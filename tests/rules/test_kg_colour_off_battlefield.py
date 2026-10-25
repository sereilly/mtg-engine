"""CR 613.1e — a card off the battlefield is the colour its owner's statics make it.

"Nonland permanents you control are white. **The same is true for spells you
control and nonland cards you own that aren't on the battlefield.**"
(Celestial Dawn.) CR 613.1 applies the layers to an *object*, a card in a
graveyard, a hand or a library is one (CR 109.1), and a static's effect "applies
at any given moment to whatever its text indicates" (CR 611.3a) — so under its
owner's Dawn a Hill Giant in a graveyard is a white creature card, and every
printed narrowing that names a colour of such a card has to see white.

The engine had the reader (``object_colors.card_colors``, seat-scoped since
6ED) and most of the matchers that answer those narrowings never handed it the
seat: ``graveyard_card_matches`` and ``_exile_search_matches`` could not be
handed one at all, and 86 of 133 matcher calls passed neither the game nor the
card's owner. Each test here puts a Dawn on the board and watches a different
reader's answer move, and its twin puts the Dawn on the *other* side, where the
same cards keep their printed colours — a colour override applied to the wrong
seat's cards is the card backwards.

``tests/regressions/test_kg_colour_dawn_census.py`` is the pool-wide half.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack

pytestmark = pytest.mark.cr("613.1e", "611.3a")


def _game(catalog, *, battlefields=((), ()), hands=((), ()), graveyards=((), ()),
          libraries=((), ()), interactive=(), cards=None):
    def card(name):
        return (cards or {}).get(name) or catalog[name]

    players = [
        PlayerState(
            name=f"P{seat + 1}",
            battlefield=[Permanent(card=card(name)) for name in battlefields[seat]],
            hand=[card(name) for name in hands[seat]],
            graveyard=[card(name) for name in graveyards[seat]],
            library=[card(name) for name in libraries[seat]],
            life=20,
        )
        for seat in (0, 1)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._sync_control()
    for player in players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    return game


def _names(cards):
    return [card.name for card in cards]


DAWN = "Celestial Dawn"


# ---------------------------------------------------------------------------
# A graveyard target (graveyard_card_matches: the picker, the cast gate, the
# handler)
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2c")
def test_revive_finds_no_green_card_in_a_graveyard_its_owners_dawn_whitened(catalog_by_name):
    """"Return target green card from your graveyard" — under its caster's
    Dawn the Grizzly Bears in that graveyard is white, so there is no legal
    target and the spell cannot be cast (CR 601.2c)."""
    game = _game(catalog_by_name, battlefields=((DAWN,), ()),
                 hands=(("Revive",), ()), graveyards=(("Grizzly Bears",), ()))

    result = game.cast_from_hand(0, "Revive")

    assert not result.supported, result.details
    assert _names(game.players[0].graveyard) == ["Grizzly Bears"]
    assert _names(game.players[0].hand) == ["Revive"]


def test_revive_returns_the_green_card_when_the_dawn_is_the_opponents(catalog_by_name):
    game = _game(catalog_by_name, battlefields=((), (DAWN,)),
                 hands=(("Revive",), ()), graveyards=(("Grizzly Bears",), ()))

    result = game.cast_from_hand(0, "Revive")
    resolve_stack(game)

    assert result.supported, result.details
    assert _names(game.players[0].hand) == ["Grizzly Bears"]


@pytest.mark.cr("602.2b")
def test_dreams_of_the_dead_returns_a_red_creature_card_its_owners_dawn_made_white(catalog_by_name):
    """"Return target **white or black** creature card from your graveyard to
    the battlefield." A printed-red Hill Giant in the graveyard of a player
    whose Dawn is out is a white creature card: the picker offers it, the
    activation gate admits it and the handler returns it."""
    game = _game(catalog_by_name, battlefields=((DAWN, "Dreams of the Dead"), ()),
                 graveyards=(("Hill Giant",), ()))

    result = game.activate_permanent_ability(0, "Dreams of the Dead")
    resolve_stack(game)

    assert result.supported, result.details
    assert game.players[0].graveyard == []
    giant = next(p for p in game.all_permanents() if p.card.name == "Hill Giant")
    assert game.controller_index_of(giant) == 0
    assert game._effective_colors(giant) == {"W"}


def test_dreams_of_the_dead_has_no_target_without_the_dawn(catalog_by_name):
    game = _game(catalog_by_name, battlefields=(("Dreams of the Dead",), (DAWN,)),
                 graveyards=(("Hill Giant",), ()))

    result = game.activate_permanent_ability(0, "Dreams of the Dead")

    assert not result.supported, result.details
    assert _names(game.players[0].graveyard) == ["Hill Giant"]


@pytest.mark.cr("603.3d")
def test_crypt_angels_entry_trigger_finds_no_blue_creature_card_under_the_dawn(catalog_by_name):
    """"…return target **blue or red** creature card from your graveyard" —
    the Merfolk under its owner's Dawn is white, so the entry trigger has no
    legal target and is removed from the stack (CR 603.3d)."""
    game = _game(catalog_by_name, battlefields=((DAWN,), ()),
                 hands=(("Crypt Angel",), ()),
                 graveyards=(("Merfolk of the Pearl Trident",), ()))

    game.cast_from_hand(0, "Crypt Angel")
    resolve_stack(game)

    assert _names(game.players[0].graveyard) == ["Merfolk of the Pearl Trident"]
    assert any("603.3d" in line for line in game.log), game.log[-6:]


def test_crypt_angel_returns_the_blue_card_when_the_dawn_is_the_opponents(catalog_by_name):
    game = _game(catalog_by_name, battlefields=((), (DAWN,)),
                 hands=(("Crypt Angel",), ()),
                 graveyards=(("Merfolk of the Pearl Trident",), ()))

    game.cast_from_hand(0, "Crypt Angel")
    resolve_stack(game)

    assert _names(game.players[0].hand) == ["Merfolk of the Pearl Trident"]


def test_balthor_returns_only_the_cards_no_dawn_whitened(catalog_by_name):
    """"Each player returns all black and all red creature cards from their
    graveyard to the battlefield." One sentence over two graveyards, and the
    Dawn reaches one of them: its controller's Scathe Zombies and Hill Giant
    are white and stay, the opponent's go."""
    pile = ("Scathe Zombies", "Hill Giant")
    game = _game(catalog_by_name, battlefields=((DAWN, "Balthor the Defiled"), ()),
                 graveyards=(pile, pile))

    result = game.activate_permanent_ability(0, "Balthor the Defiled")
    resolve_stack(game)

    assert result.supported, result.details
    assert _names(game.players[0].graveyard) == list(pile)
    assert game.players[1].graveyard == []
    returned = sorted(
        p.card.name for p in game.all_permanents() if game.controller_index_of(p) == 1
    )
    assert returned == sorted(pile)


# ---------------------------------------------------------------------------
# A library search (search_matches; the AI's own reading of it)
# ---------------------------------------------------------------------------


@pytest.mark.cr("701.23a")
def test_merchant_scroll_refuses_a_blue_instant_its_owners_dawn_whitened(catalog_by_name):
    """"Search your library for a **blue** instant card" — asked as an
    interactive seat, the resolver refuses the Counterspell: under its owner's
    Dawn it is a white instant card."""
    game = _game(catalog_by_name, battlefields=((DAWN,), ()),
                 hands=(("Merchant Scroll",), ()),
                 libraries=(("Counterspell",), ()), interactive=(0,))

    game.cast_from_hand(0, "Merchant Scroll")
    game._settle()

    assert game.pending_search_library is not None
    assert not game.confirm_search_library(0, 0)
    assert _names(game.players[0].library) == ["Counterspell"]


@pytest.mark.cr("701.23a")
@pytest.mark.parametrize("dawn_seat, found", [(0, False), (1, True)])
def test_merchant_scrolls_default_searcher_reads_the_colour_the_board_gives(
    catalog_by_name, dawn_seat, found,
):
    """The seat nobody asks takes the AI's pick, and the AI asked
    ``search_matches`` with no seat: under its own Dawn it chose the
    printed-blue Counterspell, which the resolver then refused (the search
    still ended right, by the fallback). Now its pick is the resolver's
    reading — none under its own Dawn, the Counterspell under the other's."""
    from engine.ai_prompts import choose_search_card, choose_search_cards

    battlefields = ((DAWN,), ()) if dawn_seat == 0 else ((), (DAWN,))
    game = _game(catalog_by_name, battlefields=battlefields,
                 hands=(("Merchant Scroll",), ()),
                 libraries=(("Counterspell",), ()), interactive=(0,))

    game.cast_from_hand(0, "Merchant Scroll")
    game._settle()
    choice = game.pending_choices_of("search_library", 0)[0]

    expected = ("library", 0) if found else None
    assert choose_search_card(game, 0, choice.data) == expected
    assert choose_search_cards(game, 0, choice.data, 1) == (
        [{"zone": "library", "index": 0}] if found else []
    )

    game.interactive_seats = set()
    game.auto_resolve_pending_choices()
    assert (_names(game.players[0].hand) == ["Counterspell"]) is found


# ---------------------------------------------------------------------------
# A hand (card_matches_any / _card_matches_filter at the cost and reveal sites)
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2b", "601.2h")
def test_surge_of_strength_cannot_discard_a_red_card_the_dawn_made_white(catalog_by_name):
    """"As an additional cost to cast this spell, discard a **red or green**
    card." Under its caster's Dawn the Hill Giant in hand is white, so nothing
    pays the cost and the spell is not cast."""
    game = _game(catalog_by_name, battlefields=(("Grizzly Bears", DAWN), ()),
                 hands=(("Surge of Strength", "Hill Giant"), ()))

    result = game.cast_from_hand(0, "Surge of Strength", target_permanent_index=0)

    assert not result.supported, result.details
    assert "601.2h" in result.details, result.details
    assert _names(game.players[0].hand) == ["Surge of Strength", "Hill Giant"]


def test_surge_of_strength_discards_the_red_card_under_the_opponents_dawn(catalog_by_name):
    game = _game(catalog_by_name, battlefields=(("Grizzly Bears",), (DAWN,)),
                 hands=(("Surge of Strength", "Hill Giant"), ()))

    result = game.cast_from_hand(0, "Surge of Strength", target_permanent_index=0)
    resolve_stack(game)

    assert result.supported, result.details
    assert _names(game.players[0].graveyard) == ["Hill Giant", "Surge of Strength"]


@pytest.mark.cr("701.20a")
@pytest.mark.parametrize("dawn_seat, drawn", [(1, 1), (0, 2)])
def test_baleful_stare_counts_the_red_cards_the_revealing_seat_really_holds(
    catalog_by_name, dawn_seat, drawn,
):
    """"Target opponent reveals their hand. You draw a card for each Mountain
    and red card in it." The revealed cards are a record; whose they are is
    the seat they were revealed from, and under that seat's Dawn the Hill
    Giant is white — only the Mountain counts."""
    battlefields = ((DAWN,), ()) if dawn_seat == 0 else ((), (DAWN,))
    game = _game(catalog_by_name, battlefields=battlefields,
                 hands=(("Baleful Stare",), ("Hill Giant", "Mountain")),
                 libraries=(("Island", "Island", "Island"), ()))

    game.cast_from_hand(0, "Baleful Stare", target_player_index=1)
    resolve_stack(game)

    assert len(game.players[0].hand) == drawn


# ---------------------------------------------------------------------------
# A record (Grindstone's milled cards) and a spell (Justice, Opal Titan)
# ---------------------------------------------------------------------------


@pytest.mark.cr("701.17a")
@pytest.mark.parametrize("dawn_seat, left", [(1, 0), (0, 4)])
def test_grindstone_repeats_while_the_milled_cards_share_the_dawns_white(
    catalog_by_name, dawn_seat, left,
):
    """"Target player mills two cards. If two cards that share a color were
    milled this way, repeat this process." Under the milled player's Dawn every
    nonland card is white, so a red and a green card share a colour and the
    mill goes on until two lands stop it; without it the first pair stops."""
    battlefields = (("Grindstone", DAWN), ()) if dawn_seat == 0 else (("Grindstone",), (DAWN,))
    game = _game(
        catalog_by_name, battlefields=battlefields,
        libraries=((), ("Hill Giant", "Grizzly Bears", "Scathe Zombies",
                        "Merfolk of the Pearl Trident", "Mountain", "Forest")),
    )

    result = game.activate_permanent_ability(0, "Grindstone", target_player_index=1)
    resolve_stack(game)

    assert result.supported, result.details
    assert len(game.players[1].library) == left


@pytest.mark.cr("109.5")
@pytest.mark.parametrize("dawn_seat, life", [(0, 20), (1, 17)])
def test_justice_does_not_see_a_red_spell_its_controllers_dawn_made_white(
    catalog_by_name, dawn_seat, life,
):
    """"Whenever a red creature or spell deals damage, this enchantment deals
    that much damage to that creature's or spell's controller." A Lightning
    Bolt cast under its caster's Dawn is a white spell (CR 109.5: "spells you
    control"), so Justice does not trigger; under the other seat's Dawn the
    Bolt is red and its caster takes 3."""
    battlefields = ((DAWN,), ("Justice",)) if dawn_seat == 0 else ((), ("Justice", DAWN))
    game = _game(catalog_by_name, battlefields=battlefields,
                 hands=(("Lightning Bolt",), ()))

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    resolve_stack(game)

    assert game.players[1].life == 17
    assert game.players[0].life == life


@pytest.mark.cr("702.16g")
def test_opal_titan_takes_protection_from_the_colour_the_spell_is(catalog_by_name):
    """"…protection from each of **that spell's colors**." A Grizzly Bears
    cast under its caster's Dawn is a white spell, so the Titan gains
    protection from white and not from green."""
    game = _game(catalog_by_name, battlefields=(("Opal Titan",), (DAWN,)),
                 hands=((), ("Grizzly Bears",)))

    game.cast_from_hand(1, "Grizzly Bears")
    resolve_stack(game)

    titan = next(p for p in game.all_permanents() if p.card.name == "Opal Titan")
    assert titan.is_creature
    assert game._protection_colors(titan) == {"W"}


# ---------------------------------------------------------------------------
# The two-zone exile search (_exile_search_matches)
# ---------------------------------------------------------------------------


@pytest.mark.cr("701.23a")
@pytest.mark.parametrize("dawn, taken", [(True, False), (False, True)])
def test_chandras_exile_search_reads_the_colour_of_the_card_in_the_pile(
    catalog_by_name, set_pool, dawn, taken,
):
    """"Search your graveyard and library for any number of **red** instant
    and/or sorcery cards" (Chandra, Heart of Fire's −9): under its owner's
    Dawn the Lightning Bolt in the graveyard is a white instant card, and the
    resolver refuses it as a pick."""
    walker = set_pool("M21")["Chandra, Heart of Fire"]
    game = _game(catalog_by_name, battlefields=((DAWN,) if dawn else (), ()),
                 graveyards=(("Lightning Bolt",), ()), interactive=(0,))
    chandra = Permanent(card=walker)
    game._put_permanent_onto_battlefield(0, chandra, None)
    chandra.metadata["loyalty_counters"] = 9
    game._recompute_continuous_effects()

    result = game.activate_permanent_ability(0, walker.name, ability_index=2)

    assert result.supported, result.details
    assert game.pending_choices_of("search_exile_cards", 0)
    assert game.confirm_search_exile(0, [{"zone": "graveyard", "index": 0}]) is taken
    assert (_names(game.players[0].exile) == ["Lightning Bolt"]) is taken

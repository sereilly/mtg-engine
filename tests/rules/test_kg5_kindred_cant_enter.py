"""CR 400.4a: an instant or sorcery card that would enter the battlefield
remains in its previous zone — a Kindred one included — on every road that
puts a described card onto the battlefield.

    110.4 ... Instant and sorcery cards can't enter the battlefield and thus
    can't be permanents. Some kindred cards can enter the battlefield and some
    can't, depending on their other card types.

    400.4a If an instant or sorcery card would enter the battlefield, it
    remains in its previous zone.

    609.3. If an effect attempts to do something impossible, it does only as
    much as possible.

A "Goblin card" is any card with the subtype (CR 205.3m, 308.2), so a Kindred
Instant — Goblin is one. Until kg5 each road that would put a "<creature type>
card" onto the battlefield refused at the lowering
(``lowering/_filters.creature_type_card``), because no handler on it said what
CR 400.4a says; the pool has no Kindred card, so the shapes were invented and
the roads exact by construction. Now every road asks
``permanent_cards.is_permanent_card`` before it takes the card out of its zone
(``tests/engine/test_kg5_kindred_entry_roads.py`` holds every caller of the
battlefield funnel to it), and the refusals are lifted.

Each road is driven here with an invented Kindred instant or sorcery of the
type — it stays where it was, and the road goes on doing as much as it can —
beside a creature card of the type, which still enters. The sentences are the
kg4 refusal test's (``test_kg4_kindred2_subtype_card``), each in a shape a real
card prints with a card type.

Validated backwards: on the base (59f133e63) every Kindred sentence below
refused to compile, so each board test fails at its first ``supported``
assertion; with the roads' asks switched off and the refusals lifted, every
stay test fails with the Kindred card on the battlefield (or, for the
reveals, in a graveyard or an exile it was never sent to).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, settle

_POOL = {card.name: card for card in load_catalog()}
_STAYS = "can't enter the battlefield and stays in"


def _card(name: str, type_line: str, oracle_text: str = "",
          mana_cost: str = "{1}{R}", colors=("R",)) -> CardDefinition:
    cmc = float(sum(int(ch) if ch.isdigit() else 1
                    for ch in mana_cost.replace("{", " ").replace("}", " ").split()))
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line=type_line,
        oracle_text=oracle_text, colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(), raw={"name": name, "type_line": type_line},
    )


_LIFE = "You gain 1 life."
GOBLIN_TRICK = _card("Test Goblin Trick", "Kindred Instant — Goblin", _LIFE, "{R}")
GOBLIN_RITE = _card("Test Goblin Rite", "Kindred Sorcery — Goblin", _LIFE, "{R}")
ZOMBIE_TRICK = _card("Test Zombie Trick", "Kindred Instant — Zombie", _LIFE,
                     "{B}", ("B",))
GOBLIN_LANTERN = _card("Test Goblin Lantern", "Kindred Artifact — Goblin",
                       "{T}: You gain 1 life.", "{2}", ())


def _spell(name: str, text: str) -> CardDefinition:
    return _card(name, "Sorcery", text, "{1}{B}", ("B",))


def _duel(*, hand=(), library=(), graveyard=(), their_library=(),
          their_graveyard=(), mine=(), theirs=(), interactive=(0,)) -> Game:
    """Seat 0's main phase, mana costs not enforced. Each library is exactly
    what is given, with Islands under it."""
    filler = [_POOL["Island"]] * 4
    game = Game(players=[
        PlayerState(name="P0", hand=list(hand), graveyard=list(graveyard),
                    library=[*library, *filler],
                    battlefield=[Permanent(card=c) for c in mine]),
        PlayerState(name="P1", graveyard=list(their_graveyard),
                    library=[*their_library, *filler],
                    battlefield=[Permanent(card=c) for c in theirs]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    game._sync_control()
    for permanent in game.all_permanents():
        _nosick(permanent)
    return game


def _on_battlefield(game: Game) -> list[str]:
    return sorted(p.card.name for p in game.all_permanents())


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def _cast(game: Game, card: CardDefinition, **kwargs) -> None:
    assert compile_card_oracle(card).supported, compile_card_oracle(card)
    result = game.cast_from_hand(0, card.name, **kwargs)
    assert result.supported, (result.details, game.log[-4:])


def _stay_lines(game: Game) -> list[str]:
    return [line for line in game.log if _STAYS in line]


# --- a library search ------------------------------------------------------------

_SEARCH = _spell(
    "Test Goblin Muster",
    "Search your library for a Goblin card, put it onto the battlefield, then shuffle.",
)


def _search_board(pick: str) -> tuple[Game, list]:
    game = _duel(hand=[_SEARCH], library=[GOBLIN_TRICK, _POOL["Raging Goblin"]])
    shuffled: list = []
    original = game.shuffle_library_of

    def counting(player):
        shuffled.append(player.name)
        return original(player)

    game.shuffle_library_of = counting
    _cast(game, _SEARCH)
    game.resolve_top_of_stack()
    assert game.pending_choice_of("search_library", 0) is not None, game.log[-4:]
    index = _names(game.players[0].library).index(pick)
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=index, zone="library",
    ), game.log[-4:]
    settle(game)
    return game, shuffled


@pytest.mark.cr("400.4a", "701.23a", "609.3")
def test_a_search_leaves_a_kindred_instant_in_the_library_and_still_shuffles():
    """The find is legal (a Goblin card), it stays where it was found, the
    search ends as searches do — the library shuffled — and the table is told
    "a card": the library is hidden and nothing revealed the find."""
    game, shuffled = _search_board("Test Goblin Trick")
    assert "Test Goblin Trick" in _names(game.players[0].library)
    assert _on_battlefield(game) == []
    assert _stay_lines(game) == [
        "a card can't enter the battlefield and stays in P0's library (400.4a)"
    ], game.log[-6:]
    assert shuffled == ["P0"]
    assert game.pending_choice_of("search_library", 0) is None


@pytest.mark.cr("400.4a", "701.23a")
def test_a_search_for_a_goblin_card_still_puts_a_goblin_creature_onto_the_battlefield():
    game, shuffled = _search_board("Raging Goblin")
    assert _on_battlefield(game) == ["Raging Goblin"], game.log[-6:]
    assert not _stay_lines(game)
    assert shuffled == ["P0"]


GOBLIN_BOMB = _card("Test Goblin Bomb", "Kindred Sorcery — Goblin",
                    "Test Goblin Bomb deals 5 damage to any target.", "{4}{R}{R}")


@pytest.mark.cr("400.4a", "701.23b")
def test_a_seat_nobody_asks_finds_the_goblin_that_can_enter():
    """The default search pick passes over a find the battlefield cannot take:
    the costly Kindred sorcery would stay in the library, so the seat finds the
    Goblin creature instead (CR 701.23b lets it find either, or nothing)."""
    game = _duel(hand=[_SEARCH], library=[GOBLIN_BOMB, _POOL["Raging Goblin"]],
                 interactive=())
    _cast(game, _SEARCH)
    settle(game)
    assert _on_battlefield(game) == ["Raging Goblin"], game.log[-6:]
    assert "Test Goblin Bomb" in _names(game.players[0].library)
    assert not _stay_lines(game)


_COUNTED = _spell(
    "Test Goblin Roundup",
    "Search your library for up to two Goblin cards, put them onto the "
    "battlefield, then shuffle.",
)


@pytest.mark.cr("400.4a", "701.23a", "609.3")
def test_a_counted_search_puts_down_the_finds_that_can_enter():
    """Every slot is the battlefield, so each find is asked before any is
    taken: the Goblin creature enters, the Kindred sorcery stays in the
    library."""
    game = _duel(hand=[_COUNTED],
                 library=[GOBLIN_RITE, _POOL["Grizzly Bears"], _POOL["Raging Goblin"]])
    _cast(game, _COUNTED)
    game.resolve_top_of_stack()
    library = _names(game.players[0].library)
    assert game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Test Goblin Rite")},
        {"zone": "library", "index": library.index("Raging Goblin")},
    ]), game.log[-4:]
    settle(game)
    assert _on_battlefield(game) == ["Raging Goblin"], game.log[-6:]
    assert "Test Goblin Rite" in _names(game.players[0].library)
    assert len(_stay_lines(game)) == 1


_ONE_OF_EACH = _spell(
    "Test Goblin Homestead",
    "Search your library for a Goblin card and a Swamp card, put them onto "
    "the battlefield, then shuffle.",
)


@pytest.mark.cr("400.4a", "701.23a")
def test_one_of_each_search_leaves_its_kindred_find_and_puts_down_the_swamp():
    game = _duel(hand=[_ONE_OF_EACH], library=[GOBLIN_TRICK, _POOL["Swamp"]])
    _cast(game, _ONE_OF_EACH)
    game.resolve_top_of_stack()
    library = _names(game.players[0].library)
    assert game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Test Goblin Trick")},
        {"zone": "library", "index": library.index("Swamp")},
    ]), game.log[-4:]
    settle(game)
    assert _on_battlefield(game) == ["Swamp"], game.log[-6:]
    assert "Test Goblin Trick" in _names(game.players[0].library)


@pytest.mark.cr("400.4a", "701.23a")
def test_a_counted_search_splitting_its_finds_still_refuses_a_creature_type_card():
    """Which find fills which slot is asked after the finds have left their
    zones, so a Kindred instant sent to the battlefield slot would have no zone
    to stay in: refused for a phrase that can name one, read for one that
    cannot (Cultivate's own sentence)."""
    split = ("Search your library for up to two {} cards, put one onto the "
             "battlefield tapped and the other into your hand, then shuffle.")
    assert not compile_card_oracle(_spell("Test Split", split.format("Goblin"))).supported
    assert compile_card_oracle(_spell("Test Split", split.format("basic land"))).supported


_BRIBE = _spell(
    "Test Goblin Bribe",
    "Search target opponent's library for a Goblin card and put that card onto "
    "the battlefield under your control. Then that player shuffles.",
)


@pytest.mark.cr("400.4a", "701.23a", "109.2a")
def test_a_search_of_an_opponents_library_keeps_its_creature_type_and_its_kindred_find():
    """Bribery's sentence with a creature type. The lowering read the card type
    and dropped every other word, so "a Goblin card" here was any card: the
    Bears is not findable now, the Goblin creature enters under the searcher,
    and the Kindred instant stays in its owner's library."""
    def board():
        game = _duel(hand=[_BRIBE], their_library=[
            _POOL["Grizzly Bears"], GOBLIN_TRICK, _POOL["Raging Goblin"],
        ])
        _cast(game, _BRIBE, target_player_index=1)
        game.resolve_top_of_stack()
        assert game.pending_choice_of("search_library", 0) is not None, game.log[-4:]
        return game

    def pick(game, name):
        return game.resolve_pending_choice(
            "search_library", 0, zone="library",
            library_index=_names(game.players[1].library).index(name),
        )

    game = board()
    assert not pick(game, "Grizzly Bears"), "no Goblin card"
    assert pick(game, "Test Goblin Trick")
    settle(game)
    assert "Test Goblin Trick" in _names(game.players[1].library)
    assert _on_battlefield(game) == []
    assert _stay_lines(game) == [
        "a card can't enter the battlefield and stays in P1's library (400.4a)"
    ]

    game = board()
    assert pick(game, "Raging Goblin")
    settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Raging Goblin"]


# --- from a graveyard -------------------------------------------------------------

_RAISE = _spell("Test Zombie Raising",
                "Return target Zombie card from your graveyard to the battlefield.")
_HYMN = _spell("Test Zombie Hymn",
               "Put target Zombie card from a graveyard onto the battlefield under "
               "your control.")
_SWEEP = _spell("Test Zombie Uprising",
                "Return all Zombie cards from your graveyard to the battlefield.")


@pytest.mark.cr("400.4a", "115.1", "609.3")
@pytest.mark.parametrize("target, entered", [
    ("Test Zombie Trick", []), ("Scathe Zombies", ["Scathe Zombies"]),
])
def test_a_targeted_reanimation_of_a_kindred_instant_leaves_it_in_the_graveyard(target, entered):
    """"Return target Zombie card from your graveyard to the battlefield." The
    Kindred instant is a legal target; CR 400.4a keeps it in the graveyard, and
    nothing claims there was no card to return."""
    graveyard = [ZOMBIE_TRICK, _POOL["Scathe Zombies"]]
    game = _duel(hand=[_RAISE], graveyard=graveyard)
    spec = game.cast_target_spec(0, _RAISE)
    assert sorted(t["name"] for t in spec["valid_targets"]) == [
        "Scathe Zombies", "Test Zombie Trick",
    ], spec
    _cast(game, _RAISE, target_player_index=0,
          target_permanent_index=_names(graveyard).index(target))
    settle(game)
    assert _on_battlefield(game) == entered, game.log[-6:]
    if entered:
        assert not _stay_lines(game)
        return
    assert "Test Zombie Trick" in _names(game.players[0].graveyard)
    assert _stay_lines(game) == [
        "Test Zombie Trick can't enter the battlefield and stays in P0's "
        "graveyard (400.4a)"
    ]
    assert not any("no zombie card to return" in line for line in game.log)


@pytest.mark.cr("400.4a", "115.1")
def test_a_reanimation_from_any_graveyard_leaves_the_opponents_kindred_instant():
    game = _duel(hand=[_HYMN], their_graveyard=[ZOMBIE_TRICK, _POOL["Scathe Zombies"]])
    _cast(game, _HYMN, target_player_index=1, target_permanent_index=0)
    settle(game)
    assert _on_battlefield(game) == [], game.log[-6:]
    assert "Test Zombie Trick" in _names(game.players[1].graveyard)
    assert _stay_lines(game) == [
        "Test Zombie Trick can't enter the battlefield and stays in P1's "
        "graveyard (400.4a)"
    ]
    game = _duel(hand=[_HYMN], their_graveyard=[ZOMBIE_TRICK, _POOL["Scathe Zombies"]])
    _cast(game, _HYMN, target_player_index=1, target_permanent_index=1)
    settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Scathe Zombies"]


@pytest.mark.cr("400.4a", "609.3")
def test_a_sweep_reanimation_returns_the_zombie_creatures_and_leaves_the_kindred_instant():
    game = _duel(hand=[_SWEEP], graveyard=[
        ZOMBIE_TRICK, _POOL["Scathe Zombies"], _POOL["Grizzly Bears"],
    ])
    _cast(game, _SWEEP)
    settle(game)
    assert _on_battlefield(game) == ["Scathe Zombies"], game.log[-6:]
    assert sorted(_names(game.players[0].graveyard)) == [
        "Grizzly Bears", "Test Zombie Trick", "Test Zombie Uprising",
    ]
    assert len(_stay_lines(game)) == 1


_LIVING_GOBLINS = _spell(
    "Test Living Goblins",
    "Each player exiles all Goblin cards from their graveyard, then sacrifices "
    "all creatures they control, then puts all cards they exiled this way onto "
    "the battlefield.",
)


@pytest.mark.cr("400.4a", "609.3")
def test_living_death_with_a_creature_type_leaves_the_kindred_card_in_exile():
    """Living Death's sentence with "Goblin cards", which compiled on the base
    and put whatever its exile took onto the battlefield: the Goblin creature
    comes back, the Kindred instant stays exiled (CR 400.4a, from exile)."""
    game = _duel(hand=[_LIVING_GOBLINS], graveyard=[GOBLIN_TRICK, _POOL["Raging Goblin"]],
                 mine=[_POOL["Grizzly Bears"]])
    _cast(game, _LIVING_GOBLINS)
    settle(game)
    assert _on_battlefield(game) == ["Raging Goblin"], game.log[-6:]
    assert _names(game.players[0].exile) == ["Test Goblin Trick"]
    assert "Grizzly Bears" in _names(game.players[0].graveyard)
    assert _stay_lines(game) == [
        "Test Goblin Trick can't enter the battlefield and stays in P0's "
        "exile (400.4a)"
    ]


# --- a revealed pile --------------------------------------------------------------

_CLEARING = _spell(
    "Test Goblin Clearing",
    _POOL["Clear the Land"].oracle_text.replace("land cards", "Goblin cards"),
)


@pytest.mark.cr("400.4a", "701.20b", "609.3")
def test_the_sorted_reveal_leaves_a_kindred_match_on_top_of_the_library():
    """Clear the Land with "Goblin cards": the Goblin creature enters, the rest
    are exiled, and the Kindred sorcery — a match, so not "the rest" — stays
    on top of the library it was revealed in."""
    game = _duel(hand=[_CLEARING], library=[
        _POOL["Grizzly Bears"], GOBLIN_RITE, _POOL["Raging Goblin"],
        _POOL["Swamp"], _POOL["Mountain"],
    ])
    _cast(game, _CLEARING)
    settle(game)
    assert _on_battlefield(game) == ["Raging Goblin"], game.log[-6:]
    assert game.players[0].library[0] is GOBLIN_RITE
    assert sorted(_names(game.players[0].exile)) == ["Grizzly Bears", "Mountain", "Swamp"]
    assert _stay_lines(game) == [
        "Test Goblin Rite can't enter the battlefield and stays in P0's "
        "library (400.4a)"
    ]


_GAMEKEEPING = _spell(
    "Test Goblin Keeping",
    "Reveal cards from the top of your library until you reveal a Goblin card. "
    "Put that card onto the battlefield and put all other cards revealed this "
    "way into your graveyard.",
)


@pytest.mark.cr("400.4a", "701.20b", "609.3")
def test_reveal_until_stops_on_a_kindred_instant_and_leaves_it_on_top():
    game = _duel(hand=[_GAMEKEEPING], library=[
        _POOL["Grizzly Bears"], _POOL["Swamp"], GOBLIN_TRICK, _POOL["Raging Goblin"],
    ])
    _cast(game, _GAMEKEEPING)
    settle(game)
    assert _on_battlefield(game) == [], game.log[-6:]
    assert game.players[0].library[0] is GOBLIN_TRICK
    assert game.players[0].library[1].name == "Raging Goblin"
    assert "Grizzly Bears" in _names(game.players[0].graveyard)
    assert "Swamp" in _names(game.players[0].graveyard)
    assert len(_stay_lines(game)) == 1


@pytest.mark.cr("400.4a", "701.20b")
def test_reveal_until_still_puts_a_goblin_creature_onto_the_battlefield():
    game = _duel(hand=[_GAMEKEEPING],
                 library=[_POOL["Grizzly Bears"], _POOL["Raging Goblin"]])
    _cast(game, _GAMEKEEPING)
    settle(game)
    assert _on_battlefield(game) == ["Raging Goblin"], game.log[-6:]


_MAGNETISM = _spell(
    "Test Goblin Magnetism",
    _POOL["Animal Magnetism"].oracle_text.replace("a creature card", "a Goblin card"),
)


@pytest.mark.cr("400.4a", "608.2d", "609.3")
@pytest.mark.parametrize("interactive, kindred", [
    (False, GOBLIN_TRICK), (False, GOBLIN_BOMB), (True, GOBLIN_TRICK),
])
def test_the_opponents_pick_of_a_kindred_instant_leaves_it_in_the_library(interactive, kindred):
    """Animal Magnetism with "a Goblin card": the Kindred card is a legal pick
    — the opponent's, and the one the default chooser names first, cheap or
    not, since a card that cannot enter serves the revealer least of all — and
    it stays on top of the library while the rest go to the graveyard."""
    game = _duel(hand=[_MAGNETISM], interactive=(1,) if interactive else (), library=[
        kindred, _POOL["Goblin King"], _POOL["Grizzly Bears"],
    ])
    _cast(game, _MAGNETISM)
    if interactive:
        game.resolve_top_of_stack()
        choice = game.pending_choice_of("opponent_picks_revealed", 1)
        assert choice is not None, game.log[-6:]
        assert game.confirm_opponent_picks_revealed(1, 0)
    settle(game)
    assert _on_battlefield(game) == [], game.log[-6:]
    assert game.players[0].library[0] is kindred
    assert sorted(_names(game.players[0].graveyard)) == [
        "Goblin King", "Grizzly Bears", "Island", "Island", "Test Goblin Magnetism",
    ]
    assert len(_stay_lines(game)) == 1


_CALL = _spell(
    "Test Goblin Call",
    "Reveal the top card of your library. If it's a Goblin card, put it onto the "
    "battlefield. Otherwise, put it into your graveyard.",
)


@pytest.mark.cr("400.4a", "205.3m", "608.2c")
@pytest.mark.parametrize("top, entered, binned", [
    (GOBLIN_TRICK, [], []),
    (_POOL["Raging Goblin"], ["Raging Goblin"], []),
    (_POOL["Grizzly Bears"], [], ["Grizzly Bears"]),
])
def test_if_its_a_goblin_card_put_it_onto_the_battlefield(top, entered, binned):
    """"If it's a Goblin card" asks the subtype (it refused, naming a card
    type it wanted): the Kindred instant is one, so it is not put into the
    graveyard, and CR 400.4a leaves it on top of the library."""
    game = _duel(hand=[_CALL], library=[top])
    _cast(game, _CALL)
    settle(game)
    assert _on_battlefield(game) == entered, game.log[-6:]
    assert [n for n in _names(game.players[0].graveyard) if n != _CALL.name] == binned
    if top is GOBLIN_TRICK:
        assert game.players[0].library[0] is GOBLIN_TRICK
        assert len(_stay_lines(game)) == 1


# --- from a hand ------------------------------------------------------------------

_PIPING = _spell("Test Goblin Piping",
                 "You may put a Goblin card from your hand onto the battlefield.")
_WELCOME = _spell(
    "Test Goblin Welcome",
    "Each opponent may put any number of Goblin cards from their hand onto the "
    "battlefield.",
)


@pytest.mark.cr("400.4a", "110.4a")
def test_a_pick_from_hand_offers_the_goblin_cards_that_can_enter():
    """The single pick reads "a Goblin card" as the cards that could enter
    (``permanents_only``): the Kindred artifact is offered and enters, the
    Kindred instant is not offered."""
    game = _duel(hand=[_PIPING, GOBLIN_TRICK, GOBLIN_LANTERN])
    _cast(game, _PIPING)
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=True), game.log[-4:]
    choice = game.pending_choice_of("put_from_hand_choice", 0)
    assert choice is not None, game.log[-6:]
    hand = _names(game.players[0].hand)
    live = game.live_put_from_hand_choices(choice)
    assert sorted(hand[i] for i in live) == ["Test Goblin Lantern"]
    assert game.resolve_pending_choice(
        "put_from_hand_choice", 0, hand_index=hand.index("Test Goblin Lantern"),
    )
    settle(game)
    assert _on_battlefield(game) == ["Test Goblin Lantern"]
    assert "Test Goblin Trick" in _names(game.players[0].hand)


@pytest.mark.cr("400.4a", "101.4")
def test_each_opponent_puts_its_goblin_creatures_and_keeps_its_kindred_instant():
    """Tempting Wurm's sentence with a creature type (it refused, "reads printed
    card types"): the pick offers what could enter, so the default seat puts
    its Goblin creature and the Kindred instant stays in its hand."""
    game = _duel(hand=[_WELCOME], interactive=())
    game.players[1].hand.extend([GOBLIN_TRICK, _POOL["Raging Goblin"]])
    _cast(game, _WELCOME)
    settle(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Raging Goblin"], game.log[-6:]
    assert _names(game.players[1].hand) == ["Test Goblin Trick"]


# --- a bare creature type naming a permanent --------------------------------------

_CANYON = _card(
    "Test Goblin Canyon", "Land",
    "{T}: Untap target permanent. If it's a Goblin, it gets +1/+1 until end of turn.",
    "", (),
)


@pytest.mark.cr("205.3m", "308.2", "608.2c")
@pytest.mark.parametrize("target, pumped", [
    ("Raging Goblin", True), ("Grizzly Bears", False),
])
def test_if_its_a_goblin_asks_the_targets_creature_types(target, pumped):
    """Griffin Canyon's "If it's a …" with a creature type: asked of the
    permanent's subtypes through layer 4 (it refused, "no type at all")."""
    game = _duel(mine=[_CANYON, _POOL["Raging Goblin"], _POOL["Grizzly Bears"]])
    assert compile_card_oracle(_CANYON).supported
    victim = next(p for p in game.all_permanents() if p.card.name == target)
    before = victim.effective_power
    result = game.queue_permanent_ability(
        0, "Test Goblin Canyon", target_permanent_index=game.battlefield_index_of(victim),
    )
    assert result.supported, result.details
    settle(game)
    assert victim.effective_power == before + (1 if pumped else 0), game.log[-6:]

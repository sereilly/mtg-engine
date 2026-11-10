""""<Creature type> card" is a card with that subtype — not "<creature type>
creature card" (CR 109.2a, 205.3m, 308.2).

    109.2a If a spell or ability uses a description of an object that includes
    the word "card" and the name of a zone, it means a card matching that
    description in the stated zone.

    205.3m Creatures and kindreds share their lists of subtypes; these
    subtypes are called creature types.

    308.2 ... The set of kindred subtypes is the same as the set of creature
    subtypes; these subtypes are called creature types.

``nouns.parse_object_filter`` implied the creature type after a creature
subtype under every head noun, so "search your library for a Goblin card"
(Goblin Matron), "return target Zombie card from your graveyard" (Lord of the
Undead), "put all Soldier cards revealed this way into your hand" (Enlistment
Officer) and the rest — twenty-four cards' programs, and the text-keyed readers
of "discard a Zombie card" (Putrid Raptor's morph cost) and "a Goblin card" on
top of a library (Conspicuous Snoop) — named a Goblin *creature* card. Exact on
a pool with no Kindred card, narrower on one: a Kindred Sorcery — Goblin is a
Goblin card and no creature card. A permanent named on the battlefield by a
bare subtype ("destroy target Wall") is not this question and keeps the
implication.

The pool has no Kindred card yet, so the board is an invented one, driven down
each reader's own road:

* a library search — Sliver Overlord (``search_library``, the Matron's, the
  Recruiters', Wirewood Herald's, Imperial Hellkite's) and Corpse Harvester's
  one-of-each;
* the revealed top four — Goblin Ringleader (``reveal_top_sorting_by_filter``,
  Apocalypse's six other recruiters);
* from a graveyard — Lord of the Undead and Strongarm Thug
  (``return_creature_from_graveyard_to_hand``: the announced slot and the
  fallback scan), Cruel Revival's role, Unholy Grotto (library top), Lin Sivvi
  (library bottom), Infernal Caretaker's sweep, Soulless One's count;
* a cost — Putrid Raptor's "Morph—Discard a Zombie card";
* the top of a library — Conspicuous Snoop's cast permission and its ability
  grant.

Each beside the real pool's own answer: a creature card of the type is still
found, and a card of neither the type nor a Kindred of it is not.

Onto the battlefield no card in the pool prints the phrase ("a Goblin
**permanent** card" is what the pool prints, and is read). A Kindred instant
of the type is a "<type> card" that CR 400.4a leaves where it is; each road
refused the shape here (kg4) until its handler said so, and since kg5 every
road asks ``permanent_cards`` before the card leaves its zone, so the shapes
compile — a search, a targeted reanimation from your graveyard and from any
graveyard, a sweep reanimation, Clear the Land's sorted reveal, Animal
Magnetism's opponent's pick, a reveal-until (Gamekeeper's). Their boards are
``test_kg5_kindred_cant_enter.py``.

The readers of "<creature type> spell(s)" never paired the subtype with the
creature type (each asks ``object_creature_types.card_creature_types``); they
are driven here too, with a Kindred spell, so that stays true: Goblin Warchief's
discount, Rin and Seri's cast trigger, Root Sliver's "can't be countered",
Quick Sliver's flash, amplify's "share a creature type".

Measured backwards on the base (4c3d6e34): every Kindred case below that reads
a "card" phrase fails, and every control and every spell reader passes.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.cast_timing import casts_at_instant_speed
from engine.face_down import face_down_card, is_face_down
from engine.library_top import granted_top_abilities, top_castable
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.special_actions import (available_permanent_special_actions,
                                    take_permanent_special_action)
from tests.helpers import _nosick, resolve_stack, settle

_POOL = {card.name: card for card in load_catalog()}


def _kindred(name: str, type_line: str, oracle_text: str = "",
             mana_cost: str = "{1}{B}", colors=("B",)) -> CardDefinition:
    cmc = float(sum(int(ch) if ch.isdigit() else 1
                    for ch in mana_cost.replace("{", " ").replace("}", " ").split()))
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line=type_line,
        oracle_text=oracle_text, colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(), raw={"name": name, "type_line": type_line},
    )


_LIFE = "You gain 1 life."
ZOMBIE_TRICK = _kindred("Test Zombie Trick", "Kindred Instant — Zombie", _LIFE)
SLIVER_TRICK = _kindred("Test Sliver Trick", "Kindred Instant — Sliver", _LIFE,
                        "{1}{G}", ("G",))
SLIVER_RITE = _kindred("Test Sliver Rite", "Kindred Sorcery — Sliver", _LIFE,
                       "{1}{G}", ("G",))
GOBLIN_RITE = _kindred("Test Goblin Rite", "Kindred Sorcery — Goblin", _LIFE,
                       "{1}{R}", ("R",))
TROLL_RITE = _kindred("Test Troll Rite", "Kindred Sorcery — Troll", _LIFE,
                      "{1}{R}", ("R",))
GOBLIN_LANTERN = _kindred("Test Goblin Lantern", "Kindred Artifact — Goblin",
                          "{T}: You gain 1 life.", "{2}", ())
REBEL_TRICK = _kindred("Test Rebel Trick", "Kindred Instant — Rebel", _LIFE,
                       "{1}{W}", ("W",))
MERCENARY_TRICK = _kindred("Test Mercenary Trick", "Kindred Instant — Mercenary",
                           _LIFE)
DOG_TRICK = _kindred("Test Dog Trick", "Kindred Instant — Dog", _LIFE, "{1}{W}", ("W",))


def _duel(*, mine=(), theirs=(), hand=(), library=(), graveyard=(),
          their_graveyard=(), interactive=False, active=0) -> Game:
    """Seat 0's main phase (or seat 1's, *active*), mana costs not enforced,
    every permanent past summoning sickness. Nothing is drawn: the library is
    exactly *library*, with Islands under it."""
    filler = [_POOL["Island"]] * 6
    game = Game(players=[
        PlayerState(name="P0", battlefield=[Permanent(card=c) for c in mine],
                    hand=list(hand), graveyard=list(graveyard),
                    library=[*library, *filler]),
        PlayerState(name="P1", battlefield=[Permanent(card=c) for c in theirs],
                    graveyard=list(their_graveyard), library=list(filler)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = active
    game.priority_player_index = active
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    game._sync_control()
    for permanent in game.all_permanents():
        _nosick(permanent)
    game._recompute_continuous_effects()
    return game


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def _permanent(game: Game, name: str) -> Permanent:
    return next(p for p in game.all_permanents() if p.card.name == name)


# --- a library search --------------------------------------------------------


def _overlord_search(library) -> Game:
    game = _duel(mine=[_POOL["Sliver Overlord"]], library=library, interactive=True)
    assert game.queue_permanent_ability(0, "Sliver Overlord", ability_index=0).supported
    game.resolve_top_of_stack()
    assert game.pending_choice_of("search_library", 0) is not None, game.log[-4:]
    return game


def _pick(game: Game, name: str) -> bool:
    names = _names(game.players[0].library)
    return game.resolve_pending_choice(
        "search_library", 0, library_index=names.index(name), zone="library",
    )


@pytest.mark.cr("109.2a", "205.3m", "308.2", "701.23a")
def test_a_search_for_a_sliver_card_finds_a_kindred_sliver():
    """"{3}: Search your library for a Sliver card, reveal that card, put it
    into your hand, then shuffle." (Sliver Overlord.)"""
    game = _overlord_search([_POOL["Grizzly Bears"], _POOL["Jayemdae Tome"], SLIVER_TRICK])
    assert not _pick(game, "Grizzly Bears"), "a creature card that is no Sliver"
    assert not _pick(game, "Jayemdae Tome"), "neither a Sliver nor a Kindred"
    assert _pick(game, "Test Sliver Trick"), game.log[-4:]
    resolve_stack(game)
    assert _names(game.players[0].hand) == ["Test Sliver Trick"], game.log[-4:]


@pytest.mark.cr("109.2a", "701.23a")
def test_a_search_for_a_sliver_card_still_finds_a_sliver_creature_card():
    game = _overlord_search([SLIVER_TRICK, _POOL["Muscle Sliver"]])
    assert _pick(game, "Muscle Sliver"), game.log[-4:]
    resolve_stack(game)
    assert _names(game.players[0].hand) == ["Muscle Sliver"]


@pytest.mark.cr("109.2a", "205.3m", "701.23a")
def test_corpse_harvester_finds_a_kindred_zombie_and_a_swamp():
    """"{1}{B}, {T}, Sacrifice a creature: Search your library for a Zombie card
    and a Swamp card, reveal them, put them into your hand, then shuffle." One
    find per description, and the Zombie one is any Zombie card. Answered by
    the default seat: it finds what each description names."""
    game = _duel(
        mine=[_POOL["Corpse Harvester"], _POOL["Grizzly Bears"]],
        library=[_POOL["Grizzly Bears"], ZOMBIE_TRICK, _POOL["Swamp"]],
    )
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    result = game.queue_permanent_ability(
        0, "Corpse Harvester", cost_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    settle(game)
    assert sorted(_names(game.players[0].hand)) == ["Swamp", "Test Zombie Trick"], game.log[-6:]


# --- the revealed top four ---------------------------------------------------


@pytest.mark.cr("109.2a", "205.3m", "701.20a")
def test_goblin_ringleader_keeps_every_goblin_card_it_reveals():
    """"…Put all Goblin cards revealed this way into your hand and the rest on
    the bottom of your library in any order." The Kindred sorcery and the
    Goblin creature card are Goblin cards; the Bears and the Tome are not."""
    game = _duel(
        hand=[_POOL["Goblin Ringleader"]],
        library=[GOBLIN_RITE, _POOL["Raging Goblin"], _POOL["Grizzly Bears"],
                 _POOL["Jayemdae Tome"]],
    )
    assert game.cast_from_hand(0, "Goblin Ringleader").supported
    settle(game)
    assert sorted(_names(game.players[0].hand)) == ["Raging Goblin", "Test Goblin Rite"], game.log[-6:]
    assert sorted(_names(game.players[0].library[-2:])) == ["Grizzly Bears", "Jayemdae Tome"]


# --- from a graveyard --------------------------------------------------------


@pytest.mark.cr("109.2a", "205.3m", "308.2", "115.1")
def test_lord_of_the_undead_offers_and_returns_a_kindred_zombie_card():
    """"{1}{B}, {T}: Return target Zombie card from your graveyard to your
    hand." The picker offers the Kindred instant and the Zombie creature card,
    the Bears is refused before anything is paid, and the card named is the
    card that comes back."""
    graveyard = [_POOL["Grizzly Bears"], ZOMBIE_TRICK, _POOL["Scathe Zombies"]]
    game = _duel(mine=[_POOL["Lord of the Undead"]], graveyard=graveyard)
    lord = _permanent(game, "Lord of the Undead")
    spec = game.activation_target_spec(0, game.battlefield_index_of(lord), 0)
    assert sorted(t["name"] for t in spec["valid_targets"]) == [
        "Scathe Zombies", "Test Zombie Trick",
    ], spec

    refused = game.queue_permanent_ability(0, "Lord of the Undead", target_permanent_index=0)
    assert not refused.supported and not lord.tapped
    assert game.queue_permanent_ability(
        0, "Lord of the Undead", target_permanent_index=1,
    ).supported
    resolve_stack(game)
    assert _names(game.players[0].hand) == ["Test Zombie Trick"], game.log[-4:]
    assert _names(game.players[0].graveyard) == ["Grizzly Bears", "Scathe Zombies"]


@pytest.mark.cr("109.2a", "205.3m")
@pytest.mark.parametrize("graveyard, returned", [
    ((_POOL["Grizzly Bears"], MERCENARY_TRICK), "Test Mercenary Trick"),
    ((_POOL["Grizzly Bears"], _POOL["Mercenaries"]), "Mercenaries"),
    ((_POOL["Grizzly Bears"], _POOL["Jayemdae Tome"]), None),
])
def test_strongarm_thug_returns_a_mercenary_card_with_nothing_announced(graveyard, returned):
    """"When this creature enters, you may return target Mercenary card from
    your graveyard to your hand." Cast with nothing announced, so the handler's
    own scan chooses — through the picker's predicate, past the Bears."""
    game = _duel(hand=[_POOL["Strongarm Thug"]], graveyard=list(graveyard))
    assert game.cast_from_hand(0, "Strongarm Thug").supported
    settle(game)
    assert _names(game.players[0].hand) == ([returned] if returned else []), game.log[-6:]


@pytest.mark.cr("109.2a", "205.3m", "601.2c")
def test_cruel_revival_returns_a_kindred_zombie_card():
    """"Destroy target non-Zombie creature. … Return up to one target Zombie
    card from your graveyard to your hand." The card role offers the Kindred
    instant and the Zombie creature card, and returns the one named."""
    game = _duel(
        hand=[_POOL["Cruel Revival"]], theirs=[_POOL["Grizzly Bears"]],
        graveyard=[_POOL["Hill Giant"], ZOMBIE_TRICK, _POOL["Scathe Zombies"]],
    )
    bears = _permanent(game, "Grizzly Bears")
    spec = game.cast_target_spec(0, _POOL["Cruel Revival"])
    (creature,) = spec["valid_targets"]
    assert sorted(entry["name"] for entry in creature["next"]) == [
        "Scathe Zombies", "Test Zombie Trick",
    ], creature["next"]
    assert game.queue_from_hand(0, "Cruel Revival", target_role_refs=[
        {"permanent_id": bears.permanent_id},
        {"graveyard_seat": 0, "graveyard_index": 1},
    ]).supported
    resolve_stack(game)
    assert not game.is_on_battlefield(bears)
    assert _names(game.players[0].hand) == ["Test Zombie Trick"], game.log[-4:]


@pytest.mark.cr("109.2a", "205.3m")
def test_unholy_grotto_puts_a_kindred_zombie_card_on_top():
    """"{B}, {T}: Put target Zombie card from your graveyard on top of your
    library." """
    game = _duel(mine=[_POOL["Unholy Grotto"]],
                 graveyard=[_POOL["Grizzly Bears"], ZOMBIE_TRICK])
    refused = game.queue_permanent_ability(
        0, "Unholy Grotto", ability_index=1, target_permanent_index=0,
    )
    assert not refused.supported
    assert game.queue_permanent_ability(
        0, "Unholy Grotto", ability_index=1, target_permanent_index=1,
    ).supported
    resolve_stack(game)
    assert game.players[0].library[0] is ZOMBIE_TRICK, game.log[-4:]
    assert _names(game.players[0].graveyard) == ["Grizzly Bears"]


@pytest.mark.cr("109.2a", "205.3m")
def test_lin_sivvi_bottoms_a_kindred_rebel_card():
    """"{3}: Put target Rebel card from your graveyard on the bottom of your
    library." """
    game = _duel(mine=[_POOL["Lin Sivvi, Defiant Hero"]],
                 graveyard=[_POOL["Grizzly Bears"], REBEL_TRICK])
    assert game.queue_permanent_ability(
        0, "Lin Sivvi, Defiant Hero", ability_index=1, target_permanent_index=1,
    ).supported
    resolve_stack(game)
    assert game.players[0].library[-1] is REBEL_TRICK, game.log[-4:]
    assert _names(game.players[0].graveyard) == ["Grizzly Bears"]


@pytest.mark.cr("109.2a", "205.3m", "702.37e")
def test_infernal_caretaker_returns_every_zombie_card_from_every_graveyard():
    """"When this creature is turned face up, return all Zombie cards from all
    graveyards to their owners' hands." The Kindred instant and the opponent's
    Zombie creature card go home; the Bears stays."""
    game = _duel(mine=[_POOL["Swamp"]] * 4,
                 graveyard=[ZOMBIE_TRICK, _POOL["Grizzly Bears"]],
                 their_graveyard=[_POOL["Scathe Zombies"]])
    caretaker = Permanent(card=face_down_card(_POOL["Infernal Caretaker"]))
    game._put_permanent_onto_battlefield(0, caretaker, None)
    _nosick(caretaker)
    resolve_stack(game)
    assert take_permanent_special_action(game, 0, caretaker, "turn_face_up") is None
    settle(game)
    assert caretaker.card.name == "Infernal Caretaker"
    assert _names(game.players[0].hand) == ["Test Zombie Trick"], game.log[-6:]
    assert _names(game.players[1].hand) == ["Scathe Zombies"]
    assert _names(game.players[0].graveyard) == ["Grizzly Bears"]


@pytest.mark.cr("109.2a", "205.3m", "604.3")
def test_soulless_one_counts_a_kindred_zombie_card_in_a_graveyard():
    """"…equal to the number of Zombies on the battlefield plus the number of
    Zombie cards in all graveyards." Itself, the Kindred instant and the
    opponent's Zombie creature card: 3. The Bears counts for nothing."""
    game = _duel(mine=[_POOL["Soulless One"]],
                 graveyard=[ZOMBIE_TRICK, _POOL["Grizzly Bears"]],
                 their_graveyard=[_POOL["Scathe Zombies"]])
    soulless = _permanent(game, "Soulless One")
    assert (soulless.effective_power, soulless.effective_toughness) == (3, 3)


# --- a cost ------------------------------------------------------------------


@pytest.mark.cr("109.2a", "205.3m", "702.37e")
def test_putrid_raptor_is_turned_up_by_discarding_a_kindred_zombie_card():
    """"Morph—Discard a Zombie card." The offer names the Kindred instant and
    the Zombie creature card, not the Island; discarding the Kindred one pays."""
    raptor = Permanent(card=face_down_card(_POOL["Putrid Raptor"]))
    game = _duel(hand=[_POOL["Island"], ZOMBIE_TRICK, _POOL["Scathe Zombies"]])
    game._put_permanent_onto_battlefield(0, raptor, None)
    _nosick(raptor)
    (offer,) = available_permanent_special_actions(game, 0)
    assert offer["cost_hand_choices"] == [
        {"hand_index": 1, "name": "Test Zombie Trick"},
        {"hand_index": 2, "name": "Scathe Zombies"},
    ], offer
    assert take_permanent_special_action(
        game, 0, raptor, "turn_face_up", cost_hand_index=0,
    ) is not None, "the Island is no Zombie card"
    assert is_face_down(raptor)
    assert take_permanent_special_action(
        game, 0, raptor, "turn_face_up", cost_hand_index=1,
    ) is None
    assert raptor.card.name == "Putrid Raptor"
    assert _names(game.players[0].graveyard) == ["Test Zombie Trick"]


# --- the top of a library ----------------------------------------------------


@pytest.mark.cr("109.2b", "205.3m", "601.3")
@pytest.mark.parametrize("top, castable", [
    (GOBLIN_RITE, True), (_POOL["Raging Goblin"], True), (TROLL_RITE, False),
])
def test_conspicuous_snoop_casts_a_kindred_goblin_spell_from_the_top(top, castable):
    """"You may cast Goblin spells from the top of your library." The Kindred
    sorcery is a Goblin spell; a Kindred Troll sorcery is not."""
    game = _duel(mine=[_POOL["Conspicuous Snoop"]], library=[top])
    assert top_castable(game, 0, game.players[0].library[0]) is castable
    result = game.cast_from_hand(0, top.name, from_zone="library")
    assert result.supported is castable, (result.details, game.log[-4:])
    if castable:
        resolve_stack(game)
        assert game.players[0].library[0] is not top


@pytest.mark.cr("109.2a", "205.3m", "613.1f")
def test_conspicuous_snoop_has_a_kindred_goblin_artifacts_activated_abilities():
    """"As long as the top card of your library is a Goblin card, this creature
    has all activated abilities of that card." """
    game = _duel(mine=[_POOL["Conspicuous Snoop"]], library=[GOBLIN_LANTERN])
    snoop = _permanent(game, "Conspicuous Snoop")
    assert granted_top_abilities(game, snoop) == ("{T}: You gain 1 life.",)
    game.players[0].library.insert(0, _POOL["Jayemdae Tome"])
    assert granted_top_abilities(game, snoop) == ()


# --- onto the battlefield ------------------------------------------------------
#
# No card in the pool puts a "<creature type> card" onto the battlefield; the
# pool prints "a Goblin **permanent** card" (CR 110.4a's union, read since kg4
# targets). A creature type alone names any card with it, a Kindred instant
# among them, and CR 400.4a ("If an instant or sorcery card would enter the
# battlefield, it remains in its previous zone") is what happens to that one.
# kg4 refused each road here until a handler said so; kg5's roads ask
# ``permanent_cards`` before the card leaves its zone, so each sentence reads,
# beside the same sentence printing "creature card". The boards — the Kindred
# card staying where it was on each road — are test_kg5_kindred_cant_enter.py.
# Invented sentences, each in a shape a real card prints with a card type.


def _sorcery(name: str, text: str) -> CardDefinition:
    return _kindred(name, "Sorcery", text)


_ONTO_THE_BATTLEFIELD = (
    "Search your library for a Goblin card, put it onto the battlefield, then shuffle.",
    "Return target Zombie card from your graveyard to the battlefield.",
    "Put target Zombie card from a graveyard onto the battlefield under your control.",
    "Return all Zombie cards from your graveyard to the battlefield.",
    _POOL["Clear the Land"].oracle_text.replace("land cards", "Goblin cards"),
    _POOL["Animal Magnetism"].oracle_text.replace("a creature card", "a Goblin card"),
    "Reveal cards from the top of your library until you reveal a Goblin card. Put "
    "that card onto the battlefield and put all other cards revealed this way into "
    "your graveyard.",
)


@pytest.mark.cr("109.2a", "205.3m", "400.4a")
@pytest.mark.parametrize("text", _ONTO_THE_BATTLEFIELD)
def test_a_creature_type_card_put_onto_the_battlefield_is_read(text):
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(_sorcery("Test Kindred Muster", text))
    assert program.supported, program
    for word in ("Goblin", "Zombie"):
        text = text.replace(f"{word} card", f"{word} creature card")
    assert compile_card_oracle(_sorcery("Test Creature Muster", text)).supported, text


# --- the spell readers, which already asked the subtype alone ----------------


@pytest.mark.cr("205.3m", "308.2", "601.2f")
def test_goblin_warchief_discounts_a_kindred_goblin_spell():
    """"Goblin spells you cast cost {1} less to cast." {1}{R} paid with {R}."""
    game = _duel(mine=[_POOL["Goblin Warchief"]], hand=[GOBLIN_RITE, TROLL_RITE])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"R": 1})
    assert not game.cast_from_hand(0, "Test Troll Rite").supported, "no Goblin, no discount"
    result = game.cast_from_hand(0, "Test Goblin Rite")
    assert result.supported, (result.details, game.log[-4:])
    resolve_stack(game)
    assert game.players[0].life == 21


@pytest.mark.cr("205.3m", "308.2", "603.2")
def test_rin_and_seri_sees_a_kindred_dog_spell():
    """"Whenever you cast a Dog spell, create a 1/1 green Cat creature token." """
    game = _duel(mine=[_POOL["Rin and Seri, Inseparable"]], hand=[DOG_TRICK])
    assert game.cast_from_hand(0, "Test Dog Trick").supported
    resolve_stack(game)
    tokens = sorted(p.card.name for p in game.controlled_by(0) if p.metadata.get("is_token"))
    assert tokens == ["Cat Token"], game.log[-6:]


@pytest.mark.cr("205.3m", "308.2", "101.2")
def test_root_sliver_makes_a_kindred_sliver_spell_uncounterable():
    """"Sliver spells can't be countered." """
    game = _duel(mine=[_POOL["Root Sliver"]], hand=[SLIVER_TRICK])
    game.players[1].hand.append(_POOL["Counterspell"])
    assert game.queue_from_hand(0, "Test Sliver Trick").supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    settle(game)
    assert "Counterspell: Test Sliver Trick can't be countered (Root Sliver)" in game.log
    assert game.players[0].life == 21


@pytest.mark.cr("205.3m", "308.2", "702.8a")
@pytest.mark.parametrize("quick_sliver, spell, flashed", [
    (True, SLIVER_RITE, True), (False, SLIVER_RITE, False), (True, TROLL_RITE, False),
])
def test_quick_sliver_flashes_a_kindred_sliver_sorcery(quick_sliver, spell, flashed):
    """"Any player may cast Sliver spells as though they had flash." Asked on
    the opponent's turn through the one question both timing gates ask (the
    web's action and the AI's chooser, ``casts_at_instant_speed``): a Kindred
    Sliver sorcery with Quick Sliver out, not without it, and never a Kindred
    Troll one."""
    game = _duel(mine=[_POOL["Quick Sliver"]] if quick_sliver else [],
                 hand=[spell], active=1)
    game.priority_player_index = 0
    assert casts_at_instant_speed(spell, game, 0) is flashed


@pytest.mark.cr("205.3m", "308.2", "702.38a")
@pytest.mark.parametrize("hand, counters", [
    ((ZOMBIE_TRICK, _POOL["Grizzly Bears"]), 1),
    ((_POOL["Grizzly Bears"],), 0),
])
def test_amplify_reveals_a_kindred_card_that_shares_a_creature_type(hand, counters):
    """"Amplify 1 (As this creature enters, put a +1/+1 counter on it for each
    Zombie card you reveal in your hand.)" (Embalmed Brawler.) CR 702.38a's
    "cards … that share a creature type with it": the Kindred Zombie does."""
    game = _duel(hand=[_POOL["Embalmed Brawler"], *hand])
    assert game.cast_from_hand(0, "Embalmed Brawler").supported
    settle(game)
    brawler = _permanent(game, "Embalmed Brawler")
    assert counters_on(brawler, "+1/+1") == counters, game.log[-6:]

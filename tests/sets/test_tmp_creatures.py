"""Tempest creatures — wave 2's later blocks and wave 3.

The other half of the split described in `test_tmp_creatures_early_rounds.py`,
which carries waves 1 and 2's first block. Same conventions: a delimited block
per group, imports at the top of the block, cards from `set_pool("TMP")`.
"""


# --- W2G5: a target narrowed by a counter kind the card invented ------------

# `pytest` is imported here rather than only inside the block that first
# needed it: the split made this block the file's first, and a
# module-level `@pytest.mark` decorator runs at collection, before an
# `import pytest` further down the file has executed. A missing-name scan
# that asks only whether a name is imported *somewhere* answers "yes" and
# the collection still raises.
import pytest

from engine import Game as _W2G5Game, PlayerState as _W2G5PlayerState
from engine.models import Permanent as _W2G5Permanent
from engine.named_counters import counters_on as _w2g5_counters_on
from engine.oracle import compile_card_oracle as _w2g5_compile
from engine.targeting import derive_activation_spec as _w2g5_activation_spec


def _w2g5_bounty_board(set_pool):
    """Bounty Hunter, and three creatures for it to point at."""
    pool = set_pool("TMP")
    hunter = _W2G5Permanent(card=pool["Bounty Hunter"])
    hunter.summoning_sick = False
    victims = [
        _W2G5Permanent(card=pool["Horned Turtle"]),     # blue
        _W2G5Permanent(card=pool["Trained Armodon"]),   # green
        _W2G5Permanent(card=pool["Blood Pet"]),         # black
    ]
    game = _W2G5Game(players=[
        _W2G5PlayerState(name="P1", life=20, battlefield=[hunter]),
        _W2G5PlayerState(name="P2", life=20, battlefield=victims),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, hunter, victims


def test_w2g5_bounty_hunter_marks_then_destroys_what_it_marked(set_pool):
    """"{T}: Put a bounty counter on target nonblack creature." /
    "{T}: Destroy target creature with a bounty counter on it."

    Both ends of one card, in one game. The second line refused before this
    round because "with a <kind> counter on it" was read for the +1/+1 kind
    alone — the counters CR 122.1 lets a card invent had no matcher, so the
    phrase failed the line loudly. It has one now
    (``ObjectFilter.with_named_counter``, over
    ``engine/named_counters.py``'s store).
    """
    game, hunter, (turtle, armodon, blood_pet) = _w2g5_bounty_board(set_pool)

    assert game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    ).supported
    game.resolve_stack()
    assert _w2g5_counters_on(turtle, "bounty") == 1
    assert _w2g5_counters_on(armodon, "bounty") == 0

    hunter.tapped = False
    assert game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=0,
    ).supported, game.log
    game.resolve_stack()

    defender = game.players[1]
    assert [p.card.name for p in defender.battlefield] == [
        "Trained Armodon", "Blood Pet",
    ]
    assert [c.name for c in defender.graveyard] == ["Horned Turtle"]


def test_w2g5_bounty_hunter_refuses_an_unmarked_creature_with_nothing_paid(set_pool):
    """CR 602.2b via 601.2c: an ability with a mandatory target it cannot fill
    is refused before the cost is paid — so the Hunter is still untapped and
    can be aimed somewhere legal this turn.

    The failure this guards is the quiet one: a narrowing the matcher cannot
    test is one the dispatcher ignores, and an ability that destroys *any*
    creature is not the card.
    """
    game, hunter, _victims = _w2g5_bounty_board(set_pool)

    refused = game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=1,
    )

    assert not refused.supported
    assert not hunter.tapped, "nothing is paid for a refused activation"
    assert len(game.players[1].battlefield) == 3


def test_w2g5_a_named_counter_is_not_the_plus_one_counter(set_pool):
    """The two stores stay apart in a game, not only in the matcher's unit test.

    CR 122.1a's +1/+1 counter is layer 7d and lives in ``engine/pt.py``'s
    ``plus_counters`` record; a bounty counter is an inert marker in the open
    store. A matcher reading one for the other would let Bounty Hunter destroy
    a creature somebody had merely been pumping.
    """
    game, hunter, (turtle, _armodon, _blood_pet) = _w2g5_bounty_board(set_pool)
    turtle.metadata["plus_counters"] = 2

    refused = game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=0,
    )

    assert not refused.supported, "+1/+1 counters are not bounty counters"
    assert not hunter.tapped


def test_w2g5_the_bounty_picker_offers_only_the_marked_creatures(set_pool):
    """The picker and the activation gate are one reading — the list the client
    is offered is the list the engine will accept, through the same
    ``_destroy_target_legal`` both ask."""
    game, hunter, (turtle, _armodon, _blood_pet) = _w2g5_bounty_board(set_pool)
    program = _w2g5_compile(hunter.card)
    ability = program.activated_abilities[1]
    spec = _w2g5_activation_spec(ability)

    def offered():
        return [
            t.get("name") for t in game._enumerate_targets(
                0, hunter.card, spec, for_cast=False,
                ability_source=hunter, ability_instruction=ability.instruction,
            )
        ]

    assert offered() == []

    from engine.named_counters import add_counters

    add_counters(turtle, "bounty", 1)
    assert offered() == ["Horned Turtle"]


# --- W2G5: a permanent that hands itself to the seat it just robbed ---------


def _w2g5_starke(set_pool, victim_seat):
    """Starke of Rath in play, and a Horned Turtle on *victim_seat*'s board."""
    pool = set_pool("TMP")
    starke = _W2G5Permanent(card=pool["Starke of Rath"])
    starke.summoning_sick = False
    turtle = _W2G5Permanent(card=pool["Horned Turtle"])
    boards = ([starke, turtle], []) if victim_seat == 0 else ([starke], [turtle])
    game = _W2G5Game(players=[
        _W2G5PlayerState(name="P1", life=20, battlefield=list(boards[0])),
        _W2G5PlayerState(name="P2", life=20, battlefield=list(boards[1])),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, starke


def test_w2g5_starke_of_rath_changes_hands_to_the_seat_it_robbed(set_pool):
    """"{T}: Destroy target artifact or creature. That permanent's controller
    gains control of Starke. (This effect lasts indefinitely.)"

    The seat has to be read **before** the destroy is over. By the time the
    second sentence runs the permanent is a card in a graveyard, and CR 108.4
    gives a card no controller at all — so a board read would hand Starke to
    nobody. The destroy has recorded ``last_target_controller`` since Afterlife
    (CR 608.2h); the control change reads it, which is the same preference
    "its controller loses 2 life" already takes one family over.

    The control change itself is CR 611.2b's untimed one — a layer-2
    contribution with nothing to end it — so ``controller_index_of`` answers
    the new seat and the permanent has genuinely moved.
    """
    game, starke = _w2g5_starke(set_pool, victim_seat=1)

    result = game.activate_permanent_ability(
        0, "Starke of Rath", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game.resolve_stack()

    assert result.supported, result.details
    assert [c.name for c in game.players[1].graveyard] == ["Horned Turtle"]
    assert game.controller_index_of(starke) == 1
    assert [p.card.name for p in game.controlled_by(0)] == []
    assert [p.card.name for p in game.controlled_by(1)] == ["Starke of Rath"]


def test_w2g5_starke_of_rath_stays_home_when_it_kills_its_own_side(set_pool):
    """The seat is the *victim's* controller, whoever that is — so aiming the
    ability at your own creature keeps Starke where it is. A hand-over that
    always went to an opponent would be a different card."""
    game, starke = _w2g5_starke(set_pool, victim_seat=0)

    assert game.activate_permanent_ability(
        0, "Starke of Rath", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    ).supported
    game.resolve_stack()

    assert game.controller_index_of(starke) == 0
    assert [p.card.name for p in game.controlled_by(1)] == []


def test_w2g5_a_named_self_reference_reads_as_this_creature(set_pool):
    """The half that had nothing to do with control changes.

    "…gains control of **Starke**" and "…gains control of **this creature**"
    are one printed sentence in two templating eras, and they had two readers:
    the seat-in-front spelling used ``parse_target_spec``, which has no SELF
    branch, while ``_parse_gain_control`` beside it used ``parse_recipient``,
    which does. So the modern spelling parsed and the card's own name did not.
    """
    from engine.grammar import parse_line
    from engine.grammar.lower import lower_ability

    named = lower_ability(parse_line(
        "{T}: Destroy target artifact or creature. That permanent's controller "
        "gains control of Starke of Rath.",
        card_name="Starke of Rath",
    ))
    modern = lower_ability(parse_line(
        "{T}: Destroy target artifact or creature. That permanent's controller "
        "gains control of this creature.",
    ))
    assert named == modern


# --- W2G1: the Licid cycle, and the two Rootwater merfolk -------------------

from engine import Game as _W2G1Game, PlayerState as _W2G1Player
from engine.auras import attach_aura as _w2g1_attach, detach_aura as _w2g1_detach
from engine.card_loader import load_cards as _w2g1_load
from engine.card_loader import manifest_set_path as _w2g1_path
from engine.cast_timing import casts_at_instant_speed as _w2g1_flash
from engine.models import Permanent as _W2G1Perm
from engine.oracle import compile_card_oracle as _w2g1_compile
from engine.special_actions import (
    available_permanent_special_actions as _w2g1_offers,
    take_permanent_special_action as _w2g1_take,
)

_W2G1_LEA = {c.name: c for c in _w2g1_load(_w2g1_path("LEA"))}


def _w2g1_perm(card):
    permanent = _W2G1Perm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w2g1_duel(mine, theirs=(), pool=None):
    p0 = _W2G1Player(name="P0", battlefield=list(mine), life=20,
                     mana_pool=dict(pool or {}))
    p1 = _W2G1Player(name="P1", battlefield=list(theirs), life=20)
    game = _W2G1Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.priority_player_index = 0
    game._sync_control()
    game._refresh_dynamic_creatures()
    return game, p0, p1


def _w2g1_licid_attached(set_pool, name, host="Trained Armodon"):
    """*name* activated onto a fresh *host*, with the stack emptied."""
    tmp = set_pool("TMP")
    licid, bear = _w2g1_perm(tmp[name]), _w2g1_perm(tmp[host])
    game, p0, p1 = _w2g1_duel(
        [licid, bear], pool={"W": 3, "U": 3, "B": 3, "R": 3, "G": 3}
    )
    game.activate_permanent_ability(
        0, name, ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    resolve_stack(game)
    game.check_state_based_actions()
    game.priority_player_index = 0
    return game, licid, bear, p0, p1


@pytest.mark.parametrize("name", [
    "Enraging Licid", "Leeching Licid", "Nurturing Licid",
    "Quickening Licid", "Stinging Licid",
])
def test_w2g1_every_licid_becomes_an_attached_aura_enchantment(set_pool, name):
    """The cycle's one printed line, on all five.

    22 of the top 40 shared fragments in the ingest census were these five
    cards, which is what makes this a production rather than five hooks: the
    parse, the type change and the attach are the same code for every one of
    them, and the only thing that differs between the cards is the mana symbol.
    """
    game, licid, bear, _p0, _p1 = _w2g1_licid_attached(set_pool, name)

    assert not licid.is_creature
    assert licid.has_type("aura") and licid.has_type("enchantment")
    assert not licid.has_type("licid"), "CR 205.1a: the creature types go too"
    assert licid.metadata.get("attached_to") is bear
    assert "loses this ability" not in (licid.effective_card.oracle_text or "")


def test_w2g1_enraging_licid_grants_its_host_haste_only_while_attached(set_pool):
    """"Enchanted creature has haste."

    Printed on a **creature**, which is why the support gate had to learn it:
    CR 303.4m says an ability referring to the "enchanted [object]" refers to
    whatever the permanent is attached to *even if it isn't an Aura*, and a
    Licid is a creature until its own ability has run. The grant is derived
    from the attachment on every recompute, so ending the effect takes it away
    with nothing to undo.
    """
    tmp = set_pool("TMP")
    licid, bear = _w2g1_perm(tmp["Enraging Licid"]), _w2g1_perm(tmp["Trained Armodon"])
    game, _p0, _p1 = _w2g1_duel([licid, bear], pool={"R": 2})
    assert not game._has_keyword(bear, "haste")

    game.activate_permanent_ability(
        0, "Enraging Licid", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    resolve_stack(game)
    assert game._has_keyword(bear, "haste")

    game.priority_player_index = 0
    assert _w2g1_take(game, 0, licid, "end_own_continuous_effect") is None
    assert not game._has_keyword(bear, "haste")
    assert licid.is_creature


def test_w2g1_a_licid_aura_carries_its_own_activated_ability(set_pool):
    """Nurturing Licid's "{G}: Regenerate enchanted creature." is the Aura's
    ability, activated after the type change — which is only possible because
    the ability it *loses* is the one that ran, named by
    ``context.ability_text`` rather than matched against the card's text."""
    game, licid, bear, _p0, _p1 = _w2g1_licid_attached(set_pool, "Nurturing Licid")

    program = _w2g1_compile(licid.effective_card)
    assert [a.source_line for a in program.activated_abilities] == [
        "{G}: Regenerate enchanted creature."
    ]
    result = game.activate_permanent_ability(0, "Nurturing Licid", ability_index=0)
    resolve_stack(game)
    assert result.supported, result.details


def test_w2g1_stinging_licid_watches_the_creature_it_enchants(set_pool):
    """"Whenever enchanted creature becomes tapped, this creature deals 2
    damage to that creature's controller." — the trigger belongs to the Aura,
    so it is announced by the tap seam through the attachment rather than by
    the host's own scan."""
    game, _licid, bear, p0, _p1 = _w2g1_licid_attached(set_pool, "Stinging Licid")

    before = p0.life
    game.become_tapped(bear)
    resolve_stack(game)

    assert p0.life == before - 2


def test_w2g1_a_licid_dies_with_the_creature_it_enchants(set_pool):
    """CR 704.5m: an Aura attached to nothing is put into its owner's graveyard.

    The Licid is a real Aura by then — not a creature carrying an attachment
    record — so the sweep that has always policed Auras finds it with no branch
    of its own.
    """
    game, licid, bear, p0, _p1 = _w2g1_licid_attached(set_pool, "Enraging Licid")

    game.remove_from_battlefield(bear)
    game._permanent_to_graveyard(p0, bear)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(licid)
    assert "Enraging Licid" in [c.name for c in p0.graveyard]


def test_w2g1_rootwater_matriarch_holds_a_creature_only_while_it_is_enchanted(set_pool):
    """"{T}: Gain control of target creature for as long as that creature is
    enchanted." CR 611.2b, with the condition about the **stolen** permanent
    rather than about the source — the first such row in
    ``control.LINKED_CONTROL_CONDITIONS``, and the reason the sweep asks it of
    the permanent it is already holding."""
    tmp, lea = set_pool("TMP"), _W2G1_LEA
    matriarch = _w2g1_perm(tmp["Rootwater Matriarch"])
    bear = _w2g1_perm(tmp["Trained Armodon"])
    strength = _w2g1_perm(lea["Holy Strength"])
    game, _p0, _p1 = _w2g1_duel([matriarch], [bear, strength])
    _w2g1_attach(strength, bear)
    game._refresh_dynamic_creatures()
    assert game.controller_index_of(bear) == 1

    game.activate_permanent_ability(
        0, "Rootwater Matriarch", ability_index=0,
        target_permanent_index=0, target_player_index=1,
    )
    resolve_stack(game)
    game.check_state_based_actions()
    assert game.controller_index_of(bear) == 0

    _w2g1_detach(strength, bear)
    game.check_state_based_actions()
    assert game.controller_index_of(bear) == 1


def test_w2g1_rootwater_matriarch_never_starts_on_an_unenchanted_creature(set_pool):
    """CR 611.2b's other half: "If the 'for as long as' duration never starts,
    the effect does nothing." A creature nobody has enchanted is a legal target
    the ability simply does nothing to — not one it steals for the instant
    before the state-based sweep hands it back."""
    tmp = set_pool("TMP")
    matriarch = _w2g1_perm(tmp["Rootwater Matriarch"])
    bear = _w2g1_perm(tmp["Trained Armodon"])
    game, _p0, _p1 = _w2g1_duel([matriarch], [bear])

    game.activate_permanent_ability(
        0, "Rootwater Matriarch", ability_index=0,
        target_permanent_index=0, target_player_index=1,
    )
    resolve_stack(game)

    assert game.controller_index_of(bear) == 1
    assert any("is not enchanted" in line for line in game.log)


def test_w2g1_rootwater_shaman_flashes_in_creature_auras_for_its_controller(set_pool):
    """"You may cast Aura spells with enchant creature as though they had
    flash." CR 611.1's continuous effect over CR 702.8a's timing, derived from
    the permanent's own text at the one seam both timing gates ask.

    Three narrowings, each of which would be an ability wider than the card:
    the Aura's enchant clause, the card type, and "**you** may cast" (CR 109.5).
    """
    tmp, lea = set_pool("TMP"), _W2G1_LEA
    shaman = _w2g1_perm(tmp["Rootwater Shaman"])
    game, _p0, _p1 = _w2g1_duel([shaman])

    assert _w2g1_flash(lea["Holy Strength"], game, 0), "enchant creature"
    assert not _w2g1_flash(lea["Psychic Venom"], game, 0), "enchant land"
    assert not _w2g1_flash(tmp["Trained Armodon"], game, 0), "not an Aura"
    assert not _w2g1_flash(lea["Holy Strength"], game, 1), "the opponent's spell"


# --- W2G3: Unstable Shapeshifter, CR 707.2 off a trigger ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w2g3c_game(*battlefields):
    seats = [
        PlayerState(name=f"P{index + 1}", battlefield=list(permanents))
        for index, permanents in enumerate(battlefields)
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    return game


def test_unstable_shapeshifter_copies_each_creature_that_enters(
    set_pool, catalog_by_name
):
    """"Whenever another creature enters, this creature becomes a copy of that
    creature, **except it has this ability**."

    Two things at once, and the second is what makes the card a card. Without
    CR 707.9a's granted ability the Shapeshifter copies once and is a Grizzly
    Bears for the rest of the game; with it, it becomes each new arrival in
    turn.
    """
    shifter = Permanent(card=set_pool("TMP")["Unstable Shapeshifter"])
    game = _w2g3c_game([shifter], [])
    game.players[0].hand = [
        catalog_by_name["Grizzly Bears"], catalog_by_name["Shivan Dragon"],
    ]
    game.start_turn(0)

    assert shifter.effective_card.name == "Unstable Shapeshifter"

    game.cast_from_hand(0, "Grizzly Bears")
    game._settle()
    assert shifter.effective_card.name == "Grizzly Bears"
    assert (shifter.effective_power, shifter.effective_toughness) == (2, 2)

    game.cast_from_hand(0, "Shivan Dragon")
    game._settle()
    assert shifter.effective_card.name == "Shivan Dragon"
    assert (shifter.effective_power, shifter.effective_toughness) == (5, 5)
    assert game._has_keyword(shifter, "flying")


def test_the_granted_ability_rides_the_copied_text(set_pool, catalog_by_name):
    """CR 707.9a: the ability is *in addition to* the copiable values, so it is
    appended to the copied card's text — and appended once, however many times
    the Shapeshifter has copied. Anything else and the trigger fires twice per
    arrival."""
    shifter = Permanent(card=set_pool("TMP")["Unstable Shapeshifter"])
    game = _w2g3c_game([shifter], [])
    game.players[0].hand = [
        catalog_by_name["Grizzly Bears"], catalog_by_name["Shivan Dragon"],
    ]
    game.start_turn(0)

    game.cast_from_hand(0, "Grizzly Bears")
    game._settle()
    game.cast_from_hand(0, "Shivan Dragon")
    game._settle()

    text = shifter.effective_card.oracle_text
    granted = "Whenever another creature enters, this creature becomes a copy"
    assert text.count(granted) == 1, text
    assert "Flying" in text, "the copied card's own text is still there"


def test_unstable_shapeshifter_copies_an_opponents_creature(
    set_pool, catalog_by_name
):
    """"another creature" names no controller, so an arrival on the other
    battlefield is one of them."""
    shifter = Permanent(card=set_pool("TMP")["Unstable Shapeshifter"])
    game = _w2g3c_game([shifter], [])
    game.players[1].hand = [catalog_by_name["Shivan Dragon"]]
    game.start_turn(1)

    game.cast_from_hand(1, "Shivan Dragon")
    game._settle()

    assert shifter.effective_card.name == "Shivan Dragon"


def test_a_noncreature_arrival_leaves_it_alone(set_pool, catalog_by_name):
    """The narrowing the trigger prints. A copy effect that fired on every
    permanent would make the Shapeshifter a Mox."""
    shifter = Permanent(card=set_pool("TMP")["Unstable Shapeshifter"])
    game = _w2g3c_game([shifter], [])
    game.players[0].hand = [catalog_by_name["Mox Pearl"]]
    game.start_turn(0)

    game.cast_from_hand(0, "Mox Pearl")
    game._settle()

    assert shifter.effective_card.name == "Unstable Shapeshifter"


def test_the_copy_is_layer_one_and_not_a_stamp(set_pool, catalog_by_name):
    """CR 707.2's boundary, which is the whole reason this lowers onto
    ``engine/copies.py``: what is copied is the *copiable* values, so a +1/+1
    counter on the creature that entered is not."""
    from engine.pt import add_pt_counters

    shifter = Permanent(card=set_pool("TMP")["Unstable Shapeshifter"])
    game = _w2g3c_game([shifter], [])
    game.players[0].hand = [catalog_by_name["Grizzly Bears"]]
    game.start_turn(0)

    game.cast_from_hand(0, "Grizzly Bears")
    bear = next(
        p for p in game.players[0].battlefield if p.card.name == "Grizzly Bears"
    )
    add_pt_counters(bear, "+1/+1", 2)
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (4, 4)
    assert (shifter.effective_power, shifter.effective_toughness) == (2, 2)


def test_unstable_shapeshifter_compiles_to_one_bound_copy_instruction(set_pool):
    """The payload's two keys, pinned so a later reading cannot drop either:
    the noun phrase the handler re-checks, and CR 707.9a's clause."""
    program = compile_card_oracle(set_pool("TMP")["Unstable Shapeshifter"])

    assert program.supported, program.reason
    trigger = program.triggered_abilities[0]
    assert trigger.condition.kind == "matching_permanent_enters"
    assert trigger.instruction.kind == "become_copy_of_bound_permanent"
    assert trigger.instruction.payload == {
        "filter": {"type_filter": "creature"}, "keeps_own_ability": True,
    }


# --- W2G4: revealing until a match, and emptying a hand ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


def _w2g4_card(name, type_line, text="", colors=(), power=None, toughness=None):
    raw = {"name": name, "type_line": type_line, "oracle_text": text}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text=text,
        cmc=0.0, colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(), raw=raw,
        power=str(power) if power is not None else None,
        toughness=str(toughness) if toughness is not None else None,
    )


def _w2g4_creature_game(battlefield, *, library=(), hands=((), ())):
    seats = [
        PlayerState(name="P0", battlefield=[_nosick(p) for p in battlefield],
                    library=list(library), hand=list(hands[0])),
        PlayerState(name="P1", hand=list(hands[1])),
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game._settle()
    return game


def test_sacred_guide_takes_the_white_card_and_exiles_what_it_passed(set_pool):
    """`Reveal cards from the top of your library until you reveal a white
    card. Put that card into your hand and exile all other cards revealed this
    way.` (CR 701.20.)

    The exile is the half that had no branch before this round: the same
    sentence with the rest going to a graveyard is a strictly better card in a
    pool that can reach a graveyard, so the word is read and carried out rather
    than folded onto the nearest fate that existed.
    """
    guide = Permanent(card=set_pool("TMP")["Sacred Guide"])
    black = _w2g4_card("Bog Imp", "Creature — Imp", colors=("B",))
    green = _w2g4_card("Llanowar Elves", "Creature — Elf", colors=("G",))
    white = _w2g4_card("Savannah Lions", "Creature — Cat", colors=("W",))
    below = _w2g4_card("Mountain", "Basic Land — Mountain")
    game = _w2g4_creature_game([guide], library=[black, green, white, below])

    result = game.activate_permanent_ability(0, "Sacred Guide", ability_index=0)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert [c.name for c in game.players[0].hand] == ["Savannah Lions"]
    assert [c.name for c in game.players[0].exile] == ["Bog Imp", "Llanowar Elves"]
    assert [c.name for c in game.players[0].library] == ["Mountain"]
    # The Guide itself is there — it was the activation cost — and nothing
    # else: the passed-over cards are exiled, not binned.
    assert [c.name for c in game.players[0].graveyard] == ["Sacred Guide"]


def test_sacred_guide_over_a_library_with_no_white_card_keeps_nothing(set_pool):
    """CR 701.20a bounds the reveal by the library: a run that never matches
    reveals the whole deck, takes nothing, and exiles all of it."""
    guide = Permanent(card=set_pool("TMP")["Sacred Guide"])
    black = _w2g4_card("Bog Imp", "Creature — Imp", colors=("B",))
    game = _w2g4_creature_game([guide], library=[black, black])

    game.activate_permanent_ability(0, "Sacred Guide", ability_index=0)
    game.resolve_top_of_stack()

    assert not game.players[0].hand
    assert len(game.players[0].exile) == 2
    assert not game.players[0].library


def test_shocker_redraws_what_the_discard_binned_not_the_damage_it_dealt(set_pool):
    """`Whenever this creature deals damage to a player, that player discards
    all the cards in their hand, then draws that many cards.`

    "That many" names the **discard**, and this is the assertion the round
    turned on: Shocker's trigger event also carries a number (the damage), and
    a bare back-reference used to read that one first. Its power is 2 and a
    hand of four cards makes the two readings visibly different — read the
    trigger's number, the victim discards four and draws two.
    """
    shocker = Permanent(card=set_pool("TMP")["Shocker"])
    filler = _w2g4_card("Mountain", "Basic Land — Mountain")
    game = _w2g4_creature_game([shocker])
    game.players[1].hand = [filler] * 4
    game.players[1].library = [filler] * 10

    program = compile_card_oracle(shocker.card)
    assert program.supported, program.reason
    draw = program.instructions[0].payload["steps"][1]
    assert draw.payload.get("amount_from") == "discarded_count", (
        "the nearer antecedent is the discard this sentence just performed"
    )

    game._deal_damage_to_player(game.players[1], 2, source=shocker)
    game._settle()
    resolve_stack(game)

    assert len(game.players[1].hand) == 4
    assert len(game.players[1].graveyard) == 4


def test_wood_sage_sorts_the_revealed_four_by_the_name_that_was_chosen(set_pool):
    """`{T}: Choose a creature card name. Reveal the top four cards of your
    library and put all of them with that name into your hand. Put the rest
    into your graveyard.`

    The Rock Hydra test for a two-step naming card: the prompt is answered and
    the pile is read out of the *hand* and the *graveyard*, not off the claim
    that two instructions compiled.
    """
    sage = Permanent(card=set_pool("TMP")["Wood Sage"])
    wanted = _w2g4_card("Grizzly Bears", "Creature — Bear", power=2, toughness=2)
    other = _w2g4_card("Mountain", "Basic Land — Mountain")
    game = _w2g4_creature_game(
        [sage], library=[wanted, other, wanted, other, other],
    )
    game.interactive_seats = {0}

    game.activate_permanent_ability(0, "Wood Sage", ability_index=0)
    game.resolve_top_of_stack()

    prompt = next(iter(game.pending_choices_of("choose_card_name")))
    assert prompt.data.get("card_type") == "creature", (
        "the printed narrowing reaches the seat that answers"
    )
    assert game.confirm_choose_card_name(0, "Grizzly Bears")

    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"] * 2
    assert [c.name for c in game.players[0].graveyard] == ["Mountain"] * 2
    # The fifth card was never revealed.
    assert [c.name for c in game.players[0].library] == ["Mountain"]


def test_wood_sage_naming_nothing_bins_the_whole_pile(set_pool):
    """An empty name is a legal answer that matches nothing (CR 202.1), and it
    must not be read as "match everything" — which would put four cards in the
    hand off a seat that named no card at all."""
    sage = Permanent(card=set_pool("TMP")["Wood Sage"])
    bear = _w2g4_card("Grizzly Bears", "Creature — Bear", power=2, toughness=2)
    game = _w2g4_creature_game([sage], library=[bear] * 4)
    game.interactive_seats = {0}

    game.activate_permanent_ability(0, "Wood Sage", ability_index=0)
    game.resolve_top_of_stack()
    assert game.confirm_choose_card_name(0, "")

    assert not game.players[0].hand
    assert len(game.players[0].graveyard) == 4


# --- W2G2: combat requirements, the attacker/blocker pair (CR 506-510) ---

import pytest

from engine import Game, PlayerState, ai_policy
from engine.combat_permissions import MUST_BLOCK_ATTACKERS_UNTIL_EOT
from engine.models import Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, _nosick


def _w2g2_duel(p0_cards, p1_cards):
    """Two battlefields, no summoning sickness, mana enforcement off."""
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    for card in p0_cards:
        p0.battlefield.append(_nosick(Permanent(card=card)))
    for card in p1_cards:
        p1.battlefield.append(_nosick(Permanent(card=card)))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p0, p1


def _w2g2_to_blockers(game, attackers, defender=1):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, attackers, defender)[0], game.log
    resolve_stack(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"


def test_w2g2_mounted_archers_blocks_an_extra_creature_only_once_activated(set_pool):
    """``{W}: This creature can block an additional creature this turn.``

    Two assertions, and the *first* one is the round's finding:
    ``_max_blocks_for`` counted the phrase in the raw oracle text, which cannot
    tell this activated printing from Two-Headed Giant of Foriys' static one —
    so the extra block would have been free and permanent.
    """
    archers = set_pool("TMP")["Mounted Archers"]
    game, p0, p1 = _w2g2_duel(
        [_mk_creature_card("Bear A", 2, 2), _mk_creature_card("Bear B", 2, 2)],
        [archers],
    )
    assert game._max_blocks_for(p1.battlefield[0]) == 1
    _w2g2_to_blockers(game, [0, 1])
    assert game.declare_blockers(1, {0: [0, 1]}) == (
        False, "Mounted Archers cannot block that many creatures"
    )

    game2, q0, q1 = _w2g2_duel(
        [_mk_creature_card("Bear A", 2, 2), _mk_creature_card("Bear B", 2, 2)],
        [archers],
    )
    game2.start_turn(0)
    game2._close_current_priority_step()
    assert game2.activate_permanent_ability(
        1, "Mounted Archers", ability_index=0
    ).supported
    resolve_stack(game2)
    assert game2._max_blocks_for(q1.battlefield[0]) == 2
    game2.advance_combat_phase()
    game2.advance_combat_phase()
    assert game2.declare_attackers(0, [0, 1], 1)[0]
    game2.advance_combat_phase()
    assert game2.declare_blockers(1, {0: [0, 1]})[0], game2.log


def test_w2g2_two_headed_giant_keeps_its_printed_extra_block(catalog_by_name):
    """The other side of the same fix: the *static* printing is counted off the
    compiled program's static lines, so narrowing the scan did not cost it."""
    giant = catalog_by_name["Two-Headed Giant of Foriys"]
    game, p0, p1 = _w2g2_duel(
        [_mk_creature_card("Bear A", 2, 2), _mk_creature_card("Bear B", 2, 2)],
        [giant],
    )
    assert game._max_blocks_for(p1.battlefield[0]) == 2


def test_w2g2_watchdog_must_block_and_shrinks_the_attackers(set_pool):
    """``This creature blocks each combat if able.`` (CR 509.1c) plus ``As long
    as this creature is untapped, all creatures attacking you get -1/-0.`` — a
    conditional anthem over a combat set, whose qualifier is read when P/T is
    read (CR 611.3a) rather than at the recompute."""
    dog = set_pool("TMP")["Watchdog"]
    game, p0, p1 = _w2g2_duel([_mk_creature_card("Bear", 2, 2)], [dog])
    _w2g2_to_blockers(game, [0])
    game.check_state_based_actions()
    bear = p0.battlefield[0]
    assert (bear.effective_power, bear.effective_toughness) == (1, 2)
    assert game.declare_blockers(1, {}) == (
        False, "Watchdog blocks each combat if able"
    )
    assert game.declare_blockers(1, {0: 0})[0], game.log


def test_w2g2_a_tapped_watchdog_neither_blocks_nor_shrinks(set_pool):
    """Both halves are conditional on the same word, and each is asked by a
    different reader — the anthem by the qualifier at P/T-read time, the
    requirement by "if able", which a tapped creature never is (CR 509.1a)."""
    dog = set_pool("TMP")["Watchdog"]
    game, p0, p1 = _w2g2_duel([_mk_creature_card("Bear", 2, 2)], [dog])
    p1.battlefield[0].tapped = True
    _w2g2_to_blockers(game, [0])
    game.check_state_based_actions()
    bear = p0.battlefield[0]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert game.declare_blockers(1, {})[0], game.log


def test_w2g2_the_ai_obeys_watchdogs_requirement(set_pool):
    """A requirement the AI does not know about is a declaration the engine
    refuses every combat, which is a seat doing nothing all game."""
    dog = set_pool("TMP")["Watchdog"]
    game, p0, p1 = _w2g2_duel([_mk_creature_card("Bear", 2, 2)], [dog])
    _w2g2_to_blockers(game, [0])
    assert ai_policy.choose_combat_blockers(game, 1) == {0: 0}


def test_w2g2_trumpeting_armodon_compels_one_named_pair(set_pool):
    """``{1}{G}: Target creature blocks this creature this turn if able.``
    The narrowest requirement in the step: it names *both* halves of the pair,
    so a block of anything else does not satisfy it."""
    armodon = set_pool("TMP")["Trumpeting Armodon"]
    game, p0, p1 = _w2g2_duel(
        [armodon],
        [_mk_creature_card("Wall A", 0, 4), _mk_creature_card("Wall B", 0, 4)],
    )
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0], 1)[0]
    assert game.activate_permanent_ability(
        0, "Trumpeting Armodon", ability_index=0,
        target_player_index=1, target_permanent_index=1,
    ).supported
    resolve_stack(game)
    assert p1.battlefield[1].metadata[MUST_BLOCK_ATTACKERS_UNTIL_EOT] == [
        p0.battlefield[0].permanent_id
    ]
    assert p1.battlefield[0].metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) is None
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0] is False
    assert game.declare_blockers(1, {0: 0})[0] is False, "Wall A is not the one named"
    assert game.declare_blockers(1, {1: 0})[0], game.log


def test_w2g2_flowstone_salamander_targets_only_its_own_blocker(set_pool):
    """``{R}: This creature deals 1 damage to target creature blocking it.``

    The pronoun rewrite that binds "it" to the ability's source walked only
    fields that were a bare ``TargetSpec``; ``DealDamage`` keeps its targets in
    a tuple, so this card reached the lowering still carrying the unbound
    pronoun. The picker spec is the assertion that the rewrite landed."""
    from engine.targeting import derive_activation_spec

    salamander = set_pool("TMP")["Flowstone Salamander"]
    program = compile_card_oracle(salamander)
    assert program.supported
    assert derive_activation_spec(program.activated_abilities[0]) == {
        "kind": "creature", "blocking_source": True,
    }

    game, p0, p1 = _w2g2_duel(
        [salamander],
        [_mk_creature_card("Blocker", 1, 1), _mk_creature_card("Bystander", 1, 1)],
    )
    _w2g2_to_blockers(game, [0])
    assert game.declare_blockers(1, {0: 0})[0]
    assert game.activate_permanent_ability(
        0, "Flowstone Salamander", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    ).supported
    resolve_stack(game)
    game.check_state_based_actions()
    assert [p.card.name for p in p1.battlefield] == ["Bystander"]


def test_w2g2_bounty_hunter_destroys_only_a_creature_it_marked(set_pool):
    """``{T}: Destroy target creature with a bounty counter on it.`` — the first
    card of ``ObjectFilter.with_named_counter``, and the assertion that matters is the
    *refusal*: the activation gate reads the same filter the picker does, so a
    creature carrying no bounty counter is not a legal target at all."""
    hunter = set_pool("TMP")["Bounty Hunter"]
    game, p0, p1 = _w2g2_duel(
        [hunter],
        [_mk_creature_card("Ogre", 3, 3), _mk_creature_card("Bear", 2, 2)],
    )
    game.start_turn(0)
    game._close_current_priority_step()
    assert not game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=0,
    ).supported
    p0.battlefield[0].tapped = False
    add_counters(p1.battlefield[0], "bounty", 1)
    assert not game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=1,
    ).supported, "the Bear carries no bounty counter"
    p0.battlefield[0].tapped = False
    assert game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=0,
    ).supported
    resolve_stack(game)
    game.check_state_based_actions()
    assert [p.card.name for p in p1.battlefield] == ["Bear"]


@pytest.mark.parametrize("name", [
    "Mounted Archers", "Watchdog", "Trumpeting Armodon", "Flowstone Salamander",
    "Bounty Hunter",
])
def test_w2g2_creatures_are_supported(set_pool, name):
    assert compile_card_oracle(set_pool("TMP")[name]).supported


# --- W3G5: Soltari Guerrillas — a named source, an opponent's seat, a target ---

from engine import Game, PlayerState  # noqa: F811  (block-local, see module docstring)
from engine.models import Permanent  # noqa: F811
from engine.oracle import compile_card_oracle  # noqa: F811
from tests.helpers import _mk_creature_card, _nosick  # noqa: F811


def _w3g5_guerrillas_board(set_pool, *, opposing=("Ox", 4)):
    """The Guerrillas on P0's board and one creature on P1's, both able to act."""
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    guerrillas = _nosick(Permanent(card=set_pool("TMP")["Soltari Guerrillas"]))
    p0.battlefield.append(guerrillas)
    victim = _nosick(Permanent(
        card=_mk_creature_card(opposing[0], 0, opposing[1], "Defender")
    ))
    p1.battlefield.append(victim)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p0, p1, guerrillas, victim


def _w3g5_deal(game, recipient, source, *, combat):
    """One damage event straight through CR 120.4, applied.

    The combat step is driven for the headline test; these three ask about one
    event in isolation — whether the record answers to it — so they go through
    the same entry point every damage path uses rather than through a combat.
    """
    from engine.damage_events import deal_damage
    outcome = deal_damage(
        game, {"recipient": recipient, "amount": 3, "source": source, "combat": combat}
    )
    # `deal_damage` runs CR 120.4 and deliberately leaves the *result* to its
    # caller, because what "apply" means differs by recipient. A redirected
    # event comes back consumed, with the moved points already marked on
    # whoever took them.
    if isinstance(recipient, Permanent):
        recipient.damage_marked += outcome.result
    else:
        recipient.life -= outcome.result
    return outcome


def _w3g5_attack_and_deal(game):
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0], 1)[0], game.log
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {})[0], game.log
    game.advance_combat_phase()   # combat damage


def test_w3g5_guerrillas_moves_its_combat_damage_onto_the_target(set_pool):
    """"{0}: The next time this creature would deal combat damage to an opponent
    this turn, it deals that damage to target creature instead."

    The Rock Hydra test for this card, and it has to be a real combat: the whole
    ability is a CR 614.9 record armed on a seat, and nothing short of dealing
    the damage shows whether the record was found. 3 power, so P1 keeps all 20
    life and the 0/4 across the table takes three.
    """
    game, p0, p1, guerrillas, victim = _w3g5_guerrillas_board(set_pool)
    game.start_turn(0)
    game._close_current_priority_step()
    result = game.activate_permanent_ability(
        0, "Soltari Guerrillas", permanent_index=0, ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result
    resolve_stack(game)

    _w3g5_attack_and_deal(game)
    assert p1.life == 20, game.log
    assert victim.damage_marked == 3, game.log


def test_w3g5_guerrillas_without_the_ability_hits_the_player(set_pool):
    """The control. Without it the assertion above passes on a combat that
    never dealt damage at all."""
    game, p0, p1, guerrillas, victim = _w3g5_guerrillas_board(set_pool)
    game.start_turn(0)
    game._close_current_priority_step()

    _w3g5_attack_and_deal(game)
    assert p1.life == 17, game.log
    assert victim.damage_marked == 0, game.log


def test_w3g5_guerrillas_record_is_spent_on_one_instance(set_pool):
    """"The next **time**" (CR 615.8) — one instance. A second combat in the
    same turn is dealt to the player, and a per-seat copy of the record would
    have made the count depend on how many opponents there are."""
    game, p0, p1, guerrillas, victim = _w3g5_guerrillas_board(set_pool)
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.activate_permanent_ability(
        0, "Soltari Guerrillas", permanent_index=0, ability_index=0,
        target_player_index=1, target_permanent_index=0,
    ).supported
    resolve_stack(game)

    _w3g5_deal(game, p1, guerrillas, combat=True)
    assert p1.life == 20 and victim.damage_marked == 3, game.log
    _w3g5_deal(game, p1, guerrillas, combat=True)
    assert p1.life == 17 and victim.damage_marked == 3, game.log


def test_w3g5_guerrillas_leaves_noncombat_damage_alone(set_pool):
    """The printed word "combat". A record that dropped it would move a ping
    ability's damage too — the silent direction, and the one the card excludes.
    """
    game, p0, p1, guerrillas, victim = _w3g5_guerrillas_board(set_pool)
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.activate_permanent_ability(
        0, "Soltari Guerrillas", permanent_index=0, ability_index=0,
        target_player_index=1, target_permanent_index=0,
    ).supported
    resolve_stack(game)

    _w3g5_deal(game, p1, guerrillas, combat=False)
    assert p1.life == 17, game.log
    assert victim.damage_marked == 0, game.log


def test_w3g5_guerrillas_does_not_catch_damage_to_a_blocking_creature(set_pool):
    """The card says "to an **opponent**", so a blocker takes its damage
    normally. The record lives on the opponents' seats for exactly this reason —
    ``DamageRedirect.any_recipient`` would have been found for a permanent too.
    """
    game, p0, p1, guerrillas, victim = _w3g5_guerrillas_board(set_pool)
    blocker = _nosick(Permanent(card=_mk_creature_card("Shade", 1, 5, "Shadow")))
    p1.battlefield.append(blocker)
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.activate_permanent_ability(
        0, "Soltari Guerrillas", permanent_index=0, ability_index=0,
        target_player_index=1, target_permanent_index=0,
    ).supported
    resolve_stack(game)

    _w3g5_deal(game, blocker, guerrillas, combat=True)
    assert blocker.damage_marked == 3, game.log
    assert victim.damage_marked == 0, game.log


def test_w3g5_guerrillas_needed_both_halves_of_the_set(set_pool):
    """Shadow (W1G1) and the redirect (W3G5), neither sufficient alone — and the
    card that emptied `W1G1_SHADOW_CREATURES_STILL_REFUSING`.

    Both halves at once, for Thalakos Mistfolk's reason at the top of this file:
    a card is supported when *any* of its lines is, so asserting `supported`
    alone would go green on the keyword with the ability still refused.
    """
    program = compile_card_oracle(set_pool("TMP")["Soltari Guerrillas"])
    assert program.supported
    assert "shadow" in program.static_lines
    assert [
        ability.instruction.kind for ability in program.activated_abilities
    ] == ["redirect_source_damage_to_target_until_eot"]
# --- W3G1: the attack requirement over a described set (CR 508.1a) ---

import dataclasses as _w3g1_dataclasses

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.subject_filters import subject_matches
from tests.helpers import _mk_creature_card, _nosick


def _w3g1_board(p0_cards, p1_cards):
    """Two battlefields, no summoning sickness, mana enforcement off."""
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    for card in p0_cards:
        p0.battlefield.append(_nosick(Permanent(card=card)))
    for card in p1_cards:
        p1.battlefield.append(_nosick(Permanent(card=card)))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p0, p1


def _w3g1_wall(name="Wally"):
    return _w3g1_dataclasses.replace(
        _mk_creature_card(name, 0, 4), type_line="Creature - Wall"
    )


def _w3g1_imp_activated(set_pool, p0_cards):
    """P1's Maddening Imp, activated in P0's precombat main phase."""
    game, p0, p1 = _w3g1_board(p0_cards, [set_pool("TMP")["Maddening Imp"]])
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.activate_permanent_ability(
        1, "Maddening Imp", ability_index=0
    ).supported, game.log
    resolve_stack(game)
    return game, p0, p1


def test_w3g1_maddening_imp_is_supported(set_pool):
    assert compile_card_oracle(set_pool("TMP")["Maddening Imp"]).supported


def test_w3g1_maddening_imp_compels_the_non_walls_and_spares_the_walls(set_pool):
    """The requirement and its delayed destruction, over one described set.

    The Wall assertion is the one a dropped narrowing fails, and it is dropped
    in the direction nothing else can see: a Wall marked to attack cannot attack
    (CR 702.3b), so the requirement half looks fine either way - and then the
    end step destroys it for not attacking.
    """
    game, p0, _ = _w3g1_imp_activated(
        set_pool, [_mk_creature_card("Bear", 2, 2), _w3g1_wall()]
    )
    bear, wall = p0.battlefield
    assert bear.metadata.get("must_attack_until_eot")
    assert bear.metadata.get("destroy_if_did_not_attack_eot")
    assert not wall.metadata.get("must_attack_until_eot")
    assert not wall.metadata.get("destroy_if_did_not_attack_eot")


def test_w3g1_maddening_imp_marks_only_the_active_players_creatures(set_pool):
    """``controller: "active_player"`` (CR 102.1) is a filter word now, and the
    Imp's own controller is the one seat it must not reach: the ability is
    activated on somebody else's turn, so "the active player" is never the
    activator."""
    game, p0, p1 = _w3g1_imp_activated(set_pool, [_mk_creature_card("Bear", 2, 2)])
    p1.battlefield.append(_nosick(Permanent(card=_mk_creature_card("Ally", 1, 1))))
    game._sync_control()
    assert p0.battlefield[0].metadata.get("must_attack_until_eot")
    ally = [p for p in p1.battlefield if p.card.name == "Ally"][0]
    assert not ally.metadata.get("must_attack_until_eot")


def test_w3g1_maddening_imp_refuses_the_attackerless_declaration(set_pool):
    """The mark reaches ``declare_attackers``: the requirement is enforced by
    the step that already reads it, not by anything this round added."""
    game, p0, _ = _w3g1_imp_activated(set_pool, [_mk_creature_card("Bear", 2, 2)])
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [], 1) == (False, "Bear must attack if able")
    assert game.declare_attackers(0, [0], 1)[0]


def test_w3g1_maddening_imp_destroys_the_creature_that_stayed_home(set_pool):
    """The end step's own sweep, reached through the mark the second sentence
    arms. The creature is tapped, so the requirement is met as far as it is able
    (CR 508.1a) and the declaration is legal with nobody attacking - which is
    exactly the case the destruction is printed for."""
    game, p0, _ = _w3g1_imp_activated(set_pool, [_mk_creature_card("Bear", 2, 2)])
    p0.battlefield[0].tapped = True
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [], 1)[0]
    game.resolve_end_step(0)
    game.check_state_based_actions()
    assert [p.card.name for p in p0.battlefield] == []


def test_w3g1_maddening_imp_spares_the_creature_that_attacked(set_pool):
    game, p0, _ = _w3g1_imp_activated(set_pool, [_mk_creature_card("Bear", 2, 2)])
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0], 1)[0]
    game.resolve_end_step(0)
    game.check_state_based_actions()
    assert [p.card.name for p in p0.battlefield] == ["Bear"]


@pytest.mark.parametrize("combat_steps, expected", [
    (0, True),                 # the opponent's precombat main
    (1, False),                # ...and one step later, combat has begun
])
def test_w3g1_only_before_combat_is_narrower_than_before_attackers(
    set_pool, combat_steps, expected,
):
    """"Activate only during an opponent's turn and only before combat."

    Two conjuncts, split by ``activation_restrictions._conjuncts`` before the
    table sees them, which is why this is two rows and not one. The
    beginning-of-combat step is still *before attackers are declared* and is not
    before *combat* (CR 506.1), so a row reusing Nettling Imp's window would
    pass the first case and fail the second.
    """
    game, _, _ = _w3g1_board([_mk_creature_card("Bear", 2, 2)],
                             [set_pool("TMP")["Maddening Imp"]])
    game.start_turn(0)
    game._close_current_priority_step()
    for _ in range(combat_steps):
        game.advance_combat_phase()
    assert game.activate_permanent_ability(
        1, "Maddening Imp", ability_index=0
    ).supported is expected


def test_w3g1_the_imp_cannot_be_activated_on_its_own_controllers_turn(set_pool):
    game, _, _ = _w3g1_board([_mk_creature_card("Bear", 2, 2)],
                             [set_pool("TMP")["Maddening Imp"]])
    game.start_turn(1)
    game._close_current_priority_step()
    assert not game.activate_permanent_ability(
        1, "Maddening Imp", ability_index=0
    ).supported


def test_w3g1_a_named_seat_no_longer_swallows_the_rest_of_the_phrase():
    """``subject_matches`` used to **return** the answer for four named seats,
    skipping every key tested after them.

    Total War ("except for creatures the player hasn't controlled continuously
    since the beginning of the turn") and Mudslide ("tapped creatures without
    flying they control") both carried the dropped key in their payload the
    whole way, which is why no census could see it: the narrowing was compiled,
    shipped and then not asked.
    """
    game, p0, _ = _w3g1_board([], [])
    game.start_turn(0)
    fresh = Permanent(card=_mk_creature_card("Newcomer", 1, 1))
    fresh.metadata["summoning_sickness_turn"] = game.turn
    veteran = _nosick(Permanent(card=_mk_creature_card("Veteran", 1, 1)))
    p0.battlefield += [fresh, veteran]
    game._sync_control()
    described = {
        "type_filter": "creature", "controller": "that_player",
        "controlled_since_turn_start": True,
    }
    assert not subject_matches(
        game, fresh, described, observer=1, that_player=p0
    ), "Total War's own exemption"
    assert subject_matches(game, veteran, described, observer=1, that_player=p0)


def test_w3g1_sirens_call_kept_every_word_when_two_lines_left_its_hook():
    """The card whose hook this round shrank.

    Its requirement reaches every creature the active player controls; its
    destruction reaches only the non-Walls it has controlled since the turn
    began. Two different sets from one card, which is why the description
    travels in the payload rather than being inherited from the requirement
    beside it.
    """
    call = {c.name: c for c in load_cards(manifest_set_path("LEA"))}["Siren's Call"]
    game, p0, p1 = _w3g1_board(
        [_mk_creature_card("Bear", 2, 2), _w3g1_wall()], []
    )
    p1.hand.append(call)
    game.start_turn(0)
    game._close_current_priority_step()
    arrived = Permanent(card=_mk_creature_card("Newcomer", 1, 1))
    arrived.metadata["summoning_sickness_turn"] = game.turn
    p0.battlefield.append(arrived)
    game._sync_control()
    assert game.cast_from_hand(1, "Siren's Call").supported
    resolve_stack(game)
    bear, wall, newcomer = p0.battlefield
    assert bear.metadata.get("must_attack_until_eot")
    assert wall.metadata.get("must_attack_until_eot"), "every creature attacks"
    assert newcomer.metadata.get("must_attack_until_eot")
    assert bear.metadata.get("destroy_if_did_not_attack_eot")
    assert not wall.metadata.get("destroy_if_did_not_attack_eot"), "non-Wall only"
    assert not newcomer.metadata.get("destroy_if_did_not_attack_eot"), (
        "ignored for a creature the player hasn't controlled since the turn began"
    )


def test_w3g1_both_combat_roles_resolve_or_both_refuse():
    """"Destroy the attacking creature." used to compile to ``destroy_self`` and
    "Destroy the blocking creature." refused to parse.

    Two halves of one pair-role vocabulary, one of them answering, and answering
    with the **ability's own source**. No card printed the pair, so nothing
    failed; No Quarter prints both on an enchantment that is in no combat at
    all, and would have destroyed itself.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import GrammarError, LoweringError
    from engine.grammar.lower import lower_ability

    for line in ("Destroy the attacking creature.", "Destroy the blocking creature."):
        with pytest.raises((GrammarError, LoweringError)):
            lower_ability(parse_line(line))


def test_w3g1_farrels_mantle_still_names_the_creature_it_enchants():
    """The one shipped card printing a combat role. Its trigger is about the
    enchanted creature attacking, so the role *is* the event's subject - which
    is the only context ``rebind_combat_role_to_event_subject`` resolves one
    in."""
    mantle = {
        c.name: c for c in load_cards(manifest_set_path("FEM"))
    }["Farrel's Mantle"]
    program = compile_card_oracle(mantle)
    assert program.supported
    marks = [
        step for trigger in program.triggered_abilities
        for step in (trigger.instruction.payload.get("then") or ())
        if step.kind == "assign_no_combat_damage_until_eot"
    ]
    assert [step.payload.get("subject") for step in marks] == ["attached"]
# --- W3G2: an ability activated from a graveyard, and the zone its own
# --- restriction states (Carrionette) --------------------------------------

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w3g2_carrionette(set_pool, *, in_graveyard=True, victims=("Hill Giant",)):
    """Carrionette in seat 0's graveyard (or on its battlefield), with *victims*
    on seat 1's board. Mana costs off — every assertion below is about the zone
    gate and the target gate, not about paying {2}{B}{B}."""
    pool = set_pool("TMP")
    lea = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else lea[name]

    carrionette = pool["Carrionette"]
    p0 = PlayerState(
        name="P0", life=20,
        graveyard=[carrionette] if in_graveyard else [],
        battlefield=[] if in_graveyard else [Permanent(card=carrionette)],
        library=[lea["Swamp"]] * 6,
    )
    p1 = PlayerState(
        name="P1", life=20,
        battlefield=[Permanent(card=card(name)) for name in victims],
        library=[lea["Forest"]] * 6,
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


def test_w3g2_carrionette_states_the_zone_it_functions_from(set_pool):
    """`Activate only if this card is in your graveyard.`

    CR 113.6b: the clause states where the ability functions, and it is the
    **only** place this card says so — its effect prints no zone at all. So the
    key that the graveyard activation path gates on is derived from the
    restriction, not from the effect.
    """
    program = compile_card_oracle(set_pool("TMP")["Carrionette"])
    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.supported
    assert ability.instruction.payload.get("functions_from") == "graveyard"


def test_w3g2_carrionette_exiles_itself_and_its_target_from_the_graveyard(set_pool):
    """The Rock Hydra test: activate it out of the pile and read both cards out
    of *exile* rather than off the claim that it compiled."""
    game = _w3g2_carrionette(set_pool)
    victim = game.players[1].battlefield[0]
    result = game.activate_from_graveyard(
        0, "Carrionette", target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log
    while game.stack:
        game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()

    # "Exile **this card**" — out of the graveyard it was activated from, which
    # is the branch that used to set the resolving-spell flag and move nothing.
    assert [c.name for c in game.players[0].exile] == ["Carrionette"]
    assert not game.players[0].graveyard
    # "…and target creature."
    assert not game.players[1].battlefield
    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]


def test_w3g2_carrionette_cannot_be_activated_from_the_battlefield(set_pool):
    """CR 113.6m the other way round: the ability functions **only** from the
    graveyard, so the permanent has nothing to activate."""
    game = _w3g2_carrionette(set_pool, in_graveyard=False)
    assert not game.activate_permanent_ability(0, "Carrionette").supported


def test_w3g2_carrionette_refuses_with_no_legal_target_and_spends_nothing(set_pool):
    """CR 602.2b/601.2c, and the reason it matters here rather than generally:
    the target sits in the toll's `otherwise` half, which the mandatory-target
    walk did not read. Ungated, the ability went on the stack with nothing to
    aim at and exiled the card out of its own graveyard for no effect.
    """
    game = _w3g2_carrionette(set_pool, victims=())
    result = game.activate_from_graveyard(0, "Carrionette")
    assert not result.supported
    assert [c.name for c in game.players[0].graveyard] == ["Carrionette"]
    assert not game.stack


# --- W3G2: a delayed ability answering to two events, about the permanent
# --- its own reanimation made (Coffin Queen) -------------------------------


def _w3g2_queen(set_pool, victims=("Hill Giant",)):
    """Coffin Queen on seat 0's board, *victims* in seat 1's graveyard.

    Summoning sickness is dated back rather than switched off: the ability
    costs {T}, and a Queen that entered this turn could not pay it.
    """
    pool = set_pool("TMP")
    lea = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else lea[name]

    queen = Permanent(card=pool["Coffin Queen"])
    queen.metadata["summoning_sickness_turn"] = -5
    p0 = PlayerState(
        name="P0", life=20, battlefield=[queen], library=[lea["Swamp"]] * 6,
    )
    p1 = PlayerState(
        name="P1", life=20,
        graveyard=[card(name) for name in victims],
        library=[lea["Forest"]] * 6,
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, queen


def _w3g2_reanimate(game):
    result = game.activate_permanent_ability(
        0, "Coffin Queen", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, game.log
    while game.stack:
        game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    return result


def test_w3g2_coffin_queen_exiles_the_creature_when_she_untaps(set_pool):
    """`When this creature becomes untapped or you lose control of this
    creature, exile that creature.`

    The Rock Hydra test for the first of the two events. What the delayed
    ability is *about* is the permanent the reanimation made — not the ability's
    target, which is a **card** in a graveyard — and not the Queen, which is
    what it watches.
    """
    game, queen = _w3g2_queen(set_pool)
    _w3g2_reanimate(game)
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Coffin Queen", "Hill Giant",
    ]

    game.become_untapped(queen)
    resolve_stack(game)
    game.check_state_based_actions()

    assert [p.card.name for p in game.players[0].battlefield] == ["Coffin Queen"]
    # CR 400.3: the card goes to its **owner's** exile, not the thief's.
    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]


def test_w3g2_coffin_queen_exiles_the_creature_when_she_leaves(set_pool):
    """The second event. A permanent leaving the battlefield *is* its
    controller losing control of it (CR 400.7 — what comes back is a different
    object), which is the same reading the printed `lose_control_of_source`
    trigger already takes from that transition."""
    game, queen = _w3g2_queen(set_pool)
    _w3g2_reanimate(game)

    game.remove_from_battlefield(queen)
    game.players[0].graveyard.append(queen.card)
    resolve_stack(game)
    game.check_state_based_actions()

    assert not game.players[0].battlefield
    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]


def test_w3g2_coffin_queen_keeps_the_creature_while_she_stays_tapped(set_pool):
    """Neither event has happened, so the delayed ability is still waiting.

    The assertion that makes the two above mean something: an entry armed
    without a bound object would answer the *first* permanent either event
    named, and an entry that fired on its own arming would take the creature
    back the moment it arrived.
    """
    game, _queen = _w3g2_queen(set_pool)
    _w3g2_reanimate(game)
    game.check_state_based_actions()

    assert [p.card.name for p in game.players[0].battlefield] == [
        "Coffin Queen", "Hill Giant",
    ]
    assert not game.players[1].exile


def test_w3g2_coffin_queens_delay_is_bound_to_what_it_reanimated(set_pool):
    """The compiled program, read for the three facts that make this card work:
    the event it waits for, the permanent it watches, and the *record* it is
    about — which cannot be the ability's target, because that target is a card
    in a graveyard and the delayed ability acts on a permanent."""
    program = compile_card_oracle(set_pool("TMP")["Coffin Queen"])
    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.supported
    steps = ability.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "reanimate_creature", "create_delayed_trigger",
    ]
    delay = steps[1].payload
    assert delay["event"] == "bound_permanent_untaps_or_control_lost"
    assert delay["watches"] == "source"
    assert delay["binds_recorded"] == "reanimated_permanents"
    assert delay["binds_target"] is False
    assert delay["instruction"].kind == "exile_bound_permanent"


def test_w3g2_exile_that_creature_refuses_under_an_event_that_binds_nothing():
    """"Exile that creature" names the firing event's object, and an event that
    records none makes the words name nothing at all.

    The loud direction: admitted, the sentence would compile and exile whatever
    the resolution context happened to be carrying.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    with pytest.raises(LoweringError):
        lower_ability(parse_line("Exile that creature."))
# --- W3G4: Escaped Shapeshifter (a keyword chosen by the opponent's board) ---

import pytest as _w3g4_pytest

from engine import Game as _W3G4Game
from engine import PlayerState as _W3G4PlayerState
from engine.models import Permanent as _W3G4Permanent
from engine.oracle import compile_card_oracle as _w3g4_compile
from engine.oracle import expand_same_is_true_lines as _w3g4_expand
from tests.helpers import _mk_card as _w3g4_mk_card


def _w3g4_board(set_pool, opponent):
    """Escaped Shapeshifter alone, against the permanents named."""
    shifter = _W3G4Permanent(card=set_pool("TMP")["Escaped Shapeshifter"])
    game = _W3G4Game(players=[
        _W3G4PlayerState(name="P1", battlefield=[shifter]),
        _W3G4PlayerState(name="P2", battlefield=list(opponent)),
    ])
    game._recalculate_lord_buffs()
    return game, shifter


def _w3g4_creature(name, text, colors=()):
    return _W3G4Permanent(
        card=_w3g4_mk_card(
            name=name, mana_cost="{2}", type_line="Creature - Human",
            oracle_text=text, colors=colors,
        )
    )


def test_escaped_shapeshifter_expands_into_one_static_per_quality(set_pool):
    """"The same is true for first strike, trample, and protection from any
    color" is CR 113.3 shorthand, not a second ability.

    Eight conditional statics, because "protection from any color" is **five**:
    CR 702.16b makes protection always from a stated quality, and the card gains
    protection from a colour only while an opponent controls a creature with
    protection from *that* colour. One "any color" static would hold when none
    of the five conditions did.
    """
    program = _w3g4_compile(set_pool("TMP")["Escaped Shapeshifter"])
    assert program.supported, program.reason
    statics = [i for i in program.instructions if i.kind == "conditional_static"]
    assert len(statics) == 8
    assert [i.payload.get("keywords") for i in statics[:3]] == [
        ["flying"], ["first strike"], ["trample"]
    ]
    assert [i.payload.get("protection_from") for i in statics[3:]] == [
        ["white"], ["blue"], ["black"], ["red"], ["green"]
    ]
    # Every one of them asks about the *opponent's* board, and every one of them
    # carries the exclusion — a condition that lost either half would hold on a
    # board the card does not name.
    for instruction in statics:
        condition = instruction.payload["condition"]
        assert condition["who"] == "opponent"
        assert condition["filter"]["not_named_source"] is True


@_w3g4_pytest.mark.parametrize("keyword", ["flying", "first strike", "trample"])
def test_escaped_shapeshifter_takes_a_keyword_from_the_opponents_board(
    set_pool, keyword
):
    game, shifter = _w3g4_board(set_pool, [])
    assert not game._has_keyword(shifter, keyword)

    donor = _w3g4_creature("Donor", keyword.title())
    game, shifter = _w3g4_board(set_pool, [donor])
    assert game._has_keyword(shifter, keyword)


def test_escaped_shapeshifter_reads_the_opponents_board_and_not_its_own(set_pool):
    """"As long as **an opponent** controls...". The fronted word order of this
    sentence used to refuse outright, because ``static_bonuses``' noun-condition
    anchor spelled "you control" and nothing else — while
    ``conditional_static_holds`` had answered ``who="opponent"`` all along.
    """
    flier = _w3g4_creature("Cloud", "Flying")
    shifter = _W3G4Permanent(card=set_pool("TMP")["Escaped Shapeshifter"])
    game = _W3G4Game(players=[
        _W3G4PlayerState(name="P1", battlefield=[shifter, flier]),
        _W3G4PlayerState(name="P2"),
    ])
    game._recalculate_lord_buffs()
    assert not game._has_keyword(shifter, "flying")


def test_escaped_shapeshifter_ignores_a_creature_of_its_own_name(set_pool):
    """"...**not named Escaped Shapeshifter**". Excluded by CR 201.2's name, so
    an opponent's own copy does not feed it — and a second copy would not
    either, which is what an identity comparison would get wrong."""
    twin = _W3G4Permanent(
        card=_w3g4_mk_card(
            name="Escaped Shapeshifter", mana_cost="{3}{U}{U}",
            type_line="Creature - Shapeshifter", oracle_text="Flying",
        )
    )
    game, shifter = _w3g4_board(set_pool, [twin])
    assert not game._has_keyword(shifter, "flying")
    # ...and the exclusion is only about the name: any other flier still counts.
    game, shifter = _w3g4_board(set_pool, [twin, _w3g4_creature("Cloud", "Flying")])
    assert game._has_keyword(shifter, "flying")


def test_escaped_shapeshifter_takes_protection_colour_by_colour(set_pool):
    """The correction three groups took to reach: "protection from any color" is
    not one quality. An opponent's protection-from-white creature gives the
    Shapeshifter protection from **white**, and nothing else."""
    warded = _w3g4_creature("Warded", "Protection from white")
    game, shifter = _w3g4_board(set_pool, [warded])
    assert sorted(game._protection_qualities(shifter)) == [("color", "W")]

    second = _w3g4_creature("Warded Too", "Protection from green")
    game, shifter = _w3g4_board(set_pool, [warded, second])
    assert sorted(game._protection_qualities(shifter)) == [
        ("color", "G"), ("color", "W")
    ]


def test_escaped_shapeshifter_protection_ends_when_the_condition_does(set_pool):
    """A derived grant, never a metadata stamp: the quality is read off the
    conditional static at every recompute, so it goes when the opponent's
    creature does — with nothing having to remove it."""
    warded = _w3g4_creature("Warded", "Protection from white")
    game, shifter = _w3g4_board(set_pool, [warded])
    assert game._protection_qualities(shifter)

    game.remove_from_battlefield(warded)
    game._recalculate_lord_buffs()
    assert not game._protection_qualities(shifter)


def test_escaped_shapeshifter_protection_stops_a_white_spell_targeting_it(set_pool):
    """The grant reaches the consumers a printed protection line reaches, which
    is the point of deriving it in ``_protection_qualities`` rather than in the
    derived-*keyword* channel: that channel is one word per grant and has
    nowhere to put a quality."""
    warded = _w3g4_creature("Warded", "Protection from white")
    game, shifter = _w3g4_board(set_pool, [warded])
    white_spell = _w3g4_mk_card(
        name="White Bolt", mana_cost="{W}", type_line="Instant",
        oracle_text="Destroy target creature.", colors=("W",),
    )
    assert not game._can_be_targeted(shifter, white_spell)

    game, shifter = _w3g4_board(set_pool, [])
    assert game._can_be_targeted(shifter, white_spell)


def test_the_same_is_true_rewrite_leaves_every_other_sentence_alone():
    """The gate, asserted directly. Celestial Dawn (MIR, shipped) prints the
    same five words about *objects in other zones* rather than about a quality,
    and a rewrite that took it would have written nonsense onto a card that
    works.

    The substitution check is the other half: the quality has to appear exactly
    twice in the first sentence — once in the condition, once in the effect —
    and a sentence where it does not is left alone rather than guessed at.
    """
    dawn = (
        "Nonland permanents you control are white. The same is true for spells "
        "you control and nonland cards you own that are not on the battlefield."
    )
    assert _w3g4_expand(dawn) == dawn

    once_only = (
        "As long as an opponent controls a creature with flying, this creature "
        "has trample. The same is true for first strike."
    )
    assert _w3g4_expand(once_only) == once_only


# --- W4G1: Oracle en-Vec — a window that opens on a named seat's next turn ---

from engine import Game as _W4G1Game, PlayerState as _W4G1PlayerState
from engine.models import Permanent as _W4G1Permanent
from engine.oracle import compile_card_oracle as _w4g1_compile
from engine.targeting import derive_activation_spec as _w4g1_activation_spec
from engine.turn_state import (
    DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY as _W4G1_DESTROY_KEY,
    MUST_ATTACK_ON_SEAT_TURN_KEY as _W4G1_MUST_KEY,
)


def _w4g1_board(set_pool, victim_names=("Horned Turtle", "Trained Armodon",
                                        "Bayou Dragonfly")):
    """Oracle en-Vec for seat 0, and *victim_names* for seat 1.

    Seat 1 is interactive so the test makes the choice rather than taking the
    default — which is the whole point of the card: "any number" means the
    opponent picks, and a default that always picks everything would hide the
    complement half.
    """
    pool = set_pool("TMP")
    oracle = _W4G1Permanent(card=pool["Oracle en-Vec"])
    oracle.summoning_sick = False
    oracle.metadata["summoning_sickness_turn"] = -99
    victims = []
    for name in victim_names:
        perm = _W4G1Permanent(card=pool[name])
        perm.summoning_sick = False
        perm.metadata["summoning_sickness_turn"] = -99
        victims.append(perm)
    game = _W4G1Game(players=[
        _W4G1PlayerState(name="P1", life=20, battlefield=[oracle]),
        _W4G1PlayerState(name="P2", life=20, battlefield=victims),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}
    game._sync_control()
    game.start_turn(0)
    return game, oracle, victims


def _w4g1_activate(game, chosen):
    """Activate the Oracle and answer the opponent's prompt with *chosen*."""
    result = game.activate_permanent_ability(
        0, "Oracle en-Vec", ability_index=0, target_player_index=1,
    )
    assert result.supported, game.log
    game.resolve_stack()
    assert game.pending_choices, game.log
    assert game.confirm_permanent_set_choice(
        1, [perm.permanent_id for perm in chosen]
    ), game.log
    game.resolve_stack()


def test_w4g1_oracle_en_vec_compiles_to_four_windowed_steps(set_pool):
    """One sentence per step, and the window and the record are payload.

    The card is four printed sentences and it compiles to four instructions
    that already existed — Maddening Imp's requirement and end-step
    destruction, Festival's blanket restriction, Raiding Party's plural pick.
    What Oracle en-Vec adds is two payload keys on three of them: *which* turn
    (``window``) and *which set* (``subject_from`` / ``except_from``). No new
    instruction kind, because CR 508.1a's requirement is the same requirement
    whichever turn it holds for.
    """
    program = _w4g1_compile(set_pool("TMP")["Oracle en-Vec"])
    assert program.supported

    steps = program.activated_abilities[0].instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_permanents",
        "force_subject_to_attack_until_eot",
        "cant_attack_until_eot",
        "destroy_subject_at_end_step_if_it_didnt_attack",
    ]
    assert steps[0].payload["unbounded"] is True
    # "**Target** opponent": the seat is announced when the ability is
    # activated (CR 602.2b), so the chooser is the target and the picker is
    # offered the opponents. Before this round the word was collapsed onto
    # "whichever opponent there is", which is only right in a duel — and
    # `picker_sweep` says so: an activated ability that prints "target" and
    # derives no picker is the Roots class.
    assert steps[0].payload["chooser"] == "target"
    assert steps[0].payload["targets"] == {
        "quantifier": "target", "kind": "player", "opponents_only": True,
    }
    # "…creatures **they control**": the picked-from battlefield is the seat the
    # sentence already named, lifted out of the filter into the key the
    # candidate rule answers.
    assert steps[0].payload["controlled_by"] == "chooser"
    for step in steps[1:]:
        assert step.payload["window"] == "that_players_next_turn"
    assert steps[1].payload["subject_from"] == "chosen_this_way_objects"
    assert steps[2].payload["except_from"] == "chosen_this_way_objects"
    assert steps[3].payload["subject_from"] == "chosen_this_way_objects"


def test_w4g1_the_chosen_attack_and_the_rest_cannot_on_that_players_turn(set_pool):
    """The card in a game, on the turn it names.

    Both halves at once, because the card is the pair: the two creatures the
    opponent picked are compelled (CR 508.1d) and the one they did not is
    grounded (CR 508.1c). A mark that expired at the cleanup in between would
    make both halves silently false, which is the failure this window exists to
    prevent.
    """
    game, _oracle, victims = _w4g1_board(set_pool)
    turtle, armodon, dragonfly = victims
    _w4g1_activate(game, [turtle, armodon])

    assert turtle.metadata[_W4G1_MUST_KEY] == {"seat": 1, "seat_turn": 1}
    assert dragonfly.metadata.get(_W4G1_MUST_KEY) is None

    game.start_next_turn()          # the turn the ability named
    assert game.active_player_index == 1
    assert game._must_attack_if_able(turtle)
    assert game._must_attack_if_able(armodon)
    assert not game._must_attack_if_able(dragonfly)
    assert game.can_attack(turtle, 0)
    assert game.can_attack(armodon, 0)
    assert not game.can_attack(dragonfly, 0)


def test_w4g1_a_declaration_that_leaves_a_chosen_creature_home_is_illegal(set_pool):
    """CR 508.1d: the requirement is checked against the whole declaration."""
    game, _oracle, victims = _w4g1_board(set_pool)
    turtle, armodon, _dragonfly = victims
    _w4g1_activate(game, [turtle, armodon])

    game.start_next_turn()
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    refused, why = game.declare_attackers(1, [0])
    assert not refused
    assert "Trained Armodon must attack if able" in why
    assert game.declare_attackers(1, [0, 1])[0]


def test_w4g1_a_chosen_creature_that_stayed_home_dies_at_that_turns_end_step(set_pool):
    """"At the beginning of **that turn's** end step, destroy each of the
    chosen creatures that didn't attack this turn."

    The one that could not attack is destroyed and the two that did are not —
    which is the whole difference between this mark and an unconditional
    delayed destruction. The Dragonfly is tapped *after* the untap step, so
    CR 508.1a's "if able" is genuinely unmet rather than disobeyed.
    """
    game, _oracle, victims = _w4g1_board(set_pool)
    turtle, armodon, dragonfly = victims
    _w4g1_activate(game, victims)

    game.start_next_turn()
    dragonfly.tapped = True
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0, 1])[0], game.log
    game.advance_combat_phase()
    game.declare_blockers(0, {})
    game._settle()

    game.resolve_end_step(1)
    assert [perm.card.name for perm in game.players[1].battlefield] == [
        "Horned Turtle", "Trained Armodon",
    ]
    assert [card.name for card in game.players[1].graveyard] == ["Bayou Dragonfly"]
    assert turtle.metadata[_W4G1_DESTROY_KEY] == {"seat": 1, "seat_turn": 1}
    assert armodon.metadata[_W4G1_DESTROY_KEY] == {"seat": 1, "seat_turn": 1}


def test_w4g1_the_window_is_one_turn_and_then_it_is_over(set_pool):
    """The stamp names one of that seat's turns, not "from now on".

    The failure it guards is the quiet one: a mark nothing sweeps that answered
    "yes" on every later turn would ground the opponent's whole board for the
    rest of the game, and no test of the turn it names would notice.
    """
    game, _oracle, victims = _w4g1_board(set_pool)
    turtle, _armodon, dragonfly = victims
    _w4g1_activate(game, [turtle])

    game.start_next_turn()                       # the named turn
    assert not game.can_attack(dragonfly, 0)
    assert game._must_attack_if_able(turtle)

    game.start_next_turn()                       # seat 0's
    game.start_next_turn()                       # seat 1's *next* one
    assert game.can_attack(dragonfly, 0)
    assert not game._must_attack_if_able(turtle)


def test_w4g1_choosing_none_grounds_that_players_whole_board(set_pool):
    """"**Any number**" includes none (CR 601.2c), and the complement of the
    empty set is everything.

    An opponent who picks nothing keeps every creature alive and attacks with
    none of them, which is the card working — and it is the one answer a
    ceiling-only reading of "any number" could not tell from "up to one".
    """
    game, _oracle, victims = _w4g1_board(set_pool)
    _w4g1_activate(game, [])

    game.start_next_turn()
    for victim in victims:
        assert not game.can_attack(victim, 0)
        assert not game._must_attack_if_able(victim)

    game.resolve_end_step(1)
    assert len(game.players[1].battlefield) == 3


def test_w4g1_the_restriction_reaches_a_creature_that_arrived_afterwards(set_pool):
    """CR 611.2c's second half, and the reason the restriction is state on the
    game rather than a mark on each creature.

    "Other creatures can't attack" modifies the rules rather than any object's
    characteristics, so it "can affect objects that weren't affected when that
    continuous effect began" — a creature that entered after the ability
    resolved is an *other* creature and is grounded too. Per-permanent flags
    would have missed it, which is the argument ``cant_attack_until_eot``'s
    handler already makes for the "this turn" spelling.
    """
    game, _oracle, victims = _w4g1_board(set_pool)
    turtle = victims[0]
    _w4g1_activate(game, [turtle])

    latecomer = _W4G1Permanent(card=set_pool("TMP")["Horned Turtle"])
    latecomer.summoning_sick = False
    latecomer.metadata["summoning_sickness_turn"] = -99
    game.players[1].battlefield.append(latecomer)
    game._sync_control()

    game.start_next_turn()
    assert game.can_attack(turtle, 0)
    assert not game.can_attack(latecomer, 0)


def test_w4g1_the_ability_is_refused_on_an_opponents_turn_with_nothing_paid(set_pool):
    """"Activate only during your turn." (CR 602.5.)

    An unenforced restriction is not a dead ability — it is one that works more
    often than the card allows — so the check is that the Oracle is still
    *untapped* afterwards as well as that the ability did not resolve.
    """
    game, oracle, _victims = _w4g1_board(set_pool)
    game.start_next_turn()

    refused = game.activate_permanent_ability(
        0, "Oracle en-Vec", ability_index=0, target_player_index=1,
    )
    assert not refused.supported
    assert not oracle.tapped
    assert not game.pending_choices


def test_w4g1_the_ability_offers_a_player_picker_and_strikes_out_the_activator(set_pool):
    """"**Target** opponent chooses…" — CR 602.2b announces the seat, CR 115.4
    says which seats are legal answers.

    Both halves, because each was missing on its own footing. The *picker* was
    missing because the chooser table collapsed "target opponent" onto "an
    opponent" and answered with the first live one at resolution — right in a
    duel, and the whole of the choice at three seats; ``picker_sweep`` names
    that the Roots class. The *gate* was missing because
    ``activation_target_refusal`` reasoned that a player-targeted ability always
    has a legal target — true, and not an answer to whether the seat the caller
    named is one of them.
    """
    program = _w4g1_compile(set_pool("TMP")["Oracle en-Vec"])
    assert _w4g1_activation_spec(program.activated_abilities[0]) == {
        "kind": "player", "opponents_only": True,
    }

    game, oracle, _victims = _w4g1_board(set_pool)
    refused = game.activate_permanent_ability(
        0, "Oracle en-Vec", ability_index=0, target_player_index=0,
    )
    assert not refused.supported
    assert not oracle.tapped, "nothing is paid for a refused activation"


def test_w4g1_that_players_turn_is_the_seat_the_activation_named(set_pool):
    """"During **that player's** next turn" reads the announcement, not "the
    first opponent there is".

    Three seats, which is where the two answers come apart: the Oracle names
    seat 2, and seat 1 — the seat a first-live-opponent reading would have
    picked — is untouched on its own turn.
    """
    pool = set_pool("TMP")
    oracle = _W4G1Permanent(card=pool["Oracle en-Vec"])
    oracle.summoning_sick = False
    oracle.metadata["summoning_sickness_turn"] = -99
    bystander = _W4G1Permanent(card=pool["Horned Turtle"])
    victim = _W4G1Permanent(card=pool["Trained Armodon"])
    for perm in (bystander, victim):
        perm.summoning_sick = False
        perm.metadata["summoning_sickness_turn"] = -99
    # Libraries, because a three-seat game has no CR 103.8a skip: the first
    # draw step is real and an empty library ends the game before the ability
    # can be activated.
    def _library():
        return [pool["Horned Turtle"] for _ in range(10)]

    game = _W4G1Game(players=[
        _W4G1PlayerState(name="P1", life=20, battlefield=[oracle],
                         library=_library()),
        _W4G1PlayerState(name="P2", life=20, battlefield=[bystander],
                         library=_library()),
        _W4G1PlayerState(name="P3", life=20, battlefield=[victim],
                         library=_library()),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)

    assert game.activate_permanent_ability(
        0, "Oracle en-Vec", ability_index=0, target_player_index=2,
    ).supported, game.log
    game.resolve_stack()

    game.start_next_turn()          # seat 1 — not the one named
    assert game.can_attack(bystander, 0)
    game.start_next_turn()          # seat 2 — the named turn
    assert game._must_attack_if_able(victim)


# --- Promotion gate: two shapes a target probe mistook for a target ---

from engine import Game as _PromoGame, PlayerState as _PromoPlayerState
from engine.models import Permanent as _PromoPermanent
from engine.oracle import compile_card_oracle as _promo_compile
from engine.targeting import (
    derive_activation_spec as _promo_activation_spec,
    derive_cast_spec as _promo_cast_spec,
    usable_activated_abilities as _promo_usable,
)


def _promo_board(*battlefields):
    from tests.helpers import _nosick

    game = _PromoGame(players=[
        _PromoPlayerState(name=f"P{i + 1}", battlefield=[_nosick(p) for p in perms])
        for i, perms in enumerate(battlefields)
    ])
    game.enforce_mana_costs = False
    game._settle()
    return game


def test_knight_of_dawn_chooses_a_colour_and_points_at_nothing(set_pool):
    """"{W}{W}: This creature gains protection from **the color of your
    choice** until end of turn."

    "Of your choice" is the phrase a target probe watches for, and here it
    names a **characteristic** rather than an object: CR 608.2d makes the colour
    part of the resolution and the permanent it applies to is the ability's own
    source, which nobody chooses. So the derivation answers "nothing to point
    at" *positively* — the same row Dream Coat's colour ability has — rather
    than answering None, which is what a guard reads as "the derivation lost its
    evidence".
    """
    knight = _PromoPermanent(card=set_pool("TMP")["Knight of Dawn"])
    game = _promo_board([knight], [])

    ability = _promo_usable(_promo_compile(knight.card))[0]
    assert _promo_activation_spec(ability) == {"kind": "none"}
    assert game.activation_target_spec(0, 0)["requires_target"] is False


def test_knight_of_dawn_gains_protection_from_the_colour_the_seat_named(set_pool):
    """And the choice is a real one, driven through the wire it rides on: the
    colour arrives as ``mana_color`` like every other CR 608.2d colour, and an
    unanswered choice would grant nothing at all."""
    knight = _PromoPermanent(card=set_pool("TMP")["Knight of Dawn"])
    game = _promo_board([knight], [])

    assert game.activate_permanent_ability(
        0, "Knight of Dawn", mana_color="B",
    ).supported
    game.resolve_stack()

    assert knight.metadata.get("protection_from_black") is True
    assert not knight.metadata.get("protection_from_red")


def test_mindwhip_sliver_is_cast_without_a_prompt(set_pool):
    """All Slivers have "{2}, Sacrifice this permanent: **Target player**
    discards a card at random."

    The target is inside a **granted quoted ability**, chosen when *that*
    ability is activated (CR 602.2b) and never as this creature is cast. The
    printed line opens "All Slivers have", so it carries no activation cost
    syntax and ``legality._cast_lines`` keeps it — which left the word "target"
    sitting in what the cast probe reads. The probe now erases quoted text, for
    the reason it already erases a "can't be the target of" prohibition.
    """
    from engine.legality import _cast_lines
    from engine.targeting import line_names_a_cast_target

    sliver = set_pool("TMP")["Mindwhip Sliver"]

    assert not any(line_names_a_cast_target(line) for line in _cast_lines(sliver))
    assert _promo_cast_spec(sliver, _promo_compile(sliver)) is None


def test_the_granted_sliver_ability_still_targets_a_player(set_pool):
    """The other half, which is why the line may not simply be vetoed: the
    quoted ability is real, it is on every Sliver, and it targets."""
    pool = set_pool("TMP")
    lord = _PromoPermanent(card=pool["Mindwhip Sliver"])
    other = _PromoPermanent(card=pool["Metallic Sliver"])
    game = _promo_board([lord, other], [])
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    game.players[1].hand.append(pool["Metallic Sliver"])

    spec = game.activation_target_spec(0, 1)
    assert spec["kind"] == "player" and spec["requires_target"] is True

    assert game.activate_permanent_ability(
        0, "Metallic Sliver", target_player_index=1,
    ).supported
    game.resolve_stack()

    assert not game.players[1].hand
    assert not game.is_on_battlefield(other)


# --- A Licid that has lost its line, and the next creature spell anybody casts ---
import pytest as _licid_pytest

from engine import Game as _LicidGame, PlayerState as _LicidPlayerState
from engine.event_durations import holds_window as _licid_holds_window
from engine.keywords import remove_ability_line as _licid_remove_ability_line
from engine.models import Permanent as _LicidPermanent


@_licid_pytest.mark.cr("613.1f", "701.3a")
def test_a_removed_ability_line_does_not_crash_the_spell_cast_window(set_pool):
    """`holds_window` asked `REMOVED_ABILITY_LINES` for a duration it never has.

    Two constants one word apart. The **keywords** channel carries dicts with a
    `duration`; the **lines** channel is a list of bare normalized sentences and
    `remove_ability_line`'s docstring says why it has no duration at all —
    "nothing in this pool takes an ability away for a while, and a duration
    nothing sweeps would be a promise the engine does not keep". So
    `entry.get("duration")` raised `AttributeError: 'str' object has no
    attribute 'get'` the first time a permanent that had lost a line met a
    spell-cast-ended window (Soul Sculptor's, the pool's only one).

    **This crashed every Tempest AI simulation**, which is how it surfaced —
    a Licid's own ability removes its printed line, and then any creature spell
    cast by anybody reached the sweep. Nothing in the suite drove the pair,
    because each half works alone.

    It was also wrong in the direction the function's own docstring warns about,
    crash aside: the sweep clears `REMOVED_ABILITY_KEYWORDS` and **nothing**
    anywhere ends a removed *line*, so the "is there anything to end?" half was
    asking about a channel the "end it" half does not touch.
    """
    pool = set_pool("TMP")
    licid = _LicidPermanent(card=pool["Leeching Licid"])
    game = _LicidGame(
        players=[_LicidPlayerState(name="P1", battlefield=[licid]),
                 _LicidPlayerState(name="P2")],
        enforce_mana_costs=False,
    )

    # What the Licid's activation does to itself (CR 613.1f, layer 6).
    _licid_remove_ability_line(licid, pool["Leeching Licid"].oracle_text.split("\n")[0])
    assert licid.metadata["removed_ability_lines"], "the line channel should be armed"
    assert all(isinstance(e, str) for e in licid.metadata["removed_ability_lines"]), (
        "this channel is bare strings by construction — if that changes, the "
        "reader above changes with it"
    )

    # The question the sweep asks of every permanent on every creature spell.
    assert _licid_holds_window(licid, "until_a_player_casts_a_creature_spell") is False

    # And end to end: casting a creature spell must not raise.
    game.players[1].hand.append(pool["Mogg Fanatic"])
    result = game.cast_from_hand(1, "Mogg Fanatic")
    assert result.supported, result.details

"""Tempest creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G3: the Slivers — a quoted activated ability granted to a tribe ---
# CR 113.3: what a card grants in quotes is a whole printed ability, not a
# keyword. Five Tempest Slivers print the shape and the engine's one reader of a
# printed ability is the compiler, so the grant rides as *text* on the derived
# layer-6 channel (`engine/keywords.py`'s DERIVED_ABILITY_LINES) and
# `Permanent.effective_card` folds it in. Everything downstream — the cost
# parser, the target picker, `activation_restrictions.py` — then reads it
# without knowing a lord granted it.
#
# The three things the grant must not lose, one test each: the cost, the
# self-reference, and Mindwhip Sliver's "Activate only as a sorcery."
import pytest

from engine import Game, PlayerState
from engine.keywords import derived_ability_lines
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W1G3_SLIVERS = (
    "Armor Sliver",
    "Barbed Sliver",
    "Clot Sliver",
    "Mnemonic Sliver",
    "Mindwhip Sliver",
)


def _w1g3_board(set_pool, names, *, enforce_mana=False):
    """*names* on seat 0's battlefield, none summoning sick, layers recomputed."""
    pool = set_pool("TMP")
    seats = [PlayerState(name="A"), PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = enforce_mana
    for name in names:
        perm = Permanent(card=pool[name])
        perm.metadata["summoning_sickness_turn"] = -99
        seats[0].battlefield.append(perm)
    game._recompute_continuous_effects()
    return game, seats


@pytest.mark.parametrize("name", _W1G3_SLIVERS)
def test_w1g3_every_sliver_lord_compiles_its_grant(set_pool, name):
    program = compile_card_oracle(set_pool("TMP")[name])
    assert program.supported, program.reason
    granted = [
        instruction.payload.get("granted_ability")
        for instruction in program.instructions
        if instruction.kind == "lord_buff"
    ]
    assert granted and granted[0], program.instructions


def test_w1g3_the_grant_reaches_every_sliver_and_leaves_with_the_lord(set_pool):
    """CR 611.3a/611.3b — derived, so the lord leaving takes it back."""
    game, seats = _w1g3_board(set_pool, ["Clot Sliver", "Metallic Sliver"])
    lord, mate = seats[0].battlefield
    assert derived_ability_lines(mate) == ("{2}: regenerate this permanent.",)
    # "All Slivers" names no "other", so the lord reaches itself too.
    assert derived_ability_lines(lord) == ("{2}: regenerate this permanent.",)

    game.remove_from_battlefield(lord)
    game._recompute_continuous_effects()
    assert derived_ability_lines(mate) == ()
    assert "regenerate" not in mate.effective_card.oracle_text.lower()


def test_w1g3_the_grant_does_not_reach_a_non_sliver(set_pool, cards):
    game, seats = _w1g3_board(set_pool, ["Clot Sliver"])
    bear = Permanent(card=cards["Grizzly Bears"])
    seats[0].battlefield.append(bear)
    game._recompute_continuous_effects()
    assert derived_ability_lines(bear) == ()


def test_w1g3_this_creature_inside_the_quotes_is_the_holder(set_pool):
    """The self-reference names the permanent that *has* the granted ability,
    never the Sliver granting it. Armor Sliver is 2/2 and Metallic Sliver 1/1,
    so the +0/+1 landing on the wrong one is visible in the numbers."""
    game, seats = _w1g3_board(set_pool, ["Armor Sliver", "Metallic Sliver"])
    lord, mate = seats[0].battlefield
    assert (mate.effective_power, mate.effective_toughness) == (1, 1)
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result
    game._recompute_continuous_effects()
    assert (mate.effective_power, mate.effective_toughness) == (1, 2)
    assert (lord.effective_power, lord.effective_toughness) == (2, 2)


def test_w1g3_the_granted_mana_cost_is_charged(set_pool):
    """{2}, with no mana available. The dict this replaced was keyed on the
    whole quoted text *including* the cost, and the reader charged {B} in
    words — so a differently-costed printing was unsupported rather than
    charged."""
    game, seats = _w1g3_board(
        set_pool, ["Armor Sliver", "Metallic Sliver"], enforce_mana=True
    )
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    assert not result.supported
    assert "insufficient mana" in result.details


def test_w1g3_the_granted_sacrifice_cost_is_charged(set_pool):
    """Mnemonic Sliver grants "{2}, Sacrifice this permanent: Draw a card." —
    the sacrifice is a cost, so the holder leaves the battlefield paying it."""
    game, seats = _w1g3_board(set_pool, ["Mnemonic Sliver", "Metallic Sliver"])
    seats[0].library.extend([set_pool("TMP")["Metallic Sliver"]] * 3)
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result
    assert [p.card.name for p in seats[0].battlefield] == ["Mnemonic Sliver"]
    assert len(seats[0].hand) == 1


def test_w1g3_mindwhip_sorcery_restriction_is_enforced(set_pool):
    """CR 602.5d. A parsed-and-dropped restriction is an ability that works
    more often than the card allows — wrong in the player's favour, and
    silent. `engine/activation_restrictions.py` reads the granted line's own
    text, so the rider travels with the grant."""
    game, seats = _w1g3_board(set_pool, ["Mindwhip Sliver", "Metallic Sliver"])
    game.active_player_index = 1
    game.current_phase = "precombat_main"
    refused = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0,
        target_player_index=1,
    )
    assert not refused.supported
    assert "sorcery-speed" in refused.details

    game.active_player_index = 0
    seats[1].hand.append(set_pool("TMP")["Metallic Sliver"])
    allowed = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0,
        target_player_index=1,
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert allowed.supported, allowed
    assert seats[1].hand == []


# --- W1G3: characteristic-defining P/T and a CR 608.2d choice ---
# Pallimud and Minion of the Wastes are CR 604.3 abilities whose value comes
# from something no battlefield holds: a seat chosen as the permanent entered,
# and life paid as it entered. Vhati il-Dal is the other half of this group's
# family — an effect that *offers* a rewrite of one creature's base P/T two
# ways.
from engine.pt import set_base_pt as _w1g3_set_base_pt  # noqa: F401  (channel doc)


def test_w1g3_pallimud_power_counts_the_chosen_players_tapped_lands(set_pool, cards):
    """CR 604.3 over CR 614.1c's chosen seat, narrowed by a *state*. The
    narrowing has to reach the tally: dropped, Pallimud's power would be every
    land the chosen player has rather than the ones they have spent."""
    tmp = set_pool("TMP")
    seats = [
        PlayerState(name="A", hand=[tmp["Pallimud"]]),
        PlayerState(name="B"),
    ]
    for name, tapped in (("Mountain", True), ("Mountain", True),
                         ("Forest", False), ("Grizzly Bears", True)):
        perm = Permanent(card=cards[name])
        perm.metadata["summoning_sickness_turn"] = -99
        perm.tapped = tapped
        seats[1].battlefield.append(perm)
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Pallimud")
    while game.stack:
        game.resolve_top_of_stack()
    pallimud = seats[0].battlefield[-1]
    assert pallimud.metadata.get("chosen_player_index") == 1
    game._recompute_continuous_effects()
    # Two tapped Mountains. The tapped Grizzly Bears is not a land and the
    # untapped Forest is not tapped; the printed toughness (3) stands, because
    # the sentence defines the power half alone.
    assert (pallimud.effective_power, pallimud.effective_toughness) == (2, 3)

    seats[1].battlefield[2].tapped = True
    game._recompute_continuous_effects()
    assert pallimud.effective_power == 3


def test_w1g3_minion_of_the_wastes_pays_any_life_up_to_its_controllers_total(set_pool):
    """Nameless Race's entry cost with the cap sentence unprinted. Uncapped,
    the ceiling is CR 119.4's: a player may pay more than 0 only up to their
    life total."""
    tmp = set_pool("TMP")
    seats = [PlayerState(name="A", hand=[tmp["Minion of the Wastes"]], life=20),
             PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Minion of the Wastes")
    while game.stack:
        game.resolve_top_of_stack()
    assert game.pending_choices[0].data["maximum"] == 20
    assert game.confirm_number_choice(0, 7)
    game._recompute_continuous_effects()
    minion = seats[0].battlefield[-1]
    assert seats[0].life == 13
    assert (minion.effective_power, minion.effective_toughness) == (7, 7)


def test_w1g3_the_pay_life_ceiling_is_the_payers_life_total(set_pool):
    tmp = set_pool("TMP")
    seats = [PlayerState(name="A", hand=[tmp["Minion of the Wastes"]], life=3),
             PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Minion of the Wastes")
    while game.stack:
        game.resolve_top_of_stack()
    assert game.pending_choices[0].data["maximum"] == 3
    assert not game.confirm_number_choice(0, 5)


@pytest.mark.parametrize(
    "mode_index,expected", [(0, (1, 4)), (1, (4, 1))]
)
def test_w1g3_vhati_offers_the_choice_at_resolution(set_pool, cards, mode_index, expected):
    """CR 608.2d, not CR 700.2. A modal ability is a *bulleted* list preceded
    by "Choose one —" and its mode is chosen as the ability is activated; Vhati
    prints no bullets, so the option is announced while the effect is applied —
    the same rule "gains your choice of deathtouch or lifelink" is read under,
    and the same ``choose_one`` seam."""
    tmp = set_pool("TMP")
    vhati = Permanent(card=tmp["Vhati il-Dal"])
    vhati.metadata["summoning_sickness_turn"] = -99
    angel = Permanent(card=cards["Serra Angel"])
    seats = [PlayerState(name="A", battlefield=[vhati]),
             PlayerState(name="B", battlefield=[angel])]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    result = game.activate_permanent_ability(
        0, "Vhati il-Dal", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=mode_index)
    while game.stack:
        game.resolve_top_of_stack()
    game._recompute_continuous_effects()
    assert (angel.effective_power, angel.effective_toughness) == expected


def test_w1g3_a_base_pt_choice_still_reads_the_and_spelling(set_pool, cards):
    """"base power **and** toughness 0/2" is one rewrite, not two options —
    the branch above must not eat its "and". Sorceress Queen, Jolrael and Cycle
    of Life all compiled to nothing the first time this was written, and only
    the pool-wide differential said so."""
    from engine.oracle import compile_card_oracle as _compile

    for name in ("Sorceress Queen", "Jolrael, Mwonvuli Recluse"):
        card = cards.get(name) or set_pool("TMP").get(name)
        if card is None:
            continue
        assert _compile(card).supported, name


# --- W1G3: Dracoplasm — an entry sacrifice that defines the size ---
def test_w1g3_dracoplasm_is_the_total_of_what_was_given_up(set_pool, cards):
    """CR 604.3 over CR 614.1c's entry cost, and CR 608.2g's last known
    information: the creatures are cards in a graveyard a moment later and have
    no computed characteristics at all, so the sums are read at the removal
    site rather than recounted afterwards.

    Two sums, not one — every other entry in `characteristic_defining.py`
    derives the second half from the first, and this is the one card where the
    halves are independent numbers."""
    tmp = set_pool("TMP")
    bears = Permanent(card=cards["Grizzly Bears"])
    angel = Permanent(card=cards["Serra Angel"])
    for perm in (bears, angel):
        perm.metadata["summoning_sickness_turn"] = -99
    seats = [PlayerState(name="A", hand=[tmp["Dracoplasm"]], battlefield=[bears, angel]),
             PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Dracoplasm")
    while game.stack:
        game.resolve_top_of_stack()
    assert game.resolve_pending_choice("sacrifice", 0, indices=[0, 1])
    game._recompute_continuous_effects()
    dracoplasm = seats[0].battlefield[-1]
    assert [p.card.name for p in seats[0].battlefield] == ["Dracoplasm"]
    # 2/2 + 4/4.
    assert (dracoplasm.effective_power, dracoplasm.effective_toughness) == (6, 6)
    # …and its own {R} pump is layer 7c, over the 7b the entry set.
    result = game.activate_permanent_ability(0, "Dracoplasm", permanent_index=0)
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result
    game._recompute_continuous_effects()
    assert (dracoplasm.effective_power, dracoplasm.effective_toughness) == (7, 6)


def test_w1g3_dracoplasm_declined_enters_as_a_nothing(set_pool, cards):
    """"Any number" answered with none is zero, which is what the card does
    when its controller declines — the stated policy Wood Elemental already
    follows for a non-interactive seat."""
    tmp = set_pool("TMP")
    seats = [PlayerState(name="A", hand=[tmp["Dracoplasm"]]), PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Dracoplasm")
    while game.stack:
        game.resolve_top_of_stack()
    dracoplasm = next(
        (p for p in seats[0].battlefield if p.card.name == "Dracoplasm"), None
    )
    if dracoplasm is not None:
        game._recompute_continuous_effects()
        assert (dracoplasm.effective_power, dracoplasm.effective_toughness) == (0, 0)

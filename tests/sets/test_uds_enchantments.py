"""Urza's Destiny enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: being enchanted, and enchantments that become creatures ---

from engine import Game, PlayerState
from engine.auras import attach_aura, aura_protection_colors
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack


def _w1g3_uds_creature(name: str, power: int, toughness: int, colors=()):
    """A vanilla creature with a colour, which the protection Aura reads."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_uds_game(*battlefields, lives=None):
    """One game with each seat's battlefield handed over as a list of permanents."""
    game = Game(players=[
        PlayerState(name=f"P{index}", battlefield=list(permanents))
        for index, permanents in enumerate(battlefields)
    ])
    game.enforce_mana_costs = False
    for index, life in enumerate(lives or ()):
        game.players[index].life = life
    for player in game.players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game


# --- Mask of Law and Grace -------------------------------------------------
# "Enchanted creature has protection from black and from red." CR 702.16g makes
# that clause two protection abilities, and the Aura reader had been one colour
# wide with an unanchored tail — so it matched the line and returned black.


def test_mask_of_law_and_grace_grants_both_printed_colours(set_pool):
    host = Permanent(card=_w1g3_uds_creature("Host", 2, 2))
    mask = Permanent(card=set_pool("UDS")["Mask of Law and Grace"])
    game = _w1g3_uds_game([host, mask])
    attach_aura(mask, host)

    assert game._protection_qualities(host) == {("color", "B"), ("color", "R")}


def test_mask_of_law_and_grace_reads_both_colours_off_the_text(set_pool):
    """The reader the layer bridge asks, so a gate that admitted the line and a
    grant that dropped half of it cannot pass this together."""
    mask = set_pool("UDS")["Mask of Law and Grace"]

    assert aura_protection_colors(mask.oracle_text) == frozenset({"black", "red"})
    assert compile_card_oracle(mask).supported


def test_mask_of_law_and_grace_leaves_the_other_three_colours_alone(set_pool):
    host = Permanent(card=_w1g3_uds_creature("Host", 2, 2))
    mask = Permanent(card=set_pool("UDS")["Mask of Law and Grace"])
    game = _w1g3_uds_game([host, mask])
    attach_aura(mask, host)

    qualities = game._protection_qualities(host)

    assert ("color", "G") not in qualities
    assert ("color", "U") not in qualities
    assert ("color", "W") not in qualities


# --- Opalescence -----------------------------------------------------------
# "Each other non-Aura enchantment is a creature in addition to its other types
# and has base power and base toughness each equal to its mana value."
# Titania's Song's sentence one card type over: CR 613.1d's addition and
# CR 613.4b's base-P/T setting, both already read off a `GlobalStatic`.


def test_opalescence_animates_another_enchantment(set_pool, catalog_by_name):
    opal = Permanent(card=set_pool("UDS")["Opalescence"])
    other = Permanent(card=catalog_by_name["Nevinyrral's Disk"])  # not an enchantment
    crusade = Permanent(card=catalog_by_name["Crusade"])          # {W}{W}
    game = _w1g3_uds_game([opal, other, crusade])
    game._refresh_dynamic_creatures()

    assert crusade.is_creature
    assert crusade.has_type("enchantment")
    # Base 2/2 from its own mana value, +1/+1 because Crusade is a white
    # creature and its own anthem now reaches it.
    assert (crusade.effective_power, crusade.effective_toughness) == (3, 3)
    assert not other.is_creature


def test_opalescence_does_not_animate_itself(set_pool, catalog_by_name):
    """"Each **other**" is CR 109.5's exclusion, and the templates in this table
    are applied to their own source unless the card says otherwise."""
    opal = Permanent(card=set_pool("UDS")["Opalescence"])
    game = _w1g3_uds_game([opal, Permanent(card=catalog_by_name["Crusade"])])
    game._refresh_dynamic_creatures()

    assert not opal.is_creature


def test_opalescence_does_not_animate_an_aura(set_pool, catalog_by_name):
    """"non-Aura" is a narrowing on the noun. An animated Aura would stop being
    attached and be binned by CR 704.5m, which is the card printing the opposite
    of what it says."""
    opal = Permanent(card=set_pool("UDS")["Opalescence"])
    host = Permanent(card=_w1g3_uds_creature("Host", 2, 2))
    aura = Permanent(card=catalog_by_name["Holy Strength"])
    game = _w1g3_uds_game([opal, host, aura])
    attach_aura(aura, host)
    game._refresh_dynamic_creatures()

    assert not aura.is_creature
    assert (host.effective_power, host.effective_toughness) == (3, 4)


def test_opalescence_reaches_an_opponents_enchantment(set_pool, catalog_by_name):
    """The printed noun carries no seat, so CR 109.2's description is every
    battlefield — the same reading Darkest Hour's row takes."""
    opal = Permanent(card=set_pool("UDS")["Opalescence"])
    theirs = Permanent(card=catalog_by_name["Crusade"])
    game = _w1g3_uds_game([opal], [theirs])
    game._refresh_dynamic_creatures()

    assert theirs.is_creature


# --- Lurking Jackals -------------------------------------------------------
# "When an opponent has 10 or less life, if this permanent is an enchantment,
# it becomes a 3/2 Jackal creature." CR 603.8's state trigger over the *other*
# seat's life total, where Opal Avenger prints the same sentence about its own.


def test_lurking_jackals_sleeps_while_every_opponent_is_healthy(set_pool):
    jackals = Permanent(card=set_pool("UDS")["Lurking Jackals"])
    game = _w1g3_uds_game([jackals], [], lives=(20, 20))
    game.check_state_based_actions()
    resolve_stack(game)

    assert not jackals.is_creature


def test_lurking_jackals_wakes_when_an_opponent_falls_to_ten(set_pool):
    jackals = Permanent(card=set_pool("UDS")["Lurking Jackals"])
    game = _w1g3_uds_game([jackals], [], lives=(20, 10))
    game.check_state_based_actions()
    resolve_stack(game)

    assert jackals.is_creature
    assert (jackals.effective_power, jackals.effective_toughness) == (3, 2)
    assert jackals.has_type("jackal")


def test_lurking_jackals_ignores_its_own_controllers_life_total(set_pool):
    """"An opponent" is the printed seat. Read as "you" — which is the seat the
    row carried before Lurking Jackals arrived — this animates at exactly the
    wrong moment."""
    jackals = Permanent(card=set_pool("UDS")["Lurking Jackals"])
    game = _w1g3_uds_game([jackals], [], lives=(10, 20))
    game.check_state_based_actions()
    resolve_stack(game)

    assert not jackals.is_creature


def test_lurking_jackals_names_the_seat_on_its_condition(set_pool):
    program = compile_card_oracle(set_pool("UDS")["Lurking Jackals"])

    (trigger,) = program.triggered_abilities

    assert trigger.condition.kind == "life_at_most"
    assert trigger.condition.payload == {"life_seat": "an opponent", "life_count": 10}

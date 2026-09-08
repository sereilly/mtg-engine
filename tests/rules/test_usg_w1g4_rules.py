"""The rules the Urza's Saga Auras exercised (USG wave 1, W1G4).

Four of them, and each is a rule the engine already implemented for one shape
and reached by only one route:

* **CR 700.4** — "dies" is any *permanent* being put into a graveyard from the
  battlefield, and the enqueue that puts such a trigger on the stack sat inside
  ``_permanent_to_graveyard``'s ``is_creature`` branch. So an Aura, an artifact
  or an enchantment printing its own death trigger compiled one and nothing
  ever announced it. Lich is what that cost: its whole downside was carried by
  a substring test on the printed sentence, applied inline and off the stack,
  because the general path could not reach an enchantment.
* **CR 702.5** — an Enchant clause naming a land *subtype*. The claim, the
  picker and the attach check are three readers of one clause, and the third is
  the one whose absence is silent: a noun with no matcher row reaches a
  permissive fallback, so the printed restriction is enforced by nothing.
* **CR 614.9** — a redirection with no duration, which is an Aura's static
  ability rather than a record something armed.
* **CR 509.1b** — a blocking restriction reaching the attacker through the
  attached channel as well as through its own printed text.

Its own file per SET_PLAYBOOK's block convention — a group's rules tests do not
share a file, so a mechanical union has nothing to splice.
"""

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack

_USG = {
    card.name: card
    for card in load_cards(manifest_set_path("USG", include_measured=True))
}


def _w1g4_bear(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}{G}", cmc=2.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_duel(mine: list, theirs: list | None = None, *, life: int = 20):
    """``(game, seat0, seat1)`` with mana enforcement off and control synced."""
    w1g4_seat0 = PlayerState(name="P1", battlefield=list(mine), life=life)
    w1g4_seat1 = PlayerState(name="P2", battlefield=list(theirs or []), life=life)
    w1g4_game = Game(players=[w1g4_seat0, w1g4_seat1])
    w1g4_game.enforce_mana_costs = False
    w1g4_game._sync_control()
    return w1g4_game, w1g4_seat0, w1g4_seat1


# ---------------------------------------------------------------------------
# CR 700.4 — "dies" is any permanent's move to a graveyard, not a creature's
# ---------------------------------------------------------------------------


@pytest.mark.cr("700.4", "603.3")
def test_700_4_a_non_creature_permanents_own_death_puts_its_trigger_on_the_stack():
    """An Aura is not a creature, and its own death still fires its own trigger.

    The enqueue used to sit inside the creature branch of the graveyard
    transition, so this compiled and announced nothing at all - the shape
    CR 700.4 says cannot be right, since the rule names a *permanent*.
    """
    host = Permanent(card=_w1g4_bear("Host"))
    aura = Permanent(card=_USG["Brilliant Halo"])
    game, mine, _ = _w1g4_duel([host, aura])
    attach_aura(aura, host)

    game._destroy_swept_permanents(mine, lambda perm: perm is aura)

    assert len(game.stack) == 1, "CR 603.3: the trigger goes on the stack"
    resolve_stack(game)
    assert [card.name for card in mine.hand] == ["Brilliant Halo"]


@pytest.mark.cr("700.4", "603.3")
def test_700_4_lich_still_loses_the_game_through_the_general_path():
    """The substring branch that used to carry this is gone.

    It existed only because the enqueue above could not reach an enchantment,
    and keeping both would fire the loss twice on every path that reaches both.
    The loss now happens on *resolution*, which is what CR 603.3 says a
    triggered ability does.
    """
    catalog = {
        card.name: card for card in load_cards(manifest_set_path("LEA"))
    }
    lich = Permanent(card=catalog["Lich"])
    game, mine, _ = _w1g4_duel([lich], life=0)

    game._destroy_swept_permanents(mine, lambda perm: perm is lich)
    assert mine.lost is False, "the ability is on the stack, not applied yet"

    resolve_stack(game)
    assert mine.lost is True


# ---------------------------------------------------------------------------
# CR 702.5 — Enchant, with a land subtype as the printed quality
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.5", "305.7")
def test_702_5_an_enchant_subtype_clause_is_enforced_and_not_merely_offered():
    """"Enchant Swamp" (Spreading Algae).

    Two readers, because a clause claimed by one and dropped by the other is the
    failure Homelands' Roots recorded: the picker offering nothing makes the
    card uncastable, and the attach check falling through to its permissive
    fallback makes the restriction enforced by nothing at all. Both are asked
    here, and both read CR 613 layer 4 - so CR 305.7's Swamp-turned-Island stops
    being a legal host.
    """
    from engine.auras import aura_attach_refusal
    from engine.mixins.stack.casting import permanent_matches_enchant_noun
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    algae = _USG["Spreading Algae"]
    swamp = Permanent(card=_USG["Swamp"])
    island = Permanent(card=_USG["Island"])
    game, _, _ = _w1g4_duel([swamp, island])

    spec = derive_cast_spec(algae, compile_card_oracle(algae))
    offered = game._enumerate_targets(0, algae, spec, for_cast=True)
    assert [entry["name"] for entry in offered] == ["Swamp"]

    assert permanent_matches_enchant_noun(swamp, "swamp")
    assert not permanent_matches_enchant_noun(island, "swamp")
    aura = Permanent(card=algae)
    assert aura_attach_refusal(game, aura, island) is not None


# ---------------------------------------------------------------------------
# CR 614.9 — a redirection an Aura's static text gives, and its liveness half
# ---------------------------------------------------------------------------


@pytest.mark.cr("614.9")
def test_614_9_an_aura_redirects_its_controllers_damage_onto_its_host():
    """Pariah. The damage is *dealt* to the creature, in full, by the same
    source - not prevented and re-dealt, which would lose the source."""
    host = Permanent(card=_w1g4_bear("Wall", 0, 6))
    aura = Permanent(card=_USG["Pariah"])
    game, mine, _ = _w1g4_duel([host, aura])
    attach_aura(aura, host)

    game._deal_damage_to_player(mine, 5, source=aura)

    assert mine.life == 20
    assert host.damage_marked == 5


@pytest.mark.cr("614.9")
def test_614_9_the_redirect_does_nothing_once_its_new_recipient_has_left():
    """"If one of those permanents is no longer on the battlefield ... the
    effect does nothing."

    Which is also why the record is derived from the Aura's text on each event
    rather than armed: when the host dies the Aura goes with it (CR 704.5m) and
    there is no stale record to sweep.
    """
    host = Permanent(card=_w1g4_bear("Wall", 0, 3))
    aura = Permanent(card=_USG["Pariah"])
    game, mine, _ = _w1g4_duel([host, aura])
    attach_aura(aura, host)

    game._deal_damage_to_player(mine, 3, source=aura)
    game.check_state_based_actions()
    assert mine.life == 20

    game._deal_damage_to_player(mine, 3, source=aura)
    assert mine.life == 17


# ---------------------------------------------------------------------------
# CR 509.1b — a blocking restriction the attacker's Aura imposes
# ---------------------------------------------------------------------------


@pytest.mark.cr("509.1b")
def test_509_1b_an_aura_granted_cant_be_blocked_refuses_every_blocker():
    """Cloak of Mists. The kind had two enforcement sites keyed to the
    attacker's *own* printed text; an Aura imposing it reached neither."""
    attacker = Permanent(card=_w1g4_bear("Attacker"))
    blocker = Permanent(card=_w1g4_bear("Blocker"))
    aura = Permanent(card=_USG["Cloak of Mists"])
    game, _, _ = _w1g4_duel([attacker, aura], [blocker])
    attacker.attacking = True

    assert game._can_block_attacker(blocker, attacker)
    attach_aura(aura, attacker)
    assert not game._can_block_attacker(blocker, attacker)


# ---------------------------------------------------------------------------
# CR 605.4a — the extra mana an attached trigger adds, resolved inline
# ---------------------------------------------------------------------------


@pytest.mark.cr("605.4a")
def test_605_4a_the_attached_mana_trigger_resolves_without_the_stack():
    """Fertile Ground. A triggered mana ability resolves immediately after the
    ability that triggered it, without waiting for priority - so the extra mana
    is in the pool when ``tap_land_for_mana`` returns and the stack is empty.

    Which is also the reason "one mana of any color" is answered from the
    colour the tap was asked for: there is no window in which to prompt.
    """
    forest = Permanent(card=_USG["Forest"])
    aura = Permanent(card=_USG["Fertile Ground"])
    game, mine, _ = _w1g4_duel([forest, aura])
    attach_aura(aura, forest)

    game.tap_land_for_mana(0, "Forest", chosen_color="B")

    assert game.stack == []
    assert {sym: n for sym, n in mine.mana_pool.items() if n} == {"G": 1, "B": 1}

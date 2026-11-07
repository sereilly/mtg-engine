"""A bare creature type names a permanent of that type — not a creature of it
(CR 109.2, 205.3m, 308.2).

    109.2 If a spell or ability uses a description of an object that includes
    a card type or subtype, but doesn't refer to a specific zone or include
    the word "card," "spell," "source," or "scheme," it means a permanent of
    that card type or subtype on the battlefield.

    205.3m Creatures and kindreds share their lists of subtypes; these
    subtypes are called creature types.

``nouns.parse_object_filter`` implied the creature type after every bare
creature type, so "destroy target Wall" (Tunnel), "Other Goblins get +1/+1 and
have mountainwalk" (Goblin King), "Sacrifice a Goblin" (Arms Dealer),
"Regenerate target Beast" (Krosan Warchief) and about two hundred other
programs named a Wall *creature*, a Goblin *creature*. Exact on a pool with no
Kindred card, narrower on one: a Kindred Artifact — Wall is a Wall and no
creature. The text table beside the grammar for lords
(``lord_buffs._parse_subject``) made the same implication for the lords it
reads ("Other Zombies have "{B}: Regenerate this permanent."", the Sliver
grants).

The pool has no Kindred permanent, so the board is invented Kindred
permanents beside the real pool's own answer, driven down each reader's road:
a cast's picker and gate, an activation's picker and handler, a sacrifice and
a tap cost, a lord's grants (and a lord that prints "creatures", which still
reads creatures), an entry and a death trigger, a count, a sweep, an Aura's
enchant clause, and the AI's "is there something there to destroy?".

Measured backwards: on 243f72df every Kindred case fails and every control
passes (Tunnel refusing the Bears, Rashida Scalebane offering no idle Dragon,
Glyph of Destruction's blocking Wall). With the parse, the lords and the AI arm
changed and the readers below them left as they were, the regeneration (cast
and activation), counter, enchant-Wall and Glyph of Destruction cases fail —
the last offering a blocking Bears, because the general picker dropped the
Wall and blocking flags.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _kindred(name: str, type_line: str, oracle_text: str = "",
             mana_cost: str = "{2}") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=2.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw={"name": name, "type_line": type_line},
    )


WALL = _kindred("Test Wall Idol", "Kindred Artifact — Wall")
GOBLIN = _kindred("Test Goblin Idol", "Kindred Artifact — Goblin")
BEAST = _kindred("Test Beast Idol", "Kindred Enchantment — Beast")
CAT = _kindred("Test Cat Idol", "Kindred Artifact — Cat")
ELF = _kindred("Test Elf Idol", "Kindred Artifact — Elf")
ZOMBIE = _kindred("Test Zombie Idol", "Kindred Artifact — Zombie")
WIZARD = _kindred("Test Wizard Idol", "Kindred Artifact — Wizard")
BIRD = _kindred("Test Bird Idol", "Kindred Artifact — Bird")
CLERIC = _kindred("Test Cleric Idol", "Kindred Artifact — Cleric")
DRAGON = _kindred("Test Dragon Idol", "Kindred Artifact — Dragon")


def _duel(*, mine=(), theirs=(), hand=(), interactive=False) -> Game:
    """Seat 0's main phase, mana costs not enforced, every permanent past
    summoning sickness. The libraries are Islands."""
    filler = [_POOL["Island"]] * 6
    game = Game(players=[
        PlayerState(name="P0", battlefield=[Permanent(card=c) for c in mine],
                    hand=list(hand), library=list(filler)),
        PlayerState(name="P1", battlefield=[Permanent(card=c) for c in theirs],
                    library=list(filler)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    game._sync_control()
    for permanent in game.all_permanents():
        _nosick(permanent)
    game._recompute_continuous_effects()
    return game


def _settle(game: Game) -> None:
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _permanent(game: Game, name: str) -> Permanent:
    return next(p for p in game.all_permanents() if p.card.name == name)


def _present(game: Game, name: str) -> bool:
    return any(p.card.name == name for p in game.all_permanents())


def _offered(spec: dict | None) -> list[str]:
    return sorted(str(t.get("name")) for t in (spec or {}).get("valid_targets") or ())


def _ability_spec(game: Game, name: str, ability_index: int = 0) -> dict:
    source = _permanent(game, name)
    return game.activation_target_spec(
        game.controller_index_of(source), game.battlefield_index_of(source), ability_index,
    )


def _activate(game: Game, name: str, target: Permanent, ability_index: int = 0, **kwargs):
    seat = game.controller_index_of(_permanent(game, name))
    return game.queue_permanent_ability(
        seat, name, ability_index=ability_index,
        target_player_index=game.controller_index_of(target),
        target_permanent_ids=[target.permanent_id], **kwargs,
    )


# --- a target --------------------------------------------------------------


@pytest.mark.cr("109.2", "205.3m", "601.2c", "701.8a")
@pytest.mark.parametrize("interactive", [False, True])
def test_tunnel_destroys_a_kindred_wall(interactive):
    """"Destroy target Wall. It can't be regenerated." The cast's picker offers
    the Kindred Wall beside the Wall creature and not the Bears, and the spell
    destroys the one named."""
    game = _duel(hand=[_POOL["Tunnel"]], interactive=interactive,
                 theirs=[WALL, _POOL["Wall of Stone"], _POOL["Grizzly Bears"]])
    spec = game.cast_target_spec(0, _POOL["Tunnel"])
    assert _offered(spec) == ["Test Wall Idol", "Wall of Stone"], spec
    idol = _permanent(game, WALL.name)
    result = game.cast_from_hand(
        0, "Tunnel", target_player_index=1, target_permanent_ids=[idol.permanent_id],
    )
    assert result.supported, result.details
    _settle(game)
    assert not game.is_on_battlefield(idol), game.log[-3:]
    assert _present(game, "Wall of Stone") and _present(game, "Grizzly Bears")


@pytest.mark.cr("109.2", "601.2c")
def test_tunnel_cannot_be_aimed_at_a_creature_that_is_no_wall():
    """The control: what the picker leaves out, the gate refuses."""
    game = _duel(hand=[_POOL["Tunnel"]], theirs=[_POOL["Grizzly Bears"]])
    assert _offered(game.cast_target_spec(0, _POOL["Tunnel"])) == []
    bears = _permanent(game, "Grizzly Bears")
    result = game.cast_from_hand(
        0, "Tunnel", target_player_index=1, target_permanent_ids=[bears.permanent_id],
    )
    assert not result.supported
    assert game.is_on_battlefield(bears)


@pytest.mark.cr("109.2", "205.3m", "602.2b")
def test_ali_baba_taps_a_kindred_wall():
    """"{R}: Tap target Wall." """
    game = _duel(mine=[_POOL["Ali Baba"]], theirs=[WALL, _POOL["Grizzly Bears"]])
    assert _offered(_ability_spec(game, "Ali Baba")) == ["Test Wall Idol"]
    idol = _permanent(game, WALL.name)
    assert _activate(game, "Ali Baba", idol).supported
    _settle(game)
    assert idol.tapped, game.log[-3:]


@pytest.mark.cr("109.2", "602.2b", "601.2c")
def test_rashida_scalebane_offers_no_dragon_that_is_out_of_combat():
    """"{T}: Destroy target attacking or blocking Dragon. You gain life equal
    to its power." A bare creature type gives the picker the general kind, and
    the combat narrowing is asked in that branch too: an idle Dragon — a
    creature or a Kindred — is no legal target, so nothing can be named."""
    game = _duel(mine=[_POOL["Rashida Scalebane"]],
                 theirs=[_POOL["Shivan Dragon"], DRAGON])
    assert _offered(_ability_spec(game, "Rashida Scalebane")) == []
    dragon = _permanent(game, "Shivan Dragon")
    assert not _activate(game, "Rashida Scalebane", dragon).supported
    assert game.is_on_battlefield(dragon)


@pytest.mark.cr("109.2", "509.1a", "601.2c")
def test_glyph_of_destruction_offers_the_blocking_wall_alone():
    """"Target blocking Wall you control gets +10/+0 until end of combat…" A
    bare creature type gives the cast's picker the general kind, and the Wall
    and blocking flags are asked in that branch too — the cast gate for this
    instruction asks "blocking" and not "Wall", so a flag the general branch
    dropped was a blocking Bears offered to a Wall's spell."""
    attackers = [Permanent(card=_POOL["Hill Giant"]), Permanent(card=_POOL["Hill Giant"])]
    wall = Permanent(card=_POOL["Wall of Stone"])
    bears = Permanent(card=_POOL["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=attackers, library=[_POOL["Island"]] * 6),
        PlayerState(name="P1", hand=[_POOL["Glyph of Destruction"]],
                    battlefield=[wall, bears], library=[_POOL["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()  # declare blockers
    assert game.declare_blockers(1, {0: 0, 1: 1})[0]
    game._settle()
    spec = game.cast_target_spec(1, _POOL["Glyph of Destruction"])
    assert _offered(spec) == ["Wall of Stone"], spec


@pytest.mark.cr("109.2", "205.3m", "701.19a")
def test_krosan_warchief_regenerates_a_kindred_beast():
    """"{1}{G}: Regenerate target Beast." Regeneration replaces the destruction
    of a permanent (CR 701.19a), and the Kindred Enchantment — Beast is a
    Beast: the shield it gets is the one that saves it from Disenchant."""
    game = _duel(mine=[_POOL["Krosan Warchief"], BEAST, _POOL["Grizzly Bears"]],
                 hand=[_POOL["Disenchant"]])
    assert _offered(_ability_spec(game, "Krosan Warchief")) == [
        "Krosan Warchief", "Test Beast Idol",
    ]
    idol = _permanent(game, BEAST.name)
    assert _activate(game, "Krosan Warchief", idol).supported
    _settle(game)
    assert idol.regeneration_shield == 1, game.log[-3:]
    result = game.cast_from_hand(
        0, "Disenchant", target_player_index=0, target_permanent_ids=[idol.permanent_id],
    )
    assert result.supported, result.details
    _settle(game)
    assert game.is_on_battlefield(idol), game.log[-4:]
    assert idol.tapped and idol.regeneration_shield == 0


@pytest.mark.cr("109.2", "205.3m", "601.2c", "701.19a")
def test_vitality_charm_may_regenerate_a_kindred_beast():
    """"Choose one — … • Regenerate target Beast." The cast side of the same
    reader: the mode's picker offers the Kindred Beast and the gate takes it."""
    game = _duel(hand=[_POOL["Vitality Charm"]], mine=[BEAST, _POOL["Grizzly Bears"]])
    spec = game.cast_target_spec(0, _POOL["Vitality Charm"], mode_index=2)
    assert _offered(spec) == ["Test Beast Idol"], spec
    idol = _permanent(game, BEAST.name)
    result = game.cast_from_hand(
        0, "Vitality Charm", mode_index=2, target_player_index=0,
        target_permanent_ids=[idol.permanent_id],
    )
    assert result.supported, result.details
    _settle(game)
    assert idol.regeneration_shield == 1, game.log[-3:]


@pytest.mark.cr("109.2", "205.3m", "122.1")
def test_animal_sanctuary_counters_a_kindred_cat():
    """"{2}, {T}: Put a +1/+1 counter on target Bird, Cat, Dog, Goat, Ox, or
    Snake." A counter may sit on any permanent (CR 122.1)."""
    game = _duel(mine=[_POOL["Animal Sanctuary"], CAT, _POOL["Grizzly Bears"]])
    assert _offered(_ability_spec(game, "Animal Sanctuary", 1)) == ["Test Cat Idol"]
    idol = _permanent(game, CAT.name)
    assert _activate(game, "Animal Sanctuary", idol, ability_index=1).supported
    _settle(game)
    assert int(idol.metadata.get("plus_counters", 0)) == 1, game.log[-3:]


@pytest.mark.cr("109.2", "205.3m", "702.16a")
def test_goblin_wizard_protects_a_kindred_goblin():
    """"{R}: Target Goblin gains protection from white until end of turn." """
    game = _duel(mine=[_POOL["Goblin Wizard"], GOBLIN, _POOL["Grizzly Bears"]])
    assert _offered(_ability_spec(game, "Goblin Wizard", 1)) == [
        "Goblin Wizard", "Test Goblin Idol",
    ]
    idol = _permanent(game, GOBLIN.name)
    assert _activate(game, "Goblin Wizard", idol, ability_index=1).supported
    _settle(game)
    assert ("color", "W") in game._protection_qualities(idol), game.log[-3:]


# --- a lord ----------------------------------------------------------------


@pytest.mark.cr("109.2", "205.3m", "613.1f")
def test_eladamri_reads_elves_and_elf_creatures_apart():
    """"Other Elf creatures have forestwalk. Other Elves have shroud." One
    card printing both readings: the Kindred Elf is an Elf and has shroud, and
    is no Elf creature and has no forestwalk; an Elf creature has both."""
    game = _duel(mine=[_POOL["Eladamri, Lord of Leaves"], ELF, _POOL["Llanowar Elves"]])
    idol = _permanent(game, ELF.name)
    elves = _permanent(game, "Llanowar Elves")
    assert game._has_keyword(idol, "shroud")
    assert not game._has_keyword(idol, "forestwalk")
    assert game._has_keyword(elves, "shroud") and game._has_keyword(elves, "forestwalk")


@pytest.mark.cr("109.2", "205.3m", "613.1f", "702.14a")
def test_goblin_king_reaches_a_kindred_goblin():
    """"Other Goblins get +1/+1 and have mountainwalk." The Kindred Goblin has
    mountainwalk (and no power to add to, CR 208.3); the Goblin creature gets
    both, as it always did."""
    game = _duel(mine=[_POOL["Goblin King"], GOBLIN, _POOL["Raging Goblin"]])
    idol = _permanent(game, GOBLIN.name)
    raging = _permanent(game, "Raging Goblin")
    assert game._has_keyword(idol, "mountainwalk")
    assert game._has_keyword(raging, "mountainwalk")
    assert (raging.effective_power, raging.effective_toughness) == (2, 2)


@pytest.mark.cr("109.2", "205.3m", "613.1f")
def test_zombie_master_grants_its_regeneration_to_a_kindred_zombie():
    """"Other Zombie creatures have swampwalk. Other Zombies have "{B}:
    Regenerate this permanent."" The quoted grant is the text table's
    (``lord_buffs._parse_subject``), and it reads the bare type as the
    grammar does."""
    game = _duel(mine=[_POOL["Zombie Master"], ZOMBIE])
    idol = _permanent(game, ZOMBIE.name)
    granted = [
        ability.source_line.lower()
        for ability in compile_card_oracle(idol.effective_card).activated_abilities
    ]
    assert granted == ["{b}: regenerate this permanent."], granted
    assert not game._has_keyword(idol, "swampwalk")


# --- a cost ----------------------------------------------------------------


@pytest.mark.cr("109.2", "205.3m", "601.2h", "701.21a")
@pytest.mark.parametrize("interactive", [False, True])
def test_arms_dealer_may_sacrifice_a_kindred_goblin(interactive):
    """"{1}{R}, Sacrifice a Goblin: This creature deals 4 damage to target
    creature." The cost's picker offers the Kindred Goblin, and naming it pays."""
    game = _duel(mine=[_POOL["Arms Dealer"], GOBLIN], theirs=[_POOL["Hill Giant"]],
                 interactive=interactive)
    cost = _ability_spec(game, "Arms Dealer").get("cost_spec") or {}
    assert _offered(cost) == ["Arms Dealer", "Test Goblin Idol"], cost
    idol = _permanent(game, GOBLIN.name)
    giant = _permanent(game, "Hill Giant")
    assert _activate(game, "Arms Dealer", giant, cost_permanent_ids=[idol.permanent_id]).supported
    _settle(game)
    assert not game.is_on_battlefield(idol)
    assert giant.damage_marked == 4, game.log[-3:]
    assert _present(game, "Arms Dealer")


@pytest.mark.cr("109.2", "205.3m", "601.2h")
def test_crookclaw_elder_taps_a_kindred_bird_for_its_cost():
    """"Tap two untapped Birds you control: Draw a card." The Elder (a Bird)
    and the Kindred Bird are the two."""
    game = _duel(mine=[_POOL["Crookclaw Elder"], BIRD])
    elder = _permanent(game, "Crookclaw Elder")
    idol = _permanent(game, BIRD.name)
    hand = len(game.players[0].hand)
    result = game.queue_permanent_ability(
        0, "Crookclaw Elder", ability_index=0,
        cost_permanent_ids=[elder.permanent_id, idol.permanent_id],
    )
    assert result.supported, result.details
    _settle(game)
    assert elder.tapped and idol.tapped
    assert len(game.players[0].hand) == hand + 1, game.log[-3:]


# --- a trigger, a count, a sweep -------------------------------------------


@pytest.mark.cr("109.2", "205.3m", "603.2")
def test_aether_charge_triggers_on_a_kindred_beast_entering():
    """"Whenever a Beast you control enters, you may have it deal 4 damage to
    target opponent or planeswalker." """
    game = _duel(mine=[_POOL["Aether Charge"]], hand=[BEAST])
    assert game.cast_from_hand(0, BEAST.name).supported
    _settle(game)
    assert game.players[1].life == 16, game.log[-4:]


@pytest.mark.cr("109.2", "205.3m", "700.4", "603.2")
def test_rotlung_reanimator_triggers_when_a_kindred_cleric_dies():
    """"Whenever this creature or another Cleric dies, create a 2/2 black
    Zombie creature token." "Dies" is put into a graveyard from the
    battlefield (CR 700.4), which a Kindred Cleric does when it is shattered."""
    game = _duel(mine=[_POOL["Rotlung Reanimator"], CLERIC], hand=[_POOL["Shatter"]])
    idol = _permanent(game, CLERIC.name)
    result = game.cast_from_hand(
        0, "Shatter", target_player_index=0, target_permanent_ids=[idol.permanent_id],
    )
    assert result.supported, result.details
    _settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Rotlung Reanimator", "Zombie Token",
    ], game.log[-4:]


@pytest.mark.cr("109.2", "205.3m")
def test_riptide_director_counts_a_kindred_wizard():
    """"{2}{U}{U}, {T}: Draw a card for each Wizard you control." The Director
    and the Kindred Wizard are two."""
    game = _duel(mine=[_POOL["Riptide Director"], WIZARD, _POOL["Grizzly Bears"]])
    hand = len(game.players[0].hand)
    assert game.queue_permanent_ability(0, "Riptide Director").supported
    _settle(game)
    assert len(game.players[0].hand) == hand + 2, game.log[-3:]


@pytest.mark.cr("109.2", "205.3m", "701.8a")
def test_tivadars_crusade_destroys_a_kindred_goblin():
    """"Destroy all Goblins." The Kindred Goblin goes with the Goblin
    creature, and the Bears stays."""
    game = _duel(hand=[_POOL["Tivadar's Crusade"]],
                 theirs=[GOBLIN, _POOL["Raging Goblin"], _POOL["Grizzly Bears"]])
    assert game.cast_from_hand(0, "Tivadar's Crusade").supported
    _settle(game)
    assert sorted(p.card.name for p in game.all_permanents()) == ["Grizzly Bears"], game.log[-3:]


# --- an Aura ---------------------------------------------------------------


@pytest.mark.cr("109.2", "205.3m", "303.4a")
def test_animate_wall_may_enchant_a_kindred_wall():
    """"Enchant Wall." The clause's gate has always asked ``has_type("wall")``;
    the picker offered creatures alone. Now it offers what the gate takes."""
    game = _duel(hand=[_POOL["Animate Wall"]],
                 mine=[WALL, _POOL["Wall of Stone"], _POOL["Grizzly Bears"]])
    spec = game.cast_target_spec(0, _POOL["Animate Wall"])
    assert _offered(spec) == ["Test Wall Idol", "Wall of Stone"], spec
    idol = _permanent(game, WALL.name)
    result = game.cast_from_hand(
        0, "Animate Wall", target_player_index=0, target_permanent_ids=[idol.permanent_id],
    )
    assert result.supported, result.details
    _settle(game)
    aura = _permanent(game, "Animate Wall")
    assert aura.metadata.get("attached_to") is idol, game.log[-3:]


# --- the AI ------------------------------------------------------------------


@pytest.mark.cr("109.2", "601.2c")
def test_the_ai_casts_tunnel_only_at_an_opponents_wall():
    """``ai_cast_gates._can_cast_with_targets``: "is there something on the
    opponent's board this may destroy?" was asked of a destroy carrying a type
    or a colour; "target Wall" carries neither now, and falling through it
    proposed Tunnel at the caster's own Wall."""
    from engine.ai_cast_gates import _can_cast_with_targets

    own = _duel(hand=[_POOL["Tunnel"]], mine=[WALL])
    assert not _can_cast_with_targets(own, 0, _POOL["Tunnel"])
    theirs = _duel(hand=[_POOL["Tunnel"]], theirs=[WALL])
    assert _can_cast_with_targets(theirs, 0, _POOL["Tunnel"])


# --- "spells that can target only Walls" -------------------------------------


@pytest.mark.cr("303.4a", "115.1", "601.2c")
def test_animate_wall_cannot_enchant_wall_of_shadows():
    """"This creature can't be the target of spells that can target only
    Walls…" (Wall of Shadows). An Aura spell's target is the one its enchant
    ability defines (CR 303.4a), so "Enchant Wall" (Animate Wall) is a spell
    that can target only Walls — read by ``targeting.spec_only_subtype`` off
    the enchant clause's flag. Wall of Stone may still be enchanted."""
    game = _duel(hand=[_POOL["Animate Wall"]],
                 mine=[_POOL["Wall of Shadows"], _POOL["Wall of Stone"]])
    assert _offered(game.cast_target_spec(0, _POOL["Animate Wall"])) == ["Wall of Stone"]
    shadows = _permanent(game, "Wall of Shadows")
    refused = game.cast_from_hand(
        0, "Animate Wall", target_player_index=0, target_permanent_ids=[shadows.permanent_id],
    )
    assert not refused.supported
    stone = _permanent(game, "Wall of Stone")
    result = game.cast_from_hand(
        0, "Animate Wall", target_player_index=0, target_permanent_ids=[stone.permanent_id],
    )
    assert result.supported, result.details


@pytest.mark.cr("700.2", "115.1", "601.2c")
def test_chaos_charm_may_destroy_wall_of_shadows():
    """"Choose one — • Destroy target Wall. • Chaos Charm deals 1 damage to
    target creature. • …" A modal spell that can target a non-Wall in one of
    its modes is not a spell that can target only Walls, even in its Wall mode
    (Scryfall ruling on Wall of Shadows, 2004-10-04). Tunnel, which can target
    only Walls, is still refused — the control."""
    game = _duel(hand=[_POOL["Chaos Charm"], _POOL["Tunnel"]],
                 theirs=[_POOL["Wall of Shadows"], _POOL["Wall of Stone"]])
    shadows = _permanent(game, "Wall of Shadows")
    assert _offered(game.cast_target_spec(0, _POOL["Tunnel"])) == ["Wall of Stone"]
    assert _offered(game.cast_target_spec(0, _POOL["Chaos Charm"], mode_index=0)) == [
        "Wall of Shadows", "Wall of Stone",
    ]
    result = game.cast_from_hand(
        0, "Chaos Charm", mode_index=0, target_player_index=1,
        target_permanent_ids=[shadows.permanent_id],
    )
    assert result.supported, result.details
    _settle(game)
    assert not game.is_on_battlefield(shadows), game.log[-3:]

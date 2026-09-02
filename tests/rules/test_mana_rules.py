import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _mk_card(
    name: str,
    mana_cost: str,
    type_line: str,
    oracle_text: str,
    produced_mana: tuple[str, ...] = (),
    colors: tuple[str, ...] = (),
):
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=1.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=produced_mana,
        raw={"name": name, "type_line": type_line},
    )


def _forest() -> CardDefinition:
    return _mk_card("Forest", "", "Basic Land — Forest", "({T}: Add {G}.)", produced_mana=("G",))


def _mountain() -> CardDefinition:
    return _mk_card("Mountain", "", "Basic Land — Mountain", "({T}: Add {R}.)", produced_mana=("R",))


@pytest.mark.cr("601.2h")
def test_strict_mana_blocks_unpaid_cast():
    spell = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )

    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Bolt Test", target_player_index=1)

    assert not result.supported
    assert "insufficient mana" in result.details
    assert len(p1.hand) == 1
    assert p2.life == 20


# ---------------------------------------------------------------------------
# Rule 106.1 — Mana is the resource spent to pay costs
# ---------------------------------------------------------------------------


@pytest.mark.cr("106.1")
def test_106_1_mana_is_spent_to_pay_casting_costs():
    """Mana produced by a land is spent from the pool to pay a spell's cost (106.1)."""
    bolt = _mk_card(
        "Pay Bolt",
        "{R}",
        "Instant",
        "Pay Bolt deals 3 damage to any target.",
        colors=("R",),
    )
    p1 = PlayerState(name="P1", hand=[bolt], battlefield=[Permanent(card=_mountain())])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    game.tap_land_for_mana(0, "Mountain", chosen_color="R")
    assert p1.mana_pool.get("R", 0) == 1

    result = game.cast_from_hand(0, "Pay Bolt", target_player_index=1)

    assert result.supported
    assert p2.life == 17
    assert p1.mana_pool.get("R", 0) == 0  # the mana was spent


@pytest.mark.cr("106.1b")
def test_106_1b_colorless_is_a_mana_type_distinct_from_the_five_colors():
    """Colorless mana ({C}) is one of the six mana types, tracked separately
    from the five colors (106.1b)."""
    sol_ring = _mk_card("Sol Ring", "{1}", "Artifact", "{T}: Add {C}{C}.", produced_mana=("C",))
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=sol_ring)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Sol Ring")

    assert result.supported
    assert p1.mana_pool.get("C", 0) == 2
    for colored in ("W", "U", "B", "R", "G"):
        assert p1.mana_pool.get(colored, 0) == 0


# ---------------------------------------------------------------------------
# Rule 106.3 — Mana is produced by mana abilities, and also by spells
# ---------------------------------------------------------------------------


@pytest.mark.cr("106.3")
def test_106_3_mana_ability_of_a_land_produces_mana():
    """Tapping a land activates its mana ability and produces mana (106.3/605)."""
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=_forest())])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.tap_land_for_mana(0, "Forest")

    assert p1.mana_pool.get("G", 0) == 1


@pytest.mark.cr("106.3")
def test_106_3_spell_can_also_produce_mana():
    """Mana may also be produced by the effect of a spell — a Dark Ritual-style
    instant adds mana when it resolves (106.3)."""
    ritual = _mk_card("Dark Ritual", "{B}", "Instant", "Add {B}{B}{B}.", colors=("B",))
    p1 = PlayerState(name="P1", hand=[ritual])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Dark Ritual")
    game.resolve_top_of_stack()

    assert p1.mana_pool.get("B", 0) == 3


# ---------------------------------------------------------------------------
# Rule 106.4 — Added mana goes to the pool; pools empty at end of step/phase
# ---------------------------------------------------------------------------


@pytest.mark.cr("106.4")
def test_106_4_added_mana_goes_to_the_pool_and_stays_unspent():
    """Added mana goes into the producing player's mana pool, where it can stay
    as unspent mana across further actions in the same step (106.4)."""
    forests = [Permanent(card=_forest()), Permanent(card=_forest())]
    p1 = PlayerState(name="P1", battlefield=forests)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(0, "Forest", permanent_index=0)
    assert p1.mana_pool.get("G", 0) == 1  # not spent, not lost

    game.tap_land_for_mana(0, "Forest", permanent_index=1)
    assert p1.mana_pool.get("G", 0) == 2  # unspent mana accumulated


@pytest.mark.cr("106.4")
def test_106_4_every_players_pool_empties_when_the_step_ends():
    """Each player's mana pool empties at the end of each step — mana floated
    during the end step is lost when the step closes (106.4)."""
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=_forest())])
    p2 = PlayerState(name="P2", mana_pool={"U": 2})
    game = Game(players=[p1, p2])

    game.resolve_end_step(0)
    game.tap_land_for_mana(0, "Forest")
    assert p1.mana_pool.get("G", 0) == 1
    assert p2.mana_pool.get("U", 0) == 2

    game.close_end_step()

    assert all(amount == 0 for amount in p1.mana_pool.values())
    assert all(amount == 0 for amount in p2.mana_pool.values())


@pytest.mark.cr("106.4")
def test_106_4_pool_empties_at_the_end_of_the_untap_step_too():
    """The pool empties at the end of *each* step, including steps without a
    priority window such as the untap step (106.4)."""
    p1 = PlayerState(name="P1", mana_pool={"W": 2})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_untap_step(0)

    assert all(amount == 0 for amount in p1.mana_pool.values())


# ---------------------------------------------------------------------------
# Rule 106.12 — "Tap for mana" = activate a {T} mana ability of the permanent
# ---------------------------------------------------------------------------


@pytest.mark.cr("106.12")
def test_106_12_tapping_for_mana_taps_the_permanent_and_adds_mana():
    """Tapping a land for mana activates its {T} mana ability: the permanent
    becomes tapped and the mana is added; an already-tapped permanent cannot be
    tapped for mana again (106.12)."""
    forest_perm = Permanent(card=_forest())
    p1 = PlayerState(name="P1", battlefield=[forest_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.tap_land_for_mana(0, "Forest")
    assert forest_perm.tapped is True
    assert p1.mana_pool.get("G", 0) == 1

    # The tapped land cannot pay the {T} cost again.
    assert not game.tap_land_for_mana(0, "Forest")
    assert p1.mana_pool.get("G", 0) == 1


@pytest.mark.cr("106.12a")
def test_106_12a_is_tapped_for_mana_trigger_fires_when_mana_is_produced():
    """A "whenever a player taps a land for mana" ability triggers when such a
    mana ability produces mana (106.12a) — Manabarbs damages the tapping player."""
    manabarbs = _mk_card(
        "Manabarbs",
        "{3}{R}",
        "Enchantment",
        "Whenever a player taps a land for mana, Manabarbs deals 1 damage to that player.",
        colors=("R",),
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=_forest())], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=manabarbs)], life=20)
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(0, "Forest")

    assert p1.mana_pool.get("G", 0) == 1  # the mana was still produced
    assert p1.life == 19  # the trigger fired at the tapping player
    assert p2.life == 20


# ---------------------------------------------------------------------------
# Rule 605.4 — Triggered mana abilities
# ---------------------------------------------------------------------------


@pytest.mark.cr("605.4")
def test_605_4_triggered_mana_ability_adds_its_mana_when_the_trigger_occurs():
    """A Wild Growth-style triggered mana ability (605.1b: triggers from a mana
    ability resolving, adds mana) produces its additional mana when the enchanted
    land is tapped for mana (605.4)."""
    wild_growth = _mk_card(
        "Wild Growth",
        "{G}",
        "Enchantment — Aura",
        "Enchant land\nWhenever enchanted land is tapped for mana, "
        "its controller adds an additional {G}.",
        colors=("G",),
    )
    land_perm = Permanent(card=_forest())
    aura_perm = Permanent(card=wild_growth)
    land_perm.metadata["attached_aura"] = aura_perm
    p1 = PlayerState(name="P1", battlefield=[land_perm, aura_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(0, "Forest")

    # {G} from the Forest plus the additional {G} from Wild Growth.
    assert p1.mana_pool.get("G", 0) == 2


@pytest.mark.cr("605.4a")
def test_605_4a_triggered_mana_ability_does_not_use_the_stack():
    """A triggered mana ability doesn't go on the stack — it resolves immediately
    after the mana ability that triggered it, without waiting for priority (605.4a)."""
    wild_growth = _mk_card(
        "Wild Growth",
        "{G}",
        "Enchantment — Aura",
        "Enchant land\nWhenever enchanted land is tapped for mana, "
        "its controller adds an additional {G}.",
        colors=("G",),
    )
    land_perm = Permanent(card=_forest())
    aura_perm = Permanent(card=wild_growth)
    land_perm.metadata["attached_aura"] = aura_perm
    p1 = PlayerState(name="P1", battlefield=[land_perm, aura_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(0, "Forest")

    # Both the land's mana and the triggered mana arrived with nothing on
    # the stack and no priority round.
    assert len(game.stack) == 0
    assert p1.mana_pool.get("G", 0) == 2


@pytest.mark.cr("605.1b", "605.4a")
def test_605_1b_mana_flare_is_a_triggered_mana_ability():
    """"Whenever a player taps a land for mana, that player adds one mana of any
    type that land produced." All three of 605.1b's criteria hold — no target,
    it triggers from an activated mana ability, and it could add mana — so it is
    a mana ability and never uses the stack (605.4a).

    Its mana is one more of whatever the land just produced, so the type is read
    from the event rather than written on the card.
    """
    mana_flare = _mk_card(
        "Mana Flare", "{2}{R}", "Enchantment",
        "Whenever a player taps a land for mana, that player adds one mana of "
        "any type that land produced.",
        colors=("R",),
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mana_flare)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_mountain())])
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(1, "Mountain")

    assert game.stack == []
    # The mana goes to "that player" — the one who tapped the land, not the
    # enchantment's controller.
    assert p2.mana_pool.get("R", 0) == 2
    assert p1.mana_pool.get("R", 0) == 0


@pytest.mark.cr("605.1b", "605.4a")
def test_605_1b_gauntlet_of_might_adds_its_mana_only_for_the_named_land_type():
    """"Whenever a Mountain is tapped for mana, its controller adds an
    additional {R}." Also a mana ability by 605.1b, so also inline — but its
    trigger condition names a land type, and a land that is not one must not
    trigger it."""
    gauntlet = _mk_card(
        "Gauntlet of Might", "{4}", "Artifact",
        "Red creatures get +1/+1.\nWhenever a Mountain is tapped for mana, "
        "its controller adds an additional {R}.",
    )
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=gauntlet),
            Permanent(card=_mountain()),
            Permanent(card=_forest()),
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(0, "Mountain")
    game.tap_land_for_mana(0, "Forest")

    assert game.stack == []
    assert p1.mana_pool.get("R", 0) == 2   # {R} from the Mountain plus the extra
    assert p1.mana_pool.get("G", 0) == 1   # the Forest is not a Mountain


# ---------------------------------------------------------------------------
# Rule 605.5a — a trigger on an event other than a mana ability, or one that
# cannot add mana, is NOT a mana ability
# ---------------------------------------------------------------------------


@pytest.mark.cr("605.5a", "603.3")
def test_605_5a_a_becomes_tapped_life_trigger_uses_the_stack():
    """Lifetap's shape: "Whenever a Forest an opponent controls becomes tapped,
    you gain 1 life."

    It fails 605.1b twice over — it triggers on *becoming tapped* rather than on
    a mana ability, and it could never add mana — so 605.5a puts it under the
    normal rules for triggered abilities: it goes on the stack (603.3) and its
    life arrives only when it resolves.

    That distinction is the whole point of testing it beside Mana Flare: the two
    fire from the same tap and must not share a resolution model.
    """
    lifetap = _mk_card(
        "Lifetap", "{1}{G}", "Enchantment",
        "Whenever a Forest an opponent controls becomes tapped, you gain 1 life.",
        colors=("G",),
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifetap)], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_forest())], life=20)
    game = Game(players=[p1, p2])

    game.tap_land_for_mana(1, "Forest")

    assert len(game.stack) == 1, "a non-mana trigger must wait on the stack"
    assert p1.life == 20

    game.resolve_stack()

    assert p1.life == 21


# ---------------------------------------------------------------------------
# Rule 605.5 — Spells are never mana abilities
# ---------------------------------------------------------------------------


@pytest.mark.cr("605.5", "605.5b")
def test_605_5b_mana_producing_spell_uses_the_stack_like_any_other_spell():
    """A spell can never be a mana ability, even one that only adds mana — it is
    cast, goes on the stack, and produces nothing until it resolves (605.5b)."""
    ritual = _mk_card("Dark Ritual", "{B}", "Instant", "Add {B}{B}{B}.", colors=("B",))
    p1 = PlayerState(name="P1", hand=[ritual])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Dark Ritual")

    # Unlike a mana ability, the spell waits on the stack with no mana added yet.
    assert result.supported
    assert len(game.stack) == 1
    assert p1.mana_pool.get("B", 0) == 0

    game.resolve_top_of_stack()

    assert len(game.stack) == 0
    assert p1.mana_pool.get("B", 0) == 3




@pytest.mark.cr("608.2d", "106.4")
def test_an_or_mana_line_adds_only_the_chosen_alternative():
    """"Add {B} or {R}" offers a choice while the ability resolves (CR 608.2d);
    the chosen mana — and only it — reaches the pool (CR 106.4). The parse used
    to fold the "or" away, leaving the same pips as "Add {B}{R}", whose handler
    adds *everything listed* — two mana off a line that makes one."""
    prism = _mk_card("Test Prism", "{2}", "Artifact", "{T}: Add {B} or {R}.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prism)])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)

    game.activate_permanent_ability(0, "Test Prism", permanent_index=0, mana_color="R")

    assert p1.mana_pool.get("R", 0) == 1
    assert p1.mana_pool.get("B", 0) == 0
    assert sum(p1.mana_pool.values()) == 1, "one mana, never both alternatives"


@pytest.mark.cr("608.2d")
def test_an_or_mana_line_defaults_to_one_printed_alternative():
    """With no colour chosen (a non-interactive caller), the handler still adds
    exactly one mana, from the printed alternatives — and an off-list request
    is held to the list rather than minting a colour the card cannot make."""
    prism = _mk_card("Test Prism", "{2}", "Artifact", "{T}: Add {B} or {R}.")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=prism)])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)

    game.activate_permanent_ability(0, "Test Prism", permanent_index=0, mana_color="G")

    assert p1.mana_pool.get("G", 0) == 0, "not an alternative the line prints"
    assert sum(p1.mana_pool.values()) == 1


# ---------------------------------------------------------------------------
# 106.6 — mana produced with a restriction on how it may be spent
#
# "Spend this mana only to cast creature spells." (Metamorphosis.) "…only to
# cast an instant or sorcery spell." (Vodalian Arcanist.) The restriction is a
# property of the mana, not of the permanent that made it, so it has to survive
# in the pool until the mana is spent or lost.
# ---------------------------------------------------------------------------

@pytest.mark.cr("106.6")
def test_106_6b_restricted_mana_is_held_apart_from_the_general_pool():
    """Mana produced with a spending restriction is tracked as restricted.

    It is not simply added to the pool: the pool cannot say what its mana may
    pay for, and the restriction must outlive the ability that made it.
    """
    from engine.restricted_mana import (CAST, PaymentPurpose,
                                        mana_restriction_for, restriction_admits)

    restriction = mana_restriction_for("Spend this mana only to cast creature spells.")

    assert restriction is not None
    assert restriction.key == "creature"
    bear = _mk_card("Bear", "{G}", "Creature — Bear", "")
    assert restriction_admits("creature", PaymentPurpose(CAST, card=bear)) is True


@pytest.mark.cr("106.6")
def test_106_6b_the_restriction_admits_only_what_it_names():
    """The restriction is a predicate over the **payment**, so mana marked for
    creature spells cannot pay for an instant, and vice versa.

    And a payment that is not a cast at all is admitted by neither: an
    activated ability is not a spell (CR 602.1), so "only to cast creature
    spells" cannot pay to activate one however creature-ish its source.
    """
    from engine.restricted_mana import (ACTIVATE, CAST, PaymentPurpose,
                                        restriction_admits)

    bear = _mk_card("Bear", "{G}", "Creature — Bear", "")
    bolt = _mk_card("Bolt", "{R}", "Instant", "")

    assert restriction_admits("creature", PaymentPurpose(CAST, card=bear)) is True
    assert restriction_admits("creature", PaymentPurpose(CAST, card=bolt)) is False
    assert restriction_admits("instant_or_sorcery", PaymentPurpose(CAST, card=bolt)) is True
    assert restriction_admits("instant_or_sorcery", PaymentPurpose(CAST, card=bear)) is False
    assert restriction_admits("creature", PaymentPurpose(ACTIVATE, source=bear)) is False
    assert restriction_admits("creature", None) is False


@pytest.mark.cr("106.6")
def test_106_6b_two_restrictions_are_two_separate_buckets():
    """Each restriction keeps its own bucket: one kind of restricted mana must
    never pay for what another kind admits, which a single flag could not
    express."""
    player = PlayerState(name="P1")

    player.restricted_mana.setdefault("creature", {})["G"] = 2
    player.restricted_mana.setdefault("instant_or_sorcery", {})["U"] = 1

    assert player.restricted_mana["creature"] == {"G": 2}
    assert player.restricted_mana["instant_or_sorcery"] == {"U": 1}
    assert player.mana_pool["G"] == 0  # not in the general pool


@pytest.mark.cr("106.6")
def test_106_6b_a_printed_card_declares_its_restriction(set_pool):
    """The engine reads the restriction off the printed sentence, so the card
    that prints it needs no registration — Vodalian Arcanist's mana is marked
    for instants and sorceries by its own text."""
    from engine.restricted_mana import mana_restriction_for

    arcanist = set_pool("M21")["Vodalian Arcanist"]
    restriction = next(
        (r for r in (mana_restriction_for(s) for s in arcanist.oracle_text.split(". ")) if r),
        None,
    )

    assert restriction is not None
    assert restriction.key == "instant_or_sorcery"


# ---------------------------------------------------------------------------
# CR 609.4 — "you may spend mana as though it were mana of any type"
# ---------------------------------------------------------------------------


def _fungible_game():
    from engine import Game, PlayerState

    player = PlayerState(name="P1")
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = True
    return game, player


@pytest.mark.cr("609.4", "106.1b")
def test_609_4_any_type_covers_colorless_where_any_color_does_not():
    """The two permissions differ in exactly one place, and it is the place a
    cost error would hide: a {C} in the cost. "Any **color**" is CR 106.1b's
    five, so a coloured mana cannot pay a {C}; "any **type**" adds colorless as
    the sixth, so it can. Reading the narrower word as the wider one makes a
    spell castable that is not."""
    game, player = _fungible_game()

    player.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 2, "G": 0, "C": 0}
    assert not game._pay_with_fungible_colors(
        player, {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "generic": 1}
    )
    assert player.mana_pool["R"] == 2, "a refused payment spends nothing"

    assert game._pay_with_fungible_types(
        player, {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "generic": 1}
    )
    assert sum(player.mana_pool.values()) == 0


@pytest.mark.cr("609.4")
def test_609_4_an_as_though_permission_does_not_create_mana():
    """"As though" applies only to the stated effect: it changes which pips a
    unit of mana may pay, never how many units there are."""
    game, player = _fungible_game()
    player.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0}

    assert not game._pay_with_fungible_types(
        player, {"W": 1, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    )
    assert player.mana_pool["R"] == 1


@pytest.mark.cr("106.6")
def test_106_6_a_restriction_narrows_a_payment_not_only_a_cast():
    """CR 106.6 restricts "how that mana can be spent" — not which spell it may
    be spent on. Every clause the pool printed until Ice Age happened to name a
    cast, so the predicate took the card being cast and only the casting path
    ever asked. Two Ice Age cards name a payment that is not a cast at all.

    Asked of the table rather than of a card, because the property is about the
    purposes and a card can only demonstrate the one it prints.
    """
    from engine.restricted_mana import (ACTIVATE, CAST, CUMULATIVE_UPKEEP,
                                        PaymentPurpose, mana_restriction_for,
                                        restriction_admits)

    upkeep = mana_restriction_for("Spend this mana only to pay cumulative upkeep costs.")
    ability = mana_restriction_for("Spend this mana only to activate abilities of artifacts.")
    assert upkeep is not None and ability is not None

    artifact = _mk_card("Cog", "{1}", "Artifact", "")
    bear = _mk_card("Bear", "{G}", "Creature — Bear", "")

    assert restriction_admits(upkeep.key, PaymentPurpose(CUMULATIVE_UPKEEP)) is True
    assert restriction_admits(upkeep.key, PaymentPurpose(CAST, card=bear)) is False
    assert restriction_admits(
        upkeep.key, PaymentPurpose(ACTIVATE, source=artifact)
    ) is False

    assert restriction_admits(
        ability.key, PaymentPurpose(ACTIVATE, source=artifact)
    ) is True
    assert restriction_admits(
        ability.key, PaymentPurpose(ACTIVATE, source=bear)
    ) is False
    # "…only to **activate** abilities of artifacts" is not "…to cast artifact
    # spells": the two Ice Age clauses and Mishra’s Workshop’s are three
    # different narrowings that a cast-only predicate could not have told apart.
    assert restriction_admits(
        ability.key, PaymentPurpose(CAST, card=artifact)
    ) is False
    assert restriction_admits(
        "artifact", PaymentPurpose(ACTIVATE, source=artifact)
    ) is False


# --- W2G5: what the inline land-tap fire site may resolve ---


def _w2g5_land_tap_watcher(text: str) -> CardDefinition:
    """An invented permanent whose one line watches lands being tapped for mana.
    Invented rather than named, because what is under test is which *effects*
    the fire site may carry out — a question about the site, not about a card."""
    return CardDefinition(
        name="W2G5 Land Watcher", mana_cost="{2}{R}", cmc=3.0,
        type_line="Enchantment", oracle_text=text, colors=("R",),
        color_identity=("R",), keywords=(), produced_mana=(), raw={},
    )


@pytest.mark.cr("605.4a")
def test_the_land_tap_site_resolves_damage_and_skips_what_it_cannot():
    """CR 605.4a keeps a triggered mana ability off the stack, so this event is
    resolved inline — inside a cost payment (CR 601.2g), where there is no
    priority window to give a non-mana effect.

    The arm that carries out Manabarbs' damage used to be the loop's ``else``:
    any instruction kind it did not recognize was read for an ``amount`` and
    dealt as damage, defaulting to 1. A trigger on this event whose effect is a
    *draw* therefore dealt a point of damage — silently, on a card reporting
    itself supported. The kind is now named, and anything else is skipped with a
    line in the log."""
    from engine.oracle import compile_card_oracle

    burn = _w2g5_land_tap_watcher(
        "Whenever a player taps a Mountain for mana, "
        "this enchantment deals 2 damage to that player."
    )
    draw = _w2g5_land_tap_watcher(
        "Whenever a player taps a Mountain for mana, that player draws a card."
    )
    assert compile_card_oracle(burn).supported
    assert compile_card_oracle(draw).supported, (
        "both lower; the difference is what the fire site can perform"
    )

    for card, expected_life, expected_hand in ((burn, 18, 0), (draw, 20, 0)):
        game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
        game.enforce_mana_costs = False
        game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
        mountain = CardDefinition(
            name="Mountain", mana_cost="", cmc=0.0, type_line="Basic Land — Mountain",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=("R",), raw={},
        )
        game._put_permanent_onto_battlefield(0, Permanent(card=mountain), None)
        game.players[0].library = [mountain]

        assert game.tap_land_for_mana(0, "Mountain")

        assert game.players[0].life == expected_life
        assert len(game.players[0].hand) == expected_hand, (
            "the draw is skipped, not turned into damage"
        )

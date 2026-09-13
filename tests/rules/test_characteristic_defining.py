"""Tests for Magic: The Gathering Comprehensive Rules Section 604.

Covers:
  604.3 — Characteristic-defining abilities

Every one of these was a literal containing the card's own name, in two places:
a whitelist entry gating support and an `elif` emitting a per-card instruction
kind. They are one template with a parameter, so these tests use invented cards
throughout — a test naming only Nightmare, Keldon Warlord, Plague Rats and
Gaea's Liege would pass against the version that hardcoded exactly those four.
"""

import pytest

from engine import Game, PlayerState
from engine.characteristic_defining import dynamic_pt_for
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, normalize_creature_line


def _cda_card(name: str, text: str, type_line: str = "Creature — Horror") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}{B}", cmc=3.0, type_line=type_line,
        oracle_text=text, colors=("B",), color_identity=("B",),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "*", "toughness": "*"},
    )


@pytest.mark.cr("604.3")
def test_604_3_land_count_pt_is_recognized_whatever_the_card_is_called():
    """"<name>'s power and toughness are each equal to the number of Swamps you
    control" was whitelisted as a literal *including the card's own name*, which
    `normalize_creature_line` does not replace. Every reprint and every
    functionally identical card would have needed its own whitelist line, and
    until it got one the card compiled as unsupported."""
    from engine.characteristic_defining import dynamic_pt_for

    for name, land in (("nightmare", "swamp"), ("volcano horror", "mountain"),
                       ("some other creature", "forest")):
        line = (f"{name}'s power and toughness are each equal to "
                f"the number of {land}s you control")
        found = dynamic_pt_for(line)

        assert found is not None, line
        assert found.kind == "dynamic_pt_count"
        assert found.payload == {"count": "land", "land_type": land, "scope": "you"}


@pytest.mark.cr("604.3")
def test_604_3_the_counted_land_type_comes_from_the_text():
    """The type is data, not part of the instruction kind. One kind and one
    counter serve every basic type, so a card printed with a new one needs no
    code at all — where before it needed a whitelist line, an `elif` branch and
    a counter-registry entry."""
    from engine.card_loader import load_catalog
    from engine.models import CardDefinition

    catalog = {c.name: c for c in load_catalog()}
    variant = CardDefinition(
        name="Volcano Horror", mana_cost="{5}{R}", cmc=6.0,
        type_line="Creature — Horror",
        oracle_text=("Flying\nVolcano Horror's power and toughness are each equal "
                     "to the number of Mountains you control."),
        colors=("R",), color_identity=("R",), keywords=("Flying",), produced_mana=(),
        raw={"name": "Volcano Horror", "type_line": "Creature — Horror",
             "power": "*", "toughness": "*"},
    )
    horror = Permanent(card=variant)
    player = PlayerState(
        name="P1",
        battlefield=[horror] + [Permanent(card=catalog["Mountain"]) for _ in range(4)],
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game._refresh_dynamic_creatures()

    assert (horror.effective_power, horror.effective_toughness) == (4, 4)


@pytest.mark.cr("604.3")
def test_604_3_creature_count_with_a_type_exclusion_is_name_agnostic():
    """Keldon Warlord's "number of non-Wall creatures you control"."""
    line = normalize_creature_line(
        "Some Other Warlord's power and toughness are each equal to "
        "the number of non-Wall creatures you control."
    )
    found = dynamic_pt_for(line)
    assert found is not None
    assert found.payload == {"count": "creature", "scope": "you", "exclude_type": "wall"}


@pytest.mark.cr("604.3")
def test_604_3_the_excluded_creature_type_is_read_from_the_text():
    """"non-Wall" is data. The old branch matched the literal string
    "non-wall creatures", so the same template excluding any other type
    produced no instruction."""
    for excluded in ("wall", "goblin", "djinn"):
        line = normalize_creature_line(
            f"Probe's power and toughness are each equal to "
            f"the number of non-{excluded} creatures you control."
        )
        found = dynamic_pt_for(line)
        assert found is not None, excluded
        assert found.payload["exclude_type"] == excluded


@pytest.mark.cr("604.3")
def test_604_3_creature_count_excludes_by_layer_4_type_not_the_printed_line():
    """An animated land is a creature (CR 613.1d), so it counts toward "the
    number of non-Wall creatures you control". The replaced counter tested
    `card.primary_type == "creature"` against the printed line, which no
    animation ever updates — it would have counted 1 here, not 2."""
    from engine.card_loader import load_catalog

    catalog = {c.name: c for c in load_catalog()}
    warlord = Permanent(card=_cda_card(
        "Probe Warlord",
        "Probe Warlord's power and toughness are each equal to "
        "the number of non-Wall creatures you control.",
    ))
    swamp = Permanent(card=catalog["Swamp"])
    player = PlayerState(name="P1", battlefield=[warlord, swamp])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game._refresh_dynamic_creatures()
    assert swamp.is_creature is False
    assert warlord.effective_power == 1          # only itself

    # Kormus Bell: "All Swamps are 1/1 black creatures that are still lands."
    player.battlefield.append(Permanent(card=catalog["Kormus Bell"]))
    game._refresh_dynamic_creatures()
    assert swamp.is_creature is True
    assert warlord.effective_power == 2          # itself + the animated Swamp


@pytest.mark.cr("604.3")
def test_604_3_same_name_count_uses_the_cards_own_name():
    """Plague Rats. The old branch matched the literal "creatures named plague
    rats", so any other card with this template — the whole Relentless Rats
    family — produced nothing."""
    for name in ("Plague Rats", "Relentless Rats", "Rat Colony"):
        line = normalize_creature_line(
            f"{name}'s power and toughness are each equal to the number of "
            f"creatures named {name} on the battlefield."
        )
        found = dynamic_pt_for(line)
        assert found is not None, name
        assert found.payload == {"count": "same_name", "scope": "all"}


@pytest.mark.cr("604.3")
def test_604_3_counting_a_different_cards_name_is_refused():
    """"Creatures named X" only means "named like me" when X is the subject.
    The counter works from the permanent it refreshes, so a card counting some
    *other* name would silently count the wrong creatures — it must be reported
    unsupported instead."""
    line = normalize_creature_line(
        "Impostor Rats's power and toughness are each equal to the number of "
        "creatures named Plague Rats on the battlefield."
    )
    assert dynamic_pt_for(line) is None


@pytest.mark.cr("604.3")
def test_604_3_same_name_counts_across_both_battlefields():
    card = _cda_card(
        "Probe Rats",
        "Probe Rats's power and toughness are each equal to the number of "
        "creatures named Probe Rats on the battlefield.",
    )
    mine, theirs = Permanent(card=card), Permanent(card=card)
    p1 = PlayerState(name="P1", battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()

    assert (mine.effective_power, mine.effective_toughness) == (2, 2)


@pytest.mark.cr("604.3")
def test_604_3_attacking_split_land_count_is_name_and_type_agnostic():
    """Gaea's Liege: two clauses on one line, the second counting the
    *defending* player's lands. Gated by a `startswith` on the card's name."""
    line = normalize_creature_line(
        "As long as Probe Liege isn't attacking, its power and toughness are each "
        "equal to the number of Islands you control. As long as Probe Liege is "
        "attacking, its power and toughness are each equal to the number of "
        "Islands defending player controls."
    )
    found = dynamic_pt_for(line)
    assert found is not None
    assert found.payload == {
        "count": "land", "land_type": "island", "scope": "defender_when_attacking",
    }


@pytest.mark.cr("604.3")
def test_604_3_the_attacking_split_counts_the_right_players_lands():
    from engine.card_loader import load_catalog

    catalog = {c.name: c for c in load_catalog()}
    liege = Permanent(card=_cda_card(
        "Probe Liege",
        "As long as Probe Liege isn't attacking, its power and toughness are each "
        "equal to the number of Islands you control. As long as Probe Liege is "
        "attacking, its power and toughness are each equal to the number of "
        "Islands defending player controls.",
    ))
    p1 = PlayerState(name="P1", battlefield=[liege] + [Permanent(card=catalog["Island"])])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Island"]) for _ in range(3)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game._refresh_dynamic_creatures()
    assert liege.effective_power == 1          # its controller's one Island

    liege.attacking = True
    liege.defending_player_index = 1
    game._refresh_dynamic_creatures()
    assert liege.effective_power == 3          # the defender's three Islands


# ---------------------------------------------------------------------------
# The unnarrowed count: "the number of **lands** you control" (round 21)
# ---------------------------------------------------------------------------


@pytest.mark.cr("604.3")
def test_604_3_an_unnarrowed_land_count_names_the_card_type_not_a_subtype():
    """"…equal to the number of lands you control" (Dakkon Blackblade).

    The head noun is the card type, so the payload carries no ``land_type`` at
    all — an absent key is the counter's "no restriction", the same reading
    every other omitted parameter here gets. Read through the basic-type
    alternation the sentence matched nothing and the card compiled unsupported.
    """
    for name in ("dakkon blackblade", "some other warlord"):
        line = f"{name}'s power and toughness are each equal to the number of lands you control"
        found = dynamic_pt_for(line)

        assert found is not None, line
        assert found.payload == {"count": "land", "scope": "you"}


@pytest.mark.cr("604.3", "613.1d")
def test_604_3_an_unnarrowed_land_count_counts_every_land_and_only_lands(catalog_by_name):
    """Counted through ``has_type`` like the narrowed form beside it, so an
    artifact land would count and a Mox would not — and the opponent's lands
    never do, because "you control" is on the payload."""
    variant = _cda_card(
        "Invented Blade",
        "Invented Blade's power and toughness are each equal to "
        "the number of lands you control.",
    )
    blade = Permanent(card=variant)
    mine = [Permanent(card=catalog_by_name[name]) for name in ("Mountain", "Island", "Swamp")]
    player = PlayerState(name="P1", battlefield=[blade] + mine)
    opponent = PlayerState(
        name="P2", battlefield=[Permanent(card=catalog_by_name["Forest"])],
    )
    game = Game(players=[player, opponent])
    game._refresh_dynamic_creatures()
    assert (blade.effective_power, blade.effective_toughness) == (3, 3)

    # A non-land permanent contributes nothing…
    player.battlefield.append(Permanent(card=catalog_by_name["Black Lotus"]))
    game._refresh_dynamic_creatures()
    assert blade.effective_power == 3

    # …and the count is recomputed continuously (CR 604.3).
    game.remove_from_battlefield(mine[0])
    game._refresh_dynamic_creatures()
    assert (blade.effective_power, blade.effective_toughness) == (2, 2)


# --- W1G2: a CDA whose counted set is an ordinary printed noun phrase ---

@pytest.mark.cr("604.3", "613.4a", "403.1")
def test_604_3_a_counted_cda_reads_its_noun_phrase_through_the_noun_parser():
    """"<name>'s power and toughness are each equal to **N plus the number of
    <noun phrase>**."

    Fifteen rows of this table each spell their counted set into the pattern —
    a land type, a card type, a creature name — which is one row per printed
    noun. The general row hands the phrase to the noun parser instead, so a
    colour, a union of two creature types and CR 403.1's shared battlefield
    cost no code at all.

    Invented cards throughout, for this file's own stated reason: a test naming
    An-Havva Constable and Aysen Crusader would pass against a version that
    hardcoded exactly those two.
    """
    for text, expected in (
        ("its power and toughness are each equal to 1 plus the number of "
         "green creatures on the battlefield",
         {"zone": "battlefield", "owner": "all",
          "filter": {"type_filter": "creature", "color_filter": "G"},
          "offset": 1}),
        ("its power and toughness are each equal to 3 plus the number of "
         "soldiers and warriors you control",
         {"zone": "battlefield", "owner": "you",
          "filter": {"type_filter": "creature",
                     "subtype_filter": ["soldier", "warrior"]},
          "offset": 3}),
        ("its power and toughness are each equal to 2 plus the number of "
         "black creatures you control",
         {"zone": "battlefield", "owner": "you",
          "filter": {"type_filter": "creature", "color_filter": "B"},
          "offset": 2}),
    ):
        found = dynamic_pt_for(text.replace("its", "some creature's", 1))
        assert found is not None, text
        assert found.payload == {"count_spec": expected}, text


@pytest.mark.cr("604.3")
def test_604_3_a_counted_cda_defines_only_the_half_the_sentence_names():
    """"…**toughness** is equal to …" leaves the printed power alone, and the
    mirror leaves the printed toughness alone. Which half a CDA defines is part
    of the sentence, so it is payload rather than three templates — and getting
    it wrong is a 2/1+* that reports itself as a 4/4."""
    both = dynamic_pt_for(
        "x's power and toughness are each equal to 1 plus the number of "
        "green creatures on the battlefield"
    )
    toughness = dynamic_pt_for(
        "x's toughness is equal to 1 plus the number of green creatures on "
        "the battlefield"
    )
    power = dynamic_pt_for(
        "x's power is equal to 1 plus the number of green creatures on the "
        "battlefield"
    )

    assert "defines" not in both.payload
    assert toughness.payload["defines"] == "toughness"
    assert power.payload["defines"] == "power"


@pytest.mark.cr("604.3")
def test_604_3_a_counted_cda_refuses_a_noun_phrase_it_cannot_count():
    """The general row ends in a catch-all — ``the number of <anything>`` — so
    it has to read the tail itself and refuse what it cannot.

    A characteristic-defining ability is recomputed continuously, so a payload
    the counter cannot answer is not a card that does less: it is a creature
    whose power and toughness are silently wrong every time anything looks at
    it. Both refusals below are that: a phrase the noun parser does not read,
    and one it reads into a count that cannot be taken.
    """
    # Not a noun phrase this engine reads at all.
    assert dynamic_pt_for(
        "x's power and toughness are each equal to 1 plus the number of "
        "wishes you have made this game"
    ) is None
    # Read, but the count cannot be narrowed to a seat the *event* picked:
    # "that player" is known only to the resolution holding a trigger's
    # context, and a characteristic-defining ability has none — so the key
    # would be handed over and ignored and the count taken on the wrong
    # battlefield.
    assert dynamic_pt_for(
        "x's power and toughness are each equal to 1 plus the number of "
        "creatures that player controls"
    ) is None
    # "…creatures **an opponent controls**" used to be the second refusal here,
    # for the reason above one seat over: nothing tested a ``controller`` key on
    # a count. Chameleon Spirit is the card that made that false — the
    # battlefield scan asks ``subject_matches``, which has always been able to
    # answer "not the observer's", and what was missing was a *scope* saying
    # which piles to read while the observer stayed the counting seat. So the
    # narrowing is **answered** rather than refused, and the assertion that
    # keeps it honest is that both halves survive into the spec: widen the scan
    # without keeping the key and the count is of every permanent in the game.
    opponents = dynamic_pt_for(
        "x's power and toughness are each equal to 1 plus the number of "
        "creatures an opponent controls"
    )
    assert opponents is not None
    spec = opponents.payload["count_spec"]
    assert spec["owner"] == "opponents"
    assert spec["filter"]["controller"] == "opponent"
    # A keyword is CR 613 layer 6, and this used to be the third refusal here:
    # the count asked ``permanent_matches_filter``, the pure half, which would
    # have dropped the adjective and counted every creature. The battlefield
    # scan asks ``subject_matches`` now, so the narrowing is *answered* rather
    # than refused — and the assertion that keeps this honest is that the word
    # survives into the spec, not that the sentence is rejected.
    keyworded = dynamic_pt_for(
        "x's power and toughness are each equal to 1 plus the number of "
        "creatures with flying you control"
    )
    assert keyworded is not None
    assert keyworded.payload["count_spec"]["filter"]["with_keywords"] == ["flying"]


# ---------------------------------------------------------------------------
# CR 208.2 — the printed star, and the two abilities that fill it in
# ---------------------------------------------------------------------------
#
# 604.3 above is about the *ability*; 208.2 is about the **card**, which prints
# a star where a number goes and names exactly two ways that star is answered:
# a characteristic-defining ability (208.2a) or an as-it-enters replacement
# effect (208.2b). Both live in the pool, so both are driven here rather than
# reasoned about.


@pytest.mark.cr("208.2", "208.2a")
def test_208_2a_a_star_printed_creature_reads_its_pt_off_its_cda(catalog_by_name):
    """"Rather than a fixed number, some creature cards have power and/or
    toughness that includes a star (*)" — 208.2a's form, "[power or toughness]
    is equal to …".

    The star is not a number and must never be read as one: Nightmare's printed
    power *is* the string, and every number it ever has comes from the ability.
    Asserted in both directions — the count arriving, and the count moving when
    a Swamp leaves — because a star silently read as 0 and a CDA that computes
    once look identical from a single board.
    """
    nightmare = Permanent(card=catalog_by_name["Nightmare"])
    assert nightmare.card.power == "*"
    assert nightmare.card.toughness == "*"

    swamps = [Permanent(card=catalog_by_name["Swamp"]) for _ in range(3)]
    player = PlayerState(name="P1", battlefield=[nightmare] + swamps)
    game = Game(players=[player, PlayerState(name="P2")])

    game._refresh_dynamic_creatures()
    assert (nightmare.effective_power, nightmare.effective_toughness) == (3, 3)

    game.remove_from_battlefield(swamps[0])
    game._refresh_dynamic_creatures()
    assert (nightmare.effective_power, nightmare.effective_toughness) == (2, 2)


@pytest.mark.cr("208.2", "208.2a")
def test_208_2a_a_star_printed_with_an_addend_is_the_number_plus_the_count(
    catalog_by_name,
):
    """Gaea's Avenger is printed ``1+*``, and the whole thing is the
    characteristic-defining ability's business: 208.2a's "equal to …" is
    "equal to 1 plus the number of artifacts your opponents control", so the 1
    comes out of the *sentence* and not out of the corner of the card.

    Which is why the addend is worth its own test beside the plain star: an
    implementation that read "1+*" as a printed 1 and added the count would
    agree with this on every board, and disagree the moment a card printed a
    different addend. And "your opponents control" is asserted too — a count
    taken on the wrong battlefield is a creature that is silently the wrong
    size every time anything looks at it.
    """
    avenger = Permanent(card=catalog_by_name["Gaea's Avenger"])
    assert avenger.card.power == "1+*"

    mine = PlayerState(name="P1", battlefield=[avenger])
    theirs = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=catalog_by_name["Black Lotus"]),
            Permanent(card=catalog_by_name["Mox Jet"]),
        ],
    )
    game = Game(players=[mine, theirs])

    game._refresh_dynamic_creatures()
    assert (avenger.effective_power, avenger.effective_toughness) == (3, 3)

    theirs.battlefield.append(Permanent(card=catalog_by_name["Mox Ruby"]))
    game._refresh_dynamic_creatures()
    assert (avenger.effective_power, avenger.effective_toughness) == (4, 4)

    mine.battlefield.append(Permanent(card=catalog_by_name["Mox Pearl"]))
    game._refresh_dynamic_creatures()
    assert avenger.effective_power == 4, "an artifact *you* control is not counted"


@pytest.mark.cr("208.2", "208.2a", "208.2b")
def test_208_2_every_star_printed_creature_in_the_pool_is_one_of_the_two_forms():
    """208.2 enumerates the star's answers and there are two of them, so a card
    printing a star and carrying neither is a creature whose power and toughness
    nothing defines — which no other instrument reports, because the compiler
    calls such a card supported on its other lines and the P/T refresh simply
    never reaches it.

    Asked of the whole pool rather than of a list, so a set ingested later is
    swept by construction. Both buckets are asserted non-empty as well: with the
    dichotomy read off the pool, a bug that emptied one of them would otherwise
    turn this into a test of the other.
    """
    from engine.card_loader import load_catalog
    from engine.enter_effects import choosable_bodies

    defining, entering = [], []
    for card in load_catalog():
        if "*" not in f"{card.power or ''}{card.toughness or ''}":
            continue
        kinds = {
            instruction.kind
            for instruction in compile_card_oracle(card).instructions
        }
        if "dynamic_pt_count" in kinds:
            defining.append(card.name)
        elif choosable_bodies(card.oracle_text or ""):
            entering.append(card.name)
        else:
            raise AssertionError(
                f"{card.name} prints {card.power}/{card.toughness} with neither "
                "a characteristic-defining ability (CR 208.2a) nor an "
                "as-it-enters body choice (CR 208.2b) behind it"
            )

    assert defining, "no 208.2a card in the pool — the sweep proves nothing"
    assert entering, "no 208.2b card in the pool — the sweep proves nothing"


@pytest.mark.cr("208.2", "208.2b", "614.1c")
def test_208_2b_a_creature_enters_as_one_of_the_bodies_its_card_lists(
    catalog_by_name,
):
    """"The card may have a static ability that creates a replacement effect
    that sets the creature's power and toughness to one of a number of specific
    values as it enters the battlefield … and may also list additional
    characteristics."

    Primal Clay, the pool's only one. The star is answered on the way in rather
    than continuously, so all three assertions are about the same permanent at
    different moments: the printed star, the body it entered on, and the body
    its controller replaced that with. The default is the *first* body printed
    and not the biggest, because a headless seat has to arrive somewhere and
    picking "best" would be the engine choosing for the player.

    "Additional characteristics" is the half that is easy to drop and quiet when
    dropped: the third body is a 1/6 **Wall** with defender, and a Clay that took
    the numbers without the type would sit there answering "no" to every card in
    the pool that asks about Walls.
    """
    player = PlayerState(name="P1", hand=[catalog_by_name["Primal Clay"]])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    game.queue_from_hand(0, "Primal Clay")
    game.resolve_top_of_stack()
    clay = player.battlefield[-1]

    assert clay.card.power == "*" and clay.card.toughness == "*"
    assert (clay.effective_power, clay.effective_toughness) == (3, 3)
    assert game.pending_choice_of("body_choice", 0) is not None, (
        "two or more listed values is a choice, so it has to be asked"
    )

    assert game.confirm_enter_body_choice(0, 2)
    game._settle()

    assert (clay.effective_power, clay.effective_toughness) == (1, 6)
    assert clay.has_keyword("defender")
    assert clay.has_type("wall")

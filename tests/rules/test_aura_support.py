"""Tests for Magic: The Gathering Comprehensive Rules Section 303.

Covers:
  303.4  — Auras, their enchant ability and the effects they apply

An Aura was classified supported by a single whitelist substring —
"enchant creature" — with nothing ever examining its effect lines. "Enchanted
creature glimmers uncontrollably" compiled as supported. So did an Aura whose
only line was the enchant clause. At 44 Auras in the pool that is 44 cards
whose support status was never actually checked.

engine/auras.py names the effect lines the engine carries out, and the compiler
requires every effect line of an Aura to match one. These tests use invented
Auras throughout: every real Aura in the pool is claimed, so a test built only
from real cards passes against the version that checked nothing.
"""

import pytest

from engine.auras import aura_effect_claim, unclaimed_aura_lines
from engine.card_loader import load_catalog
from engine.models import CardDefinition
from engine.oracle import (compile_card_oracle, expand_ability_lines,
                          normalize_creature_line)


def _aura(text: str, name: str = "Probe Aura") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{W}", cmc=1.0, type_line="Enchantment — Aura",
        oracle_text=text, colors=("W",), color_identity=("W",),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Enchantment — Aura"},
    )


@pytest.mark.cr("303.4")
def test_303_4_an_aura_with_an_unimplemented_effect_is_unsupported():
    """The whole point: "enchant creature" is a targeting restriction, not
    evidence that the Aura's effect is implemented."""
    for text in (
        "Enchant creature\nEnchanted creature glimmers uncontrollably.",
        "Enchant creature\nEnchanted creature has protection from everything.",
        "Enchant land\nEnchanted land produces an additional {G} when tapped.",
        "Enchant artifact\nEnchanted artifact hums a merry tune.",
    ):
        program = compile_card_oracle(_aura(text))
        assert not program.supported, text
        assert "unimplemented aura effect" in program.reason


@pytest.mark.cr("303.4")
def test_303_4_implemented_aura_effects_stay_supported():
    for text in (
        "Enchant creature\nEnchanted creature has flying.",
        "Enchant creature\nEnchanted creature gets +2/+2.",
        "Enchant creature\nEnchanted creature gets -1/-0.",
        "Enchant creature\nEnchanted creature gets +0/+2 and has reach.",
        "Enchant creature\nEnchanted creature has protection from red. "
        "This effect doesn't remove this Aura.",
        "Enchant land\nEnchanted land is a Swamp.",
        "Enchant creature\nYou control enchanted creature.",
    ):
        assert compile_card_oracle(_aura(text)).supported, text


@pytest.mark.cr("303.4")
def test_303_4_a_self_referential_etb_trigger_is_matched_by_the_cards_own_name():
    """Older printings name the card where modern Oracle says "this Aura". The
    subject is checked against the card's actual name — a wildcard subject
    would re-open the hole this table closes."""
    own = ("When Animate Dead enters, if it's on the battlefield, return "
           "enchanted creature card to the battlefield under your control.")
    assert aura_effect_claim(normalize_creature_line(own), "Animate Dead") is not None
    # Same sentence on a card that isn't Animate Dead is not its own ETB
    # trigger, and must not inherit the claim.
    assert aura_effect_claim(normalize_creature_line(own), "Unrelated Aura") is None


@pytest.mark.cr("303.4")
def test_303_4_every_aura_in_the_pool_has_all_its_effect_lines_claimed():
    """The ratchet. Ingesting a set with an Aura whose effect is not
    implemented fails here, naming the line."""
    unclaimed: list[tuple[str, str]] = []
    for card in load_catalog():
        if "aura" not in card.type_line.lower():
            continue
        # **From `expand_ability_lines`, not from the printed text.** That
        # function is where a keyword or a conjoined trigger is rewritten
        # into the lines every other reader is held to, and CLAUDE.md says
        # every reader of a card's lines must start there or it is reading
        # a different card. This one did not, and HML collected on it at the
        # promotion gate: Orcish Mine prints "At the beginning of your
        # upkeep **and** whenever enchanted land becomes tapped, remove an
        # ore counter", which the rewrite splits into the two triggers the
        # claim table implements — so the card works and this guard reported
        # its printed line as implemented by nothing.
        expanded = expand_ability_lines(card.oracle_text)
        lines = [normalize_creature_line(l) for l in expanded.split("\n")]
        for line in unclaimed_aura_lines(lines, card.name):
            unclaimed.append((card.name, line))
    assert not unclaimed, "Aura effect lines nothing implements:\n" + "\n".join(
        f"  {name}: {line}" for name, line in unclaimed
    )


@pytest.mark.cr("303.4")
def test_303_4_the_enchant_line_itself_is_not_an_effect():
    """"Enchant creature" is the targeting restriction (consumed by
    targeting.py), so it must not be mistaken for an implemented effect — an
    Aura carrying nothing else does nothing at all."""
    assert unclaimed_aura_lines(["enchant creature"]) == []
    assert aura_effect_claim("enchant creature") is None


@pytest.mark.cr("303.4")
def test_an_aura_entry_effect_the_engine_cannot_perform_is_not_claimed():
    """The hole the ETB row's `.+$` left open, closed and pinned.

    The claim table's job is to say what *implements* a line. That row matched
    any effect at all after "when this Aura enters", naming a method that
    performs exactly two of them — so an Aura printing an entry effect the
    engine cannot carry out reported **supported** and then did nothing, which
    is the silent direction this whole file exists to refuse.

    Invented sentences on purpose: every real printing either lowers (and is
    claimed by `aura_compiled_trigger_claim`, which asks the compiler) or is one
    of the two bespoke texts, so a test written from the pool alone passes
    against the wildcard.
    """
    for line in (
        "when this aura enters, frobnicate the widget",
        "when this aura enters, each player recites a poem",
        "when this enchantment enters, the sky turns green",
    ):
        assert aura_effect_claim(line, "") is None, (
            f"claimed an entry effect nothing implements: {line!r}"
        )


@pytest.mark.cr("303.4")
def test_the_two_bespoke_entry_texts_are_still_claimed():
    """The other direction: narrowing the row must not drop the two entry
    effects `_apply_aura_effect` really does perform by text matching."""
    animate = (
        "when this aura enters, if it's on the battlefield, return enchanted "
        "creature card to the battlefield under your control"
    )
    earthbind = (
        "when this aura enters, if enchanted creature has flying, this aura "
        "deals 2 damage to that creature"
    )
    assert aura_effect_claim(animate, "") is not None
    assert aura_effect_claim(earthbind, "") is not None
# ---------------------------------------------------------------------------
# CR 303.4j — an Aura moved onto something it can't legally enchant
# ---------------------------------------------------------------------------


def _moving_board(set_pool):
    """A game with one Aura on a creature, plus a land and a second creature."""
    from engine import Game, PlayerState
    from engine.auras import attach_aura
    from engine.models import Permanent

    catalog = {**set_pool("LEA"), **set_pool("LEG")}
    p1 = PlayerState(name="P1", hand=[catalog["Enchantment Alteration"]])
    p2 = PlayerState(name="P2")
    host = Permanent(card=catalog["Grizzly Bears"])
    twin = Permanent(card=catalog["Grizzly Bears"])
    land = Permanent(card=catalog["Forest"])
    aura = Permanent(card=catalog["Holy Strength"])
    p1.battlefield = [host, twin, land, aura]
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    attach_aura(aura, host)
    return game, aura, host, twin, land


@pytest.mark.cr("303.4j")
def test_303_4j_an_aura_is_not_moved_onto_an_illegal_host(set_pool):
    """"Enchant creature" is asked of the *new* host too, so a land is never a
    legal answer — and the refusal is the Aura staying put, not falling off."""
    from engine.auras import aura_attach_refusal

    game, aura, host, twin, land = _moving_board(set_pool)

    assert aura_attach_refusal(game, aura, twin) is None
    assert aura_attach_refusal(game, aura, land) is not None
    assert aura_attach_refusal(game, aura, aura) is not None
    assert aura.metadata["attached_to"] is host


@pytest.mark.cr("608.2d", "117.3b")
def test_608_2d_a_permanent_chosen_on_resolution_holds_the_resolution_open(set_pool):
    """A choice an effect offers is announced while the effect is applied, so
    the object stays on the stack and nobody receives priority until it is
    answered."""
    game, aura, _host, twin, _land = _moving_board(set_pool)
    game.interactive_seats = {0}

    game.cast_from_hand(
        0, "Enchantment Alteration",
        target_player_index=0, target_permanent_ids=[aura.permanent_id],
    )

    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "permanent_choice"
    # Nothing later in the sentence has run: the attach reads the answer, so it
    # waits for one rather than acting on a board the choice has not shaped.
    assert aura.metadata["attached_to"] is not twin

    assert game.confirm_permanent_choice(0, twin.permanent_id)
    assert game.waiting_prompt() is None
    assert aura.metadata["attached_to"] is twin


# ---------------------------------------------------------------------------
# An attached trigger's *condition* is not a claim (round 32)
# ---------------------------------------------------------------------------


@pytest.mark.cr("303.4", "603.10")
def test_303_4_an_attached_death_trigger_needs_more_than_a_parsed_condition():
    """"When enchanted creature dies, <something nothing implements>."

    ``attached_creature_dies`` parses for *every* Aura printing those words, so
    claiming the line on the condition alone admitted any effect clause at all —
    and the one dispatcher keyed on that condition kind then gave every such Aura
    Creature Bond's "damage equal to that creature's toughness". Puppet Master
    dealt it instead of returning a card; the claim asks for an instruction, or
    for the death-damage line itself, now.
    """
    invented = _aura(
        "Enchant creature\n"
        "When enchanted creature dies, its controller yodels uncontrollably."
    )

    program = compile_card_oracle(invented)

    assert not program.supported
    assert "yodels" in program.reason.lower()


@pytest.mark.cr("303.4", "603.10")
def test_303_4_the_death_damage_template_is_still_claimed_and_still_fires():
    """The one attached trigger the engine performs with no instruction behind
    it: the toughness has to be read while the creature is still on the
    battlefield (CR 603.10), so no payload can carry it. It is claimed by its
    printed *line*, which is what the dispatcher reads too."""
    from engine.auras import aura_death_damage_line

    line = normalize_creature_line(
        "When enchanted creature dies, this Aura deals damage equal to that "
        "creature's toughness to the creature's controller."
    )

    assert aura_death_damage_line(line)
    assert compile_card_oracle(
        _aura("Enchant creature\n" + line, name="Probe Bond")
    ).supported


@pytest.mark.cr("702.5a", "303.4")
def test_702_5a_an_enchant_clause_nobody_reads_leaves_its_aura_unsupported():
    """CR 702.5a's enchant ability "restricts what an Aura spell can target and
    what an Aura can enchant" — so a clause no reader implements is not a
    narrower Aura, it is an Aura with neither restriction.

    This gate asked ``line.startswith("enchant ")``, which claimed every
    subject there could be. Roots' "Enchant creature **without flying**" got
    through it, derived no cast picker (the card was uncastable) and fell
    through ``permanent_matches_enchant_noun``'s permissive fallback (the
    exclusion unenforced) — one line, two contradictory failures, and a green
    suite. Invented subjects, because every subject the pool prints is read.
    """
    for subject in (
        "creature with three heads",
        "creature without vigilant",       # not a keyword this engine has
        "spell",
        "creature you both own and control",
    ):
        program = compile_card_oracle(
            _aura(f"Enchant {subject}\nEnchanted creature gets +2/+2.")
        )
        assert not program.supported, subject
        assert "unimplemented aura effect" in program.reason


@pytest.mark.cr("702.5a")
def test_702_5a_a_readable_enchant_clause_still_claims_its_line():
    """The control for the test above, and the graveyard form beside it:
    Animate Dead's "Enchant creature card in a graveyard" names a different
    zone and so a different picker, and the engine implements that one too."""
    for subject in (
        "creature", "creature without flying", "non-Wall creature",
        "creature you control", "land", "artifact an opponent controls",
        "permanent",
    ):
        program = compile_card_oracle(
            _aura(f"Enchant {subject}\nEnchanted creature gets +2/+2.")
        )
        assert program.supported, f"{subject}: {program.reason}"
    assert unclaimed_aura_lines(
        [normalize_creature_line("Enchant creature card in a graveyard")]
    ) == []

"""Guards for cast-time targeting derived from the compiled program.

`engine/legality.py` used to answer "what does this spell target?" with its own
cascade of substring predicates — a second parser of the same text, which had to
agree with the compiler forever or the UI would offer targets the engine
rejects. `engine/targeting.py` replaced it, and these are the guards that made
the replacement safe and now keep it that way.

While both existed, a differential over the whole pool held them to the same
answer, and it caught three real bugs: Animate Dead ("Enchant creature card in a
graveyard") derived as a battlefield creature; every permanent with a targeted
activated ability — Royal Assassin, Pyramids, King Suleiman — derived a
cast-time target it does not have; and, once the differential compared whole
specs rather than kinds, Reconstruction turned out to be uncastable through the
UI. The first two are named tests below. The third is the cascade being wrong,
which is why deleting it was the fix.

With the cascade gone there is nothing left to diff against, so two things
replace it: a per-card table pinning the specs that carry flags, and a ratchet
that fails if any supported card naming a target stops deriving its own prompt.
"""

import re

import pytest

from engine.card_loader import load_catalog
from engine.oracle import compile_card_oracle
from engine.targeting import (
    card_names_a_chooser,
    derive_cast_spec,
    derive_cast_target,
    line_names_a_cast_target,
)


@pytest.fixture(scope="module")
def supported_cards():
    return [c for c in load_catalog() if compile_card_oracle(c).supported]


def test_reconstruction_picks_an_artifact_card_out_of_a_graveyard(supported_cards):
    """The bug the full-spec differential found.

    Reconstruction is the artifact sibling of Raise Dead, and the text cascade
    read its "target artifact card" as an artifact *on the battlefield*. With no
    artifact in play the UI enumerated zero legal targets for a spell whose
    actual target — an artifact card in the caster's graveyard — was sitting
    right there.
    """
    from engine import PlayerState
    from tests.helpers import _game

    catalog = {c.name: c for c in supported_cards}
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    game.players[0].graveyard.append(catalog["Ornithopter"])

    spec = game.cast_target_spec(0, catalog["Reconstruction"])

    assert spec["kind"] == "graveyard_creature"
    assert spec["card_type"] == "artifact"
    assert [t["name"] for t in spec["valid_targets"]] == ["Ornithopter"]


def test_a_permanent_has_no_cast_time_target_derived_from_its_abilities(supported_cards):
    """Only a spell picks targets as it is cast. A permanent's instructions
    belong to its abilities, which target on activation — deriving from those
    would make the UI demand a target to cast Royal Assassin."""
    for name in ("Royal Assassin", "Pyramids", "King Suleiman", "Dwarven Demolition Team"):
        card = next(c for c in supported_cards if c.name == name)
        assert derive_cast_spec(card, compile_card_oracle(card)) is None, name


def test_an_aura_on_a_graveyard_card_is_not_a_battlefield_target(supported_cards):
    """Animate Dead reads "Enchant creature card in a graveyard". Deriving
    "creature" from the leading words would offer battlefield creatures for a
    reanimation spell, whose target index means a graveyard position.

    And unlike the spell-side reanimators it is *not* scoped to the caster's own
    graveyard: `_apply_aura_effect` pops the chosen index out of whichever
    graveyard the caster pointed at.
    """
    animate_dead = next(c for c in supported_cards if c.name == "Animate Dead")

    spec = derive_cast_spec(animate_dead, compile_card_oracle(animate_dead))

    assert spec == {"kind": "graveyard_creature"}


@pytest.mark.parametrize(
    "name,expected",
    [
        # Derived from the grammar's lowered `targets` description — evidence the
        # legacy rules never recorded. Lightning Bolt and Earthbind both compile
        # to a bare `deal_damage`; only the target description tells them apart.
        ("Lightning Bolt", {"kind": "any"}),
        ("Disintegrate", {"kind": "any"}),
        # "divided **evenly**" — which division the card prints is part of
        # the spec (CR 601.2d), because the picker asks the caster for a
        # division only where the card says the caster chooses.
        ("Fireball", {"kind": "divided", "division": "evenly"}),
        ("Flight", {"kind": "creature"}),           # Enchant creature
        ("Evil Presence", {"kind": "land"}),        # Enchant land
        ("Steal Artifact", {"kind": "artifact"}),   # Enchant artifact
        ("Shatter", {"kind": "artifact"}),          # type_filter=artifact
        ("Stone Rain", {"kind": "land"}),           # type_filter=land
        ("Disenchant", {"kind": "permanent"}),      # type_filter=artifact_or_enchantment
        # Flags, each from the same place its behaviour comes from.
        ("Animate Wall", {"kind": "creature", "enchant_wall": True}),
        ("Feedback", {"kind": "permanent", "enchant_enchantment": True}),
        ("Word of Command", {"kind": "player", "opponents_only": True}),
        ("Blue Elemental Blast", {"kind": "stack", "stack_color_filter": "R"}),
        ("Counterspell", {"kind": "stack"}),
        ("Fork", {
            "kind": "stack", "copies_spell": True, "stack_instant_sorcery_only": True,
        }),
        ("Clone", {"kind": "creature", "optional": True}),
        ("Copy Artifact", {"kind": "artifact", "optional": True}),
        ("Vesuvan Doppelganger", {"kind": "creature", "optional": True}),
        ("Sacrifice", {"kind": "creature", "own_only": True, "sacrifice_cost": True}),
        ("Regrowth", {
            "kind": "graveyard_creature", "own_graveyard_only": True, "any_card": True,
        }),
        ("Raise Dead", {"kind": "graveyard_creature", "own_graveyard_only": True}),
        ("Reconstruction", {
            "kind": "graveyard_creature", "own_graveyard_only": True, "card_type": "artifact",
        }),
        # "Destroy X target Mountains." A bare land-subtype filter is a land
        # target (CR 205.3i puts land subtypes on lands and nothing else), the
        # count is the announced X, and the subtype rides ``filter`` so the
        # enumeration offers exactly the Mountains. The hand-written "divided"
        # spec retired with the card's hook.
        ("Volcanic Eruption", {
            "kind": "land", "filter": {"subtype_filter": "mountain"},
            "x_targets": True,
        }),
        # "…divided **as you choose**" (Pyrotechnics) against Fireball's
        # "divided evenly" above: one printed sentence asks the caster for a
        # division (CR 601.2d) and the other does not, and the picker cannot
        # tell them apart without this. The narrowed form — "among any number of
        # target *creatures*" — is Fire Covenant, in a measured set, so it is
        # covered in tests/sets/test_ice_instants.py instead.
        ("Pyrotechnics", {
            "kind": "divided", "division": "chosen",
            # How much there is to divide, so the picker can ask for a
            # division that totals it. Printed here; X plus a bonus for
            # Meteor Shower.
            "division_total": 4, "division_x_bonus": 0,
        }),
        ("Reverse Damage", {
            "kind": "permanent", "source_of_choice": True, "also_stack": True,
        }),
        # An enters-the-battlefield trigger that targets: this engine picks the
        # target as the permanent is cast, so the prompt has to exist there.
        ("Oubliette", {"kind": "creature"}),
    ],
)
def test_derives_the_expected_spec(supported_cards, name, expected):
    card = next(c for c in supported_cards if c.name == name)

    assert derive_cast_spec(card, compile_card_oracle(card)) == expected


# The cast-target line probe itself lives in engine/targeting.py as
# `line_names_a_cast_target`, one probe with two readers: the forward ratchet
# below and scripts/picker_sweep.py. The exclusion comments moved with it; the
# coverage ratchet asserting how much the probe examines stays here.
_REMINDER = re.compile(r"\([^)]*\)")
_names_a_cast_target = line_names_a_cast_target


# Cards that name a target the UI has no picker for, with the reason. An entry
# here is a card the engine resolves without asking, not one whose prompt went
# missing.
_NO_PICKER = {
    # "You own target card in the ante." Nothing enumerates the ante zone, so
    # the handler exchanges the card it finds there rather than one chosen.
    "Darkpact": "the ante zone has no picker",
}


def test_the_cast_ratchet_still_covers_most_of_what_targets(supported_cards):
    """A ratchet is only worth what it examines, and every exclusion above
    shrinks that.

    Five patterns decide what this file asks of the derivation, and each was
    added because a line uses the word "target" about something other than a
    cast choice. Every one of them is also a way to make the ratchet pass by
    looking at less — the trigger prefix most of all, since widening it by a
    few characters silently excused Gaze of Pain and could as easily excuse a
    hundred cards. So the size of the examined set is asserted, not assumed:
    the delayed-trigger widening cost exactly one card (203 -> 202), and a
    later loosening that costs more fails here before it can hide anything.
    """
    from engine.legality import _cast_lines

    examined = {
        card.name for card in supported_cards
        if any(
            _names_a_cast_target(_REMINDER.sub("", line))
            for line in _cast_lines(card)
        )
    }

    assert len(examined) >= 200, (
        f"the cast ratchet examines only {len(examined)} cards — an exclusion "
        "pattern above has started matching lines that really do target"
    )


def test_every_card_that_targets_as_it_is_cast_derives_its_own_prompt(supported_cards):
    """The end state of this migration, as a ratchet.

    `legality.py`'s cast cascade exists only for cards whose compiled program
    cannot answer, and that set is now empty: every supported card that names a
    target outside an activated or triggered ability derives its whole spec from
    the program. A card appearing here means a parser change took the evidence
    away, or a newly ingested card carries a shape nothing describes — either
    way it is the shadow parser growing back.
    """
    from engine.legality import _cast_lines

    gaps = []
    for card in supported_cards:
        if card.name in _NO_PICKER:
            continue
        lines = [_REMINDER.sub("", line) for line in _cast_lines(card)]
        if not any(_names_a_cast_target(line) for line in lines):
            continue
        if derive_cast_target(card, compile_card_oracle(card)) in (None, "none"):
            gaps.append(card.name)

    assert gaps == [], f"these cards target but derive no prompt: {gaps}"


def test_the_no_picker_acknowledgements_are_not_stale(supported_cards):
    """An acknowledgement that stops matching a real card is how the next card
    inheriting that name gets a free pass nobody re-checked."""
    by_name = {c.name: c for c in supported_cards}

    for name in _NO_PICKER:
        card = by_name.get(name)
        assert card is not None, f"{name} is acknowledged but not in the pool"
        assert derive_cast_target(card, compile_card_oracle(card)) in (None, "none"), (
            f"{name} derives a prompt now — delete its acknowledgement"
        )


def test_the_grammar_supplies_evidence_the_legacy_rules_never_recorded(supported_cards):
    """`deal_damage` alone cannot say what a spell targets — Lightning Bolt
    ("any target"), Fireball ("divided … among any number of targets") and
    Desert's ability ("target attacking creature") all share the kind. The
    grammar's lowered `targets` description is what distinguishes them, so
    targeting coverage now grows as a by-product of parser migration rather
    than needing its own text rules."""
    bolt = next(c for c in supported_cards if c.name == "Lightning Bolt")
    program = compile_card_oracle(bolt)
    payloads = [i.payload for i in program.instructions if "targets" in i.payload]

    assert payloads, "Lightning Bolt's damage instruction should describe its target"
    assert payloads[0]["targets"]["kind"] == "any"
    assert derive_cast_target(bolt, program) == "any"


# --- FixC: a sweep names a class, not a target ---
# The chooser census itself lives in engine/targeting.py as
# `card_names_a_chooser`, one function with two readers: this ratchet and
# scripts/picker_sweep.py, which runs the same sweep over a measured set
# during Phase 3 — a private copy here would let the two drift apart.


def test_no_card_derives_a_cast_prompt_its_text_never_asks_for(supported_cards):
    """The ratchet above, in the other direction — and the direction whose
    absence is how this defect shipped.

    A ratchet with one direction measures half a derivation. "Every card that
    targets derives a prompt" was held all along; nothing asked whether a card
    that targets *nothing* derives one, so seventeen supported cards reported a
    cast-time choice their text never offers.

    Eleven were mass effects, whose ``type_filter`` names the class the sweep
    affects and was read as the class a picker offers (CR 115.1a: an instant or
    sorcery is targeted only where its ability says "target"). The other six
    name their recipient in the payload — "each player loses 2 life", "you lose
    3 life", an enters trigger that mills its own controller — and a recipient
    the sentence fixes is chosen by nobody.

    Not cosmetic. `web/static/app.js` starts a target prompt for any spec kind
    but ``"none"``, and its picker **aborts the cast** when the candidate list
    comes back empty: Cleanse, Tivadar's Crusade, Riptide and Battle Cry could
    not be cast at all on a board with no creature.
    """
    gaps = []
    for card in supported_cards:
        program = compile_card_oracle(card)
        spec = derive_cast_spec(card, program)
        if spec is None or spec.get("kind") == "none":
            continue
        if not card_names_a_chooser(card, program):
            gaps.append(f"{card.name}: {spec}")

    assert gaps == [], (
        "these cards derive a cast prompt but choose nothing: "
        + "; ".join(sorted(gaps))
    )


def test_the_twin_ratchet_still_covers_most_of_what_derives(supported_cards):
    """A ratchet is worth what it examines, and the evidence list above is the
    way to make this one pass by looking at less — widening one word excuses
    every card printing it. So the examined set is asserted, exactly as its
    sibling asserts its own."""
    examined = [
        card for card in supported_cards
        if derive_cast_target(card, compile_card_oracle(card))
        not in (None, "none")
    ]

    assert len(examined) >= 350, (
        f"the twin ratchet examines only {len(examined)} cards — the "
        "derivation has stopped answering for cards that do choose"
    )


#: The cards the unkeyed ``type_filter`` reading invented a target for, and
#: what each one actually does. Named rather than derived, because "which cards
#: were wrong" is a fact about this defect and not a rule about the pool — the
#: rule is the ratchet above.
_SWEEPS_THAT_CHOOSE_NOTHING = {
    "Cleanse": "destroy all black creatures",
    "Jokulhaups": "destroy all artifacts, creatures, and lands",
    "Tivadar's Crusade": "destroy all Goblins",
    "Riptide": "tap all blue creatures",
    "Battle Cry": "untap all white creatures you control",
    "Reset": "untap all lands you control",
    "Hellfire": "destroy all nonblack creatures",
    "Martyr's Cry": "exile all white creatures",
    "Remove Enchantments": "return, then destroy all other enchantments",
    # Two permanents, whose sweep sits on an enters trigger. Worse than the
    # spells: `derive_cast_spec` reads an enters trigger at cast time, so a
    # board with no creature made an *artifact* and an *enchantment*
    # uncastable.
    "Arena of the Ancients": "tap all legendary creatures on entering",
    "Wrath of Marit Lage": "tap all red creatures on entering",
}


@pytest.mark.parametrize("name", sorted(_SWEEPS_THAT_CHOOSE_NOTHING))
def test_a_mass_effect_derives_no_cast_picker(supported_cards, name):
    """Wrath of God is the control that made this findable: the same sentence,
    the same sweep, and it answered "none" all along — because "destroy all
    creatures" has an instruction kind of its own with the class in the *name*,
    so there was no ``type_filter`` for the reader to mistake for a target.
    """
    card = next(c for c in supported_cards if c.name == name)

    assert derive_cast_spec(card, compile_card_oracle(card)) is None


def test_the_control_and_the_defect_now_answer_the_same_way(supported_cards):
    """Wrath of God and Cleanse, side by side."""
    by_name = {card.name: card for card in supported_cards}
    wrath, cleanse = by_name["Wrath of God"], by_name["Cleanse"]

    assert derive_cast_target(wrath, compile_card_oracle(wrath)) is None
    assert derive_cast_target(cleanse, compile_card_oracle(cleanse)) is None
# --- end FixC ---


# --- LeadA: "a graveyard" means any graveyard ---
def _graveyard_reads(program):
    """Every ``any_graveyard`` answer the program's instructions carry.

    Walked rather than read off the top instruction: the flag rides the
    ``reanimate_creature`` step, which a printed second sentence ("…It gains
    haste") would wrap in a ``sequence``. A reader that stopped at the top
    would call such a card own-graveyard-only and be wrong the same way the
    derivation was.
    """
    reads: list[bool] = []

    def walk(instruction):
        payload = getattr(instruction, "payload", None) or {}
        if instruction.kind in ("reanimate_creature", "reanimate_creature_to_battlefield"):
            reads.append(bool(payload.get("any_graveyard")))
        for key in ("steps", "then", "else", "action", "otherwise"):
            for step in payload.get(key) or ():
                if hasattr(step, "payload"):
                    walk(step)

    for instruction in program.instructions:
        walk(instruction)
    return reads


def test_whose_graveyard_a_reanimation_offers_is_the_programs_answer(supported_cards):
    """The ratchet for the defect, in both directions at once.

    ``own_graveyard_only`` was a constant in ``_reanimation_spec`` — the
    derivation asserting something about the pool that only the *payload* can
    know. Hymn of Rebirth ("from **a** graveyard") is the card that made the two
    disagree, and the disagreement cost it every target it had; the mirror
    failure would be a "from **your** graveyard" card offering an opponent's
    pile, which is the same bug pointing the other way and would let a player
    reanimate a creature the card never reaches.

    So the assertion is the agreement itself rather than a list of card names:
    a spec is own-graveyard-only exactly when its program does not say
    ``any_graveyard``.
    """
    from engine.targeting import _ENCHANT_GRAVEYARD_LINE

    disagreements = []
    for card in supported_cards:
        program = compile_card_oracle(card)
        spec = derive_cast_spec(card, program)
        if (spec or {}).get("kind") != "graveyard_creature":
            continue
        if _ENCHANT_GRAVEYARD_LINE.search(program.normalized_text or ""):
            # Animate Dead and Dance of the Dead settle their spec one step
            # earlier, off the printed ``Enchant creature card in a graveyard``
            # line (CR 115.1b) — the Aura's own evidence, read before any
            # instruction is. Their reanimation step carries no determiner at
            # all, so the payload cannot be asked; what can be asked is that
            # the earlier branch reaches the same answer the line prints.
            assert not spec.get("own_graveyard_only"), card.name
            continue
        reads = _graveyard_reads(program)
        if not reads:
            continue        # a return-to-hand or an exile, not a reanimation
        own_only = bool(spec.get("own_graveyard_only"))
        if own_only is any(reads):
            disagreements.append(f"{card.name}: spec={spec}, any_graveyard={reads}")

    assert disagreements == [], (
        "these reanimations derive a graveyard the program does not name: "
        + "; ".join(sorted(disagreements))
    )


def test_the_agreement_ratchet_still_examines_the_card_that_broke_it(supported_cards):
    """A ratchet over an empty set passes forever. Hymn of Rebirth is the only
    card in the pool whose printed phrase reads "from a graveyard" — verified
    by the walk above rather than asserted — so it is also the only evidence
    the test above is looking at anything."""
    widened = {
        card.name for card in supported_cards
        if any(_graveyard_reads(compile_card_oracle(card)))
    }

    assert widened == {"Hymn of Rebirth"}


def test_a_reanimation_printed_your_graveyard_still_offers_only_yours(supported_cards):
    """The control, as a card rather than as a rule: Resurrection prints the
    same effect with the other determiner and keeps the flag."""
    by_name = {card.name: card for card in supported_cards}
    hymn, resurrection = by_name["Hymn of Rebirth"], by_name["Resurrection"]

    assert derive_cast_spec(hymn, compile_card_oracle(hymn)) == {
        "kind": "graveyard_creature",
    }
    assert derive_cast_spec(resurrection, compile_card_oracle(resurrection)) == {
        "kind": "graveyard_creature", "own_graveyard_only": True,
    }
# --- end LeadA ---


# --- VIS W3G5: a negated targeting clause names no cast target ---
# `line_names_a_cast_target` / `cast_picker_expected` (engine/targeting.py),
# probed here as behaviour. Imports for this block, kept local so the block is
# self-contained.
import pytest as _w3g5_pytest

from engine.targeting import cast_picker_expected as _w3g5_cast_picker_expected
from engine.targeting import (
    line_names_a_cast_target as _w3g5_names_a_cast_target,
)


@_w3g5_pytest.mark.parametrize(
    "line",
    [
        # Peace Talks (VIS). The plural is the shape the singular exclusion
        # missed, and the only reason this card was a picker-sweep finding.
        "this turn and next turn, creatures can't attack, and players and "
        "permanents can't be the targets of spells or activated abilities.",
        # Bartel Runeaxe (LEG) — the singular, which was already excluded.
        "bartel runeaxe can't be the target of aura spells.",
        # Anti-Magic Aura (LEA), where the prohibition is one of two clauses.
        "enchanted creature can't be the target of spells and can't be "
        "enchanted by other auras.",
    ],
)
def test_a_prohibition_on_being_targeted_names_no_cast_target(line):
    """CR 115.1a: a spell targets only where its own text says "target". A
    line saying what *other* objects may not do names nothing its caster
    picks — in either grammatical number."""
    assert _w3g5_names_a_cast_target(line) is False


def test_the_prohibition_is_erased_from_the_line_not_a_veto_over_it():
    """The refusal test for the narrowing above.

    Narrowing a probe risks it no longer seeing a card it should see, and the
    sweep's whole value is the Roots class — a supported card no player could
    cast. The other five exclusions in `line_names_a_cast_target` are shapes of
    a *whole line*, so vetoing the line costs nothing; a prohibition is one
    clause and can share its sentence with a real cast target. Erasing the
    clause and re-asking is what keeps that line visible; a `search`-and-veto
    would answer False here and hide the next Roots.
    """
    both = (
        "destroy target creature. it can't be the target of spells this turn."
    )

    assert _w3g5_names_a_cast_target(both) is True
    # And the halves, so the assertion above cannot pass for the wrong reason.
    assert _w3g5_names_a_cast_target("destroy target creature.") is True
    assert _w3g5_names_a_cast_target(
        "it can't be the target of spells this turn."
    ) is False


def test_peace_talks_expects_no_cast_picker(set_pool):
    """The finding itself, as the card rather than as a line: Peace Talks
    derives no cast spec and no longer expects one, which is what takes
    `picker_sweep.py --set VIS` to zero."""
    card = set_pool("VIS")["Peace Talks"]
    program = compile_card_oracle(card)

    assert _w3g5_cast_picker_expected(card, program) is False
    assert derive_cast_spec(card, program) is None
# --- end VIS W3G5 ---

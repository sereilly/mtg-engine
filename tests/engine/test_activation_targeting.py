"""Guards for activated-ability targeting derived from the compiled program.

`engine/legality.py` decided what an *ability* targets with 19 substring
predicates over the card's oracle text — the same shadow-parser shape the cast
side shed, one level down. `engine/targeting.derive_activation_spec` replaced
them by reading the ability's compiled instruction, and these are the guards
that made the replacement safe and now keep it that way.

The question is genuinely per ability, not per card: an ability picks its
targets when it is activated (CR 115.1c), and one permanent may carry several
that pick differently — Pyramids destroys an Aura with one and shields a land
with the other. A card-level classifier could only give one answer.

While both existed, a differential over the whole manifest pool held them to
the same answer at two levels: the spec itself (114 abilities) and the target
list each spec *enumerates on a populated board* (222 serialized specs, every
supported permanent's default prompt plus each of its abilities). It found one
disagreement, Ebony Horse, and the derivation was right — see the first test
below. Two more abilities disagreed only because the old code needed a
special case after the fact to see them at all; the derivation sees them
directly, so that special case is gone.

With the cascade deleted there is nothing left to diff against, so three things
replace it: a table pinning every spec that carries a flag, a ratchet asserting
every ability whose line names a target derives its own prompt, and an exact
census of what still needs the one surviving text fallback.
"""

import re

import pytest

from engine import PlayerState
from engine.card_loader import load_cards, load_catalog, manifest_set_paths
from engine.legality import _fallback_activation_spec
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import CARDS_BY_NAME as _C
from tests.helpers import _game, _nosick


@pytest.fixture(scope="module")
def supported_cards():
    return [c for c in load_catalog() if compile_card_oracle(c).supported]


@pytest.fixture(scope="module")
def by_name(supported_cards):
    return {c.name: c for c in supported_cards}


def _abilities(card):
    return usable_activated_abilities(compile_card_oracle(card))


# ===========================================================================
# What the differential found
# ===========================================================================

def test_ebony_horse_offers_only_an_attacker_you_control(by_name):
    """The bug the differential caught.

    "{2}, {T}: Untap target attacking creature you control." The text cascade
    read "target attacking creature" and stopped, so the UI offered the
    *opponent's* attackers too. The handler does not: it resolves through a
    predicate requiring the creature be attacking **and** on the activating
    player's battlefield, and an explicit choice that fails it fizzles rather
    than falling back. So picking one of the targets the UI offered spent the
    {2} and the tap, logged "resolved", and did nothing at all.

    `own_only` is read off that predicate, which is why the derivation has it
    and a reading of the words did not.
    """
    horse = _nosick(Permanent(card=by_name["Ebony Horse"]))
    mine = _nosick(Permanent(card=_C["Grizzly Bears"]))
    theirs = _nosick(Permanent(card=_C["Hill Giant"]))
    for attacker in (mine, theirs):
        attacker.attacking = True
        attacker.tapped = True
    game = _game(
        PlayerState(name="P1", battlefield=[horse, mine]),
        PlayerState(name="P2", battlefield=[theirs]),
    )

    spec = game.activation_target_spec(0, 0)

    assert spec["kind"] == "creature"
    assert spec["attacking_only"] is True and spec["own_only"] is True
    # The opponent's attacker is gone from the prompt; it was never affectable.
    assert [(t["seat"], t["name"]) for t in spec["valid_targets"]] == [(0, "Grizzly Bears")]


def test_the_target_the_old_prompt_offered_did_nothing_when_chosen(by_name):
    """The other half of that bug: what happened when a player took the offer."""
    horse = _nosick(Permanent(card=by_name["Ebony Horse"]))
    theirs = _nosick(Permanent(card=_C["Hill Giant"]))
    theirs.attacking = True
    theirs.tapped = True
    game = _game(
        PlayerState(name="P1", battlefield=[horse]),
        PlayerState(name="P2", battlefield=[theirs]),
    )

    result = game.activate_permanent_ability(
        0, "Ebony Horse", target_player_index=1, target_permanent_index=0
    )

    assert result.supported  # the cost was paid and the ability "resolved" ...
    assert theirs.tapped is True  # ... and nothing happened to the creature
    assert "prevent_combat_damage_to_and_by_until_eot" not in theirs.metadata


@pytest.mark.parametrize("name,ability_index", [("King Suleiman", 0), ("Elephant Graveyard", 1)])
def test_a_subtype_only_target_needs_no_special_case(by_name, name, ability_index):
    """"Destroy target Djinn or Efreet", "Regenerate target Elephant": neither
    line contains the word "creature", so the text cascade saw no target and
    `activation_target_spec` needed a separate rescue clause that reached into
    the compiled instruction after the fact. The derivation reads that same
    instruction to begin with, so both answer directly and the rescue is gone.
    """
    ability = _abilities(by_name[name])[ability_index]

    assert derive_activation_spec(ability) == {"kind": "creature"}


# ===========================================================================
# The specs themselves
# ===========================================================================

# Every ability in the pool whose derived spec carries a flag beyond its kind —
# the interesting half, and the half a text cascade got wrong. Each flag is read
# from the code that runs the ability, never from the printed line.
@pytest.mark.parametrize(
    "name,ability_index,expected",
    [
        # From the grammar's lowered `targets` description.
        ("Desert", 1, {"kind": "creature", "attacking_only": True}),
        ("Northern Paladin", 0, {"kind": "permanent", "color_filter": "B"}),
        ("Dwarven Demolition Team", 0, {"kind": "creature", "wall_only": True}),
        ("Ali Baba", 0, {"kind": "creature", "wall_only": True}),
        # From the instruction's own payload.
        ("Island of Wak-Wak", 0, {"kind": "creature", "flying_only": True}),
        ("Singing Tree", 0, {"kind": "creature", "attacking_only": True}),
        ("Deathgrip", 0, {"kind": "stack", "stack_color_filter": "G"}),
        ("Lifeforce", 0, {"kind": "stack", "stack_color_filter": "B"}),
        ("Circle of Protection: Red", 0, {
            "kind": "permanent", "color_filter": "R", "also_stack": True,
        }),
        # From what the kind's handler does.
        ("Cyclopean Tomb", 0, {"kind": "land", "exclude_swamp": True}),
        ("Forcefield", 0, {"kind": "creature", "unblocked_attacker": True}),
        ("Jade Monolith", 0, {"kind": "creature", "requires_source": True}),
        ("Diamond Valley", 0, {"kind": "creature", "own_only": True, "sacrifice_cost": True}),
        ("Ebony Horse", 0, {"kind": "creature", "attacking_only": True, "own_only": True}),
        # And a representative of each plain kind, so a table entry going
        # missing cannot pass as "this ability never targeted".
        ("Royal Assassin", 0, {"kind": "creature"}),
        ("Rod of Ruin", 0, {"kind": "any"}),
        ("Prodigal Sorcerer", 0, {"kind": "any"}),
        ("Rocket Launcher", 0, {"kind": "any"}),
        ("Orcish Artillery", 0, {"kind": "any"}),
        ("Disrupting Scepter", 0, {"kind": "player"}),
        ("Millstone", 0, {"kind": "player"}),
        ("Icy Manipulator", 0, {"kind": "permanent"}),
        ("Aladdin", 0, {"kind": "artifact"}),
        ("Ley Druid", 0, {"kind": "land"}),
        ("Demonic Hordes", 0, {"kind": "land"}),
    ],
)
def test_derives_the_expected_spec(by_name, name, ability_index, expected):
    ability = _abilities(by_name[name])[ability_index]

    assert derive_activation_spec(ability) == expected


def test_each_ability_of_a_multi_ability_permanent_answers_for_itself(by_name):
    """Why this is per ability and not per card (CR 115.1c). Pyramids destroys
    an Aura on a land with one ability and shields a land with the other; a
    classifier reading the whole card can only report one of them."""
    destroy, shield = _abilities(by_name["Pyramids"])

    assert derive_activation_spec(destroy) == {"kind": "permanent"}
    assert derive_activation_spec(shield) == {"kind": "land"}


def test_the_two_prompts_a_multi_ability_permanent_raises_are_different(by_name):
    """And the same thing on a real board, through the index the UI sends back:
    mode 1 offers the Aura on a land, mode 2 offers the lands themselves."""
    from engine.auras import attach_aura

    pyramids = _nosick(Permanent(card=by_name["Pyramids"]))
    mountain = _nosick(Permanent(card=_C["Mountain"]))
    aura = _nosick(Permanent(card=_C["Evil Presence"]))  # Enchant land
    game = _game(
        PlayerState(name="P1", battlefield=[pyramids, mountain, aura]),
        PlayerState(name="P2"),
    )
    attach_aura(aura, mountain)

    destroy = game.activation_target_spec(0, 0, ability_index=0)
    shield = game.activation_target_spec(0, 0, ability_index=1)

    assert destroy["kind"] == "permanent"
    assert [t["name"] for t in destroy["valid_targets"]] == ["Evil Presence"]
    assert shield["kind"] == "land"
    assert [t["name"] for t in shield["valid_targets"]] == ["Mountain"]


def test_a_mana_ability_chooses_nothing_and_does_not_shadow_the_next_one(by_name):
    """Desert's first ability is "{T}: Add {C}." and its second targets. The
    default prompt (no ability index) scans in order and takes the first that
    chooses anything, which is how a land with a mana ability still raises its
    real prompt."""
    mana, damage = _abilities(by_name["Desert"])

    assert derive_activation_spec(mana) is None
    assert derive_activation_spec(damage) == {"kind": "creature", "attacking_only": True}


def test_a_shield_on_yourself_or_on_the_source_targets_nothing(by_name):
    """One kind, four answers. `grant_prevention_shield` shields the activating
    player (Conservator), the source permanent (Rock Hydra), a chosen source of
    a colour (the Circles), or a chosen target (Oasis, Samite Healer) — and the
    payload, not the sentence, says which."""
    assert derive_activation_spec(_abilities(by_name["Conservator"])[0]) is None
    assert derive_activation_spec(_abilities(by_name["Rock Hydra"])[0]) is None
    assert derive_activation_spec(_abilities(by_name["Oasis"])[0]) == {"kind": "creature"}
    assert derive_activation_spec(_abilities(by_name["Samite Healer"])[0]) == {"kind": "any"}


# ===========================================================================
# The ratchet, and the measured residue
# ===========================================================================

# Ability lines that name a target the compiled program cannot describe, with
# the reason and what would delete the entry. This is the whole of what is left
# of the shadow parser on the activation side: one line shape, carried by
# `_UNDERIVABLE_ABILITY_TARGETS` in engine/legality.py.
_FALLBACK_ABILITIES = {
    ("Jandor's Saddlebags", 0): (
        "'Untap target creature' lowers to untap_target_permanent, whose handler "
        "untaps whatever it is handed; deriving 'permanent' off the kind would "
        "offer lands. Delete when that handler honours its filter."
    ),
}

_REMINDER = re.compile(r"\([^)]*\)")
# "of your choice" covers the Circle of Protection / Forcefield / Jade Monolith
# style choices, which need the same picker as a target.
_TARGETY = re.compile(r"\btargets?\b|\bof your choice\b")


def _targeting_abilities(cards):
    for card in cards:
        for index, ability in enumerate(_abilities(card)):
            line = _REMINDER.sub("", ability.source_line or "").lower()
            if _TARGETY.search(line):
                yield card, index, ability, line


def test_the_sweep_actually_covers_the_pool(supported_cards):
    """A ratchet over an empty set ratchets nothing."""
    assert len(list(_targeting_abilities(supported_cards))) > 45


def test_every_ability_that_names_a_target_derives_its_own_prompt(supported_cards):
    """The end state of this migration, as a ratchet.

    An ability appearing here means a parser change took the evidence away, or a
    newly ingested card carries a shape nothing describes — either way it is the
    shadow parser growing back, and the UI silently auto-targets
    (`pick_target_permanent`'s fallback) instead of asking.
    """
    gaps = [
        f"{card.name} [{index}]: {line.strip()!r}"
        for card, index, ability, line in _targeting_abilities(supported_cards)
        if derive_activation_spec(ability) is None
        and (card.name, index) not in _FALLBACK_ABILITIES
    ]

    assert gaps == [], "these abilities target but derive no prompt:\n  " + "\n  ".join(gaps)


def test_the_text_fallback_carries_exactly_what_it_is_acknowledged_for(supported_cards):
    """Both directions, which is what makes it a ratchet rather than a note.

    A new ability falling through to the text fallback fails here, and so does
    an acknowledgement whose ability now derives — the second is how a fixed
    card keeps a text predicate alive forever.
    """
    reliant = {
        (card.name, index)
        for card in supported_cards
        for index, ability in enumerate(_abilities(card))
        if derive_activation_spec(ability) is None
        and _fallback_activation_spec(ability.source_line or "") is not None
    }

    assert reliant == set(_FALLBACK_ABILITIES)


def test_the_line_the_fallback_covers_is_one_the_grammar_also_refuses():
    """Why that entry is a refusal and not an oversight, stated where it fails.

    The grammar declines to lower "untap target creature" because no untap
    handler honours a target restriction — the same missing evidence the
    derivation refuses to invent. When that handler starts honouring its filter
    the grammar will lower the line, this assertion will fail, and the fallback
    (and this test) should be deleted together.
    """
    from engine.grammar import compile_line

    compiled = compile_line("Untap target creature.", card_name="Jandor's Saddlebags")

    assert compiled.parsed, "the grammar reads the line; it is the lowering that refuses"
    assert compiled.lowering_error == "no untap handler honors this restriction"


def test_the_fallback_still_reaches_the_prompt_it_exists_for(by_name):
    """And the card it covers keeps its prompt: a creature-only picker, on a
    board where an unrestricted one would offer lands."""
    saddlebags = _nosick(Permanent(card=by_name["Jandor's Saddlebags"]))
    bears = _nosick(Permanent(card=_C["Grizzly Bears"]))
    mountain = _nosick(Permanent(card=_C["Mountain"]))
    game = _game(
        PlayerState(name="P1", battlefield=[saddlebags, bears, mountain]),
        PlayerState(name="P2"),
    )

    spec = game.activation_target_spec(0, 0)

    assert spec["kind"] == "creature"
    assert [t["name"] for t in spec["valid_targets"]] == ["Grizzly Bears"]


def test_a_narrowing_only_one_slot_names_does_not_narrow_the_picker():
    """Two targets, differently restricted: the spec must narrow by what
    **every** slot admits, never by what one does.

    The picker enumerates one legal set for all the slots of a description, so
    a flag read off a single filter is applied to every slot — and "target
    creature you control deals damage … to **another target creature**" names
    the caster's creature and then anyone's. Read that way the ability could
    bite nothing but its own board, while its own handler was written to allow
    either. Per-slot legality stays the handler's; this is only about what the
    prompt is allowed to hide.
    """
    from engine.targeting import _from_targets_payload

    one_filter = _from_targets_payload({
        "quantifier": "target", "kind": "object", "count": 2,
        "filter": {"type_filter": "creature", "controller": "you"},
    })
    assert one_filter["own_only"] is True, "a single filter still narrows"

    per_slot = _from_targets_payload({
        "quantifier": "target", "kind": "object", "count": 2,
        "filter": {"type_filter": "creature", "controller": "you"},
        "filters": [
            {"type_filter": "creature", "controller": "you"},
            {"type_filter": "creature"},
        ],
    })
    assert per_slot["max_targets"] == 2
    assert "own_only" not in per_slot

    both_slots = _from_targets_payload({
        "quantifier": "target", "kind": "object", "count": 2,
        "filter": {"type_filter": "creature", "controller": "you"},
        "filters": [
            {"type_filter": "creature", "controller": "you"},
            {"type_filter": "creature", "controller": "you"},
        ],
    })
    assert both_slots["own_only"] is True, "a narrowing every slot names still applies"


# ---------------------------------------------------------------------------
# The cost half of an activation's announcement (CR 602.2b)
# ---------------------------------------------------------------------------
#
# A choosable cost is not a target and cannot be read off the instruction: the
# instruction is the *effect*, and the payment comes from somewhere no effect
# names. Every one of these abilities charged a cost the payer was never asked
# about — the deterministic default paid, which is right for a seat that names
# nothing and indistinguishable from a seat that was never offered the choice.


# The measured pool too: Hobblefiend and Witch's Cauldron are M21, and a cost
# the payer is never asked about is missing whether or not the set ships.
_COST_POOL = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _COST_POOL.setdefault(_card.name, _card)


def _cost_board(*names: str):
    perms = [_nosick(Permanent(card=_COST_POOL[name])) for name in names]
    p1 = PlayerState(name="P1", battlefield=perms)
    return _game(p1, PlayerState(name="P2")), p1, perms


def test_atog_is_asked_which_artifact_it_eats():
    """No spec at all meant no prompt, so the default paid — and among
    equal-power permanents it breaks the tie on ``permanent_id``, so a board of
    Black Lotus and Mox Ruby lost **the Lotus**."""
    game, _p1, _perms = _cost_board("Atog", "Black Lotus", "Mox Ruby")

    spec = game.activation_target_spec(0, 0)

    assert spec["kind"] == "artifact" and spec["sacrifice_cost"] is True
    assert [t["name"] for t in spec["valid_targets"]] == ["Black Lotus", "Mox Ruby"]


def test_hobblefiends_cost_withholds_the_source_it_cannot_pay_with():
    """"Sacrifice **another** creature" — the word is payload on the cost, and
    the picker has to honour it or it offers the one payment that is illegal."""
    game, _p1, _perms = _cost_board("Hobblefiend", "Grizzly Bears")

    spec = game.activation_target_spec(0, 0)

    assert spec["exclude_source"] is True
    assert [t["name"] for t in spec["valid_targets"]] == ["Grizzly Bears"]


def test_witchs_cauldron_asks_about_the_sacrifice_and_not_a_target():
    """It used to derive ``{"kind": "any"}`` off a caster-recipient life gain, so
    the client opened a *target* picker in front of an ability that targets
    nothing — and the sacrifice was still taken by default. The player was asked
    the wrong question and their answer was discarded."""
    game, _p1, _perms = _cost_board("Witch's Cauldron", "Grizzly Bears")

    spec = game.activation_target_spec(0, 0)

    assert spec["kind"] == "creature" and spec["sacrifice_cost"] is True
    assert [t["name"] for t in spec["valid_targets"]] == ["Grizzly Bears"]


def test_dwarven_weaponsmith_reports_both_announcements_separately():
    """The one that needs two prompts: CR 601.2c picks the creature that gets
    the counter, CR 601.2b picks the artifact that pays. Two fields on the wire,
    so two specs — the target's own list still includes the Weaponsmith, which
    is a legal recipient of its own counter and never a legal payment."""
    game, _p1, _perms = _cost_board("Dwarven Weaponsmith", "Black Lotus", "Grizzly Bears")

    spec = game.activation_target_spec(0, 0)

    assert spec["kind"] == "creature"
    assert [t["name"] for t in spec["valid_targets"]] == [
        "Dwarven Weaponsmith", "Grizzly Bears"
    ]
    cost = spec["cost_spec"]
    assert cost["kind"] == "artifact" and cost["sacrifice_cost"] is True
    assert [t["name"] for t in cost["valid_targets"]] == ["Black Lotus"]


def test_diamond_valley_is_not_asked_twice_for_one_creature():
    """The control for the composition rule. Its handler performs the sacrifice
    as the effect, so the instruction's own spec already *is* the cost picker —
    adding a second would collect two creatures and eat one."""
    game, _p1, _perms = _cost_board("Diamond Valley", "Grizzly Bears")

    spec = game.activation_target_spec(0, 0)

    assert spec["sacrifice_cost"] is True and "cost_spec" not in spec

"""``engine.oracle.simple_card_keywords`` — which cards have nothing to check.

A *simple* card has no abilities, or only keyword lines the engine implements.
The verification tracker auto-passes these (``web/verification_report.py``),
so the criterion has to be exact in both directions: admitting a card with a
real ability would hide it from the manual pass, and refusing a vanilla
creature would send a human to check that 2/2 is 2/2.
"""

from engine.oracle import compile_card_oracle, simple_card_keywords
from tests.helpers import _mk_creature_card


def test_a_vanilla_creature_has_no_keywords(catalog_by_name):
    assert simple_card_keywords(catalog_by_name["Grizzly Bears"]) == ()


def test_keyword_lines_are_read_in_printed_order(catalog_by_name):
    assert simple_card_keywords(catalog_by_name["Baneslayer Angel"]) == (
        "flying", "first strike", "lifelink", "protection from demons and from dragons",
    )


def test_reminder_text_is_not_an_ability(catalog_by_name):
    # "Vigilance (Attacking doesn't cause this creature to tap.)"
    assert simple_card_keywords(catalog_by_name["Alpine Watchdog"]) == ("vigilance",)
    # "({T}: Add {G}.)" — CR 305.6's intrinsic ability, nothing printed.
    assert simple_card_keywords(catalog_by_name["Forest"]) == ()
    assert simple_card_keywords(catalog_by_name["Badlands"]) == ()


def test_one_keyword_per_line_is_the_same_as_one_line(catalog_by_name):
    # "Flying\nProwess (…)"
    assert simple_card_keywords(catalog_by_name["Mistral Singer"]) == ("flying", "prowess")


def test_any_other_ability_disqualifies(catalog_by_name):
    for name in (
        "Rod of Ruin",          # activated
        "Bloodfell Caves",      # a land with a trigger and a printed mana ability
        "Animate Dead",         # an Aura: "enchant" is a keyword, but not a simple one
        "Sol Ring",             # a printed mana ability
        "Shahrazad",
        "Sanctum of All",
    ):
        assert simple_card_keywords(catalog_by_name[name]) is None, name


def test_an_entry_state_line_is_not_simple():
    """A permanent whose only text is an entry-state phrase compiles to a
    program with no instructions — the shape a vanilla creature has — but the
    engine does something card-specific with it, so it is not simple."""
    card = _mk_creature_card("Sleepy Bear", 2, 2, "This creature enters tapped.")
    assert simple_card_keywords(card) is None


def test_an_unsupported_card_is_never_simple():
    card = _mk_creature_card(
        "Mystery Bear", 2, 2, "Flying\nWhenever the moon is full, do something unparseable."
    )
    assert not compile_card_oracle(card).supported
    assert simple_card_keywords(card) is None


def test_a_simple_card_has_nothing_but_keyword_lines_in_its_program(catalog):
    """Cross-check against the compiled program: a simple card never carries
    an activated or triggered ability, a mode, or a non-keyword instruction."""
    simple = [card for card in catalog if simple_card_keywords(card) is not None]
    assert simple, "the pool has vanilla and keyword-only cards"
    for card in simple:
        program = compile_card_oracle(card)
        assert program.supported, card.name
        assert not program.activated_abilities, card.name
        assert not program.triggered_abilities, card.name
        assert not program.modes, card.name
        assert all(i.kind == "keyword_line" for i in program.instructions), card.name

"""Static abilities one permanent applies to objects it does not own.

"Each noncreature artifact loses all abilities and becomes an artifact creature
with power and toughness each equal to its mana value." (Titania's Song.) The
effect belongs to the source, but it changes the *characteristics* of other
permanents, so it has to reach the CR 613 layer system for objects the source
has no relationship with.

``layer_bridge``'s collectors take ``(perm, oid)`` and cannot see the board, so
this follows the model that already works for Auras: the affected permanent
holds a reference to the **source permanent**, and the effects are derived from
that source's text on every recompute. Nothing is materialised onto the
affected object, so a source leaving the battlefield ends its effects by no
longer being in the list — there is no flag to clear and no delta to subtract.

``engine/mixins/permanent_state.py`` rebuilds the lists each refresh; this
module owns *what the text means*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_REMINDER = re.compile(r"\([^)]*\)")


def _line(raw: str) -> str:
    return " ".join(_REMINDER.sub("", raw).strip().lower().split()).rstrip(".")


@dataclass(frozen=True)
class GlobalStatic:
    """What a global static does, and to which permanents.

    ``applies_to`` is a predicate name the refresh pass understands, kept as a
    string so this module stays free of engine imports (the same reason
    ``oracle_types`` does).
    """

    name: str
    applies_to: str
    removes_abilities: bool = False
    adds_creature_type: bool = False
    pt_from_mana_value: bool = False
    # An ability the static *grants*, as the text the granted ability would be
    # printed with. Appending it to the affected permanent's effective card
    # means the compiler produces the ability normally and every consumer — the
    # upkeep step, the UI, the coverage scripts — sees it without knowing this
    # module exists.
    grants_ability: str = ""
    # "**Green** creatures have …" (Breath of Dreams). The colour narrowing the
    # scope carries, as data beside the type word rather than as a scope name of
    # its own: "green creatures" and "creatures" are the same mechanism over
    # different sets, and a ``green_creature`` predicate would be a second one
    # per colour per type. A tuple, because a frozen dataclass has to stay
    # hashable.
    colors: tuple[str, ...] = ()
    # "If this enchantment leaves the battlefield, this effect continues until
    # end of turn." (Titania's Song.) A continuous effect that outlives its
    # source: the source stops existing, the effect does not.
    continues_until_eot: bool = False
    # "Nonland permanents you control **are white**." (Celestial Dawn.) CR 613
    # layer 5, set rather than added: CR 105.3 replaces every colour the object
    # had. A tuple because a card could print two words, and because a frozen
    # dataclass has to stay hashable.
    sets_colors: tuple[str, ...] = ()
    # "**The same is true** for spells you control and nonland cards you own
    # that aren't on the battlefield." The rest of the same sentence, and a flag
    # rather than a second static because it names no new effect -- it says the
    # colour above reaches two more populations. Kept with the effect it
    # extends, so a reader cannot have one without the other.
    extends_to_spells_and_cards: bool = False


_TEMPLATES: tuple[tuple[re.Pattern[str], GlobalStatic], ...] = (
    (
        # "Creatures you control attack each combat if able." (the Pirate
        # Pursued Whale makes.) A board-wide *requirement* granted to its
        # controller's creatures — which this module already has the shape for:
        # the ability is appended to each affected permanent's effective card,
        # so `combat_restrictions.py` reads it as though the creature printed
        # it, and the declare-attackers step needs no new code at all.
        re.compile(r"^creatures you control attack each combat if able$"),
        GlobalStatic(
            name="team_must_attack",
            applies_to="creature_you_control",
            grants_ability="This creature attacks each combat if able.",
        ),
    ),
    (
        # Energy Flux. The granted ability is a whole printed sentence, so it is
        # captured and re-emitted rather than described: anything else would be
        # this module deciding what "sacrifice unless you pay" means, which the
        # upkeep tables already know.
        # **Which permanents it reaches is payload too.** Energy Flux and The
        # Tabernacle at Pendrell Vale differ in one printed noun, and a second
        # row for the second noun would be this module deciding that "all
        # creatures have …" is a different mechanism from "all artifacts have
        # …". It is the same mechanism over a different set, so the noun is
        # payload — read into ``applies_to`` by ``global_static_for`` below,
        # the one place a printed plural becomes the singular type word
        # ``_global_static_applies`` tests.
        re.compile(r"^all (?P<scope>artifacts|creatures) have \"(?P<ability>.+)\"$"),
        GlobalStatic(name="granted_board_wide_ability", applies_to=""),
    ),
    (
        # "**Green creatures** have "Cumulative upkeep {1}."" (Breath of
        # Dreams.) The row above with a colour in front of the noun, and one
        # row rather than five: the colour is payload for the reason the noun
        # already is, and the two are read into the same ``GlobalStatic``. No
        # "all" here — the printed sentence has none, and inventing one would
        # be a second spelling of the same scope.
        re.compile(
            r"^(?P<color>white|blue|black|red|green) "
            r"(?P<scope>artifacts|creatures) have \"(?P<ability>.+)\"$"
        ),
        GlobalStatic(name="granted_board_wide_ability", applies_to=""),
    ),
    (
        # Celestial Dawn. The second sentence is optional in the pattern and
        # mandatory in the *card*: a printing with only the first is a complete
        # and narrower effect (the board alone), and one with both reaches the
        # stack and every other zone. Reading them as one line is what keeps
        # them from drifting apart -- a card whose colour reached the board and
        # not its own hand would be castable exactly as it was before.
        re.compile(
            r"^nonland permanents you control are "
            r"(?P<sets>white|blue|black|red|green)"
            r"(?P<extends>\. the same is true for spells you control and nonland "
            r"cards you own that aren't on the battlefield)?$"
        ),
        GlobalStatic(name="board_wide_color", applies_to="nonland_permanent_you_control"),
    ),
    (
        re.compile(
            r"^each noncreature artifact loses all abilities and becomes an "
            r"artifact creature with power and toughness each equal to its "
            r"mana value\.? ?(?P<lingers>if this enchantment leaves the "
            r"battlefield, this effect continues until end of turn)?$"
        ),
        GlobalStatic(
            name="titanias_song",
            applies_to="noncreature_artifact",
            removes_abilities=True,
            adds_creature_type=True,
            pt_from_mana_value=True,
        ),
    ),
)


def global_static_for(oracle_text: str) -> GlobalStatic | None:
    """The global static *oracle_text* grants, or None.

    Whole-line matches only. A line that merely *contains* one of these phrases
    is not this ability, and claiming it would apply a board-wide effect on the
    strength of a substring.
    """
    for raw_line in oracle_text.splitlines():
        line = _line(raw_line)
        for pattern, static in _TEMPLATES:
            match = pattern.match(line)
            if match is None:
                continue
            groups = match.groupdict()
            if groups.get("lingers"):
                return GlobalStatic(
                    name=static.name,
                    applies_to=static.applies_to,
                    removes_abilities=static.removes_abilities,
                    adds_creature_type=static.adds_creature_type,
                    pt_from_mana_value=static.pt_from_mana_value,
                    grants_ability=static.grants_ability,
                    continues_until_eot=True,
                )
            sets = groups.get("sets")
            if sets:
                return GlobalStatic(
                    name=static.name,
                    applies_to=static.applies_to,
                    sets_colors=(sets,),
                    extends_to_spells_and_cards=bool(groups.get("extends")),
                )
            granted = groups.get("ability")
            if granted:
                # "all creatures" names the type `creature`; the plural is
                # printed English, not a key. Singularised here rather than in
                # the predicate, so each type word has one spelling.
                scope = groups.get("scope")
                colour = groups.get("color")
                return GlobalStatic(
                    name=static.name,
                    applies_to=(scope[:-1] if scope else static.applies_to),
                    removes_abilities=static.removes_abilities,
                    adds_creature_type=static.adds_creature_type,
                    pt_from_mana_value=static.pt_from_mana_value,
                    grants_ability=granted,
                    colors=(colour,) if colour else (),
                )
            return static
    return None


def global_static_sources(permanents) -> list[tuple]:
    """Which of *permanents* are themselves board-wide statics, paired with it.

    **This family is the one place a permanent's text is read as printed**, and
    the reason is a cycle rather than a preference: ``Permanent.effective_card``
    appends the abilities these statics grant, so asking the effective text
    which permanents grant them would make the answer depend on itself. It
    terminates today only because no static in the pool applies to a static.

    Nothing needs the other reading. Both producers (Energy Flux, Titania's
    Song) are enchantments, which nothing in this pool copies, and neither
    prints a colour word or a basic land type for a text change to rewrite.
    """
    return [
        (perm, static)
        for perm in permanents
        if (static := global_static_for(perm.card.oracle_text)) is not None
    ]


def global_statics_applying_to(permanent) -> list[GlobalStatic]:
    """Every global static currently applying to *permanent*.

    Read from the source permanents recorded on it, so a source that has left
    the battlefield contributes nothing the moment the refresh drops it.
    """
    return [static for _source, static in global_static_sources(
        permanent.metadata.get("global_static_sources") or ()
    )]

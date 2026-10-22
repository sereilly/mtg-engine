"""Support derived from the text-keyed rule tables.

:func:`_derived_static_claims` names the tables that already implement a
card's text — untap restrictions, draw-step modifiers, cost modifiers, cast
and activation bans, the replacement registry, and the rest — each of which
reads a permanent's oracle text at the step that needs it and so needs no
instruction to *work*. The support gate asks it, so such a card is supported
because a table carries it out, with that table's parameters as data, rather
than because its text matched a literal: :data:`SUPPORTED_SPELL_PATTERNS`,
empty, is what the literals were. Each claim becomes a ``derived_static_rule``
instruction on the noncreature path, and ``engine/static_line_support.py`` is
the creature side of the same gate.

The tables read here say so in their own docstrings ("the support gate reads
this same table"). Split out of ``engine/oracle.py`` at the 2,000-line cap.
"""

from __future__ import annotations

from .auras import aura_claim
from .flashback import FLASHBACK_CLAIM, flashback_claims_line
from .line_normalization import normalize_creature_line


#: **Empty**, and that is the whole story of this table.
#:
#: It admitted a card into the support gate on a *substring*. It held 73
#: entries; a deletion probe — remove one, recompile all 2,181 cards, count who
#: stops being supported — found that 68 of them carried nobody. They were whole
#: printed sentences from before the grammar could read them (Timetwister's,
#: Wheel of Fortune's, the landwalk grants, the ante cards), and the table never
#: reported that it had stopped being needed. Three of the rest were the bare
#: words ``deals``, ``loses`` and ``gain``, which matched any sentence
#: containing them and let six of Mirage's thirteen unimplemented sentences
#: through the gate.
#:
#: The last five were Auras, and they were the interesting ones: an Aura's
#: ``Enchant <subject>`` line is a keyword ability (CR 702.5) producing no
#: instruction, and its effects are continuous rather than instructions, so a
#: fully implemented Aura had **no evidence of support** for the gate to find.
#: ``engine/auras.py`` was a refusal and never an approval. It is both now
#: (:func:`auras.aura_claim`), asked by ``_derived_static_claims`` like every
#: other derivation table, so an Aura is supported because this engine
#: implements it rather than because its text contains two words.
#:
#: Armor of Thorns is the epitaph. Its clause reads "Enchant **nonblack**
#: creature", which the literal ``"enchant creature"`` never matched, so the
#: card was carried by ``"gets +"`` — a different substring on a different line
#: — for an Aura that worked perfectly. Support had come loose from working.
#:
#: Keep it empty. A card the engine implements has something to show for it; a
#: card that has nothing to show for it is not implemented.
SUPPORTED_SPELL_PATTERNS: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Support derived from the text-keyed rule tables
# ---------------------------------------------------------------------------

def _activation_restrictions_readable(
    oracle_text: str, card_name: str | None = None
) -> bool:
    """Whether this card prints an "Activate only …" clause and every one of
    them is a restriction the engine enforces.

    False for a card printing none, so the claim is only made where there is
    something to claim; False also for a card printing one the table cannot
    read, which is what makes it a *gate* rather than a rubber stamp.
    """
    from .activation_restrictions import _clauses, unreadable_activation_clauses

    if not _clauses(oracle_text or "", card_name):
        return False
    return not unreadable_activation_clauses(oracle_text or "", card_name)


def _derived_static_claims(
    oracle_text: str, normalized_text: str, card_name: str | None = None
) -> list[str]:
    """Names of the rule tables that already implement this card's text.

    These tables (untap_restrictions, draw_step_modifiers, cost_modifiers,
    enter_effects) read a permanent's oracle text directly at the step that
    needs them, so they need no instruction to *work*. They were nonetheless
    absent from the support gate, which listed the same behaviours as whitelist
    literals with the table's parameters baked in — "creatures with power **3**
    or greater don't untap", "players can't untap more than **one** creature".

    That is the false-negative half of the gate/dispatch split: a card printed
    "power 4 or greater" was enforced correctly by the table and reported
    **unsupported**, because the literal named a different number. Deriving
    support from the tables that do the work means the parameter is data here
    too.
    """
    from .card_hooks import DRAW_STEP_MODIFIERS
    from .cast_timing import cast_permission_line
    from .cost_modifiers import cost_modifier_claims_line
    from .cost_x_definitions import (cast_x_ceiling_line,
                                     cast_x_definition_line, cast_x_floor_line)
    from .cast_restrictions import (MOST_PERMANENTS_PLAY_BAN_CLAIM,
                                    most_permanents_play_ban_line)
    from .damage_source_colors import CLAIM as DAMAGE_SOURCE_COLORS_CLAIM
    from .damage_source_colors import colorless_source_line
    from .draw_step_modifiers import (draw_step_bonus_for, draw_step_skip_for,
                                      skips_own_draw_step)
    from .enter_effects import enter_effect_line
    from .evasion_negation import negated_evasion_abilities
    from .extra_triggers import extra_triggers_for
    from .global_statics import global_static_for
    from .land_play_allowance import land_play_allowance_for
    from .life_prohibitions import life_gain_ban_line
    from .mana_spending import spending_permission_line
    from .prevention import prevention_claims_line
    from .regeneration import denies_regeneration_line, self_regeneration_line
    from .replacements import replacement_claims_line
    from .revealed_hands import revealed_hands_line
    from .special_actions import special_action_line
    from .target_immunity import CLAIM as TARGET_IMMUNITY_CLAIM
    from .target_immunity import immunity_claims_line
    from .lethal_damage import CLAIM as LETHAL_DAMAGE_CLAIM
    from .lethal_damage import single_source_lethal_line
    from .untap_restrictions import untap_restriction_for

    claims: list[str] = []
    if untap_restriction_for(oracle_text) is not None:
        claims.append("untap_restrictions")
    # "This creature can't be destroyed by lethal damage unless lethal damage
    # dealt by a single source is marked on it." (Ogre Enforcer.) CR 704.5g
    # narrowed by the permanent's own text: the state-based sweep reads the
    # same table on every pass, so there is no instruction — and on a creature
    # whose whole text is this line, no instruction means the card reports
    # unsupported however well the exception works.
    if any(
        single_source_lethal_line(line)
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(LETHAL_DAMAGE_CLAIM)
    # "This spell can't be countered." (Scragnoth prints it on a creature; an
    # instant or sorcery printing the same sentence reads identically.)
    # CR 113.6g: a static ability that functions on the stack, read off the card
    # by the counter handler at CR 608.2 — so there is no instruction, and its
    # own claim name for the reason the bans above have one: it is what the
    # *spell* says about itself, not a condition some counter carries.
    from .counter_conditions import (CLASS_UNCOUNTERABLE_CLAIM,
                                     UNCOUNTERABLE_CLAIM,
                                     uncounterable_class_line,
                                     uncounterable_line)

    if any(
        uncounterable_line(line) for line in (oracle_text or "").splitlines()
    ):
        claims.append(UNCOUNTERABLE_CLAIM)
    # "Creature spells can't be countered." (Gaea's Herald prints it on a
    # creature; an enchantment printing the sentence reads identically.) The
    # board half of the same immunity, read off the battlefield by the counter
    # handler — no instruction, so its own claim, asked through the reader that
    # enforces it.
    if any(
        uncounterable_class_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(CLASS_UNCOUNTERABLE_CLAIM)
    # "Reveal the first card you draw each turn." (Rowen.) The draw seam reads
    # the permanent's own text on every draw, so there is no instruction to
    # point at — and on a card whose static half is only this sentence, no
    # instruction means it reports unsupported however well the reveal works.
    from .draw_reveals import reveals_every_draw_line, reveals_first_draw_line

    if any(
        reveals_first_draw_line(line) or reveals_every_draw_line(line)
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("draw_reveals")
    # Extra land plays (Fastbond). The land-drop path derives the allowance from
    # the permanent's own text, so the gate has to ask the same table — a
    # wording the table cannot read must make the card unsupported rather than
    # supported-with-the-permission-missing, which is what the name-keyed count
    # this replaced produced.
    if land_play_allowance_for(oracle_text) is not None:
        claims.append("land_play_allowance")
    # CR 602.5 activation restrictions ("Activate only if a creature died this
    # turn"). The activation path reads the same table, so a clause it cannot
    # read is a card the gate must refuse rather than admit with the restriction
    # unenforced — the direction this whole arrangement exists to prevent.
    if _activation_restrictions_readable(oracle_text, card_name):
        claims.append("activation_restrictions")
    # "Activated abilities of creatures can't be activated." (Cursed Totem.)
    # The *board* half of CR 602.5, and the same shape as the two claims below
    # it: the activation path reads the sentence off the board at every
    # activation, so there is no instruction to produce — and on an artifact
    # whose whole text is this line, no instruction means the card reports
    # unsupported however well the ban works.
    from .activation_restrictions import global_activation_ban_line

    # Its **own** claim name, not "activation_restrictions": that one says
    # *when* an ability of this card may be activated, which
    # `_carries_no_behaviour` reads — rightly — as a clause about an ability
    # rather than as something the permanent does. This sentence is the
    # opposite: it is the whole of what Cursed Totem does, and it is about
    # everybody else's abilities.
    if any(
        global_activation_ban_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("global_activation_ban")
    # "Players can cast spells and activate abilities only during their own
    # turns." (City of Solitude.) The timing half of CR 601.3a/602.5, read off
    # the board at every cast and every activation, so there is no instruction
    # to produce — and on an enchantment whose whole text is this sentence, no
    # instruction means the card reports unsupported however well the
    # restriction works. Its own claim name for the two bans' reason: it is
    # what the permanent *does*, and it is about everybody else's turns.
    from .cast_restrictions import (COMBAT_PLAY_BAN_CLAIM,
                                    OWN_CAST_BAN_CLAIM,
                                    GLOBAL_PLAY_TIMING_CLAIM,
                                    SAME_NAME_AS_PERMANENT_BAN_CLAIM,
                                    combat_play_ban_line,
                                    own_cast_ban_line,
                                    same_name_as_permanent_ban_line,
                                    global_play_timing_line)

    if any(
        global_play_timing_line(line)
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(GLOBAL_PLAY_TIMING_CLAIM)
    # "During combat, players can't cast instant spells or activate abilities
    # that aren't mana abilities." (Hand to Hand.) The same pair of gates over a
    # *phase*, and the same reason it needs a claim: the enchantment's whole
    # text is this sentence, so no instruction means it reports unsupported
    # however well both halves work.
    if any(
        combat_play_ban_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(COMBAT_PLAY_BAN_CLAIM)
    # "Players can't cast spells with the same name as a nontoken permanent." /
    # "Players can't play nonbasic lands with the same name as a nontoken
    # permanent." (Cornered Market.) The same shape again: both lines are read
    # off the board at the announcement, so neither produces an instruction, and
    # the enchantment's whole text is the pair.
    if any(
        same_name_as_permanent_ban_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(SAME_NAME_AS_PERMANENT_BAN_CLAIM)
    # "Any player may cast creature spells with mana value 3 or less without
    # paying their mana costs and as though they had flash." (Aluren.) Three
    # permissions, all three read off the board at the cast — and the
    # enchantment's whole text is this sentence, so no instruction means it
    # reports unsupported however well all three work.
    from .cast_permissions import BOARD_FREE_CAST_CLAIM, board_free_cast_line

    if any(
        board_free_cast_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(BOARD_FREE_CAST_CLAIM)
    # "You may play lands and cast spells from your graveyard." (Yawgmoth's
    # Agenda.) The static spelling of Yawgmoth's Will's grant, read off the
    # board by ``cast_permissions.permission_for`` — no instruction, so its own
    # claim, asked through the reader that enforces it.
    from .cast_permissions import (BOARD_GRAVEYARD_PLAY_CLAIM,
                                   board_graveyard_play_line)

    if any(
        board_graveyard_play_line(line)
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(BOARD_GRAVEYARD_PLAY_CLAIM)
    # "Rather than pay the mana cost for a spell, its controller may discard a
    # card that shares a color with that spell." (Dream Halls.) CR 118.9's
    # alternative cost granted from a board rather than printed on the spell,
    # read at every cast by ``applicable_alternative_costs`` -- so there is no
    # instruction, and the enchantment's whole text is this sentence, which
    # means no claim is an unsupported card however well the offer works. The
    # arrangement Aluren's permission above has, one rule over.
    from .alternative_costs import granted_alternative_cost_claims_line

    if any(
        granted_alternative_cost_claims_line(line)
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("alternative_costs")
    # "You can't cast creature spells." (Steel Golem prints it on a creature;
    # an artifact or enchantment printing it reads the same.) CR 601.3a scoped
    # to the permanent's own controller, read off the board at every cast — so
    # there is no instruction, and its own claim name for the reason the two
    # bans above have one: it is what the permanent *does*, and it is about a
    # player rather than about this card's own timing.
    if any(
        own_cast_ban_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(OWN_CAST_BAN_CLAIM)
    # "Each player can't cast more than one spell each turn." (Arcane
    # Laboratory.) The same CR 601.3a prohibition counting casts rather than
    # naming a type, read off the board at every cast — so there is no
    # instruction, and the enchantment's whole text is this sentence, which
    # means no claim is an unsupported card however well the cap works.
    from .cast_restrictions import (LAST_CAST_COLOR_BAN_CLAIM,
                                    SPELL_CAP_CLAIM, last_cast_color_ban_line,
                                    spell_cap_line)

    # "Players can't cast spells that share a color with the spell most
    # recently cast this turn." (Mana Maze.) Read off the board at every
    # announcement, so there is no instruction to produce — and the
    # enchantment's whole text is this sentence, so without a claim it reports
    # unsupported however well the ban works.
    if any(
        last_cast_color_ban_line(line)
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(LAST_CAST_COLOR_BAN_CLAIM)

    if any(
        spell_cap_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(SPELL_CAP_CLAIM)
    # "Rather than the attacking player, you assign the combat damage of each
    # creature attacking you." (Defensive Formation.) CR 510.1a's assigner
    # substituted, read off the board by the combat damage step — so there is no
    # instruction, and the enchantment's whole text is this sentence plus one
    # restating CR 510.1c, which means no claim is an unsupported card however
    # well the substitution works.
    from .combat_assignment import (DEFENDER_ASSIGNS_CLAIM,
                                    defender_assigns_line)

    if any(
        defender_assigns_line(sentence)
        for line in (oracle_text or "").splitlines()
        for sentence in line.split(". ")
    ):
        claims.append(DEFENDER_ASSIGNS_CLAIM)
    # "Players can't gain life." (Forsaken Wastes, CR 119.7.) The life-gain seam
    # asks this same table on every gain, so there is no instruction to produce
    # — and a permanent whose whole text is the sentence would report
    # unsupported however well the ban works. Its own claim name for the reason
    # the ban above has one: it is what the permanent *does*, and it is about
    # everybody else's life totals.
    if any(
        life_gain_ban_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("life_prohibitions")
    # CR 603.2d extra triggers (Sanctum of All). The fire site reads the
    # permanent's own text, so there is no instruction — and without this claim
    # the card would be admitted with the sentence doing nothing, which for a
    # *static* line on an enchantment is a silence the line-by-line assembly
    # cannot see: it produces no instruction and raises nothing.
    if extra_triggers_for(oracle_text) is not None:
        claims.append("extra_triggers")
    # A board-wide static (Titania's Song, Energy Flux) contributes its effects
    # through the CR 613 layer bridge and, for a granted ability, through the
    # affected permanent's effective card — so there is no instruction to
    # produce, and without this the source card would report unsupported while
    # working perfectly.
    if global_static_for(oracle_text) is not None:
        claims.append("global_statics")
    # "A player who controls more permanents than each other player can't play
    # lands or cast artifact, creature, or enchantment spells. That player may
    # sacrifice a permanent…" (Damping Engine.) CR 601.3a over a seat the board
    # names, with CR 116.2d's escape hatch behind it: two gates and a registered
    # special action carry it out and none of them produces an instruction, so
    # without this claim the card reports unsupported while working exactly as
    # printed. Asked of the reader that requires *both* sentences, so a claim
    # cannot be taken on half the line.
    if any(
        most_permanents_play_ban_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(MOST_PERMANENTS_PLAY_BAN_CLAIM)
    # An Aura this module implements in full. Its ``Enchant <subject>`` line is
    # a keyword ability (CR 702.5) that produces no instruction and its effects
    # are continuous, derived from the attachment — so without this the card had
    # no evidence of support at all, and the gate took it from the substring
    # "enchant creature". Asked of the same reader that *refuses* an
    # unimplemented Aura, so the approval and the refusal cannot drift apart.
    if aura_claim(
        [normalize_creature_line(line) for line in (oracle_text or "").split("\n")],
        card_name or "",
    ) is not None:
        claims.append("auras")
    # CR 113.6b: a static ability that functions while the card is a **spell on
    # the stack** (Kaervek's Torch's tax on spells that target it, the ability
    # Torrent of Lava grants each creature). Its behaviour is a cost table and
    # the affected permanents' effective cards, so there is no instruction to
    # produce — and both cards print it beside a damage line that compiles, so
    # without this claim each reported supported doing half of what it prints.
    from .stack_statics import stack_static_claims_line

    if any(
        stack_static_claims_line(line, card_name)
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("stack_statics")
    # CR 106.6 spending permissions ("You may spend white mana as though it were
    # mana of any color"). The payment paths read the seat's derived permission
    # list at the moment a cost is paid, so there is no instruction -- and on an
    # enchantment carrying this line beside two others, no instruction means one
    # third of the card reports as done by the other two. Celestial Dawn is
    # exactly that card: with only its land-type line implemented it compiled
    # green and printed three sentences.
    if spending_permission_line(oracle_text) is not None:
        claims.append("mana_spending")
    # "You may cast this spell as though it had flash. If you cast it any time a
    # sorcery couldn't have been cast, the controller of the permanent it
    # becomes sacrifices it at the beginning of the next cleanup step."
    # (Mirage's five-Aura cycle; Necromancy prints it on an enchantment that is
    # not an Aura when it is cast.) CR 113.6b: the permission functions while
    # the card is in a hand, and the rider is stamped by the cast path and swept
    # by the cleanup step — so there is no instruction to produce, on any card
    # type.
    #
    # **The gate that asked this table was Aura-only**, and that is the whole of
    # what this row fixes. `mixins/stack/casting.py` stamps
    # `CAST_AT_INSTANT_SPEED` off `sacrifices_at_cleanup_if_cast_at_instant_speed`
    # with no type test at all, and `cast_timing.casts_at_instant_speed` reads
    # the permission off any card's text — but the only reader crediting the
    # sentence was `auras._aura_line_claimed`, which runs for a card printing an
    # `Enchant <noun>` line. A card whose enchant clause is inside quotes, or
    # that has none, was enforced correctly and credited with nothing: the
    # false-negative half of the gate/dispatch split this whole function exists
    # to close.
    #
    # Claimed line by line rather than over the whole text, and by the same
    # all-or-nothing reader the Aura gate asks — the permission without the
    # rider beside it is a strictly better card than the one printed.
    if any(
        cast_permission_line(line) for line in (oracle_text or "").splitlines()
    ):
        claims.append("cast_timing")
    # "You may discard this card any time you could cast an instant."
    # (Circling Vultures.) CR 116.2e's special action, which by CR 116.1 does
    # not use the stack — so there is nothing to compile, and on a creature
    # whose other text is a keyword and an upkeep trigger, "nothing to compile"
    # meant the card reported unsupported however well the action works.
    #
    # Claimed line by line and through the table's own reader, for the reason
    # every row above is asked that way: a literal here would be a second copy
    # of the sentence, free to drift from the one that acts.
    if any(
        special_action_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("special_actions")
    # "You may cast Aura spells with enchant creature as though they had flash."
    # (Rootwater Shaman.) The *static* timing permission, which is behaviour of
    # the permanent rather than a clause about its own cast — which is why it is
    # its own claim and not `cast_timing` above, a row `_TIMING_ONLY_CLAIMS`
    # deliberately refuses to count as evidence a permanent does anything.
    from .cast_timing import static_flash_permission

    if any(
        static_flash_permission(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("flash_permissions")
    # "Creatures with mountainwalk can be blocked as though they didn't have
    # mountainwalk." (Crevasse and its four siblings.) The blockers step reads
    # the permanent's own text, so there is no instruction — and on an
    # enchantment whose *whole* text is this sentence, no instruction means the
    # card reports unsupported however well the effect works.
    if negated_evasion_abilities(oracle_text):
        claims.append("evasion_negation")
    # "Black and/or red permanents and spells are colorless sources of damage."
    # (Ghostly Flame.) The damage paths ask the board for this at the moment a
    # source's colour matters (CR 609.7b), so there is no instruction — and on
    # an enchantment whose whole text is the sentence, no instruction means the
    # card reports unsupported however well the rewrite works.
    if any(
        colorless_source_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(DAMAGE_SOURCE_COLORS_CLAIM)
    # "X is the number of … as you cast this spell." (Spoils of War, CR 107.3c.)
    # The cast path computes it before the caster is asked, so there is no
    # instruction — and a definition no row reads must make the card unsupported
    # rather than leave the caster announcing X freely.
    if any(
        cast_x_definition_line(line) for line in (oracle_text or "").splitlines()
    ):
        claims.append("cast_x_definitions")
    # "X can't be greater than the number of snow lands you control."
    # (Winter's Chill, CR 601.2b.) The bound half of the same rule: the caster
    # still announces X and the cast path refuses one above the board's number,
    # so there is no instruction — and a bound no row can count must make the
    # card unsupported rather than leave the announcement unbounded.
    if any(
        cast_x_ceiling_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("cast_x_definitions")
    # "X can't be 0." (Ertai's Meddling, CR 601.2b.) The floor half, and the
    # only bound that forbids the default of 0 an unmade CR 107.3a
    # announcement reads as here — so a card printing it
    # with nothing reading it is castable for nothing at all.
    if any(
        cast_x_floor_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("cast_x_definitions")
    if draw_step_bonus_for(oracle_text) is not None:
        claims.append("draw_step_modifiers")
    # "Skip your draw step." (Necropotence.) The draw step reads the
    # permanent's own text, so there is no instruction — and on an enchantment
    # whose other two lines are a trigger and an activated ability, no claim
    # here would leave this one silently unread.
    if skips_own_draw_step(oracle_text):
        claims.append("draw_step_modifiers")
    # "<permanent> can't be the target of Aura spells" (Bartel Runeaxe, Tetsuo
    # Umezawa). `_can_be_targeted` reads the permanent's own text at the moment
    # a target is chosen, so there is no instruction — and on a creature whose
    # only non-keyword line is this sentence, no instruction would mean the card
    # reports unsupported however well the protection works.
    if any(immunity_claims_line(line) for line in oracle_text.splitlines()):
        claims.append(TARGET_IMMUNITY_CLAIM)
    # "…that player must choose at least one Flagbearer on the battlefield if
    # able." (Standard Bearer, Coalition Flag.) The mirror of the line above —
    # a permanent's text about what somebody else's announcement must include
    # rather than what it may not — read off the board by the cast and
    # activation paths (engine/target_requirements.py), so there is no
    # instruction and the claim asks the reader that enforces it.
    from .target_requirements import CLAIM as TARGET_REQUIREMENTS_CLAIM
    from .target_requirements import must_choose_claims_line

    if any(must_choose_claims_line(line) for line in oracle_text.splitlines()):
        claims.append(TARGET_REQUIREMENTS_CLAIM)
    # "If this card is in a graveyard, effects from spells named ~ count it as
    # a card named ~." (Pardic Firecat's line, on whatever prints it.) Read off
    # the card in the graveyard by the count's own name test, so no instruction.
    from .counted_names import CLAIM as COUNTED_NAMES_CLAIM
    from .counted_names import counts_as_claims_line

    if any(counts_as_claims_line(line) for line in oracle_text.splitlines()):
        claims.append(COUNTED_NAMES_CLAIM)
    # "Players play with their hands revealed." (Revelation.) The per-seat
    # state payload derives who may see whose hand from the permanent's own
    # text (engine/revealed_hands.py), so there is no instruction — and on an
    # enchantment whose whole text is the sentence, no instruction would mean
    # the card reports unsupported however well the reveal works. The
    # library-top twin (Field of Dreams) is the `library_top` claim below.
    if any(revealed_hands_line(line) for line in oracle_text.splitlines()):
        claims.append("revealed_hands")
    # "If this creature would be destroyed, regenerate it." (Clergy of the Holy
    # Nimbus.) CR 701.19b's static form: both destruction paths derive it from
    # the permanent's own text through `engine/regeneration.py`, so there is no
    # instruction — and on a creature whose only line is this sentence, no
    # instruction would mean the card reports unsupported however well the
    # replacement works. Asked of the same reader that performs it.
    # "Creatures dealt damage by this creature this turn can't be regenerated
    # this turn." (Bone Shaman grants it.) The dealer-side twin, claimed beside
    # its neighbour because it is the same arrangement: the damage seam derives
    # it from the permanent's own text, so there is no instruction, and without
    # this the sentence would be admitted by nothing — which for a *granted*
    # ability means the grant itself refuses, since the probe compiles the
    # quoted sentence as a card of its own.
    if any(
        self_regeneration_line(line) or denies_regeneration_line(line)
        for line in oracle_text.splitlines()
    ):
        claims.append("regeneration")
    # The *name-keyed* half of the same CR 504 story (Island Sanctuary's
    # skip-your-draw-for-protection), registered in card_hooks and carried out by
    # phases/draw_step.py, phases/declare_attackers_step.py and
    # phases/untap_step.py. It has no instruction either, and until this claim it
    # had no support of its own: the card was held up by a `spell_pattern` marker
    # the whole-text fallback produced from the words "draw a card" inside a
    # sentence about *skipping* one. Deleting that fallback is what exposed it —
    # tests/engine/test_derived_support.py named the card immediately.
    if card_name in DRAW_STEP_MODIFIERS:
        claims.append("draw_step_modifiers")
    # "If you would begin your draw step, you may skip that step instead. If you
    # do, you gain 2 life." (Fasting.) The text-keyed twin of the hook above,
    # asked of the whole card because the template is two sentences: the skip
    # and the rider it buys. `draw_step_skip_for` returns None for a rider
    # phases/draw_step.py cannot carry out, so a card printing an unreadable one
    # is reported unsupported naming the clause rather than skipping its step
    # and forgetting what the skip was for.
    if draw_step_skip_for(oracle_text) is not None:
        claims.append("draw_step_modifiers")
    if any(
        cost_modifier_claims_line(normalize_creature_line(line))
        for line in oracle_text.splitlines()
    ):
        claims.append("cost_modifiers")
    # The whole entry-state registry, not two of its constants: every phrase in
    # engine/enter_effects.py is implemented by _initialize_permanent_state, so
    # naming a subset here is the same partial-list mistake one level down.
    if any(
        enter_effect_line(line, card_name) for line in oracle_text.splitlines()
    ):
        claims.append("enter_effects")
    from .named_counters import CAP_CLAIM, counter_cap_line

    if any(
        counter_cap_line(line, card_name) for line in oracle_text.splitlines()
    ):
        claims.append(CAP_CLAIM)
    # CR 614 replacement interceptors — **the seventh table, and the one this
    # list did not ask.** An interceptor self-selects off the card's own text at
    # the event it modifies, so like the six above it needs no instruction to
    # work; unlike them it was not a claim, so a permanent whose *only* ability
    # is a replacement reported unsupported however well the interceptor ran.
    # Every such card in the pool happened to print a second readable line
    # (Lich, Ali from Cairo, Library of Leng, Conclave Mentor), which is why the
    # gap waited for a card whose whole text is one replacement.
    if any(replacement_claims_line(line) for line in oracle_text.splitlines()):
        claims.append("replacements")
    # CR 615's half of the same story: a permanent's *static* prevention (Nine
    # Lives) applies from its own text at damage time and produces no
    # instruction either. Asked as the registry, for the reason the line above
    # gives — a literal copied here could claim a wording nothing intercepts.
    if any(
        prevention_claims_line(line, card_name)
        for line in oracle_text.splitlines()
    ):
        claims.append("prevention")
    # "You have protection from the chosen card name." (Runed Halo.) A player's
    # protection, derived from the controlling permanents' own text at each of
    # the three places CR 702.16i names — so like every table above it needs no
    # instruction, and like every table above the gate has to ask it or the card
    # reports supported with the line unaccounted for.
    from .named_protection import named_protection_line

    if any(named_protection_line(line) for line in oracle_text.splitlines()):
        claims.append("named_protection")
    from .library_top import library_top_line

    if any(library_top_line(line) for line in oracle_text.splitlines()):
        claims.append("library_top")
    # "You may cast this card from your graveyard by paying {4}{R} rather than
    # paying its mana cost." — CR 702.34a's first static ability, which is what
    # a flashback keyword line is by the time this reads it
    # (``expand_ability_lines``). A permission and a price rather than an
    # effect, derived off the card's own text by ``cast_permissions`` at every
    # cast, so there is no instruction — and the claim is asked of the reader
    # that charges the cost, so a cost it cannot read is not claimed (and is
    # refused by name above). Not evidence the card *does* anything: see
    # ``_TIMING_ONLY_CLAIMS``.
    if any(flashback_claims_line(line) for line in oracle_text.splitlines()):
        claims.append(FLASHBACK_CLAIM)
    return claims

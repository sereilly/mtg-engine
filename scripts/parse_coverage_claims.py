"""The claim tables `parse_coverage.py` reads every sentence against.

What claims a sentence, as data: the text-keyed channels (`CHANNELS`, each
naming the engine code it mirrors), the channels that need the whole card
(`CARD_CHANNELS`), the trailing sentences a handler implements
(`HANDLER_CLAIMS`) and the deliberate shortcuts (`ACKNOWLEDGED`). They are
the part of the instrument every set adds to — a new text-keyed engine
behaviour is a row here — so they live apart from the analysis that walks
them, which a set rarely touches.

`parse_coverage.py` imports each table by name, so `parse_coverage.CHANNELS`
is still the binding its analysis reads (and the one a test would patch).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from engine.oracle_types import x_spend_colors_from_text  # noqa: E402
from engine.alternative_costs import (  # noqa: E402
    alternative_cost_claims_line, granted_alternative_cost_claims_line)
from engine.cast_costs import (cast_cost_claims_line,  # noqa: E402
                               x_one_of_each_color_sentence)
from engine.activation_restrictions import (  # noqa: E402
    global_activation_ban_line)
from engine.cast_permissions import (board_free_cast_line,  # noqa: E402
                                     board_graveyard_play_line)
from engine.cast_restrictions import (CAST_RESTRICTIONS,  # noqa: E402
                                      cast_absence_line, cast_condition_line,
                                      cast_damage_source_line,
                                      cast_opponent_cast_line,
                                      cast_own_cast_line)
from engine.cast_bans import (combat_play_ban_line,  # noqa: E402
                              chosen_name_ban_line,
                              same_name_as_permanent_ban_line,
                              global_cast_ban_line,
                              global_play_timing_line)
from engine.cast_bans import (most_permanents_play_ban_sentence,  # noqa: E402
                              last_cast_color_ban_line,
                              spell_cap_line)
from engine.combat_assignment import defender_assigns_line  # noqa: E402
from engine.counter_conditions import (uncounterable_class_line,  # noqa: E402
                                       uncounterable_line)
from engine.resolution_overrides import resolution_override_sentence  # noqa: E402
from engine.special_actions import (permanent_special_action_sentence,  # noqa: E402
                                    special_action_line)
from engine.cast_timing import (flash_permission_sentence,  # noqa: E402
                                sacrifices_at_cleanup_if_cast_at_instant_speed,
                                static_flash_permission)
from engine.replacements import replacement_claims_line  # noqa: E402
from engine.life_prohibitions import life_gain_ban_line  # noqa: E402
from engine.target_requirements import must_choose_claims_line  # noqa: E402
from engine.counted_names import counts_as_claims_line  # noqa: E402
from engine.cost_modifiers import (cost_modifier_claims_line,  # noqa: E402
                                  cost_modifier_reduction_sentences,
                                  cost_modifiers_for)
from engine.draw_step_modifiers import (  # noqa: E402
    draw_step_bonus_for, draw_step_skip_line,
)
from engine.global_statics import global_static_for  # noqa: E402
from engine.stack_statics import stack_static_claims_line  # noqa: E402
from engine.mana_spending import mana_spending_for  # noqa: E402
from engine.targeting import (  # noqa: E402
    enchant_graveyard_line, enchant_line_subject,
)
from engine.lord_buffs import sacrifice_state_trigger  # noqa: E402
from engine.auras import aura_effect_claim, aura_static_pt_grant  # noqa: E402
from engine.activation_restrictions import (  # noqa: E402
    activation_restriction_line,
)
from engine.activation_permissions import (  # noqa: E402
    permission_clause_readable,
)
from engine.cost_x_definitions import (  # noqa: E402
    cast_x_ceiling_line,
    cast_x_definition_line,
    cost_x_definition_readable,
)
from engine.revealed_hands import revealed_hands_line  # noqa: E402
from engine.enter_effects import enter_effect_line  # noqa: E402
from engine.extra_triggers import extra_trigger_line  # noqa: E402
from engine.flashback import flashback_claims_line  # noqa: E402
from engine.named_protection import named_protection_line  # noqa: E402
from engine.target_restrictions import target_restriction_line  # noqa: E402
from engine.land_play_allowance import land_play_line  # noqa: E402
from engine.untap_restrictions import (  # noqa: E402
    self_untap_line,
    untap_restriction_for,
    untap_type_choice_sentence,
)
from engine.draw_reveals import reveals_first_draw_line  # noqa: E402
from engine.hand_size import hand_size_line  # noqa: E402
from engine.lethal_damage import single_source_lethal_line  # noqa: E402
from engine.auras import (  # noqa: E402
    aura_board_counted_penalty_sentences,
    aura_cost_reduction_sentences,
)
from engine.oracle import (  # noqa: E402
    compile_card_oracle,
    normalize_creature_line,
)
from engine.ability_lines import (  # noqa: E402
    _parse_delayed_attack_trigger, modal_head_line)


#: "Rather than the attacking player, you assign …" and the sentence behind it.
#: One reader for both, because the second restates CR 510.1c and the first is
#: the whole rule -- see the channel's own comment below.
_DEFENDER_ASSIGNS_RESTATEMENT = (
    "you can divide that creature's combat damage as you choose among any of "
    "the creatures blocking it"
)


def defender_assigns_claims(sentence: str) -> bool:
    return (
        defender_assigns_line(sentence)
        or sentence.strip().lower().rstrip(".") == _DEFENDER_ASSIGNS_RESTATEMENT
    )


_SENTENCE_SPLIT = re.compile(r"(?<=[.!])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip(" .") for s in _SENTENCE_SPLIT.split(text) if s.strip(" .")]


# ---------------------------------------------------------------------------
# Text-keyed claim channels. Each entry mirrors a real consumer in the engine
# (the "where" string points at it) — a predicate here without implementing
# code behind it would just recreate the silence this script exists to remove.
# ---------------------------------------------------------------------------

_AURA_STATIC_PATTERNS = (
    # engine/mixins/oracle_instructions.py — the aura attach interpreter.
    re.compile(r"^enchanted creature gets [+-]\d+/[+-]\d+$"),
    re.compile(r"^enchanted creature gets [+-]\d+/[+-]\d+ and has (?:flying|fear|first strike|reach)$"),
    re.compile(r"^enchanted creature (?:has|gains) (?:flying|fear|first strike|reach|swampwalk|mountainwalk|islandwalk|forestwalk|plainswalk)$"),
    re.compile(r"^enchanted creature has protection from (?:white|blue|black|red|green)$"),
    re.compile(r"^when this aura enters, tap enchanted creature$"),
    re.compile(r"^as this aura enters, choose a basic land type$"),
    re.compile(r"^enchanted creature can attack as though it had haste$"),
    re.compile(r"^enchanted creature can't be blocked except by walls$"),
    re.compile(r"^all creatures able to block enchanted creature do so$"),
    re.compile(r"^you control enchanted (?:creature|artifact)$"),
    re.compile(r"^enchanted land is a swamp$"),
    re.compile(r"^enchanted land is the chosen type$"),
    re.compile(r"^enchanted land has indestructible and can't be enchanted by other auras$"),
    re.compile(r"^enchanted wall can attack as though it didn't have defender$"),
    re.compile(r"^tap enchanted creature$"),
    re.compile(r"^enchanted creature doesn't untap during its controller's untap step$"),
    # Animate Dead's reanimation shape (oracle_instructions.py:159-206).
    re.compile(r"^enchanted creature gets -1/-0$"),
    re.compile(r"^return enchanted creature card to the battlefield under your control"),
    # Animate Artifact's animation clause (oracle_instructions.py:465).
    re.compile(r"^as long as enchanted artifact isn't a creature, it's an artifact creature"),
    # Aspect of Wolf's CDA bonus (permanent_state.py:301).
    re.compile(r"^enchanted creature gets \+x/\+y, where x is half the number of forests"),
)

_MIXIN_TEXT_SCANS = (
    # Literal phrases engine code scans for (site noted per phrase).
    "whenever you're dealt damage, sacrifice that many nontoken permanents",  # effects.py (Lich)
    # The tail of that same sentence. `arm_forced_sacrifice(..., reason="Lich",
    # on_short={"kind": "lose"})` in effects.py IS the "if you can't" half — the
    # forced-sacrifice flow loses the game for a player who cannot pay.
    "if you can't, you lose the game",
    # helpers.py:461 — the leave-the-battlefield loss, matched on this phrase.
    "when this enchantment is put into a graveyard from the battlefield, you lose the game",
    "whenever you're dealt damage, put that many vitality counters on this aura",  # upkeep_step vitality flow (Living Artifact)
    "you don't lose the game for having 0 or less life",                 # game_ending.py (Lich)
    "as this enchantment enters, you lose life equal to your life total",  # permanent_state.py:195 (Lich)
    "you have no maximum hand size",                                     # permanent_state.py:189 (Library of Leng)
    "you may spend white mana as though it were red mana",               # permanent_state.py:192 (Sunglasses of Urza)
    "doesn't untap during your untap step",                              # untap_step.py (Time Vault, Basalt Monolith)
    "you may choose not to untap this creature during your untap step",  # untap_step.py (Old Man of the Sea)
    "if you would begin your turn while this artifact is tapped, you may skip that turn instead",  # beginning_phase.py (Time Vault)
    "enters tapped",                                                     # permanent_state.py:100
    "whenever enchanted land is tapped for mana, its controller adds an additional",  # turn_management.py:285 (Wild Growth)
    "when enchanted creature dies, this aura deals damage equal to that creature's toughness",  # _trigger_aura_death_effects (Creature Bond)
    "if you do, untap this artifact",                                    # beginning_phase.py untap_for_skip (Time Vault)
    "enter as a copy of any artifact on the battlefield",                # copy machinery (Copy Artifact; legality + clone handler)
    "where x is 1 plus the sacrificed creature's mana value",            # handlers/mana.py sacrifice_creature_for_black_mana (Metamorphosis)
    "if the creature that spell becomes as it resolves has not been turned face up",  # effects._turn_face_up, invoked at every damage/tap site (Illusionary Mask)
    "add an amount of {b} equal to the sacrificed creature's mana value",  # handlers/mana.py sacrifice_creature_for_black_mana (Sacrifice)
    "spend this mana only to cast creature spells",                      # handlers/mana.py + _pay_mana_cost creature_only_mana bucket (Metamorphosis)
    "as this artifact enters, choose an opponent",                       # permanent_state.py enter choice + pending_enter_choice prompt (Black Vise)
    "as this enchantment enters, choose a color and an opponent",        # permanent_state.py enter choice + pending_enter_choice prompt (Jihad)
    "this effect doesn't remove this aura",                              # game_ending.py 702.16c exempt branch (the Wards survive their own protection grant)
)

_ACTIVATION_GATES = (
    # queue_permanent_ability's per-ability textual gates (stack/activation_checks.py).
    "activate only during your upkeep",
    "only during your turn",
    "once each turn",
    "activate only if you have exactly seven cards in hand",
    "x can't be 0",
    "activate only as a sorcery",
    "activate only during combat",
    "activate only during the end of combat step",
    "activate only during an opponent's turn, before attackers are declared",
    # The two "who may activate" permissions that used to be literals here --
    # "Any player may activate this ability" (Ifh-Bíff Efreet) and "Only this
    # creature's owner ..." (Personal Incarnation) -- are gone from this tuple.
    # They were a second copy of engine/activation_permissions.py's table, which
    # is what let Clergy of the Holy Nimbus's third spelling read as unclaimed
    # while the module that enforces it had a row for it. The channel below asks
    # that module instead, so a permission the engine implements is claimed and
    # one it does not is not.
)


def _matches_any(sentence: str, patterns) -> bool:
    return any(p.search(sentence) if hasattr(p, "search") else p in sentence for p in patterns)


CHANNELS: tuple[tuple[str, object], ...] = (
    # (channel label, predicate(sentence) -> bool)
    # The "Enchant <subject>" line, asked of the two readers that implement it
    # rather than of the word it starts with. `startswith("enchant ")` claimed
    # every subject there could be, which is why this instrument could not see
    # Roots: "Enchant creature without flying" had no picker and no enforcement
    # and was reported as claimed text. Same reader as `auras._aura_line_claimed`
    # asks, so the census and the support gate cannot disagree about it.
    ("aura enchant noun (oracle_instructions attach)",
     lambda s: enchant_line_subject(s) is not None or enchant_graveyard_line(s)),
    ("aura static (oracle_instructions/permanent_state)", lambda s: _matches_any(s, _AURA_STATIC_PATTERNS)),
    ("cast_restrictions.py", lambda s: any(r.phrase in s for r in CAST_RESTRICTIONS)),
    # The *widening* half of the same question — "You may cast this spell as
    # though it had flash", plus the penalty printed with it (Mirage's five
    # Auras). Two channels rather than one, because this census reads a card
    # sentence by sentence and the card prints two: a permission and a rider,
    # each implemented by its own half of `engine/cast_timing.py`. Asked of the
    # readers that answer them, for the reason every claim above is.
    #
    # ``flash_permission_sentence`` rather than ``grants_flash``: that one
    # *searches*, and claimed "…as though it had flash if you pay {2} more to
    # cast it" (Rout and Invasion's four others) on its first nine words — a
    # dropped rider in the census itself, while the cards cast at instant speed
    # for their sorcery price.
    ("cast_timing.py (granted flash)", flash_permission_sentence),
    ("cast_timing.py (cleanup sacrifice rider)",
     sacrifices_at_cleanup_if_cast_at_instant_speed),
    # And the *static* half of the same file — "You may cast Aura spells with
    # enchant creature as though they had flash" (Rootwater Shaman), a
    # permission a permanent grants its controller's other spells rather than
    # one a card grants itself. Its own channel because it is its own reader.
    ("cast_timing.py (static flash permission)",
     lambda s: static_flash_permission(s) is not None),
    # CR 116's special actions — "You may discard this card any time you could
    # cast an instant" (Circling Vultures, the one card CR 116.2e names). No
    # stack and so no instruction, which is exactly the population this census
    # exists to keep honest: asked of the table's own reader, the one the
    # support gate asks.
    ("special_actions.py", lambda s: special_action_line(s) is not None),
    # CR 116.2c's half of the same file — "You may pay {R} to end this effect"
    # (Tempest's five Licids), an offer a *permanent* makes for as long as the
    # effect its own ability created is running. Its own channel because it is
    # its own reader; no stack and so no instruction, which is exactly the
    # population this census exists to keep honest.
    ("special_actions.py (permanent offer)",
     lambda s: permanent_special_action_sentence(s) is not None),
    # CR 608.2b relaxed by the object itself — "This ability still resolves if
    # its target becomes illegal" (Gilded Drake). A rider on an ability that
    # says what the *rules* do with the object rather than what the object
    # does, so there is no instruction to point at: the whole clause parses and
    # lowers to the identical program with the sentence and without it, which
    # is precisely the "trailing sentence riding along" this census exists to
    # find. Asked of the table `engine/legality.py` reads, the same seam the
    # two special-action rows above use.
    ("resolution_overrides.py",
     lambda s: resolution_override_sentence(s) is not None),
    # The board half of CR 601.3 — "Cast this spell only if you control a
    # snow land" (Blizzard). A row whose noun phrase is payload, so the
    # claim asks the reader that answers it rather than comparing against a
    # phrase list this file would be free to drift from.
    ("cast_restrictions.py (board condition)",
     lambda s: cast_condition_line(s) is not None),
    # The same half negated and asked about every battlefield — "Cast this
    # spell only if no permanents named Tidal Influence are on the
    # battlefield." Its own channel because it is its own row and its own
    # scan; the claim asks the reader that answers it, for the reason above.
    ("cast_restrictions.py (board absence)",
     lambda s: cast_absence_line(s) is not None),
    # The same half of CR 601.3 asked about a *window* rather than a board —
    # "Cast this spell only if you were dealt damage this turn by a red instant
    # or sorcery spell" (Suffocation). Its own channel because it is its own
    # row and its own reader; the claim asks the reader that answers it, for
    # the reason above.
    ("cast_restrictions.py (damage-source window)",
     lambda s: cast_damage_source_line(s) is not None),
    # The same half of CR 601.3 asked about a window of *casts* — "Cast this
    # spell only if an opponent cast a creature spell this turn." (Lure of
    # Prey.) Its own channel beside the damage window for that channel's
    # reason: it is its own row and its own reader, and the claim asks the
    # reader that answers it.
    ("cast_restrictions.py (opponent-cast window)",
     lambda s: cast_opponent_cast_line(s) is not None),
    # The same window of casts asked about the caster's own record -- "Cast this
    # spell only if you've cast another spell this turn." (Skyshroud Condor.)
    # Its own channel beside the opponent-scoped one for that channel's reason:
    # it is its own row and its own scan, and the claim asks the reader that
    # answers it.
    ("cast_restrictions.py (own-cast window)",
     lambda s: cast_own_cast_line(s) is not None),
    # "This spell can't be countered." (Scragnoth.) CR 113.6g -- a static
    # ability of the object on the stack, read off the card by the counter
    # handler at CR 608.2, so it carries no instruction. Asked of the reader
    # that enforces it.
    ("counter_conditions.py (uncounterable spell)", uncounterable_line),
    # The board half of the same immunity -- "Creature spells can't be
    # countered." (Gaea's Herald.) A permanent's static about every spell of a
    # type, read off the battlefield by the same counter handler at the same
    # moment. Its own channel, asking the reader that answers it.
    ("counter_conditions.py (uncounterable spell class)",
     lambda s: uncounterable_class_line(s) is not None),
    # The *other* board half of CR 601.3a — "Creature spells can't be cast."
    # (Aether Storm.) Not a gate the casting card prints about itself but a
    # prohibition a permanent imposes on every player, enforced by
    # `cast_bans.global_cast_ban` from `mixins/stack/casting.py`. Its
    # own channel, asking the reader that answers it.
    ("cast_restrictions.py (board-wide ban)",
     lambda s: global_cast_ban_line(s) is not None),
    # "Each player can't cast more than one spell each turn." (Arcane
    # Laboratory.) CR 601.3a counting casts rather than naming a type, enforced
    # by `cast_bans.spell_cap_ban` from `mixins/stack/casting.py`. Its
    # own channel beside the ban above, asking the reader that answers it.
    ("cast_restrictions.py (per-turn spell cap)",
     lambda s: spell_cap_line(s) is not None),
    # "Players can't cast spells that share a color with the spell most
    # recently cast this turn." (Mana Maze.) CR 601.3a comparing two spells,
    # enforced by `cast_bans.last_cast_color_ban` from
    # `mixins/stack/casting.py`. Its own channel, asking the reader that
    # answers it.
    ("cast_restrictions.py (last-cast colour ban)",
     lambda s: last_cast_color_ban_line(s)),
    # "**Rather than the attacking player, you assign the combat damage of each
    # creature attacking you.** You can divide that creature's combat damage as
    # you choose among any of the creatures blocking it." (Defensive
    # Formation.) CR 510.1a's assigner substituted, enforced by
    # `phases/combat_damage_step._defender_assigns_attacker_damage`.
    #
    # **Both sentences, one channel.** The second says what the first *means* —
    # CR 510.1c already lets whoever assigns divide the damage among the
    # blockers — so it is claimed by the reader of the substitution rather than
    # by a rule of its own, which is what a claim on a restatement is: the
    # sentence has no separate implementation and inventing one would be a
    # second reader of one printed rule.
    ("combat_assignment.py (defender assigns)", defender_assigns_claims),
    # The *name*-keyed half of the same rule — "Spells with the chosen names
    # can't be cast and lands with the chosen names can't be played." (Null
    # Chamber.) Its own channel beside the type-keyed one for that channel's
    # reason: the reader that enforces the line is the one asked, so a claim
    # cannot outlive the ban.
    ("cast_restrictions.py (chosen-name ban)",
     lambda s: chosen_name_ban_line(s)),
    # The same name-keyed rule with the names read off the **board** instead of
    # chosen — "Players can't cast spells with the same name as a nontoken
    # permanent." / "…can't play nonbasic lands with the same name…" (Cornered
    # Market). Its own channel beside the row above for that row's reason, and
    # a *separate* claim per printed line, because the card spends a line on
    # each half and each is enforced on its own.
    ("cast_restrictions.py (same-name-as-permanent ban)",
     lambda s: same_name_as_permanent_ban_line(s) is not None),
    # "A player who controls more permanents than each other player can't play
    # lands or cast artifact, creature, or enchantment spells." (Damping
    # Engine.) CR 601.3a over a seat the board names rather than the sentence,
    # enforced by `cast_bans.most_permanents_cast_ban` from
    # `mixins/stack/casting.py` and by `most_permanents_land_ban` from
    # `Game._land_play_refusal`.
    #
    # The **sentence** reader, where the support gate and the grammar ask the
    # *line* one: this census splits a printed line into sentences, and the
    # CR 116.2d offer behind this one is claimed on its own by the
    # `special_actions.py (permanent offer)` channel below. Two claims for two
    # sentences, each asking the code that carries that sentence out.
    ("cast_restrictions.py (most-permanents play ban)",
     lambda s: most_permanents_play_ban_sentence(s) is not None),
    # The same shape one rule over — "Activated abilities of creatures can't be
    # activated." (Cursed Totem), CR 602.5's board half, enforced by
    # `activation_restrictions.global_activation_ban` from
    # `mixins/stack/activation_checks.py`. Its own channel beside the cast ban and for
    # that channel's reason: the reader that answers the line is the one asked.
    ("activation_restrictions.py (board-wide ban)",
     lambda s: global_activation_ban_line(s) is not None),
    # The **timing** half of both rules at once — "Players can cast spells and
    # activate abilities only during their own turns." (City of Solitude.) One
    # printed sentence read by `cast_bans.global_play_timing` from both
    # `mixins/stack/casting.py` and `mixins/stack/activation_checks.py`, so it gets one
    # channel asking that one reader: a claim split over two would be free to
    # survive the removal of either gate.
    ("cast_restrictions.py (board-wide own-turn window)",
     lambda s: global_play_timing_line(s)),
    # The same two gates over a **phase** instead of a turn — "During combat,
    # players can't cast instant spells or activate abilities that aren't mana
    # abilities." (Hand to Hand.) One channel for the same reason the row above
    # has one: it is one printed sentence, and a claim split over the cast half
    # and the activation half would survive the removal of either gate.
    ("cast_restrictions.py (board-wide combat window)",
     lambda s: combat_play_ban_line(s) is not None),
    # CR 601.3a read the other way round: "Any player may cast creature spells
    # with mana value 3 or less without paying their mana costs and as though
    # they had flash." (Aluren.) Three permissions in one sentence — who, at
    # what cost, and when — carried out off the board's text by
    # `cast_permissions.permission_for` and `cast_timing.casts_at_instant_speed`.
    # One channel, asking the one reader all three enforcement sites ask.
    ("cast_permissions.py (board-wide free cast)",
     lambda s: board_free_cast_line(s) is not None),
    # "You may play lands and cast spells from your graveyard." (Yawgmoth's
    # Agenda.) The static spelling of Yawgmoth's Will's grant: derived off the
    # board by `cast_permissions.permission_for` at every cast and land play.
    # Its own channel, asking the reader that answers it.
    ("cast_permissions.py (controller's graveyard opened)",
     board_graveyard_play_line),
    # A CR 614 replacement effect, in full. `engine/replacements.py`'s
    # REPLACEMENT_LINES *is* the set of constants its interceptors probe for, so
    # asking it is asking the code that carries the line out. Three of these
    # phrases used to sit in _MIXIN_TEXT_SCANS below as literals — a second copy
    # of that table, free to drift from it, and the reason Forethought Amulet's
    # "If an instant or sorcery source would deal 3 or more damage to you…" read
    # as unclaimed rather than as what it was: a replacement with no interceptor
    # behind it at all.
    ("replacements.py", replacement_claims_line),
    # "Players can't gain life." (Forsaken Wastes, CR 119.7.) A prohibition
    # rather than a replacement — `Game._gain_life` asks it before it gathers
    # CR 614's contenders, because the rule says a replacement over a banned
    # gain does nothing — so it is its own channel beside the row above,
    # asking the module that carries the sentence out.
    ("life_prohibitions.py", lambda s: life_gain_ban_line(s) is not None),
    # "While an opponent is choosing targets …, that player must choose at
    # least one Flagbearer on the battlefield if able." (Standard Bearer,
    # Coalition Flag.) A requirement on somebody else's announcement
    # (CR 601.2c), read off the board by the cast and activation paths and by
    # the pickers in front of them — its own channel, asking the reader those
    # paths enforce through.
    ("target_requirements.py", must_choose_claims_line),
    # "If this card is in a graveyard, effects from spells named Flame Burst
    # count it as a card named Flame Burst." (Pardic Firecat, Diligent
    # Farmhand.) Read off the card in the graveyard by the one name test every
    # zone count asks (handlers/_common._card_matches_filter), so the sentence
    # has no instruction and this channel asks that test's own matcher.
    ("counted_names.py", counts_as_claims_line),
    # A printed additional cost (CR 601.2b). Not an instruction — a cost is not
    # an effect — so the sentence would read as unclaimed without this, which
    # is what it *should* have read while the phrase sat in the spell-pattern
    # whitelist producing a marker nothing performed.
    ("cast_costs.py", cast_cost_claims_line),
    # A printed **alternative** cost (CR 118.9) — the other half of the row
    # above, and its own channel because it is its own module and its own
    # payment. It is the row this report was already asking for: Force of Will
    # and Pyrokinesis sat in the unclaimed list with their defining line, which
    # is what an alternative cost with nothing behind it looks like from here.
    ("alternative_costs.py", alternative_cost_claims_line),
    # Dream Halls: CR 118.9's alternative cost granted to every spell from a
    # board rather than printed on the spell. The same table, found by a
    # different question — see ``alternative_costs.granted_alternative_cost``.
    ("alternative_costs.py (granted)", granted_alternative_cost_claims_line),
    # CR 702.34a: "You may cast this card from your graveyard by paying {4}{R}
    # rather than paying its mana cost." — what a flashback keyword line is by
    # the time this census reads it (`oracle.expand_ability_lines`). A CR 601.3
    # permission that requires a CR 118.9 alternative cost: no instruction,
    # carried out by `cast_permissions.permission_for` and the cast path. The
    # row this report was asking for on 27 Odyssey cards, each of which compiled
    # on its other line with the keyword dropped. Asked of the reader that
    # charges the cost, so a cost it cannot read stays unclaimed.
    ("flashback.py", flashback_claims_line),
    # "This creature can't be destroyed by lethal damage unless lethal damage
    # dealt by a single source is marked on it." (Ogre Enforcer.) CR 704.5g
    # narrowed by the permanent's own text — a state-based action, so there is
    # no instruction and the sentence would read unclaimed. Asked of the reader
    # `mixins/game_ending.py` enforces with.
    ("lethal_damage.py", single_source_lethal_line),
    ("untap_restrictions.py", lambda s: untap_restriction_for(s) is not None),
    # "As long as this artifact is untapped, each player chooses artifact,
    # creature, or land during their untap step. **That player can untap only
    # permanents of the chosen type this step.**" (Storage Matrix.)
    #
    # **Both sentences, one channel.** The row above reads the *line*, which is
    # where the support gate and the grammar ask; this census splits a line into
    # sentences, and neither half of this pair is a restriction on its own — the
    # first delimits the options and the second says what naming one does. So
    # both are claimed by the reader that carries the pair out, rather than by
    # inventing a second rule for the half that has no separate implementation.
    ("untap_restrictions.py (untap type choice)", untap_type_choice_sentence),
    # The per-source untap lines — "this artifact doesn't untap during your
    # untap step" and "you may choose not to untap this artifact …" — which the
    # untap step reads off the permanent rather than compiling.
    ("untap_restrictions.py (self untap line)",
     lambda s: self_untap_line(s) is not None),
    # "The chosen player's maximum hand size is four." (Cursed Rack.) Asked of
    # the module the cleanup step enforces CR 402.2 with.
    ("hand_size.py", hand_size_line),
    # "Reveal the first card you draw each turn." (Rowen.) Asked of the module
    # the draw seam enforces CR 701.16 with.
    ("draw_reveals.py", reveals_first_draw_line),
    # Extra land plays (Fastbond). This was a literal in _MIXIN_TEXT_SCANS
    # pointing at a name-keyed count, so the sentence read as claimed for every
    # card printing it while the code behind the claim fired for one name. The
    # predicate now calls the same derivation the land-drop path and the support
    # gate call.
    ("land_play_allowance.py", lambda s: land_play_line(s) is not None),
    # An **Aura or Equipment effect line**. `engine/auras.py` reads these off
    # the attached permanent's own text on every recompute and contributes them
    # through the CR 613 layer bridge, so there is no instruction to point at —
    # which is why the compound forms ("gets +2/+2, has first strike, and is a
    # Knight in addition to its other types") read as unclaimed until now. The
    # shipped pool prints only the simple ones; M21 prints the compounds, and
    # Equipment, whose "Equipped creature gets +1/+1" is the same reader.
    ("auras.py (attached effect)",
     lambda s: aura_effect_claim(s) is not None or aura_static_pt_grant(s) is not None),
    # "You can't choose an untapped creature as this spell's target as you cast
    # it" (Enthralling Hold) — a CR 601.2c printed targeting restriction, read by
    # the cast path and the AI's Aura chooser from engine/target_restrictions.py.
    ("target_restrictions.py", target_restriction_line),
    # "You have protection from the chosen card name" (Runed Halo) — the one
    # protection whose bearer is a player, enforced at the cast target check and
    # the player-damage path from engine/named_protection.py.
    ("named_protection.py", named_protection_line),
    # "As this enchantment enters, choose a card name" (Runed Halo) — an entry
    # state `_initialize_permanent_state` carries out, from the same table the
    # support gate reads.
    ("enter_effects.py", lambda s: enter_effect_line(s) is not None),
    # CR 603.2d extra triggers (Sanctum of All), counted where an ability is put
    # onto the stack from the permanent's own text. Same shape as the entry
    # above and claimed through the same derivation the fire site and the
    # support gate call.
    ("extra_triggers.py", extra_trigger_line),
    # CR 602.5 "Activate only …" clauses (Caged Zombie, Jade Statue), enforced by
    # engine/activation_restrictions.py from the ability's own printed line. Not
    # an instruction — a restriction is not an effect — so the sentence would
    # read as unclaimed without this.
    ("activation_restrictions.py", activation_restriction_line),
    # CR 602.1a "who may activate" permissions (Clergy of the Holy Nimbus, Ifh-Bíff
    # Efreet, Personal Incarnation), enforced by engine/activation_permissions.py
    # in both directions -- it widens the ability to other seats *and* refuses the
    # seat a permission excludes. Asked of that module rather than listed as
    # literals beside the activation gates, where two of the three spellings used
    # to live: a permission is a restriction on someone, so a spelling the table
    # knows and the claim list does not is a sentence reading unclaimed while the
    # engine enforces it, and the reverse is a claim with nothing behind it.
    # Asked through ``permission_clause_readable`` rather than the bare row
    # match, because Armageddon Clock prints the permission and a timing
    # restriction joined by "but" in one sentence -- that reader splits the
    # sentence and asks each table for its own half, which is what the grammar
    # production consuming the sentence asks too.
    ("activation_permissions.py", permission_clause_readable),
    # "X is the number of pin counters on this artifact." (Voodoo Doll.) The
    # printed definition of an activation cost's X (CR 601.2b), read by the
    # activation path off the ability's own line from engine/cost_x_definitions.py
    # -- the same table the grammar refuses an unimplemented definition with. Not
    # an instruction: a cost is not an effect.
    ("cost_x_definitions.py", cost_x_definition_readable),
    # The **cast** half of the same rule: "X is the number of artifact and/or
    # creature cards in an opponent's graveyard as you cast this spell."
    # (Spoils of War, CR 107.3c.) The casting path computes the number off the
    # card's own line before the caster is asked for one, so there is no
    # instruction — and the claim asks that module rather than a phrase list,
    # for the reason every entry above does.
    ("cost_x_definitions.py (cast)", cast_x_definition_line),
    # And the **bound** half: "X can't be greater than the number of snow lands
    # you control." (Winter's Chill, CR 601.2b.) The caster still announces X;
    # the casting path refuses one above the board's number and the picker
    # never offers one, so again there is no instruction. Asked through the
    # module that counts it, like every entry above.
    ("cost_x_definitions.py (ceiling)",
     lambda line: cast_x_ceiling_line(line) is not None),
    # "Players play with their hands revealed." (Revelation.) CR 701.20a, whose
    # whole effect is who may see what -- so the consumer is the per-seat
    # serialization in web/serialization.py, reading engine/revealed_hands.py's
    # board scan. No instruction to point at, and the grammar's registry claim
    # asks the same function.
    ("revealed_hands.py", revealed_hands_line),
    # A **delayed** triggered ability the resolving effect creates (CR 603.7):
    # "Whenever a creature attacks this turn, put a +1/+1 counter on it" (Basri,
    # Devoted Paladin). The sentence is that trigger's own text, not this line's
    # effect, which is why no parse rule matches it — `_parse_delayed_attack_
    # trigger` is what reads it and `create_delayed_trigger` is what the card
    # carries.
    ("oracle.py (delayed trigger)",
     lambda s: _parse_delayed_attack_trigger(s, None) is not None),
    # "Equip {1}" used to be claimed here by prefix, as "a cost rather than an
    # effect". It is neither: CR 702.6a defines it as an activated ability, the
    # compiler now rewrites it into one (`expand_ability_lines`, applied to the
    # text above), and the rewritten line is claimed by the activated-ability
    # parse like any other. "This Equipment enters with a soul counter on it"
    # is entry state and is claimed by enter_effects.py's own reader below.
    # A modal **trigger** head, whose modes are the bullet lines below it
    # (Trufflesnout, Elder Gargaroth). `_modal_trigger_ability` groups the head
    # with its bullets and compiles one `choose_one`; the head read alone is a
    # sentence with no effect in it, which is exactly what it should be.
    # "This ability costs {1} less to activate for each Shrine you control."
    # (Sanctum of Tranquil Light.) A CR 601.2f *reduction*, which the whole-card
    # scan above does not claim because it looks for taxes on spells; this is
    # the per-line reader the same module exposes.
    ("cost_modifiers.py (ability reduction)", cost_modifier_claims_line),
    # "You may activate loyalty abilities of <this planeswalker> on any player's
    # turn any time you could cast an instant." (Teferi, Master of Time.) CR
    # 306.5d relaxed by the card itself, read by the planeswalker compiler off
    # this exact sentence and enforced by the activation timing check.
    ("oracle.py (loyalty timing static)",
     lambda s: bool(_LOYALTY_TIMING.match(s))),
    ("oracle.py (modal trigger head)",
     lambda s: s.rstrip(" —-").endswith("choose one")),
    # A board-wide static contributes through the CR 613 layer bridge and,
    # for a granted ability, through the affected permanent's effective
    # card. There is no instruction to point at, so without this channel a
    # card whose whole behaviour is one of these reads as unclaimed text.
    # "When the chosen player controls no nontoken permanents of the chosen
    # color, sacrifice this enchantment." (Jihad, Call to Arms.) A CR 603.8
    # state trigger checked alongside the SBAs in game_ending.py, keyed to the
    # same condition the anthem beside it hangs on. Asked of the table that
    # sweep reads, rather than the literal that used to sit in
    # ``_MIXIN_TEXT_SCANS`` — a second copy of it, and one card later the second
    # copy would have needed the second phrase too.
    ("lord_buffs.py (state trigger)",
     lambda s: sacrifice_state_trigger(s) is not None),
    ("global_statics.py", lambda s: global_static_for(s) is not None),
    # CR 106.6 spending permissions. Both sentences of the pair, because the
    # census splits a printed line into sentences and the table reads them
    # together: a restriction alone grants nothing, so `mana_spending_for`
    # refuses it, and it would otherwise show as unclaimed on a card whose
    # permission is fully implemented.
    ("mana_spending.py", lambda s: mana_spending_for(s) is not None
     or s.rstrip(".") == "you may spend other mana only as though it were colorless mana"),
    # The rider of a global static that outlives its source. It is part of the
    # same ability, matched on the two-sentence form, but arrives here as its
    # own line.
    ("global_statics.py (lingering rider)",
     lambda s: s.startswith("if this enchantment leaves the battlefield, this effect continues")),
    ("draw_step_modifiers.py", lambda s: draw_step_bonus_for(s) is not None),
    # The optional whole-step skip and the rider it buys (Fasting). Two
    # sentences, claimed one at a time because this table is asked per
    # sentence — `draw_step_skip_for` reads them together to decide whether
    # the card is supported at all.
    ("draw_step_modifiers.py", lambda s: draw_step_skip_line(s)),
    ("cost_modifiers.py", lambda s: bool(cost_modifiers_for(s))),
    ("activation gate (stack/activation)", lambda s: any(g in s for g in _ACTIVATION_GATES)),
    ("mixin text scan", lambda s: _matches_any(s, _MIXIN_TEXT_SCANS)),
    # Through the compiler's own reader rather than a substring. The head is
    # printed bare ("Choose one —") and with its chooser in front of it ("An
    # opponent chooses one —", CR 700.2e), and a `startswith` test claimed the
    # first spelling only — so the second compiled, carried its modes, and
    # reported its own head as text nothing parses.
    ("modal machinery", modal_head_line),
    # Anchored at both ends here and delegating the colour vocabulary to the
    # engine's own reader, so "black **and/or red**" (Soul Burn) is claimed by
    # the same function the payment path enforces rather than by a second
    # spelling of the template that would go stale the next time one moves.
    ("x spend color (stack/activation)",
     lambda s: s.startswith("spend only") and s.endswith("mana on x")
     and bool(x_spend_colors_from_text(s))),
    # "Spend only colored mana on X. No more than one mana of each color may be
    # spent this way." (Emblazoned Golem.) Two sentences, claimed one at a time
    # because this table is asked per sentence — the cost table reads them
    # together (`cast_costs.x_one_of_each_color_line`), folds the pair onto the
    # card's {X} offer and the payment sets the colours aside
    # (`pool_payment._pay_cast_cost`); a card printing either alone, or over an X no
    # offer carries, is refused by the support gate and never reaches here.
    ("x spend one of each color (cast_costs.py)", x_one_of_each_color_sentence),
    ("ante boilerplate (deck construction, not gameplay)", lambda s: s.startswith("remove this card from your deck before playing")),
)

# ---------------------------------------------------------------------------
# Acknowledged simplifications: oracle sentences the engine deliberately does
# not implement (or implements with a documented shortcut). Each needs a
# reason. The guard test fails if an entry stops occurring (stale) so the
# list can only shrink as support improves.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Handler claims: trailing sentences a rule's HANDLER implements even though
# the rule's text anchor sits in an earlier sentence. Keyed by instruction
# kind; each pattern must describe behavior the named handler really performs
# (with a pointer), otherwise this table just recreates the silence.
# ---------------------------------------------------------------------------

HANDLER_CLAIMS: dict[str, tuple[str, ...]] = {
    # handlers/board_misc balance flow: hand/creature balancing is one resolution.
    "balance_resources": ("players discard cards and sacrifice creatures the same way",),
    # handlers/pump.berserk_pump arms destroy_if_attacked_eot.
    "berserk_pump": ("at the beginning of the next end step, destroy that creature if it attacked this turn",),
    # Blaze of Glory's handler marks the forced-block state.
    "grant_unlimited_blocking": ("it blocks each attacking creature this turn if able",),
    # Camouflage's pile flow (declare_blockers_step) owns the whole procedure.
    "randomize_blockers": (
        "creatures those players control that can block additional creatures may likewise be put into additional piles",
        "assign each pile to a different one of those attacking creatures at random",
        "each creature in a pile that can block the creature that pile is assigned to does so",
    ),
    # handlers/destruction.chaos_orb_flip destroys up to two permanents + itself.
    "chaos_orb_flip": (
        "if this artifact turns over completely at least once during the flip, destroy all nontoken permanents it touches",
        "then destroy this artifact",
    ),
    # handlers/combat remove_creature_from_combat implements the False Orders riders.
    "remove_creature_from_combat": (
        "you may have it block an attacking creature of your choice",
        "creatures it was blocking that had become blocked by only that creature this combat become unblocked",
    ),
    # handlers/stack copy_top_stack_spell + the UI retarget flow (Fork).
    "copy_top_stack_spell": ("you may choose new targets for the copy",),
    # Natural Selection's confirm flow carries the shuffle flag.
    "reorder_target_library_top": ("you may have that player shuffle",),
    # Nettling Imp / Siren's Call handler arms must-attack + delayed destroy.
    "mark_non_wall_target_to_attack": (
        "that creature attacks this turn if able",
        "destroy it at the beginning of the next end step if it didn't attack this turn",
    ),
    # Siren's Call: handlers/combat.py force_active_player_creatures_to_attack
    # arms destroy_if_did_not_attack_eot (drained in end_step.py), exempting
    # creatures not controlled continuously since the turn began (the
    # summoning_sickness_turn stamp, re-stamped on control changes).
    "force_active_player_creatures_to_attack": (
        "at the beginning of the next end step, destroy all non-wall creatures that player controls that didn't attack this turn",
        "ignore this effect for each creature the player didn't control continuously since the beginning of the turn",
    ),
    # Power Leak's upkeep mana-prevention prompt (upkeep_step / pay_upkeep_prevention).
    "deal_damage": ("prevent x of that damage, where x is the amount of mana that player paid this way",),
    # Raging River's left/right machinery (declare_blockers_step).
    "left_right_combat_division": (
        'then, for each attacking creature you control, choose "left" or "right." that creature can\'t be blocked this combat except by creatures with flying and creatures in a pile with the chosen label',
    ),
    # handlers/pump grant_flying_and_delayed_destruction arms destroy_at_next_end_step.
    "grant_flying_and_delayed_destruction": ("destroy that creature at the beginning of the next end step",),
    # handlers/pump add_variable_power_counters_to_self enforces the seven cap.
    "add_variable_power_counters_to_self": (
        "this ability can't cause the total number of +1/+0 counters on this creature to be greater than seven",
    ),
    # handlers/combat coin_flip_remove_blocker unblocks lone-blocked attackers
    # (combat.py:129).
    "coin_flip_remove_blocker": (
        "creatures it was blocking that had become blocked by only this creature this combat become unblocked",
    ),
    # Word of Command's pending_word_of_command flow forces the chosen card.
    "peek_hand_and_force_play": ("the player plays that card if able",),
    # handlers/damage.simulacrum_redirect gains the life before dealing the
    # damage (damage.py:156-157) — the rule anchors on the damage sentence,
    # so the life sentence is the *leading* one it also implements.
    "simulacrum_redirect": ("you gain life equal to the damage dealt to you this turn",),
    # Farmstead / Living Artifact grant an upkeep "pay a cost, if you do gain
    # 1 life" ability. The rule anchors on the life gain; the cost half is
    # run by the same upkeep optional-pay flow (upkeep_step.py).
    "target_gains_life": (
        'enchanted land has "at the beginning of your upkeep, you may pay {w}{w}',
        "you may remove a vitality counter from this aura",
    ),
    # Magnetic Mountain's upkeep flow (upkeep_step) pays per tapped creature of
    # the color and untaps each one it can afford.
    "upkeep_pay_per_creature_untap_color": ("if the player does, untap those creatures",),
    # Cyclone's upkeep flow (upkeep_step) deals the pay-damage itself.
    "upkeep_wind_counter_pay_or_sacrifice": (
        "if you pay, this enchantment deals damage equal to the number of wind counters on it to each creature and each player",
    ),
    # "If two or more creatures are tied for least toughness, you choose one of
    # them." (Purging Scythe; Drop of Honey prints it with power.) CR 608.2d's
    # choice on the superlative the sentence in front of it picked by, and
    # the whole of what it says is what ``choose_permanent`` already does with
    # ``only_on_tie``: one candidate records itself, two or more prompt the
    # seat the pick was armed on. So the sentence is a rider that lowers to no
    # instruction (``riders._attach_superlative_tie_break``) rather than a step
    # nothing would run.
    #
    # Both extremes, because both are printed — and the phrase is anchored on
    # "are tied for" so an ordinary sentence merely containing the word cannot
    # be claimed by a card that happens to make a choice elsewhere.
    "choose_permanent": (
        "are tied for least",
        "are tied for greatest",
    ),
    # Power Sink: "Counter target spell unless its controller pays {X}." The
    # counter handler arms the pending payment (handlers/stack.py); when it goes
    # unpaid, mixins/stack/choices._resolve_mana_payment counters the spell and
    # runs the ON_SPELL_COUNTERED hook, which is what taps the lands and empties
    # the pool. One resolution, so the second sentence is the same handler's
    # work rather than a step of its own — the grammar reads it as a rider on
    # the counter (engine/grammar/effects/stack.py _UNPAID_PENALTIES) and lowering
    # refuses any penalty this flow does not perform.
    "counter_top_stack_spell": (
        "they tap all lands with mana abilities they control and lose all unspent mana",
    ),
    # Animate Dead: the attach flow arms sacrifice_attached_on_leave, honored
    # by _remove_aura_effects.
    "reanimate_creature": (
        "when this aura leaves the battlefield, that creature's controller sacrifices it",
    ),
}


#: CR 306.5d relaxed by the card itself. The sentence names the planeswalker,
#: and the compiler collapses that to "this planeswalker" before matching —
#: which a channel predicate handed one sentence and no card name cannot do, so
#: the shape is matched instead of the canonical form.
_LOYALTY_TIMING = re.compile(
    r"^you may activate loyalty abilities of .+ on any player's turn any time "
    r"you could cast an instant$"
)


ACKNOWLEDGED: dict[str, dict[str, str]] = {
    "Shahrazad": {
        "players play a magic subgame, using their libraries as their decks": (
            "subgames are far out of scope. The life clause IS implemented: the caster "
            "is treated as the subgame winner and every other player loses half "
            "their life, rounded up (handlers/life_and_game.opponents_lose_half_life)"
        ),
    },
    "Word of Command": {
        "you control that player until word of command finishes resolving": (
            "simplified: control-of-player is modeled as forcing the chosen card "
            "to be played (pending_word_of_command)"
        ),
        "while doing so, the player can activate mana abilities only if they're from lands that player controls and only if mana they produce is spent to activate other mana abilities of lands the player controls and/or to play that card": (
            "simplified: the forced play is cast without the mana-ability micromanagement"
        ),
        "if the chosen card is cast as a spell, you control the player while that spell is resolving": (
            "simplified: the forced spell resolves under its own controller"
        ),
    },
}


# Channels whose predicate needs the **whole card**, not the sentence alone.
# One reader is like that and it is like that for a reason: Power Artifact's
# reduction is two sentences that mean nothing apart (the amount and its floor),
# so the code that carries it out matches them joined and no sentence-only
# predicate could recognise either half.
def _delayed_trigger_rider_sentences(oracle_text: str) -> set[str]:
    """Trailing sentences that belong to a delayed-trigger clause the compiler
    reads **whole** (Gaze of Pain's "if you do, it assigns no combat damage
    this turn").

    ``_parse_delayed_attack_trigger`` hands the clause behind the opener to the
    ordinary effect reader, so a two-sentence effect is read as two sentences —
    but only the first of them is a delayed-trigger clause on its own, and the
    per-sentence channel above therefore leaves the rider looking unclaimed.

    The anti-rider check is the one ``claim_clause`` makes for a rule match, and
    it is why this is a *card* channel rather than a phrase list: a trailing
    sentence is claimed only when dropping it **changes** the instruction the
    clause produces. A sentence the reader ignored still reads as unclaimed,
    which is the whole point of the report.
    """
    claimed: set[str] = set()
    for raw_line in (oracle_text or "").splitlines():
        line = normalize_creature_line(raw_line.strip()).strip(" .")
        if not line:
            continue
        whole = _parse_delayed_attack_trigger(line, None)
        if whole is None:
            continue
        sentences = _sentences(line)
        if len(sentences) < 2:
            continue
        for cut in range(1, len(sentences)):
            prefix = ". ".join(sentences[:cut])
            if _parse_delayed_attack_trigger(prefix, None) == whole:
                # This prefix already means the whole clause, so everything
                # after it was read and dropped. Claim nothing.
                return set()
        claimed.update(sentences[1:])
    return claimed


CARD_CHANNELS: tuple[tuple[str, object], ...] = (
    (
        # "Players can't cast spells or play lands with a name originally
        # printed in the Arabian Nights expansion." (City in a Bottle.)
        #
        # Implemented, and by nothing that reads this sentence:
        # `mixins/effects._set_lockout_banning_card` scans the battlefield for a
        # compiled `ban_and_sacrifice_set_permanents` instruction — which the
        # card's *other* line produces — and `mixins/stack/casting` refuses the
        # cast from it. So the behaviour is real (drive it: an Arabian Nights
        # spell is refused "banned by City in a Bottle") and the sentence had no
        # claim of its own.
        #
        # It was invisible until the Urza's Legacy promotion gate, because a
        # hooked card's every sentence used to be blanket-claimed by its hook —
        # see :class:`HookClaims`. This is the one finding that survived
        # narrowing that claim to the lines the hook actually compiles, and it
        # is a *reporting* gap rather than a missing implementation, which is
        # exactly what a claim table is for.
        "mixins/effects.py (_set_lockout_banning_card)",
        lambda card, s: (
            "can't cast spells or play lands with a name originally printed"
            in s
            and any(
                instr.kind == "ban_and_sacrifice_set_permanents"
                for instr in compile_card_oracle(card).instructions
            )
        ),
    ),
    (
        # CR 113.6b: a static ability that functions while the card is a spell
        # **on the stack** ("As long as Kaervek's Torch is on the stack, …").
        # A card channel rather than a sentence one, because the subject of the
        # clause is the card naming *itself* — a sentence-only predicate cannot
        # tell that from a clause about some other object, and reading the
        # second would apply an ability whose source this engine cannot find.
        "stack_statics.py",
        lambda card, s: stack_static_claims_line(s, card.name),
    ),
    (
        # "Activate only if **Gerrard Capashen** is attacking." CR 602.5's
        # clause with the card naming itself in it (CR 201.5). The sentence
        # channel above asks the same table with no name in hand, so the row
        # that reads "this <noun> is attacking" never saw the collapsed
        # subject and the clause was reported unclaimed while the activation
        # path — which does pass the name — refused the ability on it. A card
        # channel for `stack_statics`' reason one entry up: only the card can
        # say that the name in the clause is its own.
        "activation_restrictions.py (self-named)",
        lambda card, s: activation_restriction_line(s, card.name),
    ),
    (
        # Gaze of Pain: "you may … . **If you do**, it assigns no combat damage
        # this turn." One clause, two sentences, and the second is the half the
        # card is played for.
        "oracle.py (delayed trigger rider)",
        lambda card, s: s in _delayed_trigger_rider_sentences(card.oracle_text or ""),
    ),
    (
        "auras.py (attached ability cost reduction)",
        lambda card, s: s in aura_cost_reduction_sentences(card.oracle_text or ""),
    ),
    (
        # Heartstone: the identical two-sentence reduction printed by a
        # permanent that enchants nothing. The amount and its floor mean
        # nothing apart, so the reader matches them joined and names the pair
        # here.
        "cost_modifiers.py (board ability cost reduction)",
        lambda card, s: s in cost_modifier_reduction_sentences(
            card.oracle_text or ""
        ),
    ),
    (
        # Snowblind, the second reader shaped that way: the penalty, the two
        # boards it can be counted on and the clamp are four sentences that mean
        # nothing apart, so the derivation matches them joined.
        "auras.py (board-counted clamped penalty)",
        lambda card, s: s in aura_board_counted_penalty_sentences(
            card.oracle_text or ""
        ),
    ),
    (
        # Archery Training: 'Enchanted creature has "{T}: … where X is the
        # number of arrow counters on Archery Training."' The quote names its
        # own Aura, and `aura_effect_claim` claims a quoted grant only when the
        # host can read it — which it can only once the name is bound to the
        # object granting it (CR 201.5a, `granted_abilities.bind_granter`). The
        # name-free row in CHANNELS cannot make that binding, so it rightly
        # refuses this sentence; this row asks the same reader with the name,
        # and carries that row's label because it is that row's channel.
        "auras.py (attached effect)",
        lambda card, s: aura_effect_claim(s, card.name) is not None,
    ),
)

"""Generate PARSE_COVERAGE.md — oracle-text parse-coverage tracker.

The oracle compiler degrades gracefully: a card whose text matches nothing is
reported unsupported. What it does NOT catch is *partial* silence — a card that
compiles "supported" while some of its text was never parsed by anything (the
failure mode behind the Hasran Ogress / Army of Allah / Metamorphosis bugs:
a broad rule matched part of a clause and the rest was silently dropped).

This script closes that gap offline. For every supported card in the pool —
shipped **and** measured — it verifies that each sentence of oracle text is
claimed by a known consumer:

- the parser (whole-clause or per-sentence match),
- the compiler's keyword / trigger / static-line tables,
- one of the engine's text-keyed channels (aura attachment and aura statics,
  cast_restrictions.py, activation gates, mixin text scans, ...) — each
  CHANNELS entry names the implementing code it mirrors,
- a name-keyed card_hooks registry (bespoke behavior claims that card's
  otherwise-unclaimed sentences, listed so they stay visible).

Sentences nothing claims are "unclaimed": either a silent parser gap (fix it)
or a deliberate simplification (add it to ACKNOWLEDGED with a reason). The
guard test (tests/engine/test_parse_coverage.py) fails on unacknowledged
unclaimed text and on stale acknowledgments, so the list can only shrink.

The gate is the **shipped** pool. A measured set's supported cards are analysed
and reported in their own section but never gated on: a set is ingested so its
gaps can be counted before anyone has closed them, and failing on them would
make every ingest red on arrival. That is the same split `GRAMMAR_COVERAGE.md`
and `HOOK_RELIANCE.md` make with their floors and ceilings.

A finer second pass runs a **deletion probe** on parse-rule matches: delete
one word at a time and re-parse — if the identical instruction comes back,
the parser ignored that word (a rider a broad rule swallowed). Findings are
ratcheted through PROBE_ACKNOWLEDGED the same way.

Usage:
    python scripts/parse_coverage.py            # rewrite PARSE_COVERAGE.md
    python scripts/parse_coverage.py --check    # exit 1 on unacknowledged or
                                                # stale findings
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine import card_hooks, load_cards  # noqa: E402
from engine.card_loader import manifest_set_paths  # noqa: E402
from engine.grammar import compile_line as compile_grammar_line  # noqa: E402
from engine.oracle_types import OracleInstruction  # noqa: E402
from engine.cast_costs import cast_cost_claims_line  # noqa: E402
from engine.cast_restrictions import (CAST_RESTRICTIONS,  # noqa: E402
                                      cast_condition_line)
from engine.replacements import replacement_claims_line  # noqa: E402
from engine.cost_modifiers import cost_modifier_claims_line, cost_modifiers_for  # noqa: E402
from engine.draw_step_modifiers import (  # noqa: E402
    draw_step_bonus_for, draw_step_skip_line,
)
from engine.global_statics import global_static_for  # noqa: E402
from engine.auras import (  # noqa: E402
    aura_effect_claim,
    aura_static_pt_grant,
)
from engine.activation_restrictions import (  # noqa: E402
    activation_restriction_line,
)
from engine.activation_permissions import (  # noqa: E402
    permission_clause_readable,
)
from engine.cost_x_definitions import cost_x_definition_readable  # noqa: E402
from engine.revealed_hands import revealed_hands_line  # noqa: E402
from engine.enter_effects import enter_effect_line  # noqa: E402
from engine.extra_triggers import extra_trigger_line  # noqa: E402
from engine.named_protection import named_protection_line  # noqa: E402
from engine.target_restrictions import target_restriction_line  # noqa: E402
from engine.land_play_allowance import land_play_line  # noqa: E402
from engine.untap_restrictions import (  # noqa: E402
    self_untap_line,
    untap_restriction_for,
)
from engine.hand_size import hand_size_line  # noqa: E402
from engine.auras import (  # noqa: E402
    aura_board_counted_penalty_sentences,
    aura_cost_reduction_sentences,
)
from engine.oracle import (  # noqa: E402
    _is_supported_keyword_line,
    _is_supported_static_creature_line,
    _parse_activated_ability,
    _parse_delayed_attack_trigger,
    _parse_loyalty_ability,
    trigger_condition_of_line,
    _parse_triggered_ability,
    compile_card_oracle,
    expand_ability_lines,
    normalize_creature_line,
)
#: The shipped pool, and the measured sets beside it. Both are analysed; only
#: the shipped half gates. A measured set is ingested so its numbers can be read
#: *before* the work of supporting it is done, and a **supported** card in one is
#: exactly what this script is for — the compiler will call it done, and nothing
#: else in the repo can see a printed line it dropped. Excluding measured sets
#: was not a decision, it was the default `manifest_set_paths()` carries; Ice
#: Age's Snowfall is what it cost, counted supported on its cumulative upkeep
#: alone with a whole paragraph compiling to nothing.
CARD_PATHS = [
    *manifest_set_paths(include_measured=True),
]

#: The shipped half, by card name. What `--check` and the guard test fail on,
#: unchanged: a ratchet over a set nobody has implemented would fire on its
#: composition rather than on anything anyone did, which is the arrangement
#: `GRAMMAR_COVERAGE.md` and `HOOK_RELIANCE.md` already make.
SHIPPED_NAMES = {
    card.name for path in manifest_set_paths() for card in load_cards(path)
}
OUTPUT_PATH = REPO_ROOT / "PARSE_COVERAGE.md"

_SENTENCE_SPLIT = re.compile(r"(?<=[.!])\s+")

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
    # game_ending.py:177 — a CR 603.8 state trigger checked alongside the SBAs,
    # matched on this phrase plus the stored enter-choice (Jihad).
    "when the chosen player controls no nontoken permanents of the chosen color",
    "whenever you're dealt damage, put that many vitality counters on this aura",  # upkeep_step vitality flow (Living Artifact)
    "you don't lose the game for having 0 or less life",                 # game_ending.py (Lich)
    "as this enchantment enters, you lose life equal to your life total",  # permanent_state.py:195 (Lich)
    "you have no maximum hand size",                                     # permanent_state.py:189 (Library of Leng)
    "you may spend white mana as though it were red mana",               # permanent_state.py:192 (Sunglasses of Urza)
    "doesn't untap during your untap step",                              # untap_step.py (Time Vault, Basalt Monolith)
    "you may choose not to untap this creature during your untap step",  # untap_step.py (Old Man of the Sea)
    "if you would begin your turn while this artifact is tapped, you may skip that turn instead",  # beginning_phase.py (Time Vault)
    "this spell costs {1} more to cast for each target beyond the first",  # stack/casting.queue_from_hand (Fireball)
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
    # queue_permanent_ability's per-ability textual gates (stack/activation.py).
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
    ("aura enchant noun (oracle_instructions attach)", lambda s: s.startswith("enchant ")),
    ("aura static (oracle_instructions/permanent_state)", lambda s: _matches_any(s, _AURA_STATIC_PATTERNS)),
    ("cast_restrictions.py", lambda s: any(r.phrase in s for r in CAST_RESTRICTIONS)),
    # The board half of CR 601.3 — "Cast this spell only if you control a
    # snow land" (Blizzard). A row whose noun phrase is payload, so the
    # claim asks the reader that answers it rather than comparing against a
    # phrase list this file would be free to drift from.
    ("cast_restrictions.py (board condition)",
     lambda s: cast_condition_line(s) is not None),
    # A CR 614 replacement effect, in full. `engine/replacements.py`'s
    # REPLACEMENT_LINES *is* the set of constants its interceptors probe for, so
    # asking it is asking the code that carries the line out. Three of these
    # phrases used to sit in _MIXIN_TEXT_SCANS below as literals — a second copy
    # of that table, free to drift from it, and the reason Forethought Amulet's
    # "If an instant or sorcery source would deal 3 or more damage to you…" read
    # as unclaimed rather than as what it was: a replacement with no interceptor
    # behind it at all.
    ("replacements.py", replacement_claims_line),
    # A printed additional cost (CR 601.2b). Not an instruction — a cost is not
    # an effect — so the sentence would read as unclaimed without this, which
    # is what it *should* have read while the phrase sat in the spell-pattern
    # whitelist producing a marker nothing performed.
    ("cast_costs.py", cast_cost_claims_line),
    ("untap_restrictions.py", lambda s: untap_restriction_for(s) is not None),
    # The per-source untap lines — "this artifact doesn't untap during your
    # untap step" and "you may choose not to untap this artifact …" — which the
    # untap step reads off the permanent rather than compiling.
    ("untap_restrictions.py (self untap line)",
     lambda s: self_untap_line(s) is not None),
    # "The chosen player's maximum hand size is four." (Cursed Rack.) Asked of
    # the module the cleanup step enforces CR 402.2 with.
    ("hand_size.py", hand_size_line),
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
    ("global_statics.py", lambda s: global_static_for(s) is not None),
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
    ("modal machinery", lambda s: s.startswith("choose one")),
    ("x spend color (stack/activation)", lambda s: bool(re.match(r"^spend only (?:white|blue|black|red|green) mana on x$", s))),
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
    # handlers/destruction.volcanic_eruption deals the aftermath damage itself.
    "volcanic_eruption": (
        "volcanic eruption deals damage to each creature and each player equal to the number of mountains put into a graveyard this way",
    ),
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
    # Drop of Honey's upkeep destruction bypasses regeneration by construction;
    # a tie for least power prompts the (human) controller via
    # pending_least_power_choice / confirm_least_power_choice (upkeep_step.py).
    "upkeep_destroy_least_power_creature": (
        "it can't be regenerated",
        "if two or more creatures are tied for least power, you choose one of them",
    ),
    # Power Sink: "Counter target spell unless its controller pays {X}." The
    # counter handler arms the pending payment (handlers/stack.py); when it goes
    # unpaid, mixins/stack/choices._resolve_mana_payment counters the spell and
    # runs the ON_SPELL_COUNTERED hook, which is what taps the lands and empties
    # the pool. One resolution, so the second sentence is the same handler's
    # work rather than a step of its own — the grammar reads it as a rider on
    # the counter (engine/grammar/parser.py _UNPAID_PENALTIES) and lowering
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

# Deletion-probe baseline: findings reviewed and accepted as harmless (broad
# rules whose handlers implement the full sentence semantics). Regenerate with
# --accept-probe after reviewing new findings; the guard test fails on any
# finding not in the baseline AND on stale baseline entries, so the file is
# always an exact snapshot.
PROBE_BASELINE_PATH = REPO_ROOT / "scripts" / "parse_coverage_probe_baseline.json"


def load_probe_baseline() -> dict[tuple[str, str], tuple[str, ...]]:
    import json

    if not PROBE_BASELINE_PATH.exists():
        return {}
    raw = json.loads(PROBE_BASELINE_PATH.read_text(encoding="utf-8"))
    return {
        (entry["card"], entry["clause"]): tuple(entry["ignored"])
        for entry in raw
    }


def save_probe_baseline(findings: dict[tuple[str, str], tuple[str, ...]]) -> None:
    import json

    entries = [
        {"card": card, "clause": clause, "ignored": list(words)}
        for (card, clause), words in sorted(findings.items())
    ]
    PROBE_BASELINE_PATH.write_text(
        json.dumps(entries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# Words whose deletion never signals a real parsing gap: articles/fillers and
# the "until end of turn" duration (duration semantics live in the handlers).
_PROBE_STOPWORDS = frozenset(
    "a an the of to and then that this it its is are them their they you your "
    "until end turn".split()
)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@dataclass
class CardCoverage:
    name: str
    supported: bool
    #: Whether a player can actually deck this card. False for a card that is
    #: only in a `measured` set — reported here, never gated on.
    shipped: bool = True
    claims: list[tuple[str, str]] = field(default_factory=list)      # (sentence, channel)
    unclaimed: list[str] = field(default_factory=list)               # sentences
    acknowledged: list[tuple[str, str]] = field(default_factory=list)  # (sentence, reason)
    probe_findings: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)  # (sentence, words)


def _sentences(text: str) -> list[str]:
    return [s.strip(" .") for s in _SENTENCE_SPLIT.split(text) if s.strip(" .")]


def _grammar_instruction(compiled):
    instructions = compiled.instructions
    return (
        instructions[0] if len(instructions) == 1
        else OracleInstruction("sequence", "", {"steps": instructions})
    )


def _rule_match(
    clause: str,
    activated: bool,
    card_name: str | None = None,
    trigger_prefix: str | None = None,
    cost_prefix: str | None = None,
):
    """What parses *clause*, or (None, "unsupported").

    This used to try the grammar and then ``engine.parsing``'s rule registry,
    and the second leg is gone with the registry. ROADMAP's "a dedup that would
    be a mistake" argues that this script's value is in being an *independent*
    second opinion and that delegating to the engine would make it
    tautological. That argument is about :data:`CHANNELS` — the hand-kept
    inventory of which engine code implements which sentence — and it still
    holds there, untouched. It was never about this leg, which was not an
    inventory but a second *parser*, and whose independence was an artifact of
    two front ends existing rather than a property anything relied on. The
    grammar was already tried first, so the legacy leg only ever answered for
    text the grammar refused — text that now has no reader at all.

    What keeps the guard from being an echo of the compiler is unchanged, and
    is not this call:

    * **the unit.** The compiler claims a *line*; this script splits it into
      sentences and makes each earn a claim, then (``claim_clause``) finds the
      shortest sentence prefix that reproduces the parse so trailing sentences
      cannot ride along. That is a strictly finer question than "does this card
      compile".
    * **the deletion probe**, which is a property test over the parser rather
      than a second opinion: remove a word, re-parse, and an identical
      instruction means the word was ignored. It gets *stronger* against the
      grammar, whose full-consumption invariant means removing a meaningful
      word usually fails the parse outright.
    * **CHANNELS**, which answers "is this sentence implemented by something
      other than an instruction" from a list nobody derives from the engine.

    *trigger_prefix* is the trigger condition this clause is the remainder of,
    and is tried last. Some effects are only meaningful inside their trigger:
    "that player adds one mana of any type that land produced" names a player
    and a land the *event* binds, so ``lower_statement`` refuses it outside a
    ``land_tapped_for_mana`` trigger and the clause read alone looks unclaimed.
    The compiler hands the grammar the whole line (oracle.py
    ``_grammar_instruction``), so reading it that way here is mirroring it, not
    excusing it — and the probe re-parses through the same path, so deleting a
    word from the clause still has to change the parse.
    """
    compiled = compile_grammar_line(clause, card_name=card_name)
    if compiled.usable:
        return _grammar_instruction(compiled), "grammar"
    if trigger_prefix:
        in_trigger = compile_grammar_line(f"{trigger_prefix}, {clause}", card_name=card_name)
        if in_trigger.usable:
            return _grammar_instruction(in_trigger), "grammar (read with its trigger)"
    if cost_prefix:
        in_cost = compile_grammar_line(f"{cost_prefix}: {clause}", card_name=card_name)
        if in_cost.usable:
            return _grammar_instruction(in_cost), "grammar (read with its cost)"
    return None, "unsupported"


def _probe(
    clause: str,
    activated: bool,
    card_name: str | None = None,
    trigger_prefix: str | None = None,
    cost_prefix: str | None = None,
) -> tuple[str, ...]:
    """Words in *clause* whose deletion leaves the parse identical — i.e.
    words the parser demonstrably ignored."""
    base_instr, _ = _rule_match(clause, activated, card_name, trigger_prefix, cost_prefix)
    if base_instr is None:
        return ()
    words = clause.split()
    ignored: list[str] = []
    for i, word in enumerate(words):
        if word.lower().strip(".,;:'\"") in _PROBE_STOPWORDS:
            continue
        shorter = " ".join(words[:i] + words[i + 1:])
        instr, _ = _rule_match(shorter, activated, card_name, trigger_prefix, cost_prefix)
        if instr is not None and instr == base_instr:
            ignored.append(word)
    return tuple(ignored)


def _hooked_names() -> set[str]:
    """Card names with a bespoke card_hooks registry entry."""
    names: set[str] = set()
    for attr in dir(card_hooks):
        value = getattr(card_hooks, attr)
        if isinstance(value, dict):
            names.update(k for k in value if isinstance(k, str))
    return names


# Channels whose predicate needs the **whole card**, not the sentence alone.
# One reader is like that and it is like that for a reason: Power Artifact's
# reduction is two sentences that mean nothing apart (the amount and its floor),
# so the code that carries it out matches them joined and no sentence-only
# predicate could recognise either half.
CARD_CHANNELS: tuple[tuple[str, object], ...] = (
    (
        "auras.py (attached ability cost reduction)",
        lambda card, s: s in aura_cost_reduction_sentences(card.oracle_text or ""),
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
)


def _channel_for(sentence: str, card=None) -> str | None:
    for label, predicate in CHANNELS:
        if predicate(sentence):
            return label
    if card is not None:
        for label, predicate in CARD_CHANNELS:
            if predicate(card, sentence):
                return label
    return None


def analyze_card(card, hooked: set[str], run_probe: bool = True) -> CardCoverage:
    coverage = CardCoverage(card.name, supported=True)
    program = compile_card_oracle(card)
    if not program.supported:
        coverage.supported = False
        return coverage

    acknowledged_map = ACKNOWLEDGED.get(card.name, {})
    # Every printed line the compiled program kept an ability for, normalized the
    # same way the sentences below are, so the two can be compared at all.
    compiled_lines = {
        normalize_creature_line(ability.source_line or "").strip(" .")
        for ability in (*program.activated_abilities, *program.triggered_abilities)
        if ability.supported and ability.source_line
    }
    # Instruction kinds this card's rules actually produced, for the card-wide
    # HANDLER_CLAIMS pass below (a handler may implement a rider sentence that
    # sits on a DIFFERENT oracle line than the rule's anchor — Siren's Call's
    # delayed-destroy line rides on the attack-forcing rule's handler).
    seen_kinds: set[str] = set()

    def claim_sentence(
        sentence: str,
        activated: bool,
        owner_kind: str | None = None,
        trigger_prefix: str | None = None,
        cost_prefix: str | None = None,
    ) -> None:
        # A trailing sentence the owning rule's HANDLER implements (declared
        # in HANDLER_CLAIMS) is claimed by that handler.
        if owner_kind is not None and any(
            pattern in sentence for pattern in HANDLER_CLAIMS.get(owner_kind, ())
        ):
            coverage.claims.append((sentence, f"handler ← {owner_kind}"))
            return
        instruction, _ = _rule_match(
            sentence, activated, card.name, trigger_prefix, cost_prefix
        )
        if instruction is not None:
            seen_kinds.add(instruction.kind)
            coverage.claims.append((sentence, f"parse rule → {instruction.kind}"))
            if run_probe:
                ignored = _probe(
                    sentence, activated, card.name, trigger_prefix, cost_prefix
                )
                if ignored:
                    coverage.probe_findings.append((sentence, ignored))
            return
        channel = _channel_for(sentence, card)
        if channel is not None:
            coverage.claims.append((sentence, channel))
            return
        if sentence in acknowledged_map:
            coverage.acknowledged.append((sentence, acknowledged_map[sentence]))
            return
        if card.name in hooked:
            coverage.claims.append((sentence, "card_hooks bespoke (name-keyed)"))
            return
        # The last question, and the strongest evidence there is: **did the
        # compiler build an ability out of this line?** Every channel above
        # attributes a sentence to the module that carries it out, which is what
        # the report is for; this one only says that something did.
        #
        # It is asked last because it is the least informative answer, and asked
        # at all because the readers above are each written against one line in
        # isolation while the compiler reads a line *in its card*. A trigger
        # whose condition needs the permanent's own type, a modal head whose
        # modes are the lines below it, an ability whose cost is on the line
        # before — each is unsupported alone and compiled in place.
        if sentence in compiled_lines:
            coverage.claims.append((sentence, "compiled ability"))
            return
        coverage.unclaimed.append(sentence)

    def claim_clause(
        clause: str,
        activated: bool,
        trigger_prefix: str | None = None,
        cost_prefix: str | None = None,
    ) -> None:
        clause = clause.strip(" .")
        if not clause:
            return
        sents = _sentences(clause)
        instruction, kind = _rule_match(
            clause, activated, card.name, trigger_prefix, cost_prefix
        )
        if instruction is not None and len(sents) > 1:
            # A rule matched the whole clause — but a substring-anchored rule
            # may only have needed the first sentence(s). Claim the MINIMAL
            # sentence prefix that reproduces the identical parse; trailing
            # sentences must earn their own claim (this is what catches a
            # multi-sentence rider silently riding along).
            # Compared on the instruction alone, not the effect_kind label: with
            # two front ends in play a prefix may be claimed by the grammar and
            # the full clause by a legacy rule, and the labels differ even when
            # the produced instruction is identical. The instruction is what
            # decides whether the trailing sentences mattered.
            def _same(text: str) -> bool:
                instr, _ = _rule_match(
                    text, activated, card.name, trigger_prefix, cost_prefix
                )
                return instr is not None and instr == instruction

            for k in range(1, len(sents) + 1):
                if _same(". ".join(sents[:k])):
                    break
            claimed, rest = sents[:k], sents[k:]
            if k == len(sents):
                # No prefix short of the whole clause reproduces the parse. The
                # rule's anchor may still sit in a *trailing* sentence, in which
                # case a prefix search can never find it and the leading
                # sentences would be claimed without implementing anything —
                # exactly the silent-rider bug this script exists to catch. Fall
                # back to the smallest single sentence that reproduces it.
                single = next((s for s in sents if _same(s)), None)
                if single is not None:
                    claimed, rest = [single], [s for s in sents if s != single]
            seen_kinds.add(instruction.kind)
            claimed_text = ". ".join(claimed)
            coverage.claims.append((claimed_text, f"parse rule → {instruction.kind}"))
            if run_probe:
                ignored = _probe(
                    claimed_text, activated, card.name, trigger_prefix, cost_prefix
                )
                if ignored:
                    coverage.probe_findings.append((claimed_text, ignored))
            for sentence in rest:
                claim_sentence(
                    sentence, activated,
                    owner_kind=instruction.kind, trigger_prefix=trigger_prefix,
                    cost_prefix=cost_prefix,
                )
            return
        if instruction is not None:
            seen_kinds.add(instruction.kind)
            coverage.claims.append((clause, f"parse rule → {instruction.kind}"))
            if run_probe:
                ignored = _probe(
                    clause, activated, card.name, trigger_prefix, cost_prefix
                )
                if ignored:
                    coverage.probe_findings.append((clause, ignored))
            return
        for sentence in sents:
            claim_sentence(
                sentence, activated,
                trigger_prefix=trigger_prefix, cost_prefix=cost_prefix,
            )

    text = expand_ability_lines(
        card.oracle_text or "", card_name=card.name, legendary=card.is_legendary
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = normalize_creature_line(line)
        if not normalized:
            continue  # pure reminder text

        if line.startswith("•"):
            # A modal spell bullet — parse_modal_options feeds each through the
            # rule registry exactly like a spell clause.
            claim_clause(normalized.lstrip("• "), activated=False)
            continue
        if _is_supported_keyword_line(line):
            coverage.claims.append((normalized, "keyword table"))
            continue
        # Before the static-line gate, which now delegates to this table and
        # would otherwise absorb the attribution: the report is more use naming
        # the module that carries a line out than the gate that admits it.
        if cost_modifiers_for(normalized):
            coverage.claims.append((normalized, "cost_modifiers.py"))
            continue
        # With the card's **name**, because the gate collapses a legendary's
        # self-reference ("Gadrak can't attack unless…", "during your turn,
        # Radha has first strike") before matching. Called without it, every
        # such line read as unclaimed while the compiler admitted it — the same
        # name the two ability parsers below are already given.
        if _is_supported_static_creature_line(line, card.name):
            coverage.claims.append((normalized, "static-line table"))
            continue

        # The card's name goes to both ability parsers, because the compiler
        # passes it: `card_hooks.CARD_LINE_INSTRUCTIONS` is keyed by (name,
        # line), so without it every hooked ability reads as unsupported here
        # and its whole line lands in the unclaimed list. That went unnoticed
        # while the legacy registry answered for those lines too.
        trig = _parse_triggered_ability(line, card.name)
        if trig is not None:
            # Through the one reader, and **with the card's name** — the line
            # above already passes it. Called without it, a card whose
            # condition names itself (Axelrod Gunnarson, Nicol Bolas) returned
            # a None condition beside a non-None ability and crashed on
            # `.raw_text`. That is the third reader of this table found this
            # hour: the compiler, `test_grammar_lowering`'s guard, and here.
            condition, remainder = trigger_condition_of_line(line, card.name)
            if not trig.supported:
                # A trigger the compiler can't run, on a card that still
                # compiles supported. It may be implemented out-of-band (an
                # attach-time aura effect, a card hook) — try those channels
                # before calling it unclaimed.
                channel = _channel_for(normalized)
                if channel is not None:
                    coverage.claims.append((normalized, channel))
                elif card.name in hooked:
                    coverage.claims.append((normalized, "card_hooks bespoke (name-keyed)"))
                elif normalized in acknowledged_map:
                    coverage.acknowledged.append((normalized, acknowledged_map[normalized]))
                else:
                    coverage.unclaimed.append(normalized)
                continue
            coverage.claims.append((condition.raw_text, f"trigger table → {trig.condition.kind}"))
            claim_clause(
                remainder.lstrip(": "), activated=False,
                trigger_prefix=condition.raw_text,
            )
            continue

        # A **loyalty** ability (CR 606.3). Read before the ordinary activated
        # one because the ordinary reader wants a mana cost and a loyalty symbol
        # is not one — without this, every "+1: …" line on every planeswalker
        # falls through to the spell-clause claim, fails there, and the whole
        # line reads as unclaimed. M21 is the first set in the pool with
        # planeswalkers in it, so this is the first run where that showed.
        #
        # The split is the compiler's own: the symbol is the cost, the rest is
        # the effect, and the effect goes to the same front ends every other
        # clause does.
        loyalty = _parse_loyalty_ability(line, card.name)
        if loyalty is not None:
            if not loyalty.supported:
                if normalized in acknowledged_map:
                    coverage.acknowledged.append((normalized, acknowledged_map[normalized]))
                else:
                    coverage.unclaimed.append(normalized)
                continue
            coverage.claims.append((normalized.split(":", 1)[0], "loyalty cost"))
            claim_clause(loyalty.normalized_effect, activated=True)
            continue

        ability = _parse_activated_ability(line, card.name)
        if ability is not None:
            if not ability.supported:
                if normalized in acknowledged_map:
                    coverage.acknowledged.append((normalized, acknowledged_map[normalized]))
                else:
                    coverage.unclaimed.append(normalized)
                continue
            cost_clause = normalized.split(":", 1)[0]
            coverage.claims.append((cost_clause, "activation cost"))
            # The cost goes back to the effect as a prefix, the exact mirror of
            # *trigger_prefix* above and for the same reason. An activation cost
            # is paid before the ability goes on the stack (CR 602.2b), so what
            # it ate is a record the effect may read back — "If the discarded
            # card was a land card…" (Land's Edge) names a card only the
            # "Discard a card:" cost binds, and `lower_ability` seeds it from
            # `_COST_PRODUCES` with both halves of the colon in view. Read
            # without its cost the clause refuses, so the sentence looked
            # unclaimed while the compiler was reading it exactly this way. The
            # probe re-parses through the same path, so deleting "land" from it
            # still has to change the parse.
            claim_clause(
                ability.normalized_effect, activated=True, cost_prefix=cost_clause,
            )
            continue

        claim_clause(normalized, activated=False)

    # Card-wide HANDLER_CLAIMS pass: a rider sentence on a different oracle
    # line than its rule's anchor is still implemented by that rule's handler,
    # but only counts when this card really produced that instruction kind.
    if coverage.unclaimed and seen_kinds:
        still_unclaimed: list[str] = []
        for sentence in coverage.unclaimed:
            owner = next(
                (
                    kind
                    for kind in sorted(seen_kinds)
                    if any(pattern in sentence for pattern in HANDLER_CLAIMS.get(kind, ()))
                ),
                None,
            )
            if owner is not None:
                coverage.claims.append((sentence, f"handler ← {owner}"))
            else:
                still_unclaimed.append(sentence)
        coverage.unclaimed = still_unclaimed

    return coverage


def load_pool() -> list:
    pool: dict[str, object] = {}
    for path in CARD_PATHS:
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return [pool[name] for name in sorted(pool)]


def analyze_pool(run_probe: bool = True) -> list[CardCoverage]:
    hooked = _hooked_names()
    coverages = []
    for card in load_pool():
        coverage = analyze_card(card, hooked, run_probe=run_probe)
        coverage.shipped = card.name in SHIPPED_NAMES
        coverages.append(coverage)
    return coverages


def collect_findings(coverages: list[CardCoverage]):
    """The guard-test view: unacknowledged problems + stale acknowledgments.

    **Shipped cards only.** A measured set is ingested precisely so its gaps can
    be *counted* before anyone has closed them, so failing on them would make
    every ingest red on arrival. They are reported instead, by
    :func:`collect_measured_findings` and the section it feeds.
    """
    coverages = [c for c in coverages if c.shipped]
    unclaimed = [(c.name, s) for c in coverages for s in c.unclaimed]

    seen_acknowledged = {(c.name, s) for c in coverages for s, _ in c.acknowledged}
    stale_acknowledged = [
        (name, sentence)
        for name, entries in ACKNOWLEDGED.items()
        for sentence in entries
        if (name, sentence) not in seen_acknowledged
        and entries  # skip empty placeholder entries
    ]

    baseline = load_probe_baseline()
    probe_now = {(c.name, s): words for c in coverages for s, words in c.probe_findings}
    new_probe = {
        key: words for key, words in probe_now.items()
        if baseline.get(key) != words
    }
    stale_probe = [key for key in baseline if key not in probe_now]
    return unclaimed, stale_acknowledged, new_probe, stale_probe


def collect_measured_findings(coverages: list[CardCoverage]):
    """The same question asked of the measured sets, as a *backlog* rather than
    a gate: ``(name, sentence)`` for every supported-but-unclaimed sentence.

    This is the debt behind a measured set's supported count. A card here
    compiles, is counted in the set's progress number, and carries a printed
    line no code implements — and `--hollow-lines` cannot see most of them,
    because a line that yields no *ability part* leaves nothing to be hollow.
    """
    return [
        (c.name, sentence)
        for c in coverages
        if not c.shipped
        for sentence in c.unclaimed
    ]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render_markdown(coverages: list[CardCoverage]) -> str:
    measured = [c for c in coverages if c.supported and not c.shipped and c.unclaimed]
    coverages = [c for c in coverages if c.shipped]
    supported = [c for c in coverages if c.supported]
    fully = [c for c in supported if not c.unclaimed and not c.acknowledged]
    with_ack = [c for c in supported if c.acknowledged]
    with_unclaimed = [c for c in supported if c.unclaimed]
    probe_cards = [c for c in supported if c.probe_findings]

    channel_counts: dict[str, int] = {}
    for c in supported:
        for _, channel in c.claims:
            key = channel.split(" → ")[0]
            channel_counts[key] = channel_counts.get(key, 0) + 1

    lines = [
        "# Oracle Text Parse Coverage",
        "",
        "Tracks whether every sentence of every supported card's oracle text is",
        "claimed by a known consumer (parse rules, compiler tables, text-keyed",
        "engine channels, card hooks). Generated by `scripts/parse_coverage.py`;",
        "the guard test `tests/engine/test_parse_coverage.py` fails on new",
        "unclaimed text. Do not edit by hand.",
        "",
        f"- Supported cards analyzed: **{len(supported)}**",
        f"- Fully claimed: **{len(fully)}**",
        f"- With acknowledged simplifications: **{len(with_ack)}**",
        f"- With UNCLAIMED text (must fix or acknowledge): **{len(with_unclaimed)}**",
        f"- With deletion-probe findings (ignored words): **{len(probe_cards)}**",
        "",
    ]

    if measured:
        sentences = sum(len(c.unclaimed) for c in measured)
        lines += [
            "## Measured sets — reported, not gated",
            "",
            "Cards in a `measured` set (see `cards/manifest.json`) that the",
            "compiler calls **supported** while carrying a printed line nothing",
            "implements. They are the debt behind that set's progress number, and",
            "`--hollow-lines` sees only the ones that produced an *ability part* —",
            "a line yielding nothing at all leaves that probe nothing to find.",
            "",
            "Not gated, for the reason `GRAMMAR_COVERAGE.md`'s floors and",
            "`HOOK_RELIANCE.md`'s ceilings exclude the same sets: a ratchet over a",
            "set nobody has implemented fires on its composition rather than on",
            "anything anyone did, and every ingest would arrive red.",
            "",
            f"**{sentences} unclaimed sentence(s) across {len(measured)} supported card(s).**",
            "",
        ]
        for c in measured:
            lines.append(f"- **{c.name}**")
            lines += [f"  - `{s}`" for s in c.unclaimed]
        lines.append("")

    if with_unclaimed:
        lines += ["## Unclaimed text — fix the parser or acknowledge the simplification", ""]
        for c in with_unclaimed:
            lines.append(f"- **{c.name}**")
            lines += [f"  - `{s}`" for s in c.unclaimed]
        lines.append("")

    if with_ack:
        lines += [
            "## Acknowledged simplifications",
            "",
            "| Card | Sentence | Why it is acceptable |",
            "| --- | --- | --- |",
        ]
        for c in with_ack:
            for sentence, reason in c.acknowledged:
                lines.append(f"| {c.name} | `{sentence[:80]}` | {reason} |")
        lines.append("")

    if probe_cards:
        lines += [
            "## Deletion-probe findings (words a matching rule ignored)",
            "",
            "A rule matched the clause but produced an identical parse without",
            "these words — riders and qualifiers in this list are candidates for",
            "the Hasran-Ogress class of bug. Ratcheted via `PROBE_ACKNOWLEDGED`.",
            "",
            "| Card | Clause | Ignored words |",
            "| --- | --- | --- |",
        ]
        for c in probe_cards:
            for sentence, words in c.probe_findings:
                lines.append(f"| {c.name} | `{sentence[:70]}` | {' '.join(words)} |")
        lines.append("")

    lines += ["## Claims by channel", "", "| Channel | Sentences claimed |", "| --- | --- |"]
    for channel, count in sorted(channel_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {channel} | {count} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on unacknowledged/stale findings")
    parser.add_argument(
        "--accept-probe", action="store_true",
        help="snapshot the current deletion-probe findings as the reviewed baseline",
    )
    args = parser.parse_args()

    coverages = analyze_pool()
    measured = collect_measured_findings(coverages)

    if args.accept_probe:
        # **The shipped half, the same one `collect_findings` gates on.** This
        # snapshotted every coverage, which since the round that pointed the
        # analysis at measured sets too meant writing measured findings into a
        # baseline the check then compares against shipped cards only — so
        # accepting a single reviewed finding wrote 90 entries the very next
        # `--check` reported as stale. The ratchet has one denominator or it
        # oscillates.
        findings = {
            (c.name, s): words
            for c in coverages if c.shipped
            for s, words in c.probe_findings
        }
        save_probe_baseline(findings)
        print(f"accepted {len(findings)} probe finding(s) into {PROBE_BASELINE_PATH.name}")

    unclaimed, stale_ack, new_probe, stale_probe = collect_findings(coverages)

    if args.check:
        ok = True
        if unclaimed:
            ok = False
            print("UNCLAIMED oracle text on supported cards (fix the parser, add the")
            print("implementing channel to CHANNELS, or acknowledge in ACKNOWLEDGED):")
            for name, sentence in unclaimed:
                print(f"  {name}: {sentence}")
        if stale_ack:
            ok = False
            print("STALE acknowledged entries (no longer occur — remove them):")
            for name, sentence in stale_ack:
                print(f"  {name}: {sentence}")
        if new_probe:
            ok = False
            print("NEW deletion-probe findings — a rule matched but ignored these words.")
            print("Review each (is a rider being silently dropped?), then either fix the")
            print("rule or run scripts/parse_coverage.py --accept-probe to accept:")
            for (name, sentence), words in new_probe.items():
                print(f"  {name}: {sentence[:80]!r} ignored={list(words)}")
        if stale_probe:
            ok = False
            print("STALE probe-baseline entries (no longer occur — rerun --accept-probe):")
            for key in stale_probe:
                print(f"  {key}")
        if measured:
            cards = len({name for name, _ in measured})
            print(
                f"(measured sets carry {len(measured)} unclaimed sentence(s) on "
                f"{cards} supported card(s) — reported in PARSE_COVERAGE.md, "
                "not gated here)"
            )
        return 0 if ok else 1

    OUTPUT_PATH.write_text(render_markdown(coverages), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    if measured:
        cards = len({name for name, _ in measured})
        print(
            f"measured sets: {len(measured)} unclaimed sentence(s) on {cards} "
            "supported card(s) — reported, not gated"
        )
    if unclaimed:
        print(f"WARNING: {len(unclaimed)} unclaimed sentence(s) — run with --check for details")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

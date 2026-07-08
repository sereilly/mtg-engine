"""Generate PARSE_COVERAGE.md — oracle-text parse-coverage tracker.

The oracle compiler degrades gracefully: a card whose text matches nothing is
reported unsupported. What it does NOT catch is *partial* silence — a card that
compiles "supported" while some of its text was never parsed by anything (the
failure mode behind the Hasran Ogress / Army of Allah / Metamorphosis bugs:
a broad rule matched part of a clause and the rest was silently dropped).

This script closes that gap offline. For every supported card in the pool it
verifies that each sentence of oracle text is claimed by a known consumer:

- the parse-rule registry (whole-clause or per-sentence match),
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
from engine.cast_restrictions import CAST_RESTRICTIONS  # noqa: E402
from engine.oracle import (  # noqa: E402
    _is_supported_keyword_line,
    _is_supported_static_creature_line,
    _parse_activated_ability,
    _parse_trigger_condition,
    _parse_triggered_ability,
    compile_card_oracle,
    expand_modal_activated_lines,
    normalize_creature_line,
)
from engine.parsing import parse_primary_instruction  # noqa: E402

CARD_PATHS = [
    REPO_ROOT / "cards" / "LEA_cards.json",
    REPO_ROOT / "cards" / "LEB_cards.json",
    REPO_ROOT / "cards" / "2ED_cards.json",
    REPO_ROOT / "cards" / "ARN_cards.json",
]
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
    "if you would gain life, draw that many cards instead",              # replacements.py (Lich)
    "damage that would reduce your life total to less than 1 reduces it to 1 instead",  # replacements.py (Ali from Cairo)
    "whenever you're dealt damage, sacrifice that many nontoken permanents",  # effects.py (Lich)
    "whenever you're dealt damage, put that many vitality counters on this aura",  # upkeep_step vitality flow (Living Artifact)
    "you don't lose the game for having 0 or less life",                 # game_ending.py (Lich)
    "as this enchantment enters, you lose life equal to your life total",  # permanent_state.py:195 (Lich)
    "you have no maximum hand size",                                     # permanent_state.py:189 (Library of Leng)
    "if an effect causes you to discard a card, discard it, but you may put it on top of your library instead",  # effects._discard_card (Library of Leng)
    "you may play any number of lands on each of your turns",            # stack_casting._fastbond_count (Fastbond)
    "you may spend white mana as though it were red mana",               # permanent_state.py:192 (Sunglasses of Urza)
    "doesn't untap during your untap step",                              # untap_step.py (Time Vault, Basalt Monolith)
    "you may choose not to untap this creature during your untap step",  # untap_step.py (Old Man of the Sea)
    "if you would begin your turn while this artifact is tapped, you may skip that turn instead",  # beginning_phase.py (Time Vault)
    "this spell costs {1} more to cast for each target beyond the first",  # stack_casting.py:1210 (Fireball)
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
    # queue_permanent_ability's per-ability textual gates (stack_casting.py).
    "activate only during your upkeep",
    "only during your turn",
    "once each turn",
    "activate only if you have exactly seven cards in hand",
    "x can't be 0",
    "activate only as a sorcery",
    "activate only during combat",
    "activate only during the end of combat step",
    "activate only during an opponent's turn, before attackers are declared",
    # Ifh-Bíff Efreet: enforced (and enabled) in queue_permanent_ability's
    # source_controller_index path.
    "any player may activate this ability",
    # Personal Incarnation: owner-only activation (also lets the owner activate
    # while an opponent controls the creature).
    "only this creatures owner may activate this ability",
)


def _matches_any(sentence: str, patterns) -> bool:
    return any(p.search(sentence) if hasattr(p, "search") else p in sentence for p in patterns)


CHANNELS: tuple[tuple[str, object], ...] = (
    # (channel label, predicate(sentence) -> bool)
    ("aura enchant noun (oracle_instructions attach)", lambda s: s.startswith("enchant ")),
    ("aura static (oracle_instructions/permanent_state)", lambda s: _matches_any(s, _AURA_STATIC_PATTERNS)),
    ("cast_restrictions.py", lambda s: any(r.phrase in s for r in CAST_RESTRICTIONS)),
    ("activation gate (stack_casting)", lambda s: any(g in s for g in _ACTIVATION_GATES)),
    ("mixin text scan", lambda s: _matches_any(s, _MIXIN_TEXT_SCANS)),
    ("modal machinery", lambda s: s.startswith("choose one")),
    ("x spend color (stack_casting)", lambda s: bool(re.match(r"^spend only (?:white|blue|black|red|green) mana on x$", s))),
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
    # Animate Dead: the attach flow arms sacrifice_attached_on_leave, honored
    # by _remove_aura_effects.
    "reanimate_creature": (
        "when this aura leaves the battlefield, that creature's controller sacrifices it",
    ),
}


ACKNOWLEDGED: dict[str, dict[str, str]] = {
    "Shahrazad": {
        "players play a magic subgame, using their libraries as their decks": (
            "subgames are far out of scope; the card resolves with the life-halving only"
        ),
        "each player who doesn't win the subgame loses half their life, rounded up": (
            "applied directly to the non-caster instead of the subgame loser"
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
    claims: list[tuple[str, str]] = field(default_factory=list)      # (sentence, channel)
    unclaimed: list[str] = field(default_factory=list)               # sentences
    acknowledged: list[tuple[str, str]] = field(default_factory=list)  # (sentence, reason)
    probe_findings: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)  # (sentence, words)


def _sentences(text: str) -> list[str]:
    return [s.strip(" .") for s in _SENTENCE_SPLIT.split(text) if s.strip(" .")]


def _rule_match(clause: str, activated: bool):
    instruction, kind = parse_primary_instruction(clause, activated=activated)
    return instruction, kind


def _probe(clause: str, activated: bool) -> tuple[str, ...]:
    """Words in *clause* whose deletion leaves the parse identical — i.e.
    words the parser demonstrably ignored."""
    base_instr, base_kind = _rule_match(clause, activated)
    if base_instr is None:
        return ()
    words = clause.split()
    ignored: list[str] = []
    for i, word in enumerate(words):
        if word.lower().strip(".,;:'\"") in _PROBE_STOPWORDS:
            continue
        shorter = " ".join(words[:i] + words[i + 1:])
        instr, kind = _rule_match(shorter, activated)
        if (
            instr is not None
            and instr.kind == base_instr.kind
            and instr.payload == base_instr.payload
            and kind == base_kind
        ):
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


def _channel_for(sentence: str) -> str | None:
    for label, predicate in CHANNELS:
        if predicate(sentence):
            return label
    return None


def analyze_card(card, hooked: set[str], run_probe: bool = True) -> CardCoverage:
    coverage = CardCoverage(card.name, supported=True)
    program = compile_card_oracle(card)
    if not program.supported:
        coverage.supported = False
        return coverage

    acknowledged_map = ACKNOWLEDGED.get(card.name, {})
    # Instruction kinds this card's rules actually produced, for the card-wide
    # HANDLER_CLAIMS pass below (a handler may implement a rider sentence that
    # sits on a DIFFERENT oracle line than the rule's anchor — Siren's Call's
    # delayed-destroy line rides on the attack-forcing rule's handler).
    seen_kinds: set[str] = set()

    def claim_sentence(sentence: str, activated: bool, owner_kind: str | None = None) -> None:
        # A trailing sentence the owning rule's HANDLER implements (declared
        # in HANDLER_CLAIMS) is claimed by that handler.
        if owner_kind is not None and any(
            pattern in sentence for pattern in HANDLER_CLAIMS.get(owner_kind, ())
        ):
            coverage.claims.append((sentence, f"handler ← {owner_kind}"))
            return
        instruction, _ = _rule_match(sentence, activated)
        if instruction is not None:
            seen_kinds.add(instruction.kind)
            coverage.claims.append((sentence, f"parse rule → {instruction.kind}"))
            if run_probe:
                ignored = _probe(sentence, activated)
                if ignored:
                    coverage.probe_findings.append((sentence, ignored))
            return
        channel = _channel_for(sentence)
        if channel is not None:
            coverage.claims.append((sentence, channel))
            return
        if sentence in acknowledged_map:
            coverage.acknowledged.append((sentence, acknowledged_map[sentence]))
            return
        if card.name in hooked:
            coverage.claims.append((sentence, "card_hooks bespoke (name-keyed)"))
            return
        coverage.unclaimed.append(sentence)

    def claim_clause(clause: str, activated: bool) -> None:
        clause = clause.strip(" .")
        if not clause:
            return
        sents = _sentences(clause)
        instruction, kind = _rule_match(clause, activated)
        if instruction is not None and len(sents) > 1:
            # A rule matched the whole clause — but a substring-anchored rule
            # may only have needed the first sentence(s). Claim the MINIMAL
            # sentence prefix that reproduces the identical parse; trailing
            # sentences must earn their own claim (this is what catches a
            # multi-sentence rider silently riding along).
            for k in range(1, len(sents) + 1):
                prefix = ". ".join(sents[:k])
                prefix_instr, prefix_kind = _rule_match(prefix, activated)
                if (
                    prefix_instr is not None
                    and prefix_instr.kind == instruction.kind
                    and prefix_instr.payload == instruction.payload
                    and prefix_kind == kind
                ):
                    break
            claimed_prefix = ". ".join(sents[:k])
            seen_kinds.add(instruction.kind)
            coverage.claims.append((claimed_prefix, f"parse rule → {instruction.kind}"))
            if run_probe:
                ignored = _probe(claimed_prefix, activated)
                if ignored:
                    coverage.probe_findings.append((claimed_prefix, ignored))
            for sentence in sents[k:]:
                claim_sentence(sentence, activated, owner_kind=instruction.kind)
            return
        if instruction is not None:
            seen_kinds.add(instruction.kind)
            coverage.claims.append((clause, f"parse rule → {instruction.kind}"))
            if run_probe:
                ignored = _probe(clause, activated)
                if ignored:
                    coverage.probe_findings.append((clause, ignored))
            return
        for sentence in sents:
            claim_sentence(sentence, activated)

    text = expand_modal_activated_lines(card.oracle_text or "")
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
        if _is_supported_static_creature_line(line):
            coverage.claims.append((normalized, "static-line table"))
            continue

        trig = _parse_triggered_ability(line)
        if trig is not None:
            condition, remainder = _parse_trigger_condition(normalized)
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
            claim_clause(remainder.lstrip(": "), activated=False)
            continue

        ability = _parse_activated_ability(line)
        if ability is not None:
            if not ability.supported:
                if normalized in acknowledged_map:
                    coverage.acknowledged.append((normalized, acknowledged_map[normalized]))
                else:
                    coverage.unclaimed.append(normalized)
                continue
            coverage.claims.append((normalized.split(":", 1)[0], "activation cost"))
            claim_clause(ability.normalized_effect, activated=True)
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
    return [analyze_card(card, hooked, run_probe=run_probe) for card in load_pool()]


def collect_findings(coverages: list[CardCoverage]):
    """The guard-test view: unacknowledged problems + stale acknowledgments."""
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


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render_markdown(coverages: list[CardCoverage]) -> str:
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

    if args.accept_probe:
        findings = {(c.name, s): words for c in coverages for s, words in c.probe_findings}
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
        return 0 if ok else 1

    OUTPUT_PATH.write_text(render_markdown(coverages), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    if unclaimed:
        print(f"WARNING: {len(unclaimed)} unclaimed sentence(s) — run with --check for details")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

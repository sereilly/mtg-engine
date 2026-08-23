from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import load_cards
from engine.reporting import build_support_report
from set_argument import add_set_argument, resolve_set


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show card support coverage for the whole manifest pool, or one set"
    )
    # Defaulting to one hardcoded set made this report answer a much narrower
    # question than it appeared to: it printed LEA's 290 cards while the pool
    # had grown to several sets, so "no unsupported cards" was true of Alpha
    # and said nothing about the rest. The manifest is the single registry of
    # the pool; this reads it like everything else does, and prints which pool
    # the numbers below describe.
    add_set_argument(parser, default=None)
    parser.add_argument(
        "--hollow-lines",
        action="store_true",
        help=(
            "Census the Nine Lives class: supported cards carrying an ability "
            "part that compiled to no instruction. A card is supported when "
            "any line is, so these are the lines support can hide — each "
            "needs a registry (aura death effects, draw-step modifiers, enter "
            "effects, …) verified to actually implement it, or it is a card "
            "that works less than it reports."
        ),
    )
    parser.add_argument(
        "--refusals",
        action="store_true",
        help=(
            "For every unsupported card, every refused line and the exact "
            "refusal it meets — not just the first, which is all the plain "
            "census quotes (SET_PLAYBOOK.md Phase 1). This is the work list a "
            "backlog round is planned from: lines group by refusal site "
            "mechanically, where the reason histogram groups them by prose."
        ),
    )
    return parser


def hollow_lines_report(cards) -> list[tuple[str, str, str]]:
    """``(card, part kind, source line)`` for every supported card whose
    compiled program carries an ability with no instruction behind it."""
    from engine.oracle import compile_card_oracle

    findings: list[tuple[str, str, str]] = []
    for card in cards:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for ability in program.activated_abilities:
            if not ability.supported or ability.instruction is None:
                findings.append((card.name, "activated", ability.source_line))
        for trigger in program.triggered_abilities:
            if not trigger.supported or trigger.instruction is None:
                findings.append((card.name, "triggered", trigger.source_line))
        for mode in program.modes:
            if mode.instruction is None:
                findings.append((card.name, "mode", mode.label))
    return findings


def refusals_report(cards) -> list[tuple[str, str, str, list[tuple[str, str, str]]]]:
    """``(card, primary type, headline reason, line findings)`` for every
    unsupported card, where each line finding is ``(status, line, detail)``.

    ``status`` is ``"refused"`` (the grammar could not read the line, detail is
    the parse error), ``"unlowered"`` (parsed but no instructions, detail is
    the lowering error), or ``"clean"`` (the grammar reads it; the refusal that
    costs the card its support is in the compiler front end — the headline
    reason names it). Lines come from ``expand_ability_lines`` because that is
    the text the compiler classifies; reading ``oracle_text`` raw would census
    a different card (an equip line, most visibly).
    """
    from engine.grammar import compile_line
    from engine.oracle import compile_card_oracle, expand_ability_lines

    findings: list[tuple[str, str, str, list[tuple[str, str, str]]]] = []
    for card in cards:
        program = compile_card_oracle(card)
        if program.supported:
            continue
        lines: list[tuple[str, str, str]] = []
        for raw in expand_ability_lines(card.oracle_text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            result = compile_line(line, card_name=card.name)
            if result.blank:
                continue
            if result.parse_error:
                lines.append(("refused", line, result.parse_error))
            elif result.lowering_error:
                lines.append(("unlowered", line, result.lowering_error))
            else:
                lines.append(("clean", line, ""))
        findings.append((card.name, card.primary_type, program.reason, lines))
    return findings


def print_refusals(findings) -> None:
    from collections import Counter

    refused_total = sum(
        1 for _, _, _, lines in findings for status, _, _ in lines if status != "clean"
    )
    print(f"Unsupported cards: {len(findings)}; refused lines: {refused_total}")
    print("(the plain census quotes only the first refused line per card)")
    print()

    reason_lines: Counter = Counter()
    reason_texts: dict[str, set] = {}
    front_end_only: list[tuple[str, str]] = []
    for name, primary_type, headline, lines in findings:
        print(f"{name} [{primary_type}] — {headline}")
        clean = 0
        for status, line, detail in lines:
            if status == "clean":
                clean += 1
                continue
            print(f"  {status}: {line}")
            print(f"    ^ {detail}")
            reason_lines[detail] += 1
            reason_texts.setdefault(detail, set()).add(" ".join(line.split()).lower())
        if clean and len(lines) > clean:
            print(f"  ({clean} other line(s) read fine)")
        if clean == len(lines):
            # Every line is grammar-clean and the card is still unsupported:
            # the refusal is a front-end classification (a trigger condition
            # not in the pattern table, a blocklisted keyword, an activation
            # restriction nothing enforces). The headline reason is the site.
            front_end_only.append((name, headline))
            print("  (every line grammar-clean — the refusal is the headline reason)")
    print()
    print("By refusal site (lines / distinct sentences):")
    for detail, count in reason_lines.most_common():
        print(f"  {count} / {len(reason_texts[detail])}: {detail}")
    if front_end_only:
        print()
        print(f"Front-end refusals ({len(front_end_only)} card(s), no grammar-refused line):")
        for name, headline in front_end_only:
            print(f"  {name}: {headline}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    selection = resolve_set(parser, args)
    if args.hollow_lines and args.refusals:
        parser.error("--hollow-lines and --refusals are separate censuses; pick one")

    if args.refusals:
        findings = refusals_report(load_cards(selection.paths))
        print(f"Pool: {selection.label}")
        print_refusals(findings)
        return 0

    if args.hollow_lines:
        findings = hollow_lines_report(load_cards(selection.paths))
        print(f"Pool: {selection.label}")
        print(f"Supported cards with an instruction-less ability part: "
              f"{len({name for name, _, _ in findings})} ({len(findings)} part(s))")
        for name, kind, line in findings:
            print(f"  {name} [{kind}]: {line}")
        if findings:
            print()
            print("Each line above leans on a registry the compiler cannot see —")
            print("verify the registry actually implements it (the Rock Hydra test:")
            print("give the behaviour a game and watch it happen, not the claim).")
        return 0

    report = build_support_report(load_cards(selection.paths))

    print(f"Pool: {selection.label}")
    print(f"Total cards: {report.total_cards}")
    print(f"Supported cards: {report.supported_cards}")
    print(f"Unsupported cards: {report.unsupported_cards}")
    print()
    print("By type:")
    for card_type, count in report.by_type.items():
        supported = report.supported_by_type.get(card_type, 0)
        print(f"  {card_type}: {supported}/{count} supported")

    print()
    print("Unsupported reason breakdown:")
    if not report.unsupported_reasons:
        print("  none")
    else:
        for reason, count in report.unsupported_reasons.items():
            print(f"  {reason}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

---
name: mtg-rules
description: 'Answer Magic: The Gathering rules questions using the Comprehensive Rules. Use for timing, priority, layers, replacement/prevention effects, state-based actions, combat, and card-interaction rulings. Always consult MagicCompRules.txt when rule text is needed.'
argument-hint: 'Describe the game state, cards involved, and your rules question.'
user-invocable: true
---

# MTG Rules Assistant

## Outcome
Provide accurate, rules-grounded answers to Magic: The Gathering questions, and reference the Comprehensive Rules source file in this workspace: [MagicCompRules.txt](../../../MagicCompRules.txt).

## When To Use
- Any question about how game mechanics resolve.
- Interactions involving multiple effects, triggers, or replacement effects.
- Priority, stack, APNAP ordering, combat timing, or state-based actions.
- Layer system questions (type/color/ability/power-toughness modifications).

## Procedure
1. Parse the question into a concrete game-state summary.
2. Identify the main rule domains involved (for example: priority, combat, layers, replacement effects).
3. Consult [MagicCompRules.txt](../../../MagicCompRules.txt) for relevant sections before finalizing any non-trivial ruling.
4. Build the ruling as an ordered sequence of game events.
5. Provide a concise final answer, then include the relevant rule references from [MagicCompRules.txt](../../../MagicCompRules.txt).

## Decision Points
- If the question is straightforward and commonly known, still verify against [MagicCompRules.txt](../../../MagicCompRules.txt) before giving definitive wording.
- If card text is missing or ambiguous, ask for exact Oracle text or card names before issuing a final ruling.
- If multiple interpretations remain possible, present each interpretation with the rule sections that differentiate them.

## Quality Checks
- The answer includes a clear ruling and a short reason.
- The reasoning order matches game engine timing (triggers, priority, SBA checks, resolution).
- At least one relevant rule citation is provided from [MagicCompRules.txt](../../../MagicCompRules.txt) for non-trivial rulings.
- Uncertainty is called out explicitly when required information is missing.

## Response Style
- Prefer precise, judge-like wording over informal guesses.
- Keep the final ruling brief, then add a compact "Why" section.
- Avoid inventing rules or citing sections that were not checked.
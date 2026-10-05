"""The `combat_restrictions` half of `lowering/categories.INSTRUCTION_CATEGORIES`.

Split out at the Phase 0 before Invasion, with `categories.py` at 929 lines —
71 under the thousand-line guard — and eight groups about to open, each of which
gives every instruction kind it invents a row there. That table has crossed the
guard on nobody's branch twice already: five groups' rows summed past it at
Visions' wave 1 and two groups' at Urza's Saga's wave 2, which is what
`_zone_categories` and `_pump_categories` record.

The seam is the one every earlier split of it used: take a whole **category**,
never a slice of the file. *Which* one was measured rather than read off the
row count. `damage` is the largest left by rows (36 to this one's 34); this is
the largest by lines (108 to 99) and the one that **grows** — 21 rows at
Tempest's Phase 0 and 34 now, thirteen added where `damage` added six and no
other category more than three. A pre-split is for the rows the next set will
add, so the half to move is the half they land in.

The line is a real one rather than a size cut, and the rows below had drawn it
one comment at a time ("filed with the family whose steps dispatch it",
"enforced by the declaration rather than by a handler"): every kind here is
answered by the **combat phase**. Twenty-four have an effect handler and all
twenty-four are in `engine/handlers/combat.py`, where what the handler writes is
a mark a combat step reads back. The other ten have no `EFFECT_HANDLERS` entry
at all — the declarations and the damage assignment
(`phases/declare_attackers_step.py`, `phases/declare_blockers_step.py`,
`combat_assignment.py`) read them straight off the compiled program. The
converse is not claimed: `evasion`'s four kinds and three of `prevention`'s
resolve in that handler module too and keep their own categories, because a
category names the migration family a kind belongs to and not where its handler
sits.

There was no family module to send these home to, which was the lead worth
ruling out. Five lowering modules build them — `combat`, `requirements`,
`_declaration_costs`, `assignment` and `control_flow` — so a family holding the
rows would hold four other modules' rows; and the one whose docstring states
this subject, `lowering/combat.py`, stands at 870 lines and would have reached
978. `zones.py` held its own category's rows once and gave them up at Tempest's
Phase 0 for exactly that: a registry with no call graph is what leaves a module
of dispatch.

A floor, not a family: 34 rows of data that import nothing, folded in by
`categories.py` with `update()` exactly as the pump, zone and ownership halves
are, so there is still one table, one row per kind, and
`INSTRUCTION_CATEGORIES`' address is unchanged for every reader. The module is
named for the family (`effects/combat.py`, `lowering/combat.py`); the category
is not renamed and must not be. **Not one row's value changed** — every value
below still reads "combat_restrictions" — because `GRAMMAR_CATEGORIES` is held
equal to the values the composed table declares and has no fallback underneath.

The rows are in the order they left in. Two comments moved down to the rows
they describe (`exempt_from_attack_tapping`, `remove_from_combat`), which had
drifted twenty lines below them.
"""

#: The `combat_restrictions` rows of `INSTRUCTION_CATEGORIES`, folded in by
#: `categories.py`.
COMBAT_INSTRUCTION_CATEGORIES: dict[str, str] = {
    # Restrictions on declaring attackers/blockers (CR 506, 509).
    "cant_attack_unless_defender_controls": "combat_restrictions",
    # CR 508.1c / 509.1b: a restriction on the whole declaration rather
    # than on the creature, so the count is payload and the check lives
    # where the declaration is assembled.
    "cant_attack_unless_others_attack": "combat_restrictions",
    # CR 508.1g printed on a permanent that names a class of creatures
    # rather than itself (Flooded Woodlands, Reclamation).
    "creatures_cant_attack_unless_sacrifice": "combat_restrictions",
    # War Tax and War Cadence: the same board-wide declaration toll with the
    # cost in mana and a window on it (CR 508.1g, CR 509.1d). Two kinds
    # because the gate that charges each is a different step of combat.
    "creatures_cant_attack_unless_pay_until_eot": "combat_restrictions",
    "creatures_cant_block_unless_pay_until_eot": "combat_restrictions",
    "cant_block_unless_others_block": "combat_restrictions",
    # "…unless a creature with greater power also attacks/blocks." (Okk.) The
    # same CR 508.1c / 509.1b declaration-wide restriction asking a comparison
    # instead of a count, so the same category and GRAMMAR_CATEGORIES is
    # unchanged.
    "cant_attack_unless_greater_power_attacks": "combat_restrictions",
    "cant_block_unless_greater_power_blocks": "combat_restrictions",
    # "…unless a black or green creature also attacks." (Scarred Puma.) The
    # same declaration-wide restriction again, asking for a companion that
    # answers a printed noun phrase rather than one that outpowers it.
    "cant_attack_unless_subject_attacks": "combat_restrictions",
    # "That creature can't attack during its controller's next turn." (Wall of
    # Dust's block trigger) — a one-shot stamp on the blocked creature, read
    # back by `can_attack` for exactly one of that controller's turns.
    "cant_attack_during_controllers_next_turn": "combat_restrictions",
    "cant_block_subject": "combat_restrictions",
    # Heat Wave: the same restriction printed about a described set of
    # blockers rather than about the permanent carrying it, so the
    # blocker gate finds it by scanning the board rather than by reading
    # the blocker's own program.
    "subject_cant_block_subject": "combat_restrictions",
    # The one-shot, turn-scoped blanket ("Creatures without flying can't block
    # this turn", Destructive Tampering's second mode).
    "cant_block_until_eot": "combat_restrictions",
    "target_cant_attack_until_eot": "combat_restrictions",
    "target_cant_block_source_until_eot": "combat_restrictions",
    "target_cant_block_until_eot": "combat_restrictions",
    # The permission twin of the two above (Yare): CR 509.1b's block-count
    # ceiling raised for a turn rather than a restriction imposed for one.
    "grant_additional_blocks_until_eot": "combat_restrictions",
    # "Creatures can't attack this turn." (Festival.) The same category as its
    # blocking twin above, so GRAMMAR_CATEGORIES is unchanged.
    "cant_attack_until_eot": "combat_restrictions",
    # "This creature can't attack unless you sacrifice two Islands."
    # (Leviathan.) A restriction with a cost behind it, enforced by the
    # declaration rather than by a handler — same category, so
    # GRAMMAR_CATEGORIES is unchanged.
    "cant_attack_unless_sacrifice": "combat_restrictions",
    # "This creature assigns no combat damage this turn." (Floral Spuzzem.)
    # CR 510.1's assignment switched off for one permanent — a restriction on
    # what the combat damage step does, so it files with the other CR 506/510
    # clauses.
    "assign_no_combat_damage_until_eot": "combat_restrictions",
    # "X target blocked creatures assign their combat damage this turn as
    # though they weren't blocked." (Outmaneuver.) The same CR 510.1
    # rewrite in the other direction, so the same category and
    # GRAMMAR_CATEGORIES is unchanged.
    "assign_as_unblocked_until_eot": "combat_restrictions",
    # "You may have this creature assign its combat damage as though it weren't
    # blocked." (Lone Wolf.) The row above with no window and the permanent
    # itself as subject, which makes it a **static** ability rather than a mark:
    # the combat damage step reads it off the compiled program at CR 510.1's
    # turn-based action, exactly as it reads the mark. Same category, so
    # GRAMMAR_CATEGORIES is unchanged.
    "may_assign_as_unblocked": "combat_restrictions",
    # "Attacking doesn't cause creatures you control to tap this combat…"
    # (Johan.) A restriction on what declaring an attacker does, so it files
    # with the other CR 506/508 clauses and GRAMMAR_CATEGORIES is unchanged.
    "exempt_from_attack_tapping": "combat_restrictions",
    # "…and remove it from combat" (Disharmony, CR 506.4c). A one-shot combat
    # action rather than a restriction, filed with the family whose steps
    # dispatch it.
    "remove_from_combat": "combat_restrictions",
    # "Target unblocked attacking creature becomes blocked." (Dazzling Beauty;
    # CR 509.1h.) A one-shot change to what a creature's being in combat means,
    # filed beside `remove_from_combat` for that entry's reason: the family
    # whose steps dispatch it is the combat one.
    "become_blocked": "combat_restrictions",
    # "You choose which creatures block this combat and how those creatures
    # block." (Melee.) CR 509.1a's chooser substituted for the declare-blockers
    # turn-based action — a restriction on how that declaration is made rather
    # than an effect on any permanent, so it files with the other CR 506/509
    # clauses and GRAMMAR_CATEGORIES is unchanged.
    "choose_blocks_for_defenders": "combat_restrictions",
    # "…each creature that's blocking exactly one of those attacking creatures
    # stops blocking it and is blocking the other attacking creature."
    # (General Jarkeld.) A one-shot rewrite of an existing block (CR 509.1g),
    # filed beside Sorrow's Path's mirror of it for the same reason
    # `remove_from_combat` is here: the family whose steps dispatch it.
    "reassign_blockers_between_attackers": "combat_restrictions",
    "mark_non_wall_target_to_attack": "combat_restrictions",
    # Kookus: CR 508.1a's requirement for one turn, which is not the printed
    # static `combat_restrictions.py` reads for "attacks **each combat** if
    # able". Same category, so GRAMMAR_CATEGORIES is unchanged.
    "force_self_to_attack_until_eot": "combat_restrictions",
    # "Target creature attacks this turn if able." (Boiling Blood.) The
    # same CR 508.1a requirement on a creature the caster chose rather
    # than on the effect's own source.
    "force_target_to_attack_until_eot": "combat_restrictions",
    "force_bound_to_attack_until_eot": "combat_restrictions",
    "force_bound_to_block_until_eot": "combat_restrictions",
    # "**Non-Wall creatures the active player controls** attack this turn if
    # able." (Maddening Imp.) The same CR 508.1a requirement over every creature
    # a printed noun phrase describes — the mirror of the block twin two rows
    # down, which is why they carry the same category and the same name shape.
    "force_subject_to_attack_until_eot": "combat_restrictions",
    "force_target_to_block_until_eot": "combat_restrictions",
    "force_subject_to_block_until_eot": "combat_restrictions",
    # "This creature can attack as though it didn't have defender." with no
    # duration (the ability a kicked Prison Barricade is granted). The static
    # twin of `attack_as_though_no_defender_until_eot`, which is a `pump` row
    # only because it left with the pump sentence it is printed inside; this
    # one is a property the declare-attackers step reads off the program.
    "attacks_as_though_no_defender": "combat_restrictions",
}

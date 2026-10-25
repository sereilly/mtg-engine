from __future__ import annotations

"""Block requirements (CR 509.1c), and the maximisation that judges by them.

"The defending player checks each creature they control to see whether it's
affected by any requirements … If the number of requirements that are being
obeyed is fewer than the maximum possible number of requirements that could be
obeyed without disobeying any restrictions, the declaration of blockers is
illegal."

Three parts, one per clause of that sentence:

* **What is required** — :meth:`BlockRequirementsMixin.block_requirements`,
  every requirement on one defending player's creatures, one
  :class:`BlockRequirement` each, read off every channel the pool can arm: the
  attacker's side (Lure and its printed twins, "must be blocked if able") and
  the blocker's (Watchdog's printed line, the Aura and board-wide spellings of
  it, Provoke's mark, Blaze of Glory's, Trumpeting Armodon's).
* **The most that can be obeyed** — :meth:`~BlockRequirementsMixin.
  _most_obeyed_block_declaration`, a search over the declarations that disobey
  no restriction and pay no cost (CR 509.1c's last clause: a creature that
  can't block unless a cost is paid is never compelled to pay it).
* **The comparison** — :meth:`~BlockRequirementsMixin.
  block_requirement_refusal`, the declaration gate, and
  :meth:`~BlockRequirementsMixin.obeying_block_declaration`, the AI's: a
  declaration obeying fewer than the maximum is refused, and the AI is handed
  the nearest one that does not.

**Why a search, and not an addition test.** The five checks this replaced each
asked one requirement at a time whether the creature *could have* obeyed it by
being added to the declaration as it stood — and so each refused a declaration
that could only be fixed by *swapping* a block, not by adding one. Three
Watchdogs under Caverns of Despair had no legal declaration at all: each
two-blocker declaration left a Watchdog that "could block", and the
three-blocker one broke the cap. The CR's own example under 509.1c goes wrong
the other way: a "blocks if able" creature beside a vanilla one, facing a
menace attacker, must block *with both* — and the addition test, seeing that the
first one alone could not legally join, excused it, so declaring nothing was
accepted. Both are one question asked of the declaration as a whole, which is
what CR 509.1c asks, and the answer is a maximum over every declaration.

**Why a search, and not a matching.** Requirements alone are a b-matching
(blockers to attackers, each blocker up to its ``_max_blocks_for``), but the
restrictions that couple blockers are not: a cap on how many may block (Caverns
of Despair), a floor and a ceiling on how many may block one attacker (menace,
Stalking Tiger), a blocker that needs company (Orcish Conscripts, Mogg
Flunkies) or a bigger companion (Okk). Those are checked over the whole
declaration by the same predicates the declaration gate asks
(``block_declaration_refusal``, ``_minimum_blockers``, ``_maximum_blockers``).
A board is a handful of creatures, the search is bounded by the most each
remaining creature could add, and it stops the moment it reaches the most the
board could possibly obey — so a board on which every requirement can be obeyed
together (nearly every board) costs one walk down one branch.
"""

from dataclasses import dataclass, field
from itertools import combinations

from ..aura_restrictions import auras_imposing
from ..combat_permissions import (MUST_BLOCK_ALL_UNTIL_EOT,
                                  MUST_BLOCK_ATTACKERS_UNTIL_EOT,
                                  MUST_BLOCK_UNTIL_EOT)
from ..combat_restrictions import participation_cap
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..subject_filters import subject_matches


#: How many nodes one search may visit before it answers with the best it has
#: found. Never reached by a board the pool can build — the bound closes every
#: census board in under ten nodes, and a twelve-creature Invasion Plans board
#: against six menace attackers under Dueling Grounds in under five hundred —
#: and present so that a pathological one costs a slow declaration rather than
#: a hung game. An inexact answer is
#: still *sound* in one direction: a declaration it refuses is refused for a
#: witness that really does obey more.
_NODE_BUDGET = 200_000


@dataclass(frozen=True)
class BlockRequirement:
    """One CR 509.1c requirement on the defending player's creatures.

    ``blocker`` is the battlefield slot of the creature the requirement is
    about, or None when it is about an attacker and no creature in particular —
    "this creature must be blocked if able" (Canopy Stalker), of which the
    ruling says "only one creature is required to block" it.

    ``attacker`` is the slot of the attacker it names, or None for "block
    **something**" (Watchdog, Provoke, Invasion Plans).

    ``reason`` is what the declaration gate says when this is the requirement a
    refused declaration left unobeyed.
    """

    blocker: int | None
    attacker: int | None
    reason: str

    def obeyed(self, blocks: "dict[int, tuple[int, ...]]") -> bool:
        """Whether *blocks* (blocker slot → the attacker slots it blocks) obeys
        this requirement."""
        if self.blocker is None:
            return any(self.attacker in blocked for blocked in blocks.values())
        blocked = blocks.get(self.blocker) or ()
        if self.attacker is None:
            return bool(blocked)
        return self.attacker in blocked


@dataclass
class BlockRequirementSearch:
    """The most requirements a legal, cost-free declaration obeys, and one that
    does (``witness``, blocker slot → attacker slots). ``exact`` is False only
    when the node budget ran out first; ``visited`` is how many nodes the
    search took, which is what the budget is measured against."""

    best: int
    witness: dict[int, tuple[int, ...]] = field(default_factory=dict)
    exact: bool = True
    visited: int = 0


class BlockRequirementsMixin:
    def block_requirements(self, controller_index: int) -> list[BlockRequirement]:
        """Every CR 509.1c requirement on *controller_index*'s creatures.

        Each **source** is one requirement, because CR 509.1c counts them: a
        Watchdog under Invasion Plans is affected by two, and two Lures on one
        attacker put two on every creature able to block it. Only the attackers
        aimed at this defending player are asked about (CR 802.4b), and only
        untapped creatures carry a requirement — a tapped one is not able to
        block (CR 509.1a), so a requirement on it could never be obeyed and
        would only make every declaration look short of its total.

        Enumerated in the order the declaration step used to check the
        channels, so the requirement a refusal names is the one it named.
        """
        if not (0 <= controller_index < len(self.players)):
            return []
        attacker_seat = self.active_player_index
        own_attackers = [
            (attacker_idx, attacker)
            for attacker_idx, defending_idx in sorted(self.combat_attackers.items())
            if defending_idx == controller_index
            for attacker in (self.permanent_at(attacker_seat, attacker_idx),)
            if attacker is not None
        ]
        if not own_attackers:
            return []
        blockers = [
            (blocker_idx, blocker)
            for blocker_idx, blocker in enumerate(self.controlled_by(controller_index))
            if blocker.is_creature and not blocker.tapped
        ]
        found: list[BlockRequirement] = []

        # "All creatures able to block enchanted creature do so." (Lure.) Two
        # channels for one requirement — an Aura granting it, and the
        # creature's own printed line (Elvish Bard), which may narrow which
        # creatures it compels ("All **Walls** able to block this creature do
        # so", Marble Priest; "…creatures **with flying**…", Talruum Piper).
        # Every source separately: a Lure on Marble Priest compels every
        # creature, its printed line only the Walls, and both apply.
        for attacker_idx, attacker in own_attackers:
            sources: list[dict] = [
                dict(instr.payload.get("blocker_filter") or {})
                for instr in compile_card_oracle(attacker.effective_card).instructions
                if instr.kind == "must_be_blocked_by_all_able"
            ]
            sources.extend(
                {} for _aura in auras_imposing(attacker, "must_be_blocked_by_all_able")
            )
            for compelled in sources:
                for blocker_idx, blocker in blockers:
                    # The **attacker's** controller is the observer, because
                    # the sentence is printed on the attacker: CR 109.5's "you"
                    # is the seat whose ability it is, not the seat asked to
                    # block.
                    if compelled and not subject_matches(
                        self, blocker, compelled,
                        observer=self.controller_index_of(attacker),
                        source=attacker,
                    ):
                        continue
                    found.append(BlockRequirement(
                        blocker_idx, attacker_idx,
                        f"{blocker.card.name} must block {attacker.card.name} due to Lure",
                    ))

        # "This creature must be blocked if able." (Canopy Stalker.) The
        # weakest attacker-side requirement: **one** creature must block it —
        # "Other creatures may also block it, and are free to block other
        # creatures or not block at all" (2020-06-23 ruling) — so it is one
        # requirement about the attacker rather than one on each creature.
        # Off the effective card, so a copy carries it (CR 707.2).
        for attacker_idx, attacker in own_attackers:
            for instr in compile_card_oracle(attacker.effective_card).instructions:
                if instr.kind == "must_be_blocked":
                    found.append(BlockRequirement(
                        None, attacker_idx,
                        f"{attacker.card.name} must be blocked if able",
                    ))

        # "It blocks each attacking creature this turn if able." (Blaze of
        # Glory.) One requirement per attacker, on the one creature.
        for blocker_idx, blocker in blockers:
            if not blocker.metadata.get(MUST_BLOCK_ALL_UNTIL_EOT):
                continue
            for attacker_idx, attacker in own_attackers:
                found.append(BlockRequirement(
                    blocker_idx, attacker_idx,
                    f"{blocker.card.name} must block {attacker.card.name} "
                    "(Blaze of Glory)",
                ))

        # "Target creature blocks **this creature** this turn if able."
        # (Trumpeting Armodon, Rampant Elephant, Crashing Boars, Magnetic Web.)
        # Both halves of the pair named, the attacker by ``permanent_id`` — so a
        # marked attacker that left combat, left the battlefield or is aimed at
        # somebody else compels nothing.
        for blocker_idx, blocker in blockers:
            owed = blocker.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ()
            if not owed:
                continue
            for attacker_idx, attacker in own_attackers:
                if attacker.permanent_id in owed:
                    found.append(BlockRequirement(
                        blocker_idx, attacker_idx,
                        f"{blocker.card.name} must block {attacker.card.name} "
                        "this turn if able",
                    ))

        # "This creature blocks each combat if able." (Watchdog.) The weakest
        # blocker-side requirement — block **something** — and four channels
        # for it: the creature's own printed line (off its effective card, so a
        # copy carries it), an Aura granting it, a spell's mark for the turn
        # (Provoke), and a permanent printing it about a set (Invasion Plans).
        for blocker_idx, blocker in blockers:
            sources = (
                (1 if blocker.metadata.get(MUST_BLOCK_UNTIL_EOT) else 0)
                + sum(
                    1
                    for instr in compile_card_oracle(blocker.effective_card).instructions
                    if instr.kind == "must_block_each_combat"
                )
                + len(auras_imposing(blocker, "must_block_each_combat"))
                + self._board_block_compulsions(blocker)
            )
            found.extend(
                BlockRequirement(
                    blocker_idx, None,
                    f"{blocker.card.name} blocks each combat if able",
                )
                for _ in range(sources)
            )
        return found

    def _board_block_compulsions(self, blocker: Permanent) -> int:
        """How many permanents print Watchdog's requirement about *blocker*.

        "All creatures block each combat if able." (Invasion Plans.) Printed on
        an enchantment nobody is blocking with, so it is found by scanning the
        board rather than read off the blocker's own program — the requirement
        twin of ``creatures_cant_block`` in ``_can_block_attacker`` and the
        block-side mirror of ``_must_attack_if_able``'s ``creatures_must_attack``
        scan, over the same ``subject`` payload and the same ``subject_matches``.

        A count rather than a yes, because CR 509.1c counts requirements and two
        such permanents are two of them.

        The observer is the seat whose ability this is (CR 109.5), so a
        "creatures **you** control" printing would compel that seat's creatures
        rather than the blocker's controller's.
        """
        count = 0
        for source_perm in self.all_permanents():
            source_seat = self.controller_index_of(source_perm)
            for instr in compile_card_oracle(
                source_perm.effective_card
            ).instructions:
                if instr.kind != "creatures_must_block":
                    continue
                if subject_matches(
                    self, blocker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    count += 1
        return count

    def block_requirement_summary(
        self, controller_index: int,
    ) -> "tuple[list[BlockRequirement], int]":
        """*controller_index*'s requirements and the most of them one legal,
        cost-free declaration obeys — what the declaration gate will hold a
        declaration to, told to the player **before** they declare (the web's
        ``combat.block_requirements``). The search runs only where there is a
        requirement, which is nearly no board."""
        requirements = self.block_requirements(controller_index)
        if not requirements:
            return [], 0
        found = self._most_obeyed_block_declaration(controller_index, requirements)
        return requirements, found.best

    def block_requirement_refusal(
        self,
        controller_index: int,
        assignments: "dict[int, list[int]]",
    ) -> str | None:
        """Why *assignments* disobeys CR 509.1c, or None when it obeys it.

        *assignments* is the declaration as ``declare_blockers`` holds it —
        blocker slot → the attacker slots it blocks — and is assumed to have
        passed every CR 509.1b restriction already: the gate asks restrictions
        first, so a declaration is refused for the rule it breaks outright
        before it is refused for one it merely under-obeys.

        The declaration is illegal when it obeys fewer requirements than the
        most a declaration disobeying no restriction and paying no cost could
        obey. The refusal names a requirement a declaration obeying that many
        does obey and this one does not — the block the player is missing — and,
        when the requirements here cannot all be obeyed together, how many
        can, because "Watchdog blocks each combat if able" read alone beside a
        Caverns of Despair is a riddle.
        """
        requirements = self.block_requirements(controller_index)
        if not requirements:
            return None
        declared = _as_blocks(assignments)
        obeyed = sum(1 for requirement in requirements if requirement.obeyed(declared))
        if obeyed == len(requirements):
            return None
        found = self._most_obeyed_block_declaration(controller_index, requirements)
        if found.best <= obeyed:
            if not found.exact:
                self.log.append(
                    "CR 509.1c: the blocking-requirement search ran out of room; "
                    "the declaration stands on the best it found"
                )
            return None
        missed = next(
            requirement for requirement in requirements
            if requirement.obeyed(found.witness) and not requirement.obeyed(declared)
        )
        if found.best < len(requirements):
            return (
                f"{missed.reason} (this declaration obeys {obeyed} of the "
                f"{found.best} blocking requirements that can be obeyed together)"
            )
        return missed.reason

    def obeying_block_declaration(
        self,
        controller_index: int,
        preferred: "dict[int, int | list[int]]",
        *,
        rank=None,
    ) -> "dict[int, int | list[int]]":
        """*preferred*, or the declaration nearest it that CR 509.1c accepts.

        The AI's half of the gate. Its chooser builds the blocks it wants and
        prunes them against the restrictions, and a prune that drops a creature
        for a cap does not know the creature was compelled — so a Caverns of
        Despair could cost the declaration the Watchdog it needed and keep the
        Bear it did not. Handed back unchanged when the gate accepts it;
        otherwise the search is asked for a declaration obeying the maximum,
        trying *preferred*'s own block for each of its creatures first, so what
        comes back keeps as much of the seat's choice as the maximum allows.

        *rank* is the caller's policy for everything *preferred* does not
        settle — ``rank(blocker, attacker) -> float``, higher tried first —
        exactly as ``_legal_block_declaration`` hands its list over worst-last:
        which of two equally obeying blocks is better is a valuation, and a
        valuation is not this module's to make.

        A *preferred* that breaks a restriction is searched from as well, on a
        board with requirements: there the AI's fallback — declare nothing — is
        itself illegal, so a block the seat's own prune missed (three creatures
        on a Lured Stalking Tiger) would leave it no legal declaration at all.
        """
        requirements = self.block_requirements(controller_index)
        if not requirements:
            return preferred
        if not self._blocks_disobey_a_restriction(
            controller_index, _as_blocks(preferred)
        ) and self.block_requirement_refusal(
            controller_index, _as_lists(preferred)
        ) is None:
            return preferred
        found = self._most_obeyed_block_declaration(
            controller_index, requirements, preferred=_as_blocks(preferred), rank=rank,
        )
        return {
            blocker_idx: (list(blocked) if len(blocked) > 1 else blocked[0])
            for blocker_idx, blocked in found.witness.items()
        }

    def _blocks_disobey_a_restriction(
        self, controller_index: int, blocks: "dict[int, tuple[int, ...]]"
    ) -> bool:
        """Whether *blocks* breaks a CR 509.1b restriction the declaration gate
        enforces, asked of the same predicates it asks: each pair
        (``_can_block_attacker``, the Raging River piles), each creature's
        ceiling (``_max_blocks_for``), each attacker's floor and ceiling
        (menace, Stalking Tiger) and the whole declaration's
        (``block_declaration_refusal``). Costs are not asked: whether a seat
        can pay is its own prune's question (``_unaffordable_blocker``)."""
        attacker_seat = self.active_player_index
        own = {
            attacker_idx for attacker_idx, defending_idx in self.combat_attackers.items()
            if defending_idx == controller_index
        }
        counts: dict[int, int] = {}
        declared: list[Permanent] = []
        for blocker_idx, blocked in blocks.items():
            blocker = self.permanent_at(controller_index, blocker_idx)
            if blocker is None or not blocker.is_creature or blocker.tapped:
                return True
            if len(blocked) > self._max_blocks_for(blocker):
                return True
            declared.append(blocker)
            for attacker_idx in blocked:
                attacker = self.permanent_at(attacker_seat, attacker_idx)
                if attacker is None or attacker_idx not in own:
                    return True
                if not self._can_block_attacker(blocker, attacker):
                    return True
                if self._left_right_block_illegal(attacker_idx, blocker_idx, blocker):
                    return True
                counts[attacker_idx] = counts.get(attacker_idx, 0) + 1
        for attacker_idx, count in counts.items():
            attacker = self.permanent_at(attacker_seat, attacker_idx)
            if count < self._minimum_blockers(attacker):
                return True
            most = self._maximum_blockers(attacker)
            if most is not None and count > most:
                return True
        return self.block_declaration_refusal(declared) is not None

    def _most_obeyed_block_declaration(
        self,
        controller_index: int,
        requirements: list[BlockRequirement],
        *,
        preferred: "dict[int, tuple[int, ...]] | None" = None,
        rank=None,
    ) -> BlockRequirementSearch:
        """The most of *requirements* one legal, cost-free declaration obeys.

        A branch-and-bound search, one creature at a time, over every
        declaration CR 509.1b allows:

        * each creature's options are the attackers it may block **without a
          cost** — ``_can_block_attacker``, no cost owed (CR 509.1c's last
          clause), and the Raging River piles — in every combination up to its
          ``_max_blocks_for``, or not blocking at all;
        * a cap on blockers (Caverns of Despair) and a ceiling on one
          attacker's blockers (Stalking Tiger) are checked as the declaration
          grows, because a branch that breaks either never recovers;
        * a floor on one attacker's blockers (menace) and the set restrictions
          (``block_declaration_refusal``: company, a bigger companion, the cap)
          are checked on a whole declaration, because adding a creature can
          satisfy them.

        The bound on a branch is what it has obeyed plus the most each
        remaining creature could add on its own (under a cap, the largest that
        many), plus every "must be blocked" requirement still open. The search
        stops at the bound of the whole board, which every board whose
        requirements can all be obeyed together reaches on its first branch.

        The empty declaration is always legal — no restriction forbids not
        blocking — so the answer is never below zero and the witness never
        missing.
        """
        attacker_seat = self.active_player_index
        attackers = {
            attacker_idx: attacker
            for attacker_idx, defending_idx in sorted(self.combat_attackers.items())
            if defending_idx == controller_index
            for attacker in (self.permanent_at(attacker_seat, attacker_idx),)
            if attacker is not None
        }
        blockers = {
            blocker_idx: blocker
            for blocker_idx, blocker in enumerate(self.controlled_by(controller_index))
            if blocker.is_creature and not blocker.tapped
        }
        legal: dict[int, tuple[int, ...]] = {}
        for blocker_idx, blocker in blockers.items():
            pairs = tuple(
                attacker_idx for attacker_idx, attacker in attackers.items()
                if self._can_block_attacker(blocker, attacker)
                and not self._owes_a_cost_to_block(blocker, attacker)
                and not self._left_right_block_illegal(attacker_idx, blocker_idx, blocker)
            )
            if pairs:
                legal[blocker_idx] = pairs

        # What each requirement is worth to each creature: the "something"
        # ones (generic) and the ones naming an attacker (specific), and the
        # attacker-side ones no creature in particular carries.
        generic: dict[int, int] = {}
        specific: dict[int, dict[int, int]] = {}
        attacker_side: dict[int, int] = {}
        for requirement in requirements:
            if requirement.blocker is None:
                attacker_side[requirement.attacker] = (
                    attacker_side.get(requirement.attacker, 0) + 1
                )
            elif requirement.attacker is None:
                generic[requirement.blocker] = generic.get(requirement.blocker, 0) + 1
            else:
                owed = specific.setdefault(requirement.blocker, {})
                owed[requirement.attacker] = owed.get(requirement.attacker, 0) + 1

        def gain(blocker_idx: int, option: tuple[int, ...]) -> int:
            if not option:
                return 0
            owed = specific.get(blocker_idx) or {}
            return generic.get(blocker_idx, 0) + sum(owed.get(a, 0) for a in option)

        options: dict[int, list[tuple[int, ...]]] = {}
        ceiling: dict[int, int] = {}
        for blocker_idx, pairs in legal.items():
            blocker = blockers[blocker_idx]
            most = min(self._max_blocks_for(blocker), len(pairs))
            candidates = [
                option
                for size in range(1, most + 1)
                for option in combinations(pairs, size)
            ]
            ceiling[blocker_idx] = max(gain(blocker_idx, option) for option in candidates)

            def order(option, _blocker=blocker, _blocker_idx=blocker_idx):
                ranked = (
                    sum(rank(_blocker, attackers[a]) for a in option) / len(option)
                    if rank is not None else 0.0
                )
                return (
                    -gain(_blocker_idx, option),
                    -sum(1 for a in option if a in attacker_side),
                    -ranked,
                    len(option),
                    option,
                )

            candidates.sort(key=order)
            wanted = (preferred or {}).get(blocker_idx)
            ordered: list[tuple[int, ...]] = []
            if wanted and tuple(sorted(wanted)) in candidates:
                ordered.append(tuple(sorted(wanted)))
                candidates.remove(tuple(sorted(wanted)))
            # A creature something compels tries blocking before staying home;
            # one nothing compels stays home first unless the caller wanted it
            # to block, so the witness drafts a helper (menace's second blocker,
            # Orcish Conscripts' company) only when the maximum needs one.
            if ceiling[blocker_idx] > 0:
                ordered.extend(candidates)
                ordered.append(())
            else:
                ordered.append(())
                ordered.extend(candidates)
            options[blocker_idx] = ordered

        order_of_search = sorted(legal, key=lambda idx: (-ceiling[idx], idx))
        # The most the creatures from position i on could add, largest first,
        # so a cap's "the largest that many" is a prefix sum of what is left.
        suffix_ceilings = [
            sorted((ceiling[idx] for idx in order_of_search[i:]), reverse=True)
            for i in range(len(order_of_search) + 1)
        ]
        reachable_side = {
            attacker_idx: count for attacker_idx, count in attacker_side.items()
            if any(attacker_idx in pairs for pairs in legal.values())
        }
        cap = participation_cap(self.all_permanents(), "block")
        floors = {idx: self._minimum_blockers(attacker) for idx, attacker in attackers.items()}
        ceilings = {idx: self._maximum_blockers(attacker) for idx, attacker in attackers.items()}

        def bound(position: int, used: int, fixed: int, blocked: dict[int, int]) -> int:
            remaining = suffix_ceilings[position]
            if cap is not None:
                remaining = remaining[: max(0, cap - used)]
            open_side = sum(
                count for attacker_idx, count in reachable_side.items()
                if blocked.get(attacker_idx, 0) == 0
                and any(
                    attacker_idx in legal[idx] for idx in order_of_search[position:]
                )
            )
            met_side = sum(
                count for attacker_idx, count in attacker_side.items()
                if blocked.get(attacker_idx, 0) > 0
            )
            return fixed + met_side + open_side + sum(remaining)

        result = BlockRequirementSearch(best=0, witness={})
        top = bound(0, 0, 0, {})
        if top == 0:
            return result
        nodes = 0
        chosen: dict[int, tuple[int, ...]] = {}
        blocked_count: dict[int, int] = {}

        def whole_declaration_holds() -> bool:
            for attacker_idx, count in blocked_count.items():
                if 0 < count < floors[attacker_idx]:
                    return False
            return self.block_declaration_refusal(
                [blockers[idx] for idx in chosen]
            ) is None

        def search(position: int, used: int, fixed: int) -> bool:
            """True when the search is over (the bound of the board is
            reached, or the budget is spent)."""
            nonlocal nodes
            nodes += 1
            if nodes > _NODE_BUDGET:
                result.exact = False
                return True
            if bound(position, used, fixed, blocked_count) <= result.best:
                return False
            if position == len(order_of_search):
                if whole_declaration_holds():
                    met = fixed + sum(
                        count for attacker_idx, count in attacker_side.items()
                        if blocked_count.get(attacker_idx, 0) > 0
                    )
                    if met > result.best:
                        result.best = met
                        result.witness = dict(chosen)
                        if met >= top:
                            return True
                return False
            blocker_idx = order_of_search[position]
            for option in options[blocker_idx]:
                if option:
                    if cap is not None and used + 1 > cap:
                        continue
                    if any(
                        ceilings[a] is not None
                        and blocked_count.get(a, 0) + 1 > ceilings[a]
                        for a in option
                    ):
                        continue
                    chosen[blocker_idx] = option
                    for a in option:
                        blocked_count[a] = blocked_count.get(a, 0) + 1
                    done = search(
                        position + 1, used + 1, fixed + gain(blocker_idx, option)
                    )
                    for a in option:
                        blocked_count[a] -= 1
                        if not blocked_count[a]:
                            del blocked_count[a]
                    del chosen[blocker_idx]
                else:
                    done = search(position + 1, used, fixed)
                if done:
                    return True
            return False

        search(0, 0, 0)
        result.visited = nodes
        return result


def _as_blocks(assignments) -> "dict[int, tuple[int, ...]]":
    """A declaration as blocker slot → a tuple of attacker slots, whichever of
    the two spellings (one attacker, or a list of them) it arrived in."""
    blocks: dict[int, tuple[int, ...]] = {}
    for blocker_idx, assigned in (assignments or {}).items():
        attacker_indices = (
            assigned if isinstance(assigned, (list, tuple, set, frozenset))
            else [assigned]
        )
        attacker_indices = tuple(sorted({int(a) for a in attacker_indices}))
        if attacker_indices:
            blocks[int(blocker_idx)] = attacker_indices
    return blocks


def _as_lists(assignments) -> "dict[int, list[int]]":
    return {idx: list(blocked) for idx, blocked in _as_blocks(assignments).items()}

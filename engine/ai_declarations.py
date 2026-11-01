"""What an AI seat declares in combat: its attackers (CR 508.1) and its
blockers (CR 509.1).

:func:`choose_attackers` and :func:`choose_combat_blockers` decide;
``ai_combat`` makes the declarations and owns the fallbacks for a refused
one. Each declaration is pruned until it is legal **as a set**, because the
per-creature predicates (:func:`legal_attackers`, the engine's
``_can_block_attacker``) cannot see a restriction about who else was
declared — "can only attack alone", "can't block unless another creature
blocks", a cap per defender (:func:`_legal_declaration`,
:func:`_legal_block_declaration`) — nor a requirement the set itself creates
(:func:`_with_conditional_requirements`), nor a total cost the whole
declaration has to pay (CR 508.1h, 509.1d: :func:`_unaffordable_attacker`,
:func:`_unaffordable_blocker`). A block declaration's requirements are the
engine's to settle last (CR 509.1c, ``Game.obeying_block_declaration``),
because only a maximum over every declaration can say which compelled block a
cap may cost.

Which trades are worth making is :func:`_score_block_pair`'s, with the
damage estimates beside it — and a block that loses its blocker
(:func:`_block_loses_its_blocker`) is made only in a gang that kills its
attacker (:func:`_gang_blocks`) or as a chump the life it saves is worth
(:func:`_chump_blocks`).
"""

from __future__ import annotations

from .game import Game
from .aura_restrictions import aura_restriction_active
from .models import Permanent
from .ai_compelled_blocks import compelled_blocks, fight_outcome
from .ai_rehearsal import life_worth, permanent_worth
from .ai_scoring import choose_attack_target, _permanent_value
from .combat_assignment import combat_damage_assigned_by


def legal_attackers(game: Game, attacking_player_index: int, against: int | None = None) -> list[int]:
    """Return battlefield indices of every creature that may legally attack this
    turn — untapped, not summoning sick, and allowed to attack an opponent.

    When ``against`` is given, mirrors the original single-opponent behavior
    (legal against that one specific opponent). When omitted, returns creatures
    legal against ANY living opponent."""
    player = game.players[attacking_player_index]
    opponents = [against] if against is not None else game.opponents_of(attacking_player_index)
    # **A creature now, not a creature card** (CR 613 layer 4, through
    # ``Permanent.is_creature``). This read the printed type line, so a land
    # or an artifact an effect had made a creature never attacked in an AI's
    # hands — a Mishra's Factory animated for the fight stayed home, and a
    # rehearsal of the animation read it as worth nothing — while a creature
    # card that had stopped being one (a Licid become an Aura) was proposed.
    return [
        idx
        for idx, perm in enumerate(player.battlefield)
        if perm.is_creature
        and not perm.tapped
        and not game._is_summoning_sick(perm)
        and any(game.can_attack(perm, opp) for opp in opponents)
    ]


def _legal_declaration(
    game: Game, attacking_player_index: int, chosen: list[int],
    *, against: int | None = None,
) -> list[int]:
    """*chosen*, pruned until the **declaration** itself is legal (CR 508.1c).

    `legal_attackers` above is a per-creature predicate, and a restriction can
    be about the set: "can only attack alone" (Errantry), "can't attack unless
    at least two other creatures attack" (Orcish Conscripts). Proposing a set
    that disobeys one is not a partial failure — `declare_attackers` refuses the
    **whole** declaration, so a Conscripts beside one Bear kept the Bear home
    too, and the seat attacked with nobody all game.

    The rule is asked of the engine rather than re-read here: a second copy in
    the AI would drift from the one the declaration enforces, and the direction
    it would drift is a seat that stops attacking for reasons the rules do not
    give. The engine names the offending permanent, which is what makes this a
    prune rather than a search — each pass drops exactly one creature, so it
    terminates.

    **Which one it names is the caller's business for a cap.** "No more than two
    creatures can attack" (Caverns of Despair, Crawlspace) is disobeyed by the
    set rather than by any member of it, so the engine names the *last* attacker
    in the list it was handed — a rule cannot say which creature the attacker
    would rather keep, and inventing an answer there would put AI valuation
    inside the rules engine. So the list is handed over weakest-last, and the
    surviving indices come back in their original order, which is what makes
    this a cap the AI attacks *under* rather than one it attacks *through*.

    *against* is the seat this declaration is aimed at, which the per-defender
    cap needs and the global one does not. It matters only at a table with more
    than two living players: with one opponent the engine fills it in, and with
    several it cannot guess, so a free-for-all declaration would be pruned
    against the global cap alone and then refused whole for the other.
    """
    # Through the seam (`permanent_at`), which is where an index becomes a
    # permanent: the AI carries slots because that is what the declaration takes,
    # and a raw `battlefield[i]` here would be a second place that has to be
    # right about what a slot means.
    pruned = [
        (idx, game.permanent_at(attacking_player_index, idx)) for idx in chosen
    ]
    pruned = [(idx, perm) for idx, perm in pruned if perm is not None]
    # Descending value, so the engine's "last one" is the one this seat can most
    # afford to leave home. Only the order of the *question* changes; the answer
    # is a set, and it is returned in the caller's order below.
    pruned.sort(key=lambda entry: -_permanent_value(entry[1]))
    while pruned:
        # **What the declaration costs is pruned against too, and it was not.**
        # CR 508.1h's costs are summed over the whole declaration
        # (`_declaration_mana_plan`, `_declaration_sacrifice_plan`), where
        # `legal_attackers` above can only ask "could this seat afford *this*
        # creature". So a seat with one land under a {1}-per-attacker toll
        # proposed three attackers, the declaration refused all three, and
        # `ai_combat`'s superset fallback — every legal attacker, the same
        # three — was refused for the same reason: the seat attacked with
        # nobody while it could plainly have attacked with one. Measured on
        # War Tax and true of every shipped card that prints a summed
        # declaration cost (Koskun Falls, Elephant Grass, Propaganda,
        # Brainwash, Leviathan, Flooded Woodlands, Reclamation).
        #
        # Asked of the engine's own planners rather than re-totalled here, for
        # the restriction loop's stated reason: a second copy would drift, and
        # the direction it drifts is a seat that stops attacking for reasons
        # the rules do not give. Weakest-last ordering means the creature
        # dropped is the one this seat can most afford to leave home, exactly
        # as it is for a cap.
        unaffordable = _unaffordable_attacker(
            game, attacking_player_index, [perm for _idx, perm in pruned], against
        )
        if unaffordable is not None:
            pruned = [
                (idx, perm) for idx, perm in pruned if perm is not unaffordable
            ]
            continue
        refusal = game.attack_declaration_refusal(
            [perm for _idx, perm in pruned],
            # Who this seat is aiming at, when the caller knows. Omitting it is
            # only safe at a table with one living opponent, where the engine
            # fills it in; `choose_attackers` picks a single target even in a
            # free-for-all, so a per-defender cap (Crawlspace) at *that* seat
            # would otherwise be invisible here and the whole declaration would
            # be refused again — the exact failure this prune exists to stop.
            defenders=(
                None if against is None
                else {perm.permanent_id: against for _idx, perm in pruned}
            ),
        )
        if refusal is None:
            break
        offender, _reason = refusal
        pruned = [(idx, perm) for idx, perm in pruned if perm is not offender]
    kept = {id(perm) for _idx, perm in pruned}
    return [idx for idx in chosen if id(game.permanent_at(attacking_player_index, idx)) in kept]


def _with_conditional_requirements(
    game: Game, attacking_player_index: int, chosen: list[int], legal: list[int]
) -> list[int]:
    """*chosen*, plus every legal attacker the set itself now **requires**.

    The mirror of :func:`_legal_declaration` one rule over. That one prunes
    until a restriction stops being disobeyed; this one adds until a
    *requirement* is obeyed — "If a creature you control attacks, this creature
    also attacks if able" (Ekundu Cyclops) is conditional on the rest of the
    declaration, so a set that was legal before a creature was added can stop
    being legal because of it.

    Asked of the engine rather than re-read here, for ``_legal_declaration``'s
    reason: a second copy of the rule in the AI drifts, and the direction it
    drifts is a seat whose whole declaration is refused and which therefore
    attacks with nobody all game.

    Terminates because each pass adds at least one creature out of a finite
    list, and a set that adds nothing is stable.
    """
    picked = list(chosen)
    while True:
        declared = [
            perm for perm in
            (game.permanent_at(attacking_player_index, idx) for idx in picked)
            if perm is not None
        ]
        added = [
            idx for idx in legal
            if idx not in picked
            and game._must_attack_beside(
                game.permanent_at(attacking_player_index, idx), declared
            )
        ]
        if not added:
            return picked
        picked.extend(added)


def choose_attackers(game: Game, attacking_player_index: int) -> list[int]:
    """Return indices of creatures that should attack this turn.

    MVP multiplayer behavior: picks one opponent (``choose_attack_target``) and
    decides, for each legal attacker, whether to send it at that opponent —
    splitting one attack across multiple opponents is a documented stretch goal,
    not implemented here."""
    player = game.players[attacking_player_index]
    opponent_index = choose_attack_target(game, attacking_player_index)
    opponent = game.players[opponent_index]

    legal_attackers_list = legal_attackers(game, attacking_player_index, against=opponent_index)
    if not legal_attackers_list:
        return []

    # Creatures that must attack if able (Siren's Call, Lure-style "attacks each
    # combat if able", etc.) are non-negotiable: declare_attackers rejects any
    # declaration that omits them, so they must be in the result regardless of
    # the profitability heuristic below.
    forced = [idx for idx in legal_attackers_list if game._must_attack_if_able(player.battlefield[idx])]

    # A creature enchanted with Lure ("All creatures able to block it do so") is
    # only worth attacking with if it actually gets declared. Treat it as forced
    # so the AI doesn't decline to attack with it (which would skip the defender's
    # block step entirely from the human's perspective).
    for idx in legal_attackers_list:
        if idx not in forced and aura_restriction_active(
            player.battlefield[idx], "must_be_blocked_by_all_able"
        ):
            forced.append(idx)

    opponent_blockers = [
        perm
        for perm in game.controlled_by(opponent)
        # What can block is what is a creature now (CR 509.1a, CR 613 layer 4).
        if perm.is_creature and not perm.tapped
    ]
    if not opponent_blockers:
        return _legal_declaration(
            game, attacking_player_index, legal_attackers_list,
            against=opponent_index,
        )

    chosen = list(forced)
    for idx in legal_attackers_list:
        if idx in chosen:
            continue
        attacker = player.battlefield[idx]
        best_defender_score = max(
            _score_block_pair(blocker, attacker) for blocker in opponent_blockers
        )
        # Attack when the best possible block is not clearly profitable for the opponent.
        if best_defender_score <= _permanent_value(attacker):
            chosen.append(idx)
    chosen = _with_conditional_requirements(
        game, attacking_player_index, chosen, legal_attackers_list
    )
    chosen = _legal_declaration(
        game, attacking_player_index, chosen, against=opponent_index
    )

    # Go all-in when lethal is on the table — through the same prune, because a
    # declaration that is refused deals no damage at all. This returned the raw
    # legal set, so under either attack cap the lethal swing was refused whole
    # and the seat attacked with nobody on the turn it could have won.
    if sum(player.battlefield[i].effective_power for i in legal_attackers_list) >= opponent.life:
        return _legal_declaration(
            game, attacking_player_index, legal_attackers_list,
            against=opponent_index,
        )

    return sorted(chosen)


def _legal_block_declaration(
    game: Game,
    defending_player_index: int,
    chosen: dict[int, int | list[int]],
) -> dict[int, int | list[int]]:
    """*chosen*, pruned until the **declaration** itself is legal (CR 509.1b).

    :func:`_legal_declaration` one step of combat over, and written from the
    identical defect. ``_can_block_attacker`` is a per-pair predicate, and a
    restriction can be about the set: "no more than two creatures can block each
    combat" (Caverns of Despair), "can't block unless at least two other
    creatures block" (Orcish Conscripts, and Mogg Flunkies' "can't block
    alone"), "can't block unless a creature with greater power also blocks"
    (Okk). Proposing a map that disobeys one is not a partial failure —
    ``declare_blockers`` refuses the **whole** declaration, so the defender
    blocked with nobody, this combat and every later one, in silence.

    The rule is asked of the engine rather than re-read here, for the attack
    side's reason exactly: a second copy in the AI would drift from the one the
    declaration enforces, and the direction it drifts is a seat that stops
    blocking for reasons the rules do not give. The engine names the offending
    permanent, which is what makes this a prune rather than a search — each pass
    drops exactly one blocker, so it terminates.

    A **map**, not a list, which is the one structural difference from the
    attack side: dropping the offender means dropping a key, and the attackers
    it was assigned go with it. Everything else about that blocker's assignment
    is left alone, because a partial block is a different declaration, not a
    smaller one.

    Only this seat's own map is pruned, and only against itself: CR 802.4b
    judges each defending player's blocks with every other player's blockers
    ignored, so a second defender declaring first cannot make this one's map
    illegal.

    Which blocker the engine names for a **cap** is this function's business,
    the way it is `_legal_declaration`'s: a cap is disobeyed by the set rather
    than by any member of it, so the engine names the *last* one it was handed.
    The list therefore goes over worst-block-last — scored by the same
    `_score_block_pair` that chose the blocks — which is what makes this a cap
    the AI blocks *under* rather than one it blocks *through*.
    """
    attacker_player = game.players[game.active_player_index]
    ordered: list[tuple[int, Permanent, float]] = []
    for blocker_idx, assigned in chosen.items():
        blocker = game.permanent_at(defending_player_index, blocker_idx)
        if blocker is None:
            continue
        attacker_indices = assigned if isinstance(assigned, list) else [assigned]
        attacker = next(
            (
                perm
                for perm in (
                    game.permanent_at(attacker_player, idx)
                    for idx in attacker_indices
                )
                if perm is not None
            ),
            None,
        )
        # The value of *the block*, not of the blocker: a cap forces the seat to
        # give one up, and the one to give up is the least useful block rather
        # than the smallest creature. With no attacker resolvable there is no
        # pair to score, so the creature's own value stands in.
        score = (
            _score_block_pair(blocker, attacker)
            if attacker is not None
            else _permanent_value(blocker)
        )
        ordered.append((blocker_idx, blocker, score))
    ordered.sort(key=lambda entry: -entry[2])
    ordered = _within_blocker_ceilings(game, attacker_player, chosen, ordered)

    while ordered:
        # What the declaration *costs*, pruned against for the attack side's
        # reason exactly: CR 509.1d totals the costs of every chosen blocker, so
        # a defender with one land under a {1}-per-blocker toll (War Cadence)
        # would propose two blocks, have the declaration refused whole, and fall
        # through `ai_combat`'s superset rung to blocking with nobody — while it
        # could plainly have blocked with one. True of every shipped card
        # printing a summed block cost too (Hipparion, Awesome Presence, and
        # Heat Wave's life half).
        unaffordable = _unaffordable_blocker(
            game, defending_player_index, attacker_player,
            {idx: chosen[idx] for idx, _perm, _score in ordered},
            {idx: perm for idx, perm, _score in ordered},
            [perm for _idx, perm, _score in ordered],
        )
        if unaffordable is not None:
            ordered = [
                entry for entry in ordered if entry[1] is not unaffordable
            ]
            continue
        refusal = game.block_declaration_refusal(
            [perm for _idx, perm, _score in ordered]
        )
        if refusal is None:
            break
        offender, _reason = refusal
        ordered = [
            entry for entry in ordered if entry[1] is not offender
        ]
    kept = {blocker_idx for blocker_idx, _perm, _score in ordered}
    return {
        blocker_idx: assigned
        for blocker_idx, assigned in chosen.items()
        if blocker_idx in kept
    }



def _within_blocker_ceilings(game, attacker_player, chosen, ordered):
    """*ordered* (best block first) without the blocks that put more creatures
    on one attacker than it may be blocked by.

    "This creature can't be blocked by more than one creature." (Stalking
    Tiger, Charging Rhino, Krosan Vorine; Familiar Ground's board-wide
    spelling.) CR 509.1b's ceiling on one attacker, which the declaration gate
    reads through ``_maximum_blockers`` and ``block_declaration_refusal`` does
    not — it judges the set of blockers, not who each one blocks — so the
    prune below never saw it: two Bears both liked a Stalking Tiger, the
    declaration was refused whole, and the seat blocked with nobody.

    Asked of the same ``_maximum_blockers`` the gate asks, and the blocks kept
    are the best ones up to each ceiling: the list is already worst-last, so a
    walk down it keeps a block while its attacker has room. A creature
    blocking several attackers is dropped whole when any of them is full,
    for the reason the prune below drops a key: a partial block is a
    different declaration, not a smaller one.
    """
    ceilings: dict[int, int | None] = {}
    counted: dict[int, int] = {}
    kept = []
    for entry in ordered:
        assigned = chosen[entry[0]]
        attacker_indices = assigned if isinstance(assigned, list) else [assigned]
        for attacker_idx in attacker_indices:
            if attacker_idx not in ceilings:
                attacker = game.permanent_at(attacker_player, attacker_idx)
                ceilings[attacker_idx] = (
                    game._maximum_blockers(attacker) if attacker is not None else None
                )
        if any(
            ceilings[attacker_idx] is not None
            and counted.get(attacker_idx, 0) + 1 > ceilings[attacker_idx]
            for attacker_idx in attacker_indices
        ):
            continue
        for attacker_idx in attacker_indices:
            counted[attacker_idx] = counted.get(attacker_idx, 0) + 1
        kept.append(entry)
    return kept


def _unaffordable_attacker(game, seat, attackers, against):
    """The attacker to drop when this whole declaration cannot be paid for.

    None when it can. CR 508.1h locks in a *total* cost, so affordability is a
    property of the set rather than of any member — which means, exactly as for
    a cap, that no rule can say which creature to leave home. The weakest is
    last in the list this is handed, so naming it is the same policy the
    restriction prune already applies.

    Both halves of the cost are asked, because either can be the one that does
    not fit: mana (Koskun Falls, War Tax) and sacrifice (Flooded Woodlands,
    Leviathan). Asked of the engine's own planners, so what the AI believes it
    can afford and what the declaration will charge are one answer.
    """
    if not attackers:
        return None
    seats = None if against is None else [against] * len(attackers)
    total, plan = game._declaration_mana_plan(seat, list(attackers), seats)
    if total and plan is None:
        return attackers[-1]
    if game._declaration_sacrifice_plan(seat, list(attackers)) is None:
        return attackers[-1]
    return None



def _unaffordable_blocker(
    game, defender_seat, attacker_owner, assigned, blockers, ordered_perms
):
    """The blocker to drop when this whole block declaration cannot be paid for.

    None when it can. :func:`_unaffordable_attacker`'s twin one step of combat
    over, and every word of that docstring applies: CR 509.1d locks in a total,
    affordability is a property of the set, and no rule can say which block to
    give up — so the weakest, which is last in the list handed here, is named.

    Both currencies are asked, because either can be the one that does not fit:
    mana (Hipparion, Awesome Presence, War Cadence) and life (Heat Wave,
    CR 119.4). Through the engine's own planners, so what the AI believes it can
    afford and what the declaration will charge are one answer.
    """
    if not ordered_perms:
        return None
    plan_assignments = {
        idx: (list(a) if isinstance(a, list) else [a]) for idx, a in assigned.items()
    }
    resolved_attackers = {}
    for attacker_indices in plan_assignments.values():
        for attacker_idx in attacker_indices:
            perm = game.permanent_at(attacker_owner, attacker_idx)
            if perm is not None:
                resolved_attackers[attacker_idx] = perm
    life_owed = game._block_declaration_life(
        plan_assignments, blockers, resolved_attackers
    )
    if life_owed and game.players[defender_seat].life < life_owed:
        return ordered_perms[-1]
    total, plan = game._block_declaration_mana_plan(
        defender_seat, plan_assignments, blockers, resolved_attackers
    )
    if total and plan is None:
        return ordered_perms[-1]
    return None


def choose_combat_blockers(
    game: Game,
    defending_player_index: int,
    *,
    ignore_substitution: bool = False,
) -> dict[int, int | list[int]]:
    """The blocks an AI seat declares for *defending_player_index*.

    ``ignore_substitution`` asks for the defender's *own* best blocks even while
    another seat is choosing (see the Melee note below) — the fallback for when
    the empty declaration a substituted chooser wants is itself illegal, because
    a blocking requirement (Lure) compels a block. An illegal-but-preferred
    answer is no answer at all, and the alternative is the safety valve that
    wipes every seat's blocks.
    """
    combat = game.get_combat_state()
    if game.current_turn_phase != "combat" or game.current_step != "declare_blockers":
        return {}
    if defending_player_index not in game.combat_defending_players():
        return {}
    # "You choose which creatures block this combat and how those creatures
    # block." (Melee.) CR 509.1a's chooser is someone else, and the weights
    # below score a block for the *defender* — handed to an opponent making the
    # choice they would pick the blocks that best defend the seat they are
    # attacking. Every printing of this substitution is cast by the attacking
    # player, so the honest answer is the one the card is played for: block with
    # nothing. Asked of the seam rather than of the card, so a second printing
    # needs no weight here; if a requirement (Lure) makes the empty declaration
    # illegal, the caller falls back to the defender's own choice, which is at
    # least legal.
    chooser = game.block_chooser_index(defending_player_index)
    if (
        not ignore_substitution
        and chooser != defending_player_index
        and chooser in game.opponents_of(defending_player_index)
    ):
        # "Nothing", as far as CR 509.1c allows. Invasion Plans prints the
        # substitution beside "All creatures block each combat if able", so on
        # the card's own board the empty declaration is illegal whenever a
        # creature can block — and the nearest legal one is the fewest blocks
        # the requirements force, which is still the chooser's play.
        return game.obeying_block_declaration(defending_player_index, {})

    active_index = game.active_player_index
    # CR 802.4a: this defender may only block attackers aimed at them.
    attackers = [
        int(item["attacker_index"])
        for item in combat.get("attackers", [])
        if item.get("defending_player_index") == defending_player_index
    ]
    if not attackers:
        return {}

    defender = game.players[defending_player_index]
    attacker_player = game.players[active_index]

    available_blockers = [
        idx
        for idx, blocker in enumerate(defender.battlefield)
        # A creature now (CR 509.1a through CR 613 layer 4): an animated land
        # blocks, an Aura that was a creature card does not.
        if blocker.is_creature and not blocker.tapped
    ]
    if not available_blockers:
        return {}

    legal_pairs: list[tuple[int, int, float]] = []
    # How many blockers each attacker needs at once, asked of the engine rather
    # than of the keyword: menace is the N=2 case of a printed template the
    # declaration gate reads through one helper (Gorilla Berserkers' "except by
    # three or more creatures"), and an AI that knew only the keyword would keep
    # submitting a declaration the gate bounces — which is a seat that declares
    # no blockers at all for the rest of the combat.
    minimum_blockers: dict[int, int] = {}
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        for attacker_idx in attackers:
            if attacker_idx < 0 or attacker_idx >= len(attacker_player.battlefield):
                continue
            attacker = attacker_player.battlefield[attacker_idx]
            minimum_blockers[attacker_idx] = game._minimum_blockers(attacker)
            if not game._can_block_attacker(blocker, attacker):
                continue
            legal_pairs.append((blocker_idx, attacker_idx, _score_block_pair(blocker, attacker)))

    if not legal_pairs:
        return {}

    assignments: dict[int, int] = {}
    used_blockers: set[int] = set()

    # Priority 0: the blocks CR 509.1c already requires of one creature
    # against one attacker (provoke). The engine makes them whatever this seat
    # chooses (`Game.obeying_block_declaration`, last), so they are counted
    # first: a provoked creature that kills its attacker alone is a fight
    # nobody else joins, where three blockers on a provoked 4/1 lost a
    # Skinthinner the attacker chose to kill (LGN Phase 5).
    for blocker_idx, attacker_idx in compelled_blocks(game, defending_player_index).items():
        if blocker_idx in available_blockers and attacker_idx in attackers:
            assignments[blocker_idx] = attacker_idx
            used_blockers.add(blocker_idx)

    # Priority 1: prevent lethal where possible.
    incoming = _estimated_incoming_player_damage(game, defending_player_index)
    life = defender.life
    if incoming >= life:
        for blocker_idx, attacker_idx, _ in sorted(legal_pairs, key=lambda item: _estimated_damage_prevented(game, defending_player_index, item[1], item[0]), reverse=True):
            if blocker_idx in used_blockers:
                continue
            # A second blocker on an attacker already stopped stops nothing
            # more (trample aside): counted again, the damage it "prevented"
            # ended this loop early with an attacker still unblocked.
            if attacker_idx in assignments.values() and not game._has_keyword(
                game.permanent_at(active_index, attacker_idx), "trample",
            ):
                continue
            prevented = _estimated_damage_prevented(game, defending_player_index, attacker_idx, blocker_idx)
            if prevented <= 0:
                continue
            assignments[blocker_idx] = attacker_idx
            used_blockers.add(blocker_idx)
            incoming -= prevented
            if incoming < life:
                break

    # Priority 2: the blocks that do not give their blocker away — a kill, a
    # trade, a bounce — best first. **A losing block is set aside**, not made:
    # this loop took every legal pair whatever its score said, so at twenty
    # life a 2/2 chumped a 5/3 that would have dealt five (W1G2), and half
    # the blocks in the seeded runs were a creature lost for damage the
    # defender could take. Which block loses is the provoke chooser's own
    # estimate of the fight (`ai_compelled_blocks.fight_outcome`: first
    # strike, deathtouch, indestructible, a regeneration or prevention
    # shield), not the bare power-against-toughness `_score_block_pair`
    # ranks by.
    #
    # **An attacker the blocks already kill takes no more** (CR 510.1c: a
    # blocked creature's damage is "divided as its controller chooses among"
    # its blockers, with no order to it in this edition): a further blocker
    # adds nothing to the kill and is one more creature the attacker may choose
    # to destroy. This loop gave every blocker its best pair, so three
    # creatures that each beat a 1/1 all blocked it and Daru Mender was lost
    # (LGN Phase 5) — and of two 3/3s facing two 2/2s, both blocked the first.
    # The blocker is left for its next-best pair.
    losing: list[tuple[int, int, float]] = []
    for blocker_idx, attacker_idx, score in sorted(legal_pairs, key=lambda item: item[2], reverse=True):
        if blocker_idx in used_blockers:
            continue
        if blocker_idx in assignments:
            continue
        if _blocks_already_kill(game, defending_player_index, attacker_idx, assignments):
            continue
        if _block_loses_its_blocker(game, defending_player_index, blocker_idx, attacker_idx):
            losing.append((blocker_idx, attacker_idx, score))
            continue
        assignments[blocker_idx] = attacker_idx
        used_blockers.add(blocker_idx)
    # Priority 3: losing blocks that together kill their attacker (a gang
    # block), where the attacker is worth more than what it can kill back.
    _gang_blocks(game, defending_player_index, losing, assignments, used_blockers)
    # Priority 4: a chump block, where the life it saves is worth more than
    # the creature it costs — the trade the rehearsal's own scale prices.
    _chump_blocks(game, defending_player_index, losing, assignments, used_blockers)

    # CR 509.1b's minimum-blocker restrictions (menace, and Gorilla Berserkers'
    # printed spelling of the same thing): declare_blockers refuses an
    # assignment that puts fewer than N blockers on such an attacker, so the AI
    # declines those blocks rather than submitting a declaration that bounces.
    # Ganging up is a valuation question for another day; not blocking is always
    # legal.
    menace_counts: dict[int, int] = {}
    for assigned in assignments.values():
        for attacker_idx in assigned if isinstance(assigned, list) else [assigned]:
            menace_counts[attacker_idx] = menace_counts.get(attacker_idx, 0) + 1
    for attacker_idx, count in menace_counts.items():
        if count >= minimum_blockers.get(attacker_idx, 1):
            continue
        for blocker_idx in list(assignments):
            assigned = assignments[blocker_idx]
            if isinstance(assigned, list):
                remaining = [a for a in assigned if a != attacker_idx]
                if remaining:
                    assignments[blocker_idx] = remaining
                else:
                    del assignments[blocker_idx]
            elif assigned == attacker_idx:
                del assignments[blocker_idx]

    # CR 509.1b's restrictions on the declaration as a whole — the mirror of
    # `_legal_declaration` at the tail of `choose_attackers`.
    pruned = _legal_block_declaration(game, defending_player_index, assignments)
    # …and CR 509.1c's requirements, **last**, asked of the engine's own
    # maximisation (``Game.obeying_block_declaration``): handed back unchanged
    # when the gate accepts it, otherwise the nearest declaration obeying the
    # most requirements any declaration can, with the blocks this seat chose
    # tried first and the rest ranked by the same `_score_block_pair` that
    # chose them.
    #
    # Last because the prune just above cannot see a requirement: a cap is
    # disobeyed by the set, so it drops the worst block — and the worst block
    # may be the compelled one, so under a Caverns of Despair a Watchdog
    # dropped for a Bear the seat liked better left a declaration the gate
    # refuses whole. And asked of the engine rather than answered here: this
    # function used to carry four requirement blocks of its own (Blaze of
    # Glory, "must be blocked if able", Trumpeting Armodon, Watchdog), each an
    # addition test like the gate's five were, reading one channel apiece —
    # Watchdog's printed line but not Provoke's mark, Invasion Plans or an
    # Aura — so the seat's guess and the rule drifted exactly where a
    # requirement was armed some other way.
    return game.obeying_block_declaration(
        defending_player_index, pruned, rank=_score_block_pair
    )


def _block_loses_its_blocker(
    game: Game, defending_player_index: int, blocker_idx: int, attacker_idx: int,
) -> bool:
    """Whether the blocker at *blocker_idx* blocking the attacker at
    *attacker_idx* alone dies and leaves the attacker alive — a block that
    gives a creature away for the damage it stops (CR 510.1)."""
    attacker = game.permanent_at(game.active_player_index, attacker_idx)
    blocker = game.permanent_at(defending_player_index, blocker_idx)
    if attacker is None or blocker is None:
        return False
    blocker_dies, attacker_dies = fight_outcome(game, attacker, blocker)
    return blocker_dies and not attacker_dies


#: The most losing blocks one gang is built from. A limited board rarely has
#: more spare blockers than this, and the kill-back below is an exact search
#: over subsets of the gang.
GANG_BLOCKERS = 4

#: How many of the cheapest spare blockers a gang is searched among: every
#: gang of up to `GANG_BLOCKERS` of them is weighed (at most 162).
GANG_CANDIDATES = 8


def _blockers_on(
    game: Game, defending_player_index: int, attacker_idx: int, assignments: dict,
) -> list[Permanent]:
    """The creatures *assignments* already has blocking the attacker at
    *attacker_idx*."""
    found = [
        game.permanent_at(defending_player_index, blocker_idx)
        for blocker_idx, assigned in assignments.items()
        if attacker_idx in (assigned if isinstance(assigned, list) else [assigned])
    ]
    return [permanent for permanent in found if permanent is not None]


def _blocks_already_kill(
    game: Game, defending_player_index: int, attacker_idx: int, assignments: dict,
) -> bool:
    """Whether the blocks in *assignments* already destroy the attacker at
    *attacker_idx* (:func:`_gang_kills`)."""
    attacker = game.permanent_at(game.active_player_index, attacker_idx)
    return attacker is not None and _gang_kills(
        game, attacker, _blockers_on(game, defending_player_index, attacker_idx, assignments),
    )


def _gang_blocks(
    game: Game,
    defending_player_index: int,
    losing: list[tuple[int, int, float]],
    assignments: dict[int, int],
    used_blockers: set[int],
) -> None:
    """Add to *assignments* the losing blocks (*losing*, best first) that
    together kill their attacker, attacker by attacker, most worth killing
    first — where the attacker is worth more than the blockers it can kill
    back (:func:`_gang_is_worth_it`).

    What the old loop did by accident (every blocker took its best pair, and
    two that liked one attacker blocked it together) as a decision: two 2/2s
    on a 3/3 trade one for it; two 1/1s on a 5/5 lose both for nothing.

    **Which gang**: of every gang of up to `GANG_BLOCKERS` among the
    `GANG_CANDIDATES` cheapest spare blockers that kills the attacker beside
    the creatures already blocking it (a compelled one included) and is worth
    it, the one the attacker can kill back least of (CR 510.1c: it divides its
    damage as it likes), then the smallest, then the cheapest. A creature the
    attacker cannot destroy — protection from its colour, indestructible, too
    much toughness — costs that gang nothing, so it is the one taken. Adding
    the cheapest creatures one at a time until the damage added up took
    whatever came first, a creature more than the kill needed among them.
    """
    from itertools import combinations

    attacker_seat = game.active_player_index
    candidates: dict[int, list[int]] = {}
    for blocker_idx, attacker_idx, _score in losing:
        candidates.setdefault(attacker_idx, []).append(blocker_idx)

    def attacker_worth(attacker_idx: int) -> float:
        attacker = game.permanent_at(attacker_seat, attacker_idx)
        return permanent_worth(attacker, now=False) if attacker is not None else 0.0

    for attacker_idx in sorted(candidates, key=attacker_worth, reverse=True):
        attacker = game.permanent_at(attacker_seat, attacker_idx)
        if attacker is None:
            continue
        already = _blockers_on(game, defending_player_index, attacker_idx, assignments)
        if _gang_kills(game, attacker, already):
            continue

        def worth(idx: int) -> float:
            return permanent_worth(game.permanent_at(defending_player_index, idx), now=False)

        spare = sorted(
            (
                blocker_idx for blocker_idx in candidates[attacker_idx]
                if blocker_idx not in used_blockers
            ),
            key=worth,
        )[:GANG_CANDIDATES]
        best = None
        for size in range(1, min(GANG_BLOCKERS, len(spare)) + 1):
            for gang in combinations(spare, size):
                members = already + [
                    game.permanent_at(defending_player_index, idx) for idx in gang
                ]
                if not _gang_kills(game, attacker, members):
                    continue
                if not _gang_is_worth_it(game, attacker, members):
                    continue
                lost = sum(
                    permanent_worth(member, now=False)
                    for member in _kills_back(game, attacker, members)
                )
                key = (lost, size, sum(worth(idx) for idx in gang))
                if best is None or key < best[0]:
                    best = (key, gang)
        if best is not None:
            for idx in best[1]:
                assignments[idx] = attacker_idx
                used_blockers.add(idx)


def _kills_back(game: Game, attacker: Permanent, members: list[Permanent]) -> list[Permanent]:
    """The blockers among *members* the attacker's combat damage can destroy,
    chosen the way that costs the defender most (CR 510.1c: the attacking
    player divides the damage, lethal damage to each in turn): the most
    valuable set whose lethal damage its power covers. Deathtouch makes one
    point lethal (CR 702.2c); an indestructible or shielded blocker is not
    destroyed, nor one the attacker's damage would be prevented on —
    protection from its colour (CR 702.16e), a Circle — as
    `ai_compelled_blocks.fight_outcome` reads the same fight one on one."""
    from itertools import combinations

    from .ai_combat import _would_be_prevented

    power = combat_damage_assigned_by(attacker)
    if power <= 0:
        return []
    costs: list[tuple[Permanent, int]] = []
    for member in members:
        if game._has_keyword(member, "indestructible") or member.regeneration_shield:
            continue
        if _would_be_prevented(game, attacker, member, power):
            continue
        remaining = max(1, member.effective_toughness - member.damage_marked)
        costs.append((member, 1 if game._has_keyword(attacker, "deathtouch") else remaining))
    best: list[Permanent] = []
    best_worth = 0.0
    for size in range(1, len(costs) + 1):
        for chosen in combinations(costs, size):
            if sum(cost for _member, cost in chosen) > power:
                continue
            worth = sum(permanent_worth(member, now=False) for member, _cost in chosen)
            if worth > best_worth:
                best, best_worth = [member for member, _cost in chosen], worth
    return best


def _gang_kills(game: Game, attacker: Permanent, members: list[Permanent]) -> bool:
    """Whether *members* blocking *attacker* together destroy it: their
    combat damage (less what a shield would stop) reaches lethal, and those
    the attacker's first-strike damage kills first deal none (CR 510.4)."""
    # The attacker's own damage chooser's question (`ai_combat`, which
    # imports this module): a Circle's shield, protection, a Fog.
    from .ai_combat import _would_be_prevented

    if not members:
        return False
    if game._has_keyword(attacker, "indestructible") or attacker.regeneration_shield:
        return False
    first_struck: list[Permanent] = []
    if game._has_keyword(attacker, "first strike") or game._has_keyword(
        attacker, "double strike"
    ):
        first_struck = [
            member for member in _kills_back(game, attacker, members)
            if not (
                game._has_keyword(member, "first strike")
                or game._has_keyword(member, "double strike")
            )
        ]
    remaining = attacker.effective_toughness - attacker.damage_marked
    dealt = 0
    for member in members:
        if any(member is struck for struck in first_struck):
            continue
        amount = combat_damage_assigned_by(member)
        if amount <= 0 or _would_be_prevented(game, member, attacker, amount):
            continue
        if game._has_keyword(member, "deathtouch"):
            return True
        dealt += amount
    return dealt >= max(1, remaining)


def _gang_is_worth_it(game: Game, attacker: Permanent, members: list[Permanent]) -> bool:
    """Whether killing *attacker* is worth more than the blockers it can
    destroy back (:func:`_kills_back`), each read as the board will be once
    the turn is over (``ai_rehearsal.permanent_worth``)."""
    lost = sum(permanent_worth(member, now=False) for member in _kills_back(game, attacker, members))
    return permanent_worth(attacker, now=False) > lost


def _chump_blocks(
    game: Game,
    defending_player_index: int,
    losing: list[tuple[int, int, float]],
    assignments: dict[int, int],
    used_blockers: set[int],
) -> None:
    """Add to *assignments* the chump blocks worth making: an unblocked
    attacker blocked by a creature that dies stopping it, where the life the
    block saves is worth more than the creature
    (``ai_rehearsal.life_worth`` against ``permanent_worth`` — the scale
    every rehearsal reads a position on, under which a point of life is
    worth more the less of it is left and the loss of the game is worth
    everything). So a 2/2 does not chump a 5/3 at twenty life, a token chumps
    it at five, and anything chumps the attacker that would kill.

    The biggest hits first, each against the damage still unblocked."""
    life = game.players[defending_player_index].life
    ranked = sorted(
        losing,
        key=lambda item: _estimated_damage_prevented(
            game, defending_player_index, item[1], item[0],
        ),
        reverse=True,
    )
    for blocker_idx, attacker_idx, _score in ranked:
        if blocker_idx in used_blockers:
            continue
        if attacker_idx in assignments.values():
            continue
        blocker = game.permanent_at(defending_player_index, blocker_idx)
        if blocker is None:
            continue
        saved = _estimated_damage_prevented(
            game, defending_player_index, attacker_idx, blocker_idx,
        )
        if saved <= 0:
            continue
        after = life - _estimated_unblocked_damage(
            game, defending_player_index, assignments,
        )
        if life_worth(after + saved) - life_worth(after) <= permanent_worth(blocker, now=False):
            continue
        assignments[blocker_idx] = attacker_idx
        used_blockers.add(blocker_idx)


def _estimated_unblocked_damage(
    game: Game, defending_player_index: int, assignments: dict[int, int],
) -> int:
    """The combat damage the attackers aimed at *defending_player_index*
    would deal it under *assignments*: an unblocked attacker's power, and a
    blocked trampler's excess over its blockers' toughness (CR 702.19b)."""
    attacker_seat = game.active_player_index
    blockers_of: dict[int, list[Permanent]] = {}
    for blocker_idx, assigned in assignments.items():
        blocker = game.permanent_at(defending_player_index, blocker_idx)
        if blocker is None:
            continue
        for attacker_idx in assigned if isinstance(assigned, list) else [assigned]:
            blockers_of.setdefault(attacker_idx, []).append(blocker)
    total = 0
    for item in game.get_combat_state().get("attackers", []):
        if item.get("defending_player_index") != defending_player_index:
            continue
        attacker_idx = int(item.get("attacker_index", -1))
        attacker = game.permanent_at(attacker_seat, attacker_idx)
        if attacker is None:
            continue
        power = max(0, attacker.effective_power)
        blockers = blockers_of.get(attacker_idx)
        if not blockers:
            total += power
        elif game._has_keyword(attacker, "trample"):
            total += max(0, power - sum(
                max(0, b.effective_toughness - b.damage_marked) for b in blockers
            ))
    return total


def _score_block_pair(blocker: Permanent, attacker: Permanent) -> float:
    blocker_kills = blocker.effective_power >= attacker.effective_toughness
    attacker_kills = attacker.effective_power >= blocker.effective_toughness

    attacker_value = _permanent_value(attacker)
    blocker_value = _permanent_value(blocker)

    score = 0.0
    if blocker_kills and not attacker_kills:
        score += attacker_value + 4.0
    elif blocker_kills and attacker_kills:
        score += attacker_value - blocker_value * 0.6 + 2.0
    elif not blocker_kills and attacker_kills:
        score -= blocker_value + 2.0
    else:
        score += min(attacker.effective_power, blocker.effective_toughness) * 0.5

    # Prefer blocking higher impact attackers.
    score += attacker.effective_power * 0.3 + attacker.effective_toughness * 0.2
    return score


def _estimated_damage_prevented(game: Game, defending_player_index: int, attacker_idx: int, blocker_idx: int) -> int:
    attacker = game.players[game.active_player_index].battlefield[attacker_idx]
    blocker = game.players[defending_player_index].battlefield[blocker_idx]
    power = max(0, attacker.effective_power)
    if game._has_keyword(attacker, "trample"):
        return min(power, max(0, blocker.effective_toughness - blocker.damage_marked))
    return power


def _estimated_incoming_player_damage(game: Game, defending_player_index: int) -> int:
    combat = game.get_combat_state()
    total = 0
    for item in combat.get("attackers", []):
        if item.get("defending_player_index") != defending_player_index:
            continue
        attacker_idx = int(item.get("attacker_index", -1))
        if attacker_idx < 0 or attacker_idx >= len(game.players[game.active_player_index].battlefield):
            continue
        attacker = game.players[game.active_player_index].battlefield[attacker_idx]
        total += max(0, attacker.effective_power)
    return total

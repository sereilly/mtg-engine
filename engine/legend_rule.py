"""CR 704.5j, the legend rule — and the choice it gives the player.

    704.5j If two or more legendary permanents with the same name are
    controlled by the same player, that player chooses one of them, and the
    rest are put into their owners' graveyards.

The state-based check (``GameEndingMixin._state_based_pass``) used to keep
whichever came first on the battlefield and asked nobody. The first card to
make that visibly wrong was Helm of Kaldra: a second activation creates a new
Kaldra and moves all three Equipment onto it, and the check kept the old,
bare 4/4 and binned the new, fully equipped one (Fifth Dawn W1G4).

**A seat a person decides for is asked** (``Game.asks_a_person``: a person's
own seat, or one a person controls this turn, CR 723): the check arms a
``legend_rule`` prompt per same-name group — its data names the legendary name
and the candidates by ``permanent_id`` — and leaves the group where it is.
The game waits on the prompt (it holds priority like every prompt that
refuses other actions, CR 117.3b). The answer records which one stays
(``kept``) and makes the check again, which is where the rest are put into
their owners' graveyards: the check **resumes** with the answer rather than
the resolver moving cards outside it, so the departures are one state-based
event (CR 704.3, ``leaving_together``) like every other sweep's.

**A seat nobody asks keeps the one worth most to it**
(``ai_prompt_picks.legend_rule_keep``: Kaldra equipped over Kaldra bare, a
creature with counters over one without, an untapped one over a tapped one),
and the first on the battlefield between equals — so a seeded game reproduces
itself, and a table that never sees two different copies plays exactly as it
did when the first was always kept.

**APNAP** (CR 101.4): the seats are walked active player first. Each asked
group is its own prompt, armed in that order, and a seat with two groups is
asked about each in the order their first members sit on its battlefield.
Two asked groups' departures happen at their own answers, not together — the
one place this reading is coarser than CR 101.4's "then the actions happen
simultaneously". An owed prompt whose group has stopped being one (a member
left by another state-based action of a later pass) is dropped: the rule no
longer applies to that player.

Both reads are of the **effective** permanent, as the sweep always was:
CR 707.2 copies the name and the type line together (a Clone of Hazezon
Tamar is a second Hazezon Tamar), and layer 4 computes supertypes (CR 205.4a),
so a "legendary" an effect added or took away is counted where the printed
read would have missed both.
"""

from __future__ import annotations

#: The prompt kind — ``LEGEND_RULE_SPEC`` in ``mixins/stack/choices/permanents.py``.
LEGEND_RULE = "legend_rule"


def legend_groups(game, seat: int) -> list[tuple[str, list]]:
    """*seat*'s legendary permanents that share a name with another it
    controls: ``(name, permanents)`` per name, two or more each, in the order
    each name's first permanent sits on the battlefield and each group in
    battlefield order."""
    by_name: dict[str, list] = {}
    for perm in game.controlled_by(seat):
        if perm.has_supertype("legendary"):
            by_name.setdefault(perm.effective_card.name, []).append(perm)
    return [(name, perms) for name, perms in by_name.items() if len(perms) > 1]


def live_candidates(game, choice) -> list:
    """The permanents a ``legend_rule`` prompt is about **now**: every
    legendary permanent its seat controls with its name. Re-derived rather than
    frozen at arming, so the list offered, the list an answer is checked
    against and the list binned are one rule."""
    name = choice.data.get("name")
    return [
        perm for perm in game.controlled_by(choice.player_index)
        if perm.has_supertype("legendary") and perm.effective_card.name == name
    ]


def state_based_legend_rule(game) -> bool:
    """One pass of CR 704.5j over every seat; True when it put anything into
    a graveyard or asked anybody anything.

    A group already owed a prompt waits for its answer — or, answered
    (``kept``), keeps that one and puts the rest into their owners'
    graveyards. Any other group is armed: queued for a seat a person decides
    for, and answered on the spot by a seat nobody asks (``default_at_arm``,
    :func:`default_legend_rule`)."""
    changed = False
    for seat in game.apnap_seats(include_lost=True):
        groups = legend_groups(game, seat)
        owed = {
            choice.data.get("name"): choice
            for choice in game.pending_choices_of(LEGEND_RULE, seat)
        }
        if not groups and not owed:
            continue
        for name, perms in groups:
            choice = owed.pop(name, None)
            if choice is None:
                game.arm_pending_choice(
                    "legend_rule", seat,
                    name=name,
                    candidates=[perm.permanent_id for perm in perms],
                    # A state-based action is nobody's spell or ability
                    # (CR 704.3), and no object waits on the stack for it:
                    # stamped empty so the queue's stamps never tie the
                    # prompt to whatever happens to be resolving.
                    _stack_item=None,
                    _cause_seat=None,
                    _resolving_targets=None,
                )
                changed = True
                continue
            kept = _recorded_keep(choice, perms)
            if kept is None:
                ids = [perm.permanent_id for perm in perms]
                if choice.data.get("candidates") != ids:
                    # A copy arrived or left while the prompt was owed: the
                    # payload says what the answer will be held to.
                    choice.data["candidates"] = ids
                continue
            game.discard_pending_choice(choice)
            put_the_rest_into_graveyards(game, seat, name, kept, perms)
            changed = True
        # What is left owed no longer has a group behind it.
        for choice in owed.values():
            game.discard_pending_choice(choice)
            changed = True
    return changed


def _recorded_keep(choice, perms):
    """The permanent an answered prompt keeps, while it is still one of
    *perms*; None for an unanswered one."""
    kept_id = choice.data.get("kept")
    if kept_id is None:
        return None
    kept = next((perm for perm in perms if perm.permanent_id == kept_id), None)
    if kept is None:
        choice.data.pop("kept", None)
    return kept


def put_the_rest_into_graveyards(game, seat: int, name: str, kept, perms) -> None:
    """Everything in *perms* but *kept* to its owner's graveyard (a token
    ceases to exist, CR 111.7), last first, each with its log line."""
    for removed in reversed([perm for perm in perms if perm is not kept]):
        game.remove_from_battlefield(removed)
        died = game._permanent_to_graveyard(game.players[seat], removed)
        game.log.append(
            f"{name} {'put into graveyard' if died else 'left the battlefield'} "
            "(704.5j: legend rule)"
        )


def _keep(game, choice, kept, live) -> None:
    """Carry out a keep: on the queue (an answer, or a drained default),
    record it and make the check, which puts the rest away; armed inside the
    check by a seat nobody asks (never queued), put the rest away here."""
    if any(queued is choice for queued in game.pending_choices):
        choice.data["kept"] = kept.permanent_id
        game.log.append(
            f"{game.players[choice.player_index].name} keeps "
            f"{choice.data.get('name')} (704.5j: legend rule)"
        )
        game.check_state_based_actions()
        # The check was made because a player would receive priority (CR
        # 704.3), nearly always after something resolved, and the priority
        # pass handed the window to the seat that owed this answer while it
        # was owed ("awaiting_choice"). Answered, it is CR 117.3b's again:
        # the active player receives priority — what the release of a held
        # resolution does (``_release_stack_item``).
        if game.priority_player_index is not None and game.waiting_prompt() is None:
            game.priority_player_index = game.active_player_index
            game.priority_pass_count = 0
        return
    put_the_rest_into_graveyards(
        game, choice.player_index, choice.data.get("name"), kept, live
    )


def resolve_legend_rule(game, choice, response: dict) -> bool:
    """A person's answer: ``permanent_id``, the one to keep. Refused unless it
    names one of the group as it stands; a group that has stopped being one is
    answered by any response (there is nothing left to choose)."""
    live = live_candidates(game, choice)
    if len(live) < 2:
        game.discard_pending_choice(choice)
        return True
    wanted = response.get("permanent_id")
    kept = next((perm for perm in live if perm.permanent_id == wanted), None)
    if kept is None:
        return False
    _keep(game, choice, kept, live)
    return True


def default_legend_rule(game, choice) -> None:
    """A seat nobody asks keeps the one worth most to it
    (``ai_prompt_picks.legend_rule_keep``), the first on the battlefield
    between equals."""
    from .ai_prompt_picks import legend_rule_keep

    live = live_candidates(game, choice)
    if len(live) < 2:
        game.discard_pending_choice(choice)
        return
    _keep(game, choice, legend_rule_keep(game, choice.player_index, live), live)


__all__ = [
    "LEGEND_RULE",
    "default_legend_rule",
    "legend_groups",
    "live_candidates",
    "put_the_rest_into_graveyards",
    "resolve_legend_rule",
    "state_based_legend_rule",
]

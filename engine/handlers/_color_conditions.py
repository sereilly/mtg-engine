"""What a condition payload means when it asks about **colour**.

The third family ``control_flow.evaluate_condition`` hands a kind to, and the
handler twin of ``engine/grammar/lowering/_color_conditions.py``: a colour
asked of the object the guarded effect targets — on its own ("if it's red",
Hydroblast), against the census of the whole battlefield (Tsabo's Assassin),
against one chosen permanent (Guard Dogs), a described set (Jaded Response) or
the other target (Dead Ringers) — or the census asked about a printed colour
with no object at all (the Invasion Djinns). CR 105.2's colour set, asked of
``engine/color_census.py`` and ``engine/object_colors.py``.

Split out of ``control_flow.py`` at the 2,000-line cap's split round with the
two families beside it (``_conditions`` says why the chain divides). It shares
no reader with either. It registers no handler, hence the underscore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


def evaluate_color_condition(
    game: Game, context: OracleExecutionContext, payload: dict,
    kind: str | None,
) -> object:
    """A condition about **colour** — the guarded effect's target, the census
    of the battlefield, or both — or ``NotImplemented`` when *kind* is not one
    of them.

    Asked by ``control_flow.evaluate_condition``, which has already read
    *kind* off *payload*.
    """

    if kind == "target_is_color":
        # "Counter target spell **if it's red**." (Hydroblast, Pyroblast.)
        # CR 608.2c: the colour is read while the instruction is followed, not
        # when the target was chosen — so a spell that was red at announcement
        # and is not now goes uncountered, and the picker offers every spell
        # because "target spell" is the whole of the printed restriction
        # (CR 608.2b).
        #
        # Which object the pronoun names was decided at lowering, off the
        # effect this guards, and the two halves are resolved by the readers
        # those effects use: a counter reads `context.stack_target`, a destroy
        # resolves the chosen permanent. Asking one and falling back to the
        # other would answer about whatever object happened to be in reach.
        wanted = payload.get("color")
        if payload.get("target") == "spell":
            chosen = context.stack_target
            colors = (
                game._stack_item_colors(chosen)
                if chosen is not None and chosen in game.stack
                else ()
            )
        else:
            from ._filters import permanent_effective_colors
            from ._targets import resolve_target_permanent

            target = resolve_target_permanent(
                game, context,
                predicate=lambda perm: True,
                fallback_players=(),
                fallback_on_invalid_choice=False,
            )
            colors = permanent_effective_colors(target) if target is not None else ()
        # An object that is gone answers no to both readings, rather than
        # letting the negated one say yes about something that is not there —
        # the same call the keyword condition below makes.
        if not colors and payload.get("negated"):
            return False
        matched = wanted in colors
        return (not matched) if payload.get("negated") else matched

    if kind == "target_shares_most_common_color":
        # "Destroy target creature **if it shares a color with the most common
        # color among all permanents** or a color tied for most common."
        # (Tsabo's Assassin, Barrin's Unmaking.) CR 608.2c again: the census is
        # taken while the instruction is followed, so a permanent that entered
        # or was recoloured in response is counted, and the target itself is one
        # of "all permanents" — a lone coloured target is always most common.
        #
        # The picker offers every permanent the noun phrase admits: the clause
        # is a condition on the *effect*, not a targeting restriction, so a
        # target that fails it is a legal target the spell simply does nothing
        # to (CR 608.2b reads the printed target phrase, which says no colour).
        #
        # The same resolver the colour clause above uses, for its reason: the
        # branch and the effect beside it must mean one permanent. A target
        # that is gone shares a colour with nothing.
        from ..color_census import shares_most_common_color
        from ._targets import resolve_target_permanent

        target = resolve_target_permanent(
            game, context,
            predicate=lambda perm: True,
            fallback_players=(),
            fallback_on_invalid_choice=False,
        )
        return shares_most_common_color(game, target)

    if kind == "target_shares_color_with_chosen":
        # "Prevent all combat damage target creature would deal this turn **if
        # it shares a color with that permanent**." (Guard Dogs.) CR 105.2's
        # relation between the effect's target and the permanent a step earlier
        # in this resolution chose — both read now, while the instruction is
        # followed (CR 608.2h), and both through layer 5: a target a response
        # recoloured is judged on the colour it has, not the one it was aimed
        # at for.
        #
        # ``object_colors.share_a_color`` is the one reading of the relation:
        # a colourless object on either side shares nothing, and so does a
        # choice that was never made or whose permanent has gone.
        from ..object_colors import share_a_color
        from ._targets import resolve_target_permanent

        target = resolve_target_permanent(
            game, context,
            predicate=lambda perm: True,
            fallback_players=(),
            fallback_on_invalid_choice=False,
        )
        recorded = context.results.get(str(payload.get("permanent_from") or ""))
        chosen = (
            game.permanent_by_id(recorded) if isinstance(recorded, int) else None
        )
        if target is None or chosen is None:
            return False
        return share_a_color(
            game._effective_colors(target), game._effective_colors(chosen)
        )

    if kind == "target_shares_color_with_matching":
        # "Counter target spell **if it shares a color with a creature you
        # control**." (Jaded Response.) CR 105.2's relation between the spell
        # this effect targets and every permanent the printed phrase admits —
        # both read now, while the instruction is followed (CR 608.2c): a
        # creature that entered, left or was recoloured in response is judged
        # as it stands, and so is a spell a Lace or a Vodalian Mystic changed.
        #
        # The picker offers every spell: the clause is a condition on the
        # *effect*, not a targeting restriction ("target spell" is the whole of
        # the printed target phrase, CR 608.2b), so a spell that fails it is a
        # legal target the counter does nothing to.
        #
        # The spell's colours through ``_stack_item_colors`` — the one reader
        # of what colour a stack object is — and each permanent's through layer
        # 5. ``share_a_color`` is the one reading of the relation: a colourless
        # object on either side shares nothing (CR 105.2c), and a spell that
        # has left the stack answers no, like every clause beside this one.
        from ..object_colors import share_a_color
        from ..subject_filters import subject_matches

        chosen = context.stack_target
        if (
            payload.get("target") != "spell"
            or chosen is None
            or chosen not in game.stack
            or context.caster not in game.players
        ):
            return False
        colors = game._stack_item_colors(chosen)
        if not colors:
            return False
        described = dict(payload.get("filter") or {})
        observer = game.players.index(context.caster)
        return any(
            share_a_color(colors, game._effective_colors(permanent))
            for permanent in game.all_permanents()
            if subject_matches(
                game, permanent, described, observer=observer,
                source=context.source_permanent,
            )
        )

    if kind == "targets_differ_in_color":
        # "…unless **either one is a color the other isn't**." (Dead Ringers.)
        # CR 105.2 over the two targets' colour *sets*, read now, while the
        # instruction is followed (CR 608.2h) and through layer 5: equal sets
        # are the only way not to differ, so two colourless creatures do not
        # (CR 105.2c — the card's ruling says so) and a white-blue creature
        # beside a blue one does.
        #
        # **A pair this cannot read differs.** CR 608.2b: "If part of the
        # effect requires information about an illegal target, it fails to
        # determine any such information" — so with one target gone, or made
        # illegal in response (protection from black is the ordinary way), the
        # comparison has no answer, and the sentence that needs one does not
        # happen. The clause is printed behind "unless", where "they differ" is
        # the answer under which nothing is destroyed — the survivor is not
        # destroyed alone on the strength of a comparison nobody could make.
        from ._targets import resolve_target_slots

        first, second = resolve_target_slots(game, context, 2)
        if (
            first is None or second is None or first is second
            or not game.is_on_battlefield(first)
            or not game.is_on_battlefield(second)
            or not game.resolving_targets_all_legal()
        ):
            return True
        return frozenset(game._effective_colors(first)) != frozenset(
            game._effective_colors(second)
        )

    if kind == "color_is_most_common":
        # "…white is the most common color among all permanents or is tied for
        # most common." The Djinns print it on a static, where
        # ``static_bonuses.conditional_static_holds`` answers it; this is the
        # same payload reaching an intervening-if or a sentence-level "if", and
        # the same census answers it so the two cannot disagree about a tie.
        from ..color_census import color_is_most_common

        return color_is_most_common(
            game, str(payload.get("color") or ""),
            tied=bool(payload.get("tied", True)),
        )

    # Not a kind of this family: ``control_flow.evaluate_condition`` asks the
    # next one, and answers False when none of them claims it.
    return NotImplemented

"""The recompute's layer-1 and layer-7 half: what the board makes a creature.

``_refresh_dynamic_creatures`` is the last step of
``GameHelpersMixin._recompute_continuous_effects`` (CR 611.3a), and it
rebuilds from scratch every channel it owns rather than adjusting it:

* layer 1 first (CR 613.1a) - a copy whose source is a position in a zone
  (Volrath's Shapeshifter, ``_refresh_zone_copies``) is re-pointed before
  anything reads the permanent's ``effective_card``;
* layer 4 through ``BoardStaticsMixin._refresh_global_statics``, so a
  characteristic-defining P/T counts the lands this pass animated;
* layer 7a, characteristic-defining P/T (CR 604.3): one ``dynamic_pt_count``
  instruction describing what to count, tallied by ``_count_dynamic_pt``;
* the conditional layer-7c contributions - "as long as" bonuses, Aspect of
  Wolf, Snowblind's clamped penalty, "for as long as this artifact remains
  tapped" - into the *derived* buff channel, which this module alone clears
  (``_add_static_pt`` says why that matters);
* and, for the same reason of being a static rebuilt every pass, what each
  seat may spend mana as (CR 106.6, ``_refresh_mana_spending``) and the
  landwalks a board names.
"""

from __future__ import annotations

import re

from ..entry_choices import LIFE_PAID_AS_ENTERED
from ..aura_attachment import auras_attached_to
from .. import copies
from ..landwalk import BOARD_NAMED_LANDWALKS, board_named_landwalks
from ..zone_copies import ZONE_TOP_COPY_KIND, zone_top_copy_from_payload
from ..handlers._amounts import evaluate_count, resolve_amount
from ..handlers._targets import attached_host
from ..subject_filters import subject_matches
from ..models import Permanent, PlayerState
from ..oracle import compile_card_oracle
from ..pt import clear_cda_pt, set_cda_pt
from ..static_bonuses import (BASIC_LAND_WORDS, conditional_static_holds,
                              singular_land_type)


# "half the number of <land type>s you control" (Aspect of Wolf). The type is a
# capture rather than a literal, so a Magical Hack rewriting the word moves the
# count with it.
_HALF_LAND_COUNT_RE = re.compile(r"half the number of ([a-z]+) you control")


# Characteristic-defining P/T (CR 604.3 / layer 7a). There is no registry to
# add to: the instruction describes what to count, so a card printed with one
# of these templates needs no code here at all.
def _count_dynamic_pt(
    game, player: PlayerState, permanent: Permanent, payload: dict
) -> int:
    """Tally the objects a ``dynamic_pt_count`` instruction describes.

    One counter for every characteristic-defining P/T, because they differ only
    in *what* they count and *whose* battlefield they count it on — both of
    which arrive on the payload (engine/characteristic_defining.py). The four
    functions this replaced each hardcoded one card's answer to those two
    questions.

    Types are read through ``has_type``/``is_creature`` (CR 613 layer 4), so an
    animated land counts as a creature and a land turned into a Swamp counts as
    a Swamp — the printed type line is not the authority on either.
    """
    # "**During your turn**, …are each equal to 2 plus the number of Swamps
    # your opponents control. **During turns other than yours**, …are each 2."
    # (Angry Mob.) A question about the turn rather than about a battlefield, so
    # it is asked before the scope is read: on any other player's turn the
    # sentence names no set at all and the printed constant is the whole answer.
    if payload.get("only_during") == "your_turn":
        active = game.players[game.active_player_index] if game.players else None
        if active is not player:
            return int(payload.get("otherwise_value", 0))
    scope = payload.get("scope", "you")
    if scope == "all":
        battlefields = [p.battlefield for p in game.players]
    elif scope == "opponents":
        # "…the number of artifacts **your opponents** control" (Gaea's
        # Avenger). Whose battlefield is already payload, so this is one more
        # value for it rather than a second counter.
        battlefields = [p.battlefield for p in game.players if p is not player]
    elif scope == "chosen_player":
        # "…the number of creatures **the chosen player** controls" (Lost Order
        # of Jarkeld). The seat this permanent chose as it entered (CR 614.1c),
        # read off the permanent rather than off the game — the record belongs
        # to one object, the way `chosen_number` two branches up does.
        #
        # Through the control seam, not `player.battlefield`: the sentence says
        # "controls", and a creature the chosen player has *stolen* is one they
        # control. The scopes beside this one predate the seam and are ratcheted
        # where they are; a new one has no reason to join them.
        #
        # No record is a permanent still entering — the choice is part of
        # arriving — and an empty board is the honest answer for it: the printed
        # constant alone, which is what the card is worth until the seat exists.
        seat = permanent.metadata.get("chosen_player_index")
        battlefields = (
            [list(game.controlled_by(seat))]
            if isinstance(seat, int) and 0 <= seat < len(game.players)
            else []
        )
    elif (
        scope == "defender_when_attacking"
        and permanent.attacking
        and permanent.defending_player_index is not None
    ):
        battlefields = [game.players[permanent.defending_player_index].battlefield]
    else:
        battlefields = [player.battlefield]

    what = payload.get("count")
    if what == "sacrificed_as_entered":
        # Wood Elemental: the Forests were sacrificed as this creature entered
        # and are cards in a graveyard now (CR 400.7, CR 613.1), so there is
        # nothing on a battlefield left to tally. The number was recorded where
        # it happened; this reads it back.
        return int(permanent.metadata.get("sacrificed_as_entered") or 0)
    if what in ("sacrificed_total_power", "sacrificed_total_toughness"):
        # Dracoplasm: the summed power (or toughness) of what its controller
        # gave up as it entered. Recorded where the sacrifice happened, because
        # by now those creatures are cards in a graveyard with no computed
        # characteristics at all (CR 613.1) — the same reason Wood Elemental's
        # tally rides the permanent rather than being recounted here.
        return int(permanent.metadata.get(str(what)) or 0)
    if what == LIFE_PAID_AS_ENTERED:
        # Nameless Race: the life was paid as the creature entered (CR 614.1c)
        # and nothing on a board records it, so it rides the permanent the same
        # way Wood Elemental's sacrifice count does.
        return int(permanent.metadata.get(LIFE_PAID_AS_ENTERED) or 0)
    if what == "chosen_number":
        # Shapeshifter: the value is a number a player chose, not a tally of
        # anything, so it answers before the battlefield loop rather than inside
        # it. It is on this payload anyway because what it *defines* is a
        # characteristic-defining P/T (CR 604.3) like every other entry here.
        return int(permanent.metadata.get("chosen_number") or 0)
    excluded = payload.get("exclude_type")
    land_type = payload.get("land_type")
    card_type = payload.get("card_type")
    # "the number of **snow** lands you control" (Drift of the Dead). A
    # supertype (CR 205.4), computed through layer 4 like every other
    # characteristic — so a land Arcum's Weathervane thawed stops counting and
    # one it froze starts, which is the whole point of the Weathervane.
    supertype = payload.get("supertype")
    # "…the number of **nonbasic** lands the chosen player controls" (Skyshroud
    # War Beast). The mirror of the line above, in the same layer and asked the
    # same way: an effect that *made* a land basic stops it counting, and one
    # that took the supertype away starts it. Its own key rather than a sign on
    # ``supertype``, because a card printing both narrowings ("nonbasic snow
    # lands") is then this template rather than a new one.
    excluded_supertype = payload.get("exclude_supertype")
    # "the number of **other** Rats on the battlefield" (Pestilence Rats): the
    # source itself is excluded by identity (CR 109.5), never by name — a
    # second Rat with the same name is a different permanent.
    subtype = payload.get("subtype")
    exclude_self = bool(payload.get("exclude_self"))
    # "the number of **tapped** lands the chosen player controls" (Pallimud). A
    # state rather than a characteristic, so it is a key of its own and is asked
    # of each permanent here — dropped, Pallimud's power would be every land the
    # chosen player has rather than the ones they have spent.
    tapped = payload.get("tapped")

    total = 0
    for battlefield in battlefields:
        for perm in battlefield:
            if supertype is not None and not perm.has_supertype(supertype):
                continue
            if (
                excluded_supertype is not None
                and perm.has_supertype(excluded_supertype)
            ):
                continue
            if tapped is not None and bool(perm.tapped) is not bool(tapped):
                continue
            if exclude_self and perm is permanent:
                continue
            if what == "land":
                # No ``land_type`` on the payload is the unnarrowed printing —
                # "the number of lands you control" — so the question is the
                # card type alone. Asked through ``has_type`` like the subtype
                # branch beside it, so a permanent that *became* a land counts
                # and one that stopped being one does not (CR 613 layer 4).
                total += perm.has_type(str(land_type) if land_type else "land")
            elif what == "creature":
                if perm.is_creature and not (excluded and perm.has_type(str(excluded))):
                    total += 1
            elif what == "same_name":
                # "creatures named ~": an object's *name* is a copiable value
                # (CR 707.2, layer 1), so a Clone copying Plague Rats both is
                # named Plague Rats and counts the others. The printed face
                # answered here for a year and missed every copy.
                total += perm.effective_card.name == permanent.effective_card.name
            elif what == "card_type":
                total += bool(card_type and perm.has_type(str(card_type)))
            elif what == "subtype":
                # Through `has_type` like every other type question here, so a
                # creature *given* the subtype counts (CR 613 layer 4).
                total += bool(subtype and perm.has_type(str(subtype)))
    # "…equal to **1 plus** the number of …" (Gaea's Avenger). A printed
    # constant added to the tally, on the payload because it is part of the
    # sentence rather than part of the counting — a card printed "2 plus" is
    # the same template.
    return total + int(payload.get("plus", 0))


def _add_static_pt(permanent: Permanent, power: int, toughness: int) -> None:
    """Contribute a layer-7c modification to the *derived* buff channel.

    ``derived_buff_power``/``derived_buff_toughness`` are cleared and rebuilt
    from scratch by ``_refresh_dynamic_creatures`` on every recompute, so a
    contribution here needs no record of itself. That is the difference from
    adding to ``power_bonus``, which persists: anything written there has to be
    subtracted again later, and a subtraction that does not exactly match its
    addition compounds on every refresh — and CR 611.3a means the refresh runs
    constantly. Aspect of Wolf shipped exactly that bug; see
    tests/regressions/test_batch17.py.

    The channel is cleared by the same function that rebuilds it. Splitting
    those across two functions is how this class of bug gets back in: whoever
    calls only the rebuilding half then doubles every contribution.
    """
    if power:
        permanent.metadata["derived_buff_power"] = (
            int(permanent.metadata.get("derived_buff_power", 0)) + power
        )
    if toughness:
        permanent.metadata["derived_buff_toughness"] = (
            int(permanent.metadata.get("derived_buff_toughness", 0)) + toughness
        )


def _apply_conditional_bonus(
    permanent: Permanent, metadata_key: str, active: bool, power: int, toughness: int
) -> None:
    """A "gets +N/+N as long as <condition>" static ability
    (conditional_land_bonus, conditional_untapped_bonus, …).

    Derived, not accumulated: when the condition holds the bonus is contributed
    to the recomputed channel, and when it stops holding nothing has to be
    undone — the next recompute simply does not contribute it.
    """
    if active:
        _add_static_pt(permanent, power, toughness)
    else:
        permanent.metadata[metadata_key] = (0, 0)


class DynamicCreaturesMixin:
    def _refresh_zone_copies(self) -> None:
        """Re-point every continuous copy whose source is a position in a zone.

        "As long as the top card of your graveyard is a creature card, this
        creature has the full text of that card…" (Volrath's Shapeshifter,
        ``engine/zone_copies.py``.) CR 613 layer 1a, and the only layer-1 effect
        in the pool with no moment to be recorded at — the answer changes when a
        card is discarded, when a creature dies, when a spell finishes
        resolving, with no trigger and no event.

        So what is rebuilt here is only **where to look**: which seat's zone,
        and what the card there has to be. ``copies.copiable_card`` resolves it
        on every read, so a graveyard that changes between two recomputes is
        seen immediately rather than at the next pass — which matters, because
        nothing in this engine refreshes on a card entering a graveyard.

        The static is read off ``recorded_copiable_card`` and never off
        ``effective_card``. The copy replaces the permanent's rules text, so
        reading the effective card would lose the ability that generated the
        copy and drop it on the next pass — the effect would flicker on and off
        one recompute at a time. CR 613.6 says the same thing from the rules
        side: an effect that has started to apply keeps applying even if the
        ability generating it is removed.
        """
        for perm in self.all_permanents():
            copies.clear_derived_copy_sources(perm)
        for seat, perm in self.permanents_with_controller():
            program = compile_card_oracle(copies.recorded_copiable_card(perm))
            for instr in program.instructions:
                if instr.kind != ZONE_TOP_COPY_KIND:
                    continue
                copies.set_derived_copy_source(
                    perm,
                    # CR 109.5: "your" in an ability is its controller, which is
                    # what makes this a *refresh* and not a one-time arming —
                    # a permanent that changes controller starts reading the new
                    # controller's graveyard on the next recompute.
                    owner=self.players[seat],
                    spec=zone_top_copy_from_payload(instr.payload),
                    key=instr.kind,
                )

    def _refresh_mana_spending(self) -> None:
        """CR 106.6: what each seat may currently spend a unit of mana as.

        Rebuilt from the board every pass rather than stamped as a source
        enters, which is what a static ability is (CR 611.3a) and what the two
        booleans below were not. They stay as *views* over the derived list
        because every payment site asks them by name; what they cannot express
        -- a permission narrowed to one colour, and the restriction that comes
        with it -- is the third field.
        """
        from ..mana_spending import permissions_for_seat

        for seat, player in enumerate(self.players):
            permissions = permissions_for_seat(self, seat)
            player.mana_spending_permissions = permissions
            player.spends_mana_as_any_color = any(
                not p.fungible_colors and not p.as_colors for p in permissions
            )
            player.can_spend_white_as_red = any(
                p.may_pay("W", "R") and p.fungible_colors for p in permissions
            )
            # Only when *every* permission the seat holds carries it: a second
            # source granting an unrestricted permission lifts the narrowing,
            # because CR 106.6 permissions are additive and a restriction on one
            # of them cannot reach the mana another one freed.
            player.mana_restricted_to_colorless_others = bool(permissions) and all(
                p.others_colorless_only for p in permissions
            )
            # Which permissions the two booleans above cannot describe: a
            # narrowed source with an unnarrowed destination (Celestial Dawn),
            # a narrowed pair other than white-as-red (a card the pool has not
            # printed yet but the table already reads), or any restriction. The
            # boards the engine handled before keep the routes they had, which
            # is what makes this a widening rather than a rewrite.
            player.mana_spending_is_general = any(
                permission.others_colorless_only
                or (
                    permission.fungible_colors
                    and permission.as_colors != ("R",)
                )
                or (
                    permission.fungible_colors not in ((), ("W",))
                )
                for permission in permissions
            )

    def _refresh_aspect_of_wolf(self) -> None:
        """Aspect of Wolf: enchanted creature gets +X/+Y where X/Y are half the
        aura controller's count of a basic land type (down/up). Recomputed
        continuously so it tracks lands entering and leaving (CR 611.3a).

        **The land type is read out of the Aura's own effective text**, not
        fixed at "forest". Magical Hack rewrites that word (CR 612.1), and
        matching a printed sentence while counting a hardcoded type is the same
        mistake made twice: after the change the sentence stopped matching at
        all, so the bonus quietly became +0/+0 rather than following the word.

        Contributed to the derived buff channel, so several Aspects on one
        creature simply add up and nothing needs unwinding.
        """
        for controller in self.players:
            controlled = list(self.controlled_by(controller))
            for aura in controlled:
                match = _HALF_LAND_COUNT_RE.search(
                    aura.effective_card.oracle_text.lower()
                )
                if match is None:
                    continue
                land_type = singular_land_type(match.group(1))
                if land_type not in BASIC_LAND_WORDS:
                    continue
                creature = aura.metadata.get("attached_to")
                if creature is None or not creature.is_creature:
                    continue
                lands = sum(
                    1
                    for perm in controlled
                    if perm.has_type("land") and perm.has_type(land_type)
                )
                _add_static_pt(creature, lands // 2, (lands + 1) // 2)

    def _refresh_board_counted_penalties(self) -> None:
        """Snowblind: "Enchanted creature gets -X/-Y", where X counts a class of
        permanent on **whichever** board the combat points at, and Y is clamped
        so the creature is never killed by it.

        Derived rather than remembered, like every other Aura contribution: X
        changes when a land enters and when the creature attacks, and neither
        of those is a moment anything could hook. CR 611.3a says a continuous
        effect applies whenever its criteria are met, and "the number of snow
        lands defending player controls" is a criterion re-read on every pass.

        **The toughness the clamp reads is the toughness without this effect.**
        The derived channel this contributes to was cleared at the top of the
        refresh, so ``effective_toughness`` here is base P/T plus every other
        layer — which is the reading the printed clamp means: "toughness minus
        1" is what makes Snowblind unable to kill, and reading a toughness this
        effect had already reduced would make the clamp chase itself.
        """
        from ..aura_grants import aura_board_counted_penalty
        from ..aura_attachment import auras_attached_to
        from ..subject_filters import subject_matches

        for seat, host in self.permanents_with_controller():
            for aura in auras_attached_to(host):
                payload = aura_board_counted_penalty(
                    aura.effective_card.oracle_text
                )
                if payload is None:
                    continue
                # CR 506.2: the board is the *defending player's* while the
                # creature is attacking, and its own controller's otherwise.
                # The defending seat is stamped on the attacker at declaration,
                # so this is a read rather than a search — and an attacker
                # whose defender is gone falls back to its controller, which is
                # the sentence's own "otherwise".
                counted_seat = seat
                if host.attacking and isinstance(host.defending_player_index, int):
                    counted_seat = host.defending_player_index
                if not (0 <= counted_seat < len(self.players)):
                    continue
                described = payload["filter"]
                amount = sum(
                    1
                    for perm in self.controlled_by(counted_seat)
                    if subject_matches(self, perm, described)
                )
                if amount <= 0:
                    continue
                clamp = max(0, host.effective_toughness - 1)
                _add_static_pt(host, -amount, -min(amount, clamp))

    def _refresh_linked_tapped_pumps(self, all_permanents) -> None:
        """"…gets +2/-2 for as long as this artifact remains tapped."
        (Ashnod's Battle Gear, Tawnos's Weaponry.)

        The boost is recorded on the *source* by the handler and contributed
        here, into the same derived channel every other conditional layer-7c
        effect uses — so it is rebuilt from the board on every recompute and
        ends the instant the source stops being tapped. Nothing schedules its
        removal, which is the point: an effect that ends on a *condition*
        rather than at a step boundary has no moment anyone could hook, and a
        remembered delta would have to be unwound at one.

        Three ways the contribution simply stops, none of them special-cased:
        the source untaps, the source leaves the battlefield (its record leaves
        with it), or the pumped permanent leaves (its id no longer resolves).
        """
        from ..handlers._filters import permanent_matches_filter
        from ..handlers.pump import PUMP_WHILE_TAPPED_KEY

        for source in all_permanents:
            record = source.metadata.get(PUMP_WHILE_TAPPED_KEY)
            if not record or not source.tapped:
                continue
            power = int(record.get("power", 0))
            toughness = int(record.get("toughness", 0))
            # One record, two subjects, and exactly one of them per record: a
            # chosen permanent (`target_id`, Ashnod's Battle Gear) or a board
            # scan (`filter`, Thran Weaponry). Asserted rather than guessed at,
            # because a shared channel whose readers disagree about its shape is
            # this repo's most-repeated defect — settle the arity and the
            # element type in the same breath as the second producer.
            if "filter" in record:
                assert "target_id" not in record, (
                    "a linked-tapped pump names one permanent or a class, "
                    f"never both: {record!r}"
                )
                described = record.get("filter") or {}
                for perm in all_permanents:
                    if not perm.is_creature:
                        continue
                    if described and not permanent_matches_filter(perm, described):
                        continue
                    _add_static_pt(perm, power, toughness)
                continue
            target = self.permanent_by_id(record.get("target_id"))
            if target is None:
                continue
            _add_static_pt(target, power, toughness)

    def _refresh_dynamic_creatures(self) -> None:
        all_permanents = list(self.all_permanents())
        # **Layer 1 before everything else** (CR 613.1a): a permanent whose
        # copiable values are read out of a zone has to be re-pointed before any
        # line below reads its `effective_card`, because that read is what folds
        # the copy in. Everything from here down — the land animations, the
        # global statics, the lord buffs — starts from what layer 1 leaves.
        self._refresh_zone_copies()
        # Clear the derived layer-7c channel this method rebuilds. Everything
        # contributed below is a *conditional* continuous effect, so it is
        # recomputed from the current board rather than adjusted incrementally.
        for perm in all_permanents:
            perm.metadata.pop("derived_buff_power", None)
            perm.metadata.pop("derived_buff_toughness", None)
        self._refresh_linked_tapped_pumps(all_permanents)
        # Layer 4 before layer 7: a characteristic-defining P/T that counts
        # creatures must see the lands this pass animates, not last pass's.
        # One call, because layer 4 is one application: the land-type statics,
        # the supertype removals, the land animators and the type-changing
        # global statics are ordered against each other (CR 613.7, 613.8) and
        # were three refreshes that each read what the one before had left.
        self._refresh_global_statics(all_permanents)
        # A landwalk **named by the board** — "For each basic land type among
        # lands you control, this creature has landwalk of that type."
        # (Magnigoth Treefolk.) Layer 6 reading layer 4, so it is rebuilt here,
        # *behind* the two layer-4 refreshes above and not in
        # ``_recalculate_lord_buffs`` beside the other derived keyword grants:
        # ``_recompute_continuous_effects`` runs that pass first, and a Blood
        # Moon arriving would have its Mountains read one recompute late.
        # Its own channel for the same reason — the derived-grant channel is
        # that pass's to clear, and a grant written from here would be wiped
        # whenever it ran alone. Rebuilt whole every time (CR 611.3a), so a
        # Forest that leaves takes forestwalk with it and there is nothing to
        # find and undo; ``layer_bridge.collect_ability_effects`` reads it.
        for lw_seat, lw_perm in self.permanents_with_controller():
            named_walks = board_named_landwalks(self, lw_seat, lw_perm)
            if named_walks:
                lw_perm.metadata[BOARD_NAMED_LANDWALKS] = named_walks
            else:
                lw_perm.metadata.pop(BOARD_NAMED_LANDWALKS, None)
        self._refresh_mana_spending()
        self._refresh_aspect_of_wolf()
        # After the other 7c contributions, because its clamp reads the
        # toughness the creature has *without* it — see the method.
        self._refresh_board_counted_penalties()

        # "Attacking creatures you control get +X/+Y" (Orcish Oriflamme) used to
        # be counted here, into a channel of its own, because the lord-buff
        # consumer could not express a state qualifier. It is an ordinary lord
        # buff now — engine/lord_buffs.py derives the qualifier and
        # _recalculate_lord_buffs contributes it — so there is nothing here to
        # keep in step with it.
        for seat, permanent in self.permanents_with_controller():
            player = self.players[seat]
            prog = compile_card_oracle(permanent.effective_card)
            instr_kinds = {instr.kind for instr in prog.instructions}

            # Characteristic-defining P/T (CR 604.3, layer 7a). The
            # instruction says what to count; there is one counter, and a
            # new CDA card adds no code here at all.
            dynamic_pt = next(
                (i for i in prog.instructions if i.kind == "dynamic_pt_count"), None
            )
            # A derived channel, cleared here and rebuilt just below: a
            # creature that no longer has the ability (a Nightmare under
            # Humility — ``prog`` is the effective card's) has no 7a value,
            # where the count it was last given used to stand for ever.
            clear_cda_pt(permanent)
            if dynamic_pt is not None:
                spec = dynamic_pt.payload.get("count_spec")
                # A CDA counting *cards in a zone* asks the shared evaluator, not
                # the battlefield tally: a card in a graveyard has no computed
                # characteristics (CR 613.1), so it is a different question of a
                # different matcher — and the same evaluator the computed 7c
                # bonus below uses, so one phrase means one number wherever it
                # is printed.
                # The permanent being refreshed *is* the source of its own
                # characteristic-defining ability, and it is handed over here
                # for the reason the computed 7c bonus below hands it over: a
                # spec may name a relation to it ("other Rats on the
                # battlefield", "Auras attached to it") rather than only a set
                # of characteristics, and an evaluator with no source answers
                # such a spec by counting all of the set or none of it. Both
                # are silent, and a CDA is recomputed continuously (CR 604.3),
                # so either would be wrong every time anything read the
                # creature.
                value = (
                    evaluate_count(
                        self, player, spec, source=permanent, exclude=permanent
                    )
                    if spec is not None
                    else _count_dynamic_pt(self, player, permanent, dynamic_pt.payload)
                )
                # "…**power** is equal to" leaves the printed toughness alone
                # (Kinetic Augur is */4). ``set_cda_pt`` takes None for "leave
                # this one tracking whatever else applies", which is exactly the
                # difference and is why it is not two instruction kinds.
                # "…and its toughness is equal to 7 minus that number"
                # (Shapeshifter). The second half is derived from the same
                # value rather than counted again, which is what makes the
                # printed total a payload number instead of a second template.
                # "…power becomes the total power of those creatures **and its
                # toughness becomes their total toughness**" (Dracoplasm). The
                # one shape whose two halves are two different numbers, so the
                # second is counted rather than derived from the first — every
                # branch below reads one value and computes the other from it.
                toughness_count = dynamic_pt.payload.get("toughness_count")
                complement = dynamic_pt.payload.get("complement")
                if toughness_count is not None:
                    set_cda_pt(permanent, value, _count_dynamic_pt(
                        self, player, permanent,
                        {**dynamic_pt.payload, "count": toughness_count},
                    ))
                elif complement is not None:
                    set_cda_pt(permanent, value, max(0, int(complement) - value))
                elif dynamic_pt.payload.get("defines") == "power":
                    # "…and its toughness is equal to **that number plus 1**"
                    # (Lhurgoyf, printed */1+*). Derived from the same value
                    # rather than counted again — the same reason Shapeshifter's
                    # complement is one number and not a second template — so a
                    # card printed "plus 2" is this row with a different
                    # payload. Absent, the printed toughness stands (Kinetic
                    # Augur is */4), which is what the None says.
                    bonus = dynamic_pt.payload.get("toughness_plus")
                    set_cda_pt(
                        permanent,
                        value,
                        None if bonus is None else value + int(bonus),
                    )
                elif dynamic_pt.payload.get("defines") == "toughness":
                    # "…**toughness** is equal to the number of Forests you
                    # control" (People of the Woods, a 0/*). The mirror of the
                    # branch above and the same None: the printed power keeps
                    # tracking whatever else applies to it.
                    set_cda_pt(permanent, None, value)
                else:
                    set_cda_pt(permanent, value, value)

            # A layer-7c bonus whose *size* is computed (Carrion Grub). The
            # spec is the one every reader of a computed amount shares, so the
            # amount here and the amount a where-clause resolves at resolution
            # are the same function of the same board — which is the whole
            # reason this needed no counter of its own.
            for bonus in prog.instructions:
                if bonus.kind != "dynamic_pt_bonus":
                    continue
                # "**Enchanted** creature gets +1/+1 for each other creature
                # you control." (Vampirism.) The Aura's sentence about its
                # host, on the same instruction and the same count as the one a
                # creature prints about itself — only the permanent the delta
                # lands on differs, and that is what `subject` says. The same
                # split `conditional_static` makes a few lines down, spelled
                # the same way so one key means one thing across both.
                #
                # The recipient is the **live** record (CR 611.3b: a continuous
                # effect applies only while the Aura is attached).
                recipient = permanent
                if bonus.payload.get("subject") == "attached":
                    recipient = attached_host(self, permanent, last_known=False)
                    if recipient is None:
                        continue
                # "…for each black permanent your opponents control **as long
                # as there are seven or more cards in your graveyard**"
                # (Nantuko Blightcutter). The criteria a conditional static's
                # fixed delta is gated on, asked by the same evaluator with the
                # same seat — false, and the bonus is not added this pass.
                gate = bonus.payload.get("condition")
                if gate and not conditional_static_holds(self, seat, permanent, gate):
                    continue
                # The permanent being refreshed *is* the source of its own
                # static ability, which is what lets a spec name a relation to
                # it ("Auras attached to it") rather than only a set of
                # characteristics - and CR 109.5 makes "you" its controller.
                #
                # "…for each **other** <noun>" leaves out the permanent the
                # count is taken for. Nothing was handed over to leave out, so
                # the word was read and dropped: Squirrel Mob was 3/3 alone
                # and Mogg Squad 2/2. Both the source and the recipient,
                # because an Aura prints the word about either - "each other
                # creature" (Vampirism, Bravado) can only mean other than the
                # enchanted creature, "each other enchantment" (Ancestral
                # Mask) other than the Aura - and for a creature's own line
                # the two are one permanent.
                value = evaluate_count(
                    self, player, bonus.payload.get("x_from_count") or {},
                    source=permanent, exclude=(permanent, recipient),
                )
                _add_static_pt(
                    recipient,
                    resolve_amount(bonus.payload.get("power", 0), value),
                    resolve_amount(bonus.payload.get("toughness", 0), value),
                )

            land_bonus_instr = next(
                (i for i in prog.instructions if i.kind == "conditional_land_bonus"), None
            )
            if land_bonus_instr is not None:
                land_type = land_bonus_instr.payload["land_type"]
                has_land = any(
                    perm.has_type("land") and perm.has_type(land_type)
                    for perm in self.controlled_by(seat)
                )
                _apply_conditional_bonus(
                    permanent, "conditional_land_bonus", has_land,
                    int(land_bonus_instr.payload["power"]), int(land_bonus_instr.payload["toughness"]),
                )

            untapped_bonus_instr = next(
                (i for i in prog.instructions if i.kind == "conditional_untapped_bonus"), None
            )
            if untapped_bonus_instr is not None:
                _apply_conditional_bonus(
                    permanent, "conditional_untapped_bonus", not permanent.tapped,
                    int(untapped_bonus_instr.payload["power"]), int(untapped_bonus_instr.payload["toughness"]),
                )

            # The general conditional static (engine/static_bonuses.py): its
            # P/T half contributes to this same derived 7c channel. The
            # keyword half lives with the derived grants in
            # _recalculate_lord_buffs — that pass owns their clear/rebuild —
            # and "can't be blocked" is asked at block-legality time.
            for cs in prog.instructions:
                if cs.kind != "conditional_static":
                    continue
                cs_power = int(cs.payload.get("power", 0))
                cs_toughness = int(cs.payload.get("toughness", 0))
                # "…gets +2/+1 as long as it's black. **Otherwise**, it gets
                # -1/-2." (Phyrexian Boon.) The complement arm, on the same
                # instruction as the arm it complements — so the criteria are
                # evaluated **once** and the answer selects which delta applies,
                # rather than two instructions asking two questions that can
                # both come back true.
                #
                # Read before the "no delta" skip below, because an arm that is
                # 0/0 while its complement is not is still a live effect: the
                # skip is for a keyword-only conditional static, which has no
                # delta on either side.
                other_power = int(cs.payload.get("otherwise_power", 0))
                other_toughness = int(cs.payload.get("otherwise_toughness", 0))
                if not (cs_power or cs_toughness or other_power or other_toughness):
                    continue
                holds = conditional_static_holds(
                    self, seat, permanent, cs.payload.get("condition") or {}
                )
                if not holds and (other_power or other_toughness):
                    # The other arm is not "the absence of this one": it is a
                    # contribution in its own right, applied by the same channel
                    # and cleared by the same rebuild.
                    cs_power, cs_toughness, holds = other_power, other_toughness, True
                # "**Enchanted** creature gets +2/+2 as long as an opponent
                # controls a black permanent" (Ice Age's five Scarabs). The
                # sentence an Aura prints about its host, on the same
                # instruction and the same evaluator as the one a creature
                # prints about itself — only the permanent the delta lands on
                # differs, and that is what `subject` says.
                #
                # The seat stays the Aura's controller (CR 109.5: the ability is
                # the Aura's), so "an opponent" is measured from whoever
                # controls the Aura rather than from whoever controls the
                # creature it is stuck to. Those are different players whenever
                # the Aura is on an opponent's creature, which is exactly what
                # these five cards are for.
                recipient = permanent
                if cs.payload.get("subject") == "attached":
                    # The **live** record: CR 611.3b, a continuous effect
                    # applies only while it is attached, and an Equipment that
                    # unattaches stays on the battlefield with the last-known
                    # host still recorded on it.
                    recipient = attached_host(self, permanent, last_known=False)
                    if recipient is None:
                        continue
                _apply_conditional_bonus(
                    recipient, "conditional_static", holds, cs_power, cs_toughness
                )

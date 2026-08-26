from __future__ import annotations

from dataclasses import dataclass, field

# Re-exported for backwards compatibility with external importers.
from .game_types import SimulationResult, StackItem
from .models import CardDefinition, PlayerState
from .mixins import (
    GameEndingMixin,
    TurnManagementMixin,
    PhaseStepsMixin,
    SpellCastingMixin,
    AbilityActivationMixin,
    StackResolutionMixin,
    PendingChoicesMixin,
    OracleInstructionsMixin,
    PermanentStateMixin,
    EffectsMixin,
    GameHelpersMixin,
)
from .ante import AnteMixin
from .commander import CommanderMixin
from .legality import LegalityMixin
# Per-phase and per-step turn-structure logic (CR 500–514) lives in engine.phases,
# one mixin class per phase/step. See engine/phases/__init__.py for the taxonomy.
from .phases import (
    BeginningPhaseMixin,
    UntapStepMixin,
    UpkeepStepMixin,
    DrawStepMixin,
    PrecombatMainPhaseMixin,
    CombatPhaseMixin,
    BeginningOfCombatStepMixin,
    DeclareAttackersStepMixin,
    DeclareBlockersStepMixin,
    CombatDamageStepMixin,
    EndOfCombatStepMixin,
    PostcombatMainPhaseMixin,
    EndingPhaseMixin,
    EndStepMixin,
    CleanupStepMixin,
)



@dataclass
class Game(
    GameEndingMixin,
    # Phases and steps (CR 500–514)
    BeginningPhaseMixin,
    UntapStepMixin,
    UpkeepStepMixin,
    DrawStepMixin,
    PrecombatMainPhaseMixin,
    CombatPhaseMixin,
    BeginningOfCombatStepMixin,
    DeclareAttackersStepMixin,
    DeclareBlockersStepMixin,
    CombatDamageStepMixin,
    EndOfCombatStepMixin,
    PostcombatMainPhaseMixin,
    EndingPhaseMixin,
    EndStepMixin,
    CleanupStepMixin,
    # Cross-cutting flow and supporting machinery
    TurnManagementMixin,
    PhaseStepsMixin,
    # The stack (CR 405): one mixin per stage of an object's life on it.
    # See engine/mixins/stack/__init__.py.
    SpellCastingMixin,
    AbilityActivationMixin,
    StackResolutionMixin,
    PendingChoicesMixin,
    OracleInstructionsMixin,
    PermanentStateMixin,
    EffectsMixin,
    GameHelpersMixin,
    LegalityMixin,
    AnteMixin,
    CommanderMixin,
):
    players: list[PlayerState]
    enforce_mana_costs: bool = False
    # CR 903.1 / 903.12a: which Commander variant this game is, or None for an
    # ordinary game. "commander" or "brawl" (engine/commander.VARIANTS); every
    # seam in engine/commander.py is inert while this is None, so a normal duel
    # is unaffected. Set by the web layer from the host's format choice.
    commander_variant: str | None = None
    # CR 407.1: playing for ante is an optional variation, off unless the host
    # turns it on. While False no card is anted at the start of the game, the
    # winner takes nothing, and cards carrying "Remove this card from your deck
    # before playing if you're not playing for ante" are barred from decks,
    # sideboards, and from being brought in from outside the game (CR 407.3).
    playing_for_ante: bool = False
    # Set once the ante has been handed to the winner (CR 407.2), so the
    # transfer happens exactly once however often the end of the game is
    # re-evaluated.
    ante_awarded: bool = False
    turn: int = 1
    current_phase: str = "main"
    current_turn_phase: str = "precombat_main"
    current_step: str = "precombat_main"
    active_player_index: int = 0
    lands_played_this_turn: dict[int, int] = field(default_factory=dict)
    stack: list[StackItem] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    # CR 701.20: cards revealed to all players, as a structured record beside
    # the prose log so the UI can show the revealed faces. Each entry is
    # ``{"id": n, "seat": i, "cards": [names]}`` appended by ``record_reveal``;
    # ids are monotonic and only the newest few entries are kept — this is an
    # event feed a client diffs, not a history.
    reveal_events: list[dict] = field(default_factory=list)
    reveal_event_seq: int = 0
    extra_turns: dict[int, int] = field(default_factory=dict)
    extra_turn_queue: list[int] = field(default_factory=list)
    current_turn_is_extra: bool = False
    # 500.7: extra turns are *inserted* after the current turn; the normal
    # turn rotation must continue from the last non-extra turn, not from the
    # player who happens to be taking an extra turn. Anchored here.
    normal_rotation_anchor: int = 0
    extra_phases_after: dict[str, list[str]] = field(default_factory=dict)
    extra_steps_after: dict[str, list[str]] = field(default_factory=dict)
    custom_phase_steps: dict[str, tuple[str, ...]] = field(default_factory=dict)
    skip_turn_counts: dict[int, int] = field(default_factory=dict)
    skip_phase_counts: dict[str, int] = field(default_factory=dict)
    skip_step_counts: dict[str, int] = field(default_factory=dict)
    combat_damage_prevented_until_eot: bool = False
    # "Prevent all combat damage that would be dealt this turn **to Dogs you
    # control**." (Pack Leader.) The scoped twin of the flag above, and a list
    # rather than a flag because each entry carries the noun phrase it protects
    # and the seat "you control" means.
    #
    # A turn-wide record and not a per-recipient ``Shield``, which is the
    # decision worth writing down: the printed set is re-read when damage would
    # be dealt, so a Dog that arrives *after* this resolves is protected too. A
    # shield handed to each Dog present at resolution would silently be a
    # narrower card. Same lifetime as the flag above, cleared in the same two
    # places.
    combat_damage_prevented_for: list = field(default_factory=list)
    combat_attackers: dict[int, int] = field(default_factory=dict)
    # CR 508.1b: attackers sent at a planeswalker rather than at its controller.
    # Maps attacker battlefield idx (active player's seat) -> the attacked
    # planeswalker's ``permanent_id``. The id, not a slot: the walker sits on
    # the *defender's* battlefield, whose slots renumber independently, and a
    # walker that leaves combat mid-step must resolve to nothing (CR 510.1b)
    # rather than to whatever slid into its place. ``combat_attackers`` still
    # carries the same attacker's defending player (the walker's controller),
    # which is what blocks, restrictions and CR 508.5 read.
    combat_attacked_planeswalkers: dict[int, int] = field(default_factory=dict)
    # Maps defending player index -> {blocker battlefield idx -> attacker battlefield
    # idx list}. Nested by defender because CR 802 (attack multiple players) lets 2+
    # defenders declare blocks in the same combat, and blocker battlefield indices
    # are only unambiguous within one defender's own battlefield. A blocker almost
    # always blocks one attacker; a creature that "can block an additional creature"
    # (Two-Headed Giant of Foriys) may block more (CR 509.1b).
    combat_blockers: dict[int, dict[int, list[int]]] = field(default_factory=dict)
    # Populated only when exactly one distinct defending player exists this combat
    # (2-player games, or a 3+ player combat where a single opponent was attacked).
    # The authoritative source for "who is under attack" with 2+ defenders is
    # ``combat_attackers`` (attacker idx -> defender idx); see
    # ``CombatPhaseMixin.combat_defending_players()``.
    combat_defending_player_index: int | None = None
    # CR 802.4: defending players still under attack this combat that have already
    # declared blocks (or been auto-skipped for having no legal blocks) during the
    # declare-blockers step's APNAP-ordered declarations.
    combat_blockers_declared_by: set[int] = field(default_factory=set)
    combat_damage_resolved: bool = False
    combat_first_strike_done: bool = False
    combat_attackers_locked: bool = False
    combat_blockers_locked: bool = False
    # Banding (CR 702.22). ``combat_bands`` holds the attacking bands declared this
    # combat (each a list of attacker indices). ``combat_band_blocks`` maps an
    # attacker index to the blocker indices that block it via band propagation
    # (702.22h). ``combat_banding_damage`` is the defending player's pre-committed
    # damage assignment for attackers blocked by a creature with banding (702.22j).
    combat_bands: list[list[int]] = field(default_factory=list)
    combat_band_blocks: dict[int, list[int]] = field(default_factory=dict)
    combat_banding_damage: dict[int, dict[int, int]] = field(default_factory=dict)
    # ``combat_multiblock_damage`` is the defending player's pre-committed division
    # of a blocker's combat damage among the 2+ attackers it blocks (CR 510.1d,
    # Two-Headed Giant of Foriys). Maps blocker index -> {attacker index: damage}.
    combat_multiblock_damage: dict[int, dict[int, int]] = field(default_factory=dict)
    # Camouflage: set to the turn number when cast. While it matches the current
    # turn, the defending player's blocks are assigned randomly by pile (CR — the
    # spell replaces the declare-blockers step) instead of chosen.
    camouflage_active_turn: int | None = None
    # Raging River (CR 702 left/right division). When active, each defending player
    # splits their non-flying creatures into a "left" and a "right" pile, and the
    # attacking player labels each attacker; an attacker may then only be blocked by
    # flyers or creatures in the matching pile. ``combat_defender_piles`` maps a
    # defender creature index → "left"/"right"; ``combat_attacker_piles`` maps an
    # attacker index → "left"/"right".
    combat_left_right_active: bool = False
    combat_left_right_defender_index: int | None = None
    # Set once each player commits their piles, so the web prompt stops re-showing
    # (otherwise the seeded default piles make the prompt look perpetually pending).
    combat_left_right_defender_locked: bool = False
    combat_left_right_attacker_locked: bool = False
    combat_defender_piles: dict[int, str] = field(default_factory=dict)
    combat_attacker_piles: dict[int, str] = field(default_factory=dict)
    priority_player_index: int | None = None
    priority_pass_count: int = 0
    untapped_lands_at_turn_start: dict[int, int] = field(default_factory=dict)
    # Every decision a seat owes part-way through a spell, an ability or a turn
    # step — a library search, a discard, Balance's removals, Power Sink's
    # payment, Word of Command's borrowed card. One queue rather than one field
    # per card: ``kind`` selects the spec in engine/pending_choices.py that says
    # how to answer it, what a non-interactive seat does instead, and how the web
    # layer renders and gates it. The ``pending_<name>`` views the web layer and
    # the tests read are derived from this list (engine/mixins/stack/choices.py).
    pending_choices: list = field(default_factory=list)
    # CR 616.1e answers, keyed by (event kind, choosing seat): the order a player
    # picked for the effects contending over one event. Written when an
    # effect_order prompt is answered and read by the re-run of that event, which
    # is how the process reaches the same round again and applies the chosen
    # effect. Popped once the event gets through, so a later contention asks
    # afresh rather than inheriting a stale answer.
    effect_order_answers: dict = field(default_factory=dict)
    # Set while an event is waiting on a decision, so the loop that was running
    # it stops instead of carrying on past a step that has not happened. Cleared
    # when the answer arrives. See engine/resumption.py.
    effect_suspended: bool = False
    # The stack object currently resolving, on the interactive path only. Every
    # prompt armed while it is set records it (``_stack_item``), and the object
    # stays on the stack until nothing it armed is queued any more — CR 608.2:
    # a resolution is not over until its last instruction is done, and CR 117.3b:
    # nobody receives priority until then. Kept live across an *answer* as well,
    # because answering one prompt is how the next one of the same resolution is
    # armed (Sanctum of All's "you may …" arms the search it offered).
    resolving_stack_item: "StackItem | None" = None
    # What each interrupted loop still owes, innermost last. Empty except while a
    # decision is outstanding; a leftover entry means a loop recorded a
    # continuation nobody came back for.
    resume_stack: list = field(default_factory=list)
    # Seats controlled by a human, set by the web layer each action. Empty in
    # headless/AI play, so forced sacrifices there resolve inline without a prompt.
    interactive_seats: set[int] = field(default_factory=set)
    # Replacement effects suspended on a player's decision — the optional or
    # choose-one ones (Library of Leng's discard destination, Aladdin's Lamp's
    # look-at-the-top-X, Ring of Ma'rûf's outside-the-game card). Each entry is a
    # ReplacementChoice; the affected object sits in no zone until
    # resolve_replacement_choice answers it. Only armed for seats in
    # ``interactive_seats`` — every other seat takes the choice's default at
    # once, through the same resolver. See engine/replacement_choices.py.
    pending_replacement_choices: list = field(default_factory=list)
    # 610.3: tracks creatures exiled "until end of turn" — (owner_player_index, card)
    exile_until_eot: list[tuple[int, CardDefinition]] = field(default_factory=list)
    # 104.4: True when the game ends in a draw for all players
    is_draw: bool = False
    # 700.4-style turn tracking: creatures that died this turn (e.g. Scavenging Ghoul)
    creatures_died_this_turn: int = 0
    # The same turn, counting only the ones that were cards (Gadrak). A token
    # dying is a real creature death, so this is a strictly smaller number and a
    # genuinely different question — kept as its own tally for the reason the
    # per-seat one beside it is: a reader that wants one and gets the other is
    # wrong by however many tokens died, silently.
    nontoken_creatures_died_this_turn: int = 0
    # How many turns each seat has *begun*, incremented by
    # ``begin_turn_bookkeeping`` (both the headless flow and the web flow run
    # through it exactly once per turn). The per-seat ordinal is what "your
    # last turn" and "its controller's next turn" compare against: a global
    # turn number cannot say whether a seat took a turn in between (extra
    # turns break the alternation), where ordinal arithmetic can. Read by
    # ``can_attack`` for Giant Turtle's record and Wall of Dust's stamp.
    seat_turn_counts: dict[int, int] = field(default_factory=dict)
    # Whether each seat cast a spell or put a nontoken permanent onto the
    # battlefield during their most recent *own* turn (Arboria, CR 506.3).
    # Folded once at each turn boundary from the two per-turn records below —
    # a seat with no entry has not finished an own turn yet, which reads as
    # "did neither", the answer Arboria's first turns want.
    last_own_turn_activity: dict[int, bool] = field(default_factory=dict)
    # Nontoken permanents that entered the battlefield under each seat this
    # turn, recorded at the one entry path (`_put_permanent_onto_battlefield`)
    # and reset each turn. The seat a permanent *enters under* stands in for
    # "the player who put it there": a land drop, a resolving permanent spell
    # and a reanimation all agree, and an effect that puts a card onto the
    # battlefield under another player's control is the one reading this
    # approximates.
    nontoken_permanents_entered_this_turn: dict[int, int] = field(default_factory=dict)
    # "Rest of the game" delayed upkeep triggers left behind by a permanent that
    # has died (Cyclopean Tomb): each entry is {"controller_index", "lands"} where
    # ``lands`` are the still-mired Permanents whose mire counters must be removed
    # one-per-upkeep at the beginning of that controller's upkeeps. Populated via
    # the ON_LEAVE_BATTLEFIELD card hook and drained in resolve_upkeep.
    mire_cleanup_obligations: list = field(default_factory=list)
    # Delayed token creation from a "dies" trigger whose token appears at the
    # beginning of the next end step (Rukh Egg), by which time the source
    # permanent is long gone — each entry is {"controller_index", "name",
    # "power", "toughness", "type_line", "colors", "keywords"}. Populated in
    # _permanent_to_graveyard, drained in resolve_end_step.
    pending_end_step_tokens: list = field(default_factory=list)
    # CR 601.2i / 603.3b: triggers that fired while a spell was being cast or an
    # ability activated, waiting for that object to finish being put on the
    # stack so they can go on the stack *above* it. None means "not casting" —
    # every other announcement goes straight onto the stack, which is why this
    # is a nullable buffer rather than a queue that is always drained.
    # See ``StackResolutionMixin.deferring_triggers``.
    deferred_triggers: list | None = None
    # CR 603.7 delayed triggered abilities created by a resolving spell or
    # ability ("Whenever one or more nontoken creatures attack this turn, …" —
    # Basri Ket's −2; "At the beginning of your next main phase, …" — Mana
    # Drain). Each entry is a ``delayed_triggers.DelayedTrigger``; that module
    # holds the events that have a fire site, the one routine that fires them
    # and the expiry the cleanup step runs.
    delayed_triggers: list = field(default_factory=list)
    # CR 601.3 permissions to cast/play from outside the hand ("you may play
    # cards exiled this way", "you may cast target … from your graveyard") and
    # cost waivers ("without paying their mana costs"). CastPermission entries
    # (engine/cast_permissions.py); turn-scoped ones are swept at cleanup.
    cast_permissions: list = field(default_factory=list)
    # "Creatures without flying can't block this turn." (Destructive
    # Tampering's second mode) — one-shot blanket blocking restrictions,
    # CR 509.1b. Each entry: {"filter": {type_filter, with_keywords,
    # without_keywords}, "source_name"}. Read by _can_block_attacker (which is
    # also what the legality enumerator asks), swept at cleanup.
    blocking_restrictions_until_eot: list = field(default_factory=list)
    # How many permanents each seat has had put into their hand from the
    # battlefield this turn — the history Barrin, Tolarian Archmage's end-step
    # intervening-if reads. Keyed by owner seat (the hand the card landed in),
    # fed by the bounce paths, reset with the other per-turn counters.
    permanents_to_hand_this_turn: dict = field(default_factory=dict)
    # Nafs Asp: "that player loses N life at the beginning of their next draw
    # step unless they pay {cost} before that draw step." Each entry is
    # {"player_index", "amount", "cost", "source_name"}. Populated by the
    # arm_draw_step_life_loss_unless_pay handler, resolved in resolve_draw_step.
    pending_draw_step_life_loss: list = field(default_factory=list)
    # Aladdin's Lamp: an armed "the next time you would draw a card this turn,
    # instead look at the top X..." replacement per player. Shape:
    # {player_index: X}. Consumed by the next draw that player makes this turn;
    # cleared at end of turn.
    lamp_draw_replacements: dict = field(default_factory=dict)
    # Ring of Ma'rûf: seats whose next draw this turn is replaced by "put a card
    # you own from outside the game into your hand". Consumed by that player's
    # next draw; cleared at end of turn alongside lamp_draw_replacements.
    outside_game_draw_replacements: set = field(default_factory=set)
    # Both of the above are *armed state*, like a prevention shield. The
    # suspended draw itself waits on pending_replacement_choices.
    # Seats whose "whenever you draw your second card each turn" triggers have
    # fired this turn (Mystic Skyfish) — the condition fires once per turn, so
    # the sweep that watches ``cards_drawn_this_turn`` needs to remember who it
    # already announced. Reset with the other per-turn counters.
    second_draw_fired_this_turn: set = field(default_factory=set)
    # How many of each seat's draws the per-draw sweep has already announced
    # (Lorescale Coatl, Burlfist Oak). A count rather than a flag, because
    # "whenever you draw a card" fires once per card (CR 121.2) where the
    # second-card trigger above fires once per turn. Reset with it.
    draws_announced_this_turn: dict = field(default_factory=dict)
    # Global statics whose source has left but whose effect continues
    # until end of turn (Titania's Song). Cleared at cleanup.
    lingering_global_statics: list = field(default_factory=list)
    _global_static_sources_last: list = field(default_factory=list)
    # CR 109.5's answer for an object that is not on the battlefield: the seat
    # whose spell or ability is resolving right now, innermost first. A
    # permanent's controller is a layer-2 question the control seam answers, but
    # what a damage path carries for a *spell* is its ``CardDefinition`` — the
    # card as printed, shared by every copy in every deck and controlled by
    # nobody — so "a source **you** control" is unanswerable from the object
    # alone. Pushed around the one dispatch point (`_execute_oracle_instruction`)
    # and read by ``damage_events.damage_source_seat``; a list because a
    # `sequence` or a replacement nests resolutions inside one another. Empty
    # outside a resolution, which is the honest answer for a turn-based action.
    resolving_seats: list = field(default_factory=list)
    # The chosen targets of the object whose instruction is running, by stable
    # permanent id, pushed and popped beside ``resolving_seats``. Same reason
    # that one exists: "spells that target it" (Bronze Horse) is a question
    # about the *resolving object*, and the damage paths receive a bare
    # ``CardDefinition`` that records nothing about what was chosen. Reading it
    # off the stack is not an option -- the object is popped before its
    # instructions run -- so it is recorded for the duration at the one
    # dispatch point that knows it.
    resolving_targets: list = field(default_factory=list)

    def __post_init__(self) -> None:
        # Preserve legacy external phase naming while internally tracking phase/step.
        self._set_phase_and_step(self.current_turn_phase, self.current_step)
        if self._receives_priority(self.current_step):
            self.start_priority_window(self.active_player_index)
        self.check_state_based_actions()



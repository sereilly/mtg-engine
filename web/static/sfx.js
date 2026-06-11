const SFX = (() => {
  let _vol = parseFloat(localStorage.getItem('sfx_vol') ?? '0.7');
  let _muted = localStorage.getItem('sfx_muted') === 'true';

  // Throttle phase-change sounds to avoid rapid-fire spam during auto-pass
  let _lastPhaseSoundAt = 0;
  const PHASE_THROTTLE_MS = 300;

  function _encode(path) {
    return '/sfx/' + path.split('/').map(encodeURIComponent).join('/');
  }

  function _play(path) {
    if (_muted) return;
    try {
      const a = new Audio(_encode(path));
      a.volume = _vol;
      a.play().catch(() => {});
    } catch (_) {}
  }

  function _pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }

  // Derive primary color from a mana cost string like "{2}{G}{G}"
  function _colorOf(manaCost) {
    if (!manaCost || typeof manaCost !== 'string') return 'colorless';
    const found = [...new Set((manaCost.toUpperCase().match(/\{([WUBRG])\}/g) || []).map(t => t[1]))];
    if (found.length === 0) return 'colorless';
    if (found.length > 1) return 'multi';
    return found[0].toLowerCase();
  }

  function _isStrong(card) {
    return typeof card?.power === 'number' && card.power >= 4;
  }

  // Play the appropriate creature-enter sound based on color and power
  function _playCreatureEnter(card) {
    if (!card || typeof card === 'string') { _play('events/Creature_Summon.wav'); return; }
    const type = String(card.type || '').toLowerCase();
    if (type.includes('token') || card.is_token) { _play('card_ux/Token_Summon.wav'); return; }
    const strong = _isStrong(card);
    switch (_colorOf(card.mana_cost)) {
      case 'u': _play(strong ? 'events/Blue_Enter_StrongCreature.wav.wav' : 'events/Blue_Enter_WeakCreature.wav'); break;
      case 'b': _play(strong ? 'events/Dark_Enter_Strong.wav' : 'events/Dark_Enter_Weak.wav'); break;
      case 'g': _play(strong ? 'events/Green_Enter_Strong.wav' : 'events/Green_Enter_Weak.wav'); break;
      case 'r': _play(strong ? 'events/Red_enter_StrongCreature.wav' : 'events/Red_Enter_WeakCreature.wav'); break;
      case 'w': _play(strong ? 'events/White_Enter_StrongCreature.wav' : 'events/White_Enter_WeakCreature.wav'); break;
      default: _play('events/Creature_Summon.wav'); break;
    }
  }

  // Play the appropriate attack sound based on the attacker's color
  function _playAttackSound(card) {
    if (!card || typeof card === 'string') { _play('events/Attack_Colorless.wav'); return; }
    const sounds = { u: 'events/Blue_Attack.wav', b: 'events/Dark_Attack.wav', g: 'events/Green_Attack.wav',
                     r: 'events/Red_Attack.wav', w: 'events/White_Attack.wav',
                     multi: 'events/Attack_Multicolored.wav', colorless: 'events/Attack_Colorless.wav' };
    _play(sounds[_colorOf(card.mana_cost)] ?? sounds.colorless);
  }

  // Find the first creature that newly appeared on any battlefield between two states.
  // Assumes new permanents are appended (index >= prev length).
  function _findNewCreature(prev, next) {
    for (const s of [0, 1]) {
      const pb = prev.players?.[s]?.battlefield ?? [];
      const nb = next.players?.[s]?.battlefield ?? [];
      if (nb.length > pb.length) {
        for (let i = pb.length; i < nb.length; i++) {
          const c = nb[i];
          if (c && String(c.type || '').toLowerCase().includes('creature')) return c;
        }
      }
    }
    return null;
  }

  // ─── Public: called from renderLifePill in app.js ──────────────────────────
  function onLifeChange(seatIndex, prevLife, newLife, viewerSeat) {
    if (!Number.isFinite(prevLife) || !Number.isFinite(newLife) || newLife === prevLife) return;
    if (newLife > prevLife) {
      _play(seatIndex === viewerSeat ? 'ui/Lifegain_UI.wav' : 'ui/Lifegain_Opponent.wav');
    } else {
      _play(seatIndex === viewerSeat ? 'events/Direct_Attack_Player.wav' : 'events/Direct_Attack_Rival.wav');
    }
  }

  // ─── Public: called from renderState in app.js (before currentState = state) ─
  function onStateChange(prev, next, viewerSeat) {
    if (!next) return;

    // Pregame ended → game is starting
    if (prev?.pregame && !next.pregame) {
      _play('events/GameStart.wav');
      return;
    }
    if (!prev || next.pregame) return;

    // Game just ended
    if (!prev.winner && next.winner) {
      setTimeout(() => _play(_pick([
        'card_ux/Game_Loser_Cards_Being_Destroyed (1).wav',
        'card_ux/Game_Loser_Cards_Being_Destroyed (2).wav',
        'card_ux/Game_Loser_Cards_Being_Destroyed (3).wav',
      ])), 400);
    }

    _handlePhaseChange(prev, next, viewerSeat);

    const prevLen = Array.isArray(prev.log) ? prev.log.length : 0;
    const newEntries = Array.isArray(next.log) ? next.log.slice(prevLen) : [];
    if (newEntries.length > 0) _handleLogEntries(newEntries, prev, next, viewerSeat);

    // Stack went from non-empty to empty → resolution finished
    const prevStackLen = Array.isArray(prev.stack) ? prev.stack.length : 0;
    const nextStackLen = Array.isArray(next.stack) ? next.stack.length : 0;
    if (prevStackLen > 0 && nextStackLen === 0) {
      setTimeout(() => _play('events/Stack_End.wav'), 350);
    }
  }

  function _stepKey(state) {
    if (!state) return '';
    if (state.current_step) return state.current_step;
    if (state.current_turn_phase === 'precombat_main') return 'precombat_main';
    if (state.current_turn_phase === 'postcombat_main') return 'postcombat_main';
    return state.current_phase || '';
  }

  function _handlePhaseChange(prev, next, viewerSeat) {
    const prevKey = _stepKey(prev);
    const nextKey = _stepKey(next);
    if (prevKey === nextKey) return;

    const now = Date.now();
    if (now - _lastPhaseSoundAt < PHASE_THROTTLE_MS) return;
    _lastPhaseSoundAt = now;

    const isSelf = next.current_turn === viewerSeat;

    // Turn changed → play next-turn sting instead of a phase sound
    if (prev.turn_number !== next.turn_number) {
      _play('events/Phase_NextTurn.wav');
      return;
    }

    // Avoid double battle sound on beginning_of_combat → declare_attackers
    if (nextKey === 'declare_attackers' && prevKey === 'beginning_of_combat') return;

    const phaseMap = {
      draw:               isSelf ? 'events/Phase_Draw.wav'    : 'events/Phase_Draw_Opponent.wav',
      precombat_main:     isSelf ? 'events/Phase_Main1.wav'   : 'events/Phase_Main1_Opponent.wav',
      beginning_of_combat:isSelf ? 'events/Phase_Battle.wav'  : 'events/Phase_Battle_Opponent.wav',
      declare_attackers:  isSelf ? 'events/Phase_Battle.wav'  : 'events/Phase_Battle_Opponent.wav',
      postcombat_main:    isSelf ? 'events/Phase_Main2.wav'   : 'events/Phase_Main2_Opponent.wav',
      end:                isSelf ? 'events/Phase_End.wav'     : 'events/Phase_End_Opponent.wav',
    };
    const snd = phaseMap[nextKey];
    if (snd) _play(snd);
  }

  function _handleLogEntries(entries, prev, next, viewerSeat) {
    let graveyardPlayed = false;
    let stackResolvePlayed = false;
    let stackEnterPlayed = false;
    let summonPlayed = false;
    let tapCount = 0;

    for (const entry of entries) {
      const s = String(entry).toLowerCase();

      // ── Card draw ────────────────────────────────────────────────────────────
      const drawM = s.match(/drew (\d+) card/);
      if (drawM) {
        const n = Math.min(parseInt(drawM[1]) || 1, 5);
        const drawFiles = ['card_ux/Card_Draw (1).wav', 'card_ux/Card_Draw (2).wav', 'card_ux/Card_Draw (3).wav'];
        for (let i = 0; i < n; i++) setTimeout(() => _play(_pick(drawFiles)), i * 120);
        continue;
      }

      // ── Tapping for mana ─────────────────────────────────────────────────────
      if (s.includes('tapped') && !s.includes('untapped') && !s.includes('stasis') && !s.includes('all lands') && !s.includes('tapped all')) {
        const delay = tapCount * 110;
        tapCount++;
        setTimeout(() => _play(_pick(['card_ux/Card_Tap (1).wav', 'card_ux/Card_Tap (2).wav', 'card_ux/Card_Tap (3).wav'])), delay);
        continue;
      }

      // ── Stack enters ─────────────────────────────────────────────────────────
      if (!stackEnterPlayed && (s.endsWith('added to stack') || s.includes('ability added to stack'))) {
        _play('events/Card_Enter_Stack.wav');
        stackEnterPlayed = true;
        continue;
      }

      // ── Stack resolves (exclude "Resolved combat damage" — handled by canvas) ─
      if (!stackResolvePlayed && s.includes('resolved') &&
          !s.includes('combat damage') && !s.includes('first strike')) {
        _play(_pick(['events/Stack_Resolve_Card01.wav', 'events/Stack_Resolve_Card02.wav',
                     'events/Stack_Resolve_Card03.wav', 'events/Stack_Resolve_Card04.wav']));
        stackResolvePlayed = true;
        continue;
      }

      // ── Permanent enters battlefield ─────────────────────────────────────────
      if (!summonPlayed && s.includes('onto battlefield')) {
        const newCreature = _findNewCreature(prev, next);
        if (newCreature) {
          _playCreatureEnter(newCreature);
        } else {
          _play('events/Creature_Summon.wav');
        }
        summonPlayed = true;
        continue;
      }

      // ── Token enters ─────────────────────────────────────────────────────────
      if (s.includes('token') && !summonPlayed) {
        _play('card_ux/Token_Summon.wav');
        summonPlayed = true;
        continue;
      }

      // ── Reanimated / returned from graveyard ─────────────────────────────────
      if (s.includes('reanimated') || s.includes('returned creature from graveyard')) {
        _play('card_ux/Card_Leave_Graveyard.wav');
        continue;
      }

      // ── Declare attackers ────────────────────────────────────────────────────
      if (s.includes('declared') && s.includes('attacker')) {
        _play('events/Flag_As_Attacker.wav');
        const combat = next.combat;
        if (combat && Array.isArray(combat.attackers) && combat.attackers.length > 0) {
          const bf = next.players?.[next.current_turn]?.battlefield ?? [];
          const firstAtt = combat.attackers[0];
          const perm = firstAtt ? bf[firstAtt.attacker_index] : null;
          if (perm) setTimeout(() => _playAttackSound(perm), 200);
        }
        continue;
      }

      // ── Declare blockers ─────────────────────────────────────────────────────
      if (s.includes('declared') && s.includes('blocker')) {
        _play('events/Attack_Blocked.wav');
        continue;
      }

      // ── Sacrifice ────────────────────────────────────────────────────────────
      if (s.includes('sacrificed') || (s.includes('sacrifice') && !s.includes('search'))) {
        _play('events/Sacrifice.wav');
        graveyardPlayed = true; // card also went to graveyard; skip the separate sound
        continue;
      }

      // ── Goes to graveyard ────────────────────────────────────────────────────
      if (!graveyardPlayed && (
        s.includes('died from') || s.includes('died (') ||
        s.includes('put into graveyard') || s.includes('went to graveyard') ||
        s.includes('moved to graveyard') || s.includes("graveyard (") ||
        s.includes('no legal target and was put into') || s.includes('resolved and moved to graveyard')
      )) {
        _play('card_ux/Card_Enter_Graveyard.wav');
        graveyardPlayed = true;
        continue;
      }

      // ── Exile ────────────────────────────────────────────────────────────────
      if (s.includes('exiled') && !s.includes('returned from exile')) {
        _play('card_ux/Exile_Enter.wav');
        continue;
      }

      // ── Return from exile ────────────────────────────────────────────────────
      if (s.includes('returned from exile') || (s.includes('returned') && s.includes('exile') && s.includes("battlefield"))) {
        _play('card_ux/Exile_Exit.wav');
        continue;
      }

      // ── Coin flip ────────────────────────────────────────────────────────────
      if (s.includes('coin flip')) {
        _play('events/Coin_Flip.wav');
        if (s.includes('wins')) setTimeout(() => _play('events/Coin_Success.wav'), 700);
        continue;
      }

      // ── Counters ─────────────────────────────────────────────────────────────
      if (s.includes('counter') && (s.includes('+1') || s.includes('-1') || s.includes('placed') || s.includes('put') || s.includes('added'))) {
        _play('card_ux/Counter_Placed.wav');
        continue;
      }
      if (s.includes('counter') && (s.includes('removed') || s.includes('cancelled'))) {
        _play('card_ux/Counter_Removed.wav');
        continue;
      }

      // ── Reveal / look at top of library ──────────────────────────────────────
      if (s.includes('looking at the top') || (s.includes('reveal') && s.includes('card'))) {
        _play('events/RevealCard_TopOfDeck.wav');
        continue;
      }

      // ── Search library ───────────────────────────────────────────────────────
      if (s.includes('searching') && s.includes('library')) {
        _play('card_ux/ViewDeck.wav');
        continue;
      }
    }
  }

  // ─── Volume / mute ─────────────────────────────────────────────────────────
  function setVolume(v) {
    _vol = Math.max(0, Math.min(1, parseFloat(v) || 0));
    localStorage.setItem('sfx_vol', String(_vol));
  }
  function setMuted(m) {
    _muted = !!m;
    localStorage.setItem('sfx_muted', String(_muted));
  }
  function getVolume() { return _vol; }
  function isMuted() { return _muted; }

  // ─── UI sounds ─────────────────────────────────────────────────────────────
  function onLogOpen()     { _play('ui/Log_Open.wav'); }
  function onLogClose()    { _play('ui/Log_Close.wav'); }
  function onMenuDecide()  { _play('ui/Menu_Decide.wav'); }
  function onMenuCancel()  { _play('ui/Menu_Cancel.wav'); }
  function onMenuToggle(on){ _play(on ? 'ui/Menu_Toggle.wav' : 'ui/Menu_Untoggle.wav'); }

  return {
    onStateChange, onLifeChange,
    onLogOpen, onLogClose, onMenuDecide, onMenuCancel, onMenuToggle,
    setVolume, setMuted, getVolume, isMuted,
  };
})();

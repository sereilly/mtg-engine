// Background music player. Picks a random track when the game starts and loops
// through the available songs. Volume / mute persist in localStorage and are
// driven by the music slider next to the sound-effects controls.
const MUSIC = (() => {
  let _vol = parseFloat(localStorage.getItem('music_vol') ?? '0.4');
  let _muted = localStorage.getItem('music_muted') === 'true';

  let _tracks = [];        // list of "/music/Name.mp3" URLs
  let _audio = null;       // current HTMLAudioElement
  let _started = false;    // a track has been chosen/begun for this session
  let _tracksLoaded = false;

  function _encode(url) {
    // url is like "/music/Some Name.mp3" — encode the filename segment only.
    const i = url.lastIndexOf('/');
    return url.slice(0, i + 1) + encodeURIComponent(url.slice(i + 1));
  }

  async function _loadTracks() {
    if (_tracksLoaded) return _tracks;
    _tracksLoaded = true;
    try {
      const resp = await fetch('/api/music');
      const data = await resp.json();
      if (Array.isArray(data.tracks)) _tracks = data.tracks;
    } catch (_) {
      _tracks = [];
    }
    return _tracks;
  }

  function _playUrl(url) {
    try {
      _audio = new Audio(_encode(url));
      _audio.volume = _muted ? 0 : _vol;
      _audio.muted = _muted;
      // When a track ends, move to a different random track for variety.
      _audio.addEventListener('ended', _next);
      _audio.play().catch(() => {});
    } catch (_) {}
  }

  function _pick(excludeUrl) {
    if (_tracks.length === 0) return null;
    if (_tracks.length === 1) return _tracks[0];
    let url = excludeUrl;
    while (url === excludeUrl) url = _tracks[Math.floor(Math.random() * _tracks.length)];
    return url;
  }

  function _next() {
    const prev = _audio ? _audio.src : null;
    const url = _pick(prev && decodeURIComponent(prev));
    if (url) _playUrl(url);
  }

  // ─── Public ────────────────────────────────────────────────────────────────

  // Begin playback with a random track. Safe to call repeatedly — only the
  // first call per session starts a song. Must be triggered from a user gesture
  // (game start) so the browser allows audio autoplay.
  async function start() {
    if (_started) return;
    await _loadTracks();
    if (_tracks.length === 0) return;
    _started = true;
    const url = _pick(null);
    if (url) _playUrl(url);
  }

  function setVolume(v) {
    _vol = Math.max(0, Math.min(1, parseFloat(v) || 0));
    localStorage.setItem('music_vol', String(_vol));
    if (_audio && !_muted) _audio.volume = _vol;
  }
  function setMuted(m) {
    _muted = !!m;
    localStorage.setItem('music_muted', String(_muted));
    if (_audio) {
      _audio.muted = _muted;
      _audio.volume = _muted ? 0 : _vol;
    }
  }
  function getVolume() { return _vol; }
  function isMuted() { return _muted; }

  return { start, setVolume, setMuted, getVolume, isMuted };
})();
